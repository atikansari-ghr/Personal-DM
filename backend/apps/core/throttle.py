"""Adaptive background throttling (Change Set X).

The scheduler takes a system sample about once a minute (``perf.sample_system``) and calls ``evaluate``. When the
server stays under heavy load, two samples in a row (about two minutes, so brief spikes are ignored), throttling
starts: the job worker stops STARTING non-urgent jobs (``DEFERRABLE``) until the load has been normal for three
samples. Nothing running is interrupted: a running OCR, scan or backup finishes normally. A postponed job starts
anyway after ``performance.max_defer_minutes`` (default 15), so nothing waits forever.

Never postponed: notifications and security alerts, sign-in related work, the antivirus check of a new upload and
upload processing other than text recognition, backups and their verification, recovery, key rotation.

The state is kept in ``SchedulerRun("throttle")`` (shown in Admin → Performance) and every start and end is
recorded as a performance event with its reason.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.utils import timezone

log = logging.getLogger("personaldocs.performance")
RUN = "throttle"
HOT_SAMPLES, CALM_SAMPLES = 2, 3
# job kinds whose START may be postponed under sustained load (they are slow and nobody is waiting on them)
DEFERRABLE = frozenset({"ocr_run", "ocr_bulk", "av_library_scan", "ai_task", "goaccess_report", "geoip_update",
                        "integrity_check", "import_server", "email_poll"})


def _run():
    from apps.notify.models import SchedulerRun

    run, _ = SchedulerRun.objects.get_or_create(name=RUN)
    return run


def reasons(sample: dict) -> list[str]:
    """Which thresholds this sample exceeds (empty: normal)."""
    from . import config

    out = []
    cpu = sample.get("cpu_percent")
    if cpu is not None and cpu >= int(config.get("performance.throttle_cpu_percent")):
        out.append(f"CPU {cpu:.0f}%")
    mem = sample.get("mem_available_percent")
    if mem is not None and mem <= int(config.get("performance.throttle_memory_available_percent")):
        out.append(f"memory available {mem:.0f}%")
    swap = sample.get("swap_used_percent")
    if swap is not None and swap >= int(config.get("performance.throttle_swap_percent")):
        out.append(f"swap used {swap:.0f}%")
    io = sample.get("psi_io")
    if io is not None and io >= int(config.get("performance.throttle_io_pressure")):
        out.append(f"disk pressure {io:.0f}%")
    return out


def evaluate(sample: dict) -> dict:
    """Update the throttle state from one sample; returns the state."""
    from . import config, perf

    run = _run()
    st = {"active": False, "hot": 0, "calm": 0, "since": None, "reason": "", **(run.state or {})}
    if not config.get("performance.throttle_enabled"):
        if st["active"]:
            perf.event("throttle_end", "Background processing no longer throttled (throttling turned off)")
        st.update(active=False, hot=0, calm=0, since=None, reason="")
    else:
        why = reasons(sample)
        if why:
            st["hot"], st["calm"] = st["hot"] + 1, 0
            if not st["active"] and st["hot"] >= HOT_SAMPLES:
                st.update(active=True, since=timezone.now().isoformat(), reason=", ".join(why))
                perf.event("throttle_start", f"Background processing throttled: {', '.join(why)}", reasons=why)
                log.warning("background processing throttled: %s", ", ".join(why))
            elif st["active"]:
                st["reason"] = ", ".join(why)
        else:
            st["calm"], st["hot"] = st["calm"] + 1, 0
            if st["active"] and st["calm"] >= CALM_SAMPLES:
                started = st.get("since")
                perf.event("throttle_end", "Background processing resumed: load back to normal", since=started)
                log.info("background processing resumed")
                st.update(active=False, since=None, reason="")
    st["checked_at"] = timezone.now().isoformat()
    run.state = st
    run.last_run_at = timezone.now()
    run.save(update_fields=["state", "last_run_at"])
    return st


_cache = {"at": 0.0, "active": False}


def active() -> bool:
    """For the job worker: is throttling on? (read at most every 15 seconds)"""
    if time.monotonic() - _cache["at"] > 15:
        try:
            _cache["active"] = bool((_run().state or {}).get("active"))
        except Exception:  # noqa: BLE001 - never block work because the state cannot be read
            _cache["active"] = False
        _cache["at"] = time.monotonic()
    return _cache["active"]


def defer_cutoff():
    """Deferrable jobs queued after this moment wait; older ones run anyway (longest postponement)."""
    from . import config

    return timezone.now() - timedelta(minutes=int(config.get("performance.max_defer_minutes") or 15))


def state() -> dict:
    try:
        return dict(_run().state or {}, active=bool((_run().state or {}).get("active")))
    except Exception:  # noqa: BLE001
        return {"active": False}
