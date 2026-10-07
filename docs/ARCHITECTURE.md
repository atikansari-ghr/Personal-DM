# Architecture

```
            HTTPS (NPM / Pangolin)
                     │   real client IP via X-Forwarded-For (trusted proxies only)
                     │   country/IP access policy, before sign-in
                     │
        ┌────────────▼─────────────┐    Debian 13 LXC (2 vCPU / 4 GB / 50 GB)
        │ personaldocs-web         │    gunicorn + Django 5.2 (API + SPA + /s/ share pages)
        └────────────┬─────────────┘
                     │ SQL (unix socket, peer auth)
        ┌────────────▼─────────────┐
        │ PostgreSQL 17            │    metadata, permissions, FTS (tsvector/GIN), job queue, sessions
        └──▲───────────────────▲───┘
           │                   │
┌──────────┴─────────┐ ┌───────┴──────────────┐
│ personaldocs-worker│ │ personaldocs-scheduler│  reminders, outbox, Telegram link polling,
│ OCR/previews/      │ │                       │  IMAP polling, nightly backup, retention
│ imports/backups    │ └───────────────────────┘
└──────────┬─────────┘
           │ subprocess with limits: ocrmypdf/tesseract, soffice, pdftoppm, pg_dump
           │ Unix socket /run/clamav/clamd.ctl → clamav-daemon (no TCP); clamav-freshclam updates signatures
           ▼
  /var/lib/personaldocs/storage/{originals,derivatives}   →   NAS mount (application backups)

  personaldocs-host.path (root) ← <data>/host/request.json: inspect, check/install security updates, freshclam, reboot
```

## Principles

- **Modular monolith.** One Django project, one database, three systemd services. No Redis, Celery or Docker. See [ADR-0001](adr/0001-stack.md).
- **Centralised authorisation.** `apps/library/permissions.py` is the only place that decides access. It is used by every API view, file route, search query, export, share link and background job. Missing objects and inaccessible objects both return 404. See [ADR-0003](adr/0003-permissions.md).
- **Immutable originals.** Files are staged and hashed, then moved atomically into a path that always contains the version UUID, and marked read-only (0440). Database rows are created in the same transaction; on rollback the placed file is removed, and the integrity checker catches anything left over. See [ADR-0004](adr/0004-storage.md).
- **Durable jobs.** A PostgreSQL table with `SELECT … FOR UPDATE SKIP LOCKED`, leases, exponential backoff, idempotency keys and a global limit on heavy jobs. Handlers re-check state and permissions when they run. See [ADR-0002](adr/0002-job-queue.md).
- **Single settings registry.** `apps/core/registry.py` drives validation, permissions, UI help and `SETTINGS_REFERENCE.md`. Secrets are Fernet-encrypted with a key stored outside the database.
- **Suggestions never act alone.** OCR and parsing produce *proposed* values. Only values a person has confirmed can change names or reminders.
- **Honest integrations.** Unconfigured channels show actionable issues and are recorded as skipped, never as sent. WhatsApp is labelled as a later phase.
- **Separated security responsibilities.** The access policy (country/IP) decides whether a network may reach the app; the login audit records who authenticated; GoAccess only observes traffic; Local AI only works after authorisation has fixed which documents the person may open. See [ADR-0007](adr/0007-security-access.md).
- **AI is optional and advisory.** AI output becomes `AISuggestion` rows that a person must accept; retrieval starts from `AccessContext.documents()`. There is no cloud fallback. See [ADR-0008](adr/0008-local-ai.md).

## Request flow

Middleware order: `AccessLogMiddleware` (privacy-safe access log) → `LocalAccessCookieMiddleware` → `AccessPolicyMiddleware`
(refuses blocked networks before sessions, CSRF and authentication) → Django security, sessions, CSRF, authentication →
`AccountStateMiddleware`. The SPA (React/TS, built by Vite into `frontend/dist`) is served by WhiteNoise. API calls use the session cookie plus `X-CSRFToken`. `AccountStateMiddleware` ends sessions for disabled accounts and after a session-epoch bump (password reset, console recovery, "sign out everywhere"). `IsActiveAuthenticated` blocks the whole API, apart from password change, while a temporary password is pending, and
(when the policy requires two-step verification) apart from the passkey/authenticator setup views until one is configured.
Sign-in: password → optional second step (TOTP, passkey via WebAuthn, recovery code) → session; optional passwordless passkey
sign-in. Every outcome is written to `LoginEvent`.

