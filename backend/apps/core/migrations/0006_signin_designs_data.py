"""Change Set W: the built-in sign-in designs become protected rows, and the previous single custom wallpaper becomes
a named custom design. Idempotent (a second run changes nothing) and non-destructive: the wallpaper and logo files
and the old settings stay, so the active appearance is kept and a rollback still finds them. Desktop/Tablet/Mobile
derivatives and colours are generated on first use."""
from django.db import migrations

BUILTINS = (("minimal", "Minimal (default)"), ("nature", "Nature"), ("travel", "Travel"), ("family", "Family"),
            ("neutral", "Neutral"))


def _get(AppSetting, key, default=None):
    row = AppSetting.objects.filter(key=key).first()
    return default if row is None or row.value is None else row.value


def forwards(apps, schema_editor):
    Design = apps.get_model("core", "SigninDesign")
    AppSetting = apps.get_model("core", "AppSetting")
    for key, name in BUILTINS:
        Design.objects.get_or_create(builtin_key=key, defaults={"name": name, "template": key})
    if _get(AppSetting, "login.active_design") is not None:
        return  # already migrated
    design = _get(AppSetting, "login.design", "minimal")
    wall = _get(AppSetting, "login.wallpaper_file", "")
    overlay = int(_get(AppSetting, "login.overlay", 0) or 0)
    focal = {"center": (0.5, 0.5), "top": (0.5, 0.0), "bottom": (0.5, 1.0), "left": (0.0, 0.5), "right": (1.0, 0.5)}
    fx, fy = focal.get(_get(AppSetting, "login.position", "center"), (0.5, 0.5))
    if wall:
        d = Design.objects.filter(migrated_from="login.wallpaper_file").first()
        if d is None:
            d = Design.objects.create(name="Custom wallpaper", template="minimal", assets={"original": wall},
                                      focal_x=fx, focal_y=fy, overlay=overlay, migrated_from="login.wallpaper_file")
        active = d if design == "custom" else Design.objects.get(builtin_key=design if design in dict(BUILTINS) else "minimal")
    else:
        active = Design.objects.get(builtin_key=design if design in dict(BUILTINS) else "minimal")
    AppSetting.objects.update_or_create(key="login.active_design", defaults={"value": active.pk})


class Migration(migrations.Migration):
    dependencies = [("core", "0005_signin_designs"), ("core", "0004_notification_detail_level")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
