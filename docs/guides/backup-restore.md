<!-- audience: admin -->
# Backup and restore

## What a backup contains {#contents}

- A consistent PostgreSQL dump (accounts, groups, permissions, documents, versions, settings, audit log).
- All originals (every version), verified against their SHA-256 checksums.
- Previews and searchable copies (they can also be regenerated).
- `settings.json` (readable summary) and, optionally, the encryption key for stored integration secrets.
- `manifest.json` listing every file, size, checksum and whether the backup verified.

Consistency: originals are write-once and are always on disk before the database refers to them; the dump is a snapshot; files referenced by the snapshot are copied and verified; the backup folder is renamed from `.partial` only when complete. Unchanged originals are hard-linked from the previous backup to save space.

## Backup destination {#target}

1. Mount your NAS share in the LXC (for an unprivileged container, mount on the Proxmox host and bind-mount into the container, or use NFS/SMB inside a privileged one). Example `/etc/fstab` line inside the LXC: `nas:/volume1/backups /mnt/nas-backup nfs defaults,_netdev 0 0`.
2. Create the folder and marker once:
   ```
   mkdir -p /mnt/nas-backup/personaldocs && touch /mnt/nas-backup/personaldocs/.personaldocs-backup-target
   chown -R personaldocs: /mnt/nas-backup/personaldocs
   ```
3. Settings → Storage & backup → **Backup destination** `/mnt/nas-backup/personaldocs`.

The marker file and the *Require mounted destination* check stop backups from silently filling the local disk when the NAS is not mounted. Status shows reachability, last success, size, duration and verification.

## Identity {#identity}

Backup folders are named `backup-YYYYMMDD-HHMMSS-<installation identity>`; set the identity in Settings → General.

## Schedule {#schedule}

Default: daily at 02:30 (installation timezone). **Back up now** runs one immediately. These defaults were chosen conservatively by the developer and can be changed.

## Retention {#retention}

Default: keep the 14 most recent backups. Older ones are pruned after a successful backup, but the newest *verified* backup is never pruned.

## Encryption key {#keys}

SMTP, Telegram, Google and mailbox passwords are encrypted with `/etc/personaldocs/encryption.key`. With **Include encryption key in backup** on (default), restores can decrypt them — protect the backup share like the server. If you turn it off, copy the key to a safe offline place yourself; without it, stored integration passwords must be re-entered after a restore (documents are unaffected).

## Restore {#restore}

On a fresh or broken installation (install first if needed):

```
sudo personaldocs restore /mnt/nas-backup/personaldocs/backup-20261003-023000-personaldocs --verify-only
sudo personaldocs restore /mnt/nas-backup/personaldocs/backup-20261003-023000-personaldocs
```

The command verifies every checksum, stops the services, restores the database, originals, previews and (if present) the key, then restarts and runs health checks. Restores are console-only by design.

## Proxmox snapshots {#snapshots}

LXC snapshots are a useful extra layer but are not a verified application backup on their own.

## Integrity check {#integrity}

Runs nightly (without checksums) and on demand (with checksums) from Settings → Storage & backup, or `personaldocs integrity`. It reports missing or changed originals, broken version references and orphaned files. Repairs requeue missing previews and move unknown files to `/var/lib/personaldocs/quarantine` — nothing is deleted. A missing original can only come back from a backup.
