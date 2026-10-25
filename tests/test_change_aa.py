"""Change Set AA — direct Local AI processing, custom Overview layouts, Document Type field management.

Acceptance tests AT-461..AT-480: the change prompt's AT-436..AT-455, renumbered (+25) because AT-436..AT-460 are
already used by Change Sets Y and Z. Local AI servers are emulated by tests/fake_ai_server.py (OpenAI-compatible API,
images as image_url parts, exactly what LM Studio receives); OCR fallback uses the real Tesseract when installed.
"""
import importlib
import io
import json
import shutil
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.conf import settings as dj_settings

from apps.ai import direct
from apps.ai.models import AIJob, AIProfile, AISuggestion
from apps.core import config
from apps.core.models import AuditEvent, UserSetting
from apps.library import doctypes
from apps.library.models import Document, DocumentField, DocumentType, DocumentTypeField, OcrRun
from conftest import PASSWORD, client_for, personal_root, run_jobs, upload
from fixtures import make_image_pdf, make_text_pdf
from test_ai import enable_ai, fake_ai, make_doc, profile  # noqa: F401 - fixtures

pytestmark = pytest.mark.django_db
HAS_TESSERACT = shutil.which("tesseract") is not None


# ------------------------------------------------------------------ helpers

def _image(fmt: str, pages: int = 1, text: str = "VALID UNTIL 20/05/2031") -> bytes:
    from PIL import Image, ImageDraw

    frames = []
    for i in range(pages):
        im = Image.new("RGB", (800, 400), "white")
        ImageDraw.Draw(im).text((40, 180), f"{text} PAGE {i + 1}", fill="black")
        frames.append(im)
    buf = io.BytesIO()
    frames[0].save(buf, fmt, save_all=pages > 1, append_images=frames[1:])
    return buf.getvalue()


def _vision(profile, *, vision="vision-model", read="ok", multipage="supported"):
    profile.vision_model = vision
    profile.capabilities = {**(profile.capabilities or {}), "vision_read": read, "multipage": multipage}
    profile.save()
    return profile


def _manual_ocr():
    """Nothing is recognised on upload, so a direct Local AI run provably did not use OCR."""
    DocumentType.objects.update(ocr_mode="manual")
    config.set_value("processing.ocr_untyped_mode", "manual")


def _on_demand(**extra):
    enable_ai(**{"ai.auto_analyze": False, **extra})


def _upload(client, user, name, content) -> Document:
    r = upload(client, personal_root(user), name=name, content=content)
    assert r.status_code == 201, r.content
    run_jobs()
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


def _action(client, doc, action="analyze", **body):
    return client.post(f"/api/documents/{doc.id}/ai/action", {"action": action, **body}, format="json")


def _run(client, doc, action="analyze", **body) -> AIJob:
    r = _action(client, doc, action, **body)
    assert r.status_code == 202, r.content
    run_jobs()
    run_jobs()  # a fallback job resumes after its OCR run
    return AIJob.objects.get(pk=r.json()["job"])


def _visa_type() -> DocumentType:
    t = DocumentType.objects.create(name="Exit Re-Entry Visa", template="generic", is_custom=True, has_expiry=True,
                                    ocr_mode="manual", ocr_ai_allowed=True, description="Synthetic visa type")
    for i, (key, label, ftype, role, required) in enumerate([
            ("visa_number", "Visa Number", "identifier", "", True), ("visa_type", "Visa Type", "text", "", False),
            ("issuer", "Issuer", "text", "", False), ("issue_date", "Issue date", "date", "issue", False),
            ("expiry_date", "Expiry date", "date", "expiry", True)]):
        DocumentTypeField.objects.create(doc_type=t, key=key, label=label, field_type=ftype, role=role,
                                         required=required, order=(i + 1) * 10, extract=True)
    doctypes.sync_ocr_fields(t)
    return t


def _stepup(client):
    r = client.post("/api/backup/stepup", {"password": PASSWORD}, format="json")
    assert r.status_code == 200, r.content


# ================================================================== A. Processing Source

def test_at461_processing_source_choices_and_default(family, clients, fake_ai, profile):
    _on_demand()
    _vision(profile)
    _manual_ocr()
    assert config.get("ai.processing_source") == "original_fallback"
    assert config.get("ai.source_override") is True
    doc = _upload(clients["son1"], family["son1"], "scan.png", _image("PNG"))
    st = clients["son1"].get("/api/ai/status").json()
    assert st["processing"]["default"] == "original_fallback"
    assert set(st["processing"]["labels"]) == {"ocr_text", "original", "original_fallback"}
    assert st["profile"]["direct"]["direct"] and "PNG" in st["profile"]["direct"]["formats"]
    actions = {a["kind"]: a for a in clients["son1"].get(f"/api/documents/{doc.id}/ai").json()["actions"]}
    choices = actions["analyze"]["processing_sources"]
    assert [c["value"] for c in choices] == ["original_fallback", "original", "ocr_text"]
    assert all(c["enabled"] for c in choices)
    assert choices[0]["label"] == "Original Document — Local AI + OCR Fallback"
    assert "processing_sources" not in actions["verify"]  # Verify OCR checks the OCR text itself
    # the Main Admin can force the default for everyone
    config.set_value("ai.source_override", False)
    r = _action(clients["son1"], doc, "summarize", processing_source="ocr_text")
    assert r.status_code == 400 and "Main Admin" in r.json()["error"]
    assert clients["son1"].get("/api/ai/status").json()["processing"]["override"] is False
    assert _action(clients["dad"], doc, "summarize", processing_source="ocr_text").status_code in (202, 404)
    assert _action(clients["son1"], doc, "summarize", processing_source="bogus").status_code == 400


