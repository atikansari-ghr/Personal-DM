from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class Notification(models.Model):
    """In-app feed entry."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=300, blank=True)
    document = models.ForeignKey("library.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class OutboxMessage(models.Model):
    """External delivery (email/telegram). `key` makes retries and scheduler restarts idempotent."""

    PENDING, SENT, FAILED, SKIPPED = "pending", "sent", "failed", "skipped"

    key = models.CharField(max_length=250, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    channel = models.CharField(max_length=16)
    kind = models.CharField(max_length=40)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    document = models.ForeignKey("library.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, default=PENDING, db_index=True)
    attempts = models.IntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class ExpiryMark(models.Model):
    """Which reminder thresholds have been handled for a document's specific expiry date."""

    document = models.ForeignKey("library.Document", on_delete=models.CASCADE, related_name="expiry_marks")
    expiry_date = models.DateField()
    threshold = models.IntegerField()
    action = models.CharField(max_length=10)  # sent|skipped
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("document", "expiry_date", "threshold")]


class TelegramLink(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="telegram_link")
    chat_id = models.CharField(max_length=40, unique=True)
    username = models.CharField(max_length=80, blank=True)
    linked_at = models.DateTimeField(auto_now_add=True)


class TelegramLinkCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    code_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)


class SchedulerRun(models.Model):
    name = models.CharField(max_length=60, primary_key=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_local_date = models.DateField(null=True, blank=True)
    state = models.JSONField(default=dict, blank=True)
