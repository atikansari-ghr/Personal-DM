"""Change Set AA: Processing Source provenance on AI jobs and suggestions.

Adds empty fields only: existing jobs and suggestions keep everything they had (their source is simply not recorded).
No document is queued or sent to AI by this migration.
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai", "0003_intelligence")]

    operations = [
        migrations.AddField("aijob", "processing_source", models.CharField(blank=True, max_length=20)),
        migrations.AddField("aijob", "final_source", models.CharField(blank=True, max_length=20)),
        migrations.AddField("aijob", "fallback_used", models.BooleanField(default=False)),
        migrations.AddField("aijob", "fallback_reason", models.CharField(blank=True, max_length=300)),
        migrations.AddField("aisuggestion", "source", models.CharField(blank=True, max_length=20)),
        migrations.AddField("aisuggestion", "page", models.PositiveSmallIntegerField(blank=True, null=True)),
    ]
