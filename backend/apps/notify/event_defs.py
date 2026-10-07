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


EVENTS: dict[str, Event] = {e.key: e for e in [
    # account security (the person concerned; administrators too for admin actions)
    Event("security.passkey_added", "New passkey registered", "A passkey was added to your account.", "security", default_critical=True, category="security", severity="warning", icon="key"),
    Event("security.passkey_removed", "Passkey removed", "A passkey was removed from your account.", "security", default_critical=True, category="security", severity="warning", icon="key"),
    Event("security.totp_enabled", "Authenticator app turned on", "Two-step verification with an authenticator app was set up.", "security", default_critical=True, category="security", severity="info", icon="key"),
    Event("security.totp_disabled", "Authenticator app turned off", "Two-step verification with an authenticator app was turned off.", "security", default_critical=True, category="security", severity="warning", icon="key"),
    Event("security.recovery_codes", "Recovery codes regenerated", "New recovery codes were created; the old ones stopped working.", "security", default_critical=True, category="security", severity="warning", icon="key"),
    Event("security.passwordless", "Passwordless sign-in changed", "Signing in with a passkey alone was turned on or off.", "security", default_critical=True, category="security", severity="warning", icon="key"),
    Event("security.admin_recovery", "Two-step verification reset", "An administrator (or the server console) reset two-step verification.", "security", default_critical=True, category="security", severity="critical", icon="shield"),
    Event("security.new_country", "Sign-in from a new country", "Your account signed in from a country it never used before.", "security", default_critical=True, category="security", severity="warning", icon="globe_location"),
    Event("security.new_ip", "Sign-in from a new address", "Your account signed in from a new IP address.", "security", default_channels=("in_app",), category="security", severity="info", icon="globe_location"),
    Event("account.login", "Every sign-in", "Each successful sign-in to your account, with device, address and country.", "security", default_channels=(), category="security", severity="info", icon="key"),
    # administrators
    Event("security.failed_logins", "Repeated failed sign-ins", "Repeated failures and automatic temporary blocks.", "security", admins_only=True, default_critical=True, category="security", severity="critical", icon="alarm"),
    Event("security.authentik", "authentik account linked or unlinked", "Your account was linked to authentik, or a link was removed.", "security", default_critical=True, category="security", severity="warning", icon="key"),
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
