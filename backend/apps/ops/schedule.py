"""Backup schedule: daily, weekly (day + time) or monthly (day of month + time), in the installation timezone.

* A monthly day that does not exist in a month (29, 30, 31) runs on that month's last day.
* If the server was off at the scheduled time, the missed backup runs at the next scheduler tick (once).
* Retention (``backup.keep_daily``) is independent of the frequency: it always keeps that many successful backups.
* Everything is stored in the database, so a restart never loses or repeats a run.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta

from apps.core import config

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_NAMES = {d: calendar.day_name[i] for i, d in enumerate(WEEKDAYS)}


def _at() -> time | None:
    hhmm = config.get("backup.schedule_time")
    if not hhmm or not config.get("backup.enabled"):
        return None
    h, m = (int(x) for x in hhmm.split(":"))
    return time(h, m)


def runs_on(day: date) -> bool:
    freq = config.get("backup.frequency")
    if freq == "weekly":
        return WEEKDAYS[day.weekday()] == config.get("backup.weekday")
    if freq == "monthly":
        wanted = int(config.get("backup.month_day"))
        return day.day == min(wanted, calendar.monthrange(day.year, day.month)[1])
    return True


def last_occurrence(now_local: datetime) -> datetime | None:
    """Most recent scheduled moment at or before ``now_local`` (looks back up to ~2 months)."""
    at = _at()
    if at is None:
        return None
    day = now_local.date()
    for _ in range(64):
        moment = datetime.combine(day, at, tzinfo=now_local.tzinfo)
        if moment <= now_local and runs_on(day):
            return moment
        day -= timedelta(days=1)
    return None


def next_occurrence(now_local: datetime) -> datetime | None:
    at = _at()
    if at is None:
        return None
    day = now_local.date()
    for _ in range(64):
        moment = datetime.combine(day, at, tzinfo=now_local.tzinfo)
        if moment > now_local and runs_on(day):
            return moment
        day += timedelta(days=1)
    return None


def due(now_local: datetime, last_run_at: datetime | None) -> datetime | None:
    """The occurrence to run now, or None. ``last_run_at`` is when the previous scheduled backup was started."""
    occ = last_occurrence(now_local)
    if occ is None or (last_run_at is not None and last_run_at >= occ):
        return None
    if last_run_at is None and occ.date() != now_local.date():
        return None  # first schedule ever: start with the next occurrence (or today's), not an old one
    return occ


def describe() -> str:
    at = config.get("backup.schedule_time")
    if not config.get("backup.enabled") or not at:
        return "Automatic backups are off"
    freq = config.get("backup.frequency")
    if freq == "weekly":
        return f"Every {WEEKDAY_NAMES[config.get('backup.weekday')]} at {at}"
    if freq == "monthly":
        d = int(config.get("backup.month_day"))
        suffix = " (or the month's last day)" if d > 28 else ""
        return f"Monthly on day {d}{suffix} at {at}"
    return f"Every day at {at}"
