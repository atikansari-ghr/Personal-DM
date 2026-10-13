"""Change Set V: the standalone Settings → Storage & NAS connection becomes a Backup & Recovery destination.

Idempotent (a rerun updates the same destination) and non-destructive: the old ``nas.*`` settings, the encrypted
SMB password, existing recovery points, copies, policy links and backup files are kept. A configuration that does
not validate is migrated as **Needs Attention** instead of being dropped. See apps/ops/nas_migration.py.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.ops import nas_migration

    nas_migration.run(apps.get_model("ops", "BackupDestination"), apps.get_model("core", "AppSetting"),
                      apps.get_model("ops", "BackupPolicy"), apps.get_model("core", "AuditEvent"))


def backwards(apps, schema_editor):
    # Rolling back keeps the destination (removing it could orphan its recovery points); the old settings were
    # never removed, so the previous release's Storage & NAS page works again unchanged.
    pass


class Migration(migrations.Migration):
    dependencies = [("ops", "0002_migrate_backup_settings"), ("core", "0003_overview")]
    operations = [migrations.RunPython(forwards, backwards)]
