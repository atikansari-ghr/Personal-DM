# Administrator guide

For whoever installs and runs Personal Documents (the **main administrator**). Each section summarises what to do
and links to the detailed guide (also available in the app under **Help**). Commands run as root inside the
container (`pct enter <id>` from the Proxmox host).

## 1. Install and first-run setup {#setup}

1. Create a Debian 13 LXC (2 vCPU, 4 GB RAM, 50 GB, nesting on). `scripts/proxmox-create-lxc.sh` does it from the
   Proxmox host.
2. Inside it, clone the repository and run `bash scripts/easy-install.sh`. It asks for:
   - the domain
   - the proxy address
   - the NAS details
   - the backup time

   Then it installs and checks everything.
3. Configure the reverse proxy (below), open the HTTPS address and enter the setup code
   (`personaldocs setup-token` prints a new one).
4. The wizard creates the six family accounts. Hand each person their temporary password; they choose their own at
   first sign-in.

Guides: [installation](guides/installation.md), [setup](guides/setup.md), [private GitHub access](guides/private-github.md).

## 2. Family, extended family and permissions {#family}

**Settings → Family & access**:
- Add or disable members.
- Reset passwords.
- Reset 2FA (removes the authenticator app, passkeys and recovery codes; audited, and the person is notified).
- Manage profile photos.
- Optional folder templates.

**Extended family:** groups with a head, and delegation scopes (documents, folder permissions, receive reminders).

**Permissions:**
- Default-deny with nine capabilities, set on folders (inherited) or documents (exceptions).
- **Who has access** explains every grant.
- Moving an item that would give more people access needs *manage permissions*.

Guides: [setup](guides/setup.md), [extended family](guides/extended-family.md).

## 3. Authentication policy {#authentication}

**Settings → Authentication**:
- Allow authenticator apps (TOTP), passkeys, and passwordless passkey sign-in (off by default).
- **Require two-step verification** for nobody, administrators or everyone. People without one are guided to set
  it up; nobody is locked out.
- Re-confirmation window for sensitive changes.
- Optional Google sign-in (linking only; no automatic accounts).

Any change to these settings is a critical notification to administrators.

**Passkeys** only work on the HTTPS address in `PD_PUBLIC_ORIGIN`. Changing the domain later makes existing passkeys
unusable. `personaldocs doctor` checks the relying-party ID and origin.

Guides: [passkeys](guides/passkeys.md), [authenticator and recovery](guides/totp-recovery.md), [Google](guides/google.md).

## 4. Email and Telegram {#channels}

- **Settings → Connections:** SMTP host, port, security and sender; Telegram bot token and username. Use
  **Send test**.
- Each person adds an email address to their profile and links their own Telegram from **My account →
  Notifications**.

Guides: [SMTP](guides/smtp.md), [Telegram](guides/telegram.md).

## 5. Notification policy {#notifications}

**Settings → Notifications**:

| Setting | Purpose |
|---|---|
| Critical notifications | Events members cannot turn off. Default: account security changes, sign-ins from new countries, failed-sign-in alerts, access/authentication policy changes, failed backups, integrity problems |
| Channels for critical notifications | Where critical events always go (default in-app + email + Telegram) |
| Include names in email/Telegram | Folder/file names in external messages (long numbers are always masked) |
| Expiry reminder days, send time, recipients | When and to whom reminders go |
| Default / required channels for expiry reminders | Starting point and locked channels for reminders |

- **Delivery problems** lists anyone who would miss required notifications (no email address, Telegram not linked).
  If email or Telegram is not configured at all, it says so, and those messages are recorded as *skipped*.
- **Delivery history** shows every external message with its status.
- Members choose everything else themselves, per event and channel.
- Bulk uploads and imports produce one summary message per person.

