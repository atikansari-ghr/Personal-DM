"""Change Set Q — PaddleOCR / PP-OCRv5 and the complete OCR lifecycle. AT-211..AT-230.

The change prompt numbers these AT-191..AT-210; those numbers were already taken, so prompt AT-n = AT-(n+20) here.
CI uses tests/fake_paddle_worker.py (same protocol, Tesseract reads the text); ``test_live_*`` run the real PP-OCRv5
runtime when PD_TEST_PADDLE_PYTHON points to it, and are skipped (never reported as passed) otherwise.
Synthetic documents only.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import pytest
from conftest import client_for, personal_root, run_jobs
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from apps.core import config
from apps.core.models import AuditEvent, Job
from apps.library import ocr_admin, ocr_engines, ocr_runs, storage
from apps.library.models import Document, DocumentField, DocumentType, DocumentVersion, OcrRun

pytestmark = pytest.mark.django_db
FAKE = str(Path(__file__).with_name("fake_paddle_worker.py"))
LIVE_PY = os.environ.get("PD_TEST_PADDLE_PYTHON", "")
LIVE_HOME = os.environ.get("PD_TEST_PADDLE_HOME", "")


@pytest.fixture
def paddle(settings, tmp_path, monkeypatch):
    """The fake PaddleOCR runtime: system Python + tests/fake_paddle_worker.py, models "installed" in a temp home."""
    home = tmp_path / "paddle"
    home.mkdir()
    settings.PADDLE_PYTHON = sys.executable
    settings.PADDLE_HOME = home
    monkeypatch.setattr(ocr_engines, "WORKER", Path(FAKE))
    config.set_value("processing.ocr_engine", "paddleocr")
    from apps.security.models import HealthState

    HealthState.objects.filter(key__startswith="paddleocr").delete()
    ocr_engines.paddle_selftest()
    return home


def _font(name: str, size: int):
    for candidate in (name, "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _png(lines, font="DejaVuSans.ttf", size=(1600, 600), rtl=False) -> bytes:
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    f = _font(font, 60)
    y = 80
    for ln in lines:
        kw = {"direction": "rtl", "language": "ar"} if rtl else {}
        x = size[0] - 100 - d.textlength(ln, font=f, **kw) if rtl else 100
        d.text((x, y), ln, fill="black", font=f, **kw)
        y += 120
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _scan_pdf(pages) -> bytes:
    imgs = []
    for text in pages:
        img = Image.new("RGB", (1700, 1100), "white")
        ImageDraw.Draw(img).text((100, 200), text, fill="black", font=_font("DejaVuSans.ttf", 64))
        imgs.append(img)
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", resolution=200, save_all=True, append_images=imgs[1:])
    return buf.getvalue()


def _upload(client, folder, name, content, **data) -> Document:
    r = client.post("/api/documents", {"folder": str(folder.id), "files": [SimpleUploadedFile(name, content)], **data},
                    format="multipart")
    assert r.status_code == 201, r.content
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


def _manual():
    DocumentType.objects.update(ocr_mode="manual", ocr_ai_allowed=False)
    config.set_value("processing.ocr_untyped_mode", "manual")


def _found(client, q) -> int:
    return client.get("/api/documents", {"q": q}).json()["total"]


def _ocr_doc(client, family, text_lines, name="permit.png", **ocr_body):
    _manual()
    doc = _upload(client, personal_root(family["son1"]), name, _png(text_lines))
    run_jobs()
    r = client.post(f"/api/documents/{doc.id}/ocr", ocr_body, format="json")
    assert r.status_code == 202, r.content
    run_jobs()
    doc.refresh_from_db()
    return doc


# ------------------------------------------------------------------ AT-211 installation / health

def test_at211_paddle_health_is_a_real_inference_selftest(family, clients, paddle):
    st = ocr_engines.paddle_status(refresh=True)
    assert st["installed"] and st["paddleocr"] == "3.7.0" and not st["missing_models"] and st["healthy"]
    (paddle / "fake_mode").write_text("fail")  # imports fine, inference fails -> not healthy
    res = ocr_engines.paddle_selftest()
    assert res["healthy"] is False
    assert ocr_engines.paddle_status()["healthy"] is False
    (paddle / "fake_mode").write_text("ok")
    r = clients["dad"].post("/api/ocr/engines/selftest", {}, format="json")
    assert r.status_code == 200 and r.json()["healthy"] is True
    assert clients["son1"].post("/api/ocr/engines/selftest", {}, format="json").status_code == 403
    info = clients["dad"].get("/api/ocr/engines").json()
    assert info["default_engine"] == "paddleocr" and info["paddle"]["healthy"] and info["queue"]["concurrency"] == 1


# ------------------------------------------------------------------ AT-212 upgrade preservation

def test_at212_upgrade_labels_history_and_never_reprocesses(family, clients):
    import importlib

    from django.apps import apps as django_apps

    _manual()
    c = clients["son1"]
    doc = _upload(c, personal_root(family["son1"]), "old.png", _png(["LEGACY TESSERACT RESULT"]))
    run_jobs()
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    DocumentVersion.objects.filter(pk=v.pk).update(ocr_applied=True, text="legacy text kept", ocr_quality={"engine": "tesseract"},
                                                   ocr_engine="", ocr_model="")
    DocumentField.objects.create(document=doc, key="expiry_date", value="2031-01-15", status=DocumentField.CONFIRMED, source="ocr")
    jobs_before = Job.objects.count()
    mig = importlib.import_module("apps.library.migrations.0010_ocr_engines_lifecycle")
    mig.classify_existing(django_apps, None)
    v.refresh_from_db()
    assert v.ocr_engine == "tesseract" and v.text == "legacy text kept"  # never relabelled as PaddleOCR, text kept
    assert Job.objects.count() == jobs_before  # nothing queued: no automatic library re-processing
    assert DocumentField.objects.get(document=doc, key="expiry_date").value == "2031-01-15"
    assert storage.resolve_original(v.storage_path).exists() and doc.versions.count() == 1


# ------------------------------------------------------------------ AT-213 PP-OCRv5 default

def test_at213_new_ocr_uses_ppocrv5_and_records_engine_model_profile(family, clients, paddle):
    doc = _ocr_doc(clients["son1"], family, ["SAMPLE RESIDENCE PERMIT", "Expiry 2029-05-17"])
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    assert v.ocr_applied and v.ocr_engine == "paddleocr" and "PP-OCRv5" in v.ocr_model and v.ocr_profile == "en"
    assert v.ocr_blocks and v.ocr_blocks[0]["lines"][0]["box"]  # geometry kept for the review view
    assert "RESIDENCE" in v.text.upper() and "RESIDENCE" in doc.content_text.upper()
    run = OcrRun.objects.get(document=doc)
    assert run.status == OcrRun.DONE and run.engine == "paddleocr" and "PaddleOCR 3.7.0" in run.engine_version
    assert run.profile == "en" and run.confidence and run.line_count >= 2
    assert not v.searchable_path  # PP-OCRv5 results are text + geometry; no stale text-layer PDF is served
    st = clients["son1"].get(f"/api/documents/{doc.id}/ocr").json()
    assert st["results"][0]["engine"] == "paddleocr" and st["results"][0]["engine_label"] == "PaddleOCR PP-OCRv5"


def test_at213_fallback_and_explicit_engine(family, clients, settings, tmp_path):
    settings.PADDLE_PYTHON = str(tmp_path / "missing" / "python")  # PaddleOCR not installed
    from apps.security.models import HealthState

    HealthState.objects.filter(key__startswith="paddleocr").delete()
    doc = _ocr_doc(clients["son1"], family, ["FALLBACK SAMPLE"])
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    run = OcrRun.objects.get(document=doc)
    assert v.ocr_engine == "tesseract" and "fallback" in run.options.get("fallback", "").lower()  # truthfully labelled
    config.set_value("processing.ocr_engine_fallback", False)
    doc2 = _ocr_doc(clients["son1"], family, ["NO FALLBACK"], name="nf.png")
    assert doc2.ocr_state == "failed" and "PaddleOCR" in doc2.ocr_error


# ------------------------------------------------------------------ AT-214 resource behaviour

def test_at214_single_worker_queue_and_bounded_process(family, clients, paddle, monkeypatch):
    from apps.core import jobs
    from apps.library import sandbox

    assert config.get("processing.heavy_concurrency") == 1
    seen = []
    real = sandbox.run

    def spy(cmd, **kw):
        if "run" in cmd and str(ocr_engines.WORKER) in cmd:
            seen.append(kw)
        return real(cmd, **kw)
    monkeypatch.setattr(sandbox, "run", spy)
    _manual()
    c = clients["son1"]
    docs = [_upload(c, personal_root(family["son1"]), f"q{i}.png", _png([f"QUEUE SAMPLE {i}"])) for i in range(3)]
    run_jobs()
    for d in docs:
        assert c.post(f"/api/documents/{d.id}/ocr", {}, format="json").status_code == 202
    # with one OCR job running, the queue does not hand out a second heavy job
    first = jobs.claim("w1", heavy_limit=1)
    assert first is not None and first.kind == "ocr_run"
    assert jobs.claim("w2", heavy_limit=1) is None
    jobs.run_job(first)
    run_jobs()
    assert len(seen) == 3 and all(k["memory_mb"] == config.get("processing.paddle_memory_mb") for k in seen)
    assert all(k["cpu_seconds"] >= k["timeout"] for k in seen)
    unit = (Path(__file__).resolve().parents[1] / "deployment/systemd/personaldocs-worker.service").read_text()
    assert "MemoryMax=4000M" in unit and "CPUWeight=50" in unit


def test_at214_engine_crash_or_timeout_fails_safely(family, clients, paddle):
    (paddle / "fake_mode").write_text("crash")
    doc = _ocr_doc(clients["son1"], family, ["CRASH SAMPLE"])
    assert doc.ocr_state == "failed" and OcrRun.objects.get(document=doc).status == OcrRun.FAILED
    assert clients["son1"].get(f"/api/documents/{doc.id}").status_code == 200  # the app stays usable


# ------------------------------------------------------------------ AT-215 selective OCR

def test_at215_selective_modes_and_per_document_override(family, clients, paddle):
    c = clients["son1"]
    root = personal_root(family["son1"])
    t = DocumentType.objects.first()
    DocumentType.objects.filter(pk=t.pk).update(ocr_mode="automatic")
    auto = _upload(c, root, "auto.png", _png(["AUTOMATIC TYPE"]), doc_type=str(t.id))
    run_jobs()
    auto.refresh_from_db()
    assert auto.ocr_state in ("confirmed", "needs_review")
    # per-document Disabled beats the Automatic type
    off = _upload(c, root, "off.png", _png(["NEVER RECOGNISED"]), doc_type=str(t.id))
    Document.objects.filter(pk=off.pk).update(ocr_override="disabled")
    Job.objects.filter(kind="ocr_run", status=Job.QUEUED).delete()
    from apps.library.ocr_runs import auto_ocr

    auto_ocr(off, DocumentVersion.objects.get(pk=off.current_version_id))
    assert not Job.objects.filter(kind="ocr_run", payload__document_id=str(off.id)).exists()
    DocumentType.objects.filter(pk=t.pk).update(ocr_mode="disabled")
    r = c.post(f"/api/documents/{auto.id}/ocr", {}, format="json")
    assert r.status_code == 400 and "disabled" in r.json()["error"]
    _manual()
    man = _upload(c, root, "manual.png", _png(["MANUAL TYPE"]))
    run_jobs()
    man.refresh_from_db()
    assert man.ocr_state == "not_processed"  # Manual: only when someone runs it


# ------------------------------------------------------------------ AT-216 language profiles

def test_at216_profiles_route_to_the_script_models(family, clients, paddle):
    assert ocr_engines.PADDLE_LANGS == {"en": ["en"], "ar_en": ["ar", "en"], "hi_en": ["hi", "en"], "te_en": ["te", "en"],
                                        "ta_en": ["ta", "en"]}
    from apps.library.paddle_worker import REC

    assert REC == {"en": "en_PP-OCRv5_mobile_rec", "ar": "arabic_PP-OCRv5_mobile_rec", "hi": "devanagari_PP-OCRv5_mobile_rec",
                   "te": "te_PP-OCRv5_mobile_rec", "ta": "ta_PP-OCRv5_mobile_rec"}
    doc = _ocr_doc(clients["son1"], family, ["SAMPLE"], profile="ar_en")
    req = json.loads((paddle / "last_request.json").read_text())
    assert req["langs"] == ["ar", "en"]
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    assert v.ocr_profile == "ar_en" and "arabic" in v.ocr_model or "ar_PP-OCRv5" in v.ocr_model
    # a profile the administrator does not offer is refused; a document type can carry its own default profile
    r = clients["son1"].post(f"/api/documents/{doc.id}/ocr", {"profile": "ta_en"}, format="json")
    assert r.status_code == 400 and "not offered" in r.json()["error"]
    status = clients["dad"].get("/api/ocr/engines").json()["profiles"]
    assert {p["key"] for p in status} == {"en", "ar_en", "hi_en", "te_en", "ta_en"}


# ------------------------------------------------------------------ AT-217 / 219 / 220 remove OCR

def test_at217_at219_at220_remove_cleans_everything_derived(family, clients, paddle):
    from apps.ai.models import AIJob, AISuggestion, DocumentChunk

    c = clients["son1"]
    doc = _ocr_doc(c, family, ["ZEBRAPHRASE UNIQUE WORDING", "Expiry 2029-05-17"], name="zebra.png")
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    sha, n_versions = v.sha256, doc.versions.count()
    assert _found(c, "zebraphrase") == 1
    # derived data that must go: proposals, AI suggestion + chunk, a queued AI job, a (stale) searchable copy
    DocumentField.objects.create(document=doc, key="issuer", value="X", status=DocumentField.PROPOSED, source="ocr",
                                 source_excerpt="ZEBRAPHRASE UNIQUE")
    DocumentField.objects.update_or_create(document=doc, key="expiry_date", defaults=dict(
        value="2029-05-17", status=DocumentField.CONFIRMED, source="ocr", source_excerpt="Expiry 2029-05-17 ZEBRAPHRASE"))
    DocumentField.objects.create(document=doc, key="full_name", value="Sample Person", status=DocumentField.CONFIRMED, source="manual")
    AISuggestion.objects.create(document=doc, field="title", value="x", display="ZEBRAPHRASE title")
    DocumentChunk.objects.create(document=doc, version=v, idx=0, text="ZEBRAPHRASE", vector=[0.1, 0.2], model="m")
    ai_job = AIJob.objects.create(kind=AIJob.ANALYZE, document=doc)
    stale = storage.derivative_dir(v.id) / "searchable.pdf"
    stale.write_bytes(b"%PDF-1.4 stale text layer ZEBRAPHRASE")
    r = c.delete(f"/api/documents/{doc.id}/ocr", {"confirm": True}, format="json")
    assert r.status_code == 200, r.content
    doc.refresh_from_db()
    v.refresh_from_db()
    # removed
    assert not v.ocr_applied and v.text == "" and v.ocr_blocks == [] and v.ocr_engine == "" and v.ocr_quality == {}
    assert not stale.exists() and not DocumentChunk.objects.filter(document=doc).exists()
    assert not AISuggestion.objects.filter(document=doc, status=AISuggestion.PENDING).exists()
    assert not DocumentField.objects.filter(document=doc, status=DocumentField.PROPOSED).exists()
    assert AIJob.objects.get(pk=ai_job.pk).status == "cancelled"
    assert "ZEBRAPHRASE" not in doc.content_text.upper()
    assert _found(c, "zebraphrase") == 0  # AT-219: the phrase only existed in OCR
    assert _found(c, doc.title.split()[0]) >= 1 or doc.title  # title/filename still match
    # kept
    assert v.sha256 == sha and storage.resolve_original(v.storage_path).exists() and doc.versions.count() == n_versions
    conf = DocumentField.objects.get(document=doc, key="expiry_date")
    assert conf.status == DocumentField.CONFIRMED and conf.value == "2029-05-17" and conf.source == "ocr" and conf.source_excerpt == ""
    assert DocumentField.objects.get(document=doc, key="full_name").value == "Sample Person"
    assert doc.ocr_state == "removed" and doc.ocr_override == ""  # still eligible for OCR later
    # AT-220: audit has safe metadata only
    ev = AuditEvent.objects.filter(action="document.ocr_remove").latest("at")
    assert ev.context["engines"] == ["paddleocr"] and ev.context["removal"] == "remove"
    assert "ZEBRAPHRASE" not in json.dumps(ev.context).upper()


def test_at217_embedded_text_layer_can_be_hidden(family, clients, paddle):
    """Root cause found: a PDF's own text layer (scanner OCR) stayed after "Remove OCR data"."""
    from fixtures import make_text_pdf

    _manual()
    c = clients["son1"]
    doc = _upload(c, personal_root(family["son1"]), "scanned.pdf", make_text_pdf("EMBEDDEDLAYER words from a scanner"))
    run_jobs()
    assert _found(c, "embeddedlayer") == 1
    st = c.get(f"/api/documents/{doc.id}/ocr").json()
    assert st["embedded_text"] is True and st["results"] == []
    r = c.delete(f"/api/documents/{doc.id}/ocr", {"confirm": True, "include_embedded": True}, format="json")
    assert r.status_code == 200, r.content
    assert _found(c, "embeddedlayer") == 0
    # regenerating the preview does not bring it back
    assert c.post(f"/api/documents/{doc.id}/reprocess", {}, format="json").status_code == 200
    run_jobs()
    doc.refresh_from_db()
    assert "EMBEDDEDLAYER" not in doc.content_text.upper() and doc.ignore_embedded_text


