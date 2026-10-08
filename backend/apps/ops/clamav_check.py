"""ClamAV daemon diagnosis and repair for Debian 13. Standard library only.

Used by three callers:

* ``personaldocs antivirus status|repair|selftest`` and ``personaldocs doctor`` (root, on the server);
* the root host helper (``antivirus_repair`` action requested from Settings → Security → Antivirus);
* the web app (read-only ``diagnose()`` as the service user — that is the identity that must reach the socket).

Debian 13 (clamav 1.4.3+dfsg-1) facts this module relies on — checked against the packages themselves:

* ``clamav-daemon.service`` has ``Requires=clamav-daemon.socket`` and is *socket activated*: systemd owns the
  listening socket ``ListenStream=/run/clamav/clamd.ctl`` (``RemoveOnStop=True``) and passes it to clamd.
* Both units carry ``ConditionPathExistsGlob=/var/lib/clamav/main.{c[vl]d,inc}`` and ``daily.{…}``: while no
  signatures exist they are *skipped* (inactive, no error) and nothing starts them later on its own.
* The service has no ``Restart=``: a clamd killed by the kernel's out-of-memory killer stays dead.
* The debconf default for ``LocalSocket`` in ``/etc/clamav/clamd.conf`` is ``/var/run/clamav/clamd.ctl``, a
  different *string* from the socket unit's ``/run/clamav/clamd.ctl``. clamd only adopts the systemd socket when
  the paths match literally; otherwise it binds its own socket file and removes it again when it stops, which
  leaves the socket unit "active" with no file — the application then reports ``FileNotFoundError``.

Nothing here opens a network port: TCPSocket/TCPAddr lines are removed, clamd listens on the Unix socket only.
"""
from __future__ import annotations

import glob
import grp
import json
import os
import pwd
import re
import socket
import stat
import struct
import subprocess
import time
from pathlib import Path

CONF = Path("/etc/clamav/clamd.conf")
DB_DIR = Path("/var/lib/clamav")
RUN_DIR = Path("/run/clamav")
DEFAULT_SOCKET = "/run/clamav/clamd.ctl"
SERVICE, SOCKET_UNIT, FRESHCLAM = "clamav-daemon.service", "clamav-daemon.socket", "clamav-freshclam.service"
DROPIN = Path("/etc/systemd/system/clamav-daemon.service.d/50-personaldocs.conf")
TMPFILES = Path("/etc/tmpfiles.d/personaldocs-clamav.conf")
SERVICE_USER = "personaldocs"
PACKAGES = ("clamav", "clamav-daemon", "clamav-freshclam")
# Options earlier Personal DM releases wrote into clamd.conf that Debian's clamd does not know. clamd refuses to start
# on an unknown option ("ERROR: Parse error at line N: Unknown option EnableVersionCommand"); EnableVersionCommand only
# exists in Ubuntu's patched clamd, not in Debian 13's clamav 1.4.3+dfsg. The app reads versions without it.
UNSUPPORTED_OPTIONS = ("EnableVersionCommand",)
_UNKNOWN_RX = re.compile(r"Unknown option:?\s+([A-Za-z][A-Za-z0-9]*)")


def unknown_options(text: str) -> list[str]:
    """Option names clamd/clamconf rejected ("Unknown option X") in a log or clamconf output."""
    return sorted(set(_UNKNOWN_RX.findall(text or "")))
# The harmless, industry-standard antivirus test string (not malware). Assembled at run time so this source file is
# not itself reported by scanners; it never touches the document library.
EICAR = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*").encode()
CLEAN = b"Personal Documents antivirus self-test: this harmless text must be reported as clean.\n"

DROPIN_TEXT = """# Installed by Personal Documents (personaldocs repair / antivirus repair). Safe to keep.
# Debian's unit has no restart policy: a clamd stopped by the out-of-memory killer would stay down for good.
[Service]
Restart=on-failure
RestartSec=15s
"""
TMPFILES_TEXT = "# Installed by Personal Documents: ClamAV's runtime directory exists after every reboot.\nd /run/clamav 0755 clamav clamav -\n"


def _default_run(cmd, timeout=60, env=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)


