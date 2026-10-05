# Changelog

## 0.1.0 — unreleased

The first implementation of the full initial-release scope. See `docs/IMPLEMENTATION_STATUS.md` for the validation still pending before family production use.

### Added (2026-10-05) — browsing, OCR quality, one-line installer (Change Set J)
- ⋮ menus that open on top of every panel and stay on screen (keyboard, Escape, outside click), with Rename, Share, Archive and (administrator) Delete permanently for documents, and Rename, Change icon, Share and Archive for folders.
- Folder icons: sub-folders default to 📁; icons chosen from a list with **Reset to default**; chosen icons survive moves and upgrades.
- List, Thumbnails and Details views with sorting, saved per account and synchronised across devices.
- Drag files and whole folders from the desktop: the folder structure is recreated below the drop target, with a progress card and a per-file report.
- Your own library is listed first and opened; other areas stay closed.
- OCR: measured preprocessing (orientation, deskew, contrast, upscale, denoise), confidence per document with unreliable lines greyed out, **Re-run OCR** with a chosen rotation, card layouts ("Badge No | Expiry Date") and "No Expiry Date" understood; mean accuracy on the synthetic benchmark 0.58 → 0.97 (`docs/OCR_BENCHMARK.md`).
- Public title "Personal Documents Management System"; one-line installer `personal-DM.sh`; LinkedIn-ready README; Ko-fi support link.

### Fixed (2026-10-05) — Change Set J
- Folder and row menus were clipped by the breadcrumb bar and scrolling panels.
- Sub-folders got name-based emoji (e.g. 🏠 deep inside a folder) instead of a folder icon.
- Phone photos stored sideways and upside-down scans produced junk OCR text; "12-31-2030" (month first) was not recognised; "Badge No  Expiry Date" header/value layouts were not read.

### Added (2026-10-05) — UI, import, notifications, backups, mobile, viewer, public release
- "My Documents — <name>" with avatar at the top of the folder tree; avatars for every member's area.
- File-type icons (PDF, JPG, PNG, WEBP, TXT, DOC, XLS, PPT, ZIP, DCM, FILE) from validated content.
- Drag and drop of documents and folders, and **Move to…** with a folder picker on every device.
- Built-in viewer (PDF.js, local): zoom 25–400 %, fit page, fit width, 100 %, pages, full screen, keyboard shortcuts.
- Import: choose a destination sub-folder (or any permitted folder), keep the top folder or not, and preview the exact final hierarchy (new/existing).
- Dashboard widgets chosen with checkboxes and ordered by drag or ↑/↓; synced per account.
- Critical notifications (administrator-chosen, cannot be turned off, missing destinations flagged) and optional notifications per event and channel; one detailed template; bulk summaries; archive vs permanent deletion messages; optional "every sign-in" information.
- Backups daily, weekly or monthly with next-run status and catch-up.
- `docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md`, `SECURITY.md`, `CONTRIBUTING.md`, public README with screenshots; `scripts/privacy_check.sh`; frontend unit tests; tablet/phone parity checks.

### Fixed (2026-10-05)
- Members could not move their own documents between their own folders (now allowed when nobody gains access).
- Two opposite folder moves at the same time could detach folders; moves into archived folders were possible; a refused move could still apply a rename sent with it.
- Dropping a file outside an upload area opened it in the browser and left the app.
- Malformed list filters (`folder=undefined`) caused a server error.
- Horizontal scrolling on family settings and help at tablet widths.
- Security: `?next=` after sign-in only accepts in-app paths; PDF.js 6.4.299 (GHSA-hq66-cqwq-w95j) and React Router 7.18 (GHSA-wrjc-x8rr-h8h6).

