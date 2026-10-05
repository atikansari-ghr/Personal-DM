"""Daily / weekly / monthly backup schedules (AT-71)."""
import zoneinfo
from datetime import datetime
from unittest import mock

import pytest

from apps.core import config
from apps.core.models import Job
from apps.ops import schedule

pytestmark = pytest.mark.django_db
TZ = zoneinfo.ZoneInfo("Asia/Riyadh")


def at(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def _tick(now):
    from apps.notify.management.commands import scheduler

    with mock.patch("apps.notify.expiry.local_now", return_value=now), \
            mock.patch("django.utils.timezone.now", return_value=now.astimezone(zoneinfo.ZoneInfo("UTC"))):
        scheduler.tick()
    return Job.objects.filter(kind="backup").count()


def test_daily_weekly_monthly_occurrences(family):
    config.set_value("general.timezone", "Asia/Riyadh")
    config.set_value("backup.schedule_time", "02:30")
    assert schedule.next_occurrence(at(2026, 10, 5, 1, 0)) == at(2026, 10, 5, 2, 30)
    assert schedule.describe() == "Every day at 02:30"
    config.set_value("backup.frequency", "weekly")
    config.set_value("backup.weekday", "fri")
    assert schedule.next_occurrence(at(2026, 10, 5, 12)) == at(2026, 10, 9, 2, 30)  # 5 Oct 2026 is a Monday
    assert schedule.last_occurrence(at(2026, 10, 5, 12)) == at(2026, 10, 2, 2, 30)
    assert schedule.describe() == "Every Friday at 02:30"
    config.set_value("backup.frequency", "monthly")
    config.set_value("backup.month_day", 31)
    assert schedule.next_occurrence(at(2026, 11, 2)) == at(2026, 11, 30, 2, 30)  # November has 30 days
    assert schedule.next_occurrence(at(2027, 2, 1)) == at(2027, 2, 28, 2, 30)
    assert schedule.next_occurrence(at(2026, 12, 1)) == at(2026, 12, 31, 2, 30)
    assert "last day" in schedule.describe()
    config.set_value("backup.enabled", False)
    assert schedule.next_occurrence(at(2026, 12, 1)) is None and schedule.describe() == "Automatic backups are off"


def test_at71_scheduler_runs_each_schedule_once_survives_restart_and_catches_up(family, tmp_path):
    config.set_value("general.timezone", "Asia/Riyadh")
    config.set_value("backup.target", str(tmp_path))
    config.set_value("backup.schedule_time", "02:30")
    config.set_value("backup.frequency", "weekly")
    config.set_value("backup.weekday", "wed")
    assert _tick(at(2026, 10, 7, 2, 0)) == 0  # Wednesday, before the time
    assert _tick(at(2026, 10, 7, 2, 31)) == 1
    assert _tick(at(2026, 10, 7, 2, 32)) == 1  # not twice (state is in the database, so a restart is the same)
    assert _tick(at(2026, 10, 8, 2, 31)) == 1  # Thursday: nothing
    # server off over the scheduled time: the missed backup runs once at the next tick
    assert _tick(at(2026, 10, 15, 9, 0)) == 2
    assert _tick(at(2026, 10, 15, 9, 1)) == 2
    config.set_value("backup.frequency", "monthly")
    config.set_value("backup.month_day", 31)
    assert _tick(at(2026, 10, 30, 3, 0)) == 2
    assert _tick(at(2026, 10, 31, 3, 0)) == 3
    assert _tick(at(2026, 11, 30, 3, 0)) == 4  # 30 November stands in for the 31st
    config.set_value("backup.enabled", False)
    assert _tick(at(2026, 12, 31, 3, 0)) == 4


def test_backup_status_shows_schedule_next_run_and_retention(family, clients, tmp_path):
    config.set_value("backup.target", str(tmp_path))
    config.set_value("backup.frequency", "monthly")
    config.set_value("backup.month_day", 15)
    r = clients["dad"].get("/api/backup").json()
    assert r["schedule"].startswith("Monthly on day 15") and r["next_run"] and r["keep"] == 14
    assert clients["son1"].get("/api/backup").status_code == 403
    # invalid values are refused
    assert clients["dad"].put("/api/settings", {"values": {"backup.month_day": 32}}, format="json").status_code == 400
    assert clients["dad"].put("/api/settings", {"values": {"backup.frequency": "hourly"}}, format="json").status_code == 400