## Processing pipeline

`process_version` (heavy job):

1. Detect the format from magic bytes and extension.
2. PDF: extract native text. If there is too little text, the OCR policy of the document type allows automatic OCR and the page count is within the limit, run OCRmyPDF (`--skip-text`, PDF/A-2, one job, `OMP_THREAD_LIMIT=1`) on the primary OCR source. Otherwise the document stays *Not processed* until someone chooses **Run OCR…** (see Change set K below).
3. Image: verify it and check its pixel count, make a thumbnail, then (only under an *Automatic* policy) OCR it into a searchable PDF.
4. Office: convert with headless LibreOffice using a throwaway profile, then extract text and make a thumbnail.
5. Text: read it, up to 2 MB.
6. DICOM and other formats: store the file and mark it *unsupported* (no preview).
7. Propose fields (labels and MRZ). Confirmed fields are never overwritten; a differing new scan is flagged instead.
8. Update the search vector: title (A), metadata and fields excluding the document number (B), content (C).
9. If Local AI is enabled and the document type allows AI to read its text: queue `ai_task` jobs (analysis → suggestions; embeddings) **after** the document is stored and searchable.

All tools run through `sandbox.run`: their own session, an address-space limit, a CPU-time limit, a timeout, a scrubbed environment and a private working directory.

## Reminder engine

See `apps/notify/expiry.py` for the policy header. Thresholds are handled per (document, expiry date, threshold) in `ExpiryMark`. Deliveries are in `OutboxMessage`, keyed by `expiry:<doc>:<date>:<threshold>:<user>:<channel>`. Recipients are resolved at send time.

## Backup consistency

Originals are write-once and always exist before their rows commit. `pg_dump` takes a snapshot. Every file referenced by the snapshot is copied (or hard-linked from the previous backup) and re-hashed. The manifest is written last and the folder is renamed from `.partial`. Restore verifies every checksum before touching the database.

## Data locations

| Path | Owner / mode | Contents |
|---|---|---|
| `/opt/personaldocs/releases/<ver>-<sha>` | root:personaldocs, read-only | code, `.venv`, `frontend/dist` |
| `/etc/personaldocs` | root:personaldocs 0750 | env file, `secret_key`, `encryption.key` (0600 personaldocs), `github-token` (0600 root) |
| `/var/lib/personaldocs` | personaldocs 0750 | storage, staging, tmp, quarantine (antivirus quarantine 0400 files; integrity orphans), `pre-update-backups/` (newest 3), `host/` (host helper requests and logs), pre-upgrade DB snapshots, status files, `profile-photos/`, `branding/` (sign-in wallpaper and logo), `geoip/`, `logs/access.log`, `goaccess/` |

## Extension points (later phases)

- **More AI providers**: add a `Provider` subclass in `apps/ai/providers.py` (list_models, chat, embed) and a choice in `AIProfile.PROVIDERS`.
- **WhatsApp**: a new channel in `expiry.dispatch`/`deliver_outbox` and in `registry.CHANNELS`, once a provider has been chosen and verified.

## Change set H/I (2026-10)

- **Notifications:** an event catalogue decides, per event, whether it is critical (administrator-chosen, cannot be
  turned off, always on the critical channels) or optional (per person, per channel). All messages use one template;
  bulk actions are summarised. See [ADR 0009](adr/0009-notifications-moves-viewer.md).
- **Moves:** document and folder moves are transactional and serialised; drag and drop and "Move to…" call the same
  endpoints.
- **Viewer:** PDF.js renders previews in the browser from the authenticated preview endpoint, with all its assets
  served by the app.
- **Backups:** `ops/schedule.py` computes daily/weekly/monthly occurrences; the scheduler stores the last run so
  restarts neither skip nor repeat a slot.
- **Preferences:** theme, layout, dashboard (now Overview) widgets and notification choices are per-account server settings; the
  client refreshes them when the app returns to the foreground.

## Change set J (2026-10)

- **Menus:** `components/Menu.tsx` renders every ⋮ menu in a portal positioned from its trigger, so panels never clip
  it. See [ADR 0010](adr/0010-browsing-ocr-installer.md).
- **Desktop drops:** `dropUpload.ts` walks dropped folders (File and Directory Entries API) and uploads in batches to
  `POST /api/documents` with relative `paths`. `views._DropTree` validates them and recreates the folders.
