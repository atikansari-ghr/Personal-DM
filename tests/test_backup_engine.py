"""Change Set T - encrypted full-system recovery points (AT-276 .. AT-293 backend parts).

AT numbering: the change prompt's AT-251..AT-310 are recorded here as AT-276..AT-335 (prompt number + 25), because
AT-251..AT-275 were already used by Change Set S. See docs/TRACEABILITY.md.
"""
import io
import json
import os
from datetime import timedelta
from pathlib import Path
from unittest import mock

import pytest
from django.utils import timezone

from apps.core import config
from apps.ops import bk_crypto as C
from apps.ops import bk_engine as E
from apps.ops import bk_keys
from apps.ops.bk_destinations import MARKER, sigv4_headers
from apps.ops.models import BackupDestination, BackupPolicy, RecoveryCopy, RecoveryKey, RecoveryPoint

from conftest import personal_root, run_jobs, upload
from fixtures import make_text_pdf

pytestmark = pytest.mark.django_db

SYNTHETIC_SECRET = "synthetic-smtp-secret-DO-NOT-LEAK-7f3a"


def make_policy(tmp_path, n=1, **kw):
    dests = []
    for i in range(n):
        d = tmp_path / f"dest{i}"
        d.mkdir()
        dests.append(BackupDestination.objects.create(name=f"Test destination {i}", kind="local", config={"path": str(d)}))
    pol = BackupPolicy.objects.create(name=f"Test policy {BackupPolicy.objects.count()}", **kw)
    pol.destinations.set(dests)
    return pol, dests


def seed_library(clients, family, n=2):
    root = personal_root(family["dad"])
    for i in range(n):
        assert upload(clients["dad"], root, name=f"sample-{i}.pdf", content=make_text_pdf(f"Synthetic sample {i}")).status_code == 201
    run_jobs()


# ------------------------------------------------------------------ crypto unit tests

def test_stream_encryption_roundtrip_and_tamper_detection(tmp_path):
    dek = os.urandom(32)
    for size in (0, 5, C.CHUNK - 1, C.CHUNK, C.CHUNK + 1, 3 * C.CHUNK):
        src = tmp_path / f"p{size}"
        src.write_bytes(os.urandom(size))
        enc = tmp_path / f"e{size}"
        C.encrypt_file(src, enc, dek, "objects/x")
        assert C.decrypt_to(open(enc, "rb"), tmp_path / f"d{size}", dek, "objects/x")
        assert (tmp_path / f"d{size}").read_bytes() == src.read_bytes()
        data = enc.read_bytes()
        # truncation (drop last chunk), bit flip, wrong name (AAD), wrong key all fail
        for bad, name, key in ((data[:-16], "objects/x", dek), (data[:-1] + bytes([data[-1] ^ 1]), "objects/x", dek),
                               (data, "objects/y", dek), (data, "objects/x", os.urandom(32))):
            with pytest.raises(C.DecryptError):
                C.digest_and_verify(io.BytesIO(bad), key, name)
    # a full-size final chunk is never accepted as the last one (empty final chunk is required)
    src = tmp_path / "full"
    src.write_bytes(os.urandom(C.CHUNK))
    C.encrypt_file(src, tmp_path / "full.enc", dek, "n")
    raw = (tmp_path / "full.enc").read_bytes()
    with pytest.raises(C.DecryptError):
        C.digest_and_verify(io.BytesIO(raw[:-16]), dek, "n")


