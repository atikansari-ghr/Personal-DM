import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q

User = settings.AUTH_USER_MODEL


class Folder(models.Model):
    PERSONAL_ROOT, SHARED, NORMAL = "personal_root", "shared", "normal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    name = models.CharField(max_length=200)
    emoji = models.CharField(max_length=16, blank=True)
    emoji_is_custom = models.BooleanField(default=False)
    kind = models.CharField(max_length=20, default=NORMAL)
    owner = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="owned_folders",
                              help_text="Person whose documents this folder holds (null for shared folders)")
    group = models.ForeignKey("accounts.FamilyGroup", null=True, blank=True, on_delete=models.SET_NULL, related_name="folders")
    inherit_permissions = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=100)
    source_path = models.TextField(blank=True)
    suggested_type = models.ForeignKey("DocumentType", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                       help_text="Proposed for uploads here; never forced, never moves documents")
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["parent", "name"], condition=Q(archived_at__isnull=True), name="uniq_folder_name_active"),
        ]

    def __str__(self):
        return self.name


class AccessRule(models.Model):
    """Explicit grant of capabilities on a folder or document to a user or family group."""

    folder = models.ForeignKey(Folder, null=True, blank=True, on_delete=models.CASCADE, related_name="rules")
    document = models.ForeignKey("Document", null=True, blank=True, on_delete=models.CASCADE, related_name="rules")
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="access_rules")
    group = models.ForeignKey("accounts.FamilyGroup", null=True, blank=True, on_delete=models.CASCADE, related_name="access_rules")
    caps = models.IntegerField()
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(Q(folder__isnull=False, document__isnull=True) | Q(folder__isnull=True, document__isnull=False)), name="rule_one_target"),
            models.CheckConstraint(condition=(Q(user__isnull=False, group__isnull=True) | Q(user__isnull=True, group__isnull=False)), name="rule_one_subject"),
        ]


class DocumentType(models.Model):
    TEMPLATES = ("generic", "passport", "visa", "iqama", "national_id", "driving_license", "employee_id", "insurance", "certificate")

    OCR_DISABLED, OCR_MANUAL, OCR_AUTOMATIC = "disabled", "manual", "automatic"
    OCR_MODES = (OCR_DISABLED, OCR_MANUAL, OCR_AUTOMATIC)

    name = models.CharField(max_length=80, unique=True)
    template = models.CharField(max_length=30, default="generic")
    has_expiry = models.BooleanField(default=False)
    emoji = models.CharField(max_length=16, blank=True)
    # Selective OCR policy (Change Set K): nothing is recognised unless the type allows it.
    ocr_mode = models.CharField(max_length=10, default=OCR_MANUAL, help_text="disabled | manual | automatic")
    ocr_languages = models.JSONField(default=list, blank=True, help_text="Tesseract language codes, e.g. ['eng', 'ara']")
    ocr_fields = models.JSONField(default=list, blank=True, help_text="Structured fields expected for this type")
    ocr_ai_allowed = models.BooleanField(default=False, help_text="May Local AI read this type's recognised text")
    ocr_profile = models.CharField(max_length=10, blank=True, help_text="Default OCR language profile ('' = global default)")
    is_custom = models.BooleanField(default=False)
    archived = models.BooleanField(default=False, help_text="Hidden from new documents; existing documents keep it")
    # Change Set N: administrator-managed classification and metadata template
    description = models.CharField(max_length=500, blank=True, help_text="Shown to people choosing a type")
    sort_order = models.IntegerField(default=100)
    reminder_days = models.JSONField(default=list, blank=True,
                                     help_text="Days before expiry for reminders of this type ([] = the global setting)")

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class DocumentTypeField(models.Model):
    """One field of a document type's metadata template. `key` is stable: renaming the label never orphans values."""

    TYPES = ("text", "long_text", "date", "number", "boolean", "select", "country", "person", "identifier")
    ROLES = ("", "expiry", "issue", "no_expiry")

    doc_type = models.ForeignKey(DocumentType, on_delete=models.CASCADE, related_name="template_fields")
    key = models.CharField(max_length=80)
    label = models.CharField(max_length=80)
    field_type = models.CharField(max_length=12, default="text")
    enabled = models.BooleanField(default=True)
    required = models.BooleanField(default=False)
    order = models.IntegerField(default=100)
    help_text = models.CharField(max_length=300, blank=True)
    extract = models.BooleanField(default=True, help_text="OCR / Local AI may suggest a value")
    searchable = models.BooleanField(default=True)
    role = models.CharField(max_length=10, blank=True, help_text="expiry | issue | no_expiry: drives dates and reminders")
    choices = models.JSONField(default=list, blank=True)
    validation = models.JSONField(default=dict, blank=True, help_text="pattern / min / max / max_length")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        unique_together = [("doc_type", "key")]

    def __str__(self):
        return f"{self.doc_type.name}: {self.label}"


