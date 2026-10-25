"""Scheduler: reminders, outbox delivery, Telegram linking, email polling, backups, retention."""
import logging
import signal
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from apps.core import config, jobs

log = logging.getLogger("personaldocs.scheduler")


def _due_daily(name: str, hhmm: str, now_local) -> bool:
    from apps.notify.models import SchedulerRun

    if not hhmm:
        return False
    row, _ = SchedulerRun.objects.get_or_create(name=name)
    h, m = (int(x) for x in hhmm.split(":"))
    if row.last_local_date == now_local.date():
        return False
    return (now_local.hour, now_local.minute) >= (h, m)


def _mark(name: str, now_local) -> None:
    from apps.notify.models import SchedulerRun

    SchedulerRun.objects.update_or_create(name=name, defaults={"last_local_date": now_local.date(), "last_run_at": timezone.now()})


def tick() -> dict:
    from apps.core import ratelimit
    from apps.core.models import AuditEvent
    from apps.notify import expiry, telegram
    from apps.notify.models import SchedulerRun

    from django.conf import settings as dj

    if getattr(dj, "SANDBOX", False):
        return {"sandbox": True}  # recovery validation copy: no reminders, deliveries, imports or backups
    out = {}
    now_local = expiry.local_now()
    SchedulerRun.objects.update_or_create(name="scheduler_heartbeat", defaults={"last_run_at": timezone.now()})
    # Change Set X: a system sample about once a minute (Admin → Performance) and the adaptive throttle decision
    perf_run = SchedulerRun.objects.filter(name="perf_sample").first()
    if perf_run is None or perf_run.last_run_at is None or (timezone.now() - perf_run.last_run_at).total_seconds() >= 55:
        try:
            from apps.core import perf, throttle

            sample = perf.sample_system()
            out["throttle"] = throttle.evaluate(sample).get("active")
            SchedulerRun.objects.update_or_create(name="perf_sample", defaults={"last_run_at": timezone.now(), "state": sample})
            if _due_daily("perf_purge", "03:40", now_local):
                out["perf_purged"] = perf.purge()
                _mark("perf_purge", now_local)
        except Exception:  # noqa: BLE001 - measuring must never stop reminders or deliveries
            log.exception("performance sample failed")
    if _due_daily("expiry_scan", config.get("notifications.send_time"), now_local):
        out["expiry"] = expiry.run_expiry_scan(now_local.date())
        _mark("expiry_scan", now_local)
    out["outbox"] = expiry.deliver_outbox()
    try:
        from apps.notify import routing

        out["digests"] = routing.run_digests()
    except Exception:  # noqa: BLE001 - digests must not stop reminders
        log.exception("digest run failed")
    if config.get("telegram.enabled") and config.is_set("telegram.bot_token"):
        try:
            out["telegram_links"] = telegram.poll_updates()
        except telegram.TelegramError as exc:
            log.warning("telegram poll failed: %s", exc)
    from apps.mailimport.imap import due_accounts

    for acc in due_accounts():
        jobs.enqueue("email_poll", {"account_id": acc.id}, idempotency_key=f"email:{acc.id}:{timezone.now():%Y%m%d%H%M}")
    try:
        out["backup"] = backup_tick(now_local)
    except Exception:  # noqa: BLE001 - backup scheduling problems must not stop reminders
        log.exception("backup scheduling failed")
    if _due_daily("maintenance", "03:30", now_local):
        days = int(config.get("audit.retention_days"))
        if days:
            AuditEvent.objects.filter(at__lt=timezone.now() - timedelta(days=days)).delete()
        ratelimit.prune()
        jobs.enqueue("integrity_check", {"checksums": False}, idempotency_key=f"integrity:{now_local.date()}")
        _mark("maintenance", now_local)
    try:
        from apps.security.jobs import tick as security_tick

        out["security"] = security_tick(now_local, _due_daily, _mark)
    except Exception:  # noqa: BLE001 - security housekeeping must not stop reminders/backups
        log.exception("security maintenance failed")
    try:  # Change Set AB: maintenance jobs progress even when no browser is watching; logs follow their own retention
        from apps.ops import maintenance

        out["maintenance_jobs"] = maintenance.sync_active()
        from apps.security import active_sessions

        out["high_risk_sessions"] = active_sessions.scan_high_risk()
        if _due_daily("maintenance_purge", "03:50", now_local):
            out["maintenance_purged"] = maintenance.purge()
            _mark("maintenance_purge", now_local)
    except Exception:  # noqa: BLE001 - must never stop reminders/backups
        log.exception("maintenance job sync failed")
    try:
        from apps.core import rotation

        out["signin_rotation"] = rotation.tick(now_local)
    except Exception as exc:  # noqa: BLE001 - a design problem must never stop reminders/backups
        log.exception("sign-in design rotation failed")
        try:
            from apps.core import designs

            designs._alert(f"Sign-in design rotation failed: {type(exc).__name__}. The current design stays active.",
                           tag="rotation:failed")
        except Exception:  # noqa: BLE001
            pass
    return out


def backup_tick(now_local) -> dict:
    """Encrypted recovery points per policy (Full on its schedule, incrementals every N hours), copy retries and
    optional automated recovery validation. A configured legacy backup folder without policies is adopted as a
    destination first (same as the upgrade migration), so no unencrypted folder backups are made any more."""
    from apps.ops import bk_engine
    from apps.ops.models import BackupPolicy, RestoreRun

    if config.get("backup.target") and not BackupPolicy.objects.exists():
        import importlib

        from django.apps import apps as django_apps

        importlib.import_module("apps.ops.migrations.0002_migrate_backup_settings").forwards(django_apps, None)
    queued = []
    for pol, kind, slot in bk_engine.due_points(now_local):
        jobs.enqueue("backup_point", {"policy": pol.id, "kind": kind, "trigger": "scheduled", "slot": slot}, max_attempts=1,
                     idempotency_key=f"bkp:{pol.id}:{kind}:{slot}")
        if kind == "full":  # stored in the database: a restart never loses or repeats a run; a missed one runs once
            from apps.notify.models import SchedulerRun

            SchedulerRun.objects.update_or_create(name=f"backup_policy:{pol.id}:full", defaults={"last_run_at": timezone.now()})
        queued.append(kind)
    jobs.enqueue("backup_retry", {}, idempotency_key=f"bkretry:{timezone.now():%Y%m%d%H}{timezone.now().minute // 15}")
    days = [p.validation_days for p in BackupPolicy.objects.filter(enabled=True, validation_days__gt=0)]
    if days:
        last = RestoreRun.objects.filter(kind="validation").first()
        if last is None or timezone.now() - last.created_at >= timedelta(days=min(days)):
            jobs.enqueue("recovery_validation", {}, max_attempts=1, idempotency_key=f"validate:{now_local.date()}")
    return {"queued": queued}


class Command(BaseCommand):
    help = "Run the scheduler loop (systemd: personaldocs-scheduler.service). --once runs a single tick."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **opts):
        if opts["once"]:
            self.stdout.write(str(tick()))
            return
        stop = {"flag": False}
        signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
        signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))
        while not stop["flag"]:
            close_old_connections()
            try:
                tick()
            except Exception:  # noqa: BLE001 - keep the scheduler alive; errors are logged
                log.exception("scheduler tick failed")
            for _ in range(30):
                if stop["flag"]:
                    break
                time.sleep(1)