def test_at462_direct_local_ai_reads_original_without_ocr(family, clients, fake_ai, profile):
    _on_demand()
    _vision(profile)
    _manual_ocr()
    for name, content in (("passport.png", _image("PNG")), ("letter.pdf", make_text_pdf("SAMPLE LETTER\nNo. X1234567"))):
        fake_ai.images_seen.clear()
        doc = _upload(clients["son1"], family["son1"], name, content)
        assert not OcrRun.objects.filter(document=doc).exists()
        job = _run(clients["son1"], doc)
        assert job.status == AIJob.DONE, job.error
        assert job.processing_source == "original_fallback" and job.final_source == "original" and not job.fallback_used
        assert job.data_sent[0] == "image" and job.detail["direct_status"] == "ok"
        assert job.detail["file_type"] == ("PNG" if name.endswith("png") else "PDF") and job.detail["pages_sent"] == 1
        assert fake_ai.images_seen == [1]
        assert not OcrRun.objects.filter(document=doc).exists()  # OCR was never invoked
        doc.refresh_from_db()
        assert doc.ocr_state == "not_processed"
        sugg = {s.field: s for s in AISuggestion.objects.filter(document=doc, status="pending")}
        assert sugg["expiry_date"].value == "2031-05-20" and sugg["expiry_date"].source == "original"
        assert sugg["expiry_date"].page == 1 and sugg["expiry_date"].evidence == "observed"
        assert sugg["document_number"].value == "X1234567"
        assert doc.expiry_date is None  # still only a suggestion
        hist = clients["son1"].get(f"/api/documents/{doc.id}/ai").json()["history"][0]
        assert hist["final_source"] == "original" and hist["detail"]["file_type"] and hist["fallback_used"] is False
    # the model only ever saw page images, never OCR text, and the request was marked as untrusted content
    last = fake_ai.chats()[-1]
    assert "ORIGINAL DOCUMENT ATTACHED" in json.dumps(last) and "untrusted" in json.dumps(last)
    assert AuditEvent.objects.filter(action="ai.direct_processing", outcome="success").exists()


def test_at463_formats_and_capabilities(family, clients, fake_ai, profile, settings):
    _on_demand()
    _vision(profile)
    _manual_ocr()
    config.set_value("ai.direct_max_pages", 2)
    cases = [("photo.jpg", _image("JPEG"), "JPEG", 1), ("scan.png", _image("PNG"), "PNG", 1),
             ("pages.tiff", _image("TIFF", pages=3), "TIFF", 2), ("image.webp", _image("WEBP"), "WEBP", 1),
             ("two.pdf", make_image_pdf("VALID UNTIL 20/05/2031"), "PDF", 1)]
    for name, content, kind, pages in cases:
        fake_ai.images_seen.clear()
        doc = _upload(clients["son1"], family["son1"], name, content)
        job = _run(clients["son1"], doc, processing_source="original")
        assert job.status == AIJob.DONE, (name, job.error)
        assert job.detail["file_type"] == kind and job.detail["pages_sent"] == pages, name
        assert fake_ai.images_seen == [pages], name
        if kind == "TIFF":
            assert job.detail["truncated"] and job.detail["pages_total"] == 3  # bounded by the page limit
    # a two-page PDF: both pages rendered locally, in order
    from PIL import Image

    two = io.BytesIO()
    Image.new("RGB", (600, 300), "white").save(two, "PDF", save_all=True, append_images=[Image.new("RGB", (600, 300), "white")])
    doc = _upload(clients["son1"], family["son1"], "pages.pdf", two.getvalue())
    fake_ai.images_seen.clear()
    job = _run(clients["son1"], doc, processing_source="original")
    assert job.detail["pages_sent"] == 2 and fake_ai.images_seen == [2]
    # a model that reads one image per request only gets the first page
    _vision(profile, multipage="unsupported")
    fake_ai.images_seen.clear()
    job = _run(clients["son1"], doc, processing_source="original")
    assert fake_ai.images_seen == [1] and job.detail["truncated"]
    # the format comes from the content, not the name
    p = Path(dj_settings.TMP_DIR) / "sniff.pdf"
    p.write_bytes(_image("PNG"))
    assert direct.file_kind(p) == "png"
    p.unlink()
    # unsupported: refused at once without fallback, never claimed as supported
    txt = _upload(clients["son1"], family["son1"], "notes.txt", b"VALID UNTIL 2031-05-20 plain text")
    r = _action(clients["son1"], txt, processing_source="original")
    assert r.status_code == 409 and "TXT" in r.json()["error"] and r.json()["category"] == "unsupported"
    choices = {c["value"]: c for c in clients["son1"].get(f"/api/documents/{txt.id}/ai").json()["actions"][0]["processing_sources"]}
    assert choices["original"]["enabled"] is False and choices["original"]["reason"]
    # a profile without a working vision model claims no formats at all
    _vision(profile, read="failed")
    caps = direct.capabilities(profile)
    assert caps["formats"] == [] and not caps["direct"] and not caps["pdf"]
    _vision(profile, vision="")
    assert direct.capabilities(profile)["formats"] == []
    # Test Profile detects the capability with a synthetic page (and multi-page support)
    _vision(profile)
    profile.capabilities = {}
    profile.save()
    r = clients["dad"].post(f"/api/ai/profiles/{profile.pk}/test")
    assert r.status_code == 200, r.content
    profile.refresh_from_db()
    assert profile.capabilities["vision_read"] == "ok" and profile.capabilities["multipage"] == "supported"
    fake_ai.vision_ok = False
    clients["dad"].post(f"/api/ai/profiles/{profile.pk}/test")
    profile.refresh_from_db()
    assert profile.capabilities["vision_read"] == "failed" and not direct.capabilities(profile)["direct"]
    assert "SECRETKEY" not in json.dumps(clients["dad"].get("/api/ai/profiles").json())
    assert not list(Path(dj_settings.TMP_DIR).glob("ai-direct-*"))  # temporary pages always removed


