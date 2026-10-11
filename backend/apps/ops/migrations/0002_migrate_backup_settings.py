"""Change Set T: carry the existing backup configuration into Backup & Recovery (nothing is reset or deleted).

* A configured ``backup.target`` becomes a destination ("Existing backup share"; NAS when it had to be a mount point).
* The existing schedule becomes the policy's Full schedule unchanged (daily/weekly/monthly at the same time);
  incrementals start off for existing installations (turn them on in the policy). New installations get the
  recommended weekly Full + incremental every 4 hours when the first destination is added.
* Existing folder backups (format 1) are left in place, listed as legacy, and stay restorable.
"""
from django.db import migrations


def _get(AppSetting, key, default):
    row = AppSetting.objects.filter(key=key).first()
    return default if row is None or row.value is None else row.value


def forwards(apps, schema_editor):
    AppSetting = apps.get_model("core", "AppSetting")
    Destination = apps.get_model("ops", "BackupDestination")
    Policy = apps.get_model("ops", "BackupPolicy")
    target = _get(AppSetting, "backup.target", "")
    if not target or Policy.objects.exists():
        return
    require_mount = bool(_get(AppSetting, "backup.require_mount", True))
    dest = Destination.objects.create(name="Existing backup share", kind="nas" if require_mount else "local",
                                      config={"path": target, "require_mount": require_mount})
    pol = Policy.objects.create(
        name="Default", enabled=bool(_get(AppSetting, "backup.enabled", True)),
        full_frequency=_get(AppSetting, "backup.frequency", "daily"), full_weekday=_get(AppSetting, "backup.weekday", "sun"),
        full_month_day=int(_get(AppSetting, "backup.month_day", 1)), full_time=_get(AppSetting, "backup.schedule_time", "02:30"),
        incremental_hours=0, retention_weeks=4)
    pol.destinations.add(dest)


class Migration(migrations.Migration):
    dependencies = [("ops", "0001_initial"), ("core", "0003_overview")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
