from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class EmailAccount(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_accounts")
    label = models.CharField(max_length=80)
    host = models.CharField(max_length=200)
    port = models.IntegerField(default=993)
    security = models.CharField(max_length=10, default="ssl")  # ssl|starttls
    username = models.CharField(max_length=200)
    password_enc = models.TextField()
    mailbox = models.CharField(max_length=200, default="INBOX")
    poll_minutes = models.IntegerField(default=30)
    enabled = models.BooleanField(default=True)
    disabled_by_admin = models.BooleanField(default=False)
    last_poll_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    uidvalidity = models.CharField(max_length=40, blank=True)
    last_uid = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class EmailRule(models.Model):
    account = models.ForeignKey(EmailAccount, on_delete=models.CASCADE, related_name="rules")
    name = models.CharField(max_length=80)
    sender_contains = models.CharField(max_length=200, blank=True)
    subject_contains = models.CharField(max_length=200, blank=True)
    extensions = models.CharField(max_length=200, default="pdf,jpg,jpeg,png")
    max_mb = models.IntegerField(default=25)
    destination = models.ForeignKey("library.Folder", on_delete=models.CASCADE, related_name="+")
    enabled = models.BooleanField(default=True)
    order = models.IntegerField(default=100)

    class Meta:
        ordering = ["order", "id"]


class ImportedAttachment(models.Model):
    """Identity of an imported attachment so repeated polls are idempotent."""

    account = models.ForeignKey(EmailAccount, on_delete=models.CASCADE, related_name="imported")
    uidvalidity = models.CharField(max_length=40)
    uid = models.BigIntegerField()
    part_index = models.IntegerField()
    filename = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=10, default="done")  # done|failed|skipped
    error = models.CharField(max_length=300, blank=True)
    document = models.ForeignKey("library.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    rule = models.ForeignKey(EmailRule, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("account", "uidvalidity", "uid", "part_index")]