Guide: [notifications](guides/expiry-rules.md#critical).

## 6. OCR and processing {#ocr}

- **Settings → OCR & processing:** local OCR (English), concurrency (1 on 2 vCPU/4 GB), timeouts and memory limits.
- The job list shows failures, which you can retry.
- Optional PDF/A validation with veraPDF (`--with-verapdf`).

Guides: [OCR and corrections](guides/ocr-corrections.md), [Office and DICOM](guides/office-dicom.md).

## 7. Local AI (optional) {#ai}

**Settings → Local AI:**
1. Add a profile for LM Studio (`http://<pc-ip>:1234/v1`) or Ollama (`http://<pc-ip>:11434`).
2. Set its privacy class (local, private LAN, or external with an explicit warning).
3. Click **Test connection**.
4. Switch on the features you want.

- AI never changes documents without a person accepting the suggestion.
- It only sees documents the asking person can open, and there is no cloud fallback.
- A 2 vCPU/4 GB container cannot run useful models itself; use a LAN PC.

Guide: [Local AI](guides/local-ai.md).

## 8. Security and access {#security}

**Real client IP:** list the NPM / Pangolin (Newt) address in `PD_TRUSTED_PROXY_IPS`, then check
**Settings → Security & access → Your connection**.

**GeoIP:**
1. Enter your MaxMind account ID and licence key (stored encrypted).
2. Click **Update now**.

Updates are weekly and validated before installing. A failed update keeps the old database.

**Country policy:** off, block list or allow list (for example *Saudi Arabia + India*), plus what to do when the
country is unknown.

**Exceptions:**
- **Temporary access** for travel: country, start, end and reason. It expires on its own.
- **Trusted/blocked IPs:** CIDR ranges with an optional expiry.
- The precedence order is documented.

**Lock-out protection:** the app warns before a change would block you, and **Undo last change** reverses it. From
the console:

```
sudo personaldocs access-policy status | off | rollback | trust-ip 203.0.113.7 --hours 24 | unblock-ip … | clear-automatic
```

In an emergency, `PD_ACCESS_POLICY_DISABLED=1` in `/etc/personaldocs/personaldocs.env` disables the policy.

**Alerts and login protection:**
- Failed-sign-in delays and automatic temporary blocks.
- New-country and new-address alerts.
- Policy-change alerts.

Guides: [security & access](guides/security-access.md), [reverse proxy](guides/reverse-proxy.md).

## 9. Monitoring {#monitoring}

**Activity & health:**
- **Health & audit log:** services, jobs, disk, and every audited action.
- **Login audit:** filter by person, IP, country, method, result and date.
- **Traffic analytics (GoAccess):** requests, visitors, countries, top IPs/paths/status codes, bots, and requests
  refused by the policy. It is admin-only and never public.

Guide: [security & access](guides/security-access.md#login-audit).

## 10. Backups and restore {#backup}

- **Settings → Storage & backup:**
  - Connect the NAS (NFS or SMB) or use a mounted path containing the marker file.
  - Choose **daily**, **weekly** (a day) or **monthly** (a day of the month; 29–31 means the last day in shorter
    months) and a time.
  - Retention keeps N successful backups regardless of frequency.
- The status card shows the schedule, the next run, the last success and the last failure.
- A backup contains the database, originals, derivatives, settings and (optionally) the encryption key. The GeoIP
  file is not included; update it after a restore.
- **Restore** only from the console: `sudo personaldocs restore <backup-dir>`. Drill it on a second container.
- `sudo personaldocs integrity` checks every stored file against its checksum.

Guide: [backup & restore](guides/backup-restore.md).

## 11. Recovery {#recovery}

| Situation | Action |
|---|---|
| Main administrator locked out | `sudo personaldocs recover-admin <username> --generate` (`--reset-2fa` if all second factors are lost) |
| A member lost their phone/passkeys | Settings → Family & access → **Reset 2FA** (audited, member notified) |
| Country policy locked everyone out | `sudo personaldocs access-policy off` (or `rollback`) |
| Services broken after a failed change | `sudo personaldocs repair` |
| Bad upgrade | `sudo personaldocs rollback` (when the schema allows) or restore the pre-upgrade backup |

There is no web-based bypass of two-step verification or of the access policy.

## 12. Upgrade, doctor and repair {#upgrade}

```
sudo personaldocs upgrade     # verified backup → new release → migrations → restart → health check
sudo personaldocs repair      # safe; also applies installer steps added in newer versions
sudo personaldocs doctor      # proxy trust, GeoIP, passkey origin, AI profiles, storage, services, GoAccess
```

Guide: [upgrades](guides/upgrades.md) (with notes for each change set).

## 13. Public deployment considerations {#public}

- Expose only HTTPS through the proxy, and keep port 8000 firewalled to the proxy (the installer does this when it
  can).
- Use strong passwords, require two-step verification for administrators at least, and consider an allow list of
  your countries with temporary travel access.
- Keep the system updated (`apt upgrade`, `personaldocs upgrade`) and test a restore regularly.
- Screenshots or logs shared for support must not contain real names, documents, IPs or tokens.
- If you publish your fork, run `scripts/privacy_check.sh --history` first and read [SECURITY.md](../SECURITY.md).