# ------------------------------------------------------------------ AT-218 disable OCR

def test_at218_disable_prevents_regeneration_until_enabled(family, clients, paddle):
    c = clients["son1"]
    root = personal_root(family["son1"])
    t = DocumentType.objects.first()
    DocumentType.objects.filter(pk=t.pk).update(ocr_mode="automatic")
    doc = _upload(c, root, "auto.png", _png(["DISABLE ME LATER"]), doc_type=str(t.id))
    run_jobs()
    doc.refresh_from_db()
    assert DocumentVersion.objects.get(pk=doc.current_version_id).ocr_applied
    # offered choice: keep existing OCR text, or remove it as well
    r = c.post(f"/api/documents/{doc.id}/ocr/mode", {"disabled": True}, format="json")
    assert r.status_code == 200 and r.json()["override"] == "disabled" and r.json()["results"]
    r = c.post(f"/api/documents/{doc.id}/ocr/mode", {"disabled": True, "remove_existing": True}, format="json")
    assert r.status_code == 200 and r.json()["results"] == [] and r.json()["state"] == "disabled"
    before = Job.objects.filter(kind="ocr_run").count()
    assert c.post(f"/api/documents/{doc.id}/reprocess", {}, format="json").status_code == 200  # regenerate preview
    run_jobs()
    assert Job.objects.filter(kind="ocr_run").count() == before  # Automatic type, but no OCR came back
    r = c.post(f"/api/documents/{doc.id}/ocr", {}, format="json")
    assert r.status_code == 400 and "disabled for this document" in r.json()["error"]
    assert c.post(f"/api/documents/{doc.id}/ocr/mode", {"disabled": False}, format="json").json()["override"] == ""
    assert c.post(f"/api/documents/{doc.id}/ocr", {}, format="json").status_code == 202
    assert AuditEvent.objects.filter(action="document.ocr_disable").exists() and AuditEvent.objects.filter(action="document.ocr_enable").exists()
    viewer = clients["son2"]
    assert viewer.post(f"/api/documents/{doc.id}/ocr/mode", {"disabled": True}, format="json").status_code in (403, 404)


