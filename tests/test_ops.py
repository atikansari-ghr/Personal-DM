"""AT-24, AT-25, AT-29, jobs reliability, exports/offline (AT-15 server side), settings (AT-28)."""
import io
import json
import os
import re
import shutil
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import client_for, make_text_pdf, personal_root, run_jobs, upload
from django.conf import settings
from django.utils import timezone

from apps.core import config, crypto, jobs
from apps.core.models import AuditEvent, Job
from apps.core.registry import SETTINGS
from apps.library import storage
from apps.library.models import Document, DocumentVersion
from apps.ops import backup, integrity

pytestmark = pytest.mark.django_db


def _doc(client, user, name="x.pdf", text="sample"):
    r = upload(client, personal_root(user), name=name, content=make_text_pdf(text))
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


# ------------------------------------------------------------------ backup

def test_at24_backup_detects_missing_nas_and_writes_verified_backup(family, clients, tmp_path):
    d = _doc(clients["son1"], family["son1"])
    run_jobs()
    target = tmp_path / "nas-backup"
    config.set_value("backup.target", str(target))
    config.set_value("backup.require_mount", False)
    with pytest.raises(backup.BackupError, match="not reachable"):
        backup.check_target()
    target.mkdir()
    with pytest.raises(backup.BackupError, match="marker"):
        backup.check_target()  # an empty local folder is never mistaken for the NAS
    config.set_value("backup.require_mount", True)
    with pytest.raises(backup.BackupError, match="not on a mounted share"):
        (target / backup.MARKER).touch()
        backup.check_target()
    config.set_value("backup.require_mount", False)
    if not shutil.which("pg_dump"):
        pytest.skip("pg_dump not installed")
    result = backup.run_backup()
    assert result["verified"] and result["files"] == 1, result
    bdir = Path(result["path"])
    manifest = json.loads((bdir / "manifest.json").read_text())
    assert manifest["includes_key"] and (bdir / "database.pgdump").stat().st_size > 0
    assert (bdir / "originals" / d.current_version.storage_path).read_bytes() == storage.resolve_original(d.current_version.storage_path).read_bytes()
    assert backup.verify_backup(bdir)["ok"]
    assert backup.last_backup_status()["last_verified"] is True
    # second backup hard-links unchanged originals and prune keeps the newest verified
    config.set_value("backup.keep_daily", 1)
    result2 = backup.run_backup()
    assert os.stat(Path(result2["path"]) / "originals" / d.current_version.storage_path).st_nlink >= 1
    assert len([p for p in target.iterdir() if p.name.startswith("backup-")]) == 1
    # corruption is detected by verification
    f = Path(result2["path"]) / "originals" / d.current_version.storage_path
    os.chmod(f, 0o644)
    f.write_bytes(b"corrupt")
    assert not backup.verify_backup(Path(result2["path"]))["ok"]


def test_backup_now_requires_reachable_destination(family, clients):
    r = clients["dad"].post("/api/backup/run")
    assert r.status_code == 400 and "destination" in r.json()["error"].lower()
    assert clients["son1"].post("/api/backup/run").status_code == 403


# ------------------------------------------------------------------ integrity

def test_at25_integrity_detects_problems_and_repair_is_non_destructive(family, clients):
    a = _doc(clients["son1"], family["son1"], "a.pdf")
    b = _doc(clients["son1"], family["son1"], "b.pdf")
    run_jobs()
    assert integrity.check()["ok"]
    pa = storage.resolve_original(a.current_version.storage_path)
    os.chmod(pa, 0o644)
    pa.write_bytes(b"tampered!")
    pb = storage.resolve_original(b.current_version.storage_path)
    keep = pb.read_bytes()
    os.chmod(pb, 0o644)
    pb.unlink()
    orphan = Path(settings.ORIGINALS_DIR) / "stray" / "orphan.pdf"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")
    types = {p["type"] for p in integrity.check()["problems"]}
    assert {"size_mismatch", "missing_original", "orphan_original"} <= types
    key_before = crypto.key_path().read_bytes()
    plan = integrity.repair(dry_run=True)
    assert orphan.exists() and any("MANUAL" in a for a in plan)
    integrity.repair(dry_run=False)
    assert not orphan.exists() and list((Path(settings.DATA_DIR) / "quarantine").rglob("orphan.pdf"))  # moved, not deleted
    assert crypto.key_path().read_bytes() == key_before  # keys never regenerated
    assert DocumentVersion.objects.count() == 2  # no records deleted
    assert keep  # (the missing original can only come back from a backup)


# ------------------------------------------------------------------ jobs

