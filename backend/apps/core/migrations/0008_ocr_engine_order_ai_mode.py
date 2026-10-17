"""Change Set Z: configurable OCR engine order (light-ocr / Tesseract / PaddleOCR) and AI modes.

New installations (no people yet) get the defaults from the settings registry: OCR order light-ocr → Tesseract →
PaddleOCR in Auto mode, and AI on Demand. Existing installations keep doing exactly what they did:

* OCR: the earlier default engine and fallback switch become the order — PaddleOCR with fallback → [PaddleOCR,
  Tesseract] (Auto); PaddleOCR without fallback → [PaddleOCR] (Primary only); Tesseract → [Tesseract]. light-ocr is not
  added: the Main Admin adds it under Settings → OCR → OCR Engines once it is installed and tested.
* AI: AI switched off → AI on Demand (still off until enabled, and then nothing runs automatically); AI on with
  automatic analysis → OCR + AI (new uploads only — existing documents are never queued by the upgrade); AI on without
  automatic analysis → AI on Demand. Automatic AI never uses a Cloud profile unless the new switch allows it (off).
The old keys are removed only after their values were carried over; the reverse migration restores them.
"""
from django.db import migrations

OLD_OCR = ("processing.ocr_engine", "processing.ocr_engine_fallback")


def _get(AppSetting, key, default):
    row = AppSetting.objects.filter(key=key).first()
    return default if row is None or row.value is None else row.value


def forwards(apps, schema_editor):
    AppSetting = apps.get_model("core", "AppSetting")
    User = apps.get_model("accounts", "User")
    existing = User.objects.exists()
    if existing:
        engine = _get(AppSetting, "processing.ocr_engine", "paddleocr")
        fallback = bool(_get(AppSetting, "processing.ocr_engine_fallback", True))
        if not AppSetting.objects.filter(key="processing.ocr_engine_order").exists():
            if engine == "tesseract":
                order, mode = ["tesseract"], "auto"
            else:
                order, mode = (["paddleocr", "tesseract"], "auto") if fallback else (["paddleocr"], "primary_only")
            AppSetting.objects.create(key="processing.ocr_engine_order", value=order)
            AppSetting.objects.update_or_create(key="processing.ocr_mode", defaults={"value": mode})
        if not AppSetting.objects.filter(key="ai.mode").exists():
            enabled = bool(_get(AppSetting, "ai.enabled", False))
            auto = bool(_get(AppSetting, "ai.auto_analyze", True))
            AppSetting.objects.create(key="ai.mode", value="auto" if enabled and auto else "on_demand")
    AppSetting.objects.filter(key__in=[*OLD_OCR, "ai.auto_analyze"]).delete()


def backwards(apps, schema_editor):
    AppSetting = apps.get_model("core", "AppSetting")
    order = _get(AppSetting, "processing.ocr_engine_order", None)
    if order is not None:
        first = next((e for e in order if e in ("paddleocr", "tesseract")), "tesseract")
        AppSetting.objects.update_or_create(key="processing.ocr_engine", defaults={"value": first})
        AppSetting.objects.update_or_create(key="processing.ocr_engine_fallback", defaults={
            "value": _get(AppSetting, "processing.ocr_mode", "auto") != "primary_only"})
    mode = _get(AppSetting, "ai.mode", None)
    if mode is not None:
        AppSetting.objects.update_or_create(key="ai.auto_analyze", defaults={"value": mode in ("auto", "smart")})
        if mode == "ocr_only":
            AppSetting.objects.update_or_create(key="ai.enabled", defaults={"value": False})
    AppSetting.objects.filter(key__in=["processing.ocr_engine_order", "processing.ocr_mode", "ai.mode"]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0007_performance_metrics"), ("accounts", "0009_usersession_recognized_device")]
    operations = [migrations.RunPython(forwards, backwards)]