- **Views:** `me.doc_view` / `me.doc_sort` account settings; sorting is done by the server (`search.SORTS`).
- **OCR:** `library/ocr.py` prepares images (EXIF, grayscale, contrast, upscale, denoise, orientation, deskew) and
  returns per-line confidence. Each version stores `ocr_quality`; extraction reads only the reliable lines.
- **Installer:** `personal-DM.sh` at the repository root checks the platform and delegates to `easy-install.sh` and
  `personaldocs`.

## Change sets K and L (2026-10)

See [ADR 0011](adr/0011-selective-ocr-overview.md).

- **Selective OCR:** `library/ocr_policy.py` decides the mode (Disabled / Manual / Automatic), default languages,
  page ranges and whether AI may read a document's text, per document type and for untyped documents.
  `library/ocr_runs.py` validates requests (sources, pages, languages, size, page, queue and attempt limits), queues
  one `ocr_run` job per request (several source files, such as front and back, in one job), cancels queued jobs,
  removes OCR data and marks documents reviewed. `library/ocr_views.py` serves `/api/documents/<id>/ocr`,
  `/ocr/cancel`, `/ocr/reviewed`, `/api/ocr/review`, `/api/ocr/languages` and `/api/ocr/types`. Frontend:
  `components/OcrPanel.tsx`, `pages/OcrReview.tsx`, `pages/settings/OcrTypes.tsx`. Migrations `library.0006` (fields)
  and `library.0007` (defaults; existing installations stay Automatic).
- **Overview:** `core/overview.py` holds the layout rules (`normalize_layout`, per-widget limits), the Gregorian and
  Hijri date (`hijridate`, Umm al-Qura, installation timezone), holidays (`holidays` library merged with
  `HolidayOverride` rows) and the weather proxy (`WeatherCache` rows shared by everyone who chose the same city; only
  coordinates leave the server). `core/overview_views.py` serves `/api/overview/calendar`, `/holidays`, `/countries`,
  `/weather`, `/weather/cities`, `/weather/test`, `/weather/default-city` and `/holiday-overrides`; `/api/dashboard`
  carries the widget data. Frontend: `pages/Dashboard.tsx`, `components/OverviewWidgets.tsx`,
  `pages/settings/OverviewAdmin.tsx`. Per-account layout in `me.dashboard_widgets` and `me.overview_layout`.
  Migration `core.0003`.
- **Sign-in designs:** `core/branding.py` validates, re-encodes (WebP, metadata removed) and stores uploads under
  `<data>/branding`; `core/branding_views.py` serves the public `/api/branding`, `/api/branding/wallpaper` and
  `/api/branding/logo` (changes are administrator-only). The presets are SVG drawings in `components/LoginArt.tsx`.
- **Setup:** `accounts/services.py::complete_setup` creates the Main Administrator and the optional members in one
  transaction; no default accounts exist.

## Change set M (2026-10)

See [ADR 0012](adr/0012-antivirus-authentik-security-center.md).

- **Antivirus:** `security/antivirus.py` marks each new `DocumentVersion` *pending* in the upload transaction and
  queues a scan job after commit; the job streams the file to clamd over the local Unix socket (`INSTREAM`) and
  stores status, signature, engine and time. A detection moves the file to `<data>/quarantine` (0400) and
  `DocumentVersion.av_blocked` stops preview, download, share links, export, OCR and AI jobs. Library scans are
  `AvScanRun` rows processed in batches (pause, resume, cancel, schedule). `security/views_av.py` serves
  `/api/security/antivirus*`. Backups skip quarantined versions; the integrity check expects them in the quarantine.
