"""Change Set P: passkey sign-in mode replaces the off-by-default "allow passwordless" switch.

* An explicit earlier choice is kept: "allow passwordless" saved as off -> mode "Password + Passkey" (mfa); saved as
  on -> "Passwordless". Never chosen -> the new default, Passwordless.
* In Passwordless mode, accounts that already own a discoverable passkey get passwordless sign-in turned on (as new
  enrolments do). They can turn it off in My account; their password, TOTP and recovery codes keep working.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    AppSetting = apps.get_model("core", "AppSetting")
    User = apps.get_model("accounts", "User")
    Cred = apps.get_model("accounts", "WebAuthnCredential")
    old = AppSetting.objects.filter(key="auth.allow_passwordless").first()
    mode = "passwordless"
    if old is not None and old.value is not None:
        mode = "passwordless" if bool(old.value) else "mfa"
    if old is not None:
        AppSetting.objects.update_or_create(key="auth.passkey_mode", defaults={"value": mode})
        old.delete()
    if mode == "passwordless":
        ids = Cred.objects.filter(revoked_at__isnull=True, discoverable=True).values_list("user_id", flat=True)
        User.objects.filter(pk__in=list(ids), is_active=True).update(passwordless_enabled=True)


def backwards(apps, schema_editor):
    AppSetting = apps.get_model("core", "AppSetting")
    row = AppSetting.objects.filter(key="auth.passkey_mode").first()
    if row is not None:
        AppSetting.objects.update_or_create(key="auth.allow_passwordless", defaults={"value": row.value != "mfa"})
        row.delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_external_identity"), ("core", "0003_overview")]
    operations = [migrations.RunPython(forwards, backwards)]