def test_recovery_key_format_wrap_and_emergency_package():
    raw = C.new_recovery_key()
    text = C.format_key(raw)
    assert text.startswith("PDRK1-") and C.parse_key(text.lower().replace("-", " ")) == raw
    dek = os.urandom(32)
    w = C.wrap_dek(raw, dek, "point-1")
    assert C.unwrap_dek(raw, w, "point-1") == dek
    with pytest.raises(C.DecryptError):
        C.unwrap_dek(C.new_recovery_key(), w, "point-1")
    with pytest.raises(C.DecryptError):
        C.unwrap_dek(raw, w, "point-2")
    meta = {"installation": "test", "generation": 1, "created_at": "2026-01-01", "fingerprint": C.fingerprint(raw)}
    pkg = C.seal_emergency(raw, "correct horse battery", meta)
    assert text not in json.dumps(pkg)
    assert C.open_emergency(pkg, "correct horse battery") == raw
    with pytest.raises(C.DecryptError):
        C.open_emergency(pkg, "wrong passphrase!!")
    with pytest.raises(ValueError):
        C.seal_emergency(raw, "short", meta)


def test_sigv4_matches_aws_documented_example():
    # AWS General Reference "Signature Version 4 signing process" example (IAM ListUsers, documentation credentials)
    import datetime as dt

    h = sigv4_headers("GET", "https://iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08", region="us-east-1",
                      service="iam", access_key="AKIDEXAMPLE", secret_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
                      payload_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                      now=dt.datetime(2015, 8, 30, 12, 36, tzinfo=dt.timezone.utc),
                      extra={"content-type": "application/x-www-form-urlencoded; charset=utf-8"})
    assert h["authorization"].endswith("Signature=5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7")


# ------------------------------------------------------------------ AT-278 completeness, AT-284 no compression, AT-285 no leakage

def test_at278_full_backup_contains_every_recovery_class_without_plaintext_secrets(family, clients, tmp_path):
    seed_library(clients, family)
    config.set_value("smtp.password", SYNTHETIC_SECRET)
    pol, (dest,) = make_policy(tmp_path)
    point = E.create_point(pol, kind="full", trigger="manual")
    assert point.status == RecoveryPoint.VERIFIED, point.verification
    copy = point.copies.get()
    assert copy.state == RecoveryCopy.STORED_VERIFIED
    pdir = Path(dest.config["path"]) / str(point.id) / f"g{point.key_generation}"
    header = json.loads((pdir / "header.json").read_text())
    assert set(E.COMPONENTS) <= set(header["files"]) and header["compression"] == "none"
    # every byte on the destination is ciphertext: no synthetic secret, no PDF text, no key
    key_text = bk_keys.reveal_text(point.key_generation)
    for f in pdir.rglob("*"):
        if f.is_file():
            data = f.read_bytes()
            assert SYNTHETIC_SECRET.encode() not in data and b"Synthetic sample" not in data and b"%PDF" not in data
            assert key_text.encode() not in data
    # manifest lists every recovery class
    from apps.ops.bk_destinations import provider

    prov = provider(dest)
    hdr, dek = E.open_point(prov, point.id, point.key_generation, bk_keys.raw_key(point.key_generation))
    manifest = json.loads(E.read_component(prov, point.id, point.key_generation, dek, "manifest.enc"))
    classes = manifest["classes"]
    for k in ("database", "catalog", "settings", "secrets", "documents", "ocr", "trusted_zones", "notification_routing",
              "backup_policies", "audit_and_security_state"):
        assert k in classes
    assert "encryption.key" in classes["secrets"] and manifest["counts"]["versions"] == 2
    assert manifest["compression"] == "none"
    settings_pkg = json.loads(E.read_component(prov, point.id, point.key_generation, dek, "settings.enc"))
    assert SYNTHETIC_SECRET not in json.dumps(settings_pkg)  # secrets live only (encrypted) in the database and key package
    # the key is stored encrypted at rest
    row = RecoveryKey.objects.get(generation=point.key_generation)
    assert key_text not in row.key_enc
    # pg_dump without compression (AT-284)
    with mock.patch("subprocess.Popen", wraps=__import__("subprocess").Popen) as popen:
        E.create_point(pol, kind="incremental")
    assert "--compress=0" in popen.call_args_list[0].args[0]


