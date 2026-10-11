"""Backup & Recovery API (Change Set T).

Administration (policies, destinations, recovery points, key, emergency package, downloads, deletions) is for the
main administrator only. High-impact actions additionally need **step-up authentication**: the password plus the
authenticator code or a passkey when the account has one (``POST /api/backup/stepup``), valid for 5 minutes.
The Recovery Explorer and My Recovery are available to everyone, filtered by current permissions.
"""
from __future__ import annotations

import json
import re
import tarfile
import time
from datetime import timedelta

from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin
from apps.core import audit, jobs, ratelimit

from . import bk_crypto as C
from . import bk_destinations as D
from . import bk_engine as E
from . import bk_keys, bk_restore, schedule
from .models import (BackupDestination, BackupPolicy, EmergencyExport, KeyRotation, RecoveryCopy, RecoveryKey, RecoveryPoint,
                     RestoreRun)

STEPUP_MINUTES = 5


def _err(msg, status=400, **extra):
    return Response({"error": msg, **extra}, status=status)


# ------------------------------------------------------------------ step-up authentication

def stepup_ok(request) -> bool:
    at = request.session.get("recovery_stepup_at")
    if not at:
        return False
    try:
        from datetime import datetime

        return timezone.now() - datetime.fromisoformat(at) < timedelta(minutes=STEPUP_MINUTES)
    except ValueError:
        return False


def _needs_stepup():
    return _err("Confirm it is you: enter your password and your authenticator code or passkey.", 403, code="stepup_required")


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def stepup_options(request):
    """Passkey challenge for step-up (when the main administrator has passkeys)."""
    from apps.accounts import passkeys

    try:
        return Response(passkeys.authentication_options(request.session, user=request.user, purpose="stepup"))
    except passkeys.PasskeyError as exc:
        return _err(str(exc))


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def stepup(request):
    from apps.accounts import passkeys
    from apps.accounts import services as S

    user = request.user
    bucket = f"stepup:{user.pk}"
    if ratelimit.too_many(bucket, 5, 900):
        return _err("Too many attempts. Wait a few minutes.", 429)
    if not user.has_usable_password() or not user.check_password(request.data.get("password") or ""):
        ratelimit.hit(bucket)
        audit.record("recovery.stepup", request=request, outcome="failure", reason="password")
        return _err("Verification failed.")
    has_passkeys = passkeys.active(user).exists()
    second = None
    if user.totp_enabled or has_passkeys:
        if request.data.get("credential") and has_passkeys:
            try:
                passkeys.authenticate(request.session, request.data["credential"], purpose="stepup", user=user)
                second = "passkey"
            except passkeys.PasskeyError as exc:
                ratelimit.hit(bucket)
                return _err(str(exc))
        elif request.data.get("code") and user.totp_enabled:
            second = S.verify_second_factor(user, request.data.get("code", ""))
        if not second:
            ratelimit.hit(bucket)
            audit.record("recovery.stepup", request=request, outcome="failure", reason="second_factor")
            return _err("Enter the code from your authenticator app or use your passkey.", 400,
                        code="second_factor_required", totp=user.totp_enabled, passkey=has_passkeys)
    request.session["recovery_stepup_at"] = timezone.now().isoformat()
    audit.record("recovery.stepup", request=request, method=f"password+{second}" if second else "password")
    return Response({"status": "ok", "valid_minutes": STEPUP_MINUTES, "second_factor": second})


# ------------------------------------------------------------------ overview, policies, destinations

def dest_json(d: BackupDestination) -> dict:
    secret_keys = []
    try:
        secret_keys = sorted(D.secrets_of(d).keys())
    except D.DestError:
        pass
    return {"id": d.id, "name": d.name, "kind": d.kind, "kind_label": D.LABELS.get(d.kind, d.kind), "config": d.config,
            "secrets_set": secret_keys, "enabled": d.enabled, "health": d.health, "health_detail": d.health_detail,
            "free_bytes": d.free_bytes, "total_bytes": d.total_bytes, "checked_at": d.checked_at.isoformat() if d.checked_at else None}


