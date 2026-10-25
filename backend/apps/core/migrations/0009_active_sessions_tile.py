"""Change Set AB: add the Active Sessions tile to administrators who chose their Overview widgets before Overview groups
existed (an explicit widget list). Everything they arranged stays; the tile is appended once, so it shows in General.
Accounts with groups get it through the known-tiles mechanism; family members never see this tile."""

from django.db import migrations
from django.db.models import Q


def add_tile(apps, schema_editor):
    UserSetting = apps.get_model("core", "UserSetting")
    User = apps.get_model("accounts", "User")
    admins = User.objects.filter(Q(is_main_admin=True) | Q(is_admin=True)).values_list("id", flat=True)
    for row in UserSetting.objects.filter(key="me.dashboard_widgets", user_id__in=list(admins)):
        if isinstance(row.value, list) and "sessions" not in row.value:
            row.value = [*row.value, "sessions"]
            row.save(update_fields=["value"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_ocr_engine_order_ai_mode"),
        ("accounts", "0010_session_activity"),
    ]

    operations = [migrations.RunPython(add_tile, migrations.RunPython.noop)]
