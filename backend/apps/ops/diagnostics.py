"""Read-only diagnostics for Settings → System → Maintenance & Operations (Change Set AB).

* ``run_doctor()``      — the same checks as ``personaldocs doctor`` (one implementation: the doctor management
  command's ``run_checks``), collected as structured, sanitised results grouped by component.
* ``health_panels()``   — Database, OCR, AI, Security, Backup and Storage health from the existing health sources.
* ``system_info()``     — version, commit, Debian, uptime, CPU/load, memory, storage, database, OCR and safe AI
  information, workers. Never a secret: no keys, tokens, passwords, cookies or connection strings.
* ``safe_caches()`` / ``clear_safe_caches()`` — rebuildable caches only. Documents, OCR provenance, metadata, backups,
  audit logs, AI history, configuration, offline data and recovery material are never touched.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from .sanitize import known_secrets, redact

PASS, WARNING, FAIL, INFO = "PASS", "WARNING", "FAIL", "INFO"
NOT_CONFIGURED, NOT_APPLICABLE, NOT_TESTED = "NOT CONFIGURED", "NOT APPLICABLE", "NOT TESTED"
STATUSES = (PASS, WARNING, FAIL, NOT_CONFIGURED, NOT_APPLICABLE, NOT_TESTED, INFO)
# a FAIL in these components is a critical Doctor finding (notification to the main administrator)
CRITICAL_COMPONENTS = ("Database", "Filesystem", "Backup & recovery", "Security & authentication")
_HINT = re.compile(r"(?:→|\brun\b|\(run\b)\s*:?\s*`?(sudo personaldocs [a-z\- ]+|Settings → [^;)]+)`?", re.I)


class CollectSink:
    """Doctor output as data: one result per check, grouped by the section (component) it was reported in."""

    def __init__(self):
        self.component, self.results, self._secrets = "General", [], known_secrets()

    def section(self, name):
        self.component = name

    def _add(self, name, status, detail=""):
        detail = redact(str(detail or ""), secrets=self._secrets)
        hint = _HINT.search(detail)
        self.results.append({"component": self.component, "check": redact(str(name), secrets=self._secrets), "status": status,
                             "detail": detail, "recommended": hint.group(1).strip() if hint and status in (FAIL, WARNING) else ""})

    def report(self, name, good, detail=""):
        self._add(name, PASS if good else FAIL, detail)

    def warn(self, name, detail=""):
        self._add(name, WARNING, detail)

    def info(self, name, detail=""):
        self._add(name, INFO, detail)

    def status(self, name, state, detail=""):
        self._add(name, state if state in STATUSES else NOT_TESTED, detail)


def run_doctor() -> dict:
    """Run every Doctor check (read-only) and return grouped, sanitised results with counts."""
    from .management.commands.doctor import Command

    sink = CollectSink()
    started = time.monotonic()
    try:
        Command().run_checks(sink)
    except Exception as exc:  # noqa: BLE001 - a crashed check is reported, never raised to the browser
        sink.section("Doctor")
        sink.status("diagnostics", NOT_TESTED, f"stopped early: {exc.__class__.__name__}")
    groups: dict[str, list] = {}
    for r in sink.results:
        groups.setdefault(r["component"], []).append(r)
    counts = {s: sum(1 for r in sink.results if r["status"] == s) for s in STATUSES}
    overall = FAIL if counts[FAIL] else WARNING if counts[WARNING] else PASS
    return {"overall": overall, "counts": counts, "seconds": round(time.monotonic() - started, 1),
            "components": [{"component": k, "status": _worst(v), "results": v} for k, v in groups.items()],
            "critical": [r for r in sink.results if r["status"] == FAIL and r["component"] in CRITICAL_COMPONENTS],
            "checked_at": timezone.now().isoformat()}


def _worst(results) -> str:
    order = (FAIL, WARNING, NOT_TESTED, PASS, NOT_CONFIGURED, NOT_APPLICABLE, INFO)
    states = {r["status"] for r in results}
    return next((s for s in order if s in states), INFO)


def doctor_report_text(result: dict, *, anonymized: bool = False) -> str:
    """Plain-text Doctor report for download (always redacted; optionally anonymised for a support request)."""
    from . import sanitize

    lines = [f"Personal DM Doctor report — {result.get('checked_at', '')}", f"Overall: {result.get('overall')}",
             "Counts: " + ", ".join(f"{k} {v}" for k, v in (result.get("counts") or {}).items() if v), ""]
    for comp in result.get("components") or []:
        lines.append(f"== {comp['component']} ({comp['status']})")
        for r in comp["results"]:
            lines.append(f"[{r['status']}] {r['check']}" + (f" - {r['detail']}" if r["detail"] else ""))
        lines.append("")
    text = "\n".join(lines)
    return sanitize.anonymize(text) if anonymized else sanitize.redact(text)


# ------------------------------------------------------------------ health panels

def _panel(key, label, state, summary, facts=(), link=""):
    return {"key": key, "label": label, "state": state, "summary": summary,
            "facts": [{"label": a, "value": b} for a, b in facts], "link": link}


def _safe(fn, key, label):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - a broken source shows as Unknown, never a 500
        return _panel(key, label, "unknown", f"Could not be checked ({exc.__class__.__name__}).")


def database_health() -> dict:
    from django.db.migrations.executor import MigrationExecutor

    with connection.cursor() as cur:
        cur.execute("SELECT version()")
        version = cur.fetchone()[0].split(",")[0]
        size = None
        if connection.vendor == "postgresql":
            cur.execute("SELECT pg_database_size(current_database()), (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database())")
            size, conns = cur.fetchone()
        else:
            conns = None
    ex = MigrationExecutor(connection)
    pending = len(ex.migration_plan(ex.loader.graph.leaf_nodes()))
    state = "critical" if pending else "ok"
    return _panel("database", "Database", state,
                  f"{pending} migration(s) pending" if pending else "Reachable; all migrations applied",
                  [("Version", version), ("Size", _fmt_bytes(size)), ("Connections", conns if conns is not None else "—"),
                   ("Pending migrations", pending)], "/settings/system")


def ocr_health() -> dict:
    from apps.core import config
    from apps.core.models import Job
    from apps.library import ocr_engines

    if not config.get("processing.ocr_enabled"):
        return _panel("ocr", "OCR", "not_configured", "OCR is switched off.", link="/settings/ocr")
    eng = ocr_engines.engines_overview()
    used = [e for e in eng if e["position"]]
    primary_ok = bool(used and used[0]["available"])
    any_ok = any(e["available"] for e in used)
    failed = Job.objects.filter(kind="ocr_run", status=Job.FAILED, finished_at__gte=timezone.now() - timedelta(days=1)).count()
    state = "ok" if primary_ok and not failed else "warning" if any_ok else "critical"
    return _panel("ocr", "OCR", state,
                  ("Primary engine available" if primary_ok else "Primary engine unavailable; " + ("a fallback works" if any_ok else "no engine works")),
                  [*((e["role"], e["label"] + ("" if e["available"] else f" — {e['reason']}")) for e in used),
                   ("Queue", f"{Job.objects.filter(kind='ocr_run', status=Job.QUEUED).count()} queued, "
                             f"{Job.objects.filter(kind='ocr_run', status=Job.RUNNING).count()} running"),
                   ("Failed (24 h)", failed)], "/settings/ocr")


def ai_health() -> dict:
    from apps.ai import service
    from apps.ai.models import AIJob
    from apps.core import config

    if not config.get("ai.enabled") or service.mode() == "ocr_only":
        return _panel("ai", "AI", "not_configured", "AI is switched off.", [("Mode", service.MODE_LABELS[service.mode()])], "/settings/ai")
    p = service.default_profile()
    failed = AIJob.objects.filter(status="failed", created_at__gte=timezone.now() - timedelta(days=1)).count()
    tested = (p.last_test or {}).get("ok") if p else None
    state = "critical" if p is None else "warning" if failed or tested is False else "ok"
    return _panel("ai", "AI", state, "No default AI profile" if p is None else f"Default profile “{p.name}”",
                  [("Mode", service.MODE_LABELS[service.mode()]),
                   ("Provider", (p.get_provider_display() if p else "—")), ("Location", ("Cloud" if p.is_cloud else "Local") if p else "—"),
                   ("Text model", (p.text_model or "—") if p else "—"),
                   ("Last test", ("passed" if tested else "failed" if tested is False else "not tested") if p else "—"),
                   ("Failed jobs (24 h)", failed)], "/settings/ai")


def security_panel() -> dict:
    from apps.security import center

    h = center.security_health()
    state = "critical" if h["status"] == "At Risk" else "warning" if h["status"] != "Healthy" else "ok"
    weak = [(k, c) for k, c in (h.get("components") or {}).items() if isinstance(c, dict) and c.get("status") in ("bad", "warn")]
    return _panel("security", "Security", state, f"{h['status']} — score {h['score']}/100",
                  [*(("Forced", f) for f in h.get("forced", [])[:3]),
                   *((k.replace("_", " ").capitalize(), c.get("detail") or "") for k, c in weak[:6])],
                  "/settings/security")


def backup_panel() -> dict:
    from . import bk_engine

    h = bk_engine.health()
    lv = h.get("latest_verified")
    state = {"critical": "critical", "attention": "warning"}.get(h["state"], "ok" if h["state"] == "healthy" else "warning")
    return _panel("backup", "Backup", state, h["label"],
                  [("Newest verified", f"{lv['kind']} {lv['created_at'][:16]}" if lv else "none"),
                   ("Recovery readiness", h["readiness"]["label"]), *(("Warning", w) for w in h["warnings"][:3])],
                  "/settings/backup")


def storage_panel() -> dict:
    from apps.security import center

    h = center.storage_health()
    state = {"critical": "critical", "warning": "warning"}.get(h["status"], "ok")
    return _panel("storage", "Storage", state, f"{h['percent']}% used, {_fmt_bytes(h['free'])} free",
                  [("Total", _fmt_bytes(h["total"])), ("Free", _fmt_bytes(h["free"])),
                   ("Warning / critical at", f"{h['thresholds']['warning']}% / {h['thresholds']['critical']}%")],
                  "/settings/security?view=storage")


def health_panels() -> list[dict]:
    return [_safe(database_health, "database", "Database"), _safe(ocr_health, "ocr", "OCR"), _safe(ai_health, "ai", "AI"),
            _safe(security_panel, "security", "Security"), _safe(backup_panel, "backup", "Backup"),
            _safe(storage_panel, "storage", "Storage")]


# ------------------------------------------------------------------ system information

def _fmt_bytes(n) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _meminfo() -> dict:
    out = {}
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = ln.partition(":")
            out[k] = int(v.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return out


def _os_release() -> str:
    try:
        for ln in Path("/etc/os-release").read_text().splitlines():
            if ln.startswith("PRETTY_NAME="):
                return ln.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return platform.platform()


def _revision() -> str:
    for p in (Path(settings.REPO_DIR) / "REVISION",):
        try:
            return p.read_text().strip()[:40]
        except OSError:
            pass
    try:
        import subprocess

        r = subprocess.run(["git", "-C", str(settings.REPO_DIR), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()[:40] if r.returncode == 0 else ""
    except (OSError, ValueError):
        return ""


def installed_version() -> dict:
    return {"version": settings.APP_VERSION, "revision": _revision()}


def system_info() -> dict:
    import django

    from apps.ai import service
    from apps.core import config
    from apps.library import ocr_engines
    from apps.notify.models import SchedulerRun

    mem = _meminfo()
    try:
        uptime = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        uptime = None
    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        load = []
    du = shutil.disk_usage(settings.DATA_DIR if Path(settings.DATA_DIR).exists() else "/")
    with connection.cursor() as cur:
        cur.execute("SELECT version()")
        db_version = cur.fetchone()[0].split(",")[0]
    now = timezone.now()
    workers = []
    for name, label in (("worker_heartbeat", "Background worker"), ("scheduler_heartbeat", "Scheduler")):
        hb = SchedulerRun.objects.filter(name=name).first()
        alive = bool(hb and hb.last_run_at and now - hb.last_run_at < timedelta(minutes=5))
        workers.append({"name": label, "running": alive, "last_seen": hb.last_run_at.isoformat() if hb and hb.last_run_at else None})
    paddle = ocr_engines.paddle_status() or {}
    light = ocr_engines.light_ocr_status() or {}
    p = service.default_profile() if config.get("ai.enabled") else None
    ver = installed_version()
    return {
        "application": {"version": ver["version"], "revision": ver["revision"][:12], "python": platform.python_version(),
                        "django": django.get_version()},
        "os": {"name": _os_release(), "kernel": platform.release(), "architecture": platform.machine(), "uptime_seconds": uptime},
        "cpu": {"count": os.cpu_count(), "load": load},
        "memory": {"total": mem.get("MemTotal"), "available": mem.get("MemAvailable"), "swap_total": mem.get("SwapTotal"),
                   "swap_free": mem.get("SwapFree")},
        "storage": {"total": du.total, "used": du.used, "free": du.free},
        "database": {"version": db_version},
        "ocr": {"tesseract": ocr_engines.tesseract_version(), "paddleocr": (paddle.get("paddleocr") or "installed") if paddle.get("installed") else "not installed",
                "light_ocr": light.get("version") or ("installed" if light.get("installed") else "not installed"),
                "order": ocr_engines.engine_order()},
        "ai": {"enabled": bool(config.get("ai.enabled")), "mode": service.MODE_LABELS[service.mode()],
               "default_profile": p.name if p else None, "provider": p.get_provider_display() if p else None,
               "location": ("Cloud" if p.is_cloud else "Local") if p else None, "text_model": (p.text_model or None) if p else None},
        "workers": workers,
        "collected_at": now.isoformat(),
    }


# ------------------------------------------------------------------ safe caches

STALE_TMP = timedelta(hours=24)


def _dir_bytes(path: Path) -> tuple[int, int]:
    total = count = 0
    if not path.exists():
        return 0, 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
                count += 1
        except OSError:
            pass
    return total, count


def _stale_tmp_entries() -> list[Path]:
    """Top-level entries in the temporary and export directories untouched for 24 hours (never the upload staging
    directory, which holds uploads in progress)."""
    cutoff = time.time() - STALE_TMP.total_seconds()
    out = []
    for base in (Path(settings.TMP_DIR), Path(settings.EXPORT_TMP_DIR)):
        if not base.exists():
            continue
        for p in base.iterdir():
            try:
                if p.lstat().st_mtime < cutoff and not p.is_symlink():
                    out.append(p)
            except OSError:
                pass
    return out


def safe_caches() -> list[dict]:
    """Every cache this action may clear, with its size, what clearing it does and how it is rebuilt."""
    from apps.core.models import WeatherCache

    shared = Path(settings.DATA_DIR) / "cache" / "shared"
    s_bytes, s_count = _dir_bytes(shared)
    stale = _stale_tmp_entries()
    t_bytes = 0
    for p in stale:
        t_bytes += p.stat().st_size if p.is_file() else _dir_bytes(p)[0]
    probes = list(Path(settings.TMP_DIR).glob(".perf-probe-*")) if Path(settings.TMP_DIR).exists() else []
    return [
        {"key": "shared", "label": "Shared summary cache", "bytes": s_bytes, "items": s_count,
         "effect": "Overview counts and summaries are recomputed the next time they are shown (slightly slower once).",
         "regeneration": "Automatic, on demand."},
        {"key": "temporary", "label": "Stale temporary and export files (older than 24 hours)", "bytes": t_bytes, "items": len(stale),
         "effect": "Leftover working files of finished OCR, conversion and export jobs are removed.",
         "regeneration": "Not needed; new jobs create their own working files."},
        {"key": "probes", "label": "Storage-latency probe files", "bytes": sum(p.stat().st_size for p in probes if p.exists()),
         "items": len(probes), "effect": "Leftover probe files of the storage check are removed.", "regeneration": "Created by the next check."},
        {"key": "weather", "label": "Weather widget cache", "bytes": None, "items": WeatherCache.objects.count(),
         "effect": "The Overview weather tile fetches a fresh forecast.", "regeneration": "Automatic, on the next Overview view."},
    ]


SAFE_CACHE_KEYS = ("shared", "temporary", "probes", "weather")


def clear_safe_caches(keys=None) -> list[dict]:
    """Clear the selected rebuildable caches. Paths are fixed here; nothing outside these locations is deleted."""
    from apps.core.models import WeatherCache

    keys = [k for k in (keys or SAFE_CACHE_KEYS) if k in SAFE_CACHE_KEYS]
    out = []
    if "shared" in keys:
        shared = Path(settings.DATA_DIR) / "cache" / "shared"
        b, n = _dir_bytes(shared)
        shutil.rmtree(shared, ignore_errors=True)
        out.append({"key": "shared", "removed_items": n, "removed_bytes": b})
    if "temporary" in keys:
        n = b = 0
        for p in _stale_tmp_entries():
            try:
                if p.is_dir():
                    b += _dir_bytes(p)[0]
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    b += p.stat().st_size
                    p.unlink(missing_ok=True)
                n += 1
            except OSError:
                pass
        out.append({"key": "temporary", "removed_items": n, "removed_bytes": b})
    if "probes" in keys:
        n = 0
        tmp = Path(settings.TMP_DIR)
        for p in (tmp.glob(".perf-probe-*") if tmp.exists() else []):
            p.unlink(missing_ok=True)
            n += 1
        out.append({"key": "probes", "removed_items": n, "removed_bytes": None})
    if "weather" in keys:
        n, _ = WeatherCache.objects.all().delete()
        out.append({"key": "weather", "removed_items": n, "removed_bytes": None})
    return out