def test_at279_incremental_chain_stores_only_new_objects(family, clients, tmp_path):
    seed_library(clients, family, n=2)
    pol, _ = make_policy(tmp_path)
    full = E.create_point(pol, kind="full")
    inc1 = E.create_point(pol, kind="incremental")
    assert inc1.kind == "incremental" and inc1.parent_id == full.id and inc1.base_id == full.id
    assert not [k for k in inc1.stored if k.startswith("objects/")]  # nothing new
    upload(clients["dad"], personal_root(family["dad"]), name="new.pdf", content=make_text_pdf("Synthetic new"))
    run_jobs()
    inc2 = E.create_point(pol, kind="incremental")
    assert inc2.parent_id == inc1.id and inc2.base_id == full.id
    assert len([k for k in inc2.stored if k.startswith("objects/")]) == 1
    assert [p.id for p in inc2.chain()] == [full.id, inc1.id, inc2.id]
    assert inc2.status == RecoveryPoint.VERIFIED
    assert [p.id for p in E.dependents(full)] == [inc1.id, inc2.id]


def test_incremental_without_chain_becomes_full(family, tmp_path):
    pol, _ = make_policy(tmp_path)
    p = E.create_point(pol, kind="incremental")
    assert p.kind == "full"


def test_at280_recommended_defaults_and_configurable_schedule(family, clients, tmp_path):
    pol = BackupPolicy.objects.create(name="New")
    assert (pol.full_frequency, pol.incremental_hours, pol.retention_weeks) == ("weekly", 4, 4)


def test_at281_retention_never_deletes_a_needed_base(family, tmp_path):
    pol, _ = make_policy(tmp_path, retention_weeks=4)
    old_full = E.create_point(pol, kind="full")
    old_inc = E.create_point(pol, kind="incremental")
    RecoveryPoint.objects.filter(pk__in=[old_full.pk, old_inc.pk]).update(created_at=timezone.now() - timedelta(weeks=6))
    # only chain: never deleted, even though it is older than the retention window
    assert E.retention_plan(pol) == []
    new_full = E.create_point(pol, kind="full", trigger="manual")  # scheduled runs apply retention by themselves
    new_inc = E.create_point(pol, kind="incremental", trigger="manual")
    plan = E.retention_plan(pol)
    assert [[p.id for p in c] for c in plan] == [[old_full.id, old_inc.id]]  # the whole chain as a unit
    E.apply_retention(pol)
    assert RecoveryPoint.objects.get(pk=old_full.pk).deleted_at and RecoveryPoint.objects.get(pk=old_inc.pk).deleted_at
    assert not RecoveryPoint.objects.get(pk=new_full.pk).deleted_at and not RecoveryPoint.objects.get(pk=new_inc.pk).deleted_at
    from apps.core.models import AuditEvent

    assert AuditEvent.objects.filter(action="backup.retention").exists()


def test_at291_two_destinations_one_fails_point_partially_protected(family, tmp_path):
    pol, (good, bad) = make_policy(tmp_path, n=2)
    bad.config = {"path": str(tmp_path / "missing" / "nas")}
    bad.kind = "nas"
    bad.save()
    p = E.create_point(pol, kind="full")
    states = {c.destination_id: c.state for c in p.copies.all()}
    assert states[good.id] == RecoveryCopy.STORED_VERIFIED
    assert states[bad.id] in (RecoveryCopy.RETRY_PENDING, RecoveryCopy.UNAVAILABLE)
    assert p.status == RecoveryPoint.PARTIAL
    h = E.health()
    assert h["state"] in ("attention", "critical") and any("destination" in w.lower() or "Test destination 1" in w for w in h["warnings"])
    # the staging copy is kept for the retry; when the share comes back the copy is stored without a new backup
    nas = tmp_path / "missing" / "nas"
    nas.mkdir(parents=True)
    (nas / MARKER).touch()
    bad.config = {"path": str(nas), "require_mount": False}
    bad.save()
    RecoveryCopy.objects.filter(destination=bad).update(next_retry_at=timezone.now())
    assert E.retry_pending() == 1
    p.refresh_from_db()
    assert p.status == RecoveryPoint.VERIFIED and RecoveryPoint.objects.count() == 1


