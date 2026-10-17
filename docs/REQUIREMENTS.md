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
| UI-1 | Navigation: Overview, Folders, Shared with me, Offline access, Notifications, Archive, Settings. |
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

## Change set M (2026-10): antivirus, authentik, security center, storage health

Acceptance tests AT-138…AT-160.

| ID | Requirement |
|---|---|
| ROLE-1 | An **Administrator** role, set only by the main administrator (or by an authentik group mapping), gives access to the security center and administrator security notifications and never grants document or folder access. The "administrators" two-step verification policy covers it. |
| AV-1 | Every new file is scanned in the background by a local ClamAV daemon over its Unix socket (no TCP); uploads are never held up and each file shows a status (pending, clean, not scanned, size limit, scan failed, threat, quarantined, released). |
| AV-2 | Fail-open: when ClamAV is unavailable, files stay stored and usable, are marked Not scanned, and administrators get a critical alert. Archives are scanned as one file. |
| AV-3 | A detected file is moved to a quarantine readable only by the service; preview, download, sharing, export, OCR and Local AI are blocked; metadata stays. |
| AV-4 | Only the main administrator releases (warning, confirmation, reason of at least 10 characters, audited) or permanently deletes (typed confirmation) a quarantined file; Administrators can view but not release. |
| AV-5 | Maximum scan size (default 50 MB); larger files are stored and marked Not scanned — size limit exceeded, never Clean. |
| AV-6 | Library scan with progress, pause, resume and cancel; optional daily, weekly or monthly re-scan (default disabled); files stored before the upgrade are marked Not scanned until scanned. |
| AV-7 | Automatic signature updates (freshclam) plus Update now through the host helper; stale (2 days) and critically stale (7 days) thresholds; threat, release, unavailable, scan failure, stale and update-failure notifications are critical and cannot be turned off. |
| AV-8 | Quarantined files are excluded from backups and from integrity "missing" reports; the installer configures clamd (local socket only) and can be skipped with `--without-antivirus`. |
| AUTHK-1 | authentik as an additional OpenID Connect sign-in (discovery, HTTPS issuer only, PKCE, state, nonce, token signature/issuer/audience checks), with an encrypted client secret, configurable scopes, label and logo, and a connection test. Local sign-in always stays available; enabled two-step verification is still asked. |
| AUTHK-2 | Accounts are linked only by the signed-in person after recent re-authentication, never by matching email; the main administrator views and revokes links without touching the account or its documents. |
| AUTHK-3 | Provisioning defaults to existing accounts only; optional automatic provisioning creates member accounts only, never the main administrator. |
| AUTHK-4 | Optional group-to-role mapping to Member or Administrator only; never changes the main administrator, never grants document permissions; every change audited. |
| SEC-1 | Deployment exposure (LAN only / Internet); Internet Ready only when HTTPS with a valid certificate, HTTP→HTTPS redirect, Secure cookies, security headers and HSTS pass for the public origin. HSTS is sent for HTTPS origins (`PD_HSTS_SECONDS`, default one year). |
| SEC-2 | A Basic Internet Security Test started only by an administrator (never during install or upgrade), limited to this application and this host, with categorised findings (Passed/Warning/Failed, severity, remediation), comparison with the previous run and one year of history. |
| SEC-3 | Warning-only policy: Critical and High findings never block the application, are never shown as a pass, and notify administrators. |
| SEC-4 | Debian security updates listed and installed on request through a root host helper with fixed actions, after a database and settings backup (failure blocks unless overridden with an audited reason); logs kept; no unattended updates; manual commands shown without the helper. |
| SEC-5 | Reboot required shown; controlled reboot with preflight warnings (sessions, running jobs), worker and scheduler drained, duplicate requests refused, service health shown afterwards. |
| SEC-6 | Firewall and listening services are monitored only (ufw/nftables state, unexpected exposure such as ClamAV or PostgreSQL); no control changes firewall rules. |
| SEC-7 | Administrator-only Security Health score 0–100 (antivirus 20, HTTPS 20, security test 20, OS updates 15, firewall 10, reboot 10, authentik 5) with Healthy/Attention/At Risk bands and forcing conditions that always give At Risk. Not presented as a certification. |
| SEC-8 | Security records kept for a configurable period (default and minimum 365 days) with nightly cleanup; manual purge with cleanup analysis, confirmation and a 30-day minimum; the purge record, records about quarantined files and the latest test are protected. |
| STOR-1 | Storage Health with total, used, free and per-category usage, warning (80 %) and critical (90 %) thresholds with notifications. |
| STOR-2 | Safe cleanup only of regenerable or expired data (temporary files older than 24 hours, orphan previews and OCR copies, expired security records) with analysis and confirmation. Original documents are never deleted by any cleanup, purge, antivirus, update or repair workflow. |
| OPS-M1 | `personaldocs status` and `doctor` report ClamAV, freshclam, the host helper, signature age, files pending scan, Internet HTTPS, storage thresholds and a pending reboot; install, upgrade and repair install ClamAV and the host helper; `--with-security-tools` adds pip-audit. |

## Change set N (2026-10): document types, metadata templates, field sources and type assignment

Acceptance tests AT-161…AT-175. Guide: [document types](guides/document-types.md).

