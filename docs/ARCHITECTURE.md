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
           ▼
  /var/lib/personaldocs/storage/{originals,derivatives}   →   NAS mount (application backups)
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
2. PDF: extract native text. If there is too little text and the page count is within the limit, run OCRmyPDF (`--skip-text`, PDF/A-2, one job, `OMP_THREAD_LIMIT=1`).
3. Image: verify it and check its pixel count, make a thumbnail, then OCR it into a searchable PDF.
4. Office: convert with headless LibreOffice using a throwaway profile, then extract text and make a thumbnail.
5. Text: read it, up to 2 MB.
6. DICOM and other formats: store the file and mark it *unsupported* (no preview).
7. Propose fields (labels and MRZ). Confirmed fields are never overwritten; a differing new scan is flagged instead.
8. Update the search vector: title (A), metadata and fields excluding the document number (B), content (C).
9. If Local AI is enabled: queue `ai_task` jobs (analysis → suggestions; embeddings) **after** the document is stored and searchable.

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
| `/var/lib/personaldocs` | personaldocs 0750 | storage, staging, tmp, quarantine, pre-upgrade DB snapshots, status files, `profile-photos/`, `geoip/`, `logs/access.log`, `goaccess/` |

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
- **Preferences:** theme, layout, dashboard widgets and notification choices are per-account server settings; the
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
