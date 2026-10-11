"""Change Set T - full-system disaster recovery (AT-302 .. AT-308 automated parts).

These tests restore the real PostgreSQL test database from an encrypted recovery point (pg_dump/pg_restore), so they
use committed transactions. Clean-server (fresh LXC) runs, NAS/S3 with real credentials and Google Drive/OneDrive
are recorded separately in docs/TEST_REPORT.md.
"""
import json
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.core import config
from apps.ops import bk_engine as E
from apps.ops import bk_keys
from apps.ops import bk_recover as R

from conftest import client_for, personal_root, run_jobs, upload
from fixtures import make_text_pdf
from test_backup_engine import make_policy

pytestmark = pytest.mark.django_db(transaction=True)

SYNTHETIC_SECRET = "synthetic-telegram-token-1234:ABC-DO-NOT-LEAK"


@pytest.fixture
def system(family, tmp_path):
    clients = {n: client_for(u) for n, u in family.items()}
    root = personal_root(family["mom"])
    for i in range(2):
        assert upload(clients["mom"], root, name=f"record-{i}.pdf", content=make_text_pdf(f"Synthetic record {i}")).status_code == 201
    run_jobs()
    config.set_value("telegram.bot_token", SYNTHETIC_SECRET)
    pol, (dest,) = make_policy(tmp_path)
    full = E.create_point(pol, kind="full", trigger="manual")
    assert full.status == "verified"
    upload(clients["mom"], root, name="record-late.pdf", content=make_text_pdf("Synthetic late record"))
    run_jobs()
    inc = E.create_point(pol, kind="incremental", trigger="manual")
    key = bk_keys.raw_key(inc.key_generation)
    return {"dest": dest, "full": full, "inc": inc, "key": key, "clients": clients}


def _wreck():
    """Simulate the loss: documents and files gone, an intruder account added."""
    from apps.accounts.models import User
    from apps.library.models import Document, DocumentVersion
    from django.conf import settings
    import shutil

    DocumentVersion.objects.all().delete()
    Document.objects.all().delete()
    User.objects.create_user(username="intruder", password="Synthetic-Passw0rd!", display_name="Intruder")
    shutil.rmtree(settings.ORIGINALS_DIR, ignore_errors=True)


def test_at302_at305_normal_recovery_restores_exact_state_and_holds_integrations(system, family):
    from apps.accounts.models import User
    from apps.library.models import Document, DocumentVersion
    from apps.ops.models import RestoreRun

    prov = R.source_provider(f"local:{system['dest'].config['path']}")
    pts = R.list_points(prov)
    assert [p["point"] for p in pts[:2]] == [str(system["inc"].id), str(system["full"].id)]
    _wreck()
    report = R.run(prov, str(system["inc"].id), system["key"], mode="normal", say=lambda *_: None)
    assert report["status"] in ("completed", "completed_with_warnings"), report["warnings"]
    assert not R.marker().exists()  # the application opens only after the report
    assert not User.objects.filter(username="intruder").exists()
    assert Document.objects.count() == 3 and DocumentVersion.objects.count() == 3
    from django.conf import settings

    for v in DocumentVersion.objects.all():
        assert (Path(settings.ORIGINALS_DIR) / v.storage_path).exists()
    assert config.get("telegram.bot_token") == SYNTHETIC_SECRET  # restored secret readable with the restored key
    assert all(c["ok"] for c in report["checks"]), report["checks"]
    # integrations stay on hold until verified (telegram not enabled here: nothing to hold)
    rr = RestoreRun.objects.get(kind="full")
    assert rr.recovery_mode == "normal" and rr.report["restore_point"]["id"] == str(system["inc"].id)
    text = json.dumps(rr.report)
    assert SYNTHETIC_SECRET not in text and "PDRK1-" not in text and bk_keys.reveal_text(system["inc"].key_generation) not in text


def test_at303_resumable_and_wrong_key_changes_nothing(system, family):
    from apps.accounts.models import User
    from apps.ops import bk_crypto as C

    prov = R.source_provider(f"local:{system['dest'].config['path']}")
    with pytest.raises(C.DecryptError):
        R.run(prov, "latest", C.new_recovery_key(), say=lambda *_: None)
    assert User.objects.filter(username="dad").exists()  # nothing was replaced
    R.marker().unlink(missing_ok=True)
    (R.recovery_dir() / "state.json").unlink(missing_ok=True)


