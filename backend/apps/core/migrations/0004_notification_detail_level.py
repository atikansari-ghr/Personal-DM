"""Change Set W: Notification Detail Level replaces "include names" / "include document numbers".

New default: Full Details. An administrator who had explicitly turned *off* names in external messages chose a
stronger privacy setting; that choice is kept as Minimal Details. People keep "Use system default" (no row needed).
Idempotent: an existing detail_level row is never changed.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    AppSetting = apps.get_model("core", "AppSetting")
    if AppSetting.objects.filter(key="notifications.detail_level").exists():
        return
    names = AppSetting.objects.filter(key="notifications.include_names").first()
    if names is not None and names.value is False:
        AppSetting.objects.create(key="notifications.detail_level", value="minimal")


class Migration(migrations.Migration):
    dependencies = [("core", "0003_overview")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