def policy_json(p: BackupPolicy) -> dict:
    spec = {"time": p.full_time, "frequency": p.full_frequency, "weekday": p.full_weekday, "month_day": p.full_month_day}
    from apps.notify.expiry import local_now

    nxt = schedule.next_occurrence(local_now(), {**spec, "enabled": p.enabled})
    return {"id": p.id, "name": p.name, "enabled": p.enabled, "full_frequency": p.full_frequency, "full_weekday": p.full_weekday,
            "full_month_day": p.full_month_day, "full_time": p.full_time, "incremental_hours": p.incremental_hours,
            "retention_weeks": p.retention_weeks, "destinations": list(p.destinations.values_list("id", flat=True)),
            "verify_deep": p.verify_deep, "notify_success": p.notify_success, "validation_days": p.validation_days,
            "describe": schedule.describe_spec(spec) + (f" · incremental every {p.incremental_hours} h" if p.incremental_hours else " · no incrementals"),
            "next_full": nxt.isoformat() if nxt else None,
            "last_full_at": p.last_full_at.isoformat() if p.last_full_at else None,
            "last_incremental_at": p.last_incremental_at.isoformat() if p.last_incremental_at else None}


def point_admin_json(p: RecoveryPoint) -> dict:
    return {**bk_restore.point_json(p), "reason": p.reason, "error": p.error, "finished_at": p.finished_at.isoformat() if p.finished_at else None,
            "policy": p.policy.name if p.policy_id else None,
            "copies": [{"destination": c.destination.name, "destination_id": c.destination_id, "state": c.state,
                        "label": RecoveryCopy.LABELS.get(c.state, c.state), "detail": c.detail, "generation": c.generation,
                        "verified_at": c.verified_at.isoformat() if c.verified_at else None, "bytes": c.bytes}
                       for c in p.copies.select_related("destination")],
            "verification": {k: v for k, v in (p.verification or {}).items() if k != "build_warnings"},
            "warnings": (p.verification or {}).get("build_warnings", []),
            "dependents": RecoveryPoint.objects.filter(base=p, deleted_at__isnull=True).count() if p.kind == "full" else 0}


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def overview(request):
    rot = KeyRotation.objects.first()
    key = bk_keys.active()
    return Response({
        "health": E.health(),
        "policies": [policy_json(p) for p in BackupPolicy.objects.all()],
        "destinations": [dest_json(d) for d in BackupDestination.objects.all()],
        "points": [point_admin_json(p) for p in RecoveryPoint.objects.filter(deleted_at__isnull=True).select_related("policy")[:100]],
        "legacy": E.legacy_backups(),
        "key": {"generation": key.generation, "fingerprint": key.fingerprint, "created_at": key.created_at.isoformat()} if key else None,
        "retiring": list(RecoveryKey.objects.filter(state=RecoveryKey.RETIRING).values_list("generation", flat=True)),
        "rotation": {"id": rot.id, "status": rot.status, "from": rot.from_generation, "to": rot.to_generation,
                     "started_at": rot.started_at.isoformat(), "finished_at": rot.finished_at.isoformat() if rot.finished_at else None,
                     "results": rot.results[:200]} if rot else None,
        "running": jobs_running(),
        "kinds": [{"kind": k, "label": D.LABELS[k], "config": D.CONFIG_FIELDS[k], "secrets": D.SECRET_FIELDS[k]} for k in D.PROVIDERS],
        "stepup_valid": stepup_ok(request),
        "restores": [restore_json(r) for r in RestoreRun.objects.filter(kind__in=["full", "test", "validation"])[:20]],
    })


def jobs_running() -> list[str]:
    from apps.core.models import Job

    return list(Job.objects.filter(kind__in=["backup_point", "backup_verify", "backup_test_restore", "key_rotation"],
                                   status__in=[Job.QUEUED, Job.RUNNING]).values_list("kind", flat=True))


