"""WebGUI maintenance operations (Change Set AB): Settings → System → Maintenance & Operations.

Every operation is a persistent ``MaintenanceJob`` with ordered steps, so progress, errors and logs survive a browser
refresh, sign-out, and an application or service restart.

* **Root operations** (check for updates, upgrade, restart services, repair, rollback) are fixed requests to the root
  host helper (host_helper.py → one fixed ``personaldocs`` command each). The CLI reports each step to a progress
  file; ``sync()`` folds it into the job whenever the page polls and once a minute from the scheduler. The helper is a
  separate service, so an upgrade keeps running while it restarts the web application.
* **Application operations** (Doctor, Clear Safe Caches, repair analysis and verification) run in the background
  worker as ``maintenance_task`` jobs.

Upgrade, Repair, Rollback and Restart never overlap: they share ``lock_group="system"`` and a partial unique
constraint allows one active job per group (the CLI's own flock is the second line of defence). Nothing a person
types reaches a shell: the helper accepts only validated parameters (a ref pattern, allowlisted repair items).
"""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import audit, config, jobs

from . import host, sanitize
from .host_helper import REF_RX, REPAIR_ITEMS
from .models import MaintenanceJob as MJ

ROOT_ACTIONS = {"check_updates": "app_check_updates", "upgrade": "app_upgrade", "restart": "app_restart",
                "repair": "app_repair", "rollback": "app_rollback"}
SYSTEM_OPS = ("upgrade", "repair", "rollback", "restart")
OP_LABELS = {"check_updates": "Check for Updates", "upgrade": "Update Application", "doctor": "Doctor", "repair": "Repair",
             "restart": "Restart Personal DM Services", "rollback": "Rollback", "clear_caches": "Clear Safe Caches"}

STEP_LABELS = {
    "authorize": "Authorization and step-up", "lock": "Maintenance lock", "preflight": "Preflight checks",
    "target": "Target version validation", "disk": "Disk space", "backup": "Automatic pre-upgrade backup",
    "backup_verify": "Backup verification", "fetch": "Fetch application code", "dependencies": "Install dependencies",
    "frontend": "Frontend build", "migrations": "Database migrations", "restart": "Restart services",
    "health": "Health checks", "rollback": "Automatic rollback", "release_lock": "Release lock", "report": "Report",
    "source": "Contact the update source", "compare": "Compare versions", "checks": "Run diagnostics",
    "clear": "Clear caches", "analyze": "Analyze", "plan": "Repair plan", "confirm": "Review and confirm",
    "repair_backup": "Backup before repair", "verify": "Verify", "compatibility": "Schema compatibility",
    **{f"repair_{i}": f"Repair: {i.replace('_', ' ')}" for i in REPAIR_ITEMS},
}
PLANS = {
    "upgrade": ["authorize", "lock", "preflight", "target", "disk", "backup", "backup_verify", "fetch", "dependencies",
                "frontend", "migrations", "restart", "health", "release_lock", "report"],
    "restart": ["authorize", "lock", "restart", "health", "release_lock", "report"],
    "rollback": ["authorize", "lock", "preflight", "compatibility", "restart", "health", "release_lock", "report"],
    "repair": ["analyze", "plan", "confirm"],
    "check_updates": ["source", "compare", "report"],
    "doctor": ["checks", "report"],
    "clear_caches": ["clear", "report"],
}
# the component a failed step belongs to (Technical Details)
STEP_COMPONENT = {"lock": "Maintenance lock", "preflight": "Installation", "target": "Update source", "source": "Update source",
                  "compare": "Update source", "disk": "Storage", "backup": "Backup", "backup_verify": "Backup",
                  "repair_backup": "Backup", "fetch": "Application code", "dependencies": "Python packages",
                  "frontend": "Frontend", "migrations": "Database", "compatibility": "Database", "restart": "Services",
                  "health": "Services", "rollback": "Services", "checks": "Doctor", "clear": "Caches", "verify": "Repair"}
_STATE = {"running": "running", "ok": "succeeded", "done": "succeeded", "failed": "failed", "skipped": "skipped",
          "warning": "warning"}
HELPER_START_TIMEOUT = timedelta(minutes=10)
CONFIRM_TIMEOUT = timedelta(minutes=30)
LOST_AFTER = timedelta(minutes=80)  # the helper's longest timeout (upgrade 60 min) plus margin