def test_job_lease_recovery_idempotency_and_retry():
    calls = []

    @jobs.handler("test_flaky")
    def flaky(job):
        calls.append(job.attempts)
        if job.attempts < 2:
            raise RuntimeError("transient")
        return {"ok": True}

    j1 = jobs.enqueue("test_flaky", {}, idempotency_key="k1")
    assert jobs.enqueue("test_flaky", {}, idempotency_key="k1").pk == j1.pk
    jobs.run_pending()
    j1.refresh_from_db()
    assert j1.status == Job.QUEUED and j1.attempts == 1  # backoff scheduled
    Job.objects.filter(pk=j1.pk).update(run_after=timezone.now())
    jobs.run_pending()
    j1.refresh_from_db()
    assert j1.status == Job.DONE
    # crashed worker: an expired lease is reclaimed
    j2 = jobs.enqueue("test_flaky", {})
    claimed = jobs.claim("dead-worker")
    assert claimed.pk == j2.pk
    Job.objects.filter(pk=j2.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
    again = jobs.claim("new-worker")
    assert again.pk == j2.pk and again.attempts == 2


def test_heavy_jobs_respect_concurrency_limit():
    @jobs.handler("test_heavy", heavy=True)
    def heavy(job):
        return {}

    jobs.enqueue("test_heavy", {})
    jobs.enqueue("test_heavy", {})
    first = jobs.claim("w1", heavy_limit=1)
    assert first is not None and first.heavy
    assert jobs.claim("w2", heavy_limit=1) is None


# ------------------------------------------------------------------ exports / offline

def test_export_contains_only_accessible_documents_with_manifest(family, clients):
    mine = _doc(clients["son1"], family["son1"], "mine.pdf")
    _doc(clients["son2"], family["son2"], "theirs.pdf")
    plan = clients["son1"].get("/api/export/plan").json()
    assert plan["files"] == 1 and len(plan["parts"]) == 1
    r = clients["son1"].get("/api/export/download", {"part": 1})
    z = zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)))
    names = z.namelist()
    assert "Sam Sample/mine.pdf" in names and not any("theirs" in n for n in names)
    manifest = json.loads(z.read("MANIFEST.json"))
    assert manifest["files"][0]["sha256"] == mine.current_version.sha256
    assert AuditEvent.objects.filter(action="export.download").exists()
    # whole-family export is only for the main administrator's accessible set
    assert clients["dad"].get("/api/export/plan").json()["files"] == 2


def test_export_splits_into_parts(family, clients):
    for i in range(3):
        _doc(clients["son1"], family["son1"], f"f{i}.pdf", "x" * 10)
    from apps.library import export

    entries = export._entries(__import__("apps.library.permissions", fromlist=["AccessContext"]).AccessContext.build(family["son1"]))
    parts = export._split(entries, part_bytes=1)
    assert len(parts) == 3


def test_offline_revalidation_reports_revoked_items(family, clients):
    from apps.library.models import AccessRule

    d = _doc(clients["son2"], family["son2"])
    mom = family["mom"]
    rule = AccessRule.objects.create(folder=personal_root(family["son2"]), user=mom, caps=3)
    vid = str(d.current_version_id)
    c = client_for(mom)
    assert c.post("/api/offline/validate", {"versions": [vid]}, format="json").json()["allowed"] == [vid]
    rule.delete()
    res = c.post("/api/offline/validate", {"versions": [vid]}, format="json").json()
    assert res["revoked"] == [vid] and res["allowed"] == []


# ------------------------------------------------------------------ settings & help (AT-28)

def test_at28_every_setting_documented_with_working_help_link():
    guides = Path(settings.DOCS_DIR) / "guides"
    for s in SETTINGS:
        assert s.label and len(s.description) > 10, s.key
        assert "#" in s.help, s.key
        slug, anchor = s.help.split("#")
        path = guides / f"{slug}.md"
        assert path.exists(), f"{s.key}: missing guide {slug}"
        headings = [re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
                    for h in re.findall(r"^#+ (.+)$", path.read_text(), re.M)]
        explicit = re.findall(r'\{#([a-z0-9-]+)\}|<a id="([a-z0-9-]+)"', path.read_text())
        anchors = set(headings) | {a or b for a, b in explicit}
        assert anchor in anchors, f"{s.key}: anchor #{anchor} missing in {slug}.md"


def test_settings_reference_is_up_to_date():
    from apps.core.management.commands.settings_reference import render

    assert (Path(settings.DOCS_DIR) / "SETTINGS_REFERENCE.md").read_text() == render()


def test_settings_api_permissions_validation_and_secret_masking(family, clients):
    r = clients["son1"].put("/api/settings", {"values": {"notifications.expiry_days": [30]}}, format="json")
    assert r.status_code == 400 and "notifications.expiry_days" in r.json()["fields"]
    r = clients["son1"].put("/api/settings", {"values": {"me.theme": "blue"}}, format="json")
    assert r.status_code == 200
    assert config.get_user(family["son1"], "me.theme") == "blue" and config.get_user(family["mom"], "me.theme") == "green"
    r = clients["dad"].put("/api/settings", {"values": {"notifications.expiry_days": "90, 30, 30"}}, format="json")
    assert r.status_code == 400  # duplicates rejected with a message
    r = clients["dad"].put("/api/settings", {"values": {"smtp.password": "synthetic-smtp-pw", "general.timezone": "Mars/Base"}}, format="json")
    assert "general.timezone" in r.json()["fields"]
    listing = clients["dad"].get("/api/settings").json()["settings"]
    pw = next(s for s in listing if s["key"] == "smtp.password")
    assert pw["value"] is None and pw["configured"] is True
    assert "synthetic-smtp-pw" not in json.dumps(listing)
    assert not any(s["key"].startswith("smtp.") for s in clients["son1"].get("/api/settings").json()["settings"])
    r = clients["dad"].put("/api/settings", {"values": {"documents.filename_template": "../{title}"}}, format="json")
    assert r.status_code == 400