@pytest.mark.skipif(not HAS_TESSERACT, reason="Tesseract not installed")
def test_at464_direct_failure_falls_back_to_the_configured_ocr_chain(family, clients, fake_ai, profile):
    _on_demand()
    _vision(profile)
    _manual_ocr()
    config.set_value("processing.ocr_engine_order", ["tesseract"])
    fake_ai.direct_fail = 400  # the loaded model rejects images
    doc = _upload(clients["son1"], family["son1"], "scan.pdf", make_image_pdf("PASSPORT\nVALID UNTIL 2031-05-20"))
    assert not OcrRun.objects.filter(document=doc).exists()
    job = _run(clients["son1"], doc)
    assert job.status == AIJob.DONE, job.error
    assert job.processing_source == "original_fallback" and job.fallback_used and job.final_source == "ocr_text"
    assert "images" in job.fallback_reason or "HTTP 400" in job.fallback_reason
    assert job.detail["direct_status"] == "failed" and job.detail["ocr_engine"] == "tesseract"
    assert job.data_sent[:2] == ["image", "ocr_text"]  # both attempts are on record
    assert job.detail["ocr_order"] == ["tesseract"] and job.detail["ocr_engines_attempted"] == ["tesseract"]
    run = OcrRun.objects.get(document=doc)
    assert run.engine == "tesseract" and run.status == "done"  # the configured chain really ran
    assert any("2031" in fake_ai.document_block(json.dumps(b["messages"][-1]["content"]).replace("\\n", "\n"))
               for b in fake_ai.analysis_chats())  # normalized OCR text went back to the Local AI
    assert all(s.source == "ocr_text" for s in AISuggestion.objects.filter(document=doc))
    assert AuditEvent.objects.filter(action="ai.direct_processing", outcome="failure").exists()
    hist = clients["son1"].get(f"/api/documents/{doc.id}/ai").json()["history"][0]
    assert hist["fallback_used"] and hist["fallback_reason"] and hist["detail"]["ocr_engine"] == "tesseract"


def test_at464_malformed_or_unusable_answers_fall_back(family, clients, fake_ai, profile):
    _on_demand()
    _vision(profile)
    doc = make_doc(clients["son1"], family["son1"], "SAMPLE PASSPORT\nVALID UNTIL 2031-05-20\nNo. X1234567")
    run_jobs()
    for reply, category in (("this is not JSON at all", "bad_response"),
                            ({"fields": {"expiry_date": {"value": "2031-05-20"}}}, "unusable"),  # no printed evidence
                            ({"fields": {}}, "unusable")):
        fake_ai.direct_reply = reply
        job = _run(clients["son1"], doc)
        assert job.status == AIJob.DONE and job.fallback_used, (reply, job.error)
        assert job.detail["direct_error_category"] == category and job.final_source == "ocr_text"


def test_at465_original_only_never_runs_ocr(family, clients, fake_ai, profile):
    _on_demand()
    _vision(profile)
    _manual_ocr()
    fake_ai.direct_fail = 400
    doc = _upload(clients["son1"], family["son1"], "scan.png", _image("PNG"))
    job = _run(clients["son1"], doc, processing_source="original")
    assert job.status == AIJob.FAILED and "OCR was not run" in job.error
    assert job.processing_source == "original" and not job.fallback_used
    assert not OcrRun.objects.filter(document=doc).exists()
    doc.refresh_from_db()
    assert doc.ocr_state == "not_processed" and not fake_ai.analysis_chats()
    # a person can retry with the fallback mode
    fake_ai.direct_fail = None
    r = clients["son1"].post(f"/api/ai/jobs/{job.id}/retry", {"processing_source": "original_fallback"}, format="json")
    assert r.status_code == 202, r.content
    run_jobs()
    new = AIJob.objects.get(pk=r.json()["job"])
    assert new.status == AIJob.DONE and new.processing_source == "original_fallback" and new.final_source == "original"


