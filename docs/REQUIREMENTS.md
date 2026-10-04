# Requirements (consolidated)

Source: `MASTER_PROMPT_PERSONAL_DOCUMENTS.md` v1.0 (20 Sep 2026), the original requirements note and the UI mockups. Where they disagree, the master prompt wins. Mockups are visual direction only. IDs are used in [TRACEABILITY.md](TRACEABILITY.md).

## Deployment and scope (DEP)

| ID | Requirement |
|---|---|
| DEP-1 | Native install on a Proxmox LXC with Debian 13 (2 vCPU, 4 GB, 50 GB). No Docker. |
| DEP-2 | HTTPS through an existing Nginx Proxy Manager or Pangolin. Trusted proxy configuration, large uploads, streaming. |
| DEP-3 | Local storage for originals. Backups to a NAS or mounted share. |
| DEP-4 | Private GitHub repository. Authenticated install and update without exposing tokens. |
| DEP-5 | Desktop browser and installable mobile PWA. |
| DEP-6 | No cloud database, hosted OCR, paid SaaS or AI in any initial-release workflow. |
| DEP-7 | Single-command install, upgrade, repair, status, doctor, backup, restore and recover-admin. Idempotent and resumable. |

## Accounts and access (ACC)

| ID | Requirement |
|---|---|
| ACC-1 | First-run wizard protected by a one-time code. Creates the six initial accounts (Dad as main administrator and head) with real names. Idempotent; never duplicates. |
| ACC-2 | Immutable account IDs. Role labels are separate from display names. Every managed person has an account. No public registration. |
| ACC-3 | Individually set or generated temporary passwords, changed at first sign-in. The last main administrator cannot be demoted or disabled. |
| ACC-4 | Multiple family groups with heads. Scoped delegation (documents, membership, folder permissions, reminders, notifications) granted only by the main administrator. No escalation. |
| ACC-5 | Distinct capabilities: view, download/export/offline, upload, edit, version, organise, archive, share, manage. |
| ACC-6 | Folder inheritance with subfolder/document exceptions. Default deny. Inspectable effective access. Deterministic precedence. |
| ACC-7 | Server-side enforcement on the API, previews, thumbnails, text, snippets, autocomplete, saved views, counts, versions, archive, shares, downloads, exports and jobs. Rechecked at execution time. |
| ACC-8 | Reminder recipient status and kinship never grant access. |

## Library (LIB)

| ID | Requirement |
|---|---|
| LIB-1 | Arbitrary-depth folders, editable by authorised users. Optional templates. Shared folders. |
| LIB-2 | Folder emoji suggested by name and overridable. Presentation only. |
| LIB-3 | Originals kept byte-for-byte with checksums and configurable safe managed paths. No overwrites. |
| LIB-4 | Deliberate duplicate uploads stay separate. Retries are idempotent. |
| LIB-5 | Versions (better scans) under one record. Renewals as separate linked records. Names derived only from confirmed dates. |
| LIB-6 | Archive instead of delete. Indefinite retention. Only the main administrator restores or purges. Purge removes versions, derivatives and search data. |
| LIB-7 | Metadata: owner, type, issuer, tags, typed custom fields, dates, provenance, history. Bulk edit with partial-failure reporting. |
| LIB-8 | Import wizard (browser and approved server paths) with explicit mapping, exclusions, preview, capacity warning, resumable tracking and report. Server sources are never modified. Traversal and symlink protection. |

## Processing and search (PRO)

| ID | Requirement |
|---|---|
| PRO-1 | Local English OCR (Tesseract/OCRmyPDF) with searchable PDF/A derivatives. Originals untouched. Born-digital PDFs not degraded. |
| PRO-2 | Office previews (LibreOffice). Text previews. DICOM preserved. Unknown formats stored safely. Nothing executed. |
| PRO-3 | Visible processing states and retries. Time, memory, page and pixel limits. Bounded concurrency (default 1). |
| PRO-4 | Proposed details from deterministic parsing, with discrepancy flags. Confirmation required before they affect naming or reminders. Manual entry always possible. Copy buttons. |
| PRO-5 | Full-text search, filters, autocomplete, ranking, highlights, saved views, non-AI similarity. Permission-filtered. |
| PRO-6 | Classification suggestions only, never silent filing. |

