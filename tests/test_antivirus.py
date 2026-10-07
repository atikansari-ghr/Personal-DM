"""Antivirus with ClamAV (Change Set M, AT-138..AT-145, AT-160 for antivirus). Uses tests/fake_clamd.py and the
standard EICAR test string — never real malware."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import client_for, personal_root, run_jobs, upload
from django.conf import settings

from apps.core import config
from apps.core.models import AuditEvent
from apps.library.models import Document, DocumentVersion
from apps.notify.models import Notification
from apps.security import antivirus as av
from apps.security.models import AvScanRun
from fake_clamd import EICAR, FakeClamd

pytestmark = pytest.mark.django_db


@pytest.fixture
def clamd(tmp_path):
    sock = str(Path("/tmp") / f"pd-clamd-{tmp_path.name[-20:]}.sock")
    srv = FakeClamd(sock)
    config.set_value("antivirus.enabled", True)
    config.set_value("antivirus.socket", sock)
    yield srv
    srv.stop()


def _doc(client, user, name="note.txt", content=b"harmless synthetic text\n"):
    r = upload(client, personal_root(user), name=name, content=content)
    assert r.status_code == 201, r.content
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


def _admin_notices(user, event):
    return Notification.objects.filter(user=user, kind=event)


def test_at138_upload_is_usable_at_once_and_scanned_in_the_background(family, clients, clamd):
    doc = _doc(clients["son1"], family["son1"])
    v = doc.current_version
    assert v.av_status == "pending"  # the upload request did not wait for ClamAV
    assert clamd.scans == 0
    r = clients["son1"].get(f"/api/documents/{doc.id}/file")
    assert r.status_code == 200 and b"".join(r.streaming_content) == b"harmless synthetic text\n"
    row = clients["son1"].get(f"/api/documents/{doc.id}").json()
    assert row["current_version"]["antivirus"]["status"] == "pending"
    run_jobs()
    v.refresh_from_db()
    assert v.av_status == "clean" and v.av_engine.startswith("ClamAV 1.4.3/27800") and v.av_scanned_at
    assert clamd.scans == 1
    listing = clients["son1"].get(f"/api/documents?folder={doc.folder_id}").json()["documents"]
    assert listing[0]["av_status"] == "clean"


def test_at139_scanner_unavailable_keeps_the_file_and_warns(family, clients, clamd):
    clamd.stop()
    doc = _doc(clients["son1"], family["son1"])
    run_jobs()
    v = doc.current_version
    v.refresh_from_db()
    assert v.av_status == "not_scanned" and "not reachable" in v.av_detail
    assert clients["son1"].get(f"/api/documents/{doc.id}/file").status_code == 200
    assert AuditEvent.objects.filter(action="antivirus.unavailable").exists()
    assert _admin_notices(family["dad"], "antivirus.unavailable").exists()
    assert not _admin_notices(family["son1"], "antivirus.unavailable").exists()  # administrators only


def test_at140_eicar_is_quarantined_and_blocked(family, clients, clamd, settings):
    son, admin = clients["son1"], clients["dad"]
    doc = _doc(son, family["son1"], name="eicar.txt", content=EICAR + b"\n")
    original = Path(settings.ORIGINALS_DIR) / doc.current_version.storage_path
    assert original.exists()
    run_jobs()
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    assert v.av_status == "quarantined" and v.av_signature == "Eicar-Test-Signature"
    assert not original.exists()
    qfile = Path(settings.DATA_DIR) / "quarantine" / v.av_quarantine_path
    assert qfile.exists() and oct(qfile.stat().st_mode)[-3:] == "400"
    for url in (f"/api/documents/{doc.id}/file", f"/api/documents/{doc.id}/file?download=1", f"/api/documents/{doc.id}/preview"):
        r = son.get(url)
        assert r.status_code == 423 and r.json()["code"] == "quarantined"
        assert admin.get(url).status_code == 423  # nobody gets the binary, administrators included
    r = son.post(f"/api/documents/{doc.id}/ocr", {"sources": [{"version": str(v.id), "pages": ""}], "languages": ["eng"]}, format="json")
    assert r.status_code == 400 and "quarantine" in r.json()["error"]
    meta = son.get(f"/api/documents/{doc.id}").json()  # metadata stays so the record can be managed
    assert meta["current_version"]["antivirus"]["status"] == "quarantined" and meta["current_version"]["antivirus"]["blocked"]
    note = _admin_notices(family["dad"], "antivirus.threat").get()
    assert "Eicar-Test-Signature" in note.body and "eicar" in note.body.lower()
    assert AuditEvent.objects.filter(action="antivirus.quarantine", target_id=str(v.id)).exists()
    # the critical event cannot be turned off
    config.set_value("notifications.critical_events", [])
    assert "antivirus.threat" in config.get("notifications.critical_events")
    # integrity check does not report the quarantined original as missing; backups skip it
    from apps.ops import integrity

    assert not [p for p in integrity.check(verify_checksums=False)["problems"] if p.get("version") == str(v.id)]


def test_at141_only_the_main_administrator_releases_with_confirmation_and_reason(family, clients, clamd, settings):
    from apps.accounts.models import User

    doc = _doc(clients["son1"], family["son1"], name="eicar.com", content=EICAR)
    run_jobs()
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    User.objects.filter(pk=family["mom"].pk).update(is_admin=True)  # an Administrator, not the main administrator
    mom = client_for(User.objects.get(pk=family["mom"].pk))
    url = f"/api/security/antivirus/quarantine/{v.id}/release"
    assert mom.post(url, {"confirm": True, "reason": "Known test file from our lab"}, format="json").status_code == 403
    assert clients["son1"].post(url, {"confirm": True, "reason": "x" * 20}, format="json").status_code == 403
    admin = clients["dad"]
    assert admin.post(url, {"reason": "Known test file from our lab"}, format="json").json()["code"] == "confirm_required"
    assert admin.post(url, {"confirm": True, "reason": "ok"}, format="json").json()["code"] == "reason_required"
    r = admin.post(url, {"confirm": True, "reason": "Known test file from our lab"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "released" and r.json()["released_by"] == family["dad"].display_name
    v.refresh_from_db()
    assert (Path(settings.ORIGINALS_DIR) / v.storage_path).read_bytes() == EICAR
    assert clients["son1"].get(f"/api/documents/{doc.id}/file").status_code == 200
    ev = AuditEvent.objects.get(action="antivirus.release")
    assert ev.actor_id == family["dad"].pk and ev.context["reason_length"] >= 10
    assert _admin_notices(family["mom"], "antivirus.released").exists()  # Administrators are told too


def test_at142_signature_status_update_now_and_stale_alerts(family, clients, clamd, settings):
    admin = clients["dad"]
    h = admin.get("/api/security/antivirus?refresh=1").json()
    assert h["health"]["status"] == "ok" and h["signatures"]["version"] == "27800" and not h["signatures"]["stale"]
    # Update now needs the root host helper; without it the reason is explicit
    r = admin.post("/api/security/antivirus/update")
    assert r.status_code == 409 and "personaldocs repair" in r.json()["error"]
    hostdir = Path(settings.DATA_DIR) / "host"
    hostdir.mkdir(parents=True)
    (hostdir / "helper.json").write_text('{"installed": true}')
    r = admin.post("/api/security/antivirus/update")
    assert r.status_code == 202
    import json

    req = json.loads((hostdir / "request.json").read_text())
    assert req["action"] == "freshclam" and set(req) == {"id", "action", "requested_at", "requested_by"}
    assert admin.post("/api/security/antivirus/update").status_code == 409  # no duplicate request
    # the helper reports a failure -> critical event
    (hostdir / "freshclam.json").write_text(json.dumps({"id": req["id"], "action": "freshclam", "state": "failed", "ok": False,
                                                        "error": "Can't connect to port 443", "finished_at": "2026-10-07T01:00:00+00:00"}))
    st = admin.get("/api/security/antivirus/update/status").json()
    assert st["state"] == "failed"
    assert _admin_notices(family["dad"], "antivirus.definitions").exists()
    # definitions older than the critical limit
    clamd.signatures_date = datetime.now(timezone.utc) - timedelta(days=9)
    h = av.check_health_and_alert()
    assert h["status"] == "critical_stale" and h["critically_stale"]
    assert _admin_notices(family["dad"], "antivirus.definitions").count() >= 2


def test_at143_files_over_the_size_limit_are_kept_and_reported(family, clients, clamd):
    config.set_value("antivirus.max_scan_mb", 1)
    doc = _doc(clients["son1"], family["son1"], name="big.bin", content=b"0" * (1024 * 1024 + 10))
    run_jobs()
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    assert v.av_status == "size_limit" and "1 MB" in v.av_detail
    assert clamd.scans == 0  # never claimed clean
    assert clients["son1"].get(f"/api/documents/{doc.id}/file").status_code == 200
    problems = clients["dad"].get("/api/security/antivirus").json()["problems"]
    assert any(p["version"] == str(v.id) and p["label"] == "Not scanned — size limit exceeded" for p in problems)
    # clamd's own StreamMaxLength also counts as a size limit, not as clean
    config.set_value("antivirus.max_scan_mb", 50)
    clamd.stream_max = 10
    doc2 = _doc(clients["son1"], family["son1"], name="two.txt", content=b"x" * 100)
    run_jobs()
    assert DocumentVersion.objects.get(pk=doc2.current_version_id).av_status == "size_limit"


def test_at144_members_see_status_only_administrators_get_controls(family, clients, clamd):
    doc = _doc(clients["son1"], family["son1"])
    run_jobs()
    son = clients["son1"]
    assert son.get(f"/api/documents/{doc.id}").json()["current_version"]["antivirus"]["status"] == "clean"
    for method, url in (("get", "/api/security/antivirus"), ("post", "/api/security/antivirus/scan"),
                        ("post", "/api/security/antivirus/update")):
        assert getattr(son, method)(url).status_code == 403
    assert "security" not in [w for w in son.get("/api/dashboard").json().get("admin_widgets", [])]
    assert clients["dad"].post("/api/security/antivirus/scan", {"document": str(doc.id)}, format="json").status_code == 202
    # a failed scan is reported, the file stays usable
    clamd.fail_next = True
    run_jobs()
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    assert v.av_status == "failed" and "Permission denied" in v.av_detail
    assert son.get(f"/api/documents/{doc.id}/file").status_code == 200


def test_at145_existing_library_scan_progress_pause_resume_and_schedule(family, clients, clamd):
    for i in range(30):
        _doc(clients["son1"], family["son1"], name=f"n{i}.txt", content=f"synthetic {i}\n".encode())
    DocumentVersion.objects.update(av_status="not_scanned", av_detail="Stored before antivirus scanning was added.")
    from apps.core.models import Job

    Job.objects.filter(kind="av_scan").delete()
    admin = clients["dad"]
    r = admin.post("/api/security/antivirus/scan", {}, format="json")
    assert r.status_code == 202 and r.json()["total"] == 30
    run_id = r.json()["id"]
    assert admin.post("/api/security/antivirus/scan", {}, format="json").status_code == 409  # one at a time
    assert admin.post(f"/api/security/antivirus/runs/{run_id}", {"action": "pause"}, format="json").json()["status"] == "paused"
    run_jobs()
    assert AvScanRun.objects.get(pk=run_id).done == 0
    assert admin.post(f"/api/security/antivirus/runs/{run_id}", {"action": "resume"}, format="json").json()["status"] == "running"
    run_jobs()
    run = AvScanRun.objects.get(pk=run_id)
    assert run.status == "done" and run.done == 30 and run.counts == {"clean": 30}
    assert DocumentVersion.objects.filter(av_status="clean").count() == 30
    overview = admin.get("/api/security/antivirus").json()
    assert overview["runs"][0]["done"] == 30 and overview["counts"]["clean"] == 30
    # schedule: disabled by default, then weekly
    assert config.get("antivirus.scan_frequency") == "disabled"
    from apps.ops import schedule

    assert schedule.next_occurrence(datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc), kind="antivirus") is None
    for k, v in {"antivirus.scan_frequency": "weekly", "antivirus.scan_weekday": "sun", "antivirus.scan_time": "02:30"}.items():
        config.set_value(k, v)
    nxt = schedule.next_occurrence(datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc), kind="antivirus")
    assert nxt.date().isoformat() == "2026-10-11" and nxt.strftime("%H:%M") == "02:30"
    started = av.scheduled_scan_tick(datetime(2026, 10, 11, 2, 31, tzinfo=timezone.utc))
    assert started and started.startswith("started")
    assert AvScanRun.objects.filter(kind="scheduled").count() == 1
    assert av.scheduled_scan_tick(datetime(2026, 10, 11, 2, 40, tzinfo=timezone.utc)) is None  # once per occurrence
    # cancel
    run = AvScanRun.objects.get(kind="scheduled")
    assert admin.post(f"/api/security/antivirus/runs/{run.id}", {"action": "cancel"}, format="json").json()["status"] == "cancelled"


def test_at160_antivirus_never_deletes_originals_automatically(family, clients, clamd, settings):
    doc = _doc(clients["son1"], family["son1"], name="eicar.txt", content=EICAR)
    run_jobs()
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    qfile = Path(settings.DATA_DIR) / "quarantine" / v.av_quarantine_path
    assert qfile.read_bytes() == EICAR  # moved, not deleted
    assert Document.objects.filter(pk=doc.pk).exists()
    # a deliberate deletion needs the main administrator and typed confirmation
    url = f"/api/security/antivirus/quarantine/{v.id}/delete"
    assert clients["dad"].post(url, {}, format="json").json()["code"] == "confirm_required"
    assert clients["dad"].post(url, {"confirm_text": "DELETE"}, format="json").status_code == 204
    assert not qfile.exists() and not Document.objects.filter(pk=doc.pk).exists()
    assert AuditEvent.objects.filter(action="antivirus.quarantine_delete").exists()
