"""PDF/A validation of searchable copies: veraPDF when installed, built-in structural check otherwise."""
import shutil
from pathlib import Path
from unittest import mock

import pytest
from conftest import make_image_pdf, make_text_pdf, personal_root, run_jobs, upload

from apps.library import pdfa, sandbox, storage
from apps.library.models import Document

pytestmark = pytest.mark.django_db
VERAPDF = shutil.which("verapdf") or ("/opt/verapdf/verapdf" if Path("/opt/verapdf/verapdf").exists() else None)
HAS_OCR = shutil.which("tesseract") is not None


@pytest.fixture
def ocr_output(family, clients):
    r = upload(clients["son1"], personal_root(family["son1"]), name="scan.pdf", content=make_image_pdf("SYNTHETIC PERMIT\nSAMPLE"))
    run_jobs()
    v = Document.objects.get(pk=r.json()["documents"][0]["id"]).current_version
    return v, storage.resolve_derivative(v.searchable_path)


def test_builtin_rejects_plain_pdf(tmp_path, settings):
    settings.VERAPDF_CMD = "definitely-not-installed"
    p = tmp_path / "plain.pdf"
    p.write_bytes(make_text_pdf("not pdf/a"))
    report = pdfa.validate(p)
    assert report["validator"] == "builtin" and report["full_validation"] is False and not report["compliant"]
    text = " ".join(r["description"] for r in report["failed_rules"])
    assert "identification" in text and "output intent" in text and "not embedded" in text


@pytest.mark.tools
@pytest.mark.skipif(not HAS_OCR, reason="tesseract not installed")
def test_builtin_accepts_ocrmypdf_output_and_processing_records_it(ocr_output, settings):
    v, path = ocr_output
    settings.VERAPDF_CMD = "definitely-not-installed"
    report = pdfa.validate(path)
    assert report["compliant"], report
    assert v.pdfa_report and v.pdfa_report["compliant"] and v.pdfa


@pytest.mark.tools
@pytest.mark.skipif(not (HAS_OCR and VERAPDF), reason="veraPDF or tesseract not installed")
def test_verapdf_validates_ocr_output_and_rejects_plain_pdf(ocr_output, settings, tmp_path):
    _v, path = ocr_output
    settings.VERAPDF_CMD = VERAPDF
    report = pdfa.validate(path)
    assert report["validator"] == "verapdf" and report["full_validation"] and report["compliant"], report
    assert "2b" in report["profile"].lower()
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(make_text_pdf("plain"))
    bad = pdfa.validate(plain)
    assert bad["validator"] == "verapdf" and not bad["compliant"] and bad["failed_rules"]


def test_verapdf_failure_falls_back_to_structural_check(tmp_path, settings):
    settings.VERAPDF_CMD = "/bin/true"
    p = tmp_path / "plain.pdf"
    p.write_bytes(make_text_pdf("x"))
    with mock.patch.object(sandbox, "run", side_effect=sandbox.ToolError("verapdf timed out")):
        report = pdfa.validate(p)
    assert report["validator"] == "builtin" and "veraPDF could not run" in report["note"]


def test_unusable_verapdf_is_skipped_or_falls_back(tmp_path, settings):
    """Field failure: /opt/verapdf installed root-only -> PermissionError must not break processing."""
    p = tmp_path / "plain.pdf"
    p.write_bytes(make_text_pdf("x"))
    no_exec = tmp_path / "verapdf"
    no_exec.write_text("#!/bin/sh\n")
    no_exec.chmod(0o644)
    settings.VERAPDF_CMD = str(no_exec)
    assert pdfa.verapdf_cmd() is None
    assert pdfa.validate(p)["validator"] == "builtin"
    settings.VERAPDF_CMD = "/bin/true"
    with mock.patch.object(sandbox, "run", side_effect=PermissionError(13, "Permission denied", "/opt/verapdf/verapdf")):
        report = pdfa.validate(p)
    assert report["validator"] == "builtin" and "Permission denied" in report["note"]


@pytest.mark.tools
@pytest.mark.skipif(not HAS_OCR, reason="tesseract not installed")
def test_processing_survives_a_crashing_validator(family, clients):
    with mock.patch("apps.library.pdfa.validate", side_effect=RuntimeError("validator exploded")):
        r = upload(clients["son1"], personal_root(family["son1"]), name="scan.pdf", content=make_image_pdf("SYNTHETIC PERMIT"))
        run_jobs()
    v = Document.objects.get(pk=r.json()["documents"][0]["id"]).current_version
    assert v.state == "ready" and v.searchable_path and not v.pdfa, (v.state, v.error)
    assert "validator exploded" in v.pdfa_report["note"]