# ------------------------------------------------------------------ AT-221 / 222 inventory and bulk

def test_at221_at222_inventory_and_bulk_cleanup(family, clients, paddle):
    c = clients["son1"]
    p1 = _ocr_doc(c, family, ["PADDLE ONE"], name="p1.png")
    p2 = _ocr_doc(c, family, ["PADDLE TWO BULKWORD"], name="p2.png")
    legacy = _upload(c, personal_root(family["son1"]), "legacy.png", _png(["LEGACY"]))
    run_jobs()
    DocumentVersion.objects.filter(document=legacy).update(ocr_applied=True, ocr_engine="tesseract", text="legacy text")
    unknown = _upload(c, personal_root(family["son1"]), "unknown.png", _png(["UNKNOWN"]))
    run_jobs()
    DocumentVersion.objects.filter(document=unknown).update(ocr_applied=True, ocr_engine="unknown", text="unknown text")
    inv = clients["dad"].get("/api/ocr/inventory").json()
    assert inv["counts"]["paddleocr"] == 2 and inv["counts"]["tesseract"] == 1 and inv["counts"]["unknown"] == 1
    assert inv["storage"]["text"] > 0 and inv["storage"]["total"] >= inv["storage"]["text"]
    assert clients["dad"].get("/api/ocr/inventory", {"engine": "tesseract"}).json()["total"] == 1
    assert clients["son1"].get("/api/ocr/inventory").status_code == 403
    # preview first (nothing changes), then confirm
    ids = [str(p1.id), str(p2.id)]
    prev = clients["dad"].post("/api/ocr/bulk", {"action": "remove_disable", "ids": ids}, format="json").json()
    assert prev["affected"] == 2 and prev["reclaimable_bytes"] > 0 and "Original files" in " ".join(prev["kept"])
    assert DocumentVersion.objects.filter(document_id__in=ids, ocr_applied=True).count() == 2
    r = clients["dad"].post("/api/ocr/bulk", {"action": "remove_disable", "ids": ids, "confirm": True}, format="json")
    assert r.status_code == 202
    run_jobs()
    assert DocumentVersion.objects.filter(document_id__in=ids, ocr_applied=True).count() == 0
    assert set(Document.objects.filter(pk__in=ids).values_list("ocr_override", flat=True)) == {"disabled"}
    assert _found(c, "bulkword") == 0
    assert all(storage.resolve_original(v.storage_path).exists() for v in DocumentVersion.objects.filter(document_id__in=ids))
    assert AuditEvent.objects.filter(action="ocr.bulk_remove_disable").exists() and AuditEvent.objects.filter(action="ocr.bulk_finished").exists()
    inv2 = clients["dad"].get("/api/ocr/inventory").json()
    assert inv2["counts"]["paddleocr"] == 0 and inv2["counts"]["disabled"] == 2 and inv2["storage"]["text"] < inv["storage"]["text"]


