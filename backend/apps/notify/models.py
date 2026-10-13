from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class Notification(models.Model):
    """In-app feed entry."""

    SEVERITIES = ("critical", "warning", "success", "info")

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=300, blank=True)
    document = models.ForeignKey("library.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    # Change Set O: structured card (rendered from the same event as email / Telegram / push)
    event = models.CharField(max_length=60, blank=True, db_index=True)
    category = models.CharField(max_length=20, blank=True, db_index=True)
    severity = models.CharField(max_length=10, default="info", db_index=True)
    icon = models.CharField(max_length=30, blank=True)
    summary = models.CharField(max_length=500, blank=True)
    data = models.JSONField(default=dict, blank=True, help_text="details and actions of the card")
    is_test = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]


class OutboxMessage(models.Model):
    """External delivery (email/telegram). `key` makes retries and scheduler restarts idempotent."""

    PENDING, SENT, FAILED, SKIPPED = "pending", "sent", "failed", "skipped"
    DIGEST, DIGESTED, FALLBACK = "digest", "digested", "fallback"  # waiting for a digest / sent in one / failed over
    EXPIRED, SUPERSEDED = "expired", "superseded"  # Change Set V: never delivered late after an outage

    key = models.CharField(max_length=250, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    channel = models.CharField(max_length=16)
    kind = models.CharField(max_length=40)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    # Change Set O: rich content (HTML email part, Telegram HTML text + buttons, push payload)
    event = models.CharField(max_length=60, blank=True, db_index=True)
    severity = models.CharField(max_length=10, blank=True)
    html = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    provider_ref = models.CharField(max_length=120, blank=True, help_text="Provider message id when reported")
    is_test = models.BooleanField(default=False)
    document = models.ForeignKey("library.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, default=PENDING, db_index=True)
    # Change Set T: routing. route = direct | primary | fallback | mandatory | digest; hold = quiet_hours | digest
    route = models.CharField(max_length=10, default="direct")
    fallback_chain = models.JSONField(default=list, blank=True, help_text="Channels still to try if this one fails")
    fallback_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="fallbacks")
    hold = models.CharField(max_length=12, blank=True, help_text="Why delivery waits: quiet_hours | digest")
    digest = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="digested",
                               help_text="The digest message this item was delivered in")
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


class PushSubscription(models.Model):
    """A browser / installed-PWA push endpoint of one person (Web Push, VAPID). The endpoint host must be a known
    push service; nothing else is ever contacted."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=60)
    label = models.CharField(max_length=120, blank=True, help_text="Browser / device summary")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)


class NotificationTemplate(models.Model):
    """Administrator presentation overrides for one event (channel "" = every channel). Only plain text with
    allowlisted {placeholders}; never code or HTML. Severity and critical status are not weakened here."""

    event = models.CharField(max_length=60)
    channel = models.CharField(max_length=16, blank=True)
    title = models.CharField(max_length=200, blank=True)
    heading = models.CharField(max_length=200, blank=True)
    summary = models.CharField(max_length=500, blank=True)
    icon = models.CharField(max_length=30, blank=True)
    severity = models.CharField(max_length=10, blank=True)
    action_labels = models.JSONField(default=dict, blank=True)
    brand = models.CharField(max_length=60, blank=True, help_text="Header name in email (default: the application name)")
    footer = models.CharField(max_length=300, blank=True, help_text="Footer / help text")
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("event", "channel")]


class ExpirySnooze(models.Model):
    """A person paused expiry reminders of one document until a date (in-app action, reminders resume after)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    document = models.ForeignKey("library.Document", on_delete=models.CASCADE, related_name="+")
    until = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "document")]


class DiscordWebhook(models.Model):
    """One official Discord webhook per person (Change Set T). The URL contains the secret and is stored encrypted."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="discord_webhook")
    url_enc = models.TextField()
    hint = models.CharField(max_length=40, help_text="Non-secret display form: server/channel id prefix")
    enabled = models.BooleanField(default=True)
    status = models.CharField(max_length=20, default="untested")  # untested | connected | failed | removed_by_discord
    last_error = models.CharField(max_length=200, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class WhatsAppLink(models.Model):
    """A person's own WhatsApp account linked to the self-hosted bridge as a linked device (experimental, unofficial).
    The session credentials live only in the bridge's per-person encrypted store, never in this table."""

    CONNECTED, DISCONNECTED, DEGRADED, RELINK, PENDING = "connected", "disconnected", "degraded", "reconnect_required", "pending"
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="whatsapp_link")
    session = models.CharField(max_length=40, unique=True, help_text="Opaque bridge session id (random, per person)")
    state = models.CharField(max_length=20, default=PENDING)
    number_hint = models.CharField(max_length=20, blank=True, help_text="Last digits of the linked number")
    enabled = models.BooleanField(default=True)
    linked_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    # Change Set V: pairing is only "Linked & Verified" after a real message reached the person's own chat
    verification = models.CharField(max_length=12, blank=True, help_text="verified | pending | failed (empty: not linked)")
    verified_at = models.DateTimeField(null=True, blank=True)
    last_pairing_at = models.DateTimeField(null=True, blank=True)
