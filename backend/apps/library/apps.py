from django.apps import AppConfig


class LibraryConfig(AppConfig):
    name = "apps.library"
    label = "library"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import imports, ocr_runs, processing  # noqa: F401 - registers job handlers
