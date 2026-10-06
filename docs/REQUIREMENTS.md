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
| ACC-1 | First-run wizard protected by a one-time code. Creates only the Main Administrator (name, username, password; optional relationship label and email), who becomes head of the initial family group, followed by an optional step to add zero or more family members. No default or placeholder accounts. Idempotent; never duplicates. (Amended by change set L, FAM-1…FAM-4.) |
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
| PRO-1 | Local OCR (Tesseract/OCRmyPDF) with searchable PDF/A derivatives. Originals untouched. Born-digital PDFs not degraded. (Selective and multilingual since change set K, SOCR-1…SOCR-8.) |
| PRO-2 | Office previews (LibreOffice). Text previews. DICOM preserved. Unknown formats stored safely. Nothing executed. |
| PRO-3 | Visible processing states and retries. Time, memory, page and pixel limits. Bounded concurrency (default 1). |
| PRO-4 | Proposed details from deterministic parsing, with discrepancy flags. Confirmation required before they affect naming or reminders. Manual entry always possible. Copy buttons. |
| PRO-5 | Full-text search, filters, autocomplete, ranking, highlights, saved views, non-AI similarity. Permission-filtered. |
| PRO-6 | Classification suggestions only, never silent filing. |

## UI (UI)

| ID | Requirement |
|---|---|
| UI-1 | Navigation: Overview, Folders, Shared with me, Offline files, Notifications, Archive, Settings. |
| UI-2 | Login, recovery and TOTP; setup; Overview; import mapping; three-panel browser; full-page viewer; upload, version and review flows; family administration; sharing; offline manager; notifications; archive; profile; settings; searchable help. |
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

## Change set 2026-10: profile photos, Local AI, security and passkeys

Source: `CHANGE_PROMPT_PROFILE_AI_SECURITY` (amendment to the master prompt). Acceptance tests AT-31…AT-50.

| ID | Requirement |
|---|---|
| PROF-1 | Optional profile photo per account: upload, square crop, replace, remove; initials fallback; admin management. |
| PROF-2 | Photos private: authenticated, visibility-checked serving; content validation; metadata/GPS stripped; bomb protection; never used for identity. |
| AI-1 | Optional Local AI with named profiles (OpenAI-compatible, Ollama), test connection, model discovery, encrypted keys, limits, default profile. |
| AI-2 | Privacy classes Local / LAN / External enforced per request; External needs explicit acknowledgement; no cloud fallback. |
| AI-3 | OCR assist and smart organisation produce suggestions only; persistent changes need confirmation by a person with edit rights. |
| AI-4 | Document assistant and semantic search enforce the same permissions as browsing; revocation is immediate; no existence leaks. |
| AI-5 | AI outages never affect upload, OCR, search, preview, download, reminders or editing; background jobs with bounded concurrency; job visibility without content. |
| SEC-1 | Real client IP only via trusted proxies; NPM and Pangolin documented; doctor diagnostics. |
| SEC-2 | Application login audit (method, IP, local GeoIP country, device, correlation, flags) with admin filters and retention; no secrets. |
| SEC-3 | Local GeoIP database with status, validated updates and fail-safe behaviour. |
| SEC-4 | Pre-authentication country policy (off / block list / allow list), temporary travel access, trusted/blocked IPs, documented precedence, lock-out protection, console recovery. |
| SEC-5 | Security alerts through existing channels with throttling; automatic temporary block after repeated failures. |
| SEC-6 | Optional GoAccess traffic analytics for administrators only; installer/doctor support. |
| PK-1 | Passkeys (WebAuthn) as second factor and optional passwordless sign-in; multiple named passkeys; rename/revoke. |
| PK-2 | Authentication policy (allow TOTP / passkeys / passwordless, require 2FA, recent-auth window) without lock-outs. |
| PK-3 | Recent authentication for sensitive account changes; audited admin and console recovery that reveals no secrets. |
| PK-4 | Standards-based TOTP compatible with password managers; `autocomplete="one-time-code"`; paste allowed. |

## Change set H/I (2026-10): UI, import, notifications, backup, mobile/PWA, viewer, public release

Source: `CHANGE_PROMPT_PERSONAL_DOCUMENTS_PUBLIC_RELEASE` sections 21–24. Acceptance tests AT-61…AT-84.