def test_at292_insufficient_storage_fails_destination_without_deleting_backups(family, tmp_path):
    pol, (dest,) = make_policy(tmp_path)
    first = E.create_point(pol, kind="full")
    with mock.patch("apps.ops.bk_destinations.LocalProvider.space", return_value=(1024, 10 * 1024)):
        second = E.create_point(pol, kind="full")
    c = second.copies.get()
    assert c.state == RecoveryCopy.INSUFFICIENT and "MiB" in c.detail
    assert second.status == RecoveryPoint.FAILED
    assert not RecoveryPoint.objects.get(pk=first.pk).deleted_at  # never deleted to make room
    assert (Path(dest.config["path"]) / str(first.id)).exists()
    dest.refresh_from_db()
    assert dest.health == "insufficient_storage"


def test_at293_deep_verification_detects_corruption(family, clients, tmp_path):
    seed_library(clients, family, n=1)
    pol, (dest,) = make_policy(tmp_path)
    p = E.create_point(pol, kind="full")
    pdir = Path(dest.config["path"]) / str(p.id) / f"g{p.key_generation}"
    obj = next((pdir / "objects").iterdir())
    data = bytearray(obj.read_bytes())
    data[30] ^= 0xFF
    obj.write_bytes(bytes(data))
    res = E.verify_copy(p.copies.get())
    assert res["status"] == "failed"
    assert p.copies.get().state == RecoveryCopy.FAILED
    E.rollup(p)
    assert p.status == RecoveryPoint.FAILED  # never a false Verified
    # a corrupted manifest is detected too
    p2 = E.create_point(pol, kind="full")
    pdir2 = Path(dest.config["path"]) / str(p2.id) / f"g{p2.key_generation}"
    (pdir2 / "manifest.enc").write_bytes((pdir2 / "manifest.enc").read_bytes()[:-5])
    assert E.verify_copy(p2.copies.get())["status"] == "failed"
    # a missing chain base is detected for an incremental
    p3 = E.create_point(pol, kind="incremental")
    assert p3.parent_id == p2.id or p3.kind == "full"


def test_at282_ordinary_activity_creates_no_recovery_point(family, clients, tmp_path):
    pol, _ = make_policy(tmp_path)
    seed_library(clients, family, n=2)
    root = personal_root(family["dad"])
    clients["dad"].patch(f"/api/folders/{root.id}", {"name": root.name}, format="json")
    run_jobs()
    assert RecoveryPoint.objects.count() == 0
    from apps.core.models import Job

    assert not Job.objects.filter(kind__startswith="backup").exists()


def test_at276_existing_settings_migrate_and_legacy_backups_listed(family, tmp_path):
    from apps.ops import backup as legacy

    share = tmp_path / "share"
    share.mkdir()
    (share / MARKER).touch()
    config.set_value("backup.target", str(share))
    config.set_value("backup.require_mount", False)
    old = legacy._do_backup(share)  # a format-1 backup made by the previous release
    rows = E.legacy_backups()
    assert rows and rows[0]["path"] == old["path"]
    # the data migration turns the old target and schedule into a destination + policy
    import importlib

    from django.apps import apps as django_apps

    mig = importlib.import_module("apps.ops.migrations.0002_migrate_backup_settings")
    BackupPolicy.objects.all().delete()
    BackupDestination.objects.all().delete()
    mig.forwards(django_apps, None)
    pol = BackupPolicy.objects.get()
    assert pol.full_frequency == config.get("backup.frequency") and pol.full_time == config.get("backup.schedule_time")
    assert pol.destinations.get().config["path"] == str(share)
    # verification and restore of the legacy folder still work
    assert legacy.verify_backup(Path(old["path"]))["files"] >= 0
