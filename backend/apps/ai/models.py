"""Local AI: connection profiles, tracked jobs, reviewable suggestions and semantic-search chunks."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone


class AIProfile(models.Model):
    OPENAI, OLLAMA = "openai", "ollama"
    PROVIDERS = [(OPENAI, "OpenAI-compatible (LM Studio, llama.cpp, vLLM, LocalAI)"), (OLLAMA, "Ollama")]
    LOCAL, LAN, EXTERNAL = "local", "lan", "external"
    PRIVACY = [(LOCAL, "Local only (this server)"), (LAN, "Private LAN"), (EXTERNAL, "External endpoint")]

    name = models.CharField(max_length=80, unique=True)
    enabled = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    provider = models.CharField(max_length=10, choices=PROVIDERS, default=OPENAI)
    base_url = models.CharField(max_length=300)
    api_key_enc = models.TextField(blank=True)
    text_model = models.CharField(max_length=200, blank=True)
    vision_model = models.CharField(max_length=200, blank=True)
    embedding_model = models.CharField(max_length=200, blank=True)
    timeout_seconds = models.PositiveIntegerField(default=60)
    max_input_chars = models.PositiveIntegerField(default=12000)
    max_output_tokens = models.PositiveIntegerField(default=800)
    privacy = models.CharField(max_length=10, choices=PRIVACY, default=LAN)
    external_acknowledged = models.BooleanField(default=False)
    features = models.JSONField(default=list, blank=True, help_text="Features this profile may serve (empty = all enabled)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-is_default", "name"]


class AIJob(models.Model):
    """Visible to administrators without document content: what ran, for whom, on which model, and how it ended."""

    QUEUED, RUNNING, DONE, FAILED, SKIPPED = "queued", "running", "done", "failed", "skipped"
    ANALYZE, EMBED, ASSISTANT, TEST = "analyze", "embed", "assistant", "test"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=12, db_index=True)
    document = models.ForeignKey("library.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    profile = models.ForeignKey(AIProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs")
    model = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, default=QUEUED, db_index=True)
    error_category = models.CharField(max_length=30, blank=True)  # unavailable|timeout|bad_response|model_missing|privacy|disabled|other
    error = models.CharField(max_length=300, blank=True)  # safe message, never prompt/response content
    attempts = models.PositiveIntegerField(default=0)
    retryable = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]


class AISuggestion(models.Model):
    """A proposed metadata change. Nothing is applied until a person with edit rights accepts it."""

    PENDING, ACCEPTED, DISMISSED = "pending", "accepted", "dismissed"
    FIELDS = ("title", "doc_type", "correspondent", "tags", "folder", "issue_date", "expiry_date", "document_number", "summary")

    document = models.ForeignKey("library.Document", on_delete=models.CASCADE, related_name="ai_suggestions")
    field = models.CharField(max_length=40)
    value = models.JSONField()
    display = models.CharField(max_length=300)
    current = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, default=PENDING, db_index=True)
    job = models.ForeignKey(AIJob, null=True, blank=True, on_delete=models.SET_NULL, related_name="suggestions")
    created_at = models.DateTimeField(default=timezone.now)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["field", "-created_at"]


class DocumentChunk(models.Model):
    """Embedding of a slice of a document's text (semantic search). Always filtered by permissions at query time."""

    document = models.ForeignKey("library.Document", on_delete=models.CASCADE, related_name="ai_chunks")
    version = models.ForeignKey("library.DocumentVersion", on_delete=models.CASCADE, related_name="+")
    idx = models.PositiveIntegerField()
    text = models.TextField()
    vector = ArrayField(models.FloatField())
    model = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("version", "idx", "model")]
