"""Live ClamAV check (AT-140 with the real engine). Runs only when a clamd socket exists, e.g. on a Debian install or a
development machine with clamav-daemon; otherwise skipped (never reported as passed)."""
import os
from pathlib import Path

import pytest
from conftest import personal_root, run_jobs, upload

from apps.core import config
from apps.library.models import Document, DocumentVersion
from apps.security import antivirus as av
from fake_clamd import EICAR

SOCKET = os.environ.get("PD_TEST_CLAMD_SOCKET", "/run/clamav/clamd.ctl")
pytestmark = [pytest.mark.django_db, pytest.mark.skipif(not Path(SOCKET).is_socket(), reason=f"no clamd at {SOCKET}")]


def test_live_clamd_detects_eicar_and_passes_clean_files(family, clients):
    config.set_value("antivirus.enabled", True)
    config.set_value("antivirus.socket", SOCKET)
    info = av.version_info()
    assert info["engine"].startswith("ClamAV") and info["signatures"]
    son = clients["son1"]
    clean = upload(son, personal_root(family["son1"]), name="clean.txt", content=b"synthetic clean text\n").json()["documents"][0]["id"]
    bad = upload(son, personal_root(family["son1"]), name="eicar.com", content=EICAR).json()["documents"][0]["id"]
    run_jobs()
    assert Document.objects.get(pk=clean).current_version.av_status == "clean"
    v = DocumentVersion.objects.get(document_id=bad)
    assert v.av_status == "quarantined" and "Eicar" in v.av_signature
    assert son.get(f"/api/documents/{bad}/file").status_code == 423