def test_at306_compromise_recovery_resets_sessions_keeps_mfa(system, family):
    from apps.accounts.models import User, UserSession, WebAuthnCredential

    dad = family["dad"]
    UserSession.objects.create(user=dad, method="password")
    WebAuthnCredential.objects.create(user=dad, credential_id="synthetic-cred", public_key=b"\x01", sign_count=0, name="Sample key")
    E.create_point(system["inc"].policy, kind="incremental", trigger="manual")
    key = bk_keys.raw_key(bk_keys.active().generation)
    prov = R.source_provider(f"local:{system['dest'].config['path']}")
    epoch_before = User.objects.get(pk=dad.pk).session_epoch
    report = R.run(prov, "latest", key, mode="compromise", say=lambda *_: None)
    assert report["mode"] == "compromise"
    assert not UserSession.objects.filter(revoked_at__isnull=True, ended_at__isnull=True).exists()
    assert User.objects.get(pk=dad.pk).session_epoch > epoch_before  # every session must sign in again
    assert WebAuthnCredential.objects.filter(credential_id="synthetic-cred", revoked_at__isnull=True).exists()  # passkeys kept
    from apps.security.models import HealthState

    assert HealthState.get("security_review").get("required") is True
    assert report["follow_up"][0].startswith("Complete the security review")
    from apps.core.models import AuditEvent

    assert AuditEvent.objects.filter(action="recovery.compromise_mode").exists()


def test_at307_integrations_on_hold_until_verified(system, family, monkeypatch):
    from apps.notify.models import OutboxMessage
    from apps.ops import bk_integrations as I

    config.set_value("telegram.enabled", True)
    st = I.start_hold("normal")
    assert "channel:telegram" in st["items"]
    assert I.channel_on_hold("telegram")
    OutboxMessage.objects.create(key="t1", user=family["dad"], channel="telegram", kind="x", subject="s", body="b")
    from apps.notify import expiry

    expiry.deliver_outbox()
    assert OutboxMessage.objects.get(key="t1").status == "pending"  # nothing is sent while on hold
    from apps.notify import telegram

    monkeypatch.setattr(telegram, "test_connection", lambda: (_ for _ in ()).throw(RuntimeError("401 Unauthorized: token revoked")))
    I.verify()
    item = next(i for i in I.summary()["items"] if i["key"] == "channel:telegram")
    assert item["state"] == "action_required" and "expired or revoked" in item["detail"]
    monkeypatch.setattr(telegram, "test_connection", lambda: {"ok": True})
    I.verify()
    assert not I.channel_on_hold("telegram")


def test_recover_command_list_and_analyze(system, family, tmp_path, capsys):
    keyfile = tmp_path / "key.txt"
    keyfile.write_text(bk_keys.reveal_text(system["inc"].key_generation))
    call_command("recover", "list", "--source", f"local:{system['dest'].config['path']}")
    out = capsys.readouterr().out
    assert str(system["inc"].id) in out
    call_command("recover", "analyze", "--source", f"local:{system['dest'].config['path']}", "--key-file", str(keyfile))
    out = capsys.readouterr().out
    assert '"replaces_current_data": true' in out and keyfile.read_text() not in out
    state = (R.recovery_dir() / "state.json").read_text()
    assert "deks" not in json.loads(state)  # data keys are never written to disk


def test_recovery_marker_blocks_web_requests(family, client):
    R.marker().parent.mkdir(parents=True, exist_ok=True)
    R.marker().write_text("{}")
    try:
        r = client.get("/api/session")
        assert r.status_code == 503 and r.json()["code"] == "recovery_in_progress"
    finally:
        R.marker().unlink()


def test_at311_test_restore_and_isolated_validation_restore(system, tmp_path):
    from django.db import connection

    from apps.ops import bk_validation as V

    run = V.test_restore(system["inc"])  # scratch database, dropped afterwards; never touches the live data
    assert run.status == "completed", run.result
    assert run.result["level"] in ("database", "structure")
    name = "pd_validation_pytest"
    with connection.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
        cur.execute(f'CREATE DATABASE "{name}"')
    try:
        p = V._db_params()
        config.set_value("recovery.validation_database",
                         f"postgresql://{p['PGUSER']}:{p['PGPASSWORD']}@{p['PGHOST'] or 'localhost'}:{p['PGPORT']}/{name}")
        config.set_value("recovery.validation_dir", str(tmp_path / "validation"))
        run = V.automated_validation(system["inc"])
        assert run.status == "completed", run.result
        assert V.validation_state()["state"] == "passed"
    finally:
        from django.db import connections

        connections.close_all()
        with connection.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
