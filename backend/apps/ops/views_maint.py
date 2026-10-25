"""API for Settings → System → Maintenance & Operations (Change Set AB).

Permissions: the main administrator may run every operation; an Administrator (scoped) may only read Status, Doctor
results and Health; other people have no access. Upgrade, Restart, Repair (confirm) and Rollback also need a fresh
step-up (password + second factor, ``POST /api/backup/stepup``), consumed by the action. CSRF applies to every POST
(session authentication). Logs, technical details and reports are sanitised on the server before they are sent.
"""
from __future__ import annotations

from datetime import datetime, time

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsAdministrator, IsMainAdmin
from apps.core import audit

from . import diagnostics, host, maintenance as M
from .bk_views import _needs_stepup, stepup_ok
from .models import MaintenanceJob as MJ

STEPUP_OPS = ("upgrade", "restart", "rollback")


def _err(msg, status=400, **extra):
    return Response({"error": msg, **extra}, status=status)


def _job_json(job: MJ, *, full: bool = False) -> dict:
    out = {"id": str(job.id), "operation": job.operation, "operation_label": M.OP_LABELS.get(job.operation, job.operation),
           "status": job.status, "active": job.active, "requested_by": job.requested_by_label, "requested_at": job.requested_at,
           "started_at": job.started_at, "finished_at": job.finished_at, "current_step": job.current_step,
           "summary": job.summary, "exit_code": job.exit_code, "version_from": job.version_from, "version_to": job.version_to,
           "backup_ref": job.backup_ref, "recovery_state": job.recovery_state, "failure_class": job.failure_class,
           "parent": str(job.parent_id) if job.parent_id else None, "has_log": bool(job.log_name),
           "steps": job.steps}
    if full:
        out.update(details=job.details, result=job.result, verification=job.verification, params=_safe_params(job),
                   retries=[str(r) for r in job.retries.values_list("id", flat=True)],
                   recovery_guide=M.RECOVERY_GUIDE)
    return out


def _safe_params(job: MJ) -> dict:
    p = job.params or {}
    return {k: v for k, v in p.items() if k in ("ref", "items", "keys")}


@api_view(["GET"])
@permission_classes([IsAdministrator])
def overview(request):
    """Status for the page: installed version, helper, active operation, last update check, recent jobs."""
    M.sync_active()
    active = MJ.objects.filter(status__in=MJ.ACTIVE).first()
    last = M.last_update_check()
    return Response({
        "can_manage": bool(request.user.is_main_admin),
        "helper_installed": host.installed(),
        "installed": diagnostics.installed_version(),
        "active": _job_json(active) if active else None,
        "last_update_check": {"at": last.finished_at, "result": last.result, "job": str(last.id)} if last else None,
        "recent": [_job_json(j) for j in MJ.objects.select_related(None)[:10]],
        "operations": M.OP_LABELS,
        "stepup_valid": stepup_ok(request),
    })


@api_view(["GET"])
@permission_classes([IsAdministrator])
def health(request):
    return Response({"panels": diagnostics.health_panels()})


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def system_info(request):
    return Response(diagnostics.system_info())


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def caches(request):
    return Response({"caches": diagnostics.safe_caches(),
                     "never": ["documents and versions", "OCR text and provenance", "metadata", "backups and recovery points",
                               "audit logs", "AI history", "configuration", "offline data", "recovery material"]})


@api_view(["GET"])
@permission_classes([IsAdministrator])
def jobs_list(request):
    """Maintenance Job History with filters: operation, status, from/to (dates, YYYY-MM-DD)."""
    qs = MJ.objects.all()
    q = request.query_params
    if q.get("operation") in MJ.OPERATIONS:
        qs = qs.filter(operation=q["operation"])
    if q.get("status") in MJ.STATUSES:
        qs = qs.filter(status=q["status"])
    tz = timezone.get_current_timezone()
    for key, lookup, t in (("from", "requested_at__gte", time.min), ("to", "requested_at__lte", time.max)):
        if q.get(key):
            try:
                d = datetime.fromisoformat(q[key]).date()
            except ValueError:
                return _err(f"'{key}' must be a date (YYYY-MM-DD).")
            qs = qs.filter(**{lookup: datetime.combine(d, t, tzinfo=tz)})
    try:
        limit = min(200, max(1, int(q.get("limit", 50))))
    except ValueError:
        limit = 50
    rows = list(qs[:limit])
    for j in rows:
        if j.active:
            M.sync(j)
    return Response({"jobs": [_job_json(j) for j in rows], "total": qs.count()})


@api_view(["GET"])
@permission_classes([IsAdministrator])
def job_detail(request, pk):
    job = get_object_or_404(MJ, pk=pk)
    if not request.user.is_main_admin and job.operation not in ("doctor", "check_updates"):
        return _err("Only the main administrator can see this operation.", 403)
    M.sync(job)
    return Response(_job_json(job, full=True))