def read_conf(path: Path = CONF) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition(" ")
            out[key] = value.strip()
    except OSError:
        pass
    return out


def set_conf(text: str, values: dict[str, str | None]) -> str:
    """Return clamd.conf text with each key set exactly once (None removes the key)."""
    lines = text.splitlines()
    seen: set[str] = set()
    out = []
    for line in lines:
        key = line.strip().split(" ", 1)[0] if line.strip() and not line.strip().startswith("#") else ""
        if key in values:
            if values[key] is None or key in seen:
                continue
            seen.add(key)
            out.append(f"{key} {values[key]}")
        else:
            out.append(line)
    for key, value in values.items():
        if value is not None and key not in seen:
            out.append(f"{key} {value}")
    return "\n".join(out) + "\n"


class Clamav:
    """All host access goes through ``run`` and the path attributes, so tests can simulate a Debian host."""

    def __init__(self, run=None, *, conf: Path = CONF, db_dir: Path = DB_DIR, run_dir: Path = RUN_DIR,
                 dropin: Path = DROPIN, tmpfiles: Path = TMPFILES, service_user: str = SERVICE_USER,
                 sleep=time.sleep, as_root: bool | None = None):
        self.run = run or _default_run
        self.conf, self.db_dir, self.run_dir, self.dropin, self.tmpfiles = Path(conf), Path(db_dir), Path(run_dir), Path(dropin), Path(tmpfiles)
        self.user, self.sleep = service_user, sleep
        self.as_root = (os.geteuid() == 0) if as_root is None else as_root

    # ---------------------------------------------------------------- facts
    def _out(self, cmd, timeout=30) -> tuple[int, str]:
        try:
            p = self.run(cmd, timeout=timeout)
            return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, exc.__class__.__name__

    def unit(self, name: str) -> dict:
        code, out = self._out(["systemctl", "show", name, "--no-pager", "-p", "LoadState", "-p", "ActiveState",
                               "-p", "SubState", "-p", "UnitFileState", "-p", "Result", "-p", "ConditionResult",
                               "-p", "Listen", "-p", "NRestarts", "-p", "ExecMainStatus"])
        info = {"available": code == 0}
        for line in out.splitlines():
            k, _, v = line.partition("=")
            info[k] = v
        return info

    def packages(self) -> dict[str, bool]:
        res = {}
        for p in PACKAGES:
            code, out = self._out(["dpkg-query", "-W", "-f", "${Status}", p])
            res[p] = code == 0 and "install ok installed" in out
        return res

    def signatures(self) -> dict:
        def have(stem: str) -> bool:
            return any(glob.glob(str(self.db_dir / f"{stem}.{ext}")) for ext in ("cvd", "cld", "inc"))
        return {"main": have("main"), "daily": have("daily")}

    def unit_socket(self, unit: dict | None = None) -> str:
        listen = (unit or self.unit(SOCKET_UNIT)).get("Listen", "")
        m = re.match(r"(/\S+)\s+\(Stream\)", listen)
        return m.group(1) if m else ""

    def effective_socket(self) -> dict:
        """The socket clamd really serves: the systemd socket unit's path, else clamd.conf's LocalSocket."""
        conf = read_conf(self.conf)
        configured = conf.get("LocalSocket", "")
        unit_path = self.unit_socket()
        path = unit_path or configured or DEFAULT_SOCKET
        return {"path": path, "configured": configured, "unit": unit_path,
                "mismatch": bool(unit_path and configured and configured != unit_path),
                "tcp": bool(conf.get("TCPSocket"))}

    @staticmethod
    def socket_facts(path: str) -> dict:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return {"exists": False, "error": "FileNotFoundError"}
        except OSError as exc:
            return {"exists": False, "error": exc.__class__.__name__}
        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        try:
            group = grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            group = str(st.st_gid)
        return {"exists": True, "is_socket": stat.S_ISSOCK(st.st_mode), "owner": owner, "group": group,
                "mode": oct(stat.S_IMODE(st.st_mode))}

    # ---------------------------------------------------------------- clamd protocol
    @staticmethod
    def _talk(path: str, payload: bytes | None, cmd: str, timeout: float) -> str:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(path)
            s.sendall(f"z{cmd}\0".encode())
            if payload is not None:
                s.sendall(struct.pack("!L", len(payload)) + payload + struct.pack("!L", 0))
            data = b""
            while not data.endswith(b"\0"):
                part = s.recv(4096)
                if not part:
                    break
                data += part
            return data.rstrip(b"\0").decode("utf-8", "replace").strip()
        finally:
            s.close()

    def ping(self, path: str, timeout: float = 5.0) -> tuple[bool, str]:
        try:
            reply = self._talk(path, None, "PING", timeout)
            return reply == "PONG", reply[:120]
        except (OSError, socket.timeout) as exc:
            return False, exc.__class__.__name__

    def version(self, path: str) -> str:
        try:
            return self._talk(path, None, "VERSION", 10)[:120]
        except (OSError, socket.timeout):
            return ""

    def self_test(self, path: str) -> dict:
        """Clean text must be clean and EICAR must be detected, through INSTREAM (the app's scan path)."""
        out = {"clean": None, "eicar": None, "ok": False, "detail": ""}
        try:
            clean = self._talk(path, CLEAN, "INSTREAM", 60)
            eicar = self._talk(path, EICAR, "INSTREAM", 60)
        except (OSError, socket.timeout) as exc:
            out["detail"] = f"scan failed: {exc.__class__.__name__}"
            return out
        out["clean"] = clean.endswith("OK") and "FOUND" not in clean
        out["eicar"] = eicar.endswith("FOUND")
        out["ok"] = bool(out["clean"] and out["eicar"])
        out["detail"] = "clean file: " + ("Clean" if out["clean"] else clean[:80]) + "; EICAR: " + \
            ("detected (" + eicar.split(":", 1)[-1].replace("FOUND", "").strip()[:60] + ")" if out["eicar"] else eicar[:80] or "not detected")
        return out

    def service_user_can_connect(self, path: str) -> tuple[bool | None, str]:
        """As root: connect as the Personal DM service account (that identity must reach the socket)."""
        if not self.as_root:
            ok, detail = self.ping(path)
            return ok, f"as {pwd.getpwuid(os.geteuid()).pw_name}: {'PONG' if ok else detail}"
        try:
            pwd.getpwnam(self.user)
        except KeyError:  # not installed yet (or a development host): report what root itself sees
            ok, detail = self.ping(path)
            return (None if ok else False), f"account {self.user} does not exist; as root: {'PONG' if ok else detail}"
        code, out = self._out(["runuser", "-u", self.user, "--", "python3", "-c",
                               "import socket,sys;s=socket.socket(socket.AF_UNIX);s.settimeout(5);s.connect(sys.argv[1]);"
                               "s.sendall(b'zPING\\0');print(s.recv(16).rstrip(b'\\0').decode())", path], timeout=20)
        ok = code == 0 and out.strip().endswith("PONG")
        return ok, f"as {self.user}: " + ("PONG" if ok else (out.strip().splitlines() or ["no answer"])[-1][:160])

    def journal_hint(self) -> str:
        code, out = self._out(["journalctl", "-u", SERVICE, "-n", "60", "--no-pager", "-o", "cat"], timeout=20)
        if code != 0:
            return ""
        bad = unknown_options(out)
        if bad:
            return f"clamd refuses to start: unknown option {', '.join(bad)} in clamd.conf"
        for rx, hint in ((r"out of memory|oom|Cannot allocate memory|Killed", "clamd ran out of memory (it needs about 1.2 GB; 4 GB for the container is recommended)"),
                         (r"apparmor=\"DENIED\"|Permission denied", "permission denied (AppArmor or file permissions); see journalctl -u clamav-daemon"),
                         (r"Can't open/parse the config file|Parse error|ERROR: .*clamd.conf", "clamd.conf has an error (run clamconf)"),
                         (r"No supported database files found|Can't open file or directory", "signature files are missing or unreadable (run freshclam)"),
                         (r"Socket file .* is in use|bind\(\) failed", "a stale socket file blocks clamd")):
            m = re.search(rx, out, re.I)
            if m:
                return hint
        return ""

    def memory_mb(self) -> tuple[int, int]:
        total = avail = 0
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) // 1024
        except (OSError, ValueError):
            pass
        return total, avail

    # ---------------------------------------------------------------- diagnosis
    def diagnose(self, *, self_test: bool = True) -> dict:
        checks: list[dict] = []

        def add(key, label, state, detail="", fix=""):
            checks.append({"key": key, "label": label, "state": state, "detail": detail, "fix": fix})

        pk = self.packages()
        missing = [p for p, ok in pk.items() if not ok]
        add("packages", "ClamAV packages installed", "fail" if missing else "ok",
            "missing: " + ", ".join(missing) if missing else ", ".join(PACKAGES), "sudo personaldocs antivirus repair" if missing else "")
        sig = self.signatures()
        add("signatures", "Signature files present", "ok" if all(sig.values()) else "fail",
            f"main: {'yes' if sig['main'] else 'missing'}, daily: {'yes' if sig['daily'] else 'missing'}",
            "" if all(sig.values()) else "sudo personaldocs antivirus repair (downloads signatures with freshclam)")
        svc, sock_u, fresh = self.unit(SERVICE), self.unit(SOCKET_UNIT), self.unit(FRESHCLAM)
        if not svc.get("available"):
            add("systemd", "systemd", "info", "systemctl is not available here (not a systemd host); unit checks skipped")
        else:
            skipped = svc.get("ConditionResult") == "no" or sock_u.get("ConditionResult") == "no"
            act = svc.get("ActiveState", "unknown")
            detail = f"{act}/{svc.get('SubState', '')}, {svc.get('UnitFileState', '')}"
            if svc.get("Result") not in ("", "success", None):
                detail += f", last result: {svc.get('Result')}"
            if skipped:
                detail += " — skipped by its start condition (no signature files when it was started)"
            add("daemon", "clamav-daemon active", "ok" if act == "active" else "fail", detail,
                "" if act == "active" else "sudo personaldocs antivirus repair")
            add("socket_unit", "clamav-daemon.socket listening", "ok" if sock_u.get("ActiveState") == "active" else "fail",
                f"{sock_u.get('ActiveState', 'unknown')}, {sock_u.get('UnitFileState', '')}, {sock_u.get('Listen', '') or 'no listen address'}",
                "" if sock_u.get("ActiveState") == "active" else "sudo personaldocs antivirus repair")
            fa = fresh.get("ActiveState", "unknown")
            add("freshclam", "clamav-freshclam (automatic signature updates)", "ok" if fa == "active" else "warn",
                f"{fa}, {fresh.get('UnitFileState', '')}", "" if fa == "active" else "sudo systemctl enable --now clamav-freshclam")
            add("restart_policy", "Automatic restart after a crash", "ok" if self.dropin.exists() else "warn",
                str(self.dropin) if self.dropin.exists() else "Debian's clamd unit has no restart policy",
                "" if self.dropin.exists() else "sudo personaldocs antivirus repair")
        eff = self.effective_socket()
        path = eff["path"]
        add("socket_path", "Effective socket path", "warn" if eff["mismatch"] else "ok",
            f"{path} (systemd socket unit: {eff['unit'] or '—'}, clamd.conf LocalSocket: {eff['configured'] or '—'})"
            + (" — clamd.conf does not match the systemd socket" if eff["mismatch"] else ""),
            "sudo personaldocs antivirus repair (sets LocalSocket to the systemd socket path)" if eff["mismatch"] else "")
        conf_keys = read_conf(self.conf)
        rejected = [k for k in UNSUPPORTED_OPTIONS if k in conf_keys]
        if self.as_root:
            code, jout = self._out(["journalctl", "-u", SERVICE, "-n", "60", "--no-pager", "-o", "cat"], timeout=20)
            rejected += [k for k in unknown_options(jout if code == 0 else "") if k in conf_keys and k not in rejected]
        if rejected:
            add("conf_options", "clamd.conf options supported by this clamd", "fail",
                f"{', '.join(rejected)} is not a valid option for Debian's clamd — clamd refuses to start with it",
                "sudo personaldocs antivirus repair (removes it)  or:  sudo sed -i '/^" + rejected[0]
                + "/d' /etc/clamav/clamd.conf && sudo systemctl restart clamav-daemon.socket clamav-daemon")
        if eff["tcp"]:
            add("tcp", "No network listener", "fail", "clamd.conf contains TCPSocket: clamd listens on the network",
                "sudo personaldocs antivirus repair (removes TCPSocket/TCPAddr)")
        try:
            rd = os.stat(self.run_dir)
            try:
                rd_owner = pwd.getpwuid(rd.st_uid).pw_name
            except KeyError:
                rd_owner = str(rd.st_uid)
            add("run_dir", f"{self.run_dir} exists", "ok", f"owner {rd_owner}, mode {oct(stat.S_IMODE(rd.st_mode))}")
        except OSError:
            add("run_dir", f"{self.run_dir} exists", "fail", "missing (it lives in /run and is recreated at boot)",
                "sudo personaldocs antivirus repair (adds a tmpfiles.d entry)")
        sf = self.socket_facts(path)
        if sf["exists"]:
            add("socket_file", "Socket file", "ok" if sf["is_socket"] else "fail",
                f"{path}: {'socket' if sf['is_socket'] else 'not a socket'}, {sf['owner']}:{sf['group']} {sf['mode']}")
        else:
            add("socket_file", "Socket file", "fail", f"{path}: {sf['error']}", "sudo personaldocs antivirus repair")
        pid = self.run_dir / "clamd.pid"
        if pid.exists():
            try:
                alive = Path(f"/proc/{int(pid.read_text().strip())}").exists()
            except (OSError, ValueError):
                alive = False
            if not alive:
                add("stale_pid", "Stale clamd.pid", "warn", f"{pid} names a process that is not running", "sudo personaldocs antivirus repair")
        ok, detail = self.service_user_can_connect(path)
        add("access", "Personal DM service account can reach the socket", "ok" if ok else "fail" if ok is False else "info", detail,
            "" if ok else "sudo personaldocs antivirus repair")
        reachable = ok if ok is not None else True  # None: no service account, but root reached clamd
        test = None
        if reachable and self_test:
            ver = self.version(path)
            add("engine", "Engine and signatures (from clamd)", "ok" if ver else "warn", ver or "VERSION not answered")
            test = self.self_test(path)
            add("self_test", "Scan self-test (clean file + EICAR test pattern)", "ok" if test["ok"] else "fail", test["detail"],
                "" if test["ok"] else "check journalctl -u clamav-daemon; sudo personaldocs antivirus repair")
        total, avail = self.memory_mb()
        if total:
            add("memory", "Memory", "warn" if total < 3500 else "ok", f"{total} MB total, {avail} MB available (clamd uses about 1.2 GB)")
        hint = self.journal_hint() if self.as_root or os.access("/var/log/journal", os.R_OK) else ""
        if hint:
            add("journal", "clamd log", "warn", hint)
        failing = [c for c in checks if c["state"] == "fail"]
        if not reachable:
            status = "unavailable"
        elif test is not None and not test["ok"]:
            status = "error"
        elif failing or any(c["state"] == "warn" and c["key"] in ("freshclam", "socket_path") for c in checks):
            status = "degraded"
        else:
            status = "healthy"
        cause = self.root_cause(checks, eff, reachable=reachable)
        return {"status": status, "socket": path, "checks": checks, "cause": cause,
                "self_test": test, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    @staticmethod
    def root_cause(checks: list[dict], eff: dict, reachable: bool = False) -> str:
        by = {c["key"]: c for c in checks}

        def bad(k):
            return by.get(k, {}).get("state") == "fail"
        if reachable:
            if bad("self_test"):
                return "clamd answers but the scan self-test failed."
            if bad("tcp"):
                return "clamd listens on the network (TCPSocket)."
            if bad("signatures"):
                return ("clamd runs, but some signature files are missing: after a restart Debian's clamav-daemon would "
                        "refuse to start (its start condition needs main and daily).")
            return ""
        if bad("packages"):
            return "ClamAV is not (fully) installed."
        if bad("conf_options"):
            return ("clamd.conf contains an option this clamd does not know ("
                    + by["conf_options"]["detail"].split(" is not")[0]
                    + "), so clamav-daemon exits at start and the socket is never served. Earlier Personal DM releases "
                    "added EnableVersionCommand, which only Ubuntu's clamd supports.")
        if bad("signatures"):
            return "No signature files: Debian's clamav-daemon refuses to start without them (its start condition)."
        if "skipped by its start condition" in by.get("daemon", {}).get("detail", ""):
            return ("clamav-daemon was skipped at start because no signatures existed yet, and nothing started it after "
                    "freshclam downloaded them.")
        if bad("daemon") and ("oom" in by.get("daemon", {}).get("detail", "").lower()
                              or "memory" in by.get("journal", {}).get("detail", "")):
            return "clamd was stopped by the out-of-memory killer and Debian's unit does not restart it."
        if bad("socket_file") and eff.get("mismatch") and not bad("daemon"):
            return (f"clamd.conf LocalSocket ({eff['configured']}) differs from the systemd socket ({eff['unit']}); clamd "
                    "bound its own socket file and removed it when it restarted, so the path the app uses no longer exists.")
        if bad("daemon"):
            return "clamav-daemon is not running (see the clamd log hint and journalctl -u clamav-daemon)."
        if bad("socket_unit"):
            return "clamav-daemon.socket is not listening."
        if bad("run_dir") or bad("socket_file"):
            return "The socket file is missing although the daemon runs."
        if bad("access"):
            return "The Personal DM service account cannot connect to the socket (permissions)."
        if bad("self_test"):
            return "clamd answers but the scan self-test failed."
        if bad("tcp"):
            return "clamd listens on the network (TCPSocket)."
        return ""

    # ---------------------------------------------------------------- repair (root)
    def repair(self, *, apt: bool = True, wait_seconds: int = 240) -> dict:
        """Idempotent repair. Every step is recorded; nothing is reported as fixed unless the final diagnosis says so."""
        steps: list[dict] = []

        def step(name, ok, detail=""):
            steps.append({"step": name, "ok": ok, "detail": str(detail)[-400:]})
            return ok

        if not self.as_root:
            step("permissions", False, "repair needs root (sudo personaldocs antivirus repair)")
            return {"steps": steps, "result": self.diagnose()}
        before = self.diagnose(self_test=False)
        step("diagnosis before repair", True, before["cause"] or "no fatal problem found")
        missing = [p for p, ok in self.packages().items() if not ok]
        if missing and apt:
            code, out = self._out(["apt-get", "install", "-y", "-q", "--no-install-recommends", *PACKAGES], timeout=1800)
            step("install packages", code == 0, out if code else "installed " + ", ".join(missing))
        elif missing:
            step("install packages", False, "missing: " + ", ".join(missing))
        sock_path = self.unit_socket() or DEFAULT_SOCKET
        if self.conf.exists():
            text = self.conf.read_text(errors="replace")
            new = set_conf(text, {"TCPSocket": None, "TCPAddr": None, "LocalSocket": sock_path, "LocalSocketMode": "666",
                                  "FixStaleSocket": "true", "StreamMaxLength": "1100M", "ConcurrentDatabaseReload": "no",
                                  **{k: None for k in UNSUPPORTED_OPTIONS}})
            if new != text:
                backup = self.conf.with_name("clamd.conf.personaldocs-backup")
                if not backup.exists():
                    backup.write_text(text)
                self.conf.write_text(new)
                step("clamd.conf", True, f"LocalSocket {sock_path}, Unix socket only (backup: {backup.name})")
            else:
                step("clamd.conf", True, "already correct")
            had = {ln.strip().split(" ", 1)[0] for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")}
            removed = [k for k in UNSUPPORTED_OPTIONS if k in had]
            if removed:
                step("remove unsupported options", True, ", ".join(removed) + " removed (clamd refuses to start with them)")
            code, out = self._out(["clamconf", "-n"], timeout=60)
            if code != 127:
                extra = [k for k in unknown_options(out) if k in read_conf(self.conf)]
                if extra:  # any other option this clamd rejects: take it out rather than leave clamd unable to start
                    self.conf.write_text(set_conf(self.conf.read_text(errors="replace"), {k: None for k in extra}))
                    step("remove unsupported options", True, ", ".join(extra) + " removed (rejected by clamconf)")
                    code, out = self._out(["clamconf", "-n"], timeout=60)
                bad = [ln for ln in out.splitlines() if "ERROR" in ln or "Can't parse" in ln or "Unknown option" in ln]
                step("validate clamd.conf (clamconf)", not bad, "; ".join(bad) or "no errors")
        else:
            step("clamd.conf", False, f"{self.conf} does not exist (reinstall clamav-daemon)")
        self.dropin.parent.mkdir(parents=True, exist_ok=True)
        if not self.dropin.exists() or self.dropin.read_text() != DROPIN_TEXT:
            self.dropin.write_text(DROPIN_TEXT)
        self.tmpfiles.parent.mkdir(parents=True, exist_ok=True)
        if not self.tmpfiles.exists() or self.tmpfiles.read_text() != TMPFILES_TEXT:
            self.tmpfiles.write_text(TMPFILES_TEXT)
        self._out(["systemd-tmpfiles", "--create", str(self.tmpfiles)])
        code, out = self._out(["systemctl", "daemon-reload"])
        step("restart policy + runtime directory", code == 0, f"{self.dropin}, {self.tmpfiles}")
        if not all(self.signatures().values()):
            self._out(["systemctl", "stop", FRESHCLAM])
            code, out = self._out(["freshclam", "--stdout"], timeout=900)
            step("download signatures (freshclam)", code == 0 and all(self.signatures().values()), out.splitlines()[-1] if out else code)
        self._out(["systemctl", "enable", FRESHCLAM, SOCKET_UNIT, SERVICE])
        self._out(["systemctl", "start", FRESHCLAM])
        self._out(["systemctl", "stop", SERVICE, SOCKET_UNIT], timeout=120)
        pid = self.run_dir / "clamd.pid"
        if pid.exists():
            pid.unlink(missing_ok=True)
        self._out(["systemctl", "reset-failed", SERVICE, SOCKET_UNIT])
        code, out = self._out(["systemctl", "start", SOCKET_UNIT, SERVICE], timeout=480)
        step("start clamav-daemon.socket and clamav-daemon", code == 0, out or "started")
        deadline = time.monotonic() + wait_seconds
        up, detail = False, ""
        while time.monotonic() < deadline:
            up, detail = self.ping(sock_path)
            if up:
                break
            self.sleep(3)
        step(f"wait for {sock_path} (clamd loads signatures)", up, "PONG" if up else detail)
        result = self.diagnose()
        step("final status", result["status"] in ("healthy", "degraded"), result["status"] + (f" — {result['cause']}" if result["cause"] else ""))
        return {"steps": steps, "result": result}


def format_report(diag: dict) -> str:
    sym = {"ok": "✔", "warn": "!", "fail": "✘", "info": "•"}
    lines = [f"ClamAV status: {diag['status'].upper()}   socket: {diag['socket']}"]
    for c in diag["checks"]:
        lines.append(f"  {sym.get(c['state'], '•')} {c['label']}: {c['detail']}")
        if c.get("fix") and c["state"] in ("fail", "warn"):
            lines.append(f"      → {c['fix']}")
    if diag.get("cause"):
        lines.append(f"Likely cause: {diag['cause']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Diagnose or repair the local ClamAV daemon for Personal Documents.")
    ap.add_argument("action", choices=("status", "repair", "selftest", "socket"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    c = Clamav()
    if args.action == "socket":
        print(c.effective_socket()["path"])
        return 0
    if args.action == "repair":
        out = c.repair()
        if args.json:
            print(json.dumps(out))
        else:
            for s in out["steps"]:
                print(f"{'✔' if s['ok'] else '✘'} {s['step']}: {s['detail']}")
            print(format_report(out["result"]))
        return 0 if out["result"]["status"] in ("healthy", "degraded") else 1
    if args.action == "selftest":
        path = c.effective_socket()["path"]
        res = c.self_test(path)
        print(json.dumps(res) if args.json else f"Self-test via {path}: {'PASSED' if res['ok'] else 'FAILED'} — {res['detail']}")
        return 0 if res["ok"] else 1
    diag = c.diagnose()
    print(json.dumps(diag) if args.json else format_report(diag))
    return 0 if diag["status"] in ("healthy", "degraded") else 1


if __name__ == "__main__":
    raise SystemExit(main())