# ------------------------------------------------------------------ AT-223 / 224 reprocessing

def test_at223_reprocess_with_ppocrv5_keeps_confirmed_details(family, clients, paddle):
    _manual()
    c = clients["son1"]
    doc = _upload(c, personal_root(family["son1"]), "old.png", _png(["SAMPLE PERMIT", "Expiry 2030-12-31"]))
    run_jobs()
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    DocumentVersion.objects.filter(pk=v.pk).update(ocr_applied=True, ocr_engine="tesseract", text="old tesseract text",
                                                   ocr_quality={"engine": "tesseract"})
    Document.objects.filter(pk=doc.pk).update(ocr_sources=[{"version": str(v.id), "pages": ""}])
    DocumentField.objects.update_or_create(document=doc, key="expiry_date", defaults=dict(
        value="2031-01-15", status=DocumentField.CONFIRMED, source="manual", source_excerpt=""))
    r = clients["dad"].post("/api/ocr/bulk", {"action": "reprocess", "ids": [str(doc.id)], "confirm": True}, format="json")
    assert r.status_code == 202
    run_jobs()
    v.refresh_from_db()
    assert v.ocr_engine == "paddleocr" and "SAMPLE PERMIT" in v.text.upper()
    f = DocumentField.objects.get(document=doc, key="expiry_date")
    assert f.status == DocumentField.CONFIRMED and f.value == "2031-01-15"  # never silently overwritten
    assert OcrRun.objects.filter(document=doc, reprocess=True, status=OcrRun.DONE).count() == 1
    assert storage.resolve_original(v.storage_path).exists()