def test_at466_schema_aware_mapping_and_review(family, clients, fake_ai, profile):
    _on_demand()
    _vision(profile)
    _manual_ocr()
    t = _visa_type()
    c = clients["son1"]
    doc = _upload(c, family["son1"], "visa.png", _image("PNG"))
    assert c.post(f"/api/documents/{doc.id}/type", {"type": t.id}, format="json").status_code == 200
    doctypes.archive_field(actor=family["dad"], field=t.template_fields.get(key="visa_type"))
    fake_ai.direct_reply = {"fields": {
        "visa_number": {"value": "7012345678", "printed": "Visa No: 7012345678", "page": 1},
        "visa_type": {"value": "Multiple", "printed": "Type: Multiple", "page": 1},       # archived: never mapped
        "issuer": {"value": "Sample Passport Office", "printed": "Sample Passport Office", "page": 1},
        "expiry_date": {"value": "2030-12-16", "printed": "Expiry 16/12/2030", "page": 1},
        "issue_date": {"value": "2020-01-01"},                                            # no printed words: dropped
        "invented_key": {"value": "x", "printed": "x"}}}
    job = _run(c, doc)
    assert job.status == AIJob.DONE and job.final_source == "original", job.error
    prompt = json.dumps(fake_ai.chats()[-1])
    assert "visa_number" in prompt and "Visa Number" in prompt and "visa_type" not in prompt  # active schema only
    sugg = {s.field: s for s in AISuggestion.objects.filter(document=doc, status="pending")}
    assert sugg["detail:visa_number"].value == "7012345678" and sugg["detail:issuer"].value == "Sample Passport Office"
    assert "detail:visa_type" not in sugg and "detail:invented_key" not in sugg
    assert "issue_date" not in sugg and "detail:issue_date" not in sugg  # nothing invented to fill a field
    assert sugg["expiry_date"].value == "2030-12-16"
    data = c.get(f"/api/documents/{doc.id}/ai/suggestions").json()["suggestions"]
    row = next(s for s in data if s["field"] == "detail:visa_number")
    assert row["field_label"] == "Visa Number" and row["source"] == "original" and row["page"] == 1 and row["editable"]
    assert not DocumentField.objects.filter(document=doc, key="visa_number").exists()  # a suggestion until accepted
    r = c.post(f"/api/documents/{doc.id}/ai/suggestions/{sugg['detail:visa_number'].id}", {"action": "accept"}, format="json")
    assert r.status_code == 200, r.content
    f = DocumentField.objects.get(document=doc, key="visa_number")
    assert f.value == "7012345678" and f.status == "confirmed" and f.source == "ai"
    # edit then accept: validated like a manual entry
    r = c.post(f"/api/documents/{doc.id}/ai/suggestions/{sugg['detail:issuer'].id}", {"action": "accept", "value": "Edited Office"},
               format="json")
    assert r.status_code == 200 and DocumentField.objects.get(document=doc, key="issuer").source == "manual"
    # the OCR Text mode maps the same active schema from OCR text (values must be in the text)
    txt = make_doc(c, family["son1"], "EXIT RE-ENTRY VISA\nVisa No: 9900112233\nType: Single")
    run_jobs()
    c.post(f"/api/documents/{txt.id}/type", {"type": t.id}, format="json")
    fake_ai.analyze_reply = {"title": "Visa", "details": {"visa_number": "9900112233", "visa_type": "Single",
                                                          "issuer": "Not In Text Office"}}
    job = _run(c, txt, processing_source="ocr_text")
    assert job.final_source == "ocr_text"
    got = {s.field: s for s in AISuggestion.objects.filter(document=txt, status="pending")}
    assert got["detail:visa_number"].value == "9900112233" and got["detail:visa_number"].evidence == "observed"
    assert "detail:visa_type" not in got  # archived
    assert got["detail:issuer"].evidence == "inferred"  # free text not printed: labelled as an inference


def test_at467_cloud_profiles_never_receive_originals(family, clients, fake_ai, profile):
    from test_ai_intelligence import _cloud

    _on_demand()
    _manual_ocr()
    doc = make_doc(clients["son1"], family["son1"], "SAMPLE PASSPORT VALID UNTIL 2031-05-20")
    run_jobs()
    _cloud(clients, fake_ai, vision_model="vision-model", cloud_send_ocr_text=True, cloud_send_images=True)
    fake_ai.requests.clear()
    for mode in ("original", "original_fallback"):
        r = _action(clients["son1"], doc, processing_source=mode)
        assert r.status_code == 409 and r.json()["category"] == "privacy" and "Local" in r.json()["error"]
    assert not fake_ai.chats() and not fake_ai.images_seen  # nothing transmitted
    job = _run(clients["son1"], doc)  # the default with a Cloud profile reads OCR text only
    assert job.processing_source == "ocr_text" and job.detail.get("source_note") == "cloud_profile"
    assert not fake_ai.images_seen and "image" not in job.data_sent
    with pytest.raises(direct.NotEligible):
        direct.eligibility(doc, AIProfile.objects.get(is_default=True))
    actions = clients["son1"].get(f"/api/documents/{doc.id}/ai").json()["actions"]
    choices = {c["value"]: c for c in next(a for a in actions if a["kind"] == "analyze")["processing_sources"]}
    assert choices["original"]["enabled"] is False and choices["original_fallback"]["enabled"] is False


