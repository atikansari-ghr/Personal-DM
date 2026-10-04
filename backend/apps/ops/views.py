from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsMainAdmin
from apps.core import audit, config, jobs
from apps.core.models import Job

from . import backup, integrity


@jobs.handler("backup")
def backup_job(job):
    from apps.accounts.models import User

    actor = User.objects.filter(pk=job.payload.get("actor")).first()
    try:
        return backup.run_backup(actor=actor)
    except backup.BackupError as exc:
        raise jobs.PermanentFailure(str(exc))


@jobs.handler("integrity_check")
def integrity_job(job):
    report = integrity.check(verify_checksums=job.payload.get("checksums", True))
    from apps.notify.models import SchedulerRun

    SchedulerRun.objects.update_or_create(name="integrity_report", defaults={"state": report})
    return {"problems": report["problem_count"]}


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def backup_status(request):
    status = backup.last_backup_status()
    reach = None
    try:
        backup.check_target()
        reach = {"ok": True}
    except backup.BackupError as exc:
        reach = {"ok": False, "error": str(exc)}
    running = Job.objects.filter(kind="backup", status__in=[Job.QUEUED, Job.RUNNING]).exists()
    return Response({"status": status, "destination": reach, "running": running, "target": config.get("backup.target")})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def backup_now(request):
    try:
        backup.check_target()
    except backup.BackupError as exc:
        return Response({"error": str(exc)}, status=400)
    if Job.objects.filter(kind="backup", status__in=[Job.QUEUED, Job.RUNNING]).exists():
        return Response({"error": "A backup is already running."}, status=409)
    jobs.enqueue("backup", {"actor": str(request.user.pk)}, max_attempts=1)
    audit.record("backup.requested", request=request)
    return Response({"status": "queued"})


@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def integrity_api(request):
    from apps.notify.models import SchedulerRun

    if request.method == "POST":
        if request.data.get("repair"):
            actions = integrity.repair(dry_run=not request.data.get("confirm"))
            audit.record("integrity.repair", request=request, dry_run=not request.data.get("confirm"), actions=len(actions))
            return Response({"actions": actions, "dry_run": not request.data.get("confirm")})
        jobs.enqueue("integrity_check", {"checksums": bool(request.data.get("checksums", True))})
        return Response({"status": "queued"})
    row = SchedulerRun.objects.filter(name="integrity_report").first()
    return Response({"report": row.state if row else None})