### Added (2026-10-05) — profile photos, Local AI, security & access, passkeys
- Profile photos with crop/zoom, shown in the header, family list, permissions and document history.
- Optional Local AI (off by default): AI profiles for OpenAI-compatible servers (LM Studio, llama.cpp, vLLM) and Ollama, privacy classes (local/LAN/external) checked before every request, OCR assist and smart organisation as reviewable suggestions, document assistant with citations, semantic search, AI job list. Permission-filtered retrieval; no cloud fallback.
- Login audit (method, real IP, country, browser/OS/device, new-IP/new-country/temporary-access flags) with filters and retention.
- Real client IP through trusted proxies only (`PD_TRUSTED_PROXY_IPS`), with a "Your connection" diagnostic.
- Local GeoIP (MaxMind download with validation and atomic install, or `.mmdb` upload), weekly updates.
- Country access policy (off / block list / allow list, unknown-location action), temporary travel access, trusted and blocked IPs with expiry, documented precedence, lock-out confirmation, undo, and `personaldocs access-policy` console recovery (`PD_ACCESS_POLICY_DISABLED=1` emergency switch).
- Security alerts (failed-sign-in escalation with automatic blocks, new country/IP, temporary access, policy changes, GeoIP/GoAccess problems, account security changes), throttled and secret-free.
- Traffic analytics: privacy-safe access log, hourly GoAccess (or built-in) report, blocked-request statistics.
- Passkeys (WebAuthn) as a second step and optional passwordless sign-in; authentication policy (allow TOTP/passkeys/passwordless, require two-step verification for none/admins/everyone without lock-out), recent-auth window for sensitive changes, admin "Reset 2FA" and `recover-admin --reset-2fa`.
- TOTP fields work with password-manager autofill (`autocomplete="one-time-code"`).
- Installer/upgrade: GoAccess package, access-log rotation, new migrations; `doctor` checks proxy trust, GeoIP, passkey origin and AI profiles; backups include profile photos.

### Added (2026-10-04)
- Resizable folder-tree and document-list panels (mouse and keyboard), remembered per account.
- Active sessions list with sign-out of individual devices.
- Optional folder templates for new members (setup wizard, add member, apply to any folder).
- Notifications for access granted, finished imports, processing failures, failed backups and integrity problems, with a per-user switch for external channels.
- PDF/A-2b validation of searchable copies (veraPDF when installed via `--with-verapdf`, structural check otherwise) and `manage.py pdfa_check`.
- Automated accessibility audit (axe-core) and a CI end-to-end job.

- Connect the NAS backup share (NFS or SMB) from Settings → Storage & backup, with status, Disconnect and actionable errors (`personaldocs nas-apply`).
- Guided installers: `scripts/proxmox-create-lxc.sh` (creates the Debian 13 container on Proxmox) and `scripts/easy-install.sh` (asks every parameter and installs, configures, connects the NAS, backs up and checks), with `--dry-run`.
- `manage.py apply_settings FILE` to apply validated settings from a file.

### Fixed (2026-10-04)
- Duplicate notification keys could abort an enclosing database transaction.
- Changing your own password signed out the device you were using.

### Added
- First-run setup wizard (one-time console code) creating the six family accounts; extended-family groups, heads and scoped delegation.
- Default-deny capability permissions with folder inheritance, document exceptions and access explanations.
- Folder library with emoji suggestions, immutable checksummed originals, versions, renewals and archive/restore/purge.
- Local OCR (Tesseract/OCRmyPDF, searchable PDF/A), LibreOffice previews, thumbnails, DICOM-safe storage.
- Proposed detail extraction (labels and passport MRZ with check digits) with discrepancy flags and confirmation, plus copy buttons.
- Full-text search with highlights, autocomplete, saved views and non-AI similarity.
- Browser and server/NAS folder import wizard with explicit mapping, resumable and idempotent.
- Expiry reminders (90/60/30/7/0) over in-app, SMTP and Telegram with an idempotent outbox; verified Telegram linking.
- Public share links (expiring, password, pinned version, rate-limited); native device sharing.
- Installable PWA, camera upload, Web Share Target, opt-in per-account offline copies, streaming ZIP exports.
- Password sign-in, optional TOTP with recovery codes, Google account linking (OIDC + PKCE), console admin recovery.
- Per-user IMAP email import rules.
- Application backups to a NAS with verification and retention; console restore; integrity checker; audit log; health page.
- `personaldocs` CLI for install/upgrade/rollback/repair on Debian 13; systemd units; CI; bundled help; three themes.