def test_at468_resource_protection_rules(family, clients, fake_ai, profile, settings):
    """Automated part of AT-468: background priority, the AI concurrency limit and bounded inputs. The real 6 GB LXC
    load run is Blocked / Not Executed (see docs/TEST_REPORT.md)."""
    from apps.core.models import Job

    _on_demand()
    _vision(profile)
    _manual_ocr()
    config.set_value("ai.direct_max_pages", 1)
    doc = _upload(clients["son1"], family["son1"], "pages.tiff", _image("TIFF", pages=4))
    r = _action(clients["son1"], doc, processing_source="original")
    assert r.status_code == 202
    queued = Job.objects.filter(kind="ai_task", status=Job.QUEUED).first()
    assert queued.priority > 100  # background work yields to interactive requests (AT-400 rules)
    AIJob.objects.create(kind="analyze", status=AIJob.RUNNING)  # the one AI slot is busy
    run_jobs()
    assert AIJob.objects.get(pk=r.json()["job"]).status == AIJob.QUEUED  # waits instead of overloading
    AIJob.objects.filter(document__isnull=True).delete()
    from django.utils import timezone

    Job.objects.filter(kind="ai_task", status=Job.QUEUED).update(run_after=timezone.now())  # the retry is due now
    run_jobs()
    job = AIJob.objects.get(pk=r.json()["job"])
    assert job.status == AIJob.DONE and job.detail["pages_sent"] == 1 and job.detail["pages_total"] == 4
    config.set_value("ai.direct_max_mb", 1)
    big = _upload(clients["son1"], family["son1"], "big.png", _image("PNG") + b"\0" * (1024 * 1024 + 10))
    r = _action(clients["son1"], big, processing_source="original")
    assert r.status_code == 409 and r.json()["category"] == "too_large"
    with pytest.raises(direct.NotEligible) as exc:
        direct.eligibility(big, profile)
    assert "1 MB" in str(exc.value)


# ================================================================== B. Overview layout

def _layout(client):
    r = client.get("/api/dashboard/layout")
    assert r.status_code == 200
    return r.json()


def test_at469_tiles_resize_and_persist(family, clients):
    c = clients["mom"]
    base = _layout(c)
    assert [g["id"] for g in base["groups"]] == ["general"] and not base["customized"]
    widgets = base["groups"][0]["widgets"]
    layout = {"summary": {"cols": 9, "h": 3}, "calendar": {"cols": 4, "h": 5}, "date": {"cols": 1, "h": 99},
              "recent": {"cols": 50}}
    r = c.put("/api/dashboard/layout", {"groups": base["groups"], "layout": layout}, format="json")
    assert r.status_code == 200, r.content
    lim = base["limits"]
    saved = _layout(client_for(family["mom"]))["layout"]  # a new session (relogin) sees the same layout
    assert saved["summary"] == {"cols": 9, "h": 3, "w": 3, "style": "rect"}
    assert saved["calendar"]["cols"] == 4 and saved["calendar"]["h"] == 5
    assert saved["date"]["cols"] == lim["date"]["cols_min"] and saved["date"]["h"] == lim["date"]["h_max"]  # clamped
    assert saved["recent"]["cols"] == lim["recent"]["cols_max"] == 12
    assert c.put("/api/dashboard/layout", {"groups": base["groups"], "layout": {"summary": {"h": "tall"}}},
                 format="json").status_code == 400
    assert [w for g in _layout(c)["groups"] for w in g["widgets"]] == widgets


def test_at470_groups_create_rename_reorder_collapse_remove(family, clients):
    c = clients["mom"]
    g0 = _layout(c)["groups"][0]
    groups = [g0, {"id": "renewals", "name": "Renewals", "collapsed": False, "widgets": ["upcoming", "calendar"]},
              {"id": "family", "name": "Family", "collapsed": True, "widgets": ["activity"]}]
    groups[0] = {**g0, "widgets": [w for w in g0["widgets"] if w not in ("upcoming", "calendar", "activity")]}
    r = c.put("/api/dashboard/layout", {"groups": groups, "layout": {}}, format="json")
    assert r.status_code == 200, r.content
    got = {g["id"]: g for g in r.json()["groups"]}
    assert got["renewals"]["widgets"] == ["upcoming", "calendar"] and got["family"]["collapsed"]
    # rename and reorder
    order = [got["family"] | {"name": "Travel"}, got["general"], got["renewals"]]
    r = c.put("/api/dashboard/layout", {"groups": order, "layout": {}}, format="json")
    assert [g["name"] for g in r.json()["groups"]] == ["Travel", "General", "Renewals"]
    # removing a populated group never deletes or orphans its tiles: they go to General
    r = c.put("/api/dashboard/layout", {"groups": [g for g in r.json()["groups"] if g["id"] != "renewals"], "layout": {}},
              format="json")
    general = next(g for g in r.json()["groups"] if g["id"] == "general")
    assert {"upcoming", "calendar"} <= set(general["widgets"])
    # General cannot be removed (it comes back) and names are validated
    r = c.put("/api/dashboard/layout", {"groups": [{"id": "travel", "name": "Travel", "widgets": ["activity"]}], "layout": {}},
              format="json")
    assert r.json()["groups"][0]["id"] == "general" and {"upcoming", "calendar"} <= set(r.json()["groups"][0]["widgets"])
    for bad in ([{"id": "x", "name": "", "widgets": []}], [{"id": "x", "name": "<script>", "widgets": []}],
                [{"id": "a", "name": "Same"}, {"id": "b", "name": "same"}], [{"id": "Bad Id!", "name": "X"}]):
        assert c.put("/api/dashboard/layout", {"groups": bad, "layout": {}}, format="json").status_code == 400, bad
    # a tile is in one group only; unknown tiles are dropped instead of breaking the Overview
    r = c.put("/api/dashboard/layout", {"groups": [{"id": "general", "name": "General", "widgets": ["date", "date", "gone"]},
                                                   {"id": "two", "name": "Two", "widgets": ["date", "weather"]}], "layout": {}},
              format="json")
    # (the Travel group that was left out handed its tile to General)
    assert r.json()["groups"][0]["widgets"] == ["date", "activity"] and r.json()["groups"][1]["widgets"] == ["weather"]


