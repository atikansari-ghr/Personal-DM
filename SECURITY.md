# Security policy

Personal Documents stores a family's most sensitive papers. Security reports are welcome and taken seriously.

## Reporting a vulnerability

- **Do not open a public issue** and do not include real documents, personal data or working exploit payloads
  against someone else's installation.
- Report privately through GitHub: **Security → Report a vulnerability** on this repository (private vulnerability
  reporting). If that is not available, open an issue that only asks the maintainer for a private contact, without
  details.
- Please include: affected version/commit, a description, steps to reproduce on a test installation with synthetic
  data, and the impact you expect.

The maintainer (Atik Ansari) aims to acknowledge reports within 7 days and to agree on a fix and disclosure date
with the reporter. This is a personal project without a bug bounty.

## Supported versions

Only the latest commit on `main` (pre-release 0.1.x) receives fixes.

## Scope and design

In scope: authentication (passwords, TOTP, passkeys, recovery, Google linking), session handling, permissions
(including AI retrieval), share links, file handling and previews, the country/IP access policy and trusted-proxy IP
handling, the installer/upgrade scripts and the NAS helper.

Design points (details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/adr/](docs/adr/)):
- Default-deny permissions checked on the server for every request, preview, search result, export, notification
  and AI retrieval.
- Secrets (SMTP, Telegram, IMAP, MaxMind, AI keys, TOTP seeds) are encrypted at rest; passwords use Django's
  password hashing; passkeys store public keys only.
- Logs, audit records, notifications and analytics never contain passwords, codes, seeds, recovery codes, tokens,
  cookies or document contents.
- `X-Forwarded-For` is only honoured from `PD_TRUSTED_PROXY_IPS`.
- The access policy runs before authentication; there is no anonymous bypass. Recovery needs shell access.
- Documents are never sent to third-party services; optional Local AI only talks to the configured endpoint and
  never falls back to a cloud service.

Out of scope: attacks that need root on the server or physical access to it, social engineering of family members,
and vulnerabilities in third-party platforms (Proxmox, NPM, Pangolin, browsers) — report those upstream.

## For operators

- Keep the server patched and run `sudo personaldocs upgrade` regularly.
- Require two-step verification at least for administrators.
- Test restores. Protect the backup share: backups can include the encryption key.
- If you suspect a compromise: rotate the passwords, Telegram bot token, SMTP and MaxMind credentials; reset 2FA for
  affected accounts; review the login audit and audit log.
