"""Change Set V: the sign-in map shows English labels. Installations on the standard OpenStreetMap tiles (whose labels
are in the local language, e.g. Arabic) move to the OpenFreeMap English-label preset. A MapTiler, Stadia or custom
choice is kept. The administrator can choose OpenStreetMap again in Settings → Security → Access policy."""
from django.db import migrations


def forwards(apps, schema_editor):
    AppSetting = apps.get_model("core", "AppSetting")
    row = AppSetting.objects.filter(key="security.map_provider").first()
    if row is not None and row.value == "osm":
        row.value = "openfreemap"
        row.save(update_fields=["value"])


class Migration(migrations.Migration):
    dependencies = [("security", "0004_loginevent_coord_source_loginevent_lat_and_more"), ("core", "0003_overview")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
