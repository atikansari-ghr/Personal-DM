<!-- audience: admin -->
# Backup and restore

## What a backup contains {#contents}

- A consistent PostgreSQL dump (accounts, groups, permissions, documents, versions, settings, audit log, login audit,
  country/IP access policy, passkey public keys, AI profiles, AI suggestions and embeddings).
- Profile photos (the small private WebP files).
- All originals (every version), verified against their SHA-256 checksums.
- Previews and searchable copies (they can also be regenerated).
- `settings.json` (readable summary) and, optionally, the encryption key for stored integration secrets.
- `manifest.json` listing every file, size, checksum and whether the backup verified.

Not included: the GeoIP database file (download or upload it again after a restore — see
[Security & access](security-access.md#backup)), and files held in the **antivirus quarantine** (`<data>/quarantine`; see
[Antivirus](antivirus.md#quarantine)). Secrets such as AI API keys and the MaxMind license key are stored encrypted in the
database; they are only usable after a restore when the backup includes the encryption key (or you keep the key safely yourself).
Passkeys remain valid after a restore as long as the public address (domain) stays the same.

Consistency: originals are write-once and are always on disk before the database refers to them; the dump is a snapshot; files referenced by the snapshot are copied and verified; the backup folder is renamed from `.partial` only when complete. Unchanged originals are hard-linked from the previous backup to save space.

## Connecting the NAS {#nas}

Set this up in **Settings → Storage & backup → NAS connection**:

| Field | NFS example | SMB (Windows/Samba share) example |
|---|---|---|
| NAS connection | NFS | SMB |
| NAS server | `192.168.1.20` | `nas.local` |
| Share / export | `/volume1/backups` | `backups` |
| Folder on the share | `personaldocs` | `personaldocs` |
| SMB username / password / domain | — | `backup-user` / password / optional |
| Protocol version | optional (`4.1`) | optional (`3.0`) |

Click **Save settings**, then **Connect NAS**. A small system service mounts the share at `/mnt/pdnas`, creates the folder, checks that the app can write to it, and sets it as the backup destination automatically. The status line shows the result, with a plain-language explanation if something is wrong (wrong password, export not allowed for this container's IP, NAS unreachable, …). **Disconnect** unmounts it. The share is mounted again automatically after a reboot.

The SMB password is stored encrypted and written only to a root-only credentials file for the mount. The app never runs arbitrary mount options: only the fields above are used, and each is validated.

### Container requirements {#lxc-requirements}

Proxmox only allows NFS/SMB mounts inside **privileged** containers with the feature **mount=nfs;cifs** (`pct set <id> --features nesting=1,mount=nfs\;cifs`). The guided installer can create such a container for you.

If you prefer an **unprivileged** container (more isolated), let the Proxmox host mount the share and pass it in:

```
# on the Proxmox host
mount -t nfs 192.168.1.20:/volume1/backups /mnt/nas-backup      # or add to /etc/fstab
mkdir -p /mnt/nas-backup/personaldocs && chown 100000:100000 /mnt/nas-backup/personaldocs
pct set <id> -mp0 /mnt/nas-backup/personaldocs,mp=/mnt/nas-backup/personaldocs
```

Then choose **NAS connection: Already mounted**, set **Backup destination** to `/mnt/nas-backup/personaldocs`, and create the marker file once inside the container: `touch /mnt/nas-backup/personaldocs/.personaldocs-backup-target`.

## Backup destination {#target}

The destination is set automatically when the NAS is connected from Settings. For an *Already mounted* folder, enter its path in **Backup destination**. The marker file `.personaldocs-backup-target` and the *Require mounted destination* check stop backups from silently filling the local disk when the NAS is not mounted. Status shows reachability, last success, size, duration and verification.

## Identity {#identity}

Backup folders are named `backup-YYYYMMDD-HHMMSS-<installation identity>`; set the identity in Settings → General.

## Schedule {#schedule}

**Settings → Storage & backup → Backup settings**:

| Setting | Choices |
|---|---|
| Automatic backups | On / off. **Back up now** always works. |
| Backup frequency | **Daily**, **Weekly** (choose the day of the week) or **Monthly** (choose the day of the month) |
| Backup time | Local time in the installation timezone (default 02:30) |

- **Monthly on the 29th, 30th or 31st** runs on the last day of shorter months (for example 28 February).
- **Missed runs:** if the server was off at the scheduled time, the missed backup runs once, as soon as the
  scheduler is back. It never runs twice for the same slot, also after a restart.
- **Status:** the Backup status card shows the schedule ("Every Sunday at 02:30"), the next backup, the last
  success and the last failure with its reason.
- A backup that fails (for example the NAS is not mounted) is a critical notification for administrators.

## Retention {#retention}

Default: keep the 14 most recent successful backups, whatever the frequency (14 daily backups ≈ two weeks, 14 weekly ≈ three months). Older ones are pruned after a successful backup, but the newest *verified* backup is never pruned.

## Encryption key {#keys}

SMTP, Telegram, Google and mailbox passwords are encrypted with `/etc/personaldocs/encryption.key`. With **Include encryption key in backup** on (default), restores can decrypt them — protect the backup share like the server. If you turn it off, copy the key to a safe offline place yourself; without it, stored integration passwords must be re-entered after a restore (documents are unaffected).

## Restore {#restore}

On a fresh or broken installation (install first if needed):

```
sudo personaldocs restore /mnt/nas-backup/personaldocs/backup-20261003-023000-personaldocs --verify-only
sudo personaldocs restore /mnt/nas-backup/personaldocs/backup-20261003-023000-personaldocs
```

The command verifies every checksum, stops the services, restores the database, originals, previews and (if present) the key, then restarts and runs health checks. Restores are console-only by design.

## Pre-update backups {#pre-update}

**Install security updates…** in Settings → Security → OS updates first writes a database and settings backup to
`<data>/pre-update-backups` on the server itself; the newest three are kept. It is a quick safety net for an update,
not a replacement for the NAS backup, and it does not contain originals or a Proxmox snapshot. See
[OS updates](security-center.md#updates).

## Proxmox snapshots {#snapshots}

LXC snapshots are a useful extra layer but are not a verified application backup on their own. Take one on the Proxmox
host before installing OS updates if you want a full rollback.

## Integrity check {#integrity}

Runs nightly (without checksums) and on demand (with checksums) from Settings → Storage & backup, or `personaldocs integrity`. It reports missing or changed originals, broken version references and orphaned files. Files moved to the antivirus quarantine are not reported as missing; only a quarantined file whose quarantine copy has disappeared is reported. Repairs requeue missing previews and move unknown files to `/var/lib/personaldocs/quarantine` — nothing is deleted. A missing original can only come back from a backup.
