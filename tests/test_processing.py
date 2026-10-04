"""AT-07, AT-08, AT-10 and AT-11 (search/similarity). Tool tests need Tesseract/OCRmyPDF/LibreOffice installed."""
import hashlib
import io
import shutil
import zipfile

import pytest
from conftest import make_image_pdf, make_text_pdf, personal_root, run_jobs, upload

from apps.library import storage
from apps.library.extraction import _check_digit, extract, parse_mrz
from apps.library.models import Document, DocumentType, SavedView

pytestmark = pytest.mark.django_db

HAS_OCR = shutil.which("tesseract") is not None
HAS_SOFFICE = shutil.which("soffice") is not None


def _one(client, folder, **kw):
    r = upload(client, folder, **kw)
    assert r.status_code == 201, r.content
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


def _mrz_line2(number, nat, dob, sex, exp):
    num = number.ljust(9, "<")
    return f"{num}{_check_digit(num)}{nat}{dob}{_check_digit(dob)}{sex}{exp}{_check_digit(exp)}".ljust(42, "<") + "<0"


def test_mrz_parser_validates_check_digits():
    l1 = "P<XXXSAMPLE<<PERSON<<<<<<<<<<<<<<<<<<<<<<<<"
    l2 = _mrz_line2("Z1234567", "XXX", "000101", "M", "261018")
    props = {p.key: p for p in parse_mrz(f"{l1}\n{l2}")}
    assert props["full_name"].value == "Person Sample"
    assert props["document_number"].value == "Z1234567" and not props["document_number"].flags
    assert props["expiry_date"].value == "2026-10-18" and props["date_of_birth"].value == "2000-01-01"
    # a misread digit is flagged, not silently trusted
    bad = l2[:3] + ("8" if l2[3] != "8" else "9") + l2[4:]
    props = {p.key: p for p in parse_mrz(f"{l1}\n{bad}")}
    assert props["document_number"].flags


def test_labelled_extraction_flags_discrepancies():
    text = "Name: SAMPLE PERSON\nDate of issue: 19/10/2026\nDate of expiry: 18/10/2016\nPassport No: Z12O4567"
    props = {p.key: p for p in extract(text, owner_names=["Unrelated Name"])}
    assert props["issue_date"].value == "2026-10-19" and props["expiry_date"].value == "2016-10-18"
    assert any("not after issue" in f for f in props["expiry_date"].flags)
    assert props["document_number"].flags  # ambiguous O/0


def test_at08_proposals_need_confirmation_before_driving_names_or_reminders(family, clients):
    ptype = DocumentType.objects.get(name="Passport")
    text = "PASSPORT\nDate of issue: 19 Oct 2016\nDate of expiry: 18 Oct 2026"
    d = _one(clients["son1"], personal_root(family["son1"]), name="p.pdf", content=make_text_pdf(text), doc_type=ptype.id)
    run_jobs()
    d.refresh_from_db()
    assert d.state == Document.NEEDS_REVIEW
    assert d.fields.get(key="expiry_date").status == "proposed"
    assert d.expiry_date is None and "(dates needed)" in d.title  # proposals do not drive name/reminders
    r = clients["son1"].post(f"/api/documents/{d.id}/fields", {"confirm_all": True}, format="json")
    assert r.status_code == 200
    d.refresh_from_db()
    assert d.expiry_date.isoformat() == "2026-10-18" and d.title.endswith("(2016–2026)") and d.state == Document.READY
    # manual entry works when parsing fails
    d2 = _one(clients["son1"], personal_root(family["son1"]), name="blank.pdf", content=make_text_pdf("nothing useful"))
    run_jobs()
    clients["son1"].post(f"/api/documents/{d2.id}/fields", {"key": "expiry_date", "value": "2027-01-31"}, format="json")
    d2.refresh_from_db()
    assert d2.expiry_date.isoformat() == "2027-01-31"


def test_born_digital_pdf_is_indexed_without_ocr(family, clients):
    d = _one(clients["son1"], personal_root(family["son1"]), content=make_text_pdf("Residence certificate for Sample household\n" * 3))
    run_jobs()
    v = d.versions.get()
    assert not v.ocr_applied and "Residence certificate" in v.text
    r = clients["son1"].get("/api/documents", {"q": "residence certificate"})
    assert r.json()["total"] == 1 and "«" in r.json()["documents"][0]["snippet"]


