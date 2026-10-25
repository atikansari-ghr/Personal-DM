"""Change Set AA: archive state of document type fields.

A field that was switched off ("Shown" unchecked) already behaved like an archived field — kept, with its values,
but hidden from the Details panel and from OCR / AI. It is now labelled Archived (archived_at = its last change).
No value is changed or removed. Re-running is harmless: only fields without an archive date are touched.
"""
from django.conf import settings
from django.db import migrations, models
from django.db.models import F


def forwards(apps, schema_editor):
    Field = apps.get_model("library", "DocumentTypeField")
    Field.objects.filter(enabled=False, archived_at__isnull=True).update(archived_at=F("updated_at"), archived_order=F("order"))


class Migration(migrations.Migration):
    dependencies = [("library", "0012_doc_active_folder_idx"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.AddField("documenttypefield", "archived_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("documenttypefield", "archived_by", models.ForeignKey(
            blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
        migrations.AddField("documenttypefield", "archived_order", models.IntegerField(
            blank=True, null=True, help_text="Position before it was archived")),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