| ID | Requirement |
|---|---|
| UIX-1 | The signed-in person's own area is shown as "My Documents — <name>" with avatar at the top of the tree; no other trees leak. |
| UIX-2 | File-type icons with readable labels derived from validated content (PDF, JPG, PNG/WebP/images, TXT, DOC, XLS, PPT, ZIP, DICOM, other). |
| UIX-3 | Overview (formerly dashboard) widgets chosen with checkboxes and ordered by drag and drop or keyboard/touch buttons; per-account, synchronised across devices. |
| IMP-1 | Import mapping can choose an authorised destination folder/sub-folder through a folder picker; the preview shows the exact final hierarchy. |
| IMP-2 | The destination replaces only the import root; nested source folders are preserved; existing folders are reused, nothing is overwritten. |
| NOTE-1 | Critical notifications cannot be disabled by members; the administrator chooses critical events and channels; missing destinations are flagged, never reported as sent. |
| NOTE-2 | Optional notifications chosen per event and per channel by each person; preferences cannot override critical events or required channels. |
| NOTE-3 | Consistent detailed templates (site, account, event, date/time, folder/files, device, IP, country, method, link) without secrets; bulk actions consolidated. |
| BAK-1 | Daily, weekly (day + time) and monthly (day of month + time) backup schedules; status, next run, retention independent of frequency; short-month rule. |
| MOV-1 | Reliable drag and drop for documents and folders with server-side validation; atomic moves; self/descendant/denied/conflicting moves refused without data loss. |
| MOV-2 | "Move to…" with a folder picker on every device, using the same server checks. |
| MOB-1 | Functional parity of all major workflows on tablet, phone portrait/landscape and PWA; no unintended overflow; accessible controls. |
| MOB-2 | Account-level preferences synchronise across devices; device-local exceptions documented. |
| VIEW-1 | Full-page (and panel) viewer with zoom in/out, percentage, fit page, fit width, 100 %, full screen, page navigation and keyboard shortcuts for PDF and images. |
| VIEW-2 | Viewer keeps authorisation, never uses external viewers, fails safely on damaged files with Download available. |
| PUB-1 | Public authorship: Atik Ansari as sole author/maintainer; no AI assistant as author; Git history not rewritten. |
| PUB-2 | Secret/privacy audit of the tree and history; comprehensive .gitignore; safe env example; automated check. |
| PUB-3 | Public README with sanitised screenshots, user guide, administrator guide, CONTRIBUTING, SECURITY; MIT license (owner decision). |

## Change set J (2026-10): browsing, OCR quality, one-line installer, public presentation

Source: `CHANGE_PROMPT_PERSONAL_DOCUMENTS_PUBLIC_RELEASE` V3 section 25. Acceptance tests AT-85…AT-100.

| ID | Requirement |
|---|---|
| MENU-1 | Overflow menus render above every panel, are positioned from their trigger, stay in the viewport, support keyboard, Escape and outside click, and only one is open at a time. |
| MENU-2 | Document actions: Open, Rename, Move to, Download, Share, Archive; Permanent delete only where permitted. Folder actions: Open, Rename, Move to, Change icon, Share/permissions, Archive. Unauthorised actions hidden; destructive actions confirmed and audited. |
| ICON-1 | Top-level semantic folders keep emoji defaults; user-created sub-folders default to the standard folder icon; icons chosen from an approved list with Reset to default; stored as metadata and preserved through move, import, backup and upgrade. |
| VIEWS-1 | List, Thumbnail/Grid and Details views with sorting, selection, menus and empty/loading/error states; persisted per user and synchronised across devices. |
| DROP-1 | Files and folders dragged from the desktop upload into the target; the folder hierarchy is recreated beneath the destination; paths are validated (no traversal); progress and failures are shown; nothing is discarded silently; explicit fallback when the browser cannot provide the hierarchy. |
| TREE-1 | The signed-in user's library is at the top of the tree and expanded by default; other trees are never auto-expanded. |
| OCR-1 | OCR preprocessing (EXIF, rotation, deskew, grayscale, contrast, threshold, denoise, upscale, PSM) is benchmarked on synthetic samples and only measured improvements are adopted. |
| OCR-2 | OCR confidence is stored and displayed; junk stays out of metadata; OCR can be re-run with a rotation. |
| OCR-3 | Candidate fields (number, dates, name) are extracted as suggestions; "No Expiry Date" is represented as non-expiring; confirmed values are never overwritten. |
| PUB-4 | Public title "Personal Documents Management System" in the UI, README, package metadata, docs, installer, PWA manifest and Help; internal identifiers unchanged. |
| PUB-5 | Public screenshots use demo data only; identities are synthetic (since change set L the demo labels A. Ansari, Mom, Son1, Son2, Son3 and Daughter, see FAM-5). |
| PUB-6 | Atik Ansari as sole author in manual credits and metadata; Git history not falsified. |
| INST-1 | Root `personal-DM.sh` runnable as `bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)"` for install, upgrade, repair, doctor, status, backup, restore and admin recovery (menu and commands); Debian 13 and root checks; idempotent; data preserved; backup first; fails loudly; shows logs; no secrets. |
| PUB-7 | LinkedIn-ready README (value proposition, badges, screenshots near the top, features, architecture, one-line install, security/privacy, OCR/AI, mobile/PWA, docs, roadmap, support, author); Ko-fi support link and `.github/FUNDING.yml`; recommended topics. |

