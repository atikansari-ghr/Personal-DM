"""Scheduler: reminders, outbox delivery, Telegram linking, email polling, backups, retention."""
import logging
import signal
import time
from datetime import datetime, timedelta

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

    out = {}
    now_local = expiry.local_now()
    SchedulerRun.objects.update_or_create(name="scheduler_heartbeat", defaults={"last_run_at": timezone.now()})
    if _due_daily("expiry_scan", config.get("notifications.send_time"), now_local):
        out["expiry"] = expiry.run_expiry_scan(now_local.date())
        _mark("expiry_scan", now_local)
    out["outbox"] = expiry.deliver_outbox()
    if config.get("telegram.enabled") and config.is_set("telegram.bot_token"):
        try:
            out["telegram_links"] = telegram.poll_updates()
        except telegram.TelegramError as exc:
            log.warning("telegram poll failed: %s", exc)
    from apps.mailimport.imap import due_accounts

    for acc in due_accounts():
        jobs.enqueue("email_poll", {"account_id": acc.id}, idempotency_key=f"email:{acc.id}:{timezone.now():%Y%m%d%H%M}")
    if config.get("backup.target"):
        from apps.ops import schedule

        row, _ = SchedulerRun.objects.get_or_create(name="backup")
        occ = schedule.due(now_local, row.last_run_at)
        if occ is not None:
            jobs.enqueue("backup", {"scheduled_for": occ.isoformat()}, max_attempts=1, idempotency_key=f"backup:{occ.isoformat()}")
            SchedulerRun.objects.filter(name="backup").update(last_local_date=now_local.date(), last_run_at=timezone.now())
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
    return out


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