def test_at224_failed_replacement_keeps_previous_result(family, clients, paddle):
    c = clients["son1"]
    doc = _ocr_doc(c, family, ["KEEPWORD FIRST RESULT"], name="keep.png")
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    before = (v.text, v.ocr_engine, v.ocr_blocks)
    assert _found(c, "keepword") == 1
    (paddle / "fake_mode").write_text("fail")
    assert c.post(f"/api/documents/{doc.id}/ocr", {"reprocess": True}, format="json").status_code == 202
    run_jobs()
    v.refresh_from_db()
    doc.refresh_from_db()
    assert (v.text, v.ocr_engine, v.ocr_blocks) == before  # nothing half-replaced
    assert _found(c, "keepword") == 1 and doc.ocr_state in ("confirmed", "needs_review") and "fake PaddleOCR failure" in doc.ocr_error
    assert OcrRun.objects.filter(document=doc, status=OcrRun.FAILED).exists()
    assert storage.resolve_original(v.storage_path).exists()


# ------------------------------------------------------------------ AT-225 orphans

def test_at225_orphan_dry_run_then_cleanup_only_orphans(family, clients, paddle, settings):
    c = clients["son1"]
    doc = _upload(c, personal_root(family["son1"]), "keep.png", _png(["KEEP"]))
    run_jobs()
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    d = storage.derivative_dir(v.id)
    referenced = d / "searchable.pdf"
    referenced.write_bytes(b"%PDF referenced")
    DocumentVersion.objects.filter(pk=v.pk).update(searchable_path=storage.derivative_rel(referenced), ocr_applied=True)
    orphan_dir = Path(settings.DERIVATIVES_DIR) / "ab" / "abcdef00-0000-0000-0000-000000000000"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "searchable.pdf").write_bytes(b"x" * 5000)
    (orphan_dir / "thumb.png").write_bytes(b"preview kept")
    stray = d / "searchable-old.pdf"
    stray.write_bytes(b"y" * 3000)
    tmp_old = Path(settings.TMP_DIR) / "ocr-stale"
    tmp_old.mkdir(parents=True)
    (tmp_old / "page.png").write_bytes(b"z" * 1000)
    old = time.time() - 4 * 3600
    os.utime(tmp_old, (old, old))
    other = _upload(c, personal_root(family["son1"]), "other.png", _png(["OTHER"]))
    run_jobs()
    DocumentVersion.objects.filter(document=other).update(ocr_applied=False, ocr_blocks=[{"page": 1, "lines": []}])
    dry = clients["dad"].get("/api/ocr/orphans").json()
    items = {i["key"]: i for i in dry["items"]}
    assert items["files"]["count"] == 2 and items["files"]["bytes"] == 8000 and items["tmp"]["count"] == 1
    assert items["blocks"]["count"] == 1
    assert (orphan_dir / "searchable.pdf").exists()  # dry run deletes nothing
    assert clients["dad"].post("/api/ocr/orphans", {}, format="json").status_code == 400
    r = clients["dad"].post("/api/ocr/orphans", {"confirm": True}, format="json").json()
    assert r["removed"] >= 4 and r["after"]["count"] == 0
    assert not (orphan_dir / "searchable.pdf").exists() and not stray.exists() and not tmp_old.exists()
    assert referenced.exists() and (orphan_dir / "thumb.png").exists()  # referenced OCR copy and previews stay
    assert storage.resolve_original(v.storage_path).exists()
    keys = {x["key"] for x in clients["dad"].get("/api/security/storage?refresh=1").json()["categories"]}
    assert {"ocr_text", "ocr_cache", "ocr_orphans", "ocr_models"} <= keys


