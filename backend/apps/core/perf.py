"""Performance measurements (Change Set X): request and job timings, system samples, recent warnings.

Lightweight by design:
* each process adds to an in-memory summary and writes it to the database at most every 30 seconds (one statement),
  so measuring adds no query to an ordinary request;
* requests are recorded by route pattern ("GET documents/<uuid:pk>"), never by URL, so no identifiers, names,
  addresses or search words are stored; jobs by kind; nothing about document contents or secrets;
* everything is kept as 10-minute summaries for ``performance.retention_days`` (default 14) and then removed.
"""
from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from datetime import timedelta
from pathlib import Path

from django.db import connection
from django.utils import timezone

log = logging.getLogger("personaldocs.performance")
BUCKET_SECONDS = 600
FLUSH_SECONDS = 30
_lock = threading.Lock()
_buf: dict[tuple, list] = {}
_last_flush = [time.monotonic()]


def _bucket(now=None):
    now = now or timezone.now()
    return now.replace(second=0, microsecond=0, minute=now.minute - now.minute % (BUCKET_SECONDS // 60))


def add(kind: str, name: str, ms: float, *, queries: int = 0, db_ms: float = 0.0, error: bool = False, flush: bool = True) -> None:
    key = (_bucket(), kind, name[:120])
    with _lock:
        row = _buf.setdefault(key, [0, 0.0, 0.0, 0, 0.0, 0])
        row[0] += 1
        row[1] += ms
        row[2] = max(row[2], ms)
        row[3] += queries
        row[4] += db_ms
        row[5] += 1 if error else 0
    if flush and (time.monotonic() - _last_flush[0] > FLUSH_SECONDS or len(_buf) > 300):
        flush_now()


def flush_now() -> None:
    with _lock:
        items = list(_buf.items())
        _buf.clear()
        _last_flush[0] = time.monotonic()
    if not items:
        return
    values = []
    params = []
    for (bucket, kind, name), (n, total, mx, q, dbms, err) in items:
        values.append("(%s, %s, %s, %s, %s, %s, %s, %s, %s)")
        params += [bucket, kind, name, n, total, mx, q, dbms, err]
    sql = ("INSERT INTO core_perfbucket (bucket, kind, name, count, total_ms, max_ms, queries, db_ms, errors) VALUES "
           + ", ".join(values) +
           " ON CONFLICT (bucket, kind, name) DO UPDATE SET count = core_perfbucket.count + EXCLUDED.count, "
           "total_ms = core_perfbucket.total_ms + EXCLUDED.total_ms, max_ms = GREATEST(core_perfbucket.max_ms, EXCLUDED.max_ms), "
           "queries = core_perfbucket.queries + EXCLUDED.queries, db_ms = core_perfbucket.db_ms + EXCLUDED.db_ms, "
           "errors = core_perfbucket.errors + EXCLUDED.errors")
    try:
        with connection.cursor() as cur:
            cur.execute(sql, params)
    except Exception:  # noqa: BLE001 - measuring must never break the app (e.g. before migrations)
        log.debug("performance summary not written", exc_info=True)


atexit.register(lambda: _safe(flush_now))


def _safe(fn):
    try:
        fn()
    except Exception:  # noqa: BLE001
        pass


def event(kind: str, message: str, **data) -> None:
    from .models import PerfEvent

    try:
        PerfEvent.objects.create(kind=kind, message=message[:300], data=data)
    except Exception:  # noqa: BLE001
        log.debug("performance event not written", exc_info=True)


class PerformanceMiddleware:
    """Times API requests (route pattern, duration, database queries and time, server errors)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)
        q = [0, 0.0]

        def wrapper(execute, sql, params, many, context):
            t = time.perf_counter()
            try:
                return execute(sql, params, many, context)
            finally:
                q[0] += 1
                q[1] += (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        with connection.execute_wrapper(wrapper):
            response = self.get_response(request)
        ms = (time.perf_counter() - t) * 1000
        match = getattr(request, "resolver_match", None)
        name = f"{request.method} {match.route if match else 'unmatched'}"
        add("api", name, ms, queries=q[0], db_ms=q[1], error=response.status_code >= 500)
        try:
            from . import config

            slow = int(config.get("performance.slow_request_ms"))
        except Exception:  # noqa: BLE001
            slow = 2000
        if ms > slow and "stream" not in type(response).__name__.lower():
            event("slow_request", f"{name} took {ms:.0f} ms", route=name, ms=round(ms), queries=q[0], status=response.status_code)
        return response


def record_job(kind: str, ms: float, ok: bool) -> None:
    add("job", kind, ms, error=not ok)


# ------------------------------------------------------------------ system samples (scheduler, once a minute)
_cpu_prev: list = []


def _cpu_times() -> tuple[int, int] | None:
    try:
        vals = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        return vals[3] + (vals[4] if len(vals) > 4 else 0), sum(vals)
    except Exception:  # noqa: BLE001
        return None


def _cpu_percent() -> float | None:
    """CPU busy since the previous sample of this process (the scheduler: about a minute); the first sample of a
    process measures over half a second instead."""
    now = _cpu_times()
    if now is None:
        return None
    if not _cpu_prev:
        _cpu_prev[:] = list(now)
        time.sleep(0.5)
        now = _cpu_times() or now
    idle, total = now
    prev = _cpu_prev[:]
    _cpu_prev[:] = [idle, total]
    if not prev or total == prev[1]:
        return None
    return round(100.0 * (1 - (idle - prev[0]) / (total - prev[1])), 1)


def _meminfo() -> dict:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            out[k] = int(v.split()[0]) * 1024
    except Exception:  # noqa: BLE001
        pass
    return out


def _psi(kind: str) -> float | None:
    """'some avg60' of /proc/pressure/<kind> (percent of time tasks waited), when the kernel/container provides it."""
    try:
        for line in Path(f"/proc/pressure/{kind}").read_text().splitlines():
            if line.startswith("some"):
                return float(dict(p.split("=") for p in line.split()[1:])["avg60"])
    except Exception:  # noqa: BLE001
        return None
    return None


def _storage_latency_ms() -> float | None:
    """Time to write and flush 4 KB in the data folder (a harmless probe; the file is removed)."""
    from django.conf import settings

    try:
        d = Path(settings.TMP_DIR)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f".perf-probe-{os.getpid()}"
        t = time.perf_counter()
        with open(p, "wb") as fh:
            fh.write(b"\0" * 4096)
            fh.flush()
            os.fsync(fh.fileno())
        ms = (time.perf_counter() - t) * 1000
        p.unlink(missing_ok=True)
        return round(ms, 2)
    except Exception:  # noqa: BLE001
        return None


def sample_system() -> dict:
    """One system sample: CPU, memory, swap, pressure, storage latency, database connections, job queue."""
    from .models import Job

    mem = _meminfo()
    total = mem.get("MemTotal") or 0
    swap_total = mem.get("SwapTotal") or 0
    s = {
        "cpu_percent": _cpu_percent(),
        "load1": os.getloadavg()[0] if hasattr(os, "getloadavg") else None,
        "cpus": os.cpu_count(),
        "mem_total_mb": round(total / 2**20) if total else None,
        "mem_available_percent": round(100 * mem.get("MemAvailable", 0) / total, 1) if total else None,
        "swap_used_percent": round(100 * (swap_total - mem.get("SwapFree", 0)) / swap_total, 1) if swap_total else None,
        "psi_cpu": _psi("cpu"), "psi_memory": _psi("memory"), "psi_io": _psi("io"),
        "storage_latency_ms": _storage_latency_ms(),
    }
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            s["db_connections"] = cur.fetchone()[0]
            cur.execute("SHOW max_connections")
            s["db_max_connections"] = int(cur.fetchone()[0])
    except Exception:  # noqa: BLE001
        pass
    s["jobs_queued"] = Job.objects.filter(status=Job.QUEUED, run_after__lte=timezone.now()).count()
    s["jobs_running"] = Job.objects.filter(status=Job.RUNNING).count()
    for k, v in s.items():
        if isinstance(v, (int, float)) and k not in ("cpus", "mem_total_mb", "db_max_connections"):
            add("system", k, float(v), flush=False)
    flush_now()
    return s


def purge() -> int:
    from . import config
    from .models import PerfBucket, PerfEvent

    days = int(config.get("performance.retention_days") or 14)
    n = PerfBucket.objects.filter(bucket__lt=timezone.now() - timedelta(days=days)).delete()[0]
    n += PerfEvent.objects.filter(at__lt=timezone.now() - timedelta(days=max(days, 30))).delete()[0]
    return n
