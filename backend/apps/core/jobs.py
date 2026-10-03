"""PostgreSQL-backed durable job queue.

* enqueue() inside a transaction: the job only becomes visible when the transaction commits.
* claim() uses SELECT ... FOR UPDATE SKIP LOCKED with a lease; a crashed worker's lease expires and
  the job is reclaimed (attempt counted).
* Heavy (OCR/conversion) jobs are limited by processing.heavy_concurrency across all workers.
* Handlers must be idempotent and re-check permissions/state at execution time.
"""
from __future__ import annotations

import logging
import os
import socket
import traceback
from datetime import timedelta
from typing import Callable

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import Job

log = logging.getLogger("personaldocs.jobs")

HANDLERS: dict[str, Callable[[Job], dict | None]] = {}
HEAVY_KINDS: set[str] = set()
LEASE = timedelta(minutes=30)


class RetryLater(Exception):
    def __init__(self, message: str, delay_seconds: int = 60):
        super().__init__(message)
        self.delay_seconds = delay_seconds


class PermanentFailure(Exception):
    pass


def handler(kind: str, heavy: bool = False):
    def deco(fn):
        HANDLERS[kind] = fn
        if heavy:
            HEAVY_KINDS.add(kind)
        return fn

    return deco


def enqueue(kind: str, payload: dict | None = None, *, idempotency_key: str | None = None, delay_seconds: int = 0,
            priority: int = 100, max_attempts: int = 3) -> Job | None:
    """Create a job. With an idempotency key, an existing job with the same key is returned instead."""
    if idempotency_key:
        existing = Job.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
    try:
        with transaction.atomic():
            return Job.objects.create(
                kind=kind,
                payload=payload or {},
                heavy=kind in HEAVY_KINDS,
                priority=priority,
                max_attempts=max_attempts,
                run_after=timezone.now() + timedelta(seconds=delay_seconds),
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        return Job.objects.filter(idempotency_key=idempotency_key).first()


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def claim(worker: str, heavy_limit: int = 1) -> Job | None:
    now = timezone.now()
    with transaction.atomic():
        running_heavy = Job.objects.filter(status=Job.RUNNING, heavy=True, locked_until__gt=now).count()
        qs = Job.objects.select_for_update(skip_locked=True).filter(
            Q(status=Job.QUEUED, run_after__lte=now) | Q(status=Job.RUNNING, locked_until__lt=now)
        )
        if running_heavy >= heavy_limit:
            qs = qs.filter(heavy=False)
        job = qs.order_by("priority", "run_after").first()
        if job is None:
            return None
        if job.status == Job.RUNNING:
            log.warning("reclaiming job %s whose lease expired (worker %s)", job.id, job.locked_by)
        job.status = Job.RUNNING
        job.attempts += 1
        job.locked_by = worker
        job.locked_until = now + LEASE
        job.save(update_fields=["status", "attempts", "locked_by", "locked_until"])
        return job


def run_job(job: Job) -> None:
    fn = HANDLERS.get(job.kind)
    try:
        if fn is None:
            raise PermanentFailure(f"no handler for job kind {job.kind}")
        result = fn(job) or {}
        Job.objects.filter(pk=job.pk).update(status=Job.DONE, result=result, finished_at=timezone.now(),
                                             locked_until=None, last_error="")
    except RetryLater as exc:
        _fail(job, str(exc), retry_delay=exc.delay_seconds)
    except PermanentFailure as exc:
        _fail(job, str(exc), permanent=True)
    except Exception as exc:  # noqa: BLE001 - recorded, retried with backoff
        log.exception("job %s (%s) failed", job.id, job.kind)
        _fail(job, f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc(limit=3)}")


def _fail(job: Job, error: str, *, permanent: bool = False, retry_delay: int | None = None) -> None:
    error = error[:4000]
    if permanent or job.attempts >= job.max_attempts:
        Job.objects.filter(pk=job.pk).update(status=Job.FAILED, last_error=error, finished_at=timezone.now(),
                                             locked_until=None)
        job.last_error = error
        on_failed = HANDLERS.get(f"{job.kind}:failed")
        if on_failed:
            try:
                on_failed(job)
            except Exception:  # pragma: no cover
                log.exception("failure hook for %s raised", job.kind)
        return
    delay = retry_delay if retry_delay is not None else min(3600, 30 * (2 ** (job.attempts - 1)))
    Job.objects.filter(pk=job.pk).update(status=Job.QUEUED, last_error=error, locked_until=None,
                                         run_after=timezone.now() + timedelta(seconds=delay))


def run_pending(max_jobs: int = 100, heavy_limit: int = 1) -> int:
    """Synchronously drain the queue (used by tests and `manage.py worker --once`)."""
    count = 0
    wid = worker_id()
    while count < max_jobs:
        job = claim(wid, heavy_limit=heavy_limit)
        if job is None:
            break
        run_job(job)
        count += 1
    return count


def retry(job_id) -> bool:
    return bool(Job.objects.filter(pk=job_id, status=Job.FAILED).update(
        status=Job.QUEUED, attempts=0, run_after=timezone.now(), last_error=""))