@pytest.mark.tools
@pytest.mark.skipif(not HAS_OCR, reason="tesseract not installed")
def test_at07_image_only_pdf_becomes_searchable_and_original_unchanged(family, clients):
    content = make_image_pdf("SYNTHETIC SAMPLE PERMIT\nHOLDER SAMPLE PERSON\nVALID UNTIL 2030")
    sha = hashlib.sha256(content).hexdigest()
    d = _one(clients["son1"], personal_root(family["son1"]), name="scan.pdf", content=content)
    run_jobs()
    v = d.versions.get()
    assert v.state == "ready", v.error
    assert v.ocr_applied and "SAMPLE" in v.text.upper()
    assert v.searchable_path and storage.resolve_derivative(v.searchable_path).exists()
    assert v.pdfa  # OCRmyPDF produced (and validated) PDF/A output
    assert hashlib.sha256(storage.resolve_original(v.storage_path).read_bytes()).hexdigest() == sha
    assert clients["son1"].get("/api/documents", {"q": "permit"}).json()["total"] == 1
    assert clients["son1"].get(f"/api/documents/{d.id}/thumbnail").status_code == 200


@pytest.mark.tools
@pytest.mark.skipif(not HAS_OCR, reason="tesseract not installed")
def test_image_upload_is_ocrd(family, clients):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1400, 500), "white")
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 60)
    except OSError:
        font = ImageFont.load_default(size=60)
    ImageDraw.Draw(img).text((60, 180), "VEHICLE REGISTRATION SAMPLE", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    d = _one(clients["son1"], personal_root(family["son1"]), name="card.png", content=buf.getvalue())
    run_jobs()
    v = d.versions.get()
    assert v.format_class == "image" and v.ocr_applied and "REGISTRATION" in v.text.upper()


def _docx_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="R1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


@pytest.mark.tools
@pytest.mark.skipif(not HAS_SOFFICE, reason="LibreOffice not installed")
def test_at10_office_preview_is_local_and_original_preserved(family, clients):
    content = _docx_bytes("Synthetic tenancy agreement sample")
    d = _one(clients["son1"], personal_root(family["son1"]), name="agreement.docx", content=content)
    run_jobs()
    v = d.versions.get()
    assert v.format_class == "office" and v.state == "ready", v.error
    assert v.preview_path and "tenancy" in v.text.lower()
    assert storage.resolve_original(v.storage_path).read_bytes() == content
    r = clients["son1"].get(f"/api/documents/{d.id}/preview")
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf"


def test_at10_dicom_bundle_export_keeps_paths_and_hashes(family, clients):
    from apps.library.models import Folder

    son1 = family["son1"]
    xray = Folder.objects.create(parent=personal_root(son1), name="Xray", owner=son1)
    study = Folder.objects.create(parent=xray, name="ST000000", owner=son1)
    dicom = b"\x00" * 128 + b"DICM" + b"synthetic-dicom-payload"
    d = _one(clients["son1"], study, name="IM000001", content=dicom)
    run_jobs()
    d.refresh_from_db()
    assert d.current_version.format_class == "dicom" and d.state == Document.UNSUPPORTED
    r = clients["son1"].get("/api/export/download", {"folder": str(xray.id)})
    data = b"".join(r.streaming_content)
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    entry = next(n for n in names if n.endswith("IM000001"))
    assert "Xray/ST000000/IM000001" in entry
    assert z.read(entry) == dicom
    assert hashlib.sha256(dicom).hexdigest() in z.read("SHA256SUMS.txt").decode()


def test_at11_autocomplete_saved_views_and_similarity_respect_permissions(family, clients):
    root1, root2 = personal_root(family["son1"]), personal_root(family["son2"])
    ptype = DocumentType.objects.get(name="Passport")
    a = _one(clients["son1"], root1, name="a.pdf", content=make_text_pdf("passport renewal application sample kingdom embassy"), doc_type=ptype.id)
    b = _one(clients["son1"], root1, name="b.pdf", content=make_text_pdf("passport renewal form sample embassy appointment"), doc_type=ptype.id)
    c = _one(clients["son2"], root2, name="c.pdf", content=make_text_pdf("passport renewal secret sample embassy"), doc_type=ptype.id)
    run_jobs()
    sug = clients["son1"].get("/api/search/autocomplete", {"q": "emb"}).json()["suggestions"]
    assert "embassi" in sug or any("emb" in s.lower() for s in sug)
    sim = clients["son1"].get(f"/api/documents/{a.id}/similar").json()["similar"]
    ids = [s["id"] for s in sim]
    assert str(b.id) in ids and str(c.id) not in ids
    r = clients["son1"].post("/api/views", {"name": "Passports", "query": {"q": "passport"}, "show_on_dashboard": True}, format="json")
    assert r.status_code == 201
    views = clients["son1"].get("/api/views").json()["views"]
    assert views[0]["count"] == 2  # son2's matching document is not counted
    assert clients["son1"].get("/api/dashboard").json()["saved_views"][0]["count"] == 2
    assert SavedView.objects.count() == 1
