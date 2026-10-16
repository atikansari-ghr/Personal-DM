"""AI background jobs. Bounded concurrency (ai.max_parallel) so AI never starves document processing.

The document is already stored, OCR'd and searchable before any AI job runs; AI failures only mark the
AIJob as failed and never touch the document state.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from apps.core import config, jobs
from apps.core.models import Job

from .models import AIJob

log = logging.getLogger("personaldocs.ai")


AI_MAX_ATTEMPTS = 3          # Change Set Y: transient failures (timeout, connection, 429, temporary 5xx) only
RETRY_DELAYS = (60, 300)     # seconds before the 2nd and the 3rd attempt


def _enqueue(ai_job: AIJob, document, delay_seconds: int = 0) -> None:
    # The OCR epoch changes when OCR data is removed; a job queued before that must not rebuild AI data from it.
    jobs.enqueue("ai_task", {"ai_job": str(ai_job.id), "epoch": getattr(document, "ocr_epoch", 0)},
                 delay_seconds=delay_seconds, max_attempts=2, priority=150)


def active_analysis(document) -> AIJob | None:
    return AIJob.objects.filter(document=document, kind=AIJob.ANALYZE, status__in=[AIJob.QUEUED, AIJob.RUNNING]).first()


def queue(kind: str, *, document, user=None, delay_seconds: int = 0, requested: bool = False) -> AIJob:
    """``requested``: a person asked for it (Analyze Document, Retry). Only then may the analysis start OCR itself;
    automatic analysis after an upload never runs OCR on a document whose type is set to manual OCR."""
    if kind == AIJob.ANALYZE:  # one analysis per document at a time: pressing Analyze again never stacks up jobs
        existing = active_analysis(document)
        if existing is not None:
            if requested and not (existing.detail or {}).get("requested"):  # a person now asked for it: OCR may run
                existing.detail = {**(existing.detail or {}), "requested": True}
                AIJob.objects.filter(pk=existing.pk).update(detail=existing.detail)
            return existing
    ai_job = AIJob.objects.create(kind=kind, document=document, requested_by=user, stage="queued",
                                  detail={"requested": True} if requested else {})
    _enqueue(ai_job, document, delay_seconds)
    return ai_job


def after_processing(document, *, skip_analyze: bool = False) -> None:
    """Called when baseline processing (or an OCR run) finished. Only enqueues; never raises."""
    from . import service

    try:
        if not config.get("ai.enabled") or not config.get("ai.auto_analyze"):
            return
        user = document.created_by or document.owner
        if not skip_analyze and (service.enabled("ocr_assist") or service.enabled("smart_organization")):
            queue(AIJob.ANALYZE, document=document, user=user)
        if service.enabled("semantic_search"):
            queue(AIJob.EMBED, document=document, user=user)
    except Exception:  # noqa: BLE001 - AI must never affect baseline processing
        log.exception("could not queue AI jobs")


def ocr_started(document) -> None:
    """OCR picked up a document an analysis is waiting for: show it as running."""
    AIJob.objects.filter(document=document, kind=AIJob.ANALYZE, status=AIJob.QUEUED, stage="ocr_queued").update(stage="ocr_running")


def resume_after_ocr(document, *, ok: bool, error: str = "") -> int:
    """Change Set Y: OCR that an analysis waited for has finished. On success the analysis continues with the new text
    (no polling); on failure it fails at the OCR stage and the AI server is never called."""
    from . import service
    from .providers import AIError

    waiting = list(AIJob.objects.filter(document=document, kind=AIJob.ANALYZE, status=AIJob.QUEUED,
                                        stage__in=["ocr_queued", "ocr_running"]))
    for j in waiting:
        if ok:
            _enqueue(j, document)
        else:
            first = next((ln.strip() for ln in (error or "").splitlines() if ln.strip()), "") or "Text recognition failed."
            service.finish_job(j, error=AIError(f"OCR failed: {first[:160]}", "ocr_failed"))
    return len(waiting)


@jobs.handler("ai_task")
def ai_task(job):
    from . import service
    from .providers import AIError

    ai_job = AIJob.objects.select_related("document", "requested_by").filter(pk=job.payload.get("ai_job")).first()
    if ai_job is None or ai_job.document is None:
        return {"skipped": "missing"}
    if ai_job.status in (AIJob.DONE, AIJob.FAILED, AIJob.SKIPPED):  # already finished (a duplicate or late job)
        return {"skipped": ai_job.status}
    if ai_job.status == "cancelled" or job.payload.get("epoch", 0) != ai_job.document.ocr_epoch:
        AIJob.objects.filter(pk=ai_job.pk).update(status="cancelled", finished_at=timezone.now())
        return {"skipped": "OCR data was removed after this job was queued"}
    cv = ai_job.document.current_version
    if cv is not None and cv.av_blocked:  # never let Local AI read a quarantined file
        service.finish_job(ai_job, error=AIError("The file is in antivirus quarantine."))
        return {"skipped": "quarantined"}
    running = AIJob.objects.filter(status=AIJob.RUNNING).exclude(pk=ai_job.pk).count()
    if running >= int(config.get("ai.max_parallel")):
        # waiting for a free slot is not a failed attempt
        Job.objects.filter(pk=job.pk).update(attempts=F("attempts") - 1)
        raise jobs.RetryLater("AI concurrency limit reached", delay_seconds=30)
    ai_job.status, ai_job.started_at, ai_job.attempts, ai_job.next_retry_at = AIJob.RUNNING, timezone.now(), ai_job.attempts + 1, None
    ai_job.save(update_fields=["status", "started_at", "attempts", "next_retry_at"])
    try:
        if ai_job.kind == AIJob.ANALYZE:
            user = ai_job.requested_by or ai_job.document.owner
            made = service.analyze_document(ai_job.document, user, job=ai_job)
            if made is None:  # OCR queued first; the analysis continues when recognition finishes
                AIJob.objects.filter(pk=ai_job.pk).update(status=AIJob.QUEUED, attempts=ai_job.attempts - 1)
                return {"waiting": "ocr"}
            result = {"suggestions": len(made)}
        elif ai_job.kind == AIJob.EMBED:
            result = {"chunks": service.embed_document(ai_job.document, job=ai_job)}
        else:
            result = {}
    except AIError as exc:
        if exc.transient and ai_job.attempts < AI_MAX_ATTEMPTS:
            delay = RETRY_DELAYS[min(ai_job.attempts, len(RETRY_DELAYS)) - 1]
            ai_job.refresh_from_db(fields=["stage", "detail"])
            ai_job.status, ai_job.error_category, ai_job.error = AIJob.QUEUED, exc.category, str(exc)[:300]
            ai_job.detail = {**(ai_job.detail or {}), **exc.detail()}
            ai_job.next_retry_at = timezone.now() + timedelta(seconds=delay)
            ai_job.save(update_fields=["status", "error_category", "error", "detail", "next_retry_at"])
            _enqueue(ai_job, ai_job.document, delay)
            return {"retry_in": delay, "error": exc.category}
        ai_job.refresh_from_db(fields=["stage", "detail"])
        service.finish_job(ai_job, error=exc)
        return {"error": exc.category}
    except Exception as exc:  # noqa: BLE001
        ai_job.refresh_from_db(fields=["stage", "detail"])
        service.finish_job(ai_job, error=AIError(f"Unexpected error ({exc.__class__.__name__})."))
        log.exception("ai job failed")
        return {"error": "other"}
    ai_job.refresh_from_db(fields=["stage", "detail"])
    service.finish_job(ai_job)
    return result
