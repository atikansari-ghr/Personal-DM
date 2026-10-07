#!/usr/bin/env python3
"""Root helper for host security operations requested from Settings → Security. Standard library only.

Started by personaldocs-host.service (via `personaldocs host-apply`) when the web app writes
<data-dir>/host/request.json. Only these fixed actions exist, so the web app cannot make root run anything else:

* ``inspect``          — firewall status (read only), listening services, reboot-required flag, ClamAV services.
* ``check_updates``    — refresh the package lists and list pending Debian security updates (simulation only).
* ``install_updates``  — install the pending *security* updates found by a fresh check (never other upgrades).
* ``freshclam``        — update ClamAV signatures now.
* ``antivirus_repair`` — diagnose and repair the local ClamAV daemon/socket (clamav_check.py; fixed steps only).
* ``reboot``           — drain the Personal DM services and reboot the host (once; duplicates are ignored).

Firewall rules are never changed. Every run writes <data-dir>/host/<action>.json (status) and a log file.
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ACTIONS = ("inspect", "check_updates", "install_updates", "freshclam", "antivirus_repair", "reboot")
SERVICE_USER = "personaldocs"
PKG_RX = re.compile(r"^[a-z0-9][a-z0-9+.\-]{0,99}$")
INST_RX = re.compile(r"^Inst (\S+) (?:\[(\S+)\] )?\((\S+) ([^)]*)\)")
APP_SERVICES = ("personaldocs-worker", "personaldocs-scheduler", "personaldocs-web")
EXPECTED_PORTS = {22: "SSH", 8000: "Personal Documents (web)"}
LOCAL_ONLY = {5432: "PostgreSQL", 3310: "ClamAV (must not be exposed)"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HostHelper:
    def __init__(self, data_dir: Path, run=None, reboot_flag: Path = Path("/run/reboot-required"),
                 service_user: str = SERVICE_USER, which=shutil.which):
        self.dir = Path(data_dir) / "host"
        self.run = run or (lambda cmd, timeout=600, env=None: subprocess.run(cmd, capture_output=True, text=True,
                                                                             timeout=timeout, env=env))
        self.reboot_flag, self.user, self.which = Path(reboot_flag), service_user, which

    # ---------------------------------------------------------- files
    def _write(self, name: str, data: dict) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f".{name}.tmp"
        tmp.write_text(json.dumps(data, indent=1))
        os.replace(tmp, self.dir / name)
        try:
            pw = pwd.getpwnam(self.user)
            os.chown(self.dir / name, pw.pw_uid, pw.pw_gid)
        except (KeyError, PermissionError):
            pass
        return data

    def _log(self, req_id: str, text: str) -> str:
        logs = self.dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        name = f"{re.sub(r'[^A-Za-z0-9_-]', '', req_id)[:40] or 'run'}.log"
        with open(logs / name, "a") as fh:
            fh.write(text)
        return name

    # ---------------------------------------------------------- inspect (read only)
    def firewall(self) -> dict:
        if self.which("ufw"):
            p = self.run(["ufw", "status", "verbose"], timeout=30)
            out = (p.stdout or "").strip()
            active = out.lower().startswith("status: active")
            lines = out.splitlines()
            sep = next((i for i, ln in enumerate(lines) if ln.startswith("--")), len(lines))
            rules = [ln for ln in lines[sep + 1:] if ln.strip()]
            return {"tool": "ufw", "active": active, "rules": len(rules), "summary": "\n".join(out.splitlines()[:30])}
        if self.which("nft"):
            p = self.run(["nft", "list", "ruleset"], timeout=30)
            out = p.stdout or ""
            chains = re.findall(r"chain \S+ \{[^}]*policy (drop|accept)", out)
            rules = sum(1 for ln in out.splitlines() if ln.strip() and not ln.strip().startswith(("table", "chain", "type", "}", "policy")))
            return {"tool": "nftables", "active": rules > 0 or "drop" in chains, "rules": rules,
                    "summary": f"{rules} rule(s); default policies: {', '.join(chains) or 'none'}"}
        return {"tool": None, "active": False, "rules": 0, "summary": "No firewall tool (ufw or nftables) is installed."}

    def listening(self) -> list[dict]:
        p = self.run(["ss", "-H", "-tulpn"], timeout=30)
        out = []
        for ln in (p.stdout or "").splitlines():
            parts = ln.split()
            if len(parts) < 5:
                continue
            proto, local = parts[0], parts[4]
            addr, _, port = local.rpartition(":")
            proc = re.search(r'users:\(\("([^"]+)"', ln)
            try:
                port_n = int(port)
            except ValueError:
                continue
            addr = addr.strip("[]")
            out.append({"proto": proto, "address": addr, "port": port_n, "process": proc.group(1) if proc else "",
                        "public": addr not in ("127.0.0.1", "::1", "localhost") and not addr.startswith("127.")})
        return out

    def service_state(self, name: str) -> str:
        if not self.which("systemctl"):
            return "unknown"
        return (self.run(["systemctl", "is-active", name], timeout=15).stdout or "unknown").strip() or "unknown"

    def inspect(self, req: dict) -> dict:
        listening = self.listening()
        unexpected = [s for s in listening if s["public"] and s["port"] not in EXPECTED_PORTS]
        exposed_local_only = [s for s in listening if s["public"] and s["port"] in LOCAL_ONLY]
        return {"state": "done", "firewall": self.firewall(), "listening": listening, "unexpected": unexpected,
                "exposed_local_only": exposed_local_only, "reboot_required": self.reboot_flag.exists(),
                "reboot_packages": self._reboot_pkgs(),
                "services": {s: self.service_state(s) for s in ("clamav-daemon", "clamav-freshclam", *APP_SERVICES)}}

    def _reboot_pkgs(self) -> list[str]:
        f = self.reboot_flag.with_name("reboot-required.pkgs")
        try:
            return sorted(set(f.read_text().split()))[:50]
        except OSError:
            return []

    # ---------------------------------------------------------- updates
    def pending_security(self, refresh: bool = True) -> tuple[list[dict], str]:
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C"}
        log = ""
        if refresh:
            p = self.run(["apt-get", "update", "-q"], timeout=600, env=env)
            log += f"$ apt-get update\n{p.stdout}{p.stderr}\n"
            if p.returncode != 0:
                raise RuntimeError(f"apt-get update failed: {(p.stderr or p.stdout)[-300:]}")
        p = self.run(["apt-get", "-s", "-q", "dist-upgrade"], timeout=300, env=env)
        log += f"$ apt-get -s dist-upgrade\n{p.stdout[-20000:]}\n"
        pending = []
        for ln in (p.stdout or "").splitlines():
            m = INST_RX.match(ln)
            if m and "security" in m.group(4).lower() and PKG_RX.match(m.group(1)):
                pending.append({"package": m.group(1), "current": m.group(2) or "", "candidate": m.group(3), "origin": m.group(4)[:80]})
        return pending, log

    def check_updates(self, req: dict) -> dict:
        pending, log = self.pending_security(refresh=True)
        logname = self._log(req["id"], log)
        return {"state": "done", "pending": pending, "count": len(pending), "log": logname,
                "reboot_required": self.reboot_flag.exists()}

    def install_updates(self, req: dict) -> dict:
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C"}
        pending, log = self.pending_security(refresh=True)
        names = [p["package"] for p in pending]
        if not names:
            logname = self._log(req["id"], log + "\nNo pending security updates.\n")
            return {"state": "done", "installed": [], "log": logname, "reboot_required": self.reboot_flag.exists()}
        cmd = ["apt-get", "install", "-y", "-q", "--only-upgrade", "-o", "Dpkg::Options::=--force-confold",
               "-o", "Dpkg::Options::=--force-confdef", *names]
        p = self.run(cmd, timeout=3600, env=env)
        log += f"$ {' '.join(cmd)}\n{p.stdout}{p.stderr}\n"
        logname = self._log(req["id"], log)
        ok = p.returncode == 0
        return {"state": "done" if ok else "failed", "installed": names if ok else [], "log": logname,
                "error": "" if ok else (p.stderr or p.stdout)[-400:], "reboot_required": self.reboot_flag.exists()}

    # ---------------------------------------------------------- ClamAV signatures
    def freshclam(self, req: dict) -> dict:
        if not self.which("freshclam"):
            return {"state": "failed", "ok": False, "error": "freshclam is not installed (sudo personaldocs repair)."}
        log = ""
        self.run(["systemctl", "stop", "clamav-freshclam"], timeout=60)
        p = self.run(["freshclam", "--stdout"], timeout=900)
        log += f"$ freshclam\n{p.stdout}{p.stderr}\n"
        self.run(["systemctl", "start", "clamav-freshclam"], timeout=60)
        logname = self._log(req["id"], log)
        ok = p.returncode == 0
        return {"state": "done" if ok else "failed", "ok": ok, "log": logname,
                "error": "" if ok else (p.stderr or p.stdout)[-300:]}

    # ---------------------------------------------------------- ClamAV daemon repair
    def antivirus_repair(self, req: dict) -> dict:
        try:
            from .clamav_check import Clamav
        except ImportError:  # run as a script by personaldocs host-apply
            from clamav_check import Clamav
        out = Clamav(run=self.run).repair()
        log = "\n".join(f"{'OK  ' if s['ok'] else 'FAIL'} {s['step']}: {s['detail']}" for s in out["steps"])
        logname = self._log(req["id"], log + "\n")
        res = out["result"]
        ok = res["status"] in ("healthy", "degraded")
        return {"state": "done" if ok else "failed", "ok": ok, "log": logname, "steps": out["steps"], "diagnosis": res,
                "error": "" if ok else (res.get("cause") or "ClamAV is still not working; see the steps.")}

    # ---------------------------------------------------------- reboot
    def reboot(self, req: dict) -> dict:
        marker = self.dir / "reboot.lock"
        if marker.exists():
            return {"state": "ignored", "message": "A reboot is already in progress."}
        marker.write_text(now())
        for s in APP_SERVICES[:2]:  # worker waits for its current job (TimeoutStopSec) before stopping
            self.run(["systemctl", "stop", s], timeout=960)
        self.run(["systemd-run", "--on-active=10", "--unit=personaldocs-reboot", "systemctl", "reboot"], timeout=30)
        return {"state": "rebooting", "message": "Services stopped; the host reboots in about 10 seconds."}

    # ---------------------------------------------------------- dispatch
    def apply(self) -> dict:
        try:
            req = json.loads((self.dir / "request.json").read_text())
        except (OSError, ValueError):
            return {"state": "failed", "error": "No readable request."}
        action = req.get("action")
        if action not in ACTIONS or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(req.get("id", ""))):
            return self._write("last-error.json", {"state": "failed", "error": "Unknown action.", "at": now()})
        started = now()
        self._write(f"{action}.json", {"id": req["id"], "action": action, "state": "running", "started_at": started})
        try:
            result = getattr(self, action)(req)
        except Exception as exc:  # noqa: BLE001 - report every failure back to the web app
            result = {"state": "failed", "error": f"{exc.__class__.__name__}: {str(exc)[:300]}"}
        return self._write(f"{action}.json", {"id": req["id"], "action": action, "started_at": started, "finished_at": now(),
                                              **result})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=os.environ.get("PD_DATA_DIR", "/var/lib/personaldocs"))
    ap.add_argument("--apply", action="store_true", help="process <data-dir>/host/request.json")
    ap.add_argument("--mark-installed", action="store_true", help="record that the helper unit is installed")
    args = ap.parse_args(argv)
    h = HostHelper(Path(args.data_dir))
    if args.mark_installed:
        h._write("helper.json", {"installed": True, "at": now()})
        return 0
    if args.apply:
        out = h.apply()
        print(json.dumps({k: v for k, v in out.items() if k in ("action", "state", "error")}))
        return 0 if out.get("state") not in ("failed",) else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
