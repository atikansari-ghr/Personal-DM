from django.apps import AppConfig


class AIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    label = "ai"

    def ready(self):
        from . import jobs  # noqa: F401 - registers job handlers