def _clean_policy(data, p: BackupPolicy | None = None) -> dict:
    out = {}
    if "name" in data:
        name = str(data["name"]).strip()[:80]
        if not name:
            raise ValueError("Give the policy a name.")
        out["name"] = name
    if "full_frequency" in data:
        if data["full_frequency"] not in ("daily", "weekly", "monthly"):
            raise ValueError("Full backup frequency must be daily, weekly or monthly.")
        out["full_frequency"] = data["full_frequency"]
    if "full_weekday" in data:
        if data["full_weekday"] not in schedule.WEEKDAYS:
            raise ValueError("Choose a day of the week.")
        out["full_weekday"] = data["full_weekday"]
    if "full_time" in data:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(data["full_time"])):
            raise ValueError("Enter the time as HH:MM (24-hour).")
        out["full_time"] = data["full_time"]
    for k, lo, hi, msg in (("full_month_day", 1, 31, "Day of the month must be 1–31."),
                           ("incremental_hours", 0, 168, "Incremental interval must be 0 (off) to 168 hours."),
                           ("retention_weeks", 1, 520, "Keep Full backups for 1 to 520 weeks."),
                           ("validation_days", 0, 365, "Validation interval must be 0 (off) to 365 days.")):
        if k in data:
            try:
                v = int(data[k])
            except (TypeError, ValueError):
                raise ValueError(msg) from None
            if not lo <= v <= hi:
                raise ValueError(msg)
            out[k] = v
    for k in ("enabled", "verify_deep", "notify_success"):
        if k in data:
            out[k] = bool(data[k])
    return out


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def policies(request):
    try:
        values = _clean_policy(request.data)
    except ValueError as exc:
        return _err(str(exc))
    if "name" not in values:
        return _err("Give the policy a name.")
    if BackupPolicy.objects.filter(name=values["name"]).exists():
        return _err("A policy with this name exists.")
    p = BackupPolicy.objects.create(**values)
    p.destinations.set(BackupDestination.objects.filter(pk__in=request.data.get("destinations") or []))
    _config_changed(request, f"Policy “{p.name}” created")
    return Response(policy_json(p), status=201)


@api_view(["PUT", "DELETE"])
@permission_classes([IsMainAdmin])
def policy_detail(request, pk):
    p = BackupPolicy.objects.filter(pk=pk).first()
    if p is None:
        return _err("Not found.", 404)
    if request.method == "DELETE":
        if not stepup_ok(request):
            return _needs_stepup()
        name = p.name
        p.delete()  # recovery points stay (policy set to empty); they still follow retention via their chain
        _config_changed(request, f"Policy “{name}” removed")
        return Response(status=204)
    try:
        values = _clean_policy(request.data, p)
    except ValueError as exc:
        return _err(str(exc))
    for k, v in values.items():
        setattr(p, k, v)
    p.save()
    if "destinations" in request.data:
        p.destinations.set(BackupDestination.objects.filter(pk__in=request.data.get("destinations") or []))
    _config_changed(request, f"Policy “{p.name}” changed")
    return Response(policy_json(p))


def _config_changed(request, what: str):
    audit.record("backup.config", request=request, change=what)
    from apps.notify import events

    events.backup_event("backup.config_changed", detail=what, actor=request.user, tag=str(time.time()))


def _clean_dest(data, d: BackupDestination | None = None) -> tuple[dict, dict | None]:
    kind = data.get("kind", d.kind if d else "")
    if kind not in D.PROVIDERS:
        raise ValueError("Choose a destination type.")
    values = {"kind": kind}
    if "name" in data:
        values["name"] = str(data["name"]).strip()[:80]
        if not values["name"]:
            raise ValueError("Give the destination a name.")
    cfg = dict(d.config if d else {})
    for f in D.CONFIG_FIELDS[kind]:
        if f in (data.get("config") or {}):
            v = data["config"][f]
            cfg[f] = bool(v) if f == "require_mount" else str(v).strip()[:500]
    if kind in ("local", "nas"):
        path = cfg.get("path", "")
        if not path.startswith("/") or ".." in path.split("/"):
            raise ValueError("Enter an absolute folder path such as /mnt/pdnas/personaldocs.")
        from django.conf import settings as dj

        if path.rstrip("/") in (str(dj.DATA_DIR), str(dj.STORAGE_DIR), "/"):
            raise ValueError("Backups must not be written into the application's own data folder.")
    if kind == "s3" and not str(cfg.get("endpoint", "")).startswith("https://"):
        raise ValueError("Use an https:// S3 endpoint.")
    values["config"] = cfg
    if "enabled" in data:
        values["enabled"] = bool(data["enabled"])
    secrets = None
    if data.get("secrets"):
        secrets = {k: str(v) for k, v in data["secrets"].items() if k in D.SECRET_FIELDS[kind] and v not in (None, "")}
    return values, secrets


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def destinations(request):
    try:
        values, secrets = _clean_dest(request.data)
    except ValueError as exc:
        return _err(str(exc))
    if "name" not in values or BackupDestination.objects.filter(name=values["name"]).exists():
        return _err("Give the destination a unique name.")
    d = BackupDestination(**values)
    if secrets:
        D.set_secrets(d, secrets)
    d.save()
    if not BackupPolicy.objects.exists():  # first destination: the recommended policy (weekly Full + incremental every 4 h)
        p = BackupPolicy.objects.create(name="Default")
        p.destinations.add(d)
    _config_changed(request, f"Destination “{d.name}” ({D.LABELS[d.kind]}) added")
    return Response(dest_json(d), status=201)


