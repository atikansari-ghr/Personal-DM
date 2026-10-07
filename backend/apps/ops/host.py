"""Web-app side of the root host helper (see host_helper.py). The app only writes a request with a fixed action
name; personaldocs-host.path notices it and runs the helper as root, which writes <data>/host/<action>.json."""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings

from apps.core import audit

from .host_helper import ACTIONS


class HostError(Exception):
    pass


def host_dir() -> Path:
    return Path(settings.DATA_DIR) / "host"


def installed() -> bool:
    """True when the installer set up personaldocs-host.path (it writes helper.json)."""
    return (host_dir() / "helper.json").exists()


def status(action: str) -> dict:
    if action not in ACTIONS:
        raise HostError("Unknown action.")
    try:
        return json.loads((host_dir() / f"{action}.json").read_text())
    except (OSError, ValueError):
        return {}


def running(action: str) -> bool:
    st = status(action)
    if st.get("state") not in ("requested", "running"):
        return False
    started = st.get("requested_at") or st.get("started_at")
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(started) < timedelta(hours=2)
    except (TypeError, ValueError):
        return False


def request(action: str, *, actor=None, request_obj=None, **params) -> dict:
    if action not in ACTIONS:
        raise HostError("Unknown action.")
    if not installed():
        raise HostError("The host helper is not installed. On the server run: sudo personaldocs repair")
    if running(action):
        raise HostError("This operation is already running. Wait for it to finish.")
    d = host_dir()
    d.mkdir(parents=True, exist_ok=True)
    req = {"id": secrets.token_hex(8), "action": action, "requested_at": datetime.now(timezone.utc).isoformat(),
           "requested_by": actor.username if actor else "system"}
    # status first, so the UI shows "requested" at once
    (d / f".{action}.tmp").write_text(json.dumps({"id": req["id"], "action": action, "state": "requested",
                                                  "requested_at": req["requested_at"]}))
    os.replace(d / f".{action}.tmp", d / f"{action}.json")
    tmp = d / ".request.tmp"
    tmp.write_text(json.dumps(req))
    os.replace(tmp, d / "request.json")
    audit.record(f"host.{action}_requested", request=request_obj, actor=actor, request_id=req["id"])
    return req


def log_text(name: str, limit: int = 200_000) -> str:
    if not name or "/" in name or ".." in name:
        return ""
    try:
        return (host_dir() / "logs" / name).read_text(errors="replace")[-limit:]
    except OSError:
        return ""


def reboot_required() -> bool | None:
    """The helper's last inspection, or the flag file itself (readable without root)."""
    flag = Path("/run/reboot-required")
    insp = status("inspect")
    if insp.get("reboot_required") is not None:
        return bool(insp["reboot_required"]) or flag.exists()
    return flag.exists() if Path("/run").exists() else None
