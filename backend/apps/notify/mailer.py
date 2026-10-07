"""SMTP delivery configured from the settings registry (no secrets in environment files)."""
from __future__ import annotations

from django.core.mail import EmailMultiAlternatives
from django.core.mail.backends.smtp import EmailBackend

from apps.core import config


class NotConfigured(Exception):
    pass


class RegistryEmailBackend(EmailBackend):
    def __init__(self, **kwargs):
        if not config.get("smtp.enabled") or not config.get("smtp.host"):
            raise NotConfigured("Email (SMTP) is not configured. Configure it in Settings → Connections.")
        security = config.get("smtp.security")
        super().__init__(
            host=config.get("smtp.host"),
            port=int(config.get("smtp.port")),
            username=config.get("smtp.username") or None,
            password=config.get("smtp.password") or None,
            use_tls=security == "starttls",
            use_ssl=security == "ssl",
            timeout=20,
            fail_silently=False,
        )


def send_mail_now(to: str, subject: str, body: str, html: str = "") -> None:
    """Send now. With ``html`` the message is multipart: the plain-text part is complete on its own and the HTML part
    has no scripts, external images or trackers."""
    backend = RegistryEmailBackend()
    msg = EmailMultiAlternatives(subject=subject, body=body, from_email=config.get("smtp.from_address") or None, to=[to],
                                 connection=backend)
    if html:
        msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)