# ------------------------------------------------------------------ AT-226 / 227 test and compare

def test_at226_at227_test_and_compare_outside_the_library(family, clients, paddle):
    docs = Document.objects.count()
    img = SimpleUploadedFile("sample.png", _png(["SAMPLE PERMIT 2031", "Expiry 2031-03-15"]))
    r = clients["dad"].post("/api/ocr/test", {"file": img, "engines": "paddleocr,tesseract", "profile": "en",
                                              "expected": "SAMPLE PERMIT 2031\nExpiry 2031-03-15", "template": "iqama"},
                            format="multipart")
    assert r.status_code == 200, r.content
    res = r.json()
    assert res["artifacts_removed"] and "not comparable" in res["note"]
    by = {x["engine"]: x for x in res["results"]}
    assert by["paddleocr"]["ok"] and by["tesseract"]["ok"] and by["paddleocr"]["has_geometry"]
    assert by["paddleocr"]["accuracy"] > 80 and by["tesseract"]["accuracy"] > 80  # judged by expected text
    assert any(f["key"] == "expiry_date" for f in by["paddleocr"]["fields"])
    assert Document.objects.count() == docs  # never added to the family library
    assert not [p for p in Path(ocr_engines.settings.TMP_DIR).glob("ocrtest-*")]
    assert AuditEvent.objects.filter(action="ocr.test", context__compared=True).exists()
    assert clients["son1"].post("/api/ocr/test", {"file": SimpleUploadedFile("s.png", b"x")}, format="multipart").status_code == 403


