from django.apps import AppConfig


class OpsConfig(AppConfig):
    name = "apps.ops"
    label = "ops"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import views  # noqa: F401 - registers job handlers
