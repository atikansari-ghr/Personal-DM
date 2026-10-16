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


class HolidayOverride(models.Model):
    """An administrator's correction to the holiday library: confirm or rename a calculated date, add a holiday the
    library lacks, or hide one that does not apply. Library data itself is never edited."""

    CONFIRMED, PROVISIONAL = "confirmed", "provisional"
    STATUS = [(CONFIRMED, "Confirmed"), (PROVISIONAL, "Provisional")]

    country = models.CharField(max_length=3)
    date = models.DateField()
    name = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default=CONFIRMED)
    hidden = models.BooleanField(default=False, help_text="Hide the library holidays of this country on this date")
    source = models.CharField(max_length=200, blank=True, help_text="Where the correction comes from, e.g. an official announcement")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("country", "date")]
        ordering = ["date"]


class WeatherCache(models.Model):
    """Last successful weather response per location, shared by all workers so the provider is asked rarely."""

    key = models.CharField(max_length=120, primary_key=True)
    data = models.JSONField(default=dict)
    fetched_at = models.DateTimeField()


class SigninDesign(models.Model):
    """A named sign-in page design (Change Set W).

    Built-in designs (``builtin_key`` set) are protected templates: they can be activated and duplicated, never
    edited or deleted. Custom designs keep their own wallpaper (original plus Desktop/Tablet/Mobile derivatives),
    optional logo, focal point, colour mode and palette. Exactly one design is active (setting ``login.active_design``).
    Asset file names live in ``assets``; files are shared between designs after Duplicate and only removed when no
    saved design (and no legacy setting) refers to them.
    """

    AUTO, LIGHT, DARK, CUSTOM = "auto", "light", "dark", "custom"
    COLOR_MODES = (AUTO, LIGHT, DARK, CUSTOM)
    OK, UNAVAILABLE = "ok", "unavailable"

    name = models.CharField(max_length=80)
    builtin_key = models.CharField(max_length=20, unique=True, null=True, blank=True)
    template = models.CharField(max_length=20, default="minimal", help_text="Built-in artwork shown without a wallpaper")
    assets = models.JSONField(default=dict, blank=True, help_text="{original, desktop, tablet, mobile, logo}: file names")
    focal_x = models.FloatField(default=0.5)
    focal_y = models.FloatField(default=0.5)
    overlay = models.IntegerField(default=0)
    color_mode = models.CharField(max_length=8, default=AUTO)
    analysis = models.JSONField(default=dict, blank=True, help_text="Auto colour analysis of the wallpaper")
    overrides = models.JSONField(default=dict, blank=True, help_text="Palette values chosen by the administrator")
    palette = models.JSONField(default=dict, blank=True, help_text="Final palette used on the sign-in page")
    state = models.CharField(max_length=12, default=OK)
    state_detail = models.CharField(max_length=300, blank=True)
    migrated_from = models.CharField(max_length=40, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["builtin_key", "name", "id"]

    @property
    def builtin(self) -> bool:
        return bool(self.builtin_key)


class PerfBucket(models.Model):
    """Change Set X: aggregated performance measurements in 10-minute buckets (Admin → Performance).

    kind: "api" (a request route such as "documents/<uuid:pk>", never a URL with identifiers), "job" (a background job
    kind), "client" (loading errors reported by browsers) or "system" (CPU, memory, swap, I/O, queue, connections).
    Holds counts and timings only: no request contents, document data, names or secrets."""

    bucket = models.DateTimeField(db_index=True)
    kind = models.CharField(max_length=10)
    name = models.CharField(max_length=120)
    count = models.IntegerField(default=0)
    total_ms = models.FloatField(default=0)
    max_ms = models.FloatField(default=0)
    queries = models.BigIntegerField(default=0)
    db_ms = models.FloatField(default=0)
    errors = models.IntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bucket", "kind", "name"], name="perf_bucket_uniq")]


class PerfEvent(models.Model):
    """Notable performance events: slow requests, throttling started/ended, warnings. No private data."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    kind = models.CharField(max_length=30)
    message = models.CharField(max_length=300)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-at"]