def test_at471_layouts_are_personal(family, clients):
    mom, son = clients["mom"], clients["son1"]
    son_before = _layout(son)
    r = mom.put("/api/dashboard/layout", {"groups": [{"id": "general", "name": "General", "widgets": ["date"]},
                                                     {"id": "mine", "name": "Mine", "widgets": ["recent"]}],
                                          "layout": {"date": {"cols": 6}}}, format="json")
    assert r.status_code == 200
    assert _layout(son) == son_before  # the other person's Overview is untouched
    son.put("/api/dashboard/layout", {"groups": [{"id": "general", "name": "General", "widgets": ["weather"]}], "layout": {}},
            format="json")
    assert [g["id"] for g in _layout(mom)["groups"]] == ["general", "mine"]
    assert set(UserSetting.objects.filter(key="me.dashboard_groups").values_list("user__username", flat=True)) == {"mom", "son1"}
    # the generic settings API cannot write another person's layout either
    r = mom.put("/api/settings", {"values": {"me.dashboard_groups": {"groups": []}}, "user": str(family["son1"].pk)}, format="json")
    assert [g["id"] for g in _layout(son)["groups"]] == ["general"] and _layout(son)["groups"][0]["widgets"] == ["weather"]


def test_at472_reflow_never_changes_the_saved_layout(family, clients):
    c = clients["mom"]
    groups = _layout(c)["groups"]
    c.put("/api/dashboard/layout", {"groups": groups, "layout": {"summary": {"cols": 8, "h": 4}}}, format="json")
    for agent in ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", "Mozilla/5.0 (X11; Linux x86_64)"):
        assert c.get("/api/dashboard/layout", HTTP_USER_AGENT=agent).json()["layout"]["summary"]["cols"] == 8
    css = (Path(dj_settings.REPO_DIR) / "frontend" / "src" / "styles.css").read_text()
    assert "repeat(12, minmax(0, 1fr))" in css and "@media (max-width: 640px)" in css  # phones reflow to one column


def test_at473_reset_layout_only_for_that_person(family, clients):
    mom, son = clients["mom"], clients["son1"]
    for c in (mom, son):
        c.put("/api/dashboard/layout", {"groups": [{"id": "general", "name": "General", "widgets": ["date"]},
                                                   {"id": "x", "name": "X", "widgets": ["recent"]}], "layout": {"date": {"cols": 6}}},
              format="json")
    docs = Document.objects.count()
    r = mom.post("/api/dashboard/layout/reset")
    assert r.status_code == 200 and not r.json()["customized"] and [g["id"] for g in r.json()["groups"]] == ["general"]
    assert r.json()["groups"][0]["widgets"] == config.get_user(family["mom"], "me.dashboard_widgets") and r.json()["layout"] == {}
    assert [g["id"] for g in _layout(son)["groups"]] == ["general", "x"]  # only mom's layout was reset
    assert Document.objects.count() == docs
    assert AuditEvent.objects.filter(action="overview.layout_reset").count() == 1


# ================================================================== C. Document Type fields

def _typed_doc(clients, family, t, values: dict) -> Document:
    doc = make_doc(clients["son1"], family["son1"], "SAMPLE visa document")
    clients["son1"].post(f"/api/documents/{doc.id}/type", {"type": t.id}, format="json")
    for k, v in values.items():
        DocumentField.objects.update_or_create(document=doc, key=k, defaults={"value": v, "status": "confirmed", "source": "manual"})
    return doc


def test_at474_field_reorder_keeps_identity_and_values(family, clients):
    admin = clients["dad"]
    t = _visa_type()
    doc = _typed_doc(clients, family, t, {"visa_number": "7012345678", "issuer": "Office"})
    ids = list(t.template_fields.order_by("order").values_list("id", flat=True))
    keys_before = dict(t.template_fields.values_list("id", "key"))
    new = [ids[4], ids[2], ids[0], ids[1], ids[3]]
    r = admin.post(f"/api/document-types/{t.id}/fields", {"reorder": new}, format="json")
    assert r.status_code == 200, r.content
    assert list(t.template_fields.order_by("order").values_list("id", flat=True)) == new  # persists
    assert dict(t.template_fields.values_list("id", "key")) == keys_before
    assert DocumentField.objects.get(document=doc, key="visa_number").value == "7012345678"
    detail = clients["son1"].get(f"/api/documents/{doc.id}").json()
    assert [f["key"] for f in detail["template"]][0] == "expiry_date"
    # an incomplete or foreign list is refused (no field can lose its position silently)
    assert admin.post(f"/api/document-types/{t.id}/fields", {"reorder": new[:3]}, format="json").status_code == 400
    ev = AuditEvent.objects.filter(action="settings.document_type_fields_reorder").latest("id")
    assert ev.context["order"][0] == "expiry_date"
    assert clients["mom"].post(f"/api/document-types/{t.id}/fields", {"reorder": new}, format="json").status_code == 403