def _start(request, operation, params=None):
    try:
        job = M.start(operation, request.user, params=params, request=request)
    except M.MaintenanceError as exc:
        return _err(str(exc), exc.status, code=exc.code)
    return Response(_job_json(job, full=True), status=202)


def _require_confirm_and_stepup(request):
    if request.data.get("confirm") is not True:
        return _err("Confirm the operation first.", code="confirm_required")
    if not stepup_ok(request):
        return _needs_stepup()
    return None


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def run(request, operation):
    """Start an operation. Upgrade, Restart and Rollback need confirm=true and a fresh step-up."""
    if operation not in ("check_updates", "upgrade", "restart", "rollback", "clear_caches", "repair"):
        return _err("Unknown operation.", 404)
    params = {}
    if operation in STEPUP_OPS:
        bad = _require_confirm_and_stepup(request)
        if bad:
            return bad
    if operation == "upgrade" and request.data.get("ref"):
        params["ref"] = str(request.data["ref"])[:100]
    if operation == "clear_caches":
        keys = request.data.get("keys") or list(diagnostics.SAFE_CACHE_KEYS)
        if not isinstance(keys, list) or any(k not in diagnostics.SAFE_CACHE_KEYS for k in keys):
            return _err("Unknown cache.")
        if request.data.get("confirm") is not True:
            return _err("Confirm the operation first.", code="confirm_required")
        params["keys"] = keys
    resp = _start(request, operation, params)
    if operation in STEPUP_OPS and resp.status_code == 202:
        request.session.pop("recovery_stepup_at", None)  # one high-risk action per step-up
    return resp


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def job_action(request, pk, action):
    job = get_object_or_404(MJ, pk=pk)
    try:
        if action == "retry":
            if job.operation in STEPUP_OPS:
                bad = _require_confirm_and_stepup(request)
                if bad:
                    return bad
            new = M.retry(job, request.user, request=request)
            if job.operation in STEPUP_OPS:
                request.session.pop("recovery_stepup_at", None)
            return Response(_job_json(new, full=True), status=202)
        if action == "cancel":
            return Response(_job_json(M.cancel(job, request.user, request=request), full=True))
        if action == "confirm":
            if not stepup_ok(request):
                return _needs_stepup()
            items = request.data.get("items")
            if not isinstance(items, list):
                return _err("Choose the repairs to run.")
            M.confirm_repair(job, request.user, [str(i) for i in items], request=request)
            request.session.pop("recovery_stepup_at", None)
            job.refresh_from_db()
            return Response(_job_json(job, full=True), status=202)
    except M.MaintenanceError as exc:
        return _err(str(exc), exc.status, code=exc.code)
    return _err("Unknown action.", 404)


def _text_response(text: str, filename: str, download: bool) -> HttpResponse:
    resp = HttpResponse(text, content_type="text/plain; charset=utf-8")
    resp["Cache-Control"] = "no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    if download:
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def job_log(request, pk):
    job = get_object_or_404(MJ, pk=pk)
    download = request.query_params.get("download") == "1"
    audit.record("maintenance.log_viewed" if not download else "maintenance.log_downloaded", request=request,
                 target_type="maintenance_job", target_id=str(job.id))
    text = M.log_text(job) or "No log was recorded for this operation."
    return _text_response(text, f"personaldm-{job.operation}-{str(job.id)[:8]}.log", download)


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def job_report(request, pk):
    """Sanitized Support Report. ``anonymize=1`` also removes IP addresses, user and host names, document paths and
    network names (records are never changed)."""
    job = get_object_or_404(MJ, pk=pk)
    anon = request.query_params.get("anonymize") == "1"
    audit.record("maintenance.support_report", request=request, target_type="maintenance_job", target_id=str(job.id),
                 anonymized=anon)
    return _text_response(M.support_report(job, anonymized=anon),
                          f"personaldm-support-{job.operation}-{str(job.id)[:8]}{'-anonymized' if anon else ''}.txt", True)


@api_view(["GET"])
@permission_classes([IsAdministrator])
def doctor_report(request, pk):
    job = get_object_or_404(MJ, pk=pk, operation="doctor")
    anon = request.query_params.get("anonymize") == "1"
    return _text_response(diagnostics.doctor_report_text(job.result or {}, anonymized=anon),
                          f"personaldm-doctor-{str(job.id)[:8]}.txt", True)


@api_view(["POST"])
@permission_classes([IsAdministrator])
def doctor_readonly(request):
    """Run Doctor (read-only diagnostics). Scoped administrators may run it too; it changes nothing."""
    try:
        job = M.start("doctor", request.user, request=request)
    except M.MaintenanceError as exc:
        return _err(str(exc), exc.status, code=exc.code)
    return Response(_job_json(job, full=True), status=202)
