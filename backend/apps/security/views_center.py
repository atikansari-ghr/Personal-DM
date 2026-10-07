"""Security center API for Administrators: health score, Internet Ready, security test, OS updates, reboot,
firewall (read only), security records and Storage Health."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsAdministrator
from apps.core import audit
from apps.ops import host

from . import center
from .models import HealthState, OsUpdateRun, SecurityTestRun


def _err(msg, status=400, **extra):
    return Response({"error": msg, **extra}, status=status)


def _run_json(r: SecurityTestRun, full: bool = False) -> dict:
    out = {"id": r.id, "status": r.status, "started_at": r.started_at, "finished_at": r.finished_at, "deployment": r.deployment,
           "started_by": r.started_by.display_name if r.started_by_id else None, "summary": r.summary}
    if full:
        out["findings"] = r.findings
    return out


@api_view(["GET"])
@permission_classes([IsAdministrator])
def health(request):
    return Response(center.security_health())


@api_view(["GET", "POST"])
@permission_classes([IsAdministrator])
def https(request):
    """GET the last result; POST re-checks the public HTTPS address now."""
    if request.method == "POST":
        audit.record("security.https_check", request=request)
        return Response(center.https_checks())
    return Response(center.https_state())


@api_view(["GET", "POST"])
@permission_classes([IsAdministrator])
def tests(request):
    if request.method == "POST":
        try:
            run = center.start_security_test(request.user)
        except ValueError as exc:
            return _err(str(exc), 409)
        return Response(_run_json(run), status=202)
    runs = SecurityTestRun.objects.select_related("started_by")[:50]
    latest = runs[0] if runs else None
    return Response({"runs": [_run_json(r) for r in runs], "latest": _run_json(latest, full=True) if latest else None,
                     "note": "A baseline of this application and its host. It does not prove the absence of vulnerabilities "
                             "and never scans other devices on your network."})


@api_view(["GET"])
@permission_classes([IsAdministrator])
def test_detail(request, pk):
    return Response(_run_json(get_object_or_404(SecurityTestRun, pk=pk), full=True))


def _os_json(r: OsUpdateRun) -> dict:
    return {"id": r.id, "action": r.action, "status": r.status, "requested_at": r.requested_at, "finished_at": r.finished_at,
            "requested_by": r.requested_by.display_name if r.requested_by_id else None, "backup_status": r.backup_status,
            "backup_detail": r.backup_detail, "backup_override": r.backup_override, "override_reason": r.override_reason,
            "packages": r.packages, "reboot_required": r.reboot_required, "error": r.error, "has_log": bool(r.log_name)}


@api_view(["GET"])
@permission_classes([IsAdministrator])
def os_updates(request):
    center.sync_os_runs()
    check = host.status("check_updates")
    return Response({
        "helper_installed": host.installed(), "pending": check.get("pending") or [], "checked_at": check.get("finished_at"),
        "check_state": check.get("state"), "reboot_required": host.reboot_required(),
        "reboot_packages": host.status("inspect").get("reboot_packages") or [],
        "runs": [_os_json(r) for r in OsUpdateRun.objects.select_related("requested_by")[:30]],
        "post_reboot": HealthState.get("post_reboot"),
        "unattended": "Automatic OS updates are not enabled by Personal DM. Updates are installed only when an administrator "
                      "chooses Install security updates.",
        "manual_commands": ["sudo apt-get update", "sudo apt-get upgrade", "sudo reboot"],
    })


def _host_action(request, action: str, **fields) -> OsUpdateRun | Response:
    try:
        req = host.request(action, actor=request.user, request_obj=request)
    except host.HostError as exc:
        return _err(str(exc), 409, manual_commands=["sudo apt-get update", "sudo apt-get upgrade", "sudo reboot"])
    return OsUpdateRun.objects.create(action=action, request_id=req["id"], requested_by=request.user, **fields)


@api_view(["POST"])
@permission_classes([IsAdministrator])
def os_check(request):
    run = _host_action(request, "check_updates")
    return run if isinstance(run, Response) else Response(_os_json(run), status=202)


@api_view(["POST"])
@permission_classes([IsAdministrator])
def os_install(request):
    """Install pending security updates. A database/settings backup is attempted first; if it fails the update stops
    unless the administrator explicitly overrides it (with a reason, audited)."""
    d = request.data
    if d.get("confirm") is not True:
        return _err("Confirm that you want to install the security updates.", code="confirm_required")
    if not host.installed():
        return _err("The host helper is not installed. On the server run: sudo personaldocs repair", 409)
    backup = center.pre_update_backup(request.user)
    override = False
    reason = str(d.get("override_reason") or "").strip()
    if not backup["ok"]:
        if d.get("override_backup") is not True:
            audit.record("security.os_updates_blocked", request=request, outcome="failure", reason="backup_failed")
            return _err("The backup before updating failed, so the update was not started.", 409, code="backup_failed",
                        detail=backup["detail"])
        if len(reason) < 10:
            return _err("Give a reason of at least 10 characters for updating without a backup.", code="reason_required")
        override = True
        audit.record("security.update_backup_override", request=request, reason_length=len(reason), detail=backup["detail"][:200])
    run = _host_action(request, "install_updates", backup_status="ok" if backup["ok"] else "failed",
                       backup_detail=backup["detail"][:300], backup_override=override, override_reason=reason[:300])
    if isinstance(run, Response):
        return run
    audit.record("security.os_updates_started", request=request, target_type="os_update", target_id=str(run.id),
                 backup=run.backup_status, override=override)
    return Response(_os_json(run), status=202)


@api_view(["GET"])
@permission_classes([IsAdministrator])
def os_log(request, pk):
    run = get_object_or_404(OsUpdateRun, pk=pk)
    st = host.status(run.action)
    name = run.log_name or (st.get("log") if st.get("id") == run.request_id else "")
    return Response({"log": host.log_text(name or "")})


@api_view(["GET", "POST"])
@permission_classes([IsAdministrator])
def reboot(request):
    """GET: what a reboot would interrupt. POST {confirm: true}: drain services and reboot (once)."""
    if request.method == "GET":
        return Response({**center.reboot_preflight(), "helper_installed": host.installed(),
                         "reboot_required": host.reboot_required()})
    if request.data.get("confirm") is not True:
        return _err("Confirm the reboot.", code="confirm_required")
    if OsUpdateRun.objects.filter(action="reboot", status__in=("requested", "running", "rebooting")).exists() or host.running("reboot"):
        return _err("A reboot is already in progress.", 409)
    run = _host_action(request, "reboot")
    if isinstance(run, Response):
        return run
    audit.record("security.reboot_requested", request=request, target_type="os_update", target_id=str(run.id))
    from apps.notify import events

    for admin in events._admins():
        events.notify(admin, "security.operations", kind="security.operations", key=f"reboot:{run.id}",
                      title="Server reboot requested", lines=[f"Requested by {request.user.display_name}."], link="/settings/security?view=updates")
    return Response(_os_json(run), status=202)


@api_view(["GET", "POST"])
@permission_classes([IsAdministrator])
def firewall(request):
    """Read-only firewall and exposure status. POST refreshes the inspection; nothing can change firewall rules."""
    if request.method == "POST":
        try:
            host.request("inspect", actor=request.user, request_obj=request)
        except host.HostError as exc:
            return _err(str(exc), 409)
    insp = host.status("inspect")
    return Response({"helper_installed": host.installed(), "state": insp.get("state"), "checked_at": insp.get("finished_at"),
                     "firewall": insp.get("firewall"), "listening": insp.get("listening") or [],
                     "unexpected": insp.get("unexpected") or [], "exposed_local_only": insp.get("exposed_local_only") or [],
                     "expected_ports": {"22": "SSH", "8000": "Personal Documents (web, behind the reverse proxy)"},
                     "note": "Personal DM only reports the firewall status; it never opens, closes or changes rules. Manage "
                             "the firewall on the host (for example with ufw) or in Proxmox."})


@api_view(["GET", "POST"])
@permission_classes([IsAdministrator])
def security_records(request):
    """GET ?categories=a,b&older_than_days=N → cleanup analysis. POST {categories, older_than_days, confirm} → purge."""
    src = request.data if request.method == "POST" else request.query_params
    cats = src.get("categories") or list(center.PURGE_CATEGORIES)
    if isinstance(cats, str):
        cats = [c for c in cats.split(",") if c]
    if any(c not in center.PURGE_CATEGORIES for c in cats) or not cats:
        return _err("Choose one or more record categories.")
    try:
        days = int(src.get("older_than_days") or 365)
    except (TypeError, ValueError):
        return _err("Enter a number of days.")
    if days < 30:
        return _err("Records younger than 30 days cannot be purged.")
    if request.method == "GET":
        return Response({**center.purge_preview(cats, days), "available": center.PURGE_CATEGORIES})
    if request.data.get("confirm") is not True:
        return _err("Review the cleanup analysis and confirm.", code="confirm_required")
    return Response(center.purge(cats, days, actor=request.user, request=request))


@api_view(["GET", "POST"])
@permission_classes([IsAdministrator])
def storage(request):
    """GET: usage, categories and cleanup analysis. POST {kinds, confirm}: safe cleanup only."""
    if request.method == "POST":
        kinds = [k for k in (request.data.get("kinds") or []) if k in center.CLEANUP_KINDS]
        if not kinds:
            return _err("Choose what to clean up.")
        if request.data.get("confirm") is not True:
            return _err("Review the analysis and confirm.", code="confirm_required")
        return Response({"freed": center.cleanup(kinds, actor=request.user, request=request)})
    return Response({**center.storage_health(refresh=request.query_params.get("refresh") == "1"),
                     "cleanup": center.cleanup_analysis()})