## UI (UI)

| ID | Requirement |
|---|---|
| UI-1 | Navigation: Overview, Folders, Shared with me, Offline files, Notifications, Archive, Settings. |
| UI-2 | Login, recovery and TOTP; setup; dashboard; import mapping; three-panel browser; full-page viewer; upload, version and review flows; family administration; sharing; offline manager; notifications; archive; profile; settings; searchable help. |
| UI-3 | Per-account themes (Green, Blue, Black & White) with accessible contrast, visible focus, and non-colour status. |
| UI-4 | Responsive layout without horizontal overflow. PWA with camera/file upload, share-in and share-out with fallbacks. |
| UI-5 | Every setting has a label, description, default, scope, editor, effect, accessible tooltip and help link. Bundled, sanitised help. |

## Offline and export (OFF)

| ID | Requirement |
|---|---|
| OFF-1 | Opt-in offline copies with a manager. Persistent storage requested. Quota errors handled. |
| OFF-2 | Partitioned per account. Defined sign-out behaviour. Revalidation on reconnect. No indiscriminate caching of sensitive responses. |
| OFF-3 | Streaming ZIP exports with manifest, checksums, folder hierarchy and split parts. Audited. |

## Notifications and sharing (NOT)

| ID | Requirement |
|---|---|
| NOT-1 | Global schedule (90/60/30/7/0) set by the main administrator. Stops after the expiry day. Configurable timezone (default Asia/Riyadh) and send time. |
| NOT-2 | Recipients: owner and designated head, plus delegates. Deduplicated. Explicit policies for missed runs, new imports, changed dates, disabled accounts, head changes and renewals. Idempotent keys. |
| NOT-3 | In-app, SMTP and Telegram channels. Admin defaults and required channels. Actionable missing-configuration issues. Never fake delivery. Tests, retries, masked errors, previews. |
| NOT-4 | Minimal message content: no document number, no attachment, login-required link. |
| NOT-5 | Verified Telegram chat linking. |
| NOT-6 | Public links: high entropy, expiry, optional hashed password, rate limiting, revocation, pinned version. Disabled on archive. |

## Email import (MAIL)

| ID | Requirement |
|---|---|
| MAIL-1 | Per-user IMAP accounts and rules (sender, subject, type, size, destination). Connection test. History. Encrypted credentials. Admin can disable without seeing secrets. |
| MAIL-2 | Writable destinations only, rechecked each poll. Idempotent by UIDVALIDITY/UID/part. Messages preserved. |

## Authentication (AUTH)

| ID | Requirement |
|---|---|
| AUTH-1 | Secure hashing, sessions, CSRF, rate limits, generic errors, session rotation. Single-use, expiring reset tokens. |
| AUTH-2 | Optional TOTP with protected secrets and one-use recovery codes. Documented reset path. |
| AUTH-3 | Audited, scoped console recovery for the main administrator. No public backdoor. |
| AUTH-4 | Google linking after recent verification. OIDC validation (issuer, audience, signature, expiry, state, nonce, PKCE). Unique binding by subject. No auto-link or registration. TOTP still enforced. Admin enable/configure with diagnostics and the exact callback URL. |

## Operations (OPS)

| ID | Requirement |
|---|---|
| OPS-1 | Scheduled and on-demand backups to a NAS. Consistent and verified. Includes keys with documented recovery. Mount detection. Retention never prunes the only valid backup. Status reporting. |
| OPS-2 | Restore that recovers accounts, permissions, originals, versions, settings and secrets. |
| OPS-3 | Integrity checker with non-destructive repairs. Disk-pressure detection. |
| OPS-4 | Audit of required events without secrets. Scoped visibility. Configurable retention. |
| OPS-5 | Upgrades with a pre-upgrade backup, controlled migrations, health checks and schema-aware rollback. Repair never resets data or keys. |
| OPS-6 | CI and local verification. Lockfiles. No secrets or private data in the repository. |

## Later phases (not in the initial release)

Local AI providers (OCR, classification, chat, embeddings), personal WhatsApp notifications, native apps, scanning enhancement, in-browser Office editing, DICOM viewing.
