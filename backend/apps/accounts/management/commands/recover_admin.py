"""Privileged console recovery for the main administrator. Requires shell access to the LXC."""
import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts import services as S
from apps.accounts.models import User
from apps.core import audit


class Command(BaseCommand):
    help = "Reset a main administrator's password (and optionally authenticator) from the server console."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--reset-totp", action="store_true", help="Also remove the authenticator app and recovery codes")
        parser.add_argument("--reset-2fa", action="store_true", help="Remove authenticator app, ALL passkeys and recovery codes (lost devices)")
        parser.add_argument("--generate", action="store_true", help="Generate a temporary password instead of prompting")
        parser.add_argument("--make-admin", action="store_true", help="Grant main administrator to this account (if none remain)")

    def handle(self, *args, username, reset_totp, generate, make_admin, reset_2fa=False, **opts):
        user = User.objects.filter(username=username.lower()).first()
        if user is None:
            raise CommandError("No such account.")
        if not user.is_main_admin:
            if make_admin and not S.active_main_admins().exists():
                user.is_main_admin = True
            else:
                raise CommandError("Console recovery is limited to main administrator accounts (use --make-admin only when no active main administrator exists).")
        if generate:
            password, temporary = S.generate_password(), True
        else:
            password = getpass.getpass("New password: ")
            if password != getpass.getpass("Repeat: "):
                raise CommandError("Passwords differ.")
            temporary = False
        with transaction.atomic():
            user.is_active = True
            user.save()
            try:
                S.set_password(user, password, temporary=temporary)
            except S.AccountError as exc:
                raise CommandError(str(exc))
            if reset_totp or reset_2fa:
                S.totp_disable(user)
            revoked = 0
            if reset_2fa:
                from django.utils import timezone

                from apps.accounts.passkeys import active

                revoked = active(user).update(revoked_at=timezone.now())
                user.passwordless_enabled = False
                user.save(update_fields=["passwordless_enabled"])
            audit.record("recovery.console_admin", actor=None, actor_label="console", target=user, subject_user=user,
                         reset_totp=reset_totp or reset_2fa, passkeys_revoked=revoked)
        if reset_2fa:
            from apps.security import alerts

            alerts.account_security(user, "Two-step verification was reset from the server console")
        self.stdout.write(self.style.SUCCESS(f"Password reset for {user.username}; all of their sessions were signed out."))
        if generate:
            self.stdout.write(f"Temporary password (change at next sign-in): {password}")