# Known failure conditions in a log → (failure class, detected condition, probable cause, recommended action).
# A probable cause is shown only when one of these matched (never a guess).
CONDITIONS = [
    (r"No space left on device|less than 2 GB free", "disk_full", "The disk is full or nearly full.",
     "The data disk does not have enough free space.", "Free disk space (Storage Health), then retry."),
    (r"another personaldocs operation is running", "locked", "Another maintenance operation holds the lock.",
     "An operation started in a terminal is still running.", "Wait for it to finish, then retry."),
    (r"pre-upgrade backup failed|could not be verified|snapshot could not be read back", "backup_failed",
     "The pre-upgrade backup failed or could not be verified.", "The backup destination is unreachable or full.",
     "Fix the backup destination (Settings → Backup & Recovery), then retry. The upgrade did not change anything."),
    (r"could not reach the update source|git fetch failed|Could not resolve host|could not clone", "network",
     "The update source could not be reached.", "No network connection or wrong repository credentials.",
     "Check the network and the repository token, then retry."),
    (r"revision .* not found|branch or tag .* not found|invalid target version", "target_invalid",
     "The requested version does not exist at the update source.", "", "Choose an existing branch, tag or commit."),
    (r"Python dependency installation failed|pip.*error", "dependencies", "Installing Python packages failed.",
     "", "Check the network, then retry; run Doctor."),
    (r"frontend build failed|frontend assets missing", "frontend", "The frontend could not be built.", "",
     "Retry; on low-memory hosts use a release with a prebuilt frontend."),
    (r"Migration failed|migrate.*Error|django\.db\.utils\.\w+Error", "migration_failed", "A database migration failed.",
     "", "Open the full log; the database was restored from the snapshot when possible."),
    (r"not healthy|did not become healthy|Health check failed", "health_failed",
     "The services did not pass their health checks.", "", "Run Doctor, then Repair; see the Recovery Guide."),
    (r"Permission denied", "permissions", "A file or directory permission prevented the operation.", "",
     "Run Repair (directories), then retry."),
    (r"no previous release recorded", "no_previous", "There is no previous release to roll back to.", "",
     "Restore from a recovery point instead (Recovery Guide)."),
    (r"migrations unknown to|not compatible with", "schema_incompatible",
     "The database schema is newer than the previous release.",
     "The upgrade applied database migrations the previous release does not know.",
     "A code-only rollback is not safe: restore the pre-upgrade recovery point (Recovery Guide)."),
    (r"host helper did not start|not installed", "helper_unavailable", "The root host helper did not run the request.",
     "personaldocs-host.path is not installed or not running.", "On the server run: sudo personaldocs repair"),
]
RECOVERY_GUIDE = "/help/troubleshooting#maintenance-recovery"


