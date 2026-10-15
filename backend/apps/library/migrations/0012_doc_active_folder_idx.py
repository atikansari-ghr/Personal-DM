"""Change Set X: partial index for document counts per folder (index-only scan of active documents).

Created CONCURRENTLY, so the upgrade never blocks reading or writing documents while it is built. Data is not
changed. Reversible (the index is dropped concurrently). ``IF NOT EXISTS`` makes a repeated or interrupted run safe.
"""
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    atomic = False  # CREATE INDEX CONCURRENTLY cannot run inside a transaction

    dependencies = [("library", "0011_offline_devices")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="document",
                    index=models.Index(fields=["folder"], condition=Q(archived_at__isnull=True), name="doc_active_folder_idx"),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='CREATE INDEX CONCURRENTLY IF NOT EXISTS "doc_active_folder_idx" ON "library_document" ("folder_id") '
                        'WHERE "archived_at" IS NULL',
                    reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "doc_active_folder_idx"',
                ),
            ],
        ),
    ]