- **authentik:** `accounts/authentik.py` is a generic OpenID Connect client (discovery, authorization code with
  PKCE, state and nonce, ID token verified with the provider's JWKS, issuer and audience). `ExternalIdentity` links a
  provider subject to a user; an existing account is linked only through the link flow
  (`/api/auth/authentik/start?mode=link`) started by the signed-in user after recent re-authentication, never by
  matching email. Optional automatic provisioning creates a new member account with its link; group mapping changes
  only `is_admin` on accounts that are not the main administrator.
  Routes `/api/auth/authentik/start`, `/callback`, `/test`, `/links`.
- **Administrator role:** `User.is_admin`; `User.is_administrator` (main administrator or Administrator) gates the
  security center APIs and security notifications and is not consulted by `library/permissions.py`.
- **Security center:** `security/center.py` holds the HTTPS checks, the Basic Internet Security Test
  (`SecurityTestRun`, run as a background job), the Security Health score, record retention and purge, and Storage
  Health with safe cleanup; `security/views_center.py` serves `/api/security/health`, `/https`, `/tests`,
  `/os-updates`, `/reboot`, `/firewall`, `/records` and `/storage`. Frontend: `pages/settings/SecurityCenter.tsx`.
- **Host helper:** the app writes `<data>/host/request.json`; `personaldocs-host.path` starts `personaldocs
  host-apply`, which runs `ops/host_helper.py` as root with a fixed list of actions and writes status and logs back.
  `ops/host.py` is the app side. The web app never runs `sudo`.
- **HTTPS:** `SECURE_HSTS_SECONDS` from `PD_HSTS_SECONDS` (default one year for https origins), sent only on requests
  Django sees as HTTPS (`PD_BEHIND_PROXY` and `X-Forwarded-Proto`).
- Migrations `accounts.0005`, `accounts.0006`, `library.0008`, `security.0002`, `security.0003`.

## Change set N (2026-10): document types and metadata templates

See [ADR 0013](adr/0013-document-types-templates.md) and the [document types guide](guides/document-types.md).

- **Data model** (migration `library.0009_document_type_templates`):
  - `DocumentType` (seeded by `seed_defaults`, editable): name, icon, `description`, `sort_order`, expiry awareness,
    `reminder_days` (empty = global schedule), archived, plus the OCR policy fields of change set K.
  - `DocumentTypeField` (the template): stable `key`, `label`, `field_type` (text, long_text, date, number, boolean,
    select, country, person, identifier), `enabled`, `required`, `order`, `help_text`, `extract`, `searchable`,
    `role` (expiry, issue, no_expiry), `choices`, `validation` (pattern, min, max, max_length).
  - `Document`: `doc_type`, `type_source` (manual, folder, ocr, ai, import, system, migrated), `type_confirmed`,
    `type_suggestions` (pending suggestions with source, reason, confidence), `details_incomplete_ok`.
  - `DocumentField` (a value): `key`, `label`, `value`, status (suggested/confirmed), `source` (manual, ocr, mrz, ai,
    import, system, migrated), `scope` (type = template field, custom = one-off detail, unmapped = previous detail
    after a type change), `overridden`, `previous_type`, `updated_at`.
  - `Folder.suggested_type`: a suggestion for uploads, inherited by sub-folders; never applied to existing documents.
- **Folder and type are orthogonal.** Moves (`library/services.py`) never touch `doc_type`; type changes never touch
  `folder` or storage.
- **`library/doctypes.py`** is the single place for type logic: template defaults and `ensure_template`,
  `validate_value` / `check_value`, `role_keys` (which keys have the expiry / issue / no-expiry roles),
  `details_status`, `allowed_extract_keys` and `store_proposals` (OCR/AI proposals limited to extractable template
  fields, never over confirmed values), `guess_type` / `suggest_from_text` / `folder_suggestion` /
  `add_suggestion`, `plan_change` and `change_type` (preview and apply: matching keys kept, others become
  `unmapped`, expiry re-derived, history and audit written), `resolve_unmapped` (map / keep / remove), `remap_ocr`
  (proposals from stored OCR text, no new OCR job), `promote` and `report`. The bulk `set_type` action and
  `DELETE /api/document-types/<id>` with `reassign_to` go through `change_type`.
- **Reminders:** `services.apply_confirmed_fields` derives issue and expiry dates only from confirmed values of the
  role fields in the template scope (not custom or unmapped values); `notify/expiry.py` uses the type's
  `reminder_days` when set.
- **Search:** `library/search.py` indexes values of searchable template fields; identifiers are not searchable by
  default. `ocr_views.ocr_review_queue` filters by `type` (including untyped).
- **API:** `library/views_types.py` serves `/api/documents/<id>/type`, `/api/documents/<id>/remap-ocr`,
  `/api/documents/bulk-type`, `/api/document-types` (active types for any signed-in user), and the main-administrator
  routes `/api/document-types/admin`, `/<id>`, `/<id>/fields`, `/<id>/fields/<fid>` and `/review`.
- **Frontend:** `components/DocumentDetails.tsx` (Details panel, type change and bulk dialogs, folder suggestion),
  `components/UploadDialog.tsx` (folder-suggested type), `pages/settings/DocumentTypes.tsx` (types, template editor
  with preview, review of untyped documents), `pages/OcrReview.tsx` (type filter).
- **Ops:** `manage.py document_types report` (`personaldocs manage document_types report`) and an info line in
  `doctor`.