def test_at475_archive_keeps_values_and_leaves_active_use(family, clients, fake_ai, profile):
    admin = clients["dad"]
    t = _visa_type()
    doc = _typed_doc(clients, family, t, {"visa_number": "7012345678"})
    vn = t.template_fields.get(key="visa_number")
    assert doctypes.details_status(doc)["missing_required"] == ["Expiry date"] or "Visa Number" not in doctypes.details_status(doc)["missing_required"]
    r = admin.post(f"/api/document-types/{t.id}/fields/{vn.id}/archive")
    assert r.status_code == 200, r.content
    vn.refresh_from_db()
    assert not vn.enabled and vn.archived_at and vn.archived_by == family["dad"] and vn.archived_order == 10
    assert DocumentField.objects.get(document=doc, key="visa_number").value == "7012345678"  # value kept
    detail = clients["son1"].get(f"/api/documents/{doc.id}").json()
    assert "visa_number" not in [f["key"] for f in detail["template"]]
    assert "visa_number" not in [f["key"] for f in detail["fields"]] and detail["archived_values"] == 1
    # no longer required, extracted or sent to AI
    t.template_fields.filter(key="visa_number").update(required=True)
    doc.refresh_from_db()
    assert "Visa Number" not in doctypes.details_status(doc)["missing_required"]
    assert "visa_number" not in doctypes.allowed_extract_keys(doc)
    assert "visa_number" not in [d["key"] for d in direct.template_details(doc)]
    t.refresh_from_db()
    assert "visa_number" not in t.ocr_fields
    from apps.library.extraction import Proposal

    assert doctypes.store_proposals(doc, [Proposal("visa_number", "1111111111", "ocr", 0.9, [], "")]) == 0
    # Archived Fields lists it with the number of documents holding a value (no content)
    data = admin.get("/api/document-types/admin").json()
    row = next(f for f in next(x for x in data["types"] if x["id"] == t.id)["fields"] if f["key"] == "visa_number")
    assert row["archived"] and row["documents_with_values"] == 1 and row["archived_by"] and "7012345678" not in json.dumps(row)
    assert AuditEvent.objects.filter(action="settings.document_type_field_archive").exists()
    # archiving all fields never falls back to "any field" behaviour
    for f in t.template_fields.filter(enabled=True):
        doctypes.archive_field(actor=family["dad"], field=f)
    assert doctypes.allowed_extract_keys(doc) == set() and doctypes.role_keys(doc) == {}


def test_at476_archived_metadata_only_on_request_and_for_viewers(family, clients):
    t = _visa_type()
    doc = _typed_doc(clients, family, t, {"visa_number": "7012345678"})
    doctypes.archive_field(actor=family["dad"], field=t.template_fields.get(key="visa_number"))
    assert "7012345678" not in json.dumps(clients["son1"].get(f"/api/documents/{doc.id}").json())  # hidden by default
    r = clients["son1"].get(f"/api/documents/{doc.id}/archived-metadata")
    assert r.status_code == 200
    assert r.json()["values"] == [{"key": "visa_number", "label": "Visa Number", "value": "7012345678", "status": "confirmed",
                                   "source": "manual", "source_label": "Manual", "archived_at": r.json()["values"][0]["archived_at"],
                                   "identifier": False}]
    assert clients["son2"].get(f"/api/documents/{doc.id}/archived-metadata").status_code == 404  # no access, no leak


def test_at477_restore_brings_back_the_same_field_without_duplicates(family, clients):
    admin = clients["dad"]
    t = _visa_type()
    doc = _typed_doc(clients, family, t, {"visa_number": "7012345678"})
    vn = t.template_fields.get(key="visa_number")
    admin.post(f"/api/document-types/{t.id}/fields/{vn.id}/archive")
    r = admin.post(f"/api/document-types/{t.id}/fields/{vn.id}/restore")
    assert r.status_code == 200, r.content
    vn.refresh_from_db()
    assert vn.enabled and vn.archived_at is None and vn.order == 10  # its previous position was still free
    assert DocumentTypeField.objects.filter(doc_type=t, key="visa_number").count() == 1
    assert DocumentField.objects.filter(document=doc, key="visa_number").count() == 1
    detail = clients["son1"].get(f"/api/documents/{doc.id}").json()
    assert next(f for f in detail["fields"] if f["key"] == "visa_number")["value"] == "7012345678"
    doc.refresh_from_db()
    assert "visa_number" in doctypes.allowed_extract_keys(doc)
    # when its position was taken meanwhile it is added at the end
    admin.post(f"/api/document-types/{t.id}/fields/{vn.id}/archive")
    t.template_fields.filter(key="issuer").update(order=10)
    admin.post(f"/api/document-types/{t.id}/fields/{vn.id}/restore")
    vn.refresh_from_db()
    assert vn.order == max(t.template_fields.filter(enabled=True).values_list("order", flat=True))
    assert admin.post(f"/api/document-types/{t.id}/fields/{vn.id}/restore").status_code == 400  # not archived
    assert AuditEvent.objects.filter(action="settings.document_type_field_restore").count() == 2


