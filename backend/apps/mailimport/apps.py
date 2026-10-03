from django.apps import AppConfig


class MailimportConfig(AppConfig):
    name = "apps.mailimport"
    label = "mailimport"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import imap  # noqa: F401 - registers job handlers
