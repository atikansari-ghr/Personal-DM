from django.db import migrations


def seed(apps, schema_editor):
    from apps.library.management.commands.seed_defaults import DEFAULT_TYPES

    DocumentType = apps.get_model("library", "DocumentType")
    for name, template, expiry, emoji in DEFAULT_TYPES:
        DocumentType.objects.get_or_create(name=name, defaults={"template": template, "has_expiry": expiry, "emoji": emoji})


class Migration(migrations.Migration):
    dependencies = [("library", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