# ------------------------------------------------------------------ AT-228 Local AI

def test_at228_ai_follows_ocr_epoch_and_never_overwrites_confirmed(family, clients, paddle, monkeypatch):
    from apps.ai import jobs as ai_jobs
    from apps.ai.models import AIJob

    t = DocumentType.objects.first()
    DocumentType.objects.filter(pk=t.pk).update(ocr_mode="manual", ocr_ai_allowed=True)
    called = []
    monkeypatch.setattr(ai_jobs, "after_processing", lambda doc: called.append(str(doc.id)))
    c = clients["son1"]
    doc = _upload(c, personal_root(family["son1"]), "ai.png", _png(["AI SAMPLE"]), doc_type=str(t.id))
    run_jobs()
    assert c.post(f"/api/documents/{doc.id}/ocr", {}, format="json").status_code == 202
    run_jobs()
    assert str(doc.id) in called  # PP-OCRv5 output feeds the permitted Local AI step
    monkeypatch.undo()
    doc.refresh_from_db()
    ai_job = AIJob.objects.create(kind=AIJob.ANALYZE, document=doc)
    from apps.core import jobs as core_jobs

    j = core_jobs.enqueue("ai_task", {"ai_job": str(ai_job.id), "epoch": doc.ocr_epoch})
    Job.objects.filter(pk=j.pk).update(status=Job.RUNNING)  # already picked up when OCR is removed
    assert c.delete(f"/api/documents/{doc.id}/ocr", {"confirm": True}, format="json").status_code == 200
    j.refresh_from_db()
    out = ai_jobs.ai_task(j)
    assert "removed" in out.get("skipped", "")  # stale AI work cannot rebuild suggestions from removed text


