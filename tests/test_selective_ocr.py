"""Selective, multilingual OCR with source/page selection, removal, review queue and limits (AT-101..AT-115).

Synthetic documents only.
"""
from __future__ import annotations

import io

import pytest
from conftest import client_for, personal_root, run_jobs
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw, ImageFont

from apps.ai.models import AIJob
from apps.core import config
from apps.core.models import AuditEvent, Job
from apps.library import ocr_policy
from apps.library.models import AccessRule, Document, DocumentField, DocumentType, DocumentVersion
from apps.library import permissions as P

pytestmark = pytest.mark.django_db


def _font(name: str, size: int):
    for candidate in (name, "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _png(lines: list[str], font: str = "DejaVuSans.ttf", size=(1600, 700), rtl=False) -> bytes:
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


def _scan_pdf(pages: list[str]) -> bytes:
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


def _add_file(client, doc, name, content, additional=True) -> DocumentVersion:
    r = client.post(f"/api/documents/{doc.id}/versions", {"file": SimpleUploadedFile(name, content),
                                                          "additional": "true" if additional else ""}, format="multipart")
    assert r.status_code == 201, r.content
    return DocumentVersion.objects.get(pk=r.json()["id"])


def _manual():
    DocumentType.objects.update(ocr_mode="manual", ocr_ai_allowed=False)
    config.set_value("processing.ocr_untyped_mode", "manual")
    config.set_value("processing.ocr_untyped_ai_allowed", False)


def _ocr(client, doc, **body):
    return client.post(f"/api/documents/{doc.id}/ocr", body, format="json")


# ------------------------------------------------------------------ AT-101..103 policy

def test_at101_new_installations_default_to_manual_and_uploads_are_not_recognised(family, clients):
    from apps.core.registry import BY_KEY

    assert BY_KEY["processing.ocr_untyped_mode"].default == "manual"
    assert DocumentType._meta.get_field("ocr_mode").default == "manual"
    _manual()
    doc = _upload(clients["son1"], personal_root(family["son1"]), "scan.png", _png(["SAMPLE MEMBERSHIP CARD 4455"]))
    run_jobs()
    doc.refresh_from_db()
    assert doc.ocr_state == "not_processed" and "4455" not in doc.content_text
    assert not Job.objects.filter(kind="ocr_run").exists()
    assert doc.current_version.thumbnail_path  # the preview is still made


def test_at102_at103_administrator_configures_types_and_custom_types(family, clients):
    admin, member = clients["dad"], clients["son1"]
    assert member.get("/api/ocr/types").status_code == 403
    types = admin.get("/api/ocr/types").json()["types"]
    passport = next(t for t in types if t["name"] == "Passport")
    assert "expiry_date" in passport["ocr_fields"]
    r = admin.patch(f"/api/ocr/types/{passport['id']}", {"ocr_mode": "automatic", "ocr_languages": ["eng", "ara"]}, format="json")
    assert r.status_code == 200 and r.json()["ocr_mode"] == "automatic" and r.json()["ocr_languages"] == ["eng", "ara"]
    assert admin.patch(f"/api/ocr/types/{passport['id']}", {"ocr_mode": "always"}, format="json").status_code == 400
    assert admin.patch(f"/api/ocr/types/{passport['id']}", {"ocr_languages": ["xyz"]}, format="json").status_code == 400
    r = admin.post("/api/ocr/types", {"name": "Club card", "template": "employee_id", "ocr_mode": "manual", "ocr_languages": ["eng"]}, format="json")
    assert r.status_code == 201 and r.json()["is_custom"] and "document_number" in r.json()["ocr_fields"]
    custom = DocumentType.objects.get(name="Club card")
    _upload(member, personal_root(family["son1"]), "club.png", _png(["SAMPLE CLUB"]), doc_type=str(custom.id))
    assert admin.delete(f"/api/ocr/types/{custom.id}").status_code == 409  # in use: never deleted
    assert admin.patch(f"/api/ocr/types/{custom.id}", {"archived": True}, format="json").json()["archived"]
    assert Document.objects.filter(doc_type=custom).count() == 1  # documents keep their type
    assert AuditEvent.objects.filter(action="settings.ocr_type_update").exists()


# ------------------------------------------------------------------ AT-104..107 sources and pages

def test_at104_at105_only_selected_sources_front_and_back_as_one_job(family, clients):
    _manual()
    c = clients["son1"]
    doc = _upload(c, personal_root(family["son1"]), "front.png", _png(["SAMPLE ID FRONT", "NUMBER 7788"]))
    back = _add_file(c, doc, "back.png", _png(["SAMPLE ID BACK", "ISSUED 2021"]))
    copy = _add_file(c, doc, "copy.png", _png(["PHOTOCOPY 9911"]))
    run_jobs()
    doc.refresh_from_db()
    assert doc.current_version.original_name == "front.png" and back.is_additional  # additional files do not replace
    r = _ocr(c, doc, sources=[{"version": str(doc.current_version_id)}, {"version": str(back.id)}], languages=["eng"])
    assert r.status_code == 202 and r.json()["state"] == "queued"
    run_jobs()
    doc.refresh_from_db()
    assert doc.ocr_state in ("confirmed", "needs_review")
    assert "7788" in doc.content_text and "BACK" in doc.content_text.upper()
    assert "9911" not in doc.content_text  # the photocopy was not selected
    copy.refresh_from_db()
    assert not copy.ocr_applied and copy.text == ""
    assert {s["version"] for s in doc.ocr_sources} == {str(doc.current_version_id), str(back.id)}
    assert Job.objects.filter(kind="ocr_run").count() == 1


def test_at106_entire_pdf_pages_and_ranges(family, clients):
    _manual()
    c = clients["son1"]
    doc = _upload(c, personal_root(family["son1"]), "policy.pdf", _scan_pdf(["PAGE ONE ALPHA", "PAGE TWO BRAVO", "PAGE THREE CHARLIE"]))
    run_jobs()
    v = str(doc.current_version_id)
    assert _ocr(c, doc, sources=[{"version": v, "pages": "5"}]).status_code == 400
    assert _ocr(c, doc, sources=[{"version": v, "pages": "2-1"}]).status_code == 400
    assert _ocr(c, doc, sources=[{"version": v, "pages": "x"}]).status_code == 400
    assert _ocr(c, doc, sources=[{"version": v, "pages": "2"}]).status_code == 202
    run_jobs()
    doc.refresh_from_db()
    text = doc.content_text.upper()
    assert "BRAVO" in text and "ALPHA" not in text and "CHARLIE" not in text
    assert DocumentVersion.objects.get(pk=v).ocr_pages == "2"
    assert _ocr(c, doc, sources=[{"version": v, "pages": "1, 3"}]).status_code == 202
    run_jobs()
    doc.refresh_from_db()
    assert "ALPHA" in doc.content_text.upper() and "CHARLIE" in doc.content_text.upper()
    assert _ocr(c, doc, sources=[{"version": v}]).status_code == 202  # entire PDF -> searchable PDF/A copy
    run_jobs()
    ver = DocumentVersion.objects.get(pk=v)
    assert ver.searchable_path and all(w in ver.text.upper() for w in ("ALPHA", "BRAVO", "CHARLIE"))
    assert ocr_policy.parse_pages("1-3,2", 3) == [1, 2, 3]


def test_at107_automatic_ocr_processes_only_the_primary_source(family, clients):
    passport = DocumentType.objects.get(name="Passport")
    DocumentType.objects.filter(pk=passport.pk).update(ocr_mode="automatic")
    c = clients["son1"]
    doc = _upload(c, personal_root(family["son1"]), "front.png", _png(["SAMPLE PASSPORT 5566"]), doc_type=str(passport.id))
    run_jobs()
    doc.refresh_from_db()
    assert "5566" in doc.content_text and Job.objects.filter(kind="ocr_run").count() == 1
    _add_file(c, doc, "extra.png", _png(["EXTRA COPY 3344"]))
    run_jobs()
    doc.refresh_from_db()
    assert Job.objects.filter(kind="ocr_run").count() == 1 and "3344" not in doc.content_text  # not processed
    # a replacement current file is not processed either while an explicit primary source is set
    DocumentVersion.objects.filter(document=doc).update()
    _add_file(c, doc, "rescan.png", _png(["RESCAN 1212"]), additional=False)
    run_jobs()
    doc.refresh_from_db()
    assert Job.objects.filter(kind="ocr_run").count() == 1 and "1212" not in doc.content_text


# ------------------------------------------------------------------ AT-108..110 removal and re-runs

def test_at108_at109_remove_ocr_keeps_original_and_clears_search(family, clients):
    _manual()
    c = clients["son1"]
    doc = _upload(c, personal_root(family["son1"]), "card.png", _png(["SAMPLE KEYWORDZEBRA 8899", "Expiry Date 31/12/2030"]))
    run_jobs()
    sha = doc.current_version.sha256
    assert _ocr(c, doc, languages=["eng"]).status_code == 202
    run_jobs()
    assert c.get("/api/documents", {"q": "keywordzebra"}).json()["total"] == 1
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    searchable = v.searchable_path
    assert searchable
    assert c.delete(f"/api/documents/{doc.id}/ocr", {}, format="json").status_code == 400  # needs confirmation
    r = c.delete(f"/api/documents/{doc.id}/ocr", {"confirm": True}, format="json")
    assert r.status_code == 200 and r.json()["state"] == "removed"
    doc.refresh_from_db()
    v.refresh_from_db()
    assert v.sha256 == sha and v.text == "" and not v.ocr_applied and not v.searchable_path
    assert c.get("/api/documents", {"q": "keywordzebra"}).json()["total"] == 0
    assert not DocumentField.objects.filter(document=doc, status=DocumentField.PROPOSED).exists()
    from apps.library import storage

    assert storage.resolve_original(v.storage_path).exists()
    assert not storage.resolve_derivative(searchable).exists()
    ev = AuditEvent.objects.get(action="document.ocr_remove")
    assert "KEYWORDZEBRA" not in str(ev.context).upper()  # what was removed is not kept in the audit log


def test_at110_rerun_cannot_overwrite_confirmed_values(family, clients):
    _manual()
    c = clients["son1"]
    doc = _upload(c, personal_root(family["son1"]), "card.png", _png(["Badge No    Expiry Date", "145070      12-31-2030"]))
    run_jobs()
    _ocr(c, doc)
    run_jobs()
    assert c.post(f"/api/documents/{doc.id}/fields", {"key": "expiry_date", "value": "2031-01-15", "confirm": True}, format="json").status_code == 200
    assert _ocr(c, doc, rotate=0).status_code == 202
    run_jobs()
    f = DocumentField.objects.get(document=doc, key="expiry_date")
    assert f.status == "confirmed" and f.value == "2031-01-15" and f.proposed_value == "2030-12-31"


# ------------------------------------------------------------------ AT-111 languages

def test_at111_english_arabic_and_hindi_and_missing_packs_reported(family, clients):
    _manual()
    c = clients["son1"]
    root = personal_root(family["son1"])
    installed = set(ocr_policy.installed_languages())
    assert {"eng", "ara", "hin"} <= installed, "install tesseract-ocr-ara and tesseract-ocr-hin to run this test"
    ar = _upload(c, root, "ar.png", _png(["المملكة العربية السعودية", "بطاقة هوية"], font="NotoNaskhArabic-Regular.ttf", rtl=True))
    hi = _upload(c, root, "hi.png", _png(["भारत सरकार", "पहचान पत्र"], font="NotoSansDevanagari-Regular.ttf"))
    run_jobs()
    assert _ocr(c, ar, languages=["ara"]).status_code == 202
    assert _ocr(c, hi, languages=["hin"]).status_code == 202
    run_jobs()
    ar.refresh_from_db()
    hi.refresh_from_db()
    assert "السعودية" in ar.content_text or "العربية" in ar.content_text, ar.content_text
    assert "भारत" in hi.content_text or "सरकार" in hi.content_text, hi.content_text
    assert DocumentVersion.objects.get(pk=hi.current_version_id).ocr_quality["languages"] == ["hin"]
    # a configured language whose pack is missing is reported, and cannot be used
    config.set_value("processing.ocr_languages", ["eng", "ara", "hin", "urd"])
    if "urd" not in installed:
        assert "urd" in ocr_policy.missing_languages()
        r = _ocr(c, hi, languages=["urd"])
        assert r.status_code == 400 and "not installed" in r.json()["error"]
    assert _ocr(c, hi, languages=["fra"]).status_code == 400  # not offered by the administrator


# ------------------------------------------------------------------ AT-112..115 states, review, limits, AI

def test_at112_at113_states_permissions_and_review_queue(family, clients):
    _manual()
    son1, mom = family["son1"], family["mom"]
    doc = _upload(clients["son1"], personal_root(son1), "card.png", _png(["SAMPLE CARD", "Expiry Date 31/12/2030"]))
    run_jobs()
    AccessRule.objects.create(document=doc, user=mom, caps=P.VIEW)
    mc = client_for(mom)
    assert mc.get(f"/api/documents/{doc.id}/ocr").json()["can_run"] is False  # view only
    assert _ocr(mc, doc).status_code in (403, 404)
    assert mc.delete(f"/api/documents/{doc.id}/ocr", {"confirm": True}, format="json").status_code in (403, 404)
    assert _ocr(clients["son1"], doc).status_code == 202
    assert Document.objects.get(pk=doc.pk).ocr_state == "queued"
    run_jobs()
    doc.refresh_from_db()
    assert doc.ocr_state == "needs_review"
    items = clients["son1"].get("/api/ocr/review").json()["items"]
    assert [i["id"] for i in items] == [str(doc.id)] and items[0]["proposed"]
    assert mc.get("/api/ocr/review").json()["items"] == []  # view-only: not listed
    assert clients["son2"].get("/api/ocr/review").json()["items"] == []  # no access: not even counted
    assert clients["son1"].post(f"/api/documents/{doc.id}/ocr/reviewed").json()["state"] == "confirmed"


def test_at114_limits_queue_cancel_and_pause(family, clients):
    _manual()
    c = clients["son1"]
    root = personal_root(family["son1"])
    doc = _upload(c, root, "card.png", _png(["SAMPLE PAUSE 6060"]))
    other = _upload(c, root, "other.png", _png(["SAMPLE OTHER"]))
    run_jobs()
    config.set_value("processing.max_pages", 1)
    pdf = _upload(c, root, "two.pdf", _scan_pdf(["ONE", "TWO"]))
    run_jobs()
    assert "limit" in _ocr(c, pdf).json()["error"]
    config.set_value("processing.ocr_max_file_mb", 1)
    big = _upload(c, root, "big.png", _png(["X"], size=(4000, 4000)) + b"\0" * (1024 * 1024))
    run_jobs()
    assert "MB" in _ocr(c, big).json()["error"]
    config.set_value("processing.ocr_queue_max", 1)
    config.set_value("processing.ocr_paused", True)
    assert _ocr(c, doc).status_code == 202
    assert "queue is full" in _ocr(c, other).json()["error"]
    assert "already queued" in _ocr(c, doc).json()["error"]
    run_jobs()  # paused: the job waits, no attempt is used
    doc.refresh_from_db()
    job = Job.objects.get(kind="ocr_run", payload__document_id=str(doc.id))
    assert doc.ocr_state == "queued" and job.status == Job.QUEUED and job.attempts == 0
    assert c.post(f"/api/documents/{doc.id}/ocr/cancel").status_code == 200
    assert Job.objects.get(pk=job.pk).status == Job.CANCELLED
    config.set_value("processing.ocr_paused", False)
    assert _ocr(c, doc).status_code == 202
    Job.objects.filter(kind="ocr_run", status=Job.QUEUED).update(run_after=job.created_at)
    run_jobs()
    doc.refresh_from_db()
    assert "6060" in doc.content_text


def test_at115_local_ai_receives_only_permitted_content(family, clients, settings):
    _manual()
    config.set_value("ai.enabled", True)
    config.set_value("ai.auto_analyze", True)
    from apps.ai import service

    settings_feature = "ai.feature_ocr_assist"
    if settings_feature in __import__("apps.core.registry", fromlist=["BY_KEY"]).BY_KEY:
        config.set_value(settings_feature, True)
    c = clients["son1"]
    doc = _upload(c, personal_root(family["son1"]), "card.png", _png(["SAMPLE AI CHECK 1234"]))
    run_jobs()
    _ocr(c, doc)
    run_jobs()
    doc.refresh_from_db()
    assert "1234" in doc.content_text  # native OCR works with AI not allowed
    assert not AIJob.objects.filter(document=doc).exists()  # nothing was queued for Local AI
    assert service is not None
