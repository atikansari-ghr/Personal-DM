# Changelog

## 0.1.0 — unreleased

The first implementation of the full initial-release scope. See `docs/IMPLEMENTATION_STATUS.md` for the validation still pending before family production use.

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
