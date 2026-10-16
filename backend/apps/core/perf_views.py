"""Admin → Performance (Change Set X): recent measurements, warnings and the Performance Diagnostic Report.

Administrators see the dashboard; only the main administrator downloads the diagnostic report. Nothing here
contains passwords, tokens, recovery keys, document contents, file names, search words or personal details:
requests are listed by route pattern, jobs by kind.
"""
from __future__ import annotations

import os
import platform
from collections import defaultdict
from datetime import timedelta

from django.conf import settings as dj
from django.db import connection
from django.db.models import Max, Sum
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsAdministrator, IsMainAdmin

from . import audit, config, perf, perfcache, throttle
from .models import PerfBucket, PerfEvent

PROCESS_STARTED = timezone.now()


def _window(request) -> int:
    try:
        return max(1, min(24 * 14, int(request.query_params.get("hours", 24))))
    except ValueError:
        return 24


def _aggregate(kind: str, since) -> list[dict]:
    rows = (PerfBucket.objects.filter(kind=kind, bucket__gte=since).values("name")
            .annotate(n=Sum("count"), total=Sum("total_ms"), mx=Max("max_ms"), q=Sum("queries"), db=Sum("db_ms"), err=Sum("errors")))
    out = []
    for r in rows:
        n = r["n"] or 0
        out.append({"name": r["name"], "count": n, "avg_ms": round((r["total"] or 0) / max(1, n), 1), "max_ms": round(r["mx"] or 0, 1),
                    "avg_queries": round((r["q"] or 0) / max(1, n), 1), "avg_db_ms": round((r["db"] or 0) / max(1, n), 1),
                    "errors": r["err"] or 0})
    return out


def _trend(since) -> dict:
    series = defaultdict(list)
    for b in PerfBucket.objects.filter(kind="system", bucket__gte=since).order_by("bucket"):
        series[b.name].append({"at": b.bucket, "avg": round(b.total_ms / max(1, b.count), 1), "max": round(b.max_ms, 1)})
    api = defaultdict(lambda: [0, 0.0])
    for b in PerfBucket.objects.filter(kind="api", bucket__gte=since).values("bucket").annotate(n=Sum("count"), t=Sum("total_ms")):
        api[b["bucket"]] = [b["n"], b["t"]]
    series["api_avg_ms"] = [{"at": k, "avg": round(v[1] / max(1, v[0]), 1), "max": None} for k, v in sorted(api.items())]
    series["api_requests"] = [{"at": k, "avg": v[0], "max": None} for k, v in sorted(api.items())]
    return dict(series)


def _heartbeats() -> dict:
    from apps.notify.models import SchedulerRun

    now = timezone.now()
    out = {}
    for name in ("worker_heartbeat", "scheduler_heartbeat"):
        r = SchedulerRun.objects.filter(name=name).first()
        out[name.replace("_heartbeat", "")] = {"last_seen": r.last_run_at if r else None,
                                                "age_seconds": int((now - r.last_run_at).total_seconds()) if r and r.last_run_at else None}
    return out


def _warnings(sample: dict, api: list[dict], jobs: list[dict], beats: dict, th: dict) -> list[str]:
    out = []
    if th.get("active"):
        out.append(f"Background processing throttled: {th.get('reason') or 'heavy load'}.")
    mem = sample.get("mem_available_percent")
    if mem is not None and mem < 15:
        out.append(f"Little memory available ({mem:.0f}%).")
    swap = sample.get("swap_used_percent")
    if swap is not None and swap > 30:
        out.append(f"Swap in use ({swap:.0f}%): the server may be short of memory.")
    if (sample.get("storage_latency_ms") or 0) > 200:
        out.append(f"Slow storage: writing 4 KB took {sample['storage_latency_ms']:.0f} ms.")
    if (sample.get("jobs_queued") or 0) > 50:
        out.append(f"{sample['jobs_queued']} background jobs are waiting.")
    conns, maxc = sample.get("db_connections"), sample.get("db_max_connections")
    if conns and maxc and conns > 0.8 * maxc:
        out.append(f"Database connections nearly used up ({conns} of {maxc}).")
    for name, b in beats.items():
        if b["age_seconds"] is None or b["age_seconds"] > 180:
            out.append(f"The {name} has not reported for {b['age_seconds'] or '—'} seconds.")
    for r in sorted(api, key=lambda r: -r["avg_ms"])[:3]:
        if r["avg_ms"] > 1000 and r["count"] >= 3:
            out.append(f"Slow requests: {r['name']} averages {r['avg_ms']:.0f} ms.")
    return out