class Tag(models.Model):
    name = models.CharField(max_length=60, unique=True)
    color = models.CharField(max_length=9, default="#d8eadb")

    class Meta:
        ordering = ["name"]


class Correspondent(models.Model):
    name = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ["name"]


class CustomFieldDef(models.Model):
    TYPES = ("text", "date", "number", "boolean", "choice")

    key = models.SlugField(max_length=60, unique=True)
    label = models.CharField(max_length=80)
    type = models.CharField(max_length=10, default="text")
    choices = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["label"]


class Document(models.Model):
    # text recognition states (shown to people as: Not processed, Queued, Processing, Needs review, Confirmed,
    # Failed, OCR removed)
    OCR_STATES = ("not_processed", "queued", "processing", "needs_review", "confirmed", "failed", "removed")
    QUEUED, PROCESSING, NEEDS_REVIEW, READY, FAILED, UNSUPPORTED = (
        "queued", "processing", "needs_review", "ready", "failed", "unsupported")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    folder = models.ForeignKey(Folder, on_delete=models.PROTECT, related_name="documents")
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="documents")
    group = models.ForeignKey("accounts.FamilyGroup", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    title = models.CharField(max_length=255)
    title_is_custom = models.BooleanField(default=False)
    doc_type = models.ForeignKey(DocumentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    TYPE_SOURCES = ("", "manual", "folder", "ocr", "ai", "import", "system", "migrated")
    type_source = models.CharField(max_length=10, blank=True, help_text="How the type was assigned")
    type_confirmed = models.BooleanField(default=False, help_text="A person chose or accepted the type")
    type_suggestions = models.JSONField(default=list, blank=True,
                                        help_text="Pending type suggestions: [{type, source, reason, confidence}]")
    details_incomplete_ok = models.BooleanField(default=False, help_text="Explicitly confirmed with required fields empty")
    correspondent = models.ForeignKey(Correspondent, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    tags = models.ManyToManyField(Tag, blank=True, related_name="documents")
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    no_expiry = models.BooleanField(default=False, help_text="A confirmed 'does not expire' statement (no reminders)")
    current_version = models.ForeignKey("DocumentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    state = models.CharField(max_length=16, default=QUEUED, db_index=True)
    review_flags = models.JSONField(default=list, blank=True)
    inherit_permissions = models.BooleanField(default=True)
    renews = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="renewed_by",
                               help_text="The previous credential this record renews (separate record)")
    content_text = models.TextField(blank=True)
    # Text recognition (OCR) state for the whole logical document; see apps/library/ocr_runs.py
    ocr_state = models.CharField(max_length=16, default="not_processed", db_index=True)
    ocr_sources = models.JSONField(default=list, blank=True, help_text="Primary OCR source set: [{version, pages}]")
    ocr_languages = models.JSONField(default=list, blank=True)
    ocr_error = models.TextField(blank=True)
    ocr_updated_at = models.DateTimeField(null=True, blank=True)
    # Change Set Q: per-document OCR controls
    ocr_override = models.CharField(max_length=10, blank=True, default="",
                                    help_text="'' follows the document type; 'disabled' = never recognise this document")
    ocr_profile = models.CharField(max_length=10, blank=True, help_text="Language profile of the last OCR run")
    ignore_embedded_text = models.BooleanField(default=False, help_text="Do not use the text layer embedded in the file")
    ocr_epoch = models.PositiveIntegerField(default=0, help_text="Bumped when OCR data is removed; stale jobs skip")
    search_vector = SearchVectorField(null=True)
    source_path = models.TextField(blank=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    archived_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [GinIndex(fields=["search_vector"])]

    def __str__(self):
        return self.title


class DocumentVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    original_name = models.CharField(max_length=255)
    storage_path = models.CharField(max_length=500, unique=True, help_text="Relative to ORIGINALS_DIR")
    size = models.BigIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    mime = models.CharField(max_length=120, blank=True)
    format_class = models.CharField(max_length=16, default="other")  # pdf|image|text|office|dicom|other
    comment = models.CharField(max_length=255, blank=True)
    preview_path = models.CharField(max_length=500, blank=True, help_text="Relative to DERIVATIVES_DIR")
    searchable_path = models.CharField(max_length=500, blank=True)
    thumbnail_path = models.CharField(max_length=500, blank=True)
    text = models.TextField(blank=True)
    page_count = models.IntegerField(null=True, blank=True)
    ocr_applied = models.BooleanField(default=False)
    pdfa = models.BooleanField(default=False, help_text="Searchable copy passed PDF/A validation")
    pdfa_report = models.JSONField(default=dict, blank=True)
    ocr_quality = models.JSONField(default=dict, blank=True, help_text="OCR confidence, rotation, steps, low-confidence lines")
    ocr_pages = models.CharField(max_length=200, blank=True, help_text="Pages recognised ('' = all pages)")
    # Change Set Q: which engine produced the recognised text (historical Tesseract results are never relabelled)
    ocr_engine = models.CharField(max_length=12, blank=True, db_index=True, help_text="paddleocr | tesseract | unknown")
    ocr_model = models.CharField(max_length=120, blank=True)
    ocr_profile = models.CharField(max_length=10, blank=True)
    ocr_blocks = models.JSONField(default=list, blank=True, help_text="Per page: lines with text, score and box")
    ocr_at = models.DateTimeField(null=True, blank=True)
    is_additional = models.BooleanField(default=False, help_text="Another side/copy of the same document (not a replacement)")
    state = models.CharField(max_length=16, default="queued")
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    # antivirus (ClamAV); the file stays usable while the scan is pending or could not run
    AV_STATES = ("pending", "clean", "not_scanned", "size_limit", "failed", "threat", "quarantined", "released")
    av_status = models.CharField(max_length=16, default="not_scanned", db_index=True)
    av_signature = models.CharField(max_length=200, blank=True, help_text="Detection name reported by ClamAV")
    av_engine = models.CharField(max_length=120, blank=True, help_text="Engine and signature version used")
    av_detail = models.CharField(max_length=300, blank=True, help_text="Why a file was not scanned / scan error")
    av_scanned_at = models.DateTimeField(null=True, blank=True)
    av_quarantine_path = models.CharField(max_length=300, blank=True, help_text="Relative to QUARANTINE_DIR")
    av_released_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    av_released_at = models.DateTimeField(null=True, blank=True)
    av_release_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-number"]
        unique_together = [("document", "number")]

    @property
    def av_blocked(self) -> bool:
        """Threat detected or quarantined: no preview, download, OCR or AI on this file."""
        return self.av_status in ("threat", "quarantined")


class DocumentField(models.Model):
    """Structured detail value with provenance; proposed values never drive reminders/naming."""

    PROPOSED, CONFIRMED = "proposed", "confirmed"
    STANDARD = ("full_name", "document_number", "issue_date", "expiry_date", "no_expiry", "date_of_birth", "nationality",
                "issuer", "country_code", "sex", "place_of_issue")
    SENSITIVE = ("document_number",)

    TYPE, CUSTOM, UNMAPPED = "type", "custom", "unmapped"
    SOURCES = ("manual", "ocr", "mrz", "ai", "import", "system", "migrated")

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="fields")
    key = models.CharField(max_length=80)
    label = models.CharField(max_length=80, blank=True, help_text="For one-off details that are not in the template")
    value = models.TextField(blank=True)
    status = models.CharField(max_length=10, default=PROPOSED)
    source = models.CharField(max_length=20, default="manual")  # manual|ocr|mrz|ai|import|system|migrated
    # type: from the type template (or extraction); custom: a one-off detail of this document;
    # unmapped: kept from a previous type until the person maps, keeps or removes it
    scope = models.CharField(max_length=10, default=TYPE)
    overridden = models.BooleanField(default=False, help_text="A person replaced an OCR / AI value")
    previous_type = models.CharField(max_length=80, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    version = models.ForeignKey(DocumentVersion, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    confidence = models.FloatField(null=True, blank=True)
    flags = models.JSONField(default=list, blank=True)
    source_excerpt = models.CharField(max_length=300, blank=True)
    proposed_value = models.TextField(blank=True)
    confirmed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("document", "key")]


class DocumentHistory(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="history")
    at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=40)
    changes = models.JSONField(default=dict)

    class Meta:
        ordering = ["-at"]


class ShareLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="share_links")
    version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, related_name="share_links",
                                help_text="Links are pinned to one version; renewals never substitute")
    token_hash = models.CharField(max_length=128, unique=True)
    token_hint = models.CharField(max_length=8)
    password_hash = models.CharField(max_length=200, blank=True)
    allow_download = models.BooleanField(default=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    access_count = models.IntegerField(default=0)
    last_access_at = models.DateTimeField(null=True, blank=True)


class SavedView(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_views")
    name = models.CharField(max_length=80)
    query = models.JSONField(default=dict)
    show_on_dashboard = models.BooleanField(default=False)
    show_in_sidebar = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class ImportSession(models.Model):
    BROWSER, SERVER = "browser", "server"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    source_type = models.CharField(max_length=10)
    source_root = models.TextField(blank=True)
    destination = models.ForeignKey(Folder, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=16, default="scanning")  # scanning|mapping|importing|done|failed|cancelled
    scan = models.JSONField(default=dict, blank=True)
    mapping = models.JSONField(default=dict, blank=True)  # top-level source folder -> {"user": id} | {"shared": folder_id} | {"skip": true}
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class ImportItem(models.Model):
    session = models.ForeignKey(ImportSession, on_delete=models.CASCADE, related_name="items")
    relative_path = models.TextField()
    size = models.BigIntegerField(default=0)
    status = models.CharField(max_length=10, default="pending")  # pending|done|failed|skipped
    excluded_reason = models.CharField(max_length=120, blank=True)
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    error = models.TextField(blank=True)
    attempts = models.IntegerField(default=0)

    class Meta:
        unique_together = [("session", "relative_path")]


class OcrRun(models.Model):
    """One OCR job: engine, models, profile, sources, options, timing, outcome and confidence summary.

    It never stores recognised text: the text lives on the document version only once the whole run succeeded, so a
    failed run leaves the previous result untouched and removing OCR data leaves nothing behind here."""

    QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"
    id = models.BigAutoField(primary_key=True)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="ocr_runs")
    job_id = models.UUIDField(null=True, blank=True)
    engine = models.CharField(max_length=12, help_text="paddleocr | tesseract")
    engine_version = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=200, blank=True)
    profile = models.CharField(max_length=10, blank=True)
    languages = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True)
    options = models.JSONField(default=dict, blank=True)
    reprocess = models.BooleanField(default=False, help_text="Explicit re-processing of existing OCR")
    status = models.CharField(max_length=10, default=QUEUED, db_index=True)
    confidence = models.FloatField(null=True, blank=True)
    line_count = models.PositiveIntegerField(default=0)
    low_lines = models.PositiveIntegerField(default=0)
    seconds = models.FloatField(null=True, blank=True)
    error = models.CharField(max_length=500, blank=True)
    requested_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class OfflineDevice(models.Model):
    """One browser or installed app (PWA) of one account that keeps offline copies (Change Set S).

    Offline state is scoped by user + device + folder/document: a selection made on one device never downloads
    anything on another device or for another account. The id is issued by the server and kept by the device; it
    is not a secret and grants nothing by itself (every request is still authenticated and authorised)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="offline_devices")
    label = models.CharField(max_length=80, help_text="Friendly name, e.g. 'Chrome on Windows' or 'iPhone app'")
    platform = models.CharField(max_length=80, blank=True, help_text="Browser / operating system summary")
    installed_app = models.BooleanField(default=False, help_text="Running as an installed app (standalone display)")
    created_at = models.DateTimeField(auto_now_add=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    reported_items = models.PositiveIntegerField(default=0)
    reported_bytes = models.BigIntegerField(default=0)
    reported_failures = models.PositiveIntegerField(default=0)
    wipe_requested_at = models.DateTimeField(null=True, blank=True,
                                             help_text="Remove all protected offline data at the next sync")

    class Meta:
        ordering = ["-last_sync_at", "-created_at"]
        indexes = [models.Index(fields=["user", "last_sync_at"])]


class OfflineSelection(models.Model):
    """A folder (optionally with its subfolders) or a single document chosen for offline use on one device."""

    id = models.BigAutoField(primary_key=True)
    device = models.ForeignKey(OfflineDevice, on_delete=models.CASCADE, related_name="selections")
    folder = models.ForeignKey(Folder, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    recursive = models.BooleanField(default=True, help_text="Folder: include all subfolders")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(folder__isnull=False, document__isnull=True) | Q(folder__isnull=True, document__isnull=False),
                                   name="offline_selection_one_target"),
            models.UniqueConstraint(fields=["device", "folder"], condition=Q(folder__isnull=False), name="uniq_offline_folder"),
            models.UniqueConstraint(fields=["device", "document"], condition=Q(document__isnull=False), name="uniq_offline_document"),
        ]
