"""Change Set AB: last activity per session (Active vs Signed In). Existing sessions start from their last request
time, so nobody looks Active just because the upgrade ran."""

import django.utils.timezone
from django.db import migrations, models
from django.db.models import F


def backfill(apps, schema_editor):
    apps.get_model("accounts", "UserSession").objects.update(last_activity_at=F("last_seen_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_usersession_recognized_device"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersession",
            name="last_activity_at",
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