def test_at478_permanent_deletion_is_protected(family, clients):
    from apps.accounts.models import User

    t = _visa_type()
    docs = [_typed_doc(clients, family, t, {"visa_number": f"70123456{i}"}) for i in range(2)]
    vn = t.template_fields.get(key="visa_number")
    url = f"/api/document-types/{t.id}/fields/{vn.id}"
    User.objects.filter(pk=family["mom"].pk).update(is_admin=True)  # an Administrator, not the Main Admin
    for name in ("mom", "son1"):
        assert client_for(User.objects.get(username=name)).delete(url, {"confirm": "DELETE"}, format="json").status_code == 403
    admin = clients["dad"]
    r = admin.delete(url, {"confirm": "DELETE"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "not_archived"  # Archive first
    admin.post(f"{url}/archive")
    preview = admin.get(url).json()
    assert preview["documents_with_values"] == 2 and "stored values in 2 documents" in preview["message"]
    assert "Archive is recommended" in preview["message"] and "Backups" in preview["backups_note"]
    r = admin.delete(url, {}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "confirm_required" and r.json()["documents_with_values"] == 2
    r = admin.delete(url, {"confirm": "DELETE"}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "stepup_required"
    assert DocumentField.objects.filter(key="visa_number").count() == 2  # nothing removed yet
    _stepup(admin)
    r = admin.delete(url, {"confirm": "DELETE", "reason": "No longer printed on visas"}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["deleted_values"] == 2
    assert not DocumentTypeField.objects.filter(pk=vn.pk).exists()
    assert not DocumentField.objects.filter(document__in=docs, key="visa_number").exists()
    ev = AuditEvent.objects.get(action="settings.document_type_field_delete")
    assert ev.context["documents_with_values"] == 2 and ev.context["permanent"] and "7012345" not in json.dumps(ev.context)
    assert docs[0].history.filter(action="type_field_deleted").exists()
    # the step-up confirmation was used up: a second destructive action needs a new one
    it = t.template_fields.get(key="issuer")
    admin.post(f"/api/document-types/{t.id}/fields/{it.id}/archive")
    r = admin.delete(f"/api/document-types/{t.id}/fields/{it.id}", {"confirm": "DELETE"}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "stepup_required"


# ================================================================== upgrade and release gate

def _migration(app, name):
    return importlib.import_module(f"apps.{app}.migrations.{name}")


def test_at479_upgrade_preserves_data_and_sends_nothing(family, clients, fake_ai, profile):
    t = _visa_type()
    doc = _typed_doc(clients, family, t, {"visa_number": "7012345678", "visa_type": "Single"})
    # a field switched off before the upgrade ("Shown" unchecked) becomes an archived field, values kept
    DocumentTypeField.objects.filter(doc_type=t, key="visa_type").update(enabled=False, archived_at=None, archived_order=None)
    AIJob.objects.all().delete()
    fake_ai.requests.clear()
    _migration("library", "0013_field_archive").forwards(django_apps, None)
    _migration("library", "0013_field_archive").forwards(django_apps, None)  # idempotent
    vt = DocumentTypeField.objects.get(doc_type=t, key="visa_type")
    assert vt.archived_at is not None and not vt.enabled and vt.archived_order == vt.order
    assert DocumentField.objects.get(document=doc, key="visa_type").value == "Single"
    assert DocumentTypeField.objects.filter(doc_type=t, enabled=True).count() == 4
    assert not AIJob.objects.exists() and not fake_ai.chats()  # nothing queued or sent by the upgrade
    # existing accounts get a valid default layout; a stale tile reference never breaks it
    for u in family.values():
        g = client_for(u).get("/api/dashboard/layout").json()["groups"]
        assert g[0]["id"] == "general" and g[0]["widgets"] == config.get_user(u, "me.dashboard_widgets")
    UserSetting.objects.update_or_create(user=family["mom"], key="me.dashboard_groups",
                                         defaults={"value": {"groups": [{"id": "general", "name": "General",
                                                                         "widgets": ["date", "removed_tile"]}], "known": ["date"]}})
    from apps.core import config as cfg

    cfg._invalidate(family["mom"])
    got = clients["mom"].get("/api/dashboard/layout").json()["groups"][0]["widgets"]
    assert got[0] == "date" and "removed_tile" not in got
    assert "weather" in got  # a tile added later (not known when saved) appears in General
    # processing source default is set safely; the AI migration only adds empty provenance fields
    assert config.get("ai.processing_source") == "original_fallback"
    from django.db import connection

    cols = {c.name for c in connection.introspection.get_table_description(connection.cursor(), "ai_aijob")}
    assert {"processing_source", "final_source", "fallback_used", "fallback_reason"} <= cols


def test_at480_release_gate_records_every_test_honestly():
    root = Path(__file__).resolve().parents[1] / "docs"
    report = (root / "TEST_REPORT.md").read_text()
    trace = (root / "TRACEABILITY.md").read_text()
    start = report.index("## Change set AA")
    section = report[start:report.index("\n## ", start + 5)]
    for n in range(461, 481):
        assert f"AT-{n}" in section and f"AT-{n}" in trace, n
    for line in section.splitlines():
        if "Not Executed" in line or "Blocked" in line:
            assert "Passed" not in line, line  # an unexecuted test is never reported as passed