@api_view(["PUT", "DELETE"])
@permission_classes([IsMainAdmin])
def destination_detail(request, pk):
    d = BackupDestination.objects.filter(pk=pk).first()
    if d is None:
        return _err("Not found.", 404)
    if request.method == "DELETE":
        if not stepup_ok(request):
            return _needs_stepup()
        if d.copies.exclude(state=RecoveryCopy.DELETED).filter(point__deleted_at__isnull=True).exists() and not request.data.get("confirm"):
            return _err("This destination holds recovery points. Removing it from Personal DM keeps the files on the "
                        "destination but they are no longer tracked or retained.", 409, code="has_copies")
        name = d.name
        d.delete()
        _config_changed(request, f"Destination “{name}” removed")
        return Response(status=204)
    try:
        values, secrets = _clean_dest(request.data, d)
    except ValueError as exc:
        return _err(str(exc))
    for k, v in values.items():
        setattr(d, k, v)
    if secrets:
        merged = {**D.secrets_of(d), **secrets}
        D.set_secrets(d, merged)
    d.save()
    _config_changed(request, f"Destination “{d.name}” changed")
    return Response(dest_json(d))


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def destination_test(request, pk):
    d = BackupDestination.objects.filter(pk=pk).first()
    if d is None:
        return _err("Not found.", 404)
    try:
        res = D.provider(d).test()
        E._set_health(d, "healthy", res.get("detail", ""), res.get("free"), res.get("total"))
        return Response({"ok": True, **res})
    except D.DestError as exc:
        E._set_health(d, {"auth_required": "auth_required", "insufficient_storage": "insufficient_storage"}.get(exc.code, "unavailable"), str(exc))
        return Response({"ok": False, "code": exc.code, "detail": str(exc)})


# ------------------------------------------------------------------ jobs

@jobs.handler("backup_point", heavy=True)
def backup_point_job(job):
    from apps.accounts.models import User

    pol = BackupPolicy.objects.filter(pk=job.payload.get("policy")).first()
    actor = User.objects.filter(pk=job.payload.get("actor")).first()
    try:
        p = E.create_point(pol, kind=job.payload.get("kind", "full"), trigger=job.payload.get("trigger", "scheduled"), actor=actor)
        return {"point": str(p.id), "status": p.status}
    except E.BackupError as exc:
        raise jobs.PermanentFailure(str(exc))


@jobs.handler("backup_verify", heavy=True)
def backup_verify_job(job):
    p = RecoveryPoint.objects.get(pk=job.payload["point"])
    E.verify_point(p)
    return {"status": p.status}


@jobs.handler("backup_test_restore", heavy=True)
def backup_test_restore_job(job):
    from apps.accounts.models import User

    from .bk_validation import test_restore

    p = RecoveryPoint.objects.get(pk=job.payload["point"])
    run = test_restore(p, actor=User.objects.filter(pk=job.payload.get("actor")).first())
    return {"status": run.status}


@jobs.handler("backup_retry")
def backup_retry_job(job):
    return {"retried": E.retry_pending(), "retired": bk_keys.retire_unused()}


@jobs.handler("recovery_validation", heavy=True)
def recovery_validation_job(job):
    from .bk_validation import automated_validation

    run = automated_validation()
    return {"status": run.status if run else "not_configured"}


