"""Web-app side of NAS mounting (unprivileged). See nas_helper.py for the root side.

`request_apply` validates the NAS settings and writes <data-dir>/nas/request.json (plus a one-time 0600
password file for SMB). The personaldocs-nas.path unit notices the request and runs the root helper, which
mounts /mnt/pdnas and writes status.json. `sync` adopts a successful mount as the backup destination.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

from apps.core import config
from apps.core.registry import BY_KEY, SettingError, coerce

from .nas_helper import MOUNT_POINT, NasError, validate

FIELDS = ("type", "server", "share", "subfolder", "username", "domain", "version")


def state_dir() -> Path:
    return Path(settings.DATA_DIR) / "nas"


def read_status() -> dict:
    try:
        return json.loads((state_dir() / "status.json").read_text())
    except (OSError, ValueError):
        return {"state": "not_configured", "message": "The NAS has not been connected yet."}


def _write(name: str, text: str, mode: int = 0o640) -> None:
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{name}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.replace(tmp, d / name)


def snapshot() -> dict:
    snap = {}
    for f in FIELDS:
        defn = BY_KEY[f"nas.{f}"]
        try:
            snap[f] = coerce(defn, config.get(defn.key))
        except SettingError as exc:
            raise NasError(f"Invalid {defn.label}: {exc}")
    return validate(snap)


def request_apply(actor=None, action: str = "mount") -> dict:
    if action not in ("mount", "unmount"):
        raise NasError("Unknown action.")
    snap = snapshot() if action == "mount" else {}
    if action == "mount" and snap["type"] == "none":
        raise NasError("Choose NFS or SMB first (or set the backup destination folder if Proxmox already mounts the share).")
    if action == "mount" and snap["type"] == "smb":
        password = config.get("nas.password")
        if not password:
            raise NasError("Enter the SMB password first.")
        _write("smb.password", password + "\n", 0o600)
    payload = {"action": action, "at": datetime.now(timezone.utc).isoformat(), **snap}
    _write("status.json", json.dumps({"state": "pending", "message": "Waiting for the system service to apply the change…",
                                      "at": payload["at"], "action": action}))
    _write("request.json", json.dumps(payload))  # written last: this triggers the root helper
    return payload


def sync() -> dict:
    """Adopt a successful mount as the backup destination (and clear it after an unmount)."""
    status = read_status()
    target = config.get("backup.target") or ""
    if status.get("state") == "mounted" and status.get("target") and status["target"] != target:
        config.set_value("backup.target", status["target"])
        config.set_value("backup.require_mount", True)
    elif status.get("state") == "unmounted" and target.startswith(str(MOUNT_POINT)):
        config.set_value("backup.target", "")
    return status
