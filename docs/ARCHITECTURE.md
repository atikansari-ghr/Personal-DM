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
Sign-in: password (username, or an email address that belongs to exactly one active account) → optional second step
(TOTP, passkey via WebAuthn, recovery code) → session; or, in the default `auth.passkey_mode` *passwordless*, **Sign in
with Passkey** (discoverable credential, user verification required) directly. Every outcome is written to `LoginEvent`.

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

- **OCR engines (Change Set Q):** `library/ocr_engines.py` routes runs to PaddleOCR (PP-OCRv5, default) or Tesseract
  (Legacy), resolves fallback, maps language profiles to models, and checks health with a real-inference self-test.
  `library/paddle_worker.py` runs in the isolated `/opt/personaldocs/paddle-venv` through the sandbox (memory, CPU and
  time limits; it never imports Django and never downloads models). Runs are staged and applied atomically
  (`ocr_runs._apply_run`) against the document's OCR epoch. `ocr_runs.remove_ocr` / `set_ocr_disabled` implement
  removal and the per-document override. `library/ocr_admin.py` provides the inventory, throttled bulk jobs
  (`ocr_bulk`), orphan analysis/cleanup and Test / Compare. `OcrRun` records run metadata, never text. See
  [ADR 0016](adr/0016-paddleocr-ocr-lifecycle.md).
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

## Change set O (2026-10): notification pipeline

See [ADR 0014](adr/0014-rich-notifications.md) and the [notifications guide](guides/notifications.md).

```
event source (notify/events.py, notify/expiry.py, security/alerts.py, security/antivirus.py,
              security/center.py, security/views_center.py, passkey / TOTP / recovery / authentik)
   │  builds a structured Message (rich.py): event, severity, category, icon, title, heading, summary,
   │  details (+ sensitive flag), actions, guidance, items, link, placeholder context, TEST flag
   ▼
dispatch (expiry.py): recipients → channels (catalog.channels_for: preferences + critical/required channels)
   │  idempotency key per event, repeat cooldown for recurring conditions (events.notify cooldown_group)
   ├─ in_app   → rich.render_in_app   → Notification (title, summary, severity, category, icon, data = card)
   ├─ email    → rich.render_email    → OutboxMessage (subject, plain text, html)        ┐
   ├─ telegram → rich.render_telegram → OutboxMessage (HTML text, inline URL buttons)    ├─ worker: deliver_outbox
   └─ push     → rich.render_push     → OutboxMessage (payload: title, body, url, tag)   ┘   retry/backoff, provider_ref
```

- **Templates.** `rich.apply_template` applies a `NotificationTemplate` override (per event and channel, or all
  channels) before rendering: `check_template_text` accepts plain text with allowlisted placeholders only, `fill`
  substitutes escaped values (names masked outside the app per `notifications.include_names`), and `floor_severity`
  keeps critical events at Warning or above. The event's details, action targets, recipients and channels are not
  templated.
- **Escaping.** Every renderer escapes for its own output (HTML for email and Telegram, plain text elsewhere); the
  admin preview of email renders in a sandboxed iframe. Values never become markup.
- **Actions.** `events.default_actions` and the expiry message define actions as application paths; `rich.safe_path`
  refuses API paths and anything containing `release`. Links carry no tokens; opening one goes through the normal
  sign-in and permission checks. In-app-only actions (Snooze) go through `POST /api/notifications/<id>/action`.
- **Sensitive details.** A detail marked sensitive (the document number) is left out unless
  `notifications.include_document_number` is on, then masked to the last four characters; it is never rendered for
  push. Long digit runs are masked in external channels.
- **Web Push** (`notify/webpush.py`): a VAPID key pair is created on first use and stored encrypted in the database
  (so it is in backups). Subscriptions (`PushSubscription`) are accepted only for HTTPS endpoints on the known push
  services (`fcm.googleapis.com`, `android.googleapis.com`, `*.push.services.mozilla.com`, `web.push.apple.com`,
  `*.push.apple.com`, `*.notify.windows.com`), never for internal addresses or URLs with credentials. Payloads are
  encrypted with aes128gcm (`http-ece`) and signed with VAPID (`py-vapid`); 404/410 responses remove the
  subscription. `render_push` follows the recipient's `me.push_preview`. The service worker (`sw.ts`) shows the
  notification and on click opens only same-origin pages.
- **Delivery states.** `OutboxMessage` moves through pending (queued / retrying with the next attempt time), sent,
  failed and skipped; `provider_ref` holds the provider's message id (Telegram message id, push `Location`) and is
  shown as "accepted by the provider". Errors are stored with credentials redacted.
- **TEST sends** (`POST /api/notifications/templates/<event>/test`) build a sample `Message` with `test=True`, send it
  only to the requesting administrator and write only the audit entry `notifications.test_sent`.