def overview(hours: int) -> dict:
    from apps.notify.models import SchedulerRun

    since = timezone.now() - timedelta(hours=hours)
    perf.flush_now()  # include this process's latest numbers
    sample_row = SchedulerRun.objects.filter(name="perf_sample").first()
    sample = (sample_row.state if sample_row else None) or {}
    api = sorted(_aggregate("api", since), key=lambda r: -r["count"])
    jobs = sorted(_aggregate("job", since), key=lambda r: -r["count"])
    client = _aggregate("client", since)
    beats = _heartbeats()
    th = throttle.state()
    total = sum(r["count"] for r in api)
    return {
        "window_hours": hours,
        "version": getattr(dj, "APP_VERSION", ""),
        "sampled_at": sample_row.last_run_at if sample_row else None,
        "system": sample,
        "throttle": th,
        "requests": {"total": total, "avg_ms": round(sum(r["avg_ms"] * r["count"] for r in api) / max(1, total), 1),
                     "errors": sum(r["errors"] for r in api), "by_route": api[:40],
                     "slowest": sorted(api, key=lambda r: -r["avg_ms"])[:10],
                     "most_queries": sorted(api, key=lambda r: -r["avg_queries"])[:10]},
        "jobs": jobs,
        "client_errors": client,
        "cache": {"settings_snapshot": config.cache_stats(), "shared": perfcache.stats(),
                  "note": "Counters of the web process that answered this request, since it started."},
        "workers": {**beats, "web_workers": os.environ.get("PD_WEB_WORKERS"), "web_threads": os.environ.get("PD_WEB_THREADS"),
                    "process_started": PROCESS_STARTED},
        "trend": _trend(since),
        "events": [{"at": e.at, "kind": e.kind, "message": e.message} for e in PerfEvent.objects.all()[:30]],
        "warnings": _warnings(sample, api, jobs, beats, th),
    }


@api_view(["GET"])
@permission_classes([IsAdministrator])
def performance(request):
    return Response(overview(_window(request)))


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def diagnostic_report(request):
    """Performance Diagnostic Report: the dashboard data plus the environment and performance settings."""
    data = overview(_window(request))
    with connection.cursor() as cur:
        cur.execute("SHOW server_version")
        pg = cur.fetchone()[0]
        db = {}
        for k in ("shared_buffers", "work_mem", "effective_cache_size", "max_connections"):
            cur.execute(f"SHOW {k}")
            db[k] = cur.fetchone()[0]
        cur.execute("SELECT pg_database_size(current_database())")
        db["database_size_mb"] = round(cur.fetchone()[0] / 2**20)
    from apps.library.models import Document, Folder

    data["environment"] = {
        "python": platform.python_version(), "postgresql": pg, "database": db, "os": platform.platform(terse=True),
        "cpus": os.cpu_count(), "settings": {k: config.get(k) for k in (
            "performance.throttle_enabled", "performance.throttle_cpu_percent", "performance.throttle_memory_available_percent",
            "performance.throttle_swap_percent", "performance.throttle_io_pressure", "performance.max_defer_minutes",
            "performance.slow_request_ms", "processing.heavy_concurrency")},
        "dataset": {"documents": Document.objects.count(), "folders": Folder.objects.count()},
    }
    data["generated_at"] = timezone.now()
    audit.record("performance.report", request=request, hours=data["window_hours"])
    resp = JsonResponse(data, json_dumps_params={"indent": 1, "default": str})
    resp["Content-Disposition"] = f'attachment; filename="performance-report-{timezone.now():%Y%m%d-%H%M}.json"'
    return resp


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def client_report(request):
    """Browsers report loading problems (failed API calls, app files that did not load): counts only."""
    kinds = {"api_error", "network_error", "chunk_error"}
    for e in (request.data.get("errors") or [])[:20]:
        kind = str(e.get("kind") or "")
        if kind not in kinds:
            continue
        status = str(e.get("status") or "")[:3]
        perf.add("client", f"{kind} {status}".strip(), float(e.get("ms") or 0), error=True)
    return Response(status=204)
