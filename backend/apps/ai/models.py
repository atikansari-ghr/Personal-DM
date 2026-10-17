"""Local AI: connection profiles, tracked jobs, reviewable suggestions and semantic-search chunks."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone


class AIProfile(models.Model):
    OPENAI, OLLAMA = "openai", "ollama"
    # Change Set Z: cloud providers (always Cloud: external endpoint, explicit acknowledgement, per-category send controls)
    OPENAI_CLOUD, ANTHROPIC, GEMINI, OPENROUTER = "openai_cloud", "anthropic", "gemini", "openrouter"
    PROVIDERS = [(OPENAI, "Local LLM — OpenAI-compatible (LM Studio, llama.cpp, vLLM, LocalAI)"), (OLLAMA, "Local LLM — Ollama"),
                 (OPENAI_CLOUD, "OpenAI"), (ANTHROPIC, "Anthropic Claude"), (GEMINI, "Google Gemini"), (OPENROUTER, "OpenRouter")]
    CLOUD_PROVIDERS = (OPENAI_CLOUD, ANTHROPIC, GEMINI, OPENROUTER)
    LOCAL, LAN, EXTERNAL = "local", "lan", "external"
    PRIVACY = [(LOCAL, "Local only (this server)"), (LAN, "Private LAN"), (EXTERNAL, "External endpoint")]
    LOC_LOCAL, LOC_CLOUD = "local", "cloud"

    name = models.CharField(max_length=80, unique=True)
    enabled = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    provider = models.CharField(max_length=20, choices=PROVIDERS, default=OPENAI)
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
    # Change Set Y: what this server was seen to support (e.g. {"structured_output": "unsupported"}); cleared when the
    # server URL, provider or text model changes
    capabilities = models.JSONField(default=dict, blank=True)
    # Change Set Z: every profile is explicitly Local or Cloud (Cloud = a cloud provider or an external endpoint).
    # A Cloud profile only receives the data categories switched on here; original images and files are off by default.
    location = models.CharField(max_length=10, default=LOC_LOCAL)
    cloud_send_ocr_text = models.BooleanField(default=False)
    cloud_send_metadata = models.BooleanField(default=False)
    cloud_send_images = models.BooleanField(default=False)
    cloud_send_files = models.BooleanField(default=False)
    last_test = models.JSONField(default=dict, blank=True)  # {at, ok, kind, steps: [{step, ok}], latency_ms} — checks actually run
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-is_default", "name"]

    @property
    def is_cloud(self) -> bool:
        return self.location == self.LOC_CLOUD or self.provider in self.CLOUD_PROVIDERS or self.privacy == self.EXTERNAL


class AIJob(models.Model):
    """Visible to administrators without document content: what ran, for whom, on which model, and how it ended."""

    QUEUED, RUNNING, DONE, FAILED, SKIPPED, CANCELLED = "queued", "running", "done", "failed", "skipped", "cancelled"
    ANALYZE, EMBED, ASSISTANT, TEST = "analyze", "embed", "assistant", "test"
    # Change Set Z: AI Actions in Document Details
    EXTRACT, VERIFY, SUMMARIZE, ASK, SUGGEST_TYPE, FILENAME, EXPIRY = (
        "extract", "verify", "summarize", "ask", "suggest_type", "filename", "expiry")
    ACTIONS = (ANALYZE, EXTRACT, VERIFY, SUMMARIZE, ASK, SUGGEST_TYPE, FILENAME, EXPIRY)

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
    # Change Set Y: where the job is (queued, preparing, ocr_queued, ocr_running, validating_ocr, ai_running,
    # validating_ai, saving, done) or where it failed; safe facts only (engine, counts, HTTP status, sanitized
    # server message) — never document text
    stage = models.CharField(max_length=20, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    # Change Set Z provenance: what actually ran (kept when the profile is later renamed or deleted), where, and which
    # data categories were sent (ocr_text, metadata, image, file) — never the content itself, keys or tokens
    trigger = models.CharField(max_length=10, blank=True)  # manual | auto | smart
    profile_name = models.CharField(max_length=80, blank=True)
    provider = models.CharField(max_length=20, blank=True)
    location = models.CharField(max_length=10, blank=True)  # local | cloud
    data_sent = models.JSONField(default=list, blank=True)
    usage = models.JSONField(default=dict, blank=True)  # {input_tokens, output_tokens} when the provider reports them
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
    # Change Set Z: observed (printed in the text) or inferred; the AI's own confidence (never combined with OCR
    # confidence); conflict = it differs from a value a person confirmed (accepting needs an explicit confirmation)
    evidence = models.CharField(max_length=10, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    conflict = models.BooleanField(default=False)

    class Meta:
        ordering = ["field", "-created_at"]


class AIOutput(models.Model):
    """Change Set Z: a disposable AI result shown in Document Details — summary, OCR verification flags, expiry analysis,
    an Ask AI answer. Labelled AI-generated; never changes the document, its OCR or confirmed metadata. Authorized people
    may delete it; the AIJob (audit record) stays."""

    SUMMARY, VERIFY, EXPIRY, ANSWER = "summary", "verify", "expiry", "answer"

    document = models.ForeignKey("library.Document", on_delete=models.CASCADE, related_name="ai_outputs")
    job = models.ForeignKey(AIJob, null=True, blank=True, on_delete=models.SET_NULL, related_name="outputs")
    kind = models.CharField(max_length=10)
    content = models.JSONField(default=dict)
    question = models.CharField(max_length=1000, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]


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
