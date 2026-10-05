"""The public title became "Personal Documents Management System". Installations still showing the old default
name get the new one; a name the administrator chose is kept."""
from django.db import migrations

OLD, NEW = "Personal Documents", "Personal Documents Management System"


def forwards(apps, schema_editor):
    AppSetting = apps.get_model("core", "AppSetting")
    for s in AppSetting.objects.filter(key="general.app_name"):
        if s.value == OLD:
            s.value = NEW
            s.save(update_fields=["value"])


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
