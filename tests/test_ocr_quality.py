"""OCR preprocessing quality, structured fields and correction persistence (AT-93, AT-94, AT-95). Synthetic only."""
from __future__ import annotations

import io

import pytest
from conftest import personal_root, run_jobs
from django.core.files.uploadedfile import SimpleUploadedFile
from ocr_samples import samples

from apps.library import ocr
from apps.library.extraction import extract, parse_date_info
from apps.library.models import Document, DocumentField

BASELINE = ocr.Options(exif=False, gray=False, contrast=False, denoise=False, upscale=False, orientation=False, deskew=False)


def _f1(found: str, truth: str) -> float:
    import re

    def words(t):
        return [w for w in re.findall(r"[a-z0-9]+(?:[-/][a-z0-9]+)*", t.lower()) if len(w) >= 2]

    t, f = words(truth), words(found)
    if not f:
        return 0.0
    r = sum(1 for w in t if w in set(f)) / len(t)
    p = sum(1 for w in f if w in set(t)) / len(f)
    return 0.0 if r + p == 0 else 2 * r * p / (r + p)


@pytest.mark.django_db
def test_at93_preprocessing_improves_hard_samples_without_hurting_clean_ones(settings, tmp_path):
    settings.TMP_DIR = tmp_path
    data = {name: (img, truth) for name, img, truth, _ in samples()}
    hard = ["phone photo, patterned card, skewed 4°", "phone photo stored sideways (EXIF 6)", "upside-down scan",
            "rotated 90° without EXIF"]
    clean = ["clean card scan", "clean text page"]
    for name in hard:
        img, truth = data[name]
        before = _f1(ocr.recognise(img, BASELINE).text, truth)
        after = _f1(ocr.recognise(img).text, truth)
        assert after >= 0.9 and after > before, (name, before, after)
    for name in clean:
        img, truth = data[name]
        assert _f1(ocr.recognise(img).text, truth) >= 0.98, name


@pytest.mark.django_db
def test_ocr_reports_confidence_rotation_and_low_confidence_lines(settings, tmp_path):
    settings.TMP_DIR = tmp_path
    img, truth = {n: (i, t) for n, i, t, _ in samples()}["upside-down scan"]
    res = ocr.recognise(img)
    q = res.quality()
    assert q["rotation"] == 180 and q["confidence"] > 70 and "grayscale" in q["steps"]
    assert all(c >= ocr.LOW_CONFIDENCE for i, c in enumerate(q["line_confidence"]) if i not in q["low_lines"])
    # a manual rotation overrides automatic detection
    assert ocr.recognise(img, ocr.Options(rotate=90)).rotation == 90


def test_column_layout_dates_and_no_expiry_extraction():
    card = "SAMPLE ENERGY COMPANY\nSAM SAMPLE\nEMPLOYEE cikige\nBadge No Expiry Date\n145070 12-31-2030"
    got = {p.key: p for p in extract(card, owner_names=["Sam Sample"])}
    assert got["document_number"].value == "145070" and got["expiry_date"].value == "2030-12-31"
    assert got["full_name"].value == "Sam Sample"
    assert "no_expiry" not in got  # "Badge No" + "Expiry Date" is not a no-expiry statement
    resident = "SAMPLE AUTHORITY\nName: SAM SAMPLE\nID No: 2345678901\nDate of Issue: 15/03/2019\nNo Expiry Date"
    got = {p.key: p for p in extract(resident)}
    assert got["no_expiry"].value == "yes" and "expiry_date" not in got
    assert got["issue_date"].value == "2019-03-15" and not got["issue_date"].flags
    assert "issuer" not in got  # "AUTHORITY" in a heading is not an issuer value
    assert parse_date_info("05/06/2020") == (__import__("datetime").date(2020, 6, 5), True)  # ambiguous -> flagged
    assert parse_date_info("12-31-2030")[0].isoformat() == "2030-12-31"
    assert parse_date_info("March 3, 2027")[0].isoformat() == "2027-03-03"


def _upload_image(client, folder, img, name):
    buf = io.BytesIO()
    exif = img.getexif()
    img.convert("RGB").save(buf, "JPEG", quality=92, exif=exif.tobytes() if exif else b"")
    r = client.post("/api/documents", {"folder": str(folder.id), "files": [SimpleUploadedFile(name, buf.getvalue())]}, format="multipart")
    assert r.status_code == 201, r.content
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


def _fields(doc):
    return {f.key: f for f in DocumentField.objects.filter(document=doc)}


@pytest.mark.django_db(transaction=False)
def test_at94_sideways_phone_photo_gives_suggested_fields_not_confirmed(family, clients):
    son1 = family["son1"]
    img = {n: i for n, i, _t, _f in samples()}["phone photo stored sideways (EXIF 6)"]
    doc = _upload_image(clients["son1"], personal_root(son1), img, "badge.jpg")
    run_jobs()
    doc.refresh_from_db()
    f = _fields(doc)
    assert f["document_number"].value == "145070" and f["document_number"].status == "proposed"
    assert f["expiry_date"].value == "2030-12-31" and f["expiry_date"].status == "proposed"
    assert doc.expiry_date is None  # nothing drives reminders until a person confirms
    v = doc.current_version
    assert v.ocr_quality["confidence"] > 60 and "exif-orientation" in v.ocr_quality["steps"]
    detail = clients["son1"].get(f"/api/documents/{doc.id}").json()
    assert detail["current_version"]["ocr_quality"]["confidence"] > 60


@pytest.mark.django_db
def test_at94_no_expiry_statement_is_represented_not_invented(family, clients):
    son1 = family["son1"]
    img = {n: i for n, i, _t, _f in samples()}["rotated 90° without EXIF"]
    doc = _upload_image(clients["son1"], personal_root(son1), img, "resident.jpg")
    run_jobs()
    f = _fields(doc)
    assert f["no_expiry"].value == "yes" and f["no_expiry"].status == "proposed" and "expiry_date" not in f
    r = clients["son1"].post(f"/api/documents/{doc.id}/fields", {"key": "no_expiry", "value": "yes", "confirm": True}, format="json")
    assert r.status_code == 200, r.content
    doc.refresh_from_db()
    assert doc.no_expiry and doc.expiry_date is None
    row = clients["son1"].get(f"/api/documents/{doc.id}").json()
    assert row["expiry"]["level"] == "none" and row["expiry"]["label"] == "No expiry"


@pytest.mark.django_db
def test_at95_confirmed_values_survive_ocr_reruns(family, clients):
    son1 = family["son1"]
    img = {n: i for n, i, _t, _f in samples()}["clean card scan"]
    doc = _upload_image(clients["son1"], personal_root(son1), img, "card.jpg")
    run_jobs()
    c = clients["son1"]
    assert c.post(f"/api/documents/{doc.id}/fields", {"key": "expiry_date", "value": "2031-01-15", "confirm": True}, format="json").status_code == 200
    r = c.post(f"/api/documents/{doc.id}/reprocess", {"rotate": 0}, format="json")
    assert r.status_code == 200
    run_jobs()
    f = _fields(doc)["expiry_date"]
    assert f.status == "confirmed" and f.value == "2031-01-15"  # the person's correction is kept
    assert f.proposed_value == "2030-12-31" and any("suggests" in x for x in f.flags)  # the new reading is only offered
    doc.refresh_from_db()
    assert doc.expiry_date.isoformat() == "2031-01-15"
    assert c.post(f"/api/documents/{doc.id}/reprocess", {"rotate": 45}, format="json").status_code == 400
