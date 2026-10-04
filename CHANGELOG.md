# Changelog

## 0.1.0 — unreleased

The first implementation of the full initial-release scope. See `docs/IMPLEMENTATION_STATUS.md` for the validation still pending before family production use.

### Added (2026-10-04)
- Resizable folder-tree and document-list panels (mouse and keyboard), remembered per account.
- Active sessions list with sign-out of individual devices.
- Optional folder templates for new members (setup wizard, add member, apply to any folder).
- Notifications for access granted, finished imports, processing failures, failed backups and integrity problems, with a per-user switch for external channels.
- PDF/A-2b validation of searchable copies (veraPDF when installed via `--with-verapdf`, structural check otherwise) and `manage.py pdfa_check`.
- Automated accessibility audit (axe-core) and a CI end-to-end job.

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
