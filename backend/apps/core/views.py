"""Settings registry, audit log, jobs, health and bundled help API."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from django.conf import settings as dj
from django.db import connection
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin

from . import audit, config, jobs, registry
from .models import AuditEvent, Job
from .registry import BY_KEY, GLOBAL, SETTINGS, USER, SettingError

SECTIONS = [
    ("general", "General"), ("documents", "Documents & Folders"), ("processing", "OCR & Processing"),
    ("notifications", "Notifications"), ("connections", "Connections"), ("authentication", "Authentication"),
    ("storage", "Storage & Backup"), ("security", "Security & Access"), ("activity", "Activity & Health"), ("appearance", "Appearance"),
    ("my_notifications", "My notifications"), ("ai", "Local AI"),
]


def _setting_json(defn, user):
    if defn.scope == GLOBAL:
        value = None if defn.secret else config.get(defn.key)
        configured = config.is_set(defn.key) if defn.secret else None
    else:
        value, configured = config.get_user(user, defn.key), None
    extra = {}
    if defn.type == "widget_list":
        value = registry.normalize_widgets(value)
        extra["choice_labels"] = registry.WIDGETS
    elif defn.type == "event_list":
        extra["choice_labels"] = {k: e.label for k, e in registry.NOTIFY_EVENTS.items()}
    return {**defn.public(), **extra, "value": value, "configured": configured, "can_edit": config.can_edit(user, defn.key)}


@api_view(["GET", "PUT"])
@permission_classes([IsActiveAuthenticated])
def settings_api(request):
    user = request.user
    if request.method == "PUT":
        errors, changed = {}, []
        for key, value in (request.data.get("values") or {}).items():
            defn = BY_KEY.get(key)
            if defn is None or not config.can_edit(user, key):
                errors[key] = "You cannot change this setting."
                continue
            try:
                if defn.scope == USER:
                    config.set_user(user, key, value)
                else:
                    config.set_value(key, value, actor=user)
                changed.append(key)
            except SettingError as exc:
                errors[key] = str(exc)
        if changed:
            audit.record("settings.update", request=request, keys=changed)
            policy = [k for k in changed if k.startswith(("auth.", "security.")) or k.startswith("notifications.critical")]
            if policy:
                from apps.security import alerts

                labels = ", ".join(BY_KEY[k].label for k in policy)
                alerts.admin_event("alerts.auth_policy", "Authentication / security policy changed",
                                   f"{user.display_name} changed: {labels}.", key=f"authpolicy:{timezone.now():%Y%m%d%H%M%S%f}",
                                   link="/settings/authentication")
        if errors:
            return Response({"error": "Some settings were not saved.", "fields": errors, "saved": changed}, status=400)
    visible = [s for s in SETTINGS if s.scope == USER or user.is_main_admin or s.section in ("general",)]
    if not user.is_main_admin:
        visible = [s for s in visible if s.scope == USER or s.key in ("general.app_name", "general.timezone", "general.date_format")]
    return Response({"sections": [{"id": sid, "label": label} for sid, label in SECTIONS],
                     "settings": [_setting_json(s, user) for s in visible]})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def audit_log(request):
    qs = AuditEvent.objects.select_related("actor")
    if not request.user.is_main_admin:
        qs = qs.filter(Q(actor=request.user) | Q(subject_user=request.user))
    p = request.query_params
    if p.get("action"):
        qs = qs.filter(action__startswith=p["action"])
    if p.get("outcome"):
        qs = qs.filter(outcome=p["outcome"])
    if p.get("actor") and request.user.is_main_admin:
        qs = qs.filter(actor_id=p["actor"])
    if p.get("target"):
        qs = qs.filter(target_id=p["target"])
    try:
        offset = max(0, int(p.get("offset", 0)))
    except ValueError:
        offset = 0
    total = qs.count()
    events = [{"id": e.id, "at": e.at, "actor": e.actor.display_name if e.actor_id and e.actor else (e.actor_label or "system"),
               "action": e.action, "outcome": e.outcome, "target_type": e.target_type, "target_id": e.target_id,
               "ip": e.ip if request.user.is_main_admin else None, "context": e.context} for e in qs[offset:offset + 100]]
    return Response({"events": events, "total": total})


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def jobs_api(request):
    status = request.query_params.get("status")
    qs = Job.objects.all().order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    counts = {s: Job.objects.filter(status=s).count() for s in (Job.QUEUED, Job.RUNNING, Job.FAILED)}
    return Response({"counts": counts, "jobs": [{"id": str(j.id), "kind": j.kind, "status": j.status, "attempts": j.attempts,
                                                 "error": j.last_error[:500], "created_at": j.created_at, "finished_at": j.finished_at}
                                                for j in qs[:100]]})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def job_retry(request, pk):
    ok = jobs.retry(pk)
    audit.record("job.retry", request=request, target_type="job", target_id=str(pk))
    return Response({"retried": ok})


def _tool_ok(cmd: str) -> bool:
    return shutil.which(cmd) is not None


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Unauthenticated liveness/readiness: no sensitive details."""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        db = True
    except Exception:  # noqa: BLE001
        db = False
    return Response({"status": "ok" if db else "degraded", "database": db}, status=200 if db else 503)


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def admin_health(request):
    from apps.library import storage
    from apps.notify.models import SchedulerRun
    from apps.ops.backup import last_backup_status

    worker = SchedulerRun.objects.filter(name="worker_heartbeat").first()
    sched = SchedulerRun.objects.filter(name="scheduler_heartbeat").first()
    now = timezone.now()

    def alive(row):
        return bool(row and row.last_run_at and (now - row.last_run_at).total_seconds() < 180)

    du = shutil.disk_usage(dj.DATA_DIR if Path(dj.DATA_DIR).exists() else "/")
    return Response({
        "version": dj.APP_VERSION,
        "services": {"worker": alive(worker), "scheduler": alive(sched)},
        "tools": {"ocrmypdf": _tool_ok(dj.OCRMYPDF_CMD[0]) or len(dj.OCRMYPDF_CMD) > 1, "tesseract": _tool_ok(dj.TESSERACT_CMD),
                  "libreoffice": _tool_ok(dj.SOFFICE_CMD), "pdftoppm": _tool_ok(dj.PDFTOPPM_CMD)},
        "disk": {"total": du.total, "used": du.used, "free": du.free, "low": du.free < storage.MIN_FREE_BYTES * 4},
        "jobs": {"failed": Job.objects.filter(status=Job.FAILED).count(), "queued": Job.objects.filter(status=Job.QUEUED).count()},
        "backup": last_backup_status(),
        "public_origin": dj.PUBLIC_ORIGIN,
    })


# ------------------------------------------------------------------ help

def _guides_dir() -> Path:
    return Path(dj.DOCS_DIR) / "guides"


def _guide_meta(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), path.stem)
    audience = "admin" if "<!-- audience: admin -->" in text else "all"
    return {"slug": path.stem, "title": title, "audience": audience}


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def help_index(request):
    q = (request.query_params.get("q") or "").strip().lower()
    out = []
    for p in sorted(_guides_dir().glob("*.md")):
        meta = _guide_meta(p)
        if q:
            text = p.read_text(encoding="utf-8").lower()
            if q not in text:
                continue
            i = text.find(q)
            meta["excerpt"] = re.sub(r"\s+", " ", text[max(0, i - 80): i + 120])
        out.append(meta)
    return Response({"guides": out, "version": dj.APP_VERSION})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def help_guide(request, slug):
    if not re.fullmatch(r"[a-z0-9\-]{1,80}", slug):
        raise Http404
    path = _guides_dir() / f"{slug}.md"
    if not path.exists():
        raise Http404
    return Response({**_guide_meta(path), "markdown": path.read_text(encoding="utf-8")})