class MaintenanceError(Exception):
    def __init__(self, message: str, code: str = "error", status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


# ------------------------------------------------------------------ files

def jobs_dir() -> Path:
    return host.host_dir() / "jobs"


def app_log_dir() -> Path:
    return Path(settings.DATA_DIR) / "maintenance" / "logs"


def log_path(job: MJ) -> Path | None:
    name = job.log_name
    if not name or "/" in name or ".." in name:
        return None
    if job.operation in ROOT_ACTIONS:
        return host.host_dir() / "logs" / name
    return app_log_dir() / name


def append_log(job: MJ, text: str) -> None:
    """Application-side log lines (doctor, caches, analysis, verification). Sanitised before writing."""
    d = app_log_dir()
    d.mkdir(parents=True, exist_ok=True)
    if not job.log_name:
        job.log_name = f"{job.id}.app.log"
        MJ.objects.filter(pk=job.pk).update(log_name=job.log_name)
    with open(d / job.log_name, "a") as fh:
        fh.write(sanitize.redact(text.rstrip("\n")) + "\n")


def log_text(job: MJ, limit: int = 2_000_000) -> str:
    """The full log, sanitised server-side. Root jobs also include the application-side lines (verification)."""
    parts = []
    p = log_path(job)
    if p is not None:
        try:
            parts.append(p.read_text(errors="replace")[-limit:])
        except OSError:
            pass
    side = app_log_dir() / f"{job.id}.app.log"
    if job.operation in ROOT_ACTIONS and side.exists():
        parts.append(side.read_text(errors="replace")[-limit:])
    return sanitize.redact("\n".join(parts))


# ------------------------------------------------------------------ job creation

def _now_iso() -> str:
    return timezone.now().isoformat()


def _plan_steps(operation: str) -> list[dict]:
    return [{"key": k, "label": STEP_LABELS.get(k, k), "status": "pending", "started_at": None, "finished_at": None,
             "detail": ""} for k in PLANS[operation]]


def _set_step(job: MJ, key: str, status: str, detail: str = "") -> None:
    now = _now_iso()
    for s in job.steps:
        if s["key"] == key:
            break
    else:
        s = {"key": key, "label": STEP_LABELS.get(key, key.replace("_", " ").capitalize()), "status": "pending",
             "started_at": None, "finished_at": None, "detail": ""}
        # insert new steps (repair items, rollback) before the trailing bookkeeping steps
        tail = next((i for i, x in enumerate(job.steps) if x["key"] in ("release_lock", "report", "verify") and x["status"] == "pending"),
                    len(job.steps))
        job.steps.insert(tail, s)
    if status == "pending":
        pass
    elif status == "running":
        s["started_at"] = s["started_at"] or now
        job.current_step = key
    else:
        s["started_at"] = s["started_at"] or now
        s["finished_at"] = now
        if job.current_step == key:
            job.current_step = ""
    s["status"] = status
    if detail:
        s["detail"] = sanitize.redact(detail)[:500]


def create(operation: str, user, *, params: dict | None = None, parent: MJ | None = None, request=None) -> MJ:
    if operation not in MJ.OPERATIONS:
        raise MaintenanceError("Unknown maintenance operation.")
    job = MJ(operation=operation, requested_by=user, requested_by_label=(user.display_name if user else "system")[:80],
             params=params or {}, parent=parent, steps=_plan_steps(operation),
             lock_group="system" if operation in SYSTEM_OPS else None)
    if operation in ("upgrade", "restart", "rollback"):
        _set_step(job, "authorize", "succeeded", "Main administrator, confirmed with step-up")
    try:
        with transaction.atomic():
            job.save()
    except IntegrityError:
        active = MJ.objects.filter(lock_group="system", status__in=MJ.ACTIVE).first()
        raise MaintenanceError(
            f"{OP_LABELS.get(active.operation, 'Another operation') if active else 'Another operation'} is already running. "
            "Upgrade, Repair, Rollback and Restart never run at the same time.", "locked", 409)
    audit.record(f"maintenance.{operation}_requested", request=request, actor=user, target_type="maintenance_job",
                 target_id=str(job.id), **({"retry_of": str(parent.id)} if parent else {}))
    return job


def request_helper(job: MJ, params: dict | None = None) -> None:
    """Queue the fixed root request for a job. The queue file survives a helper that is busy with another request."""
    action = ROOT_ACTIONS[job.operation]
    if not host.installed():
        _finish(job, MJ.FAILED, "The root host helper is not installed, so this operation cannot run from the web interface.",
                failure_class="helper_unavailable",
                details={"condition": "The root host helper (personaldocs-host.path) is not installed.",
                         "recommended": "On the server run: sudo personaldocs repair — or run the command in a terminal: "
                                        f"sudo personaldocs {_cli_equivalent(job)}"})
        raise MaintenanceError("The host helper is not installed. On the server run: sudo personaldocs repair",
                               "helper_unavailable", 409)
    req = {"id": secrets.token_hex(8), "action": action, "job": str(job.id), "params": params or {},
           "requested_at": datetime.now(dt_tz.utc).isoformat(), "requested_by": job.requested_by_label}
    d = host.host_dir()
    (d / "queue").mkdir(parents=True, exist_ok=True)
    tmp = d / "queue" / f".{job.id}.tmp"
    tmp.write_text(json.dumps(req))
    os.replace(tmp, d / "queue" / f"{job.requested_at:%Y%m%d%H%M%S}-{job.id}.json")
    tmp = d / ".request.tmp"
    tmp.write_text(json.dumps(req))
    os.replace(tmp, d / "request.json")  # wakes personaldocs-host.path
    MJ.objects.filter(pk=job.pk).update(helper_request=req["id"])
    job.helper_request = req["id"]


def _cli_equivalent(job: MJ) -> str:
    p = job.params or {}
    return {"check_updates": "check-updates", "upgrade": "upgrade" + (f" --ref {p['ref']}" if p.get("ref") else ""),
            "restart": "restart", "rollback": "rollback",
            "repair": "repair --only " + ",".join(p.get("items") or [])}.get(job.operation, job.operation)


def start(operation: str, user, *, params: dict | None = None, parent: MJ | None = None, request=None) -> MJ:
    """Create and start one operation (the repair entry point is ``start("repair")`` = Analyze)."""
    params = dict(params or {})
    if operation == "upgrade" and params.get("ref"):
        ref = str(params["ref"]).strip()
        if not REF_RX.match(ref) or ".." in ref:
            raise MaintenanceError("The target version must be a branch, tag or commit name (letters, digits, . _ - /).")
        params["ref"] = ref
    if operation in ROOT_ACTIONS and operation != "repair" and not host.installed():
        raise MaintenanceError("The host helper is not installed. On the server run: sudo personaldocs repair",
                               "helper_unavailable", 409)
    job = create(operation, user, params=params, parent=parent, request=request)
    if operation in ROOT_ACTIONS and operation != "repair":
        request_helper(job, {"ref": params["ref"]} if params.get("ref") else {})
    else:
        jobs.enqueue("maintenance_task", {"job": str(job.id), "phase": "analyze" if operation == "repair" else "run"},
                     priority=10, max_attempts=1)
    return job


def retry(job: MJ, user, request=None) -> MJ:
    if job.active:
        raise MaintenanceError("This operation is still running.", "active", 409)
    params = dict(job.params or {})
    return start(job.operation, user, params=params, parent=job, request=request)


def cancel(job: MJ, user, request=None) -> MJ:
    """Only a job that has not started work can be cancelled (queued, or waiting for repair confirmation)."""
    if job.status == MJ.CONFIRM or (job.status == MJ.QUEUED and not _helper_status(job)):
        _finish(job, MJ.CANCELLED, "Cancelled before any change was made.", notify_=False)
        _remove_queue_file(job)
        audit.record("maintenance.cancelled", request=request, actor=user, target_type="maintenance_job", target_id=str(job.id))
        return job
    raise MaintenanceError("This operation has already started and cannot be cancelled safely.", "running", 409)


def _remove_queue_file(job: MJ) -> None:
    q = host.host_dir() / "queue"
    for f in (q.glob(f"*-{job.id}.json") if q.is_dir() else []):
        f.unlink(missing_ok=True)


# ------------------------------------------------------------------ worker (application operations)

@jobs.handler("maintenance_task")
def maintenance_task(task) -> dict:
    job = MJ.objects.filter(pk=task.payload.get("job")).first()
    if job is None or job.status not in MJ.ACTIVE:
        return {"skipped": True}
    phase = task.payload.get("phase", "run")
    try:
        if job.operation == "doctor":
            _run_doctor(job)
        elif job.operation == "clear_caches":
            _run_clear_caches(job)
        elif job.operation == "repair" and phase == "analyze":
            _repair_analyze(job)
        elif job.operation == "repair" and phase == "execute":
            _repair_execute(job)
        elif job.operation == "repair" and phase == "verify":
            _repair_verify(job)
    except Exception as exc:  # noqa: BLE001 - every failure ends in a visible job state
        job.refresh_from_db()
        if job.current_step:
            _set_step(job, job.current_step, "failed", f"{exc.__class__.__name__}: {exc}")
        append_log(job, f"[{_now_iso()}] ERROR {exc.__class__.__name__}: {exc}")
        _finish(job, MJ.FAILED, f"{OP_LABELS[job.operation]} failed: {exc.__class__.__name__}.",
                details={"error": sanitize.redact(f"{exc.__class__.__name__}: {exc}")[:1000]}, failure_class="internal")
    return {"job": str(job.id)}


def _mark_running(job: MJ, step: str) -> None:
    job.status, job.started_at = MJ.RUNNING, job.started_at or timezone.now()
    _set_step(job, step, "running")
    job.save(update_fields=["status", "started_at", "steps", "current_step"])


def _run_doctor(job: MJ) -> None:
    from . import diagnostics

    _mark_running(job, "checks")
    append_log(job, f"[{_now_iso()}] Doctor started by {job.requested_by_label}")
    res = diagnostics.run_doctor()
    append_log(job, diagnostics.doctor_report_text(res))
    c = res["counts"]
    _set_step(job, "checks", "warning" if c["FAIL"] or c["WARNING"] else "succeeded",
              f"{c['PASS']} passed, {c['WARNING']} warnings, {c['FAIL']} failed")
    job.result = res
    status = MJ.SUCCEEDED if res["overall"] == "PASS" else MJ.WARNINGS
    summary = (f"Doctor: {c['FAIL']} failed, {c['WARNING']} warning(s), {c['PASS']} passed." if c["FAIL"] or c["WARNING"]
               else f"Doctor: all {c['PASS']} checks passed.")
    _finish(job, status, summary)
    if res["critical"]:
        _notify_admins("maintenance.doctor_critical", job, f"Doctor found {len(res['critical'])} critical problem(s)",
                       "; ".join(f"{r['component']}: {r['check']}" for r in res["critical"][:3]), severity="critical")


def _run_clear_caches(job: MJ) -> None:
    from . import diagnostics

    _mark_running(job, "clear")
    keys = [k for k in (job.params or {}).get("keys") or diagnostics.SAFE_CACHE_KEYS if k in diagnostics.SAFE_CACHE_KEYS]
    out = diagnostics.clear_safe_caches(keys)
    for r in out:
        append_log(job, f"cleared {r['key']}: {r['removed_items']} item(s)" + (f", {r['removed_bytes']} bytes" if r["removed_bytes"] else ""))
    _set_step(job, "clear", "succeeded", ", ".join(f"{r['key']} ({r['removed_items']})" for r in out))
    job.result = {"cleared": out}
    _finish(job, MJ.SUCCEEDED, f"Cleared {len(out)} safe cache(s). No documents, metadata, backups or logs were touched.")


# ------------------------------------------------------------------ repair: analyze → plan → confirm → backup → repair → verify

REPAIR_RULES = [
    # (item, doctor check regex, statuses, problem, proposed repair, affects, restart, backup, risk)
    ("migrations", r"^migrations applied", ("FAIL",), "Database migrations are pending.", "Apply the pending migrations.",
     ["PostgreSQL database schema"], False, True, "medium"),
    ("directories", r"^directory ", ("FAIL",), "An application directory is missing or not writable.",
     "Create the data directories and restore their ownership and permissions.", ["/var/lib/personaldocs"], False, False, "low"),
    ("packages", r"^tool ", ("FAIL",), "A required system tool is missing.", "Install the required Debian packages.",
     ["Debian packages"], False, False, "low"),
    ("ocr_languages", r"^OCR language packs installed", ("FAIL",), "OCR language packs are missing.",
     "Install the Tesseract language packs for the offered OCR languages.", ["Debian packages (tesseract-ocr-*)"], False, False, "low"),
    ("services", r"^service personaldocs-|^worker running|^scheduler running", ("FAIL",),
     "A Personal DM service is not running.", "Enable and restart the Personal DM services.",
     ["personaldocs-web", "personaldocs-worker", "personaldocs-scheduler"], True, False, "low"),
    ("antivirus", r"^ClamAV scanner operational|^ClamAV self-test", ("FAIL",), "The ClamAV scanner does not work.",
     "Repair the ClamAV daemon, its socket and signatures (fixed steps with a scan self-test).",
     ["clamav-daemon", "clamav-freshclam"], False, False, "low"),
]


def _stale_jobs() -> int:
    from apps.core.models import Job

    return Job.objects.filter(status=Job.RUNNING, locked_until__lt=timezone.now()).exclude(kind="maintenance_task").count()


def _repair_analyze(job: MJ) -> None:
    from . import diagnostics

    _mark_running(job, "analyze")
    res = diagnostics.run_doctor()
    findings = [r for c in res["components"] for r in c["results"] if r["status"] in ("FAIL", "WARNING")]
    plan, matched = [], set()
    for item, rx, states, problem, proposed, affects, restart, backup, risk in REPAIR_RULES:
        hits = [f for f in findings if f["status"] in states and re.search(rx, f["check"])]
        if hits:
            matched.update(id(h) for h in hits)
            plan.append({"item": item, "problem": problem, "proposed": proposed, "affects": affects, "restart": restart,
                         "backup": backup, "risk": risk, "evidence": [f"{h['check']}: {h['detail']}"[:200] for h in hits[:4]]})
    stale = _stale_jobs()
    if stale:
        plan.append({"item": "jobs", "problem": f"{stale} background job(s) are stuck in Running after a crash.",
                     "proposed": "Queue them again (their work is idempotent).", "affects": ["Background job queue"],
                     "restart": False, "backup": False, "risk": "low", "evidence": [f"{stale} job(s) with an expired lease"]})
    manual = [{"check": f["check"], "component": f["component"], "status": f["status"], "detail": f["detail"],
               "recommended": f["recommended"] or "See the Troubleshooting Guide."}
              for f in findings if id(f) not in matched][:40]
    _set_step(job, "analyze", "succeeded", f"{len(findings)} finding(s) checked")
    _set_step(job, "plan", "succeeded", f"{len(plan)} automatic repair(s) proposed" if plan else "nothing to repair automatically")
    job.result = {"plan": plan, "manual": manual, "doctor": {"overall": res["overall"], "counts": res["counts"]},
                  "helper_installed": host.installed()}
    append_log(job, f"[{_now_iso()}] Repair analysis: {len(plan)} automatic, {len(manual)} manual item(s)")
    if not plan:
        _set_step(job, "confirm", "skipped", "nothing to confirm")
        _finish(job, MJ.SUCCEEDED, "No automatic repair is needed." + (f" {len(manual)} finding(s) need manual attention." if manual else ""))
        return
    job.status = MJ.CONFIRM
    _set_step(job, "confirm", "running", "Review the repair plan and confirm")
    job.summary = f"Repair plan ready: {len(plan)} repair(s) to review."
    job.save(update_fields=["status", "steps", "current_step", "result", "summary"])


def confirm_repair(job: MJ, user, items: list[str], request=None) -> MJ:
    if job.operation != "repair" or job.status != MJ.CONFIRM:
        raise MaintenanceError("This repair is not waiting for confirmation.", "state", 409)
    planned = {p["item"] for p in (job.result or {}).get("plan", [])}
    items = [i for i in dict.fromkeys(items or []) if i in planned and i in REPAIR_ITEMS]
    if not items:
        raise MaintenanceError("Select at least one repair from the plan.")
    if not host.installed():
        raise MaintenanceError("The host helper is not installed, so repairs cannot run from the web interface. "
                               "On the server run: sudo personaldocs repair", "helper_unavailable", 409)
    job.params = {**(job.params or {}), "items": items}
    _set_step(job, "confirm", "succeeded", f"confirmed by {user.display_name}: {', '.join(items)}")
    job.status = MJ.RUNNING
    job.save(update_fields=["params", "steps", "current_step", "status"])
    audit.record("maintenance.repair_confirmed", request=request, actor=user, target_type="maintenance_job",
                 target_id=str(job.id), items=items)
    jobs.enqueue("maintenance_task", {"job": str(job.id), "phase": "execute"}, priority=10, max_attempts=1)
    return job


def _repair_execute(job: MJ) -> None:
    from . import bk_engine

    items = (job.params or {}).get("items") or []
    plan = {p["item"]: p for p in (job.result or {}).get("plan", [])}
    if any(plan.get(i, {}).get("backup") for i in items):
        _set_step(job, "repair_backup", "running")
        job.save(update_fields=["steps", "current_step"])
        res = bk_engine.pre_change_backup(f"Before repair ({', '.join(items)})", actor=job.requested_by)
        if not res["ok"]:
            _set_step(job, "repair_backup", "failed", res["detail"])
            _finish(job, MJ.FAILED, "The backup before the repair failed, so the repair was not started.",
                    details={"error": res["detail"], "condition": "The pre-repair backup failed or could not be verified.",
                             "recommended": "Fix the backup destination (Settings → Backup & Recovery), then retry."},
                    failure_class="backup_failed")
            return
        job.backup_ref = res.get("point") or ""
        _set_step(job, "repair_backup", "succeeded", res["detail"])
    for i in items:
        _set_step(job, f"repair_{i}", "pending")
    _set_step(job, "health", "pending")
    _set_step(job, "verify", "pending")
    job.save(update_fields=["steps", "backup_ref", "current_step"])
    request_helper(job, {"items": items})


def _repair_verify(job: MJ) -> None:
    from . import diagnostics

    _set_step(job, "verify", "running")
    job.save(update_fields=["steps", "current_step"])
    res = diagnostics.run_doctor()
    items = (job.params or {}).get("items") or []
    still = []
    for item, rx, states, *_ in REPAIR_RULES:
        if item in items:
            still += [f"{r['check']}: {r['detail']}" for c in res["components"] for r in c["results"]
                      if r["status"] in states and re.search(rx, r["check"])]
    if "jobs" in items and _stale_jobs():
        still.append("background jobs still stuck")
    job.verification = {"checked_at": _now_iso(), "remaining": still[:20], "doctor": res["counts"]}
    append_log(job, f"[{_now_iso()}] Verification: {len(still)} problem(s) remain")
    if still:
        _set_step(job, "verify", "failed", f"{len(still)} problem(s) remain")
        _finish(job, MJ.PARTIAL, f"Repair partly succeeded: {len(still)} problem(s) remain.",
                details={"error": "; ".join(still)[:1000], "condition": "Some checks still fail after the repair.",
                         "recommended": "Open Technical Details and the Troubleshooting Guide."}, failure_class="verify_failed")
    else:
        _set_step(job, "verify", "succeeded", "the repaired checks pass")
        _finish(job, MJ.SUCCEEDED, f"Repair complete and verified ({', '.join(items)}).")


# ------------------------------------------------------------------ sync from the root helper

def _helper_status(job: MJ) -> dict:
    try:
        return json.loads((jobs_dir() / f"{job.id}.json").read_text())
    except (OSError, ValueError):
        return {}


def _progress(job: MJ) -> list[dict]:
    try:
        lines = (jobs_dir() / f"{job.id}.progress").read_text(errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def sync(job: MJ) -> MJ:
    """Fold the helper's status and progress into the job. Idempotent; safe from any process at any time."""
    if not job.active:
        return job
    now = timezone.now()
    if job.status == MJ.CONFIRM:
        if now - (job.started_at or job.requested_at) > CONFIRM_TIMEOUT:
            _finish(job, MJ.CANCELLED, "The repair plan was not confirmed within 30 minutes; nothing was changed.", notify_=False)
        return job
    if job.operation not in ROOT_ACTIONS or not job.helper_request:
        if job.status == MJ.QUEUED and now - job.requested_at > HELPER_START_TIMEOUT and not _worker_alive():
            _finish(job, MJ.FAILED, "The background worker did not start the operation.", failure_class="worker_unavailable",
                    details={"condition": "The background worker is not running.",
                             "recommended": "Restart Personal DM Services, or on the server: sudo systemctl restart personaldocs-worker"})
        return job
    st = _helper_status(job)
    meta: dict = {}
    changed = False
    for ev in _progress(job):
        if ev.get("t") == "step" and ev.get("key"):
            key = str(ev["key"])[:40]
            state = _STATE.get(ev.get("value"), "running")
            cur = next((s for s in job.steps if s["key"] == key), None)
            if cur is None or cur["status"] != state or (ev.get("msg") and cur.get("detail") != ev.get("msg")):
                _set_step(job, key, state, ev.get("msg") or "")
                changed = True
        elif ev.get("t") == "meta" and ev.get("key"):
            meta[str(ev["key"])] = sanitize.redact(str(ev.get("value", "")))[:500]
    if meta.get("version_from") and job.version_from != meta["version_from"]:
        job.version_from, changed = meta["version_from"][:80], True
    if meta.get("version_to") and job.version_to != meta["version_to"]:
        job.version_to, changed = meta["version_to"][:80], True
    if meta.get("backup_ref") and job.backup_ref != meta["backup_ref"]:
        job.backup_ref, changed = meta["backup_ref"][:200], True
    if st.get("log") and job.log_name != st["log"]:
        job.log_name, changed = str(st["log"])[:80], True
    state = st.get("state")
    if state == "running" and job.status != MJ.RUNNING:
        job.status = MJ.RUNNING
        job.started_at = _parse(st.get("started_at")) or now
        changed = True
    if changed:
        job.save()
    if state in ("done", "failed"):
        _finalize_root(job, st, meta)
    elif not state and now - job.requested_at > HELPER_START_TIMEOUT:
        _finish(job, MJ.FAILED, "The host helper did not start the operation.", failure_class="helper_unavailable",
                details={"condition": "The host helper did not start the operation within 10 minutes.",
                         "probable_cause": "personaldocs-host.path is not running.",
                         "recommended": "On the server run: sudo systemctl status personaldocs-host.path, then sudo personaldocs repair"})
    elif state == "running" and now - (job.started_at or job.requested_at) > LOST_AFTER:
        _finish(job, MJ.RECOVERY if job.operation in ("upgrade", "rollback") else MJ.FAILED,
                "The operation stopped reporting progress (the host may have restarted during it).",
                failure_class="lost", details={"condition": "No result from the host helper after 80 minutes.",
                                               "recommended": "Run Doctor; open the full log and the Recovery Guide."})
    return job


def _parse(v):
    try:
        return datetime.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def _worker_alive() -> bool:
    from apps.notify.models import SchedulerRun

    hb = SchedulerRun.objects.filter(name="worker_heartbeat").first()
    return bool(hb and hb.last_run_at and timezone.now() - hb.last_run_at < timedelta(minutes=5))


def sync_active() -> int:
    n = 0
    for job in MJ.objects.filter(status__in=MJ.ACTIVE):
        sync(job)
        n += 1
    return n


def _analyze_failure(job: MJ, error: str, last: str) -> dict:
    """Technical Details for a failed root operation: failed step, component, exit code, the exact sanitised error,
    log context, and a detected condition / probable cause only when a known pattern matched."""
    failed = next((s for s in reversed(job.steps) if s["status"] == "failed"), None)
    text = log_text(job, limit=400_000)
    lines = text.splitlines()
    idx = max((i for i, ln in enumerate(lines) if "ERROR" in ln or "Failed at line" in ln), default=len(lines) - 1)
    context = lines[max(0, idx - 15): idx + 5] if lines else []
    out = {"failed_step": failed["key"] if failed else "", "failed_step_label": failed["label"] if failed else "",
           "component": STEP_COMPONENT.get(failed["key"], "Maintenance") if failed else "Maintenance",
           "timestamp": (failed or {}).get("finished_at") or _now_iso(), "exit_code": job.exit_code,
           "error": sanitize.redact(error or last or "The command failed without an error message.")[:2000],
           "log_context": [sanitize.redact(x)[:400] for x in context], "condition": "", "probable_cause": "",
           "recommended": "Open the full log; run Doctor; see the Troubleshooting Guide.", "recovery_guide": RECOVERY_GUIDE}
    # the exact error decides first; the surrounding log only when the error itself matches nothing known
    for hay in (error or "", last or "", "\n".join(context)):
        hit = next((c for c in CONDITIONS if hay and re.search(c[0], hay, re.I)), None)
        if hit:
            _, cls, condition, cause, action = hit
            out.update(condition=condition, probable_cause=cause, recommended=action, failure_class=cls)
            break
    return out


def _finalize_root(job: MJ, st: dict, meta: dict) -> None:
    job.exit_code = st.get("exit_code")
    ok = st.get("state") == "done" and job.exit_code == 0
    outcome = meta.get("outcome", "")
    for s in job.steps:  # a step left running when the process ended did not finish
        if s["status"] == "running":
            s["status"], s["finished_at"] = ("succeeded" if ok else "failed"), _now_iso()
    _set_step(job, "release_lock", "succeeded", "released when the command ended")
    if job.verification == {} and meta.get("verification"):
        job.verification = {"result": meta["verification"], "checked_at": _now_iso()}
    op = job.operation
    if ok:
        if op == "check_updates":
            job.result = st.get("result") or {}
            r = job.result
            state = r.get("state")
            summary = {"current": "Personal DM is up to date.",
                       "available": f"An update is available: {r.get('available_version')} ({r.get('behind')} change(s)).",
                       "no_source": "No update source is configured (installed from a local copy).",
                       }.get(state, f"Update check finished ({state}).")
            _finish(job, MJ.WARNINGS if r.get("warnings") or state in ("diverged", "unknown_installed", "no_source") else MJ.SUCCEEDED, summary)
        elif op == "upgrade":
            if outcome == "current":
                _finish(job, MJ.SUCCEEDED, f"Already at {job.version_from or 'the latest version'}; nothing to install.")
            else:
                warn = any(s["status"] == "warning" for s in job.steps)
                job.recovery_state = ""
                _finish(job, MJ.WARNINGS if warn else MJ.SUCCEEDED,
                        f"Upgraded {job.version_from} → {job.version_to}; health checks passed.")
                _notify_admins("maintenance.upgrade_completed", job, "Upgrade completed",
                               f"{job.version_from} → {job.version_to}", severity="success")
        elif op == "repair":
            job.status = MJ.RUNNING
            job.save()
            jobs.enqueue("maintenance_task", {"job": str(job.id), "phase": "verify"}, priority=10, max_attempts=1)
        elif op == "rollback":
            job.recovery_state = "rolled_back"
            _finish(job, MJ.SUCCEEDED, f"Rolled back {job.version_from} → {job.version_to}; health checks passed (verified).")
            _notify_admins("maintenance.rollback", job, "Rollback completed and verified", f"{job.version_from} → {job.version_to}",
                           severity="success")
        else:
            _finish(job, MJ.SUCCEEDED, "Personal DM services restarted; health checks passed.")
        return
    details = _analyze_failure(job, meta.get("error", ""), st.get("last_line", "") or st.get("error", ""))
    cls = details.pop("failure_class", "") or ("lost" if job.exit_code in (124,) else "command_failed")
    details["previous_version"], details["attempted_version"] = job.version_from, job.version_to
    details["backup_ref"] = job.backup_ref
    if op == "upgrade":
        if outcome == "rolled_back":
            job.recovery_state = "rolled_back"
            details.update(rollback_required=False, health="previous version verified healthy after the automatic rollback")
            _finish(job, MJ.ROLLED_BACK, f"Upgrade Failed — Rolled Back to {job.version_from} (verified healthy).",
                    details=details, failure_class=cls)
            _notify_admins("maintenance.rollback", job, "Upgrade failed — rolled back (verified)", details["error"][:200], severity="warning")
        elif outcome == "remains_operational":
            job.recovery_state = "remains_operational"
            details.update(rollback_required=False, health="the existing version was not changed" if not job.verification
                           else job.verification.get("result", ""))
            _finish(job, MJ.FAILED, "Upgrade Failed — Existing Version Remains Operational.", details=details, failure_class=cls)
            _notify_admins("maintenance.upgrade_failed", job, "Upgrade failed — existing version remains operational",
                           f"Failed step: {details['failed_step_label']}. {details['error'][:160]}", severity="warning")
        else:
            job.recovery_state = "recovery_required"
            details.update(rollback_required=True, health="not verified healthy",
                           recommended="Follow the Recovery Guide: restore the pre-upgrade backup " + (f"({job.backup_ref}) " if job.backup_ref else "")
                           + "or run a rollback only if the schema is compatible.")
            _finish(job, MJ.RECOVERY, "Upgrade Failed — Recovery Required.", details=details, failure_class=cls)
            _notify_admins("maintenance.recovery_required", job, "Upgrade failed — recovery required",
                           f"Failed step: {details['failed_step_label']}.", severity="critical")
    elif op == "rollback":
        if outcome == "recovery_required":
            job.recovery_state = "recovery_required"
            _finish(job, MJ.RECOVERY, "Rollback Failed — Recovery Required.", details=details, failure_class=cls)
            _notify_admins("maintenance.recovery_required", job, "Rollback failed — recovery required", details["error"][:200], severity="critical")
        else:
            job.recovery_state = "remains_operational"
            _finish(job, MJ.FAILED, "Rollback not performed — the current version remains active.", details=details, failure_class=cls)
            _notify_admins("maintenance.rollback", job, "Rollback not performed", details["error"][:200], severity="warning")
    elif op == "repair":
        _finish(job, MJ.FAILED, f"Repair failed at {details['failed_step_label'] or 'a step'}.", details=details, failure_class=cls)
        _notify_admins("maintenance.repair_failed", job, "Repair failed", details["error"][:200], severity="warning")
    elif op == "restart":
        _finish(job, MJ.FAILED, "Restart finished, but the services did not pass their health checks." if details["failed_step"] == "health"
                else "Restart failed.", details=details, failure_class=cls)
    else:
        _finish(job, MJ.FAILED, f"{OP_LABELS[op]} failed.", details=details, failure_class=cls)


def _finish(job: MJ, status: str, summary: str, *, details: dict | None = None, failure_class: str = "",
            notify_: bool = True) -> None:
    job.status, job.summary = status, sanitize.redact(summary)[:300]
    job.finished_at = timezone.now()
    job.current_step = ""
    if details is not None:
        job.details = sanitize.redact_obj({**(job.details or {}), **details})
    if failure_class:
        job.failure_class = failure_class[:40]
    for s in job.steps:
        if s["key"] == "report" and s["status"] == "pending":
            s.update(status="succeeded", started_at=_now_iso(), finished_at=_now_iso())
        elif s["status"] == "pending" and status not in (MJ.SUCCEEDED, MJ.WARNINGS):
            s["status"] = "not_run"
    job.save()
    audit.record(f"maintenance.{job.operation}_finished", actor=job.requested_by, target_type="maintenance_job",
                 target_id=str(job.id), outcome="success" if status in (MJ.SUCCEEDED, MJ.WARNINGS) else "failure",
                 status=status, failure_class=job.failure_class)


def _notify_admins(event: str, job: MJ, title: str, summary: str, *, severity: str = "info") -> None:
    from apps.accounts.models import User
    from apps.notify import events

    link = f"/settings/system/maintenance?job={job.id}"
    for admin in User.objects.filter(is_main_admin=True, is_active=True):
        events.notify(admin, event, key=f"maintenance:{job.id}:{event}", title=title, summary=sanitize.redact(summary)[:300],
                      facts=[("Operation", OP_LABELS.get(job.operation, job.operation)),
                             *((("Version", f"{job.version_from} → {job.version_to}"),) if job.version_to else ())],
                      link=link, severity=severity)


# ------------------------------------------------------------------ retention and reports

def purge() -> dict:
    """Nightly: maintenance logs older than maintenance.log_retention_days, history after maintenance.history_days.
    Separate from the audit-log retention; active jobs are never touched."""
    now = timezone.now()
    log_cut = now - timedelta(days=int(config.get("maintenance.log_retention_days")))
    hist_cut = now - timedelta(days=int(config.get("maintenance.history_days")))
    logs = 0
    for job in MJ.objects.filter(finished_at__lt=log_cut).exclude(log_name=""):
        for p in (log_path(job), app_log_dir() / f"{job.id}.app.log", jobs_dir() / f"{job.id}.progress"):
            if p is not None and p.exists():
                try:
                    p.unlink()
                    logs += 1
                except OSError:
                    pass
        MJ.objects.filter(pk=job.pk).update(log_name="")
    old = MJ.objects.filter(finished_at__lt=hist_cut).exclude(status__in=MJ.ACTIVE)
    for job in old:
        (jobs_dir() / f"{job.id}.json").unlink(missing_ok=True)
    rows, _ = old.delete()
    return {"logs": logs, "jobs": rows}


def support_report(job: MJ, *, anonymized: bool) -> str:
    """Sanitized Support Report: job summary, steps, technical details, system information and the log. Always
    redacted; with ``anonymized`` also without IP addresses, user/host names, document paths and network names."""
    from . import diagnostics

    try:
        info = diagnostics.system_info()
    except Exception as exc:  # noqa: BLE001
        info = {"error": exc.__class__.__name__}
    lines = [f"Personal DM support report — generated {_now_iso()}",
             f"Operation: {OP_LABELS.get(job.operation, job.operation)}  Job: {job.id}",
             f"Status: {job.status}  Requested: {job.requested_at:%Y-%m-%d %H:%M} UTC by {job.requested_by_label}",
             f"Summary: {job.summary}", f"Versions: {job.version_from or '—'} → {job.version_to or '—'}",
             f"Recovery state: {job.recovery_state or '—'}  Exit code: {job.exit_code}", "", "== Steps"]
    lines += [f"[{s['status']}] {s['label']}" + (f" - {s['detail']}" if s.get("detail") else "") for s in job.steps]
    lines += ["", "== Technical details", json.dumps(job.details or {}, indent=1, default=str), "",
              "== System information", json.dumps(info, indent=1, default=str), "", "== Log", log_text(job)]
    text = "\n".join(lines)
    return sanitize.anonymize(text) if anonymized else sanitize.redact(text)


def last_update_check() -> MJ | None:
    return MJ.objects.filter(operation="check_updates", status__in=(MJ.SUCCEEDED, MJ.WARNINGS)).first()