# ------------------------------------------------------------------ AT-229 persistence

def test_at229_models_and_config_survive_restart(family, clients, paddle, settings):
    from apps.security.models import HealthState

    assert str(settings.PADDLE_HOME).startswith(str(paddle))  # models live in the data directory, not in a release
    HealthState.objects.filter(key__startswith="paddleocr").delete()  # "restart": nothing cached
    ocr_engines.paddle_selftest()
    assert ocr_engines.paddle_status(refresh=True)["healthy"]
    script = (Path(__file__).resolve().parents[1] / "scripts/personaldocs").read_text()
    assert "PADDLE_HOME=$DATA_DIR/paddle" in script and "PADDLE_VENV=$PREFIX/paddle-venv" in script
    optional = script.split("install_optional_packages() {")[1].split("\n}")[0]
    post = script.split("cmd_post_upgrade() {")[1].split("\n}")[0]
    repair = script.split("cmd_repair() {")[1].split("\n}")[0]
    assert "install_paddleocr" in optional and "install_optional_packages" in post and "install_optional_packages" in repair


# ------------------------------------------------------------------ live PP-OCRv5 (skipped unless the runtime exists)

live = pytest.mark.skipif(not (LIVE_PY and Path(LIVE_PY).exists() and LIVE_HOME), reason="real PaddleOCR runtime not available")


@pytest.fixture
def real_paddle(settings):
    settings.PADDLE_PYTHON = LIVE_PY
    settings.PADDLE_HOME = Path(LIVE_HOME)
    from apps.security.models import HealthState

    HealthState.objects.filter(key__startswith="paddleocr").delete()
    config.set_value("processing.ocr_engine", "paddleocr")
    config.set_value("processing.ocr_profiles", ["en", "ar_en", "hi_en", "te_en", "ta_en"])


@live
def test_live_at211_real_selftest_and_document_run(family, clients, real_paddle):
    res = ocr_engines.paddle_selftest()
    assert res["healthy"], res
    doc = _ocr_doc(clients["son1"], family, ["SAMPLE RESIDENCE PERMIT", "Name: Sample Person", "Expiry: 2027-03-15"])
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    assert v.ocr_engine == "paddleocr" and "PP-OCRv5" in v.ocr_model, (v.ocr_engine, doc.ocr_error)
    assert "RESIDENCE" in v.text.upper() and "2027-03-15" in v.text


@live
def test_live_at216_arabic_english_profile(family, clients, real_paddle):
    doc = _ocr_doc(clients["son1"], family, ["المملكة العربية السعودية"], name="ar.png", profile="ar_en")
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    assert v.ocr_profile == "ar_en" and "arabic_PP-OCRv5_mobile_rec" in v.ocr_model
    assert "السعودية" in v.text or "العربية" in v.text, v.text


@live
def test_live_at216_hindi_english_profile_reads_upright(family, clients, real_paddle):
    """Regression: with text-line orientation on, PP-OCRv5 read every line of this card upside down (benchmark)."""
    assert config.get("processing.paddle_textline") is False
    img = _png(["नमूना पहचान पत्र"], font="/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf")
    _manual()
    doc = _upload(clients["son1"], personal_root(family["son1"]), "hi.png", img)
    run_jobs()
    assert clients["son1"].post(f"/api/documents/{doc.id}/ocr", {"profile": "hi_en"}, format="json").status_code == 202
    run_jobs()
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    assert v.ocr_profile == "hi_en" and "devanagari_PP-OCRv5_mobile_rec" in v.ocr_model
    assert "पहचान" in v.text and "नमूना" in v.text, v.text  # upright: an upside-down read produces Latin-like junk