@jobs.handler("key_rotation", heavy=True)
def key_rotation_job(job):
    from apps.accounts.models import User

    from . import bk_rotate

    actor = User.objects.filter(pk=job.payload.get("actor")).first()
    rot = bk_rotate.retry(actor) if job.payload.get("retry") else bk_rotate.rotate(actor)
    return {"status": rot.status if rot else "none"}


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def run_now(request):
    pol = BackupPolicy.objects.filter(pk=request.data.get("policy")).first() or E.default_policy()
    if pol is None or not pol.destinations.filter(enabled=True).exists():
        return _err("Add a destination first.")
    kind = request.data.get("kind", "full")
    if kind not in ("full", "incremental"):
        return _err("Choose Full or Incremental.")
    if jobs_running():
        return _err("A backup task is already running.", 409)
    jobs.enqueue("backup_point", {"policy": pol.id, "kind": kind, "trigger": "manual", "actor": str(request.user.pk)}, max_attempts=1)
    audit.record("backup.requested", request=request, backup_kind=kind, policy=pol.name)
    return Response({"status": "queued"})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def point_action(request, pk, action):
    p = RecoveryPoint.objects.filter(pk=pk, deleted_at__isnull=True).first()
    if p is None:
        return _err("Not found.", 404)
    if action == "verify":
        jobs.enqueue("backup_verify", {"point": str(p.id)}, max_attempts=1)
    elif action == "test-restore":
        jobs.enqueue("backup_test_restore", {"point": str(p.id), "actor": str(request.user.pk)}, max_attempts=1)
    else:
        return _err("Unknown action.", 404)
    audit.record(f"backup.{action}", request=request, target_type="recovery_point", target_id=str(p.id))
    return Response({"status": "queued"})


# ------------------------------------------------------------------ protected deletion and download

def _coverage(p: RecoveryPoint, removing: list[RecoveryPoint]) -> dict:
    remaining = RecoveryPoint.objects.filter(deleted_at__isnull=True).exclude(pk__in=[x.pk for x in removing]) \
        .filter(status__in=[RecoveryPoint.VERIFIED, RecoveryPoint.PARTIAL])
    oldest = remaining.order_by("created_at").first()
    newest = remaining.order_by("-created_at").first()
    return {"remaining_points": remaining.count(), "oldest_remaining": oldest.created_at.isoformat() if oldest else None,
            "newest_remaining": newest.created_at.isoformat() if newest else None,
            "warning": "No verified recovery point would remain." if not remaining.exists() else
            ("Restores to dates between these points will no longer be possible." if removing else "")}


@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def point_delete(request, pk):
    p = RecoveryPoint.objects.filter(pk=pk, deleted_at__isnull=True).first()
    if p is None:
        return _err("Not found.", 404)
    deps = E.dependents(p)
    preview = {"point": point_admin_json(p), "dependents": [bk_restore.point_json(x) for x in deps],
               "coverage": _coverage(p, [p, *deps]),
               "note": "This is a protected deletion, not immutable storage: deleted copies cannot be recovered by Personal DM."}
    if request.method == "GET":
        return Response(preview)
    if deps and not request.data.get("include_dependents"):
        return _err(f"{len(deps)} later recovery point(s) depend on this one. Delete them together, or keep this point.", 409,
                    code="dependents", **preview)
    if not stepup_ok(request):
        return _needs_stepup()
    res = E.delete_points([p, *deps], actor=request.user, reason="manual", request=request)
    from apps.notify import events

    events.backup_event("backup.deleted", point=p, actor=request.user,
                        detail=f"{len(res['deleted'])} recovery point(s) deleted"
                        + (f"; {len(res['pending'])} pending on unreachable destinations" if res["pending"] else "") + ".",
                        tag="manual")
    return Response(res)


def _tar_header(name: str, size: int) -> bytes:
    ti = tarfile.TarInfo(name)
    ti.size, ti.mtime, ti.mode = size, int(time.time()), 0o600
    return ti.tobuf(format=tarfile.PAX_FORMAT)


