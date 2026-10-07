"""Notification event definitions (no imports from the rest of the app, so the settings registry can use them)."""
from __future__ import annotations

from dataclasses import dataclass

CHANNELS = ("in_app", "email", "telegram", "push")
CATEGORIES = ("documents", "expiry", "ocr", "security", "system", "sharing")
SEVERITIES = ("critical", "warning", "success", "info")


@dataclass(frozen=True)
class Event:
    key: str
    label: str
    description: str
    group: str  # security | documents | system
    admins_only: bool = False
    default_critical: bool = False
    default_channels: tuple = ("in_app",)
    always_critical: bool = False  # cannot be removed from the critical list (antivirus and security-health events)
    category: str = "system"  # documents | expiry | ocr | security | system | sharing
    severity: str = "info"  # default; a call may raise it (critical events are never shown below "warning")
    icon: str = "info"  # semantic icon key (apps.notify.icons)
    mandatory: tuple = ()  # protected security warnings: always shown, a template cannot remove or change them


NOT_YOU = "If this was not you, change your password and sign out other devices in My account → Security, and tell the family administrator."
NO_SECRETS = "This message never contains a password, code or reset token, and the administrators will never ask you for one."

EVENTS: dict[str, Event] = {e.key: e for e in [
    # passwords (Change Set P)
    Event("security.password_reset_requested", "Password reset requested", "A password reset link was sent to your email address (by you or an administrator).", "security", default_critical=True, default_channels=("in_app", "email"), category="security", severity="warning", icon="key",
          mandatory=("If you did not ask for a password reset, ignore the link — your password stays the same — and tell the family administrator.", "The reset link works once and expires soon. Never forward it.")),
    Event("security.password_admin_reset", "Administrator reset your password", "An administrator started a password reset for your account.", "security", default_critical=True, default_channels=("in_app", "email"), category="security", severity="warning", icon="shield",
          mandatory=("If you did not expect this, contact the family administrator.", NO_SECRETS)),
    Event("security.temporary_password", "Temporary password issued", "An administrator reset your password and gave you a temporary password through a secure channel.", "security", default_critical=True, default_channels=("in_app", "email"), category="security", severity="warning", icon="key",
          mandatory=("The temporary password is never sent in this message. You must choose a new password when you next sign in.", "Your other devices were signed out. If you did not expect this, contact the family administrator immediately.")),
    Event("security.password_changed", "Password reset completed", "The password of your account was changed or reset.", "security", default_critical=True, default_channels=("in_app", "email"), category="security", severity="success", icon="success",
          mandatory=("If you did not change your password, contact the family administrator immediately.",)),
    Event("security.account_locked", "Account locked", "Sign-in to an account was paused after repeated failed attempts.", "security", default_critical=True, default_channels=("in_app", "email"), category="security", severity="critical", icon="alarm",
          mandatory=("Sign-in for this account is paused for a few minutes after repeated failed attempts. If this was not you, someone may be guessing the password: change it and turn on a passkey or authenticator app.",)),
    # account security (the person concerned; administrators too for admin actions)
    Event("security.passkey_added", "New passkey registered", "A passkey was added to your account.", "security", default_critical=True, category="security", severity="warning", icon="key", mandatory=(NOT_YOU,)),
    Event("security.passkey_removed", "Passkey removed", "A passkey was removed from your account.", "security", default_critical=True, category="security", severity="warning", icon="key", mandatory=(NOT_YOU,)),
    Event("security.totp_enabled", "Authenticator app turned on", "Two-step verification with an authenticator app was set up.", "security", default_critical=True, category="security", severity="info", icon="key", mandatory=(NOT_YOU,)),
    Event("security.totp_disabled", "Authenticator app turned off", "Two-step verification with an authenticator app was turned off.", "security", default_critical=True, category="security", severity="warning", icon="key", mandatory=(NOT_YOU,)),
    Event("security.recovery_codes", "Recovery codes regenerated", "New recovery codes were created; the old ones stopped working.", "security", default_critical=True, category="security", severity="warning", icon="key", mandatory=(NOT_YOU,)),
    Event("security.passwordless", "Passwordless sign-in changed", "Signing in with a passkey alone was turned on or off.", "security", default_critical=True, category="security", severity="warning", icon="key", mandatory=(NOT_YOU,)),
    Event("security.admin_recovery", "Two-step verification reset", "An administrator (or the server console) reset two-step verification.", "security", default_critical=True, category="security", severity="critical", icon="shield", mandatory=(NOT_YOU,)),
    Event("security.new_country", "Unusual sign-in (new country)", "Your account signed in from a country it never used before.", "security", default_critical=True, category="security", severity="warning", icon="globe_location", mandatory=(NOT_YOU,)),
    Event("security.new_ip", "Sign-in from a new address", "Your account signed in from a new IP address.", "security", default_channels=("in_app",), category="security", severity="info", icon="globe_location", mandatory=(NOT_YOU,)),
    Event("account.login", "New sign-in", "Each successful sign-in to your account, with device, address and country.", "security", default_channels=(), category="security", severity="info", icon="key", mandatory=(NOT_YOU,)),
    # administrators
    Event("security.failed_logins", "Repeated failed sign-ins", "Repeated failures and automatic temporary blocks.", "security", admins_only=True, default_critical=True, category="security", severity="critical", icon="alarm"),
    Event("security.authentik", "authentik account linked or removed", "Your account was linked to authentik, or a link was removed.", "security", default_critical=True, category="security", severity="warning", icon="key",
          mandatory=("If you did not link or remove this sign-in, remove the link in My account and contact the family administrator.",)),
    Event("security.google", "Google account linked or removed", "Your account was linked to a Google account, or the link was removed.", "security", default_critical=True, category="security", severity="warning", icon="key",
          mandatory=("If you did not link or remove this sign-in, remove the link in My account and contact the family administrator.",)),
    Event("security.policy_exception", "Sign-in via temporary country access", "A sign-in only possible because of a travel exception.", "security", admins_only=True, default_critical=True, category="security", severity="warning", icon="globe_location"),
    Event("security.policy_change", "Access policy changes", "Country policy, trusted/blocked IPs and temporary access created, changed or expired.", "security", admins_only=True, default_critical=True, category="security", severity="warning", icon="shield"),
    Event("security.auth_policy", "Authentication policy changes", "Changes to sign-in, two-step verification and passkey settings.", "security", admins_only=True, default_critical=True, category="security", severity="warning", icon="shield"),
    Event("security.health", "GeoIP / traffic report problems", "A GeoIP update or traffic report failed.", "system", admins_only=True, default_channels=("in_app", "email"), category="system", severity="warning", icon="warning"),
    # antivirus and security operations: always critical, administrators only
    Event("antivirus.threat", "Malware detected and quarantined", "ClamAV detected a threat in an uploaded file; it was quarantined.", "security", admins_only=True, default_critical=True, always_critical=True, category="security", severity="critical", icon="alarm"),
    Event("antivirus.released", "Quarantined file released", "The main administrator released a file from quarantine.", "security", admins_only=True, default_critical=True, always_critical=True, category="security", severity="critical", icon="shield"),
    Event("antivirus.unavailable", "Antivirus unavailable or scan failed", "ClamAV could not be reached or a scan failed; files stay usable but are marked Not scanned.", "security", admins_only=True, default_critical=True, always_critical=True, category="security", severity="critical", icon="alarm"),
    Event("antivirus.definitions", "Antivirus definitions stale or update failed", "Virus signatures are out of date or the signature update failed.", "security", admins_only=True, default_critical=True, always_critical=True, category="security", severity="warning", icon="shield"),
    Event("security.operations", "Security operations", "OS security updates, reboots, security-test results with Critical/High findings, storage warnings and log purges.", "security", admins_only=True, default_critical=True, category="system", severity="warning", icon="system"),
    Event("backup.failed", "Backup failed", "The scheduled or manual backup did not complete.", "system", admins_only=True, default_critical=True, category="system", severity="critical", icon="backup"),
    Event("integrity.failed", "Integrity problems", "The storage integrity check found missing or changed files.", "system", admins_only=True, default_critical=True, category="system", severity="critical", icon="storage"),
    # documents
    Event("expiry.reminder", "Expiry reminders", "Reminders before a confirmed expiry date (90/60/30/7/0 days by default).", "documents", category="expiry", severity="warning", icon="calendar"),
    Event("document.added", "Documents added", "Documents added to your folders by someone else or by an import (one summary per action).", "documents", default_channels=("in_app", "email"), category="documents", severity="success", icon="upload"),
    Event("document.archived", "Documents archived or deleted", "Your documents were archived (restorable) or permanently deleted by someone else.", "documents", default_channels=("in_app", "email"), category="documents", severity="info", icon="document"),
    Event("document.shared", "Access given to you", "Someone gave you access to a folder or document.", "documents", default_channels=("in_app", "email"), category="sharing", severity="info", icon="user"),
    Event("document.changed", "Your documents changed by someone else", "Someone else moved, restored, re-typed or confirmed the details of your documents.", "documents", default_channels=("in_app",), category="documents", severity="info", icon="document"),
    Event("import.finished", "Import finished", "A folder import finished (summary with a link to the report).", "documents", default_channels=("in_app", "email"), category="documents", severity="success", icon="folder"),
    Event("processing.completed", "OCR / processing finished", "A document you uploaded is processed and searchable.", "documents", default_channels=(), category="ocr", severity="success", icon="scan"),
    Event("processing.failed", "OCR / processing failed", "A document you uploaded could not be processed (the original is safe).", "documents", default_channels=("in_app", "email"), category="ocr", severity="warning", icon="failure"),
]}

DEFAULT_CRITICAL = [k for k, e in EVENTS.items() if e.default_critical]
LABELS = {k: e.label for k, e in EVENTS.items()}
