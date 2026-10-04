from django.apps import AppConfig


class NotifyConfig(AppConfig):
    name = "apps.notify"
    label = "notify"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        pass