def _pad(n: int) -> bytes:
    return b"\0" * ((512 - n % 512) % 512)


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def point_download(request, pk):
    """Stream the complete encrypted recoverable set (base Full + incrementals up to this point) from one
    destination as an uncompressed tar. Only ciphertext ever leaves the server."""
    p = RecoveryPoint.objects.filter(pk=pk, deleted_at__isnull=True).first()
    if p is None:
        return _err("Not found.", 404)
    if not stepup_ok(request):
        return _needs_stepup()
    from .bk_validation import chain_copies

    chain = p.chain()
    dest_id = request.query_params.get("destination")
    candidates = [int(dest_id)] if dest_id and dest_id.isdigit() else list(p.copies.filter(state__in=[RecoveryCopy.STORED_VERIFIED, RecoveryCopy.STORED_WARNING]).values_list("destination_id", flat=True))
    copies = None
    for did in candidates:
        cc = chain_copies(p, did)
        if all(str(x.id) in cc for x in chain):
            copies = cc
            break
    if copies is None:
        return _err("No destination holds a complete verified chain for this recovery point.", 409)
    readme = (f"Personal Documents Management System - encrypted recovery package\n"
              f"Recovery point: {p.id} ({p.kind}, {p.created_at:%Y-%m-%d %H:%M} UTC)\n"
              f"Contains {len(chain)} point(s): " + " -> ".join(f"{x.kind}:{str(x.id)[:8]}" for x in chain) + "\n"
              f"Key generation: {p.key_generation}. Every file is encrypted; the Backup Recovery Key (or the Emergency "
              f"Recovery Package and its passphrase) is needed to restore.\n"
              "Restore on a clean Debian 13 server: sudo personaldocs recover --source local:/path/to/extracted/folder\n").encode()

    def stream():
        yield _tar_header("README.txt", len(readme)) + readme + _pad(len(readme))
        for x in chain:
            c = copies[str(x.id)]
            prov = D.provider(c.destination)
            with prov.open(E.rel(x.id, c.generation, "header.json")) as fh:
                head = fh.read()
            hdr = json.loads(head)
            yield _tar_header(E.rel(x.id, c.generation, "header.json"), len(head)) + head + _pad(len(head))
            for name, meta in sorted(hdr["files"].items()):
                yield _tar_header(E.rel(x.id, c.generation, name), meta["cipher_size"])
                sent = 0
                with prov.open(E.rel(x.id, c.generation, name)) as fh:
                    for b in D.iter_stream(fh):
                        sent += len(b)
                        yield b
                if sent != meta["cipher_size"]:
                    raise RuntimeError("Destination returned a different size; download aborted.")
                yield _pad(sent)
        yield b"\0" * 1024

    audit.record("backup.download", request=request, target_type="recovery_point", target_id=str(p.id), points=len(chain))
    from apps.notify import events

    events.backup_event("backup.downloaded", point=p, actor=request.user,
                        detail=f"Encrypted package with {len(chain)} recovery point(s) downloaded.", tag=str(time.time()))
    resp = StreamingHttpResponse(stream(), content_type="application/x-tar")
    resp["Content-Disposition"] = f'attachment; filename="personaldocs-recovery-{p.created_at:%Y%m%d-%H%M}-{str(p.id)[:8]}.tar"'
    return resp


# ------------------------------------------------------------------ Recovery Key and Emergency Recovery Package

@api_view(["POST"])
@permission_classes([IsMainAdmin])
def key_reveal(request):
    if not stepup_ok(request):
        return _needs_stepup()
    key = bk_keys.ensure_active()
    text = bk_keys.reveal_text(key.generation)
    request.session.pop("recovery_stepup_at", None)  # one reveal per step-up
    audit.record("recovery.key_revealed", request=request, generation=key.generation)  # never the key itself
    from apps.notify import events

    events.backup_event("recovery.key_revealed", actor=request.user, detail=f"Key generation {key.generation} was revealed.",
                        tag=str(time.time()))
    resp = Response({"key": text, "generation": key.generation, "fingerprint": key.fingerprint, "hide_after_seconds": 60})
    resp["Cache-Control"] = "no-store"
    return resp


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def key_rotate(request):
    if not stepup_ok(request):
        return _needs_stepup()
    if jobs_running():
        return _err("Wait until the running backup task has finished.", 409)
    jobs.enqueue("key_rotation", {"actor": str(request.user.pk), "retry": bool(request.data.get("retry"))}, max_attempts=1)
    request.session.pop("recovery_stepup_at", None)
    audit.record("recovery.key_rotation_requested", request=request, retry=bool(request.data.get("retry")))
    return Response({"status": "queued"})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def emergency_export(request):
    if not stepup_ok(request):
        return _needs_stepup()
    passphrase = request.data.get("passphrase") or ""
    if passphrase != (request.data.get("confirm") or ""):
        return _err("The two passphrases differ.")
    info = bk_keys.emergency_package(request.user)
    meta = {"installation": info["installation"], "generation": info["generation"], "created_at": timezone.now().isoformat(),
            "fingerprint": info["fingerprint"]}
    try:
        sealed = C.seal_emergency(info["raw"], passphrase, meta)
    except ValueError as exc:
        return _err(str(exc))
    sealed["instructions"] = bk_keys.INSTRUCTIONS
    EmergencyExport.objects.create(generation=info["generation"], exported_by=request.user)
    request.session.pop("recovery_stepup_at", None)
    audit.record("recovery.emergency_exported", request=request, generation=info["generation"])
    from apps.notify import events

    events.backup_event("recovery.emergency", actor=request.user, severity="success",
                        detail=f"An Emergency Recovery Package for key generation {info['generation']} was exported. Keep it offline.",
                        tag=str(time.time()))
    body = json.dumps(sealed, indent=1).encode()
    resp = HttpResponse(body, content_type="application/json")
    resp["Content-Disposition"] = f'attachment; filename="personaldocs-emergency-recovery-g{info["generation"]}.pdrp"'
    resp["Cache-Control"] = "no-store"
    return resp


