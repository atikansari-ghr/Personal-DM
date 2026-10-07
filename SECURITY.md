# Security policy

Personal Documents Management System stores a family's most sensitive papers. Security reports are welcome and taken seriously.

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

In scope: authentication (passwords, TOTP, passkeys, recovery, Google and authentik linking), session handling,
permissions (including AI retrieval and the Administrator role), share links, file handling and previews, antivirus
quarantine and release, notification rendering, templates and Web Push subscriptions, the country/IP access policy and trusted-proxy IP handling, the installer/upgrade scripts,
the NAS helper and the host helper.

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
- New files are scanned by a local ClamAV daemon over a Unix socket (no network port, no cloud scanner). Scanning is
  fail-open: when ClamAV is unavailable, files stay usable and are marked *Not scanned*. Detected files are
  quarantined and blocked; only the main administrator can release them. A *Clean* result only means ClamAV's current
  signatures found nothing, and archives are scanned as one file.
- authentik sign-in uses OpenID Connect with PKCE, state and nonce; accounts are linked only by their owner, never by
  matching email, and authentik never grants document permissions.
- The Administrator role gives access to the security center, not to documents.
- Root actions from the web interface (OS security updates, signature updates, reboot) go through a host helper that
  accepts only a fixed list of actions; the web application never runs `sudo`.
- **Notification rendering is a security boundary.** Document, folder and person names, OCR-derived values and
  administrator template text are untrusted input: each channel renderer escapes them for its own format (HTML email,
  Telegram HTML, plain text, push), templates accept plain text with an allowlist of placeholders only (no code, no
  HTML), and the email preview is shown in a sandboxed frame. Emails contain no scripts, remote images or tracking
  pixels.
- **No tokens in notification links.** Actions in notifications are application paths only; opening one requires
  sign-in and the normal permission checks, so a forwarded message grants nothing. Paths to the API and quarantine
  releases are never offered as actions. Document numbers are left out unless the administrator allows a masked
  number, and never appear in push notifications.
- **Push endpoint allowlist.** Web Push subscriptions are accepted only for HTTPS endpoints on the known push
  services (Apple, Google, Mozilla, Microsoft); internal addresses, other hosts and URLs with credentials are refused,
  so a subscription cannot make the server call into the local network. Payloads are encrypted for the receiving
  device and the VAPID signing key is stored encrypted.

**Limits of the built-in checks.** The Basic Internet Security Test in Settings → Security is a baseline of this
application and this server. It is not a penetration test, it does not scan other devices, and passing it does not
prove the absence of vulnerabilities. The Security Health score is a summary for your own installation, not a
certification. The firewall view only monitors ufw/nftables and listening services; it cannot change rules.

Out of scope: attacks that need root on the server or physical access to it, social engineering of family members,
and vulnerabilities in third-party platforms (Proxmox, NPM, Pangolin, browsers) — report those upstream.

## For operators

- Keep the server patched (Settings → Security → OS updates, or `apt-get upgrade` on the host) and run
  `sudo personaldocs upgrade` regularly.
- Keep ClamAV running with fresh signatures, set the deployment exposure correctly, and for Internet deployments keep
  **Internet Ready** green and the host firewall active.
- Run the Basic Internet Security Test after configuration changes and resolve Critical findings.
- Require two-step verification at least for administrators.
- Test restores. Protect the backup share: backups can include the encryption key.
- If you suspect a compromise: rotate the passwords, Telegram bot token, SMTP, MaxMind and authentik client
  credentials; revoke authentik links and reset 2FA for affected accounts; review the login audit, audit log and
  security records.
