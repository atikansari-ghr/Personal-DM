<!-- audience: admin -->
# Architecture (for maintainers)

See also `docs/ARCHITECTURE.md` and the decision records in `docs/adr/`.

## Components {#components}

- **Backend**: Django 5.2 modular monolith (`backend/apps/*`) with a JSON API under `/api/`, served by gunicorn.
- **Frontend**: React + TypeScript single-page app built with Vite to static files, served by the same origin (WhiteNoise).
- **Database**: PostgreSQL — metadata, permissions, full-text search (tsvector + GIN), durable job queue, sessions.
- **Worker** (`manage.py worker`): leases jobs from the PostgreSQL queue (`SELECT … FOR UPDATE SKIP LOCKED`), runs OCR/previews/imports/backups with bounded concurrency.
- **Scheduler** (`manage.py scheduler`): reminders, outbox delivery, Telegram link polling, email polling, nightly backup, retention, integrity.

## Apps {#apps}

| App | Responsibility |
|---|---|
| `core` | Settings registry, encrypted secrets, audit, jobs, rate limiting, health, help |
| `accounts` | Users, groups, delegation, setup wizard, sign-in, TOTP, Google linking |
| `library` | Folders, documents, versions, fields, permissions, storage, processing, search, sharing, imports, exports |
| `notify` | Expiry scheduling, in-app notifications, SMTP/Telegram outbox |
| `mailimport` | Per-user IMAP accounts and rules |
| `ops` | Backup/restore, integrity, diagnostics |
| `security` | Real client IP (trusted proxies), login audit, local GeoIP, pre-authentication country/IP access policy, security alerts, access log and traffic analytics |
| `ai` | Optional Local AI: provider adapters (OpenAI-compatible, Ollama), privacy classes, suggestions, permission-filtered assistant and semantic search, AI jobs |

## Data model {#data-model}

`User` (UUID) ⟶ `GroupMembership` ⟵ `FamilyGroup` (head) ⟵ `Delegation`. `Folder` tree (owner, inherit flag) with `AccessRule` (folder **or** document, user **or** group, capability bitmask). `Document` (owner, folder, type, confirmed dates, current version, renews) ⟶ `DocumentVersion` (immutable file, checksum, derivatives, text) and `DocumentField` (proposed/confirmed with provenance). `ShareLink` pins a version. `ImportSession`/`ImportItem` track imports idempotently. `OutboxMessage` keys make delivery idempotent; `ExpiryMark` records handled thresholds.
`WebAuthnCredential` (public key, sign counter, name) belongs to a `User`, which also carries `photo_name` for its private
profile photo. `LoginEvent` records authentication; `GeoPolicy` (singleton), `CountryRule`, `TemporaryCountryAccess` and `IPRule`
form the access policy; `BlockedStat` counts refusals. `AIProfile`, `AIJob`, `AISuggestion` (pending until accepted) and
`DocumentChunk` (embeddings) hold Local AI state.

Request path: `AccessLogMiddleware` → `LocalAccessCookieMiddleware` → `AccessPolicyMiddleware` (denies before sessions,
CSRF and authentication) → Django security/session/CSRF/auth → views. The access policy cache is per process (15 s).

## API {#api}

All endpoints are listed in `backend/personaldocs/urls.py`. Authentication is session cookie + CSRF header (`X-CSRFToken`). Errors are `{"error": "...", "fields"?: {...}}`. Inaccessible objects return 404, indistinguishable from non-existent ones.

## Jobs {#jobs}

Job kinds: `process_version` (heavy), `import_server`, `email_poll`, `backup`, `integrity_check`, `ai_task` (bounded by
`ai.max_parallel`, queued only after baseline processing), `geoip_update`, `goaccess_report`. Jobs are idempotent and re-check permissions/state when they run. A crashed worker's lease (30 min) expires and the job is retried with backoff (max attempts then *failed*, retryable in the UI).

## Settings registry {#registry}

`backend/apps/core/registry.py` defines every setting once (validation, default, scope, editor, help link). The UI, API validation and `docs/SETTINGS_REFERENCE.md` (via `manage.py settings_reference`) all come from it; a test fails if the reference is stale or a help link is broken.