# ------------------------------------------------------------------ Recovery Explorer (everyone, permission-aware)

def restore_json(r: RestoreRun, full: bool = False) -> dict:
    out = {"id": str(r.id), "kind": r.kind, "mode": r.mode, "recovery_mode": r.recovery_mode, "status": r.status,
           "point_label": r.point_label, "point": str(r.point_id) if r.point_id else None, "created_at": r.created_at.isoformat(),
           "finished_at": r.finished_at.isoformat() if r.finished_at else None, "actor": r.actor_label,
           "summary": (r.result or {}).get("summary", "")}
    if full:
        out.update(impact=r.impact, result=r.result, report=r.report, target=r.target)
    return out


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def recovery_points(request):
    pts = bk_restore.restorable_points()[:200]
    main = request.user.is_main_admin
    return Response({"points": [{"id": str(p.id), "kind": p.kind, "created_at": p.created_at.isoformat(), "status": p.status if main else None}
                                for p in pts]})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def recovery_explore(request, pk):
    p = bk_restore.restorable_points().filter(pk=pk).first()
    if p is None:
        return _err("Not found.", 404)
    try:
        return Response(bk_restore.explorer(request.user, p, owner=request.query_params.get("owner") or None,
                                            folder=request.query_params.get("folder") or None, q=request.query_params.get("q", "")[:100]))
    except bk_restore.RestoreError as exc:
        return _err(str(exc), 409)


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def recovery_compare(request, pk, doc):
    p = bk_restore.restorable_points().filter(pk=pk).first()
    if p is None:
        return _err("Not found.", 404)
    try:
        return Response(bk_restore.compare(request.user, p, str(doc)))
    except bk_restore.RestoreError as exc:
        return _err(str(exc), 404)


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def recovery_restore(request):
    p = bk_restore.restorable_points().filter(pk=request.data.get("point")).first()
    if p is None:
        return _err("Choose a recovery point.", 404)
    kind = request.data.get("kind")
    execute = bool(request.data.get("execute"))
    if ratelimit.too_many(f"restore:{request.user.pk}", 30, 3600):
        return _err("Too many restore requests. Try again later.", 429)
    try:
        run = bk_restore.run(request.user, p, kind=kind, target=request.data.get("target") or {},
                             mode=request.data.get("mode") or "keep_new", execute=execute, request=request)
    except bk_restore.RestoreError as exc:
        return _err(str(exc), 400)
    return Response(restore_json(run, full=True), status=201 if execute else 200)


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def recovery_runs(request):
    qs = RestoreRun.objects.all() if request.user.is_main_admin else RestoreRun.objects.filter(actor=request.user)
    return Response({"runs": [restore_json(r) for r in qs.exclude(status="analyzed")[:100]]})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def recovery_run_detail(request, pk):
    r = RestoreRun.objects.filter(pk=pk).first()
    if r is None or (not request.user.is_main_admin and r.actor_id != request.user.pk):
        return _err("Not found.", 404)
    data = restore_json(r, full=True)
    if request.query_params.get("export"):
        resp = HttpResponse(json.dumps(data, indent=1, default=str), content_type="application/json")
        resp["Content-Disposition"] = f'attachment; filename="personaldocs-{r.kind}-restore-report-{str(r.id)[:8]}.json"'
        return resp
    return Response(data)


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def my_recovery(request):
    return Response(bk_restore.my_recovery(request.user))
