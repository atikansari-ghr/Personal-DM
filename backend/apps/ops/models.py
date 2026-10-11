"""Backup & Recovery (Change Set T): encrypted full-system recovery points, destinations, policies and restores.

Terminology used everywhere (UI, docs, API):
* **Recovery point** - one Full or Incremental backup of the whole application (database, documents and versions,
  OCR data, settings, encrypted secrets). Scope is always the full system; granularity belongs to restore.
* **Copy** - the encrypted package of a recovery point on one destination. Each copy has its own state.
* **Recovery Key** - the single key (per generation) that decrypts every retained recovery point of that generation.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class RecoveryKey(models.Model):
    """One generation of the Backup Recovery Key. The key is stored encrypted with the installation key (never as
    plain text). A generation stays usable until no retained copy references it."""

    ACTIVE, PENDING, RETIRING, RETIRED = "active", "pending", "retiring", "retired"
    generation = models.PositiveIntegerField(primary_key=True)
    key_enc = models.TextField(help_text="Recovery Key encrypted with the installation key (apps.core.crypto)")
    fingerprint = models.CharField(max_length=16, help_text="Short non-secret identifier shown in the UI")
    state = models.CharField(max_length=10, default=ACTIVE, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-generation"]


class EmergencyExport(models.Model):
    """Readiness metadata only: that an Emergency Recovery Package was exported, when and for which generation.
    Where the person keeps it is never recorded."""

    id = models.BigAutoField(primary_key=True)
    generation = models.PositiveIntegerField(db_index=True)
    exported_at = models.DateTimeField(default=timezone.now)
    exported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-exported_at"]


class BackupDestination(models.Model):
    LOCAL, NAS, S3, GDRIVE, ONEDRIVE = "local", "nas", "s3", "gdrive", "onedrive"
    KINDS = (LOCAL, NAS, S3, GDRIVE, ONEDRIVE)
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=10)
    config = models.JSONField(default=dict, blank=True, help_text="Non-secret settings (path, bucket, endpoint, folder id)")
    secret_enc = models.TextField(blank=True, help_text="Encrypted JSON with credentials (never returned by the API)")
    enabled = models.BooleanField(default=True)
    # last known health (Healthy / Destination Unavailable / Authentication Required / Insufficient Storage ...)
    health = models.CharField(max_length=24, default="unknown")
    health_detail = models.CharField(max_length=300, blank=True)
    free_bytes = models.BigIntegerField(null=True, blank=True)
    total_bytes = models.BigIntegerField(null=True, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]


class BackupPolicy(models.Model):
    """When full and incremental recovery points are made and where they go. Scope is always the full system."""

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    enabled = models.BooleanField(default=True)
    full_frequency = models.CharField(max_length=8, default="weekly")  # daily | weekly | monthly
    full_weekday = models.CharField(max_length=3, default="sun")
    full_month_day = models.PositiveSmallIntegerField(default=1)
    full_time = models.CharField(max_length=5, default="02:30")
    incremental_hours = models.PositiveSmallIntegerField(default=4, help_text="0 = no incrementals")
    retention_weeks = models.PositiveSmallIntegerField(default=4, help_text="Full backups are kept this many weeks")
    destinations = models.ManyToManyField(BackupDestination, related_name="policies", blank=True)
    verify_deep = models.BooleanField(default=True)
    notify_success = models.BooleanField(default=False)
    validation_days = models.PositiveSmallIntegerField(default=0, help_text="Automated recovery validation every N days (0 = off)")
    last_full_at = models.DateTimeField(null=True, blank=True)
    last_incremental_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]


class RecoveryPoint(models.Model):
    FULL, INCREMENTAL = "full", "incremental"
    RUNNING, VERIFIED, PARTIAL, WARNING, FAILED, DELETED = "running", "verified", "partial", "warning", "failed", "deleted"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(BackupPolicy, null=True, blank=True, on_delete=models.SET_NULL, related_name="points")
    kind = models.CharField(max_length=12)
    trigger = models.CharField(max_length=20, default="scheduled")  # scheduled | manual | pre_change | rotation
    reason = models.CharField(max_length=200, blank=True)
    base = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="chain_points",
                             help_text="The Full backup this incremental depends on")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children",
                               help_text="The previous point of the chain")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, default=RUNNING, db_index=True)
    key_generation = models.PositiveIntegerField()
    app_version = models.CharField(max_length=20, blank=True)
    schema = models.JSONField(default=dict, blank=True, help_text="Latest applied migration per app")
    size_bytes = models.BigIntegerField(default=0)
    stored = models.JSONField(default=dict, blank=True, help_text="Encrypted objects stored in THIS point: name -> plain sha256")
    counts = models.JSONField(default=dict, blank=True, help_text="Inventory counts (users, folders, documents, versions ...)")
    verification = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def chain(self) -> list["RecoveryPoint"]:
        """Base Full first, this point last."""
        out = []
        p = self
        while p is not None and len(out) < 1000:
            out.append(p)
            p = p.parent
        return list(reversed(out))


class RecoveryCopy(models.Model):
    STORED_VERIFIED, STORED_WARNING, FAILED, RETRY_PENDING = "stored_verified", "stored_warning", "failed", "retry_pending"
    AUTH_REQUIRED, UNAVAILABLE, INSUFFICIENT, UPLOADING, DELETED = "auth_required", "unavailable", "insufficient_storage", "uploading", "deleted"
    LABELS = {STORED_VERIFIED: "Stored & Verified", STORED_WARNING: "Stored, Verification Warning", FAILED: "Failed",
              RETRY_PENDING: "Retry Pending", AUTH_REQUIRED: "Authentication Required", UNAVAILABLE: "Destination Unavailable",
              INSUFFICIENT: "Insufficient Storage", UPLOADING: "Uploading", DELETED: "Deleted"}
    id = models.BigAutoField(primary_key=True)
    point = models.ForeignKey(RecoveryPoint, on_delete=models.CASCADE, related_name="copies")
    destination = models.ForeignKey(BackupDestination, on_delete=models.CASCADE, related_name="copies")
    generation = models.PositiveIntegerField()
    state = models.CharField(max_length=24, default=UPLOADING, db_index=True)
    detail = models.CharField(max_length=500, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    bytes = models.BigIntegerField(default=0)
    stored_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("point", "destination")]
        ordering = ["destination__name"]


class KeyRotation(models.Model):
    RUNNING, COMPLETE, PARTIAL, FAILED = "running", "complete", "partial", "failed"
    id = models.BigAutoField(primary_key=True)
    from_generation = models.PositiveIntegerField()
    to_generation = models.PositiveIntegerField()
    status = models.CharField(max_length=10, default=RUNNING)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    results = models.JSONField(default=list, blank=True, help_text="[{point, destination, state, detail}]")
    checkpoint = models.ForeignKey(RecoveryPoint, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-started_at"]


class RestoreRun(models.Model):
    """A restore (granular, test, full system or validation) with its impact analysis and report."""

    KINDS = ("version", "document", "folder", "user", "full", "test", "validation")
    MODES = ("keep_new", "replace", "skip")
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=12)
    mode = models.CharField(max_length=10, default="keep_new")
    recovery_mode = models.CharField(max_length=12, blank=True, help_text="normal | compromise (full system only)")
    point = models.ForeignKey(RecoveryPoint, null=True, blank=True, on_delete=models.SET_NULL, related_name="restores")
    point_label = models.CharField(max_length=120, blank=True)
    target = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, default="analyzed")  # analyzed | running | completed | failed | partial
    impact = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    report = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor_label = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