- **Frontend:** `pages/Notifications.tsx`, `components/NotificationCard.tsx`, `components/NotificationBanners.tsx`
  (poll every 60 s and on navigation), `pages/settings/NotificationTemplates.tsx` (Template Manager, Delivery history),
  the push section of My account → Notifications.
- Migration `notify.0002_rich_notifications`; new tables `PushSubscription`, `NotificationTemplate`, `ExpirySnooze`.

## Change set P (2026-10): passkey sign-in mode, password reset, security templates, ClamAV repair

See [ADR 0015](adr/0015-passkey-signin-password-reset-clamav-repair.md).

- **Passkey mode.** `auth.passkey_mode` (`passwordless` default, `mfa`) replaces `auth.allow_passwordless`
  (migration `accounts.0007_passkey_mode`). `accounts/views.py::session_state` tells `pages/Auth.tsx` which methods to
  offer; the page shows password, "or", **Sign in with Passkey**, then authentik/Google, and starts WebAuthn
  conditional mediation (`webauthn.ts`) for passkey autofill in the username field. `passkey_login_verify` uses
  `py_webauthn` with user verification required, a single-use challenge, and the origin and RP ID of
  `PD_PUBLIC_ORIGIN`. Registering a discoverable passkey in passwordless mode sets the account's passwordless flag;
  `my_passwordless` turns it off again (recent confirmation, audited, notified). In `mfa` mode passkeys are only the
  second step.
- **Password reset** (`accounts/password_reset.py`, one module for every entry point):

```
Forgot password? ──┐
Admin "Send reset email" ─┤ can_reset (admin, not self, main admin protected, active)
                         ▼
               new_token: 32 random bytes, hash stored, older unused tokens invalidated,
               expires after auth.reset_token_minutes
                         ▼
               send_reset_email: rich.Message(secret_link=…/reset-password?token=…) → render_email
               → mailer.send_mail_now (direct SMTP; never OutboxMessage, Notification, Telegram, push or logs)
                         ▼
               POST /api/auth/password/reset: hash lookup, valid + unused → set_password → token used
               → password_changed → "Password reset completed"

Admin "Generate temporary password" → can_reset → generate_password(16) → set_password(temporary=True)
   (hash only; must_change; invalidates tokens; the changed hash ends every Django session)
   → response once with Cache-Control: no-store → audit family.password_reset_by_admin (method, never the value)
   → notify security.temporary_password (person) + security.password_admin_reset (other main administrators)
```

- **Security templates.** `notify/event_defs.py` gives security events a `mandatory` tuple; `rich.Message` always
  merges it in, and `render_email` (red box, `IMPORTANT:` lines in plain text), `render_telegram` (bold ⚠️ lines) and
  `render_in_app` (`mandatory` in the card data) render it outside the template fields, so an override cannot remove
  it. `NotificationTemplate.brand` and `.footer` (migration `notify.0003_template_brand_footer`) go through the same
  `check_template_text` and escaping. `Message.secret_link` is accepted only for this application's
  `/reset-password?token=` address and is rendered only by `render_email`.
- **ClamAV diagnosis and repair.** `ops/clamav_check.py` (standard library only) is shared by three callers:

```
sudo personaldocs antivirus status|repair|selftest ─┐
personaldocs install / post-upgrade / repair ───────┼─▶ python3 clamav_check.py (root)
host helper action antivirus_repair (ops/host_helper.py)┘      diagnose(): systemd units, socket unit Listen vs
                                                               clamd.conf LocalSocket, /run/clamav, socket file,
web app (personaldocs user):                                   runuser PING as personaldocs, VERSION, INSTREAM
  security/antivirus.py::diagnose, self_test ─────────────▶   self-test, memory, journal → root_cause()
  security/views_av.py  /api/security/antivirus/diagnose      repair(): packages, clamd.conf, drop-in, tmpfiles,
                        /selftest, /repair (→ host helper)    freshclam, enable/start socket + daemon, wait PONG,
                                                               final diagnose + self-test
```

  The web app never runs root commands: **Repair antivirus** writes the fixed action `antivirus_repair` to the host
  helper request file. After a repair the installer runs `manage antivirus sync-socket PATH` so `antivirus.socket`
  matches the socket clamd really serves. `security/antivirus.py` derives the health state (Healthy, Degraded,
  Unavailable, Error, disabled) from a live `PING` plus a small clean `INSTREAM` scan and the last self-test result;
  `security/center.py::security_health` gives Unavailable and Error 0 points and forces At Risk. The hourly check runs
  `self_test` once a day and after a failure. `doctor` prints the root diagnosis before the app checks.
- Migrations `accounts.0007_passkey_mode`, `notify.0003_template_brand_footer`. No new dependencies.
