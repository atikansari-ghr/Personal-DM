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


def active_analysis(document, kind: str = AIJob.ANALYZE) -> AIJob | None:
    return AIJob.objects.filter(document=document, kind=kind, status__in=[AIJob.QUEUED, AIJob.RUNNING]).first()


def queue(kind: str, *, document, user=None, delay_seconds: int = 0, requested: bool = False, trigger: str = "",
          options: dict | None = None) -> AIJob:
    """``requested``: a person asked for it (an AI Action, Retry). Only then may the analysis start OCR itself;
    automatic analysis after an upload never runs OCR on a document whose type is set to manual OCR. ``trigger``:
    manual, auto (OCR + AI) or smart (Smart Auto, with the matching conditions in ``options``)."""
    trigger = trigger or ("manual" if requested else "auto")
    if kind in AIJob.ACTIONS:  # one job per action and document at a time: pressing it again never stacks up jobs
        existing = active_analysis(document, kind)
        if existing is not None:
            if requested and not (existing.detail or {}).get("requested"):  # a person now asked for it: OCR may run
                existing.detail = {**(existing.detail or {}), "requested": True, **(options or {})}
                AIJob.objects.filter(pk=existing.pk).update(detail=existing.detail, trigger="manual")
            return existing
    detail = {**({"requested": True} if requested else {}), **(options or {})}
    ai_job = AIJob.objects.create(kind=kind, document=document, requested_by=user, stage="queued", trigger=trigger,
                                  detail=detail)
    _enqueue(ai_job, document, delay_seconds)
    return ai_job


def smart_reasons(document) -> list[str]:
    """Smart Auto: which configured conditions apply to this document now (empty = AI is not invoked)."""
    from apps.library.models import DocumentField

    on = set(config.get("ai.smart_triggers") or [])
    doc = document
    cv = doc.current_version
    out = []
    if "low_confidence" in on and cv is not None and cv.ocr_applied:
        conf = (cv.ocr_quality or {}).get("confidence")
        if isinstance(conf, (int, float)) and conf < int(config.get("ai.smart_confidence")):
            out.append("low_confidence")
    if "missing_metadata" in on and (doc.issue_date is None or doc.correspondent_id is None):
        out.append("missing_metadata")
    if "unknown_type" in on and not doc.doc_type_id:
        out.append("unknown_type")
    if "missing_expiry" in on and doc.doc_type_id and doc.doc_type.has_expiry and not doc.expiry_date and not doc.no_expiry:
        out.append("missing_expiry")
    if "conflicting_fields" in on and any(f.proposed_value and f.value and f.proposed_value != f.value
                                          for f in DocumentField.objects.filter(document=doc)):
        out.append("conflicting_fields")
    if "needs_review" in on and doc.ocr_state == "needs_review":
        out.append("needs_review")
    if "selected_types" in on and doc.doc_type_id:
        names = {n.strip().lower() for n in (config.get("ai.smart_types") or "").split(",") if n.strip()}
        if doc.doc_type.name.lower() in names:
            out.append("selected_types")
    return out


def after_processing(document, *, skip_analyze: bool = False) -> None:
    """Called when baseline processing (or an OCR run) finished. Only enqueues; never raises."""
    from . import service

    try:
        mode = service.mode()
        if not service.enabled() or mode in ("on_demand", "ocr_only"):
            return  # AI on Demand: only an explicit action by an authorized person invokes AI
        user = document.created_by or document.owner
        if not skip_analyze and (service.enabled("ocr_assist") or service.enabled("smart_organization")):
            if mode == "auto":
                queue(AIJob.ANALYZE, document=document, user=user, trigger="auto")
            else:
                reasons = smart_reasons(document)
                if reasons:
                    queue(AIJob.ANALYZE, document=document, user=user, trigger="smart", options={"smart": reasons})
        if mode == "auto" and service.enabled("semantic_search"):
            queue(AIJob.EMBED, document=document, user=user, trigger="auto")
    except Exception:  # noqa: BLE001 - AI must never affect baseline processing
        log.exception("could not queue AI jobs")


def ocr_started(document) -> None:
    """OCR picked up a document an analysis is waiting for: show it as running."""
    AIJob.objects.filter(document=document, kind__in=AIJob.ACTIONS, status=AIJob.QUEUED, stage="ocr_queued").update(stage="ocr_running")


def resume_after_ocr(document, *, ok: bool, error: str = "") -> int:
    """Change Set Y: OCR that an analysis waited for has finished. On success the analysis continues with the new text
    (no polling); on failure it fails at the OCR stage and the AI server is never called."""
    from . import service
    from .providers import AIError

    waiting = list(AIJob.objects.filter(document=document, kind__in=AIJob.ACTIONS, status=AIJob.QUEUED,
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
    if ai_job.status == AIJob.CANCELLED or job.payload.get("epoch", 0) != ai_job.document.ocr_epoch:
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
        if ai_job.kind in AIJob.ACTIONS and ai_job.kind != AIJob.ASK:
            user = ai_job.requested_by or ai_job.document.owner
            made = service.run_action(ai_job.kind, ai_job.document, user, job=ai_job)
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
