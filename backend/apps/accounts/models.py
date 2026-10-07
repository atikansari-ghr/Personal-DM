import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

DELEGATION_SCOPES = ("documents", "membership", "folder_permissions", "reminders", "notifications")

AVATAR_COLORS = ("#d8eadb", "#f6d5d5", "#d6e4f5", "#e5d9f2", "#f8e7b9", "#cdeee6", "#f3dcc7", "#dfe7c9")


class User(AbstractUser):
    """Every person whose documents are managed has an account (immutable UUID id)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField(max_length=80)
    full_name = models.CharField(max_length=150, blank=True)
    role_label = models.CharField(max_length=40, blank=True, help_text="Relationship label, e.g. Dad, Mom, Son1")
    is_main_admin = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False, help_text="Administrator: security and operations area (antivirus, "
                                   "security tests, storage health). The main administrator always has these rights.")
    must_change_password = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    totp_secret_enc = models.TextField(blank=True)
    totp_enabled = models.BooleanField(default=False)
    totp_pending_enc = models.TextField(blank=True)
    avatar_color = models.CharField(max_length=9, default=AVATAR_COLORS[0])
    photo_name = models.CharField(max_length=40, blank=True, help_text="Random file stem in <data>/profile-photos (private)")
    photo_updated_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.IntegerField(default=100)
    reminder_group = models.ForeignKey("FamilyGroup", null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="reminder_members",
                                       help_text="Group whose head receives this person's expiry reminders")
    session_epoch = models.IntegerField(default=0, help_text="Incremented to invalidate all sessions")
    passwordless_enabled = models.BooleanField(default=False, help_text="Person opted in to passwordless passkey sign-in")

    class Meta:
        ordering = ["sort_order", "display_name"]

    def __str__(self):
        return self.display_name or self.username

    @property
    def is_administrator(self) -> bool:
        """Main administrator or Administrator role. Never grants document/folder access by itself."""
        return bool(self.is_main_admin or self.is_admin)

    @property
    def initials(self) -> str:
        name = (self.display_name or self.username).strip()
        parts = name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return name[:2].upper()


class FamilyGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    head = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="headed_groups")
    sort_order = models.IntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class GroupMembership(models.Model):
    group = models.ForeignKey(FamilyGroup, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("group", "user")]


class Delegation(models.Model):
    """A scoped delegation over one family group. Granted only by the main administrator."""

    delegate = models.ForeignKey(User, on_delete=models.CASCADE, related_name="delegations")
    group = models.ForeignKey(FamilyGroup, on_delete=models.CASCADE, related_name="delegations")
    scopes = models.JSONField(default=list)
    granted_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("delegate", "group")]


class RecoveryCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=128)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reset_tokens")
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def valid(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()


class GoogleIdentity(models.Model):
    """Link between a Google (issuer, subject) and exactly one local account."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="google_identity")
    issuer = models.CharField(max_length=100)
    subject = models.CharField(max_length=255)
    email = models.CharField(max_length=254, blank=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("issuer", "subject")]


class SetupState(models.Model):
    """Singleton tracking the first-run wizard."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    completed_at = models.DateTimeField(null=True, blank=True)
    token_hash = models.CharField(max_length=128, blank=True)
    token_created_at = models.DateTimeField(null=True, blank=True)
    progress = models.JSONField(default=dict, blank=True)

    @classmethod
    def get(cls) -> "SetupState":
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class UserSession(models.Model):
    """One signed-in browser/device. The id is stored inside the Django session as session['device']."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="device_sessions")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    method = models.CharField(max_length=40, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_seen_at"]

    @property
    def active(self) -> bool:
        return self.revoked_at is None and self.ended_at is None


class WebAuthnCredential(models.Model):
    """A registered passkey / security key. Only the public key and verifier state are stored, never private keys."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="passkeys")
    credential_id = models.CharField(max_length=1400, unique=True, help_text="base64url credential id")
    public_key = models.BinaryField()
    sign_count = models.BigIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)
    aaguid = models.CharField(max_length=40, blank=True)
    device_type = models.CharField(max_length=20, blank=True)  # single_device | multi_device (synced)
    backed_up = models.BooleanField(default=False)
    discoverable = models.BooleanField(default=False, help_text="Resident key: usable for passwordless sign-in")
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]


class ExternalIdentity(models.Model):
    """Link between an external OpenID Connect identity (authentik) and one local account.

    Created only by the signed-in person (Profile → Security → Link authentik account) or by automatic provisioning
    when the administrator enabled it. Never created because an email address matches."""

    provider = models.CharField(max_length=30, default="authentik")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="external_identities")
    issuer = models.CharField(max_length=300)
    subject = models.CharField(max_length=255)
    email = models.CharField(max_length=254, blank=True)
    username = models.CharField(max_length=150, blank=True)
    groups = models.JSONField(default=list, blank=True)
    provisioned = models.BooleanField(default=False, help_text="Account was created automatically on first sign-in")
    linked_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("issuer", "subject"), ("provider", "user")]