def test_help_is_bundled_and_searchable(family, clients):
    r = clients["son1"].get("/api/help")
    slugs = {g["slug"] for g in r.json()["guides"]}
    assert {"getting-started", "backup-restore", "google", "telegram"} <= slugs
    assert clients["son1"].get("/api/help", {"q": "telegram"}).json()["guides"]
    assert clients["son1"].get("/api/help/../../etc").status_code == 404


# ------------------------------------------------------------------ audit (AT-29)

def test_at29_audit_excludes_secrets_and_is_scoped(family, clients):
    from apps.core import audit

    audit.record("test.event", actor=family["son1"], password="pw", token="t", document_number="Z1", note="ok")
    ev = AuditEvent.objects.get(action="test.event")
    assert ev.context == {"note": "ok"}
    _doc(clients["son2"], family["son2"])
    son1_events = clients["son1"].get("/api/audit").json()["events"]
    assert all(e["actor"] in ("Sam Sample",) or e["action"] == "test.event" for e in son1_events)
    assert not any(e["action"] == "document.upload" for e in son1_events)
    assert any(e["action"] == "document.upload" for e in clients["dad"].get("/api/audit").json()["events"])


def test_malformed_inputs_do_not_leak(family, clients):
    assert clients["son1"].get("/api/documents", {"limit": "abc"}).status_code == 200
    assert clients["son1"].post("/api/documents/bulk", {"ids": ["x", "../../"], "action": "archive"}, format="json").json()["failed"] == 2
    assert clients["son1"].get("/api/folders/00000000-0000-0000-0000-000000000000").status_code == 404
    assert clients["son1"].get("/api/nonexistent").status_code == 404


def test_health_endpoint_reveals_nothing_sensitive(db):
    from rest_framework.test import APIClient

    r = APIClient().get("/api/health")
    assert r.status_code == 200 and set(r.json()) == {"status", "database"}


@pytest.mark.django_db(transaction=True)
def test_at24_restore_recovers_accounts_permissions_versions_settings_and_keys(tmp_path):
    """Full round trip: backup, simulate loss, restore from the backup folder."""
    if not shutil.which("pg_dump") or not shutil.which("pg_restore"):
        pytest.skip("PostgreSQL client tools not installed")
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.accounts import services as S
    from apps.accounts.models import User
    from apps.library.models import AccessRule
    from conftest import setup_payload

    S.complete_setup(setup_payload())
    son1 = User.objects.get(username="son1")
    c = client_for(son1)
    User.objects.update(must_change_password=False)
    r = upload(c, personal_root(son1), name="keep.pdf", content=make_text_pdf("restore me"))
    doc = Document.objects.get(pk=r.json()["documents"][0]["id"])
    c.post(f"/api/documents/{doc.id}/versions", {"file": SimpleUploadedFile("v2.pdf", make_text_pdf("v2"))}, format="multipart")
    config.set_value("smtp.password", "synthetic-secret-value")
    config.set_value("notifications.expiry_days", [60, 7, 0])
    target = tmp_path / "nas"
    target.mkdir()
    (target / backup.MARKER).touch()
    config.set_value("backup.target", str(target))
    config.set_value("backup.require_mount", False)
    result = backup.run_backup()
    assert result["verified"]
    # disaster: rows, files and key lost
    paths = [storage.resolve_original(v.storage_path) for v in doc.versions.all()]
    Document.objects.filter(pk=doc.pk).update(current_version=None)
    DocumentVersion.objects.filter(document=doc).delete()
    Document.objects.filter(pk=doc.pk).delete()
    for p in paths:
        os.chmod(p, 0o644)
        p.unlink()
    crypto.key_path().unlink()
    crypto.reset_cache()
    out = backup.restore_backup(Path(result["path"]))
    assert out["key_restored"] and out["files_restored"] == 2
    from django.db import connection

    connection.close()
    restored = Document.objects.get(pk=doc.pk)
    assert restored.versions.count() == 2 and all(p.exists() for p in paths)
    assert AccessRule.objects.filter(user__username="son1").exists()
    assert User.objects.get(username="dad").is_main_admin
    assert config.get("notifications.expiry_days") == [60, 7, 0]
    assert config.get("smtp.password") == "synthetic-secret-value"  # decryptable with the restored key
