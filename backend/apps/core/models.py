import uuid

from django.conf import settings
from django.db import models


class AppSetting(models.Model):
    """Global setting values. Definitions live in apps.core.registry."""

    key = models.CharField(max_length=120, primary_key=True)
    value = models.JSONField(null=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)


class UserSetting(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="setting_values")
    key = models.CharField(max_length=120)
    value = models.JSONField(null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "key")]


class AuditEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor_label = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=80, db_index=True)
    outcome = models.CharField(max_length=20, default="success")  # success|failure|denied
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=64, blank=True, db_index=True)
    # Subject user the event concerns (e.g. document owner) so per-user audit views can be filtered.
    subject_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    ip = models.GenericIPAddressField(null=True, blank=True)
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-at"]


class Job(models.Model):
    QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"
    STATUS = [(s, s) for s in (QUEUED, RUNNING, DONE, FAILED, CANCELLED)]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    kind = models.CharField(max_length=60, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=12, choices=STATUS, default=QUEUED, db_index=True)
    heavy = models.BooleanField(default=False)  # OCR/conversion jobs share a smaller concurrency budget
    priority = models.IntegerField(default=100)
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    run_after = models.DateTimeField(db_index=True)
    locked_by = models.CharField(max_length=80, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=200, null=True, blank=True, unique=True)
    last_error = models.TextField(blank=True)
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "run_after", "priority"])]


class RateLimitHit(models.Model):
    bucket = models.CharField(max_length=200, db_index=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)
