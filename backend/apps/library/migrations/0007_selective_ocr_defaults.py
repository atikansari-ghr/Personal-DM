"""Selective OCR defaults (Change Set K).

* Every document type gets its expected structured fields and English as the default OCR language.
* New installations (setup not yet completed) default to Manual OCR and no Local AI access to recognised text.
* Existing installations keep their previous behaviour (every upload was recognised automatically and Local AI could
  analyse it): their types are set to Automatic with AI allowed, and documents without a type also stay Automatic.
  Administrators can switch any type to Manual or Disabled in Settings -> OCR & processing.
* Documents that were already recognised get an OCR state and their current file as the primary OCR source.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.library.ocr_policy import TEMPLATE_FIELDS

    DocumentType = apps.get_model("library", "DocumentType")
    Document = apps.get_model("library", "Document")
    DocumentField = apps.get_model("library", "DocumentField")
    SetupState = apps.get_model("accounts", "SetupState")
    AppSetting = apps.get_model("core", "AppSetting")
    existing = SetupState.objects.filter(completed_at__isnull=False).exists()
    DocumentType.objects.get_or_create(name="Employee / company ID",
                                       defaults={"template": "employee_id", "has_expiry": True, "emoji": "💼"})
    for t in DocumentType.objects.all():
        t.ocr_fields = TEMPLATE_FIELDS.get(t.template, [])
        t.ocr_languages = t.ocr_languages or ["eng"]
        if existing:
            t.ocr_mode, t.ocr_ai_allowed = "automatic", True
        t.save(update_fields=["ocr_fields", "ocr_languages", "ocr_mode", "ocr_ai_allowed"])
    if existing:
        for key, value in (("processing.ocr_untyped_mode", "automatic"), ("processing.ocr_untyped_ai_allowed", True)):
            AppSetting.objects.get_or_create(key=key, defaults={"value": value})
    for d in Document.objects.filter(current_version__ocr_applied=True).only("id", "current_version_id"):
        proposed = DocumentField.objects.filter(document_id=d.id, status="proposed").exists()
        Document.objects.filter(pk=d.id).update(
            ocr_state="needs_review" if proposed else "confirmed",
            ocr_sources=[{"version": str(d.current_version_id), "pages": ""}])


class Migration(migrations.Migration):
    dependencies = [("library", "0006_selective_ocr"), ("accounts", "0004_passkeys"), ("core", "0002_public_title")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
