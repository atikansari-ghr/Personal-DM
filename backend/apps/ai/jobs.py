"""AI background jobs. Bounded concurrency (ai.max_parallel) so AI never starves document processing.

The document is already stored, OCR'd and searchable before any AI job runs; AI failures only mark the
AIJob as failed and never touch the document state.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.core import config, jobs

from .models import AIJob

log = logging.getLogger("personaldocs.ai")


def queue(kind: str, *, document, user=None, delay_seconds: int = 0) -> AIJob:
    ai_job = AIJob.objects.create(kind=kind, document=document, requested_by=user)
    # The OCR epoch changes when OCR data is removed; a job queued before that must not rebuild AI data from it.
    jobs.enqueue("ai_task", {"ai_job": str(ai_job.id), "epoch": getattr(document, "ocr_epoch", 0)},
                 delay_seconds=delay_seconds, max_attempts=2, priority=150)
    return ai_job


def after_processing(document) -> None:
    """Called when baseline processing finished. Only enqueues; never raises."""
    from . import service

    try:
        if not config.get("ai.enabled") or not config.get("ai.auto_analyze"):
            return
        user = document.created_by or document.owner
        if service.enabled("ocr_assist") or service.enabled("smart_organization"):
            queue(AIJob.ANALYZE, document=document, user=user)
        if service.enabled("semantic_search"):
            queue(AIJob.EMBED, document=document, user=user)
    except Exception:  # noqa: BLE001 - AI must never affect baseline processing
        log.exception("could not queue AI jobs")


@jobs.handler("ai_task")
def ai_task(job):
    from . import service
    from .providers import AIError

    ai_job = AIJob.objects.select_related("document", "requested_by").filter(pk=job.payload.get("ai_job")).first()
    if ai_job is None or ai_job.document is None:
        return {"skipped": "missing"}
    if ai_job.status == "cancelled" or job.payload.get("epoch", 0) != ai_job.document.ocr_epoch:
        AIJob.objects.filter(pk=ai_job.pk).update(status="cancelled", finished_at=timezone.now())
        return {"skipped": "OCR data was removed after this job was queued"}
    cv = ai_job.document.current_version
    if cv is not None and cv.av_blocked:  # never let Local AI read a quarantined file
        service.finish_job(ai_job, error=AIError("The file is in antivirus quarantine."))
        return {"skipped": "quarantined"}
    running = AIJob.objects.filter(status=AIJob.RUNNING).exclude(pk=ai_job.pk).count()
    if running >= int(config.get("ai.max_parallel")):
        raise jobs.RetryLater("AI concurrency limit reached", delay_seconds=30)
    ai_job.status, ai_job.started_at, ai_job.attempts = AIJob.RUNNING, timezone.now(), ai_job.attempts + 1
    ai_job.save(update_fields=["status", "started_at", "attempts"])
    try:
        if ai_job.kind == AIJob.ANALYZE:
            user = ai_job.requested_by or ai_job.document.owner
            result = {"suggestions": len(service.analyze_document(ai_job.document, user, job=ai_job))}
        elif ai_job.kind == AIJob.EMBED:
            result = {"chunks": service.embed_document(ai_job.document, job=ai_job)}
        else:
            result = {}
    except AIError as exc:
        service.finish_job(ai_job, error=exc)
        if exc.category in ("unavailable", "timeout") and job.attempts < job.max_attempts:
            ai_job.status = AIJob.QUEUED
            ai_job.save(update_fields=["status"])
            raise jobs.RetryLater(str(exc), delay_seconds=300)
        return {"error": exc.category}
    except Exception as exc:  # noqa: BLE001
        service.finish_job(ai_job, error=AIError(f"Unexpected error ({exc.__class__.__name__})."))
        log.exception("ai job failed")
        return {"error": "other"}
    service.finish_job(ai_job)
    return result