| ID | Requirement |
|---|---|
| DT-1 | Folder and document type are independent: moving a document never changes its type and changing the type never moves the file. |
| DT-2 | Document types are editable data (seeded, not code constants) managed by the main administrator: add from a standard template or a copy, edit name, icon, description, expiry awareness and per-type reminder days, archive/restore, delete only when unused or after moving its documents to another type with the value-preserving rules. |
| DT-3 | Each type has a template of fields with a stable key, label, field type (text, long text, date, number, yes/no, select, country, person, identifier), shown/required flags, order, help text, OCR/AI extraction flag, searchable flag, role (expiry, issue, no expiry), choices and validation (pattern, minimum, maximum, maximum length); fields with values are turned off, not deleted; reordering is keyboard accessible with a preview. |
| DT-4 | The Details panel shows the owner, the document type (Set type / Change… for editors, read-only for viewers, "Not assigned" when empty, Manage for the main administrator), a details status (confirmed, incomplete with the required fields, needs review) with "Confirm as incomplete", the template fields in order, additional details and previous details. The type can be set from the upload dialog, the Details panel, the document ⋮ menu / More actions and bulk Set type…. |
| DT-5 | Every value records its source (manual, OCR, MRZ, Local AI, import, system, migrated), whether it is suggested or edited, and who confirmed it when; confirmed values are never overwritten by OCR, re-maps or AI (a differing value is shown as "New scan suggests …"). |
| DT-6 | Type suggestions from the folder, from OCR text (with reason and confidence) and from the local AI are suggestions only (Accept / Change / Ignore); conflicting suggestions are shown as a conflict; a confirmed type is never silently replaced. |
| DT-7 | Changing a type shows a preview (values kept, values that become previous details with the reason, additional details, new empty fields, a warning when the expiry field no longer applies); unmapped values are kept as previous details to map, keep or remove; nothing is deleted. |
| DT-8 | After a type change, existing OCR text can be re-mapped to the new type's fields without a new OCR scan, as suggestions only. |
| DT-9 | One-off additional details never change the template; the main administrator can promote one to a template field after confirmation, moving only that document's value. |
| DT-10 | Bulk Set type… previews counts and current types, skips documents with another confirmed type unless explicitly overridden, skips documents the person may not edit, and uses the same safe change per document. |
| DT-11 | Viewers see the type read-only; editors assign types, edit values and add details; only the main administrator manages templates, promotes fields and reviews untyped documents. Type changes, bulk changes, re-maps, reviews and template changes are audited and recorded in the document history without OCR text. |
| DT-12 | Search filters by type, indexes values of searchable fields (identifiers not searchable by default), and the OCR review queue filters by type (All / Not assigned / a type). OCR and the local AI propose only template fields marked extractable. |
| DT-13 | Only the confirmed value of the expiry-role field drives the expiry date and reminders; per-type reminder days override the global setting; a type change re-derives the expiry date and never invents one. |
| DT-14 | The upgrade migration gives every type a template, keeps typed documents' types (confirmed, source migrated), leaves untyped documents untyped, keeps values outside the template as additional details (confirmed issue/expiry/no-expiry fields are added to the template), and deletes nothing. A folder can carry a suggested type for uploads (inherited by sub-folders); an administrator review of untyped documents applies nothing until confirmed. |
| DT-15 | The Details panel, type selection and previous details work by touch at tablet and phone sizes without clipping. |
| OPS-N1 | `personaldocs manage document_types report` and `personaldocs doctor` report typed, untyped and suggested counts; no new system packages; the migration is applied by the normal upgrade after the verified backup. |

## Change set O (2026-10): rich notification formatting, icons, templates and interactive actions

Acceptance tests AT-176…AT-195. Guide: [notifications](guides/notifications.md).

| ID | Requirement |
|---|---|
| RN-1 | Every notification is one structured message (event, severity critical/warning/success/info, category, semantic icon, title, heading, summary, details with icons, actions, guidance, items, link, placeholder context, TEST flag) rendered by one renderer per channel: in-app, email, Telegram and push. |
| RN-2 | Email is multipart: a plain-text part in the earlier layout and a responsive HTML part (header, severity and category as text, headline, summary, details table with icons, buttons, guidance, footer) using a table layout with inline CSS, no JavaScript, no images or tracking pixels, and `dir="auto"` for right-to-left text. |
| RN-3 | Telegram messages use HTML parse mode with escaped values and an emoji per detail; inline URL buttons only when the application has an `https://` address (otherwise links in the text); a rejected rich message is resent as plain text. |
| RN-4 | A Notification Center shows each person only their own notifications as cards (icon, severity and category as text, title, summary, time, unread state, actions, details, files, guidance) with Mark read/unread, Mark all read, filters (All/Unread, category, severity) and cursor paging; up to three banners for new warning, critical and success notifications; critical notifications stay in the Notification Center. |
| RN-5 | Web Push as a fourth channel: VAPID keys created on first use and stored encrypted (backed up); payloads encrypted (aes128gcm) and signed with maintained libraries; subscriptions accepted only for known push services over HTTPS and never for internal addresses or URLs with credentials; expired subscriptions removed; per-person lock-screen detail (Minimal, Standard, Detailed) and never document numbers or text; turned on per device and never added to anyone's channels automatically; an administrator switch turns push off. |
| RN-6 | Event-specific actions are application paths only, without tokens, and opening them requires sign-in and the normal permission checks; paths to the API or to a quarantine release are refused; release from quarantine is never offered in a message. Snooze of expiry reminders is in-app only and per person. |
| RN-7 | The main administrator can override, per event and channel (or all channels), the title/subject, heading, summary (plain text with an allowlist of placeholders), icon (from the central list), severity shown and action labels (no placeholders); unknown placeholders and other braces are refused; no code or HTML is interpreted and all values are escaped per channel; changes and resets are audited. |
| RN-8 | Live previews for email desktop, email mobile (sandboxed frame), Telegram, in-app, push and plain text; TEST sends to the administrator on chosen channels with sample data, marked TEST, creating no real event and only the audit entry `notifications.test_sent`. |
| RN-9 | Critical events cannot be shown below Warning and template or preference changes never remove a critical event or a required channel. |
| RN-10 | Recurring conditions (antivirus unavailable, stale signatures, signature update failure, storage warning/critical) are not repeated to the same person within `notifications.repeat_cooldown_hours` (default 24, 1–168); new critical events are sent at once; expiry reminders follow their schedule; idempotency keys prevent duplicates; bulk actions produce one summary. |
| RN-11 | Messages handle Unicode and right-to-left text and use the installation time zone and date format. |
| RN-12 | A delivery history lists external messages with event, recipient, channel, state (queued, retrying with the next try, sent, failed, skipped), attempts, "accepted by the provider" when a provider message id exists, errors with credentials redacted, filters by channel and state, and TEST rows marked; it never claims delivery to the device. |
| RN-13 | Expiry messages use the document type (or "Document (type not assigned)"), the confirmed full name (otherwise the owner), the expiry date of the expiry-role field, days left and the folder; severity ≤ 7 days or today critical, ≤ 60 warning, otherwise information; the document number is hidden by default and shown masked (last four characters) in email, Telegram and in-app only when `notifications.include_document_number` is on, never in push; unconfirmed values are never shown. |
| RN-14 | Security and system events use the policy severity and audience: antivirus events critical and for administrators only; OS security updates installed (success, or warning when a reboot is required) and failed (critical); reboot requested (warning); security test with Critical/High findings (critical); storage warning/critical; authentik link/unlink to the person (critical by default). |
| RN-15 | The Notification Center, filters and actions work by touch at tablet and phone sizes without clipping and pass the accessibility audit; icons have accessible labels and severity is never shown by colour alone. |
| OPS-O1 | One migration (`notify.0002_rich_notifications`) and two Python packages (`http-ece`, `py-vapid`) installed by the normal upgrade after the verified backup; existing notifications are classified without changing their text, links or read state; SMTP/Telegram configuration, preferences, critical events and channels and expiry schedules are unchanged; no post-upgrade step. |

## Change set P (2026-10): sign-in screen passkeys, administrator password reset, security templates, ClamAV repair

