"""Background jobs: GeoIP updates, GoAccess reports, temporary-access expiry, retention."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from apps.core import config, jobs

log = logging.getLogger("personaldocs.security")


@jobs.handler("geoip_update")
def geoip_update(job):
    from . import alerts, geoip, policy

    try:
        result = geoip.update_from_maxmind(config.get("geoip.account_id"), config.get("geoip.license_key"),
                                           config.get("geoip.edition"))
    except geoip.GeoIPError as exc:
        alerts.admin_event("alerts.health", "GeoIP update failed",
                           f"{exc} The previous database (if any) is still used; the access policy is unchanged.",
                           key=f"geoip:{timezone.localdate()}")
        raise jobs.PermanentFailure(str(exc))
    policy.invalidate()
    return result


@jobs.handler("goaccess_report")
def goaccess_report(job):
    from . import traffic

    return traffic.build_report()


def expire_temporary_access() -> int:
    """Temporary country rules stop granting access by time alone; this notifies once when they end."""
    from . import alerts, policy
    from .models import TemporaryCountryAccess

    now = timezone.now()
    n = 0
    for row in TemporaryCountryAccess.objects.filter(ends_at__lte=now, expiry_notified=False):
        row.expiry_notified = True
        row.save(update_fields=["expiry_notified"])
        alerts.admin_event("alerts.policy_changes", "Temporary country access ended",
                           f"Temporary access for {row.country} ({row.reason}) ended at {timezone.localtime(row.ends_at):%Y-%m-%d %H:%M}.",
                           key=f"temp_end:{row.pk}")
        n += 1
    if n:
        policy.invalidate()
    return n


def retention() -> int:
    from .models import BlockedStat, IPRule, LoginEvent

    days = int(config.get("security.login_audit_retention_days"))
    removed = 0
    if days:
        removed = LoginEvent.objects.filter(at__lt=timezone.now() - timedelta(days=days)).delete()[0]
    BlockedStat.objects.filter(day__lt=timezone.localdate() - timedelta(days=400)).delete()
    IPRule.objects.filter(automatic=True, expires_at__lt=timezone.now() - timedelta(days=30)).delete()
    return removed


def tick(now_local, due_daily, mark) -> dict:
    """Called from the scheduler loop."""
    out = {"temporary_expired": expire_temporary_access()}
    if config.get("goaccess.enabled"):
        from . import traffic

        summary = traffic.read_summary()
        fresh = summary and summary.get("generated_at", "") > (timezone.now() - timedelta(minutes=55)).isoformat()
        if not fresh:
            jobs.enqueue("goaccess_report", {}, max_attempts=1, idempotency_key=f"goaccess:{timezone.now():%Y%m%d%H}")
    if due_daily("security_maintenance", "03:40", now_local):
        out["login_events_removed"] = retention()
        if config.get("geoip.auto_update") and config.is_set("geoip.license_key") and now_local.weekday() == 2:
            jobs.enqueue("geoip_update", {}, max_attempts=2, idempotency_key=f"geoip:{now_local:%Y%m%d}")
        mark("security_maintenance", now_local)
    return out
