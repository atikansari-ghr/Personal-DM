"""Password resets: self-service email link, administrator "Send Password Reset Email" and administrator temporary
passwords (Change Set P).

Rules kept here so every entry point behaves the same:

* reset tokens: 32 random bytes, only their hash is stored, single use, valid ``auth.reset_token_minutes`` (default
  30); a newer request or any password change invalidates every older unused token;
* the reset link is sent directly by email (branded HTML + plain text). It is never written to the notification
  outbox, the in-app history, Telegram, push or any log;
* a temporary password is shown to the administrator once in the API response and stored only as a password hash;
  it is never emailed. The person must change it at the next sign-in; all their sessions end (a changed password
  hash invalidates every Django session, so this is not optional);
* an Administrator cannot reset the Main Administrator (only another main administrator can; the console recovery
  ``personaldocs recover-admin`` stays available);
* internet-facing installations send reset links only over https.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import audit, config, crypto

from . import services as S
from .models import PasswordResetToken, User


class ResetError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def can_reset(actor: User, target: User) -> None:
    if not (actor.is_main_admin or actor.is_admin):
        raise ResetError("Only administrators can reset passwords.", 403)
    if target.pk == actor.pk:
        raise ResetError("Use My account → Password & security → Change password for your own account.", 400)
    if target.is_main_admin and not actor.is_main_admin:
        raise ResetError("Only a main administrator can reset a main administrator's password. If no main administrator "
                         "can sign in, use the server console: sudo personaldocs recover-admin USERNAME", 403)
    if not target.is_active:
        raise ResetError("This account is disabled. Enable it first.", 400)


def https_ok() -> bool:
    return settings.PUBLIC_ORIGIN.startswith("https://") or config.get("security.deployment") != "internet"


def new_token(user: User) -> str:
    """Create a single-use token and invalidate every older unused one."""
    now = timezone.now()
    token = crypto.token_urlsafe(32)
    with transaction.atomic():
        user.reset_tokens.filter(used_at__isnull=True).update(used_at=now)
        PasswordResetToken.objects.create(user=user, token_hash=crypto.hash_token(token),
                                          expires_at=now + timedelta(minutes=int(config.get("auth.reset_token_minutes"))))
    return token


def send_reset_email(user: User, *, actor: User | None = None) -> None:
    """Branded reset email with the single-use link (sent directly; raises on SMTP problems)."""
    from apps.notify import mailer, rich, templates

    if not user.email:
        raise ResetError("This account has no email address. Add one, or generate a temporary password instead.")
    if not config.get("smtp.enabled"):
        raise ResetError("Email is not configured (Settings → Notifications → Email).")
    if not https_ok():
        raise ResetError("Reset links of an internet-facing installation need the https:// address (PD_PUBLIC_ORIGIN).")
    minutes = int(config.get("auth.reset_token_minutes"))
    token = new_token(user)
    by_admin = actor is not None and actor.pk != user.pk
    msg = rich.Message(
        event="security.password_reset_requested", title=f"{config.get('general.app_name')}: reset your password",
        heading="Reset your password",
        summary=(f"An administrator ({actor.display_name}) sent you this password reset link. " if by_admin else "")
        + f"Use the button within {minutes} minutes to choose a new password.",
        details=[rich.Detail("Account", user.username, "user"), rich.Detail("Link valid for", f"{minutes} minutes", "time"),
                 rich.Detail("Requested by", actor.display_name if by_admin else "you (Forgot password)", "shield"),
                 rich.Detail("Date/time", templates.local_stamp(), "time")],
        secret_link=f"{settings.PUBLIC_ORIGIN}/reset-password?token={token}", secret_label="Reset password",
        context={"recipient_name": user.display_name})
    subject, text, html_doc = rich.render_email(msg, user)
    mailer.send_mail_now(user.email, subject, text, html=html_doc)


def admin_send_reset_email(actor: User, target: User, request=None) -> None:
    from apps.notify.events import notify

    can_reset(actor, target)
    try:
        send_reset_email(target, actor=actor)
    except ResetError:
        audit.record("family.password_reset_email", request=request, outcome="failure", target=target, subject_user=target)
        raise
    except Exception as exc:  # noqa: BLE001 - SMTP problems: report without details that could contain secrets
        audit.record("family.password_reset_email", request=request, outcome="failure", target=target, subject_user=target,
                     reason="smtp_error")
        raise ResetError(f"The email could not be sent ({exc.__class__.__name__}). Check Settings → Notifications → Email.", 502)
    audit.record("family.password_reset_email", request=request, target=target, subject_user=target)
    notify(target, "security.password_admin_reset", key=f"pwreset:{target.pk}:{timezone.now():%Y%m%d%H%M%S%f}",
           title="An administrator started a password reset",
           summary=f"{actor.display_name} sent a password reset link to your email address. Your current password keeps "
                   "working until you choose a new one.",
           facts=[("Account", target.username), ("Changed by", actor.display_name)], kind="security")


def admin_temporary_password(actor: User, target: User, *, request=None) -> str:
    """Returns the plaintext once (for the administrator's screen). Only its hash is stored."""
    from apps.notify.events import notify

    can_reset(actor, target)
    password = S.generate_password(16)
    S.set_password(target, password, temporary=True)  # also invalidates reset tokens and ends every session
    audit.record("family.password_reset_by_admin", request=request, target=target, subject_user=target, method="temporary_password",
                 sessions_revoked=True)
    notify(target, "security.temporary_password", key=f"pwtemp:{target.pk}:{timezone.now():%Y%m%d%H%M%S%f}",
           title="Your password was reset by an administrator",
           summary=f"{actor.display_name} reset your password and is giving you a temporary password through a secure channel "
                   "(in person or another channel you agreed on).",
           facts=[("Account", target.username), ("Changed by", actor.display_name),
                  ("Sessions", "signed out on every device")], kind="security")
    for admin in User.objects.filter(is_active=True).exclude(pk__in=[actor.pk, target.pk]).filter(is_main_admin=True):
        notify(admin, "security.password_admin_reset", key=f"pwtemp-admin:{target.pk}:{admin.pk}:{timezone.now():%Y%m%d%H%M%S%f}",
               title=f"{actor.display_name} reset the password of {target.display_name}",
               summary="A temporary password was issued. The person must choose a new password at the next sign-in.",
               facts=[("Account", target.username), ("Changed by", actor.display_name)], kind="security")
    return password


def password_changed(user: User, *, how: str, request=None) -> None:
    """Completion notice after a reset link, a forced change after a temporary password, or a normal change."""
    from apps.notify.events import notify

    notify(user, "security.password_changed", key=f"pwchanged:{user.pk}:{timezone.now():%Y%m%d%H%M%S%f}",
           title="Your password was changed",
           summary={"reset_link": "Your password was reset with an email link.",
                    "temporary": "You replaced the temporary password with your own.",
                    "change": "Your password was changed in My account."}.get(how, "Your password was changed."),
           facts=[("Account", user.username)], kind="security")