Acceptance tests AT-196…AT-210 (the change prompt numbered them AT-176…AT-190; see the mapping in
[TRACEABILITY.md](TRACEABILITY.md) (section *Change set P*)). Guides: [passkeys](guides/passkeys.md),
[password reset](guides/password-reset.md), [notifications](guides/notifications.md#security-templates),
[antivirus](guides/antivirus.md#diagnose).

| ID | Requirement |
|---|---|
| AP-1 | The sign-in page offers, in this order: email or username and password; an "or" separator; **Sign in with Passkey**; then authentik and Google only when enabled. On a non-secure (plain http) address the passkey button is disabled with the note "Passkeys need the secure HTTPS address of this app". |
| AP-2 | The username field offers saved passkeys through the browser's autofill (WebAuthn conditional mediation, `autocomplete="username webauthn"`) where the browser supports it. |
| AP-3 | Passwordless sign-in uses a discoverable credential with user verification required, a single-use challenge (replay refused), and origin and relying-party-ID checks; it needs neither username nor password. |
| AP-4 | A setting `auth.passkey_mode` chooses **Passwordless** (default) or **Password + Passkey** (`mfa`) and replaces `auth.allow_passwordless`. Its migration keeps an explicit earlier choice (saved off → mfa, saved on → passwordless, never chosen → passwordless) and, in passwordless mode, turns passwordless on for accounts that already have a discoverable passkey. In mfa mode passkeys are only the second step after the password. |
| AP-5 | In both modes the main administrator's password, recovery codes and `personaldocs recover-admin` console recovery keep working; nobody is locked out by a mode change. |
| AP-6 | Enrolling, renaming and removing a passkey need a recent confirmation, are audited (`account.passkey_register`, `account.passkey_rename`, `account.passkey_revoke`) and notified. Enrolling a discoverable passkey in passwordless mode turns passwordless on for that account; the person can turn it off. |
| AP-7 | Sign-in accepts an email address instead of the username when the address belongs to exactly one active account. |
| AP-8 | Administrators (main administrator, Administrator role) can reset another account's password after a recent confirmation, with **Generate temporary password**: 16 cryptographically random characters returned once (`Cache-Control: no-store`), stored only as a hash, never emailed, logged or notified; the person must change it at the next sign-in; all their sessions end and earlier reset tokens are invalidated; audited as `family.password_reset_by_admin` with method `temporary_password` and never the password; the person and the other main administrators are notified without the password. |
| AP-9 | **Send password reset email**: a branded HTML and plain-text email with a single-use link valid `auth.reset_token_minutes` (default 30, 5–1440); only the token's hash is stored; a newer request or any password change invalidates older links; a successful reset invalidates the link and sends "Password reset completed". The link is sent directly by email and never stored in the outbox, in-app history, Telegram, push or logs. On an Internet deployment links are sent only when `PD_PUBLIC_ORIGIN` is https. Self-service "Forgot password?" uses the same email. Audited as `family.password_reset_email`. |
| AP-10 | An Administrator who is not a main administrator cannot reset a main administrator's password (403 with a hint to the console recovery); nobody resets their own password through this function; non-administrators cannot use it. |
| NT-S1 | New security events, critical by default: password reset requested, administrator reset your password, temporary password issued, password reset completed, account locked (to the person and the administrators, once per lock window, never with the attempted password) and Google account linked or removed. |
| NT-S2 | Every security event carries mandatory security text, shown on email (HTML and plain text), Telegram and in-app, which a template can neither remove nor change; the Template Manager shows it as locked. |
| NT-S3 | Templates also offer a branding name (≤ 60 characters, email header) and a footer / help text (≤ 300 characters), with the same allowlisted placeholders and escaping and without code or raw HTML; HTML email always keeps its plain-text part; the reset email's button label is the `reset_password` action label. |
| NT-S4 | Messages never contain passwords (temporary or attempted), one-time codes or reset tokens, except the reset link in the reset email itself. |
| AV-R1 | A diagnosis shared by the command line, the root host helper and the web app checks packages, signatures, the `clamav-daemon` service (including a skipped start condition and its last result), the `clamav-daemon.socket` unit, freshclam, the restart policy, the effective socket path (socket unit versus `LocalSocket`), the absence of a TCP listener, `/run/clamav`, the socket file (type, owner, group, mode), a stale pid, access by the service account, version, a clean + EICAR scan self-test, memory and journal hints, and names the likely cause. |
| AV-R2 | Cached engine and signature versions are never treated as proof that scanning works; when ClamAV is unreachable they are shown as "last seen". |
| AV-R3 | A root repair, safe to repeat, installs missing packages, sets `LocalSocket` to the systemd socket path, removes TCP listeners, sets the required clamd options (with a one-time backup and `clamconf` validation), downloads missing signatures, enables and starts the socket and the daemon in order, waits for `PONG`, and reports success only when the final state is Healthy or Degraded. It never opens a TCP port. |
| AV-R4 | Install, upgrade (post-upgrade), repair and the web app's **Repair antivirus** (host-helper action `antivirus_repair`, no browser-supplied commands) use this repair; afterwards the app's `antivirus.socket` is synced to the effective socket. `personaldocs antivirus status|repair|selftest` and `doctor` expose it on the command line. |
| AV-R5 | An administrator self-test scans a harmless file and the EICAR test file from a private 0700 temporary directory through the upload scan path, deletes them, creates no document or quarantine entry, uses no live malware and is audited (`antivirus.self_test`). |
| AV-R6 | The diagnose, self-test and repair endpoints (`/api/security/antivirus/diagnose`, `/selftest`, `/repair`) are for administrators only. |
| AV-R7 | The repair is persistent: a restart drop-in (`Restart=on-failure`, `RestartSec=15s`) for `clamav-daemon.service` and a tmpfiles entry for `/run/clamav`. |
| AV-R8 | Upload behaviour is unchanged after repair: pending → Clean; EICAR → Threat detected → Quarantined; scanner unavailable → Not scanned (fail-open, critical alert); oversize → Not scanned — size limit exceeded; only administrators re-scan and only the main administrator releases. |
| AV-R9 | Health states Healthy (reachable and a real scan works), Degraded (non-fatal issue such as stale signatures), Unavailable (unreachable), Error (cannot scan or last self-test failed) and Turned off drive the Security Health score: Unavailable and Error give 0 antivirus points and force At Risk. The hourly check runs the self-test once a day and after a failure. |
| OPS-P1 | Two migrations (`accounts.0007_passkey_mode`, `notify.0003_template_brand_footer`), no new packages; the post-upgrade step runs the ClamAV repair automatically; existing accounts, passkeys and templates are kept. |

## Change set Q (2026-10): PaddleOCR (PP-OCRv5) and the complete OCR lifecycle

Acceptance tests AT-211…AT-230 (the change prompt numbered them AT-191…AT-210, prompt AT-n = AT-(n+20); see
[TRACEABILITY.md](TRACEABILITY.md), section *Change set Q*). Guides: [OCR engines](guides/ocr-engines.md),
[OCR, details and corrections](guides/ocr-corrections.md). Decision: [ADR 0016](adr/0016-paddleocr-ocr-lifecycle.md).

| ID | Requirement |
|---|---|
| OQ-1 | PaddleOCR with PP-OCRv5 models is the default OCR engine; Tesseract stays available as *Legacy / Fallback* and as an explicit choice. OCR stays local: no document image, page or text is sent to an external service. |
| OQ-2 | The PaddleOCR runtime is isolated from the application environment (own virtual environment, pinned versions), runs CPU-only through the sandbox with a memory limit, a CPU limit and a timeout, and never downloads models while recognising. |
| OQ-3 | *Healthy* means a real inference self-test succeeded; installed packages or a successful import alone are not healthy. The health is shown in Settings, in `personaldocs ocr status` and in `personaldocs doctor`. |
| OQ-4 | Every OCR result records engine, engine version/model, language profile and date; historical results are labelled Tesseract or Unknown and never relabelled as PaddleOCR. |
| OQ-5 | Changing the default engine never triggers library-wide OCR; existing documents are re-processed only by an explicit administrator action. |
| OQ-6 | Language profiles English, Arabic + English, Hindi (Devanagari) + English, Telugu + English and Tamil + English route to the matching PP-OCRv5 models (and to the equivalent Tesseract languages); the administrator chooses which are offered, the default profile and a profile per document type. |
| OQ-7 | On a 6 GB / 4 vCPU server OCR runs one job at a time with bounded memory and CPU; a crash, timeout or memory-limit stop fails visibly once and keeps the previous result. |
| OQ-8 | Per document: Run / Re-run OCR (sources, pages, engine, profile), View OCR text (with engine label), Remove OCR data, Disable / Enable OCR for this document. |
| OQ-9 | Remove OCR data deletes recognised text, positions, confidences, every searchable copy, the search entries built from them, unconfirmed suggestions, raw OCR excerpts, Local AI suggestions, semantic chunks and queued Local AI work; it keeps originals, versions, manual and confirmed details, ownership, permissions and audit history; optionally it also hides the embedded text layer. Running OCR or AI jobs cannot bring the removed text back. |
| OQ-10 | Disable OCR for this document prevents every regeneration (Automatic type, Regenerate preview, repair, bulk re-process) until enabled again; the person decides whether the existing text is kept or removed. |
| OQ-11 | Removal, disabling, bulk actions, orphan cleanup, self-tests and OCR tests are audited without any recognised text. |
| OQ-12 | Administrator *Existing OCR data*: counts by engine (PaddleOCR / Tesseract / Unknown), searchable, disabled, failed and queued, storage used, filters, and bulk Remove / Remove and disable / Disable / Enable / Re-process / Set profile with a mandatory preview, run in throttled batches. |
| OQ-13 | Re-processing is staged: the new result replaces the old one atomically only when every source succeeded; confirmed details are never overwritten. |
| OQ-14 | Orphan analysis is a dry run; cleanup removes only the verified derived orphans (unreferenced searchable copies, stale scratch folders, leftover blocks, chunks, suggestions, abandoned runs), never originals, versions, confirmed details, previews or running jobs. Storage Health shows OCR text, cache, orphans and models. |
| OQ-15 | *Test OCR / Compare engines* (administrator only) runs a sanitised file outside the library, reports diagnostics and character accuracy against expected text, never treats engine confidences as comparable, and deletes its temporary files. |
| OQ-16 | Local AI keeps reading only the OCR text of types where it is allowed; it works with PP-OCRv5 output and never overwrites confirmed details. |
| OQ-17 | Install, upgrade, post-upgrade and repair install the runtime and the models of the offered profiles and run the self-test; a CPU without AVX, too little disk or `--without-paddleocr` leaves Tesseract working. Models and settings persist across restarts, upgrades and repairs. |
| OQ-18 | A representative benchmark compares PP-OCRv5 and Tesseract on the samples actually available; categories without samples are reported as Not Run, never fabricated. |

## Change set R (2026-10): application-wide UI alignment, responsive layout and visual regression

Acceptance tests AT-231…AT-245 (the change prompt called this "Change Set Q" with AT-211…AT-225; prompt AT-n =
AT-(n+20); see [TRACEABILITY.md](TRACEABILITY.md), section *Change set R*). Guide: [UI layout rules](guides/ui-layout.md).
Decision: [ADR 0017](adr/0017-ui-layout-primitives.md).

| ID | Requirement |
|---|---|
| UI-1 | The reported preview-header defect is reproduced and its root cause documented before the fix. |
| UI-2 | The document header uses the available panel width: the title wraps only at meaningful boundaries, the status badges (OCR, antivirus, expiry, archived) stay together as one group, file name, size and version stay inline where space permits and wrap deliberately otherwise, and actions never squeeze the information column. |
| UI-3 | Long document, folder and file names, metadata and help tables have defined behaviour (natural wrapping, wrap-anywhere for names without spaces, sideways scrolling for wide tables); security, expiry and error meaning is never hidden by truncation. |
| UI-4 | Layout adapts deliberately: wide desktop uses horizontal space, narrow panes and tablets reflow into rows, phones stack title → badges → details → actions → viewer; components in panes respond to the pane width (container queries). |
| UI-5 | The three-panel Folders screen keeps usable minimum widths, switches to a two-panel mode with the document at full width below 1280 px, and to one panel at a time on phones. |
| UI-6 | Icon + text controls, badges and status elements align consistently through shared flex primitives; no page-specific pixel offsets, negative margins, JavaScript text measuring, overflow hiding or font shrinking as a fix. |
| UI-7 | An automated audit covers the screens of the change prompt's audit scope at 1920×1080, 1440×900, 1366×768, tablet landscape and portrait, and about 430 and 390 px; geometry of the document header is regression-tested against a reviewed baseline. |
| UI-8 | Menus, dropdowns and dialogs stay inside the viewport and are keyboard and touch reachable; icon-only buttons have accessible names; focus stays visible; DOM order stays logical. |
| UI-9 | Arabic and mixed-character metadata and file names do not break the audited layouts (the application itself stays left-to-right). |

## Change set S (2026-10): offline access, PWA identity, premium themes and public screenshot quality

Acceptance tests AT-251…AT-275 (the change prompt called this "Change Set R" with AT-226…AT-250; prompt AT-n =
AT-(n+25); see [TRACEABILITY.md](TRACEABILITY.md), section *Change set S*). Guides:
[offline access](guides/offline-export.md), [phone and tablet (PWA)](guides/mobile-pwa.md), [themes](guides/themes.md),
[public screenshots](guides/screenshots.md). Decisions: [ADR 0018](adr/0018-offline-device-scope.md),
[ADR 0019](adr/0019-theme-tokens-glass.md).

| ID | Requirement |
|---|---|
| OF-1 | Offline state is scoped by account + device (browser profile or installed app) + folder/document; a choice on one device or account never downloads anything for another. |
| OF-2 | The folder **⋮** menu offers *Make available offline… / Update offline copy / Remove offline copy* only with download permission; making a folder available offers *This folder and all subfolders* (default, recommended) or *This folder only*, and shows document and subfolder counts, estimated size, free storage and large-download / quota warnings. |
| OF-3 | The document **⋮** menu offers *Make available offline / Update offline copy / Remove offline copy*. |
| OF-4 | Offline status per document — available, downloading/updating with progress, update available, outdated, failed, locked, not available — is shown with icon and text, never colour alone, and announced to assistive technology while it changes. |
| OF-5 | The Offline access page shows the current device, offline folders and documents, counts, storage used and limits, last sync, pending updates and failures, with Sync now, Update all, Manage storage and Remove offline copy; other devices of the account can be renamed or forgotten. |
| OF-6 | Every sync re-validates access server-side (download permission, archive, antivirus quarantine, deselection, account and global capability) before new content is downloaded, and deletes anything no longer permitted. |
| OF-7 | Sign-out follows the administrator's policy (remove unless the person chose to keep, or always remove); copies lock after a configurable number of days without a sync; the limitation that an offline device cannot be erased remotely is documented. |
| OF-8 | Caching of recognised/extracted text offline is an independent administrator policy, off by default; removed OCR disappears from devices at the next sync. App shell, originals, offline text, index and API answers are stored separately; protected originals are never in a shared or generic cache. |
| OF-9 | The main administrator can turn offline copies on/off globally and per person, request removal from a device, and set automatic updates, the sign-out policy, the lock period, the suggested per-device space and the large-download threshold (Settings → Offline & PWA). |
| PW-1 | The installed app identity is *Personal DM* with a green document-and-shield icon generated from one master SVG: 512/192 *any*, 512/192 *maskable* (artwork inside the safe zone), 180 Apple touch icon (opaque), 32/16 favicons and `favicon.ico`. |
| PW-2 | Manifest `id`, `name`, `short_name`, `start_url`, `scope`, `display`, `theme_color`, `background_color`, icon paths, types, sizes and purposes validate; identity files load without authentication with correct content types; missing file paths answer 404 instead of the app page. |
| PW-3 | Apple touch icon, `apple-mobile-web-app-title` and `-capable` markup is explicit; doctor and check-access report missing icons and proxies that require sign-in for them; the fresh-install procedure for iPhone/iPad is documented. |
| TH-1 | Themes use semantic tokens (surfaces, elevation, navigation, text, borders, accent, status, focus, shadow, radius, overlay, viewer, glass); components do not hard-code theme colours. |
| TH-2 | Presets: Default Green (default, unchanged), Blue, Dark, Glass Light, Glass Dark (Black & White kept), selectable per account through preview cards with Reset to default; the choice follows the account to every device and never changes another person's theme. |
| TH-3 | Glass effects are selective (navigation, top bar, cards, menus, dialogs; never nested), content stays readable, an opaque fallback applies without `backdrop-filter` or with reduced transparency, and phones use a reduced effect budget. |
| TH-4 | Every theme keeps visible focus, sufficient contrast, status meaning without colour alone, and respects reduced motion; document pages stay on white. |
| SS-1 | Public screenshots are captures of the real application with synthetic demo data, at a consistent 1440×900 (phones 390×844) and device pixel ratio 2, after fonts and animations settle. |
| SS-2 | Captures pass automated quality (no overflow, clipped text, broken images) and privacy gates (no e-mail outside example domains, no IP outside documentation ranges, no token-like strings) and a documented human review. |
| SS-3 | The capture workflow is repeatable from a fresh instance (`scripts/e2e.sh`); the README tells the product story in a fixed order with accurate captions. |

## Change set T (2026-10): encrypted backup and recovery, notification routing and channels, sign-in security, rich guides

Acceptance tests AT-276…AT-335. The change prompt numbered them AT-251…AT-310: prompt AT-n = AT-(n+25). See
[TRACEABILITY.md](TRACEABILITY.md), section *Change set T*.

Guides: [backup and restore](guides/backup-restore.md), [disaster recovery](guides/disaster-recovery.md),
[notifications](guides/notifications.md), [Discord](guides/discord.md), [WhatsApp Personal](guides/whatsapp-personal.md),
[sign-in security and map](guides/security-map.md), [documentation](guides/documentation.md).

Decisions: [ADR 0020](adr/0020-encrypted-recovery-points.md), [ADR 0021](adr/0021-notification-routing-channels.md),
[ADR 0022](adr/0022-trusted-zones-signin-map-risk.md).

| ID | Requirement |
|---|---|
| BR-1 | A recovery point contains everything needed to rebuild the application: database, every document version and original, OCR text and derived files, profile photos, branding, settings and protected secrets. |
| BR-2 | Recovery points are encrypted. Each point has its own key, wrapped by the Backup Recovery Key. Each file is authenticated in chunks, so truncation and tampering are detected. No plaintext secret reaches a destination, log or notification. There is no separate compression stage. |
| BR-3 | Full and incremental chains, with a configurable schedule. Recommended: weekly Full, incremental every 4 hours, kept 4 weeks. Retention never deletes a base that a kept point needs. Ordinary activity never starts a backup. |
| BR-4 | A policy can write to several destinations (local/USB, NAS, S3-compatible, Google Drive, OneDrive). Each destination has its own status, free space and retries. One failing or full destination never invalidates or deletes the other copies. |
| BR-5 | Every copy is deep-verified: checksums, authenticated decryption, manifest, chain and database dump. Health is derived from verified recovery state, never from the scheduler running. |
| BR-6 | A verified pre-change safety backup is made before upgrades and other high-risk operations. If it fails, the operation is blocked and a critical notification is sent. |
| BR-7 | The Recovery Key is revealed only to the main administrator after step-up authentication, and is never logged, audited, notified or written to diagnostics. Rotation re-encrypts every reachable copy and names any destination it could not reach. |
| BR-8 | An Emergency Recovery Package (passphrase-sealed key and instructions) can be exported. Recovery Readiness is Ready, Not Ready or Outdated, and records nothing about where the package is kept. |
| BR-9 | The Recovery Explorer shows each person only what they may recover with their current permissions. Version, document, folder-tree and person restores offer Keep both, Replace and Skip for conflicts. A Restore Impact Analysis comes first. A deleted account can be recreated, transferred or restored into a staging folder. |
| BR-10 | Deleting a recovery point shows the points that depend on it, needs step-up and is audited. Downloads are encrypted packages, authorised server-side and audited. |
| BR-11 | The administrator Backup Health widget and Automated Recovery Validation are provided. Validation restores only into a separately configured, isolated environment, never production, with delivery disabled. My Recovery never shows destinations or paths. |
| DR-1 | The installer offers *Recover Existing Installation*. Recovery accepts local/USB, `.tar`, NAS, S3, Google Drive and OneDrive sources, with temporary bootstrap credentials that are never stored. |
| DR-2 | Integrity, key and compatibility checks run before anything changes. Recovery is resumable. The web application answers 503 until recovery is complete. |
| DR-3 | Normal mode restores everything as completely as possible. Compromise mode ends all sessions and untrusts all devices, keeps MFA unless explicitly reset, never relinks WhatsApp automatically, and requires a security review. |
| DR-4 | Restored integrations stay on hold until a safe connection test passes. A secret-free Recovery & Security Report is written. |
| NR-1 | New backup and recovery notification events exist. Main-administrator events go only to the main administrator. |
| NR-2 | People can add their own Discord webhook: stored encrypted, shown masked, tested without posting, removable. |
| NR-3 | WhatsApp Personal (experimental) runs through an optional, separately installed bridge. Each person has an isolated session. It is notification-only: no composer, no contacts, no other recipients. The bridge version is pinned, with controlled update and rollback. A bridge failure never affects other channels. |
| NR-4 | Channels are chosen per route category, with a fallback chain. A fallback is used once and never after a successful primary delivery. |
| NR-5 | Quiet Hours hold normal messages; critical messages are delivered. Daily and weekly digests are available; critical messages stay immediate. |
| NR-6 | People see their own delivery history; administrators see counts only. Discord and WhatsApp are never enabled automatically for existing people. Signal is not offered. |
| SZ-1 | Trusted Zones have a friendly name and several IPv4/IPv6 networks. The most specific network wins. A Trusted Zone replaces "Unknown country". |
| SZ-2 | The sign-in map uses Leaflet with configurable online tiles. Sign-in addresses are never sent to the tile server or any geolocation service. Configured pins are labelled as such and never called GeoIP. |
| SZ-3 | People see their own sign-ins, delegates with the membership scope their group, the main administrator everyone. This is enforced server-side. |
| SZ-4 | Every sign-in gets an explainable risk level (Normal, Low, Warning, High) from zone, device, method, country history and impossible travel. Risk never blocks a sign-in. |
| SZ-5 | Recognised devices are listed. *Mark Unrecognized* ends the device's sessions, removes its recognition, audits, notifies, and offers next steps. |
| SZ-6 | Sign-in, map and device records are kept 1 year by default. Current security state (active devices) is kept. |
| DOC-1 | Rich guides cover the new features, with screenshots next to the steps, callouts, review dates and in-app navigation (categories, search, breadcrumbs, table of contents, previous/next). |
| DOC-2 | `scripts/check_docs.py` fails on broken links or anchors, missing images or alt text, orphan screenshots, broken *Learn more* links, outdated UI terms and missing review dates. |
| DOC-3 | Screenshots use synthetic data only: no real names, documents, keys, tokens, webhook addresses, WhatsApp QR or session data, real public IPs, or production backup locations. |

## Change set U (2026-10): corrective fixes for the folder tree, sign-in map, sign-in designs, WhatsApp and Discord

Acceptance tests AT-336…AT-355. The change prompt numbered them AT-311…AT-330: prompt AT-n = AT-(n+25). See
[TRACEABILITY.md](TRACEABILITY.md), section *Change set U*, and the root causes in
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-u).

| ID | Requirement |
|---|---|
| FT-1 | Every folder tree row has the same columns (indent, expander, icon, name, extras) from shared tree tokens. A row without children keeps an empty expander slot. Each level is indented by the same step. |
| FT-2 | Long names wrap inside the name column. The expander and icon stay on the first line and do not move. The tree never scrolls sideways or sits under its scrollbar. |
| FT-3 | Alignment and readability hold in Default Green, Blue, Dark, Glass Light and Glass Dark, at desktop, tablet and phone widths, and in right-to-left layout. There are no per-folder offsets or pixel nudges. |
| FT-4 | Keyboard: Enter opens, ArrowRight expands, ArrowLeft collapses. Rows have `treeitem` roles with levels and expanded state, and keep visible focus. |
| MP-1 | The sign-in map provider is configurable: OpenStreetMap (low-volume use), MapTiler or Stadia Maps with the administrator's own key, or a custom/self-hosted server. A custom tile address set earlier keeps working. |
| MP-2 | Tile requests follow the provider's policy. They send only this site's origin as `Referer`, never a spoofed header, and are never proxied or scraped. The Content-Security-Policy allows only the configured tile origin, for images and for the test request. |
| MP-3 | A failing provider (401, 403, 429, network) shows a clear *Map unavailable* state with the reason and the fix, never a grid of blocked tiles. Tiles are not retried in a loop. |
| MP-4 | Sign-in records, Trusted Zones, GeoIP and risk work without map tiles. Sign-in addresses are never sent to a tile provider or a geolocation service. |
| MP-5 | **Test Map Provider** (main administrator) fetches one tile from the browser, records Working, Failed or No status with the HTTP status and time, keeps the last successful test, never returns the API key in its result, and is audited. |
| SD-1 | The sign-in page, its design thumbnails and its previews always use the sign-in theme. They are equally clear under every app theme. |
| SD-2 | Changing an app theme never changes the sign-in design, and saving a sign-in design never changes anyone's theme. |
| SD-3 | Choosing a design previews it. It is published only with *Save design*, or dropped with *Discard*. A live preview shows the desktop and phone layouts, and a large preview shows the full sign-in page. |
| CN-1 | Settings → Connections shows a card for each provider (In-App, Email, Telegram, Push, Discord, WhatsApp) with its real state: Connected, Configured, Disabled, Available but not configured, Degraded or Not installed. No feature that exists is shown as "Planned". |
| CN-2 | The WhatsApp Personal administrator section shows the bridge service: installed, systemd state, reachability, version, protocol, compatibility, update, linked people (counts only) and last check. It detects a running bridge before WhatsApp is turned on. Turning it on needs no restart. |
| CN-3 | People see their own WhatsApp state: Disabled by Admin, Service unavailable, Not linked, Waiting for scan (the QR refreshes by itself), Connected, Reconnect needed. They can Link, Send test, Reconnect and Unlink, and see their last notification. Nobody can see another person's QR, session or controls. |
| CN-4 | Discord has its own administrator switch. People see Disabled by Admin when it is off, and the last test and last delivery when they have a webhook. Webhooks stay encrypted and masked. |
| CN-5 | The routing matrix explains why a chosen Discord or WhatsApp channel cannot deliver (turned off, not linked, service unavailable). The fallback chain is used meanwhile. A failing bridge never affects other channels. |

## Later phases

Native apps, scanning enhancement, in-browser Office editing, DICOM viewing.

## Change set Z (2026-10): optional AI Document Intelligence and the OCR engine order {#change-set-z}

Acceptance tests AT-441…AT-460 (prompt AT-416…AT-435 = AT-(n+25)). See [TRACEABILITY.md](TRACEABILITY.md#change-set-z)
and [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-z).

| ID | Requirement |
|---|---|
| ADI-1 | OCR engine order: light-ocr, Tesseract and PaddleOCR in any Main Admin order (Primary, Fallbacks), mode Auto or Primary only; new installations light-ocr → Tesseract → PaddleOCR (Auto); upgrades keep their behaviour. OCR priority is separate from AI and AI never changes it. |
| ADI-2 | Four provenance layers kept apart: original document, original OCR result, AI interpretation, user-confirmed metadata. AI never rewrites OCR or confirmed metadata. |
| ADI-3 | AI modes: AI on Demand (default), OCR Only, OCR + AI, Smart Auto (configurable triggers). Upgrades never start sending existing documents to AI. |
| ADI-4 | Provider abstraction (status/models, capabilities, health check, text and document analysis, usage) for Local LLM (OpenAI-compatible, Ollama), OpenAI, Anthropic, Gemini and OpenRouter; named profiles, a default profile, secrets encrypted and never shown; jobs keep the profile/provider/model actually used. |
| ADI-5 | Every profile is Local or Cloud; Cloud profiles have independent controls for OCR text, metadata, original images and original files (images/files off by default); automatic AI never uses a Cloud profile unless separately allowed. |
| ADI-6 | Cloud disclosure: a confirmation naming profile, provider and data categories before an original image/file is sent; text-only sends say so; nothing is sent without it. |
| ADI-7 | Permission-aware AI Actions in Document Details: Analyze, Extract Metadata, Verify OCR, Summarize, Ask AI, Suggest Type, Suggest Filename, Detect Expiry/Renewal; only actions allowed by permissions, policy and capabilities are offered. |
| ADI-8 | Suggestions are not authoritative until accepted: accept, reject, edit then accept, accept selected, reject all; conflicts with values a person set need explicit review. |
| ADI-9 | No fabrication: observed vs inferred, no invented numbers/dates, empty when unsure; structured output validated (schema, types, dates, allowed types, lengths, keys) before it can become a suggestion. |
| ADI-10 | Prompt-injection isolation: system policy, task and untrusted document content separated; AI cannot act (delete, share, permissions, security, OCR priority, backups, passwords, secrets). |
| ADI-11 | Ask AI limited to documents the person may open, with provenance; summaries/expiry labelled AI-generated; expiry facts separate from reminder policy. |
| ADI-12 | Audit and AI History: user, time, document, profile, provider, model, action, Local/Cloud, data categories, status, duration, usage — never keys or document content; disposable AI outputs deletable. |
| ADI-13 | Statuses Queued, Processing, Completed, Needs Review, Provider Unavailable, Timed Out, Failed, Cancelled; AI failure never impairs documents/OCR; AT-400 throttling and concurrency apply. |
| ADI-14 | Settings → AI shows status, model, Local/Cloud, privacy and Last Test with Test Profile (only checks actually run); `personaldocs doctor` reports AI mode, default profile and safe provider diagnostics. |

## Change set Y (2026-10): OCR → AI document analysis pipeline {#change-set-y}

Acceptance tests AT-426…AT-440 (prompt AT-401…AT-415 = AT-(n+25); the prompt called itself "Change Set X", which is
taken). See [TRACEABILITY.md](TRACEABILITY.md#change-set-y) and [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-y).

| ID | Requirement |
|---|---|
| AIP-1 | One pipeline: document → selected OCR engine (Tesseract or PaddleOCR) → normalized text → validation → selected AI profile's text model → validated metadata suggestions. OCR engine and AI profile are chosen independently. |
| AIP-2 | The text model receives only text, never the original file or a page image; the embedding model is never used for generation; a vision model is not required. |
| AIP-3 | Usable existing text is reused; explicit OCR re-runs and new file versions take effect; manual corrections are never overwritten. |
| AIP-4 | Empty OCR stops the job before the AI server is called, attributed to OCR. |
| AIP-5 | OpenAI-compatible servers (incl. LM Studio) and Ollama: only supported parameters; structured output with exactly one compatibility fallback; defensive JSON parsing and schema validation. |
| AIP-6 | Sanitized HTTP diagnostics (status, server message, rejected capability) without document text or secrets. |
| AIP-7 | Deterministic failures fail at once; transient failures (timeout, connection, 429, temporary 5xx) retry with backoff, bounded; truthful job states and visible stages; no duplicate queued analyses. |
| AIP-8 | Separate tests: AI profile/connection with model roles, AI analysis, OCR Tesseract, OCR PaddleOCR. |
| AIP-9 | Long text is split deterministically in page order; any unanalysed remainder is recorded. |
| AIP-10 | Backward compatible: existing profiles work unchanged, old failed jobs stay failed but may be retried; privacy, throttling and performance controls apply. |

## Change set X (2026-10): performance {#change-set-x}

Acceptance tests AT-401…AT-425 (prompt AT-376…AT-400 = AT-(n+25)). See [TRACEABILITY.md](TRACEABILITY.md#change-set-x),
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-x) and [PERFORMANCE.md](PERFORMANCE.md).

| ID | Requirement |
|---|---|
| PERF-1 | A reproducible BEFORE/AFTER benchmark on a sanitised synthetic dataset (pages, API, queries, bundles, concurrency, memory). |
| PERF-2 | Targets: sign-in ≤ 1.5 s, dashboard ≤ 2 s, Settings ≤ 1.5 s, cached section ≤ 0.5 s, folder/document/details ≤ 1 s, search ≤ 1–2 s, typical API ≤ 0.5 s. |
| PERF-3 | Settings loads per section on demand; cached sections switch instantly; direct links, Back/Forward and permissions unchanged; obsolete requests cancelled. |
| PERF-4 | No query count grows with the data on list, dashboard, tree and preference endpoints; authorisation unchanged. |
| PERF-5 | Safe, beneficial, reversible indexes created without blocking documents. |
| PERF-6 | Caches only non-private derived data, with immediate invalidation, no cross-user reuse, no secrets, hit/miss counters; no external cache service. |
| PERF-7 | Route/section code splitting, heavy modules on demand, request deduplication, compressed immutable static files, no stale deployments. |
| PERF-8 | Large folders load incrementally in server order without losing documents; lists never fetch binaries. |
| PERF-9 | Interactive requests take priority; under sustained load non-urgent jobs are postponed (bounded), running jobs never interrupted, critical work never postponed; visible and logged. |
| PERF-10 | Admin Performance dashboard and main-admin Diagnostic Report: useful, lightweight, administrator-only, no secrets or document data, limited retention. |
| PERF-11 | Runtime tuned from measurement within 6 GB; post-upgrade maintenance safe and repeatable. |
| PERF-12 | Search/OCR architecture unchanged; every existing feature and permission intact. |

## Change set W (2026-10): named sign-in designs and rotation, complete details and IPs, Notification Detail Level {#change-set-w}

Acceptance tests AT-376…AT-400. The change prompt numbered them AT-351…AT-375: prompt AT-n = AT-(n+25). See
[TRACEABILITY.md](TRACEABILITY.md#change-set-w) and the root causes in
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-w).

| ID | Requirement |
|---|---|
| SD-1 | The main administrator can create, create from template, duplicate, rename, edit, preview, activate, revert and delete any number of named sign-in designs; exactly one is active globally. |
| SD-2 | Built-in designs are protected templates (activate or duplicate only); Minimal is the protected default and Reset to default activates it. |
| SD-3 | Colour mode Auto derives a readable palette from the wallpaper region next to the sign-in panel; Light, Dark and Custom are available; contrast meets WCAG (text 4.5:1); Custom overrides survive a wallpaper replacement. |
| SD-4 | The original wallpaper is kept; Desktop, Tablet and Phone derivatives are cropped around a focal point without distortion; content is validated (type, size, dimensions) and metadata removed. |
| SD-5 | Preview at Desktop, Tablet and Phone with password, passkey and SSO controls never changes the live design. |
| SD-6 | Activation is atomic and audited; Revert restores the previous design; deleting the active design activates the default first; damaged assets fall back to the default with an alert; files are removed only when unreferenced; all design files are backed up. |
| SD-7 | The upgrade migrates the previous design and wallpaper into named designs idempotently and keeps the appearance. |
| ROT-1 | Rotation uses a pool of at least two valid designs, Sequential (ordered) or Random (no immediate repeat), Daily/Weekly/Monthly in the installation timezone, last valid day for 29–31. |
| ROT-2 | Manual activation does not disable rotation; open sign-in pages are not refreshed; missed runs are reconciled once (Sequential) or with one recovery choice (Random), audited. |
| ROT-3 | Unavailable designs are skipped and alerted; fewer than two valid → Needs Attention; none → built-in default; routine rotations are audit-only; Preview Rotation changes nothing. |
| MD-1 | Authorised people see complete, unmasked document metadata on every surface; unauthorised people see nothing of it. |
| MD-2 | OCR Metadata expands after OCR; low-confidence values are marked for review; manual corrections are not overwritten; Copy copies the complete value, shows "Copied" and is never logged. |
| MD-3 | Masking is removed at the shared root; secrets (passwords, keys, tokens, codes) stay protected; history and audit never copy sensitive values. |
| IP-1 | Complete IPv4 and IPv6 addresses are shown to authorised people in security views, alerts and notifications. |
| ND-1 | Notification Detail Level Full (default) or Minimal as a system setting, with a per-person override (system default / Full / Minimal); it changes presentation only, never permissions; Full is limited to what the recipient may see. |

## Change set V (2026-10): NAS in Backup Destinations, English sign-in map, tooltips, Help permissions, WhatsApp pairing {#change-set-v}

Acceptance tests AT-356…AT-375. The change prompt numbered them AT-331…AT-350: prompt AT-n = AT-(n+25). See
[TRACEABILITY.md](TRACEABILITY.md#change-set-v) and the root causes in
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-v).

| ID | Requirement |
|---|---|
| NAS-1 | NAS (SMB, NFS, Already mounted) is configured only in Backup & Recovery → Destinations; Settings → Storage & NAS is removed and its address redirects. |
| NAS-2 | The upgrade migrates the old NAS connection automatically, idempotently and without deleting configuration, credentials or backup data; a failure shows Needs Attention with Edit Configuration, Test Connection and Retry Migration. |
| NAS-3 | Secrets are write-only: never returned, logged or audited; an empty field keeps the stored value. |
| NAS-4 | Destination cards show health, free space with Warning (20 %) and Critical (10 %) thresholds (overridable), last/next backup and retries; failures name the failed check. Valid backups are never deleted to make room. |
| BQ-1 | Backup Now per destination: confirmation, full-system Full point on that destination only, truthful states, no Cancel. |
| BQ-2 | Backup-class jobs run one at a time, first in first out, without queue jumping or duplicates, and survive navigation, sign-out and restarts. |
| TT-1 | One shared tooltip: never clipped by containers or the viewport, flips/shifts, keyboard/touch/screen-reader accessible, consistent in every theme. |
| TT-2 | Tooltip texts come from a central registry by id; missing ids fail the tests; Learn more is shown only for guides the person may open. |
| HLP-1 | Help navigation, categories, search, excerpts, related and contextual links, direct URLs and the API show only content the person is authorised for, enforced by the server per request. |
| MAP-1 | Map labels are in English where the data has English or Latin names, independent of the browser language, from a policy-compliant provider; no language selector. |
| MAP-2 | Hover shows person, IP and place; click/tap shows authorised details; nearby sign-ins cluster; map and list share filters (default Last 7 days) and selection; records without coordinates show Location unavailable; one-year retention unchanged. |
| WA-1 | Linking uses one bridge with isolated encrypted sessions per person; a link attempt stays valid 5 minutes with a countdown; no new QR while connecting; a new QR only after expiry or definitive failure. |
| WA-2 | Live stages up to Linked & Verified (verification message); automatic reconnect with back-off; Relink Required with notification through another channel. |
| WA-3 | Stale queued messages expire or are superseded after an outage, except security and critical messages; delivery history is accurate. |
| WA-4 | Main-administrator diagnostics without secrets, Restart Bridge, pinned tested library, explicit update with rollback and post-update diagnostics, incompatibility alert through non-WhatsApp channels. |

