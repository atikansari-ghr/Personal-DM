"""Login audit and geographic/IP access policy."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class LoginEvent(models.Model):
    """One authentication event. Never stores passwords, codes, tokens or cookies."""

    SUCCESS, FAILURE, DENIED, LOGOUT = "success", "failure", "denied", "logout"
    RESULTS = [(r, r) for r in (SUCCESS, FAILURE, DENIED, LOGOUT)]

    id = models.BigAutoField(primary_key=True)
    at = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="login_events")
    username = models.CharField(max_length=150, blank=True, help_text="Username as typed (for failures with no account)")
    result = models.CharField(max_length=10, choices=RESULTS, db_index=True)
    method = models.CharField(max_length=40, blank=True, db_index=True)  # password, password+totp, password+passkey, passkey, google, ...
    reason = models.CharField(max_length=40, blank=True)  # failure category: bad_password, bad_code, rate_limited, ...
    ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    country = models.CharField(max_length=2, blank=True, db_index=True)
    country_name = models.CharField(max_length=80, blank=True)
    browser = models.CharField(max_length=40, blank=True)
    os = models.CharField(max_length=40, blank=True)
    device = models.CharField(max_length=10, blank=True)  # desktop|mobile|tablet|bot
    correlation = models.CharField(max_length=64, blank=True, db_index=True)  # device session id
    totp_used = models.BooleanField(default=False)
    passkey_used = models.BooleanField(default=False)
    oidc_used = models.BooleanField(default=False)
    flags = models.JSONField(default=list, blank=True)  # new_ip, new_country, policy_exception, escalated

    class Meta:
        ordering = ["-at"]
        indexes = [models.Index(fields=["user", "-at"]), models.Index(fields=["result", "-at"])]


class GeoPolicy(models.Model):
    """Singleton: geographic access control (enforced before authentication)."""

    OFF, BLOCKLIST, ALLOWLIST = "off", "blocklist", "allowlist"
    MODES = [(m, m) for m in (OFF, BLOCKLIST, ALLOWLIST)]

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=10, choices=MODES, default=OFF)
    unknown_action = models.CharField(max_length=5, default="allow", help_text="allow|deny when the country cannot be determined")
    version = models.PositiveIntegerField(default=0)
    previous = models.JSONField(default=dict, blank=True, help_text="Snapshot before the last change, for rollback")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    @classmethod
    def get(cls) -> "GeoPolicy":
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class CountryRule(models.Model):
    ALLOW, BLOCK = "allow", "block"

    country = models.CharField(max_length=2)
    kind = models.CharField(max_length=5, choices=[(ALLOW, ALLOW), (BLOCK, BLOCK)])
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        unique_together = [("country", "kind")]
        ordering = ["kind", "country"]


class TemporaryCountryAccess(models.Model):
    """Travel exception: allows a country between starts_at and ends_at regardless of the country policy."""

    country = models.CharField(max_length=2)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(db_index=True)
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    expiry_notified = models.BooleanField(default=False)

    class Meta:
        ordering = ["-ends_at"]

    def active(self, now=None) -> bool:
        now = now or timezone.now()
        return self.starts_at <= now < self.ends_at


class IPRule(models.Model):
    TRUSTED, BLOCKED = "trusted", "blocked"

    cidr = models.CharField(max_length=64)
    kind = models.CharField(max_length=7, choices=[(TRUSTED, TRUSTED), (BLOCKED, BLOCKED)], db_index=True)
    description = models.CharField(max_length=200, blank=True)  # reason for blocked entries
    enabled = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    automatic = models.BooleanField(default=False, help_text="Created by failed-login escalation")

    class Meta:
        ordering = ["kind", "cidr"]

    def live(self, now=None) -> bool:
        now = now or timezone.now()
        return self.enabled and (self.expires_at is None or self.expires_at > now)


class BlockedStat(models.Model):
    """Daily count of requests refused by the access policy (shown in Traffic Analytics)."""

    day = models.DateField(db_index=True)
    reason = models.CharField(max_length=30)
    country = models.CharField(max_length=2, blank=True)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("day", "reason", "country")]
