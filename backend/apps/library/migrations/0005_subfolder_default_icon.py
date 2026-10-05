"""Sub-folders below the first level get the standard folder icon unless someone chose an icon (J2).

Only automatically assigned icons change; icons a person picked (emoji_is_custom) are kept.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Folder = apps.get_model("library", "Folder")
    (Folder.objects.filter(emoji_is_custom=False, kind="normal", parent__kind="normal")
     .exclude(emoji="📁").update(emoji="📁"))


class Migration(migrations.Migration):
    dependencies = [("library", "0004_ocr_quality_no_expiry")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
