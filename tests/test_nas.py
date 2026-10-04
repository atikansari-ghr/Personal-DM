"""NAS mounting from Settings: validation, unit rendering, request/status flow, root helper (with a fake systemctl)."""
import json
import os
import stat
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.core import config
from apps.ops import nas
from apps.ops.nas_helper import Helper, NasError, hint, render_credentials, render_unit, validate

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("field,value", [
    ("server", "nas;rm -rf /"), ("server", "nas.local\nWhat=/etc"), ("share", "/vol/../../etc"), ("share", "/vol\nOptions=exec"),
    ("username", "bob,uid=0"), ("username", "a b"), ("domain", "x=y"), ("version", "4;id"), ("subfolder", "../up"), ("type", "ext4"),
])
def test_validation_rejects_injection(field, value):
    req = {"type": "smb", "server": "nas.local", "share": "backups", "username": "bob", field: value}
    with pytest.raises(NasError):
        validate(req)


def test_render_units():
    nfs = render_unit(validate({"type": "nfs", "server": "192.168.1.20", "share": "/volume1/backups", "version": "4.1"}), 999, 999)
    assert "What=192.168.1.20:/volume1/backups" in nfs and "Type=nfs" in nfs and "vers=4.1" in nfs and "Where=/mnt/pdnas" in nfs
    smb = render_unit(validate({"type": "smb", "server": "nas.local", "share": "Family Backups", "username": "bob"}), 998, 997)
    assert "What=//nas.local/Family\\x20Backups" in smb and "Type=cifs" in smb and "uid=998" in smb and "gid=997" in smb
    assert "credentials=/etc/personaldocs/nas-smb.credentials" in smb and "password" not in smb.lower().replace("credentials", "")
    assert render_credentials({"username": "bob", "domain": "WG"}, "s3cret") == "username=bob\npassword=s3cret\ndomain=WG\n"
    with pytest.raises(NasError):
        render_credentials({"username": "bob"}, "a\nusername=root")


def test_hints():
    assert "privileged" in hint("mount error: Operation not permitted", "nas")
    assert "refused access" in hint("mount error(13): Permission denied", "nas")
    assert "Cannot reach" in hint("mount.nfs: Connection timed out", "nas")


def _fake_run(mount_ok=True, enable_err=""):
    calls = []

    def run(cmd, timeout=60):
        calls.append(cmd)
        if cmd[:2] == ["mountpoint", "-q"]:
            return SimpleNamespace(returncode=0 if mount_ok else 1, stdout="", stderr="")
        if cmd[:3] == ["systemctl", "enable", "--now"]:
            return SimpleNamespace(returncode=0 if not enable_err else 1, stdout="", stderr=enable_err)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    run.calls = calls
    return run


def _helper(tmp_path, settings, run):
    settings.DATA_DIR = tmp_path / "data"
    return Helper(tmp_path / "data", run=run, unit_dir=tmp_path / "units", mount_point=tmp_path / "pdnas",
                  credentials=tmp_path / "smb.cred", service_user="no-such-user-for-tests")


def test_smb_request_mount_and_adopt_destination(family, clients, tmp_path, settings):
    (tmp_path / "units").mkdir()
    helper = _helper(tmp_path, settings, _fake_run())
    config.set_value("nas.type", "smb")
    config.set_value("nas.server", "nas.local")
    config.set_value("nas.share", "backups")
    config.set_value("nas.username", "bob")
    assert clients["dad"].post("/api/backup/nas", {"action": "mount"}, format="json").status_code == 400  # no password yet
    config.set_value("nas.password", "synthetic-smb-pw")
    r = clients["dad"].post("/api/backup/nas", {"action": "mount"}, format="json")
    assert r.status_code == 200 and r.json()["status"]["state"] == "pending"
    req = json.loads((tmp_path / "data/nas/request.json").read_text())
    assert "synthetic-smb-pw" not in json.dumps(req)  # the watched request never contains the password
    pw_file = tmp_path / "data/nas/smb.password"
    assert stat.S_IMODE(os.stat(pw_file).st_mode) == 0o600
    status = helper.apply()
    assert status["state"] == "mounted", status
    assert not pw_file.exists()  # one-time password file removed
    assert (tmp_path / "smb.cred").read_text().startswith("username=bob\npassword=synthetic-smb-pw")
    assert stat.S_IMODE(os.stat(tmp_path / "smb.cred").st_mode) == 0o600
    assert (tmp_path / "pdnas/personaldocs/.personaldocs-backup-target").exists()
    assert "What=//nas.local/backups" in (tmp_path / "units/mnt-pdnas.mount").read_text()
    data = clients["dad"].get("/api/backup/nas").json()
    assert data["status"]["state"] == "mounted"
    assert config.get("backup.target") == str(tmp_path / "pdnas/personaldocs")  # adopted as backup destination


def test_mount_failure_reports_actionable_error(family, tmp_path, settings):
    (tmp_path / "units").mkdir()
    helper = _helper(tmp_path, settings, _fake_run(mount_ok=False, enable_err="mount error: Operation not permitted"))
    config.set_value("nas.type", "nfs")
    config.set_value("nas.server", "192.168.1.20")
    config.set_value("nas.share", "/volume1/backups")
    nas.request_apply(None, "mount")
    status = helper.apply()
    assert status["state"] == "error" and "privileged" in status["message"]
    assert config.get("backup.target") == ""


def test_unmount_clears_destination(family, tmp_path, settings):
    (tmp_path / "units").mkdir()
    helper = _helper(tmp_path, settings, _fake_run())
    config.set_value("nas.type", "nfs")
    config.set_value("nas.server", "192.168.1.20")
    config.set_value("nas.share", "/volume1/backups")
    nas.request_apply(None, "mount")
    helper.apply()
    settings.DATA_DIR = tmp_path / "data"
    nas.sync()
    # the helper's mount point is a temp dir in tests; make sync recognise it as the managed mount
    config.set_value("backup.target", str(nas.MOUNT_POINT / "personaldocs"))
    nas.request_apply(None, "unmount")
    assert helper.apply()["state"] == "unmounted"
    assert not (tmp_path / "units/mnt-pdnas.mount").exists()
    nas.sync()
    assert config.get("backup.target") == ""


def test_api_permissions_and_stale_pending(family, clients, tmp_path, settings):
    settings.DATA_DIR = tmp_path / "data"
    assert clients["son1"].get("/api/backup/nas").status_code == 403
    config.set_value("nas.type", "nfs")
    config.set_value("nas.server", "192.168.1.20")
    config.set_value("nas.share", "/volume1/backups")
    clients["dad"].post("/api/backup/nas", {"action": "mount"}, format="json")
    status_file = tmp_path / "data/nas/status.json"
    st = json.loads(status_file.read_text())
    st["at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    status_file.write_text(json.dumps(st))
    data = clients["dad"].get("/api/backup/nas").json()
    assert data["status"]["state"] == "error" and "personaldocs repair" in data["status"]["message"]


def test_settings_validation_via_api(family, clients):
    r = clients["dad"].put("/api/settings", {"values": {"nas.server": "nas;reboot", "nas.username": "a,b"}}, format="json")
    assert r.status_code == 400 and {"nas.server", "nas.username"} <= set(r.json()["fields"])
    listing = clients["dad"].get("/api/settings").json()["settings"]
    assert next(s for s in listing if s["key"] == "nas.password")["value"] is None
