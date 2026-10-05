#!/usr/bin/env python3
"""Root helper that mounts the NAS backup share. Standard library only (no Django, no database).

Started by personaldocs-nas.service (via `personaldocs nas-apply`) when the web app writes
<data-dir>/nas/request.json. The request holds only the NAS fields, which are re-validated here with the same
validators as the settings registry; an SMB password is passed in a separate 0600 file that is deleted after
use. Only a fixed mount unit for /mnt/pdnas is written, so the web app cannot make root run anything else.

Proxmox only lets *privileged* containers with the `mount=nfs;cifs` feature mount NFS/SMB. Unprivileged
containers need the share bind-mounted by the Proxmox host instead ("Already mounted" in Settings).
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/ for apps.core.registry (pure Python)

from apps.core.registry import (SettingError, _validate_host, _validate_plain, _validate_share,  # noqa: E402
                                _validate_subfolder, _validate_version)

MOUNT_POINT = Path("/mnt/pdnas")
UNIT_NAME = "mnt-pdnas.mount"
UNIT_DIR = Path("/etc/systemd/system")
CREDENTIALS = Path("/etc/personaldocs/nas-smb.credentials")
MARKER = ".personaldocs-backup-target"
SERVICE_USER = "personaldocs"


class NasError(Exception):
    pass


def validate(req: dict) -> dict:
    snap = {k: str(req.get(k) or "").strip() for k in ("type", "server", "share", "subfolder", "username", "domain", "version")}
    if snap["type"] not in ("none", "nfs", "smb"):
        raise NasError("Unknown NAS type.")
    checks = [(_validate_host, "server", "NAS server"), (_validate_share, "share", "share"), (_validate_subfolder, "subfolder", "folder"),
              (_validate_plain, "username", "username"), (_validate_plain, "domain", "domain"), (_validate_version, "version", "version")]
    for fn, key, label in checks:
        try:
            fn(snap[key])
        except SettingError as exc:
            raise NasError(f"Invalid {label}: {exc}")
    snap["subfolder"] = snap["subfolder"] or "personaldocs"
    if snap["type"] in ("nfs", "smb"):
        if not snap["server"] or not snap["share"]:
            raise NasError("Enter the NAS server and share first.")
        if snap["type"] == "nfs" and not snap["share"].startswith("/"):
            raise NasError("NFS exports start with '/', for example /volume1/backups.")
        if snap["type"] == "smb" and not snap["username"]:
            raise NasError("Enter the SMB username.")
    return snap


def _escape_unit_path(value: str) -> str:
    return value.replace("\\", "\\\\").replace(" ", "\\x20")


def render_unit(snap: dict, uid: int, gid: int) -> str:
    if snap["type"] == "nfs":
        what, fstype = f"{snap['server']}:{snap['share']}", "nfs"
        opts = ["rw", "_netdev", "nofail", "soft", "timeo=150", "retrans=3"]
    elif snap["type"] == "smb":
        what, fstype = f"//{snap['server']}/{snap['share'].strip('/')}", "cifs"
        opts = ["rw", "_netdev", "nofail", f"credentials={CREDENTIALS}", f"uid={uid}", f"gid={gid}",
                "file_mode=0640", "dir_mode=0750", "iocharset=utf8"]
    else:
        raise NasError("NAS connection is set to 'Already mounted'; nothing to mount.")
    if snap.get("version"):
        opts.append(f"vers={snap['version']}")
    return (
        "# Managed by Personal Documents Management System (Settings -> Storage & backup). Changes here are overwritten.\n"
        "[Unit]\nDescription=Personal Documents Management System NAS backup share\nAfter=network-online.target\nWants=network-online.target\n\n"
        f"[Mount]\nWhat={_escape_unit_path(what)}\nWhere={MOUNT_POINT}\nType={fstype}\nOptions={','.join(opts)}\nTimeoutSec=30\n\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )


def render_credentials(snap: dict, password: str) -> str:
    if "\n" in password or "\r" in password:
        raise NasError("The SMB password must not contain line breaks.")
    lines = [f"username={snap['username']}", f"password={password}"]
    if snap.get("domain"):
        lines.append(f"domain={snap['domain']}")
    return "\n".join(lines) + "\n"


def hint(detail: str, server: str) -> str:
    low = detail.lower()
    if "operation not permitted" in low or "error(1)" in low or "only root can" in low:
        return ("This container is not allowed to mount network shares. Use a privileged LXC with the Proxmox feature "
                "'mount=nfs;cifs', or mount the share on the Proxmox host and choose 'Already mounted'.")
    if "access denied" in low or "logon failure" in low or "permission denied" in low or "error(13)" in low:
        return "The NAS refused access. Check the username/password, or that the NFS export allows this container's IP address."
    if "no route" in low or "timed out" in low or "unreachable" in low or "could not resolve" in low or "error(113)" in low:
        return f"Cannot reach {server}. Check the address and that the NAS accepts connections from this container."
    if "no such file" in low or "bad share" in low or "does not exist" in low or "error(2)" in low:
        return "The share or export was not found on the NAS. Check the share name or export path."
    if "wrong fs type" in low or "unknown filesystem" in low or "helper program" in low:
        return "NFS/SMB client tools are missing. Run 'sudo personaldocs repair' (installs nfs-common and cifs-utils)."
    return "Mounting failed. See the details below."


class Helper:
    def __init__(self, data_dir: Path, run=None, unit_dir: Path = UNIT_DIR, mount_point: Path = MOUNT_POINT,
                 credentials: Path = CREDENTIALS, service_user: str = SERVICE_USER):
        self.dir = Path(data_dir) / "nas"
        self.run = run or (lambda cmd, timeout=60: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout))
        self.unit_dir, self.mount_point, self.credentials, self.user = Path(unit_dir), Path(mount_point), Path(credentials), service_user

    def status(self, state: str, message: str, **extra) -> dict:
        data = {"state": state, "message": message, "at": datetime.now(timezone.utc).isoformat(), **extra}
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "status.tmp"
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self.dir / "status.json")
        try:
            pw = pwd.getpwnam(self.user)
            os.chown(self.dir / "status.json", pw.pw_uid, pw.pw_gid)
        except (KeyError, PermissionError):
            pass
        return data

    def _ids(self) -> tuple[int, int]:
        try:
            pw = pwd.getpwnam(self.user)
            return pw.pw_uid, pw.pw_gid
        except KeyError:
            return 0, 0

    def apply(self) -> dict:
        pw_file = self.dir / "smb.password"
        try:
            req = json.loads((self.dir / "request.json").read_text())
        except (OSError, ValueError):
            return self.status("error", "No NAS request found. Use 'Connect NAS' in Settings → Storage & backup.")
        password = ""
        if pw_file.exists():
            password = pw_file.read_text().rstrip("\n")
            pw_file.unlink()
        request_at = req.get("at")
        unit = self.unit_dir / UNIT_NAME
        try:
            if req.get("action") == "unmount":
                self.run(["systemctl", "disable", "--now", UNIT_NAME])
                unit.unlink(missing_ok=True)
                self.credentials.unlink(missing_ok=True)
                self.run(["systemctl", "daemon-reload"])
                return self.status("unmounted", "The NAS share was disconnected. Backups pause until a destination is configured.",
                                   request_at=request_at)
            snap = validate(req)
            if snap["type"] == "none":
                return self.status("not_configured", "NAS connection is 'Already mounted': set the backup destination folder instead.",
                                   request_at=request_at)
            uid, gid = self._ids()
            if snap["type"] == "smb":
                if not password and not self.credentials.exists():
                    raise NasError("Enter the SMB password first.")
                if password:
                    fd = os.open(self.credentials, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w") as fh:
                        fh.write(render_credentials(snap, password))
                    os.chmod(self.credentials, 0o600)
            self.mount_point.mkdir(parents=True, exist_ok=True)
            self.run(["systemctl", "stop", UNIT_NAME])
            unit.write_text(render_unit(snap, uid, gid))
            self.run(["systemctl", "daemon-reload"])
            res = self.run(["systemctl", "enable", "--now", UNIT_NAME], timeout=90)
            mounted = self.run(["mountpoint", "-q", str(self.mount_point)]).returncode == 0
            if res.returncode != 0 or not mounted:
                journal = self.run(["journalctl", "-u", UNIT_NAME, "-n", "15", "--no-pager", "-o", "cat"]).stdout or ""
                detail = ((res.stderr or "") + "\n" + journal).strip()
                return self.status("error", hint(detail, snap["server"]), detail=detail[-1200:], request_at=request_at)
            target = self.mount_point / snap["subfolder"]
            target.mkdir(exist_ok=True)
            if uid:
                try:
                    os.chown(target, uid, gid)
                except PermissionError:
                    pass  # NFS root-squash: the folder must already be writable by the service account
            (target / MARKER).touch()
            if uid:
                probe = self.run(["runuser", "-u", self.user, "--", "touch", str(target / ".write-test")])
                if probe.returncode != 0:
                    return self.status("error", f"The share is mounted but the app cannot write to it. Give write access on the NAS "
                                       f"(NFS: allow UID {uid} or map users; SMB: the account needs write permission).",
                                       detail=(probe.stderr or "")[-500:], request_at=request_at)
                (target / ".write-test").unlink(missing_ok=True)
            st = os.statvfs(target)
            return self.status("mounted", f"Connected. Backups will be written to {target}.", target=str(target),
                               free_bytes=st.f_bavail * st.f_frsize, total_bytes=st.f_blocks * st.f_frsize, request_at=request_at)
        except NasError as exc:
            return self.status("error", str(exc), request_at=request_at)
        except subprocess.TimeoutExpired:
            return self.status("error", "The NAS did not respond in time. Check the address and network.", request_at=request_at)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default="/var/lib/personaldocs")
    args = ap.parse_args(argv)
    if os.geteuid() != 0:
        print("nas_helper must run as root", file=sys.stderr)
        return 2
    result = Helper(Path(args.data_dir)).apply()
    print(json.dumps(result))
    return 0 if result["state"] in ("mounted", "unmounted", "not_configured") else 1


if __name__ == "__main__":
    sys.exit(main())