## Change set K (2026-10): selective OCR, Overview widgets, sign-in designs

Acceptance tests AT-101…AT-130.

| ID | Requirement |
|---|---|
| SOCR-1 | OCR policy per document type: Disabled, Manual or Automatic, with default languages, expected fields and whether Local AI may read the text. New installations default to Manual; documents without a type follow a separate setting. Existing installations keep automatic OCR with AI allowed after upgrade. |
| SOCR-2 | Administrators add and archive custom document types; built-in types and types in use are never deleted. |
| SOCR-3 | A person with edit rights chooses the source files (for example front and back as one job), the pages of a PDF (all, single pages, ranges) and the languages. Automatic OCR processes only the primary OCR source. |
| SOCR-4 | English, Arabic and Hindi offered by default, further Tesseract languages selectable; missing language packs reported by doctor and installed by install, upgrade and repair. |
| SOCR-5 | Visible OCR states (Not processed, Queued, Processing, Needs review, Confirmed, Failed, OCR removed); Run, Re-run, Cancel and Mark reviewed; re-runs never overwrite confirmed values. |
| SOCR-6 | Remove OCR data deletes recognised text, its search entries and unconfirmed suggestions; the original file and confirmed details are kept. |
| SOCR-7 | OCR review queue listing only documents the person may edit. Limits for file size, pages per job, queue length and attempts; the queue can be paused without losing jobs. |
| SOCR-8 | Local AI reads OCR text only for document types (or untyped documents) where AI is allowed. |
| OVW-1 | Overview page with accessible, labelled widgets: Today, Weather, Documents summary, Month calendar, Upcoming holidays, Expiring soon, Shared with me, Recent documents, Recent activity and the earlier widgets; only documents the person may see. |
| OVW-2 | Customize Overview: add, remove, reorder (drag and buttons), resize on a responsive grid with per-widget limits, styles (rectangular, compact, circular only for single-value widgets), widget settings, reset and cancel; stored per account and synchronised across devices. Saved widget choices survive upgrades. |
| OVW-3 | Gregorian and Hijri date (Umm al-Qura via a maintained library) in the installation timezone, with an administrator adjustment of up to ±2 days. |
| OVW-4 | Month calendar and upcoming holidays from a maintained holidays library (no hard-coded dates); default Saudi Arabia and India; administrator-selected countries; moon-dependent holidays marked Provisional with their source; administrator corrections (confirm, rename, add, hide) with status and source. |
| OVW-5 | Optional weather widget, off by default: server-side provider access with a shared cache, per-person city, only coordinates sent, encrypted API key, connection test, stale and unavailable states without breaking the Overview. |
| LOGIN-1 | Sign-in page designs: bundled presets (Minimal default, Nature, Travel, Family, Neutral), wallpaper left and sign-in panel right, phone layout with the form first. Sign-in methods identical with every design. |
| LOGIN-2 | Custom wallpaper and logo uploads validated by content and size, re-encoded with metadata removed, stored locally and backed up; preview, position, overlay, title, tagline, remove and reset. |

## Change set L (2026-10): family setup model

Acceptance tests AT-131…AT-137.

| ID | Requirement |
|---|---|
| FAM-1 | Clean setup creates only the Main Administrator; no default family accounts, placeholder members or hard-coded names. |
| FAM-2 | Optional "Add family members" step with zero, one or many validated rows (name, username, relationship with suggestions, optional email and password) and Skip for now; generated temporary passwords must be changed at first sign-in. |
| FAM-3 | Members can be added later in Settings → Family & access. |
| FAM-4 | Upgrades keep every existing account, folder and document; deactivating or removing a member never silently deletes documents. |
| FAM-5 | Screenshot and documentation names are demo labels (A. Ansari, Mom, Son1, Son2, Son3, Daughter) added in the optional step, never defaults. |

## Later phases

Personal WhatsApp notifications, native apps, scanning enhancement, in-browser Office editing, DICOM viewing.
