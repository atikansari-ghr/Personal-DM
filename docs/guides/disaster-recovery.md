<!-- audience: main_admin -->
<!-- reviewed: 2026-10-11 -->
# Disaster recovery runbook

Use this runbook to bring the whole application back from an encrypted recovery point. It covers:

- a lost or broken server;
- a corrupted installation;
- accidental mass deletion;
- a suspected cyberattack.

## Scope {#scope}

> [!IMPORTANT]
> Personal DM restores the **application**: database, documents and versions, OCR data, settings and encrypted
> secrets. It does this onto a clean, supported **Debian 13** system (normally a Proxmox LXC container).
>
> Recreating the Proxmox host, the LXC container, storage or networking is **outside** Personal DM's backup. Use
> Proxmox's own tools for that, then continue here.

What you need:

- a clean Debian 13 container (2 CPU, 6 GB RAM recommended), or the damaged installation;
- the encrypted backups: a destination folder, a downloaded `.tar`, a NAS share, S3, Google Drive or OneDrive;
- the **Backup Recovery Key** (`PDRK1-…`), **or** the **Emergency Recovery Package** (`.pdrp`) and its passphrase.

> [!CAUTION]
> Without the key or the emergency package and its passphrase, encrypted backups cannot be opened by anyone,
> including Personal DM.

## 1. Choose the path {#choose-path}

The installer offers two paths:

- **New Installation**: an empty system and a new first-run setup.
- **Recover Existing Installation**: install only what is needed, then restore. You do **not** create a new
  administrator account or set up the application first.

On a clean container, as root:

```
bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)"
```

Choose **2) Recover Existing Installation**. To skip the menu, add `-- recover` at the end. Answer the installer's
questions (address, port), but do **not** finish the web setup: the restored database brings every account back. On a server where Personal DM is already installed (damaged data):

```
sudo personaldocs recover
```

Both start the same guided recovery. While it runs, the web address answers *Recovery in progress* (HTTP 503). A
partly recovered instance is never shown as healthy.

## 2. Choose where the backup is {#sources}

| Choice | What you give |
| --- | --- |
| **Local folder or USB stick** | The folder that contains the recovery points (folders named like `0f1c…/g1/`). |
| **Downloaded package file (.tar)** | The path of the file you downloaded from **Recovery points → Download** (copy it to the server first, e.g. with `scp`). |
| **NAS share** | NFS or SMB server, share, and (SMB) username and password typed now. The share is mounted read-only at `/mnt/pd-recovery`. |
| **S3-compatible storage** | `https://endpoint/bucket/prefix`, then a temporary access key and secret key. |
| **Google Drive** | The folder id and a **temporary access token**. |
| **Microsoft OneDrive** | The folder (default `Apps/PersonalDocs`) and a **temporary access token**. |

### Temporary bootstrap credentials {#bootstrap}

On a new server, your normal destination credentials are inside the encrypted backup, so you cannot use them yet. The
credentials you type during recovery:

- are used only to fetch the encrypted packages;
- are kept in memory or in the environment of the recovery command;
- are never saved as application credentials.

After the restore, the original (encrypted) integration settings come back, and each one is verified separately (step
7).

For Google Drive or OneDrive, get a short-lived access token with your own OAuth app, for example with the Google OAuth
Playground or the Microsoft Graph Explorer. Use read access to the backup folder only.

> [!WARNING]
> Live recovery from Google Drive and OneDrive could not be tested automatically, because it needs real accounts. Test
> it once with your own account before you depend on it.

## 3. Pick the recovery point and give the key {#key}

1. The tool lists the recovery points it finds: date, Full or incremental, key generation, application version, and
   chain length.
2. Enter the id, or press Enter for the newest point.
3. Choose **Backup Recovery Key** (typed or pasted; it is never shown on screen or written to disk) or **Emergency
   Recovery Package** (file path and passphrase).

A wrong key stops the recovery **before anything is changed**.

## 4. Integrity and compatibility checks {#checks}

The tool downloads the whole chain (still encrypted) into `/var/lib/personaldocs/recovery/work` and checks:

- the checksum of every file, and that it decrypts and authenticates;
- the manifest and the chain: an incremental's base Full backup and earlier incrementals must all be present;
- compatibility. A backup made by a **newer** Personal DM version is refused; upgrade the code first. Older backups are
  fine: newer database migrations are applied after the restore.

## 5. Restore Impact Analysis {#impact}

Before you confirm, the tool prints:

- the number of accounts, groups, folders, documents, versions and access rules in the backup;
- whether the current database is empty or will be **replaced** (with the current numbers);
- the disk space needed and free;
- the secrets in the backup (names only);
- the planned actions for the chosen mode.

## 6. Choose the mode {#mode}

### Normal disaster recovery {#normal}

Use this after hardware failure, corruption or accidental deletion.

- Everything is restored as completely as possible.
- Existing sessions stay valid.
- External integrations are restored but **stay on hold** until a connection test passes (step 7).
- WhatsApp Personal sessions are restored and reconnected. If WhatsApp rejects a session, it shows
  **Reconnect Required** and the person links again with a QR code.

### Compromise / cyberattack recovery {#compromise}

Use this when you suspect someone else had access. Choose a recovery point from **before** the incident. This mode:

- restores documents, accounts, permissions, settings and protected secrets from that point;
- **ends every Personal DM session**, so everyone must sign in again;
- **revokes remembered-device trust**: every recognised device becomes Unrecognized;
- **keeps passkeys and authenticator apps**, unless you run the command with `--reset-mfa` (a separately warned
  action);
- never reconnects WhatsApp linked devices automatically; each person links again with a fresh QR code;
- holds notification and cloud integrations until they are verified;
- requires a **security review** by the main administrator and records prominently that Compromise mode was used.

GeoIP or map data are never used on their own to decide whether a restored sign-in is safe.

Type **RECOVER** to start. The services are stopped, then:

1. the database is restored and migrated;
2. the files are restored with checksums;
3. the secrets are restored;
4. the security actions for the chosen mode are applied.

## 7. Integration verification {#integrations}

Every restored external integration starts **on hold**. Nothing is sent or fetched through it until a safe connection
test passes. A test never sends a message.

| Integration | Test |
| --- | --- |
| Email (SMTP) | Connect and sign in. |
| Telegram | Bot token check (`getMe`). |
| PWA push | Push keys restored. |
| Discord | The webhook's details are read; nothing is posted. |
| WhatsApp Personal | Normal: reconnect; Compromise: *Reconnect Required*. |
| Backup destinations | Reachability and free space. |
| Email import accounts | Sign in and out. |
| Google / authentik sign-in | Configuration restored; sign in once to confirm. |

Expired or revoked credentials show **Action Required**. Fix them in Settings, then open **Settings → Backup & Recovery
→ Overview → After the recovery** and click **Verify again**. Use **Accept as fixed** for an item you fixed another way.

## 8. Health checks and report {#report}

The tool then validates the result:

- the number of users, folders, documents and versions matches the catalogue;
- every version has its original file;
- the restored secrets can be decrypted with the restored key;
- `manage.py check` passes.

It writes the **Recovery & Security Report**:

| Section | Contents |
| --- | --- |
| Restore | Mode, restore point and chain, integrity and chain verification, database/schema state. |
| What was restored | Documents, folders and versions; users, groups and access rules; settings. |
| Integrations | Each one's state and what needs re-authorisation; the WhatsApp reconnect or relink status. |
| Security | Sessions ended and devices untrusted (Compromise mode). |
| Problems | Warnings, and failed or skipped items. |
| Follow-up | Recommended actions for the administrator. |

The report **never** contains passwords, the Recovery Key, emergency package contents, API tokens, OAuth secrets,
webhook addresses or linked-device credentials. It is saved in `/var/lib/personaldocs/recovery/report-<id>.json` and
listed under **Settings → Backup & Recovery → Restores & reports**, where **Export report (JSON)** downloads it.

Only after the report is written does the application open again (the 503 page disappears).

## 9. After recovery: security review {#review}

Do these in order:

1. Sign in as the main administrator and open the Recovery & Security Report.
2. After a **Compromise** recovery:
   - change your password;
   - review every account, passkey and authenticator app;
   - review the sign-in map;
   - remove anything you do not recognise;
   - rotate the Backup Recovery Key.
   Then mark the review as completed (**After the recovery** card).
3. Make a **Full backup** now.
4. Export a new **Emergency Recovery Package** if the key generation changed.
5. Install the GeoIP database again and run `sudo personaldocs repair` (this reinstalls the PaddleOCR models if you use
   them).
6. Run `sudo personaldocs doctor`; every line should be OK.

## Failure, resume and rollback {#resume}

- **A step failed.** The tool stops and the application stays closed (503). Fix the cause (space, network, wrong key)
  and run `sudo personaldocs recover` again. Steps that already finished are skipped: files fetched intact are not
  downloaded again. Check progress with `sudo personaldocs manage recover status`.
- **Wrong recovery point.** Run the recovery again with another point. Each run replaces the database and files with
  that point.
- **Rollback.** Before the database is replaced, the previous installation key and secret key are kept as
  `*.before-recovery` files in `/etc/personaldocs`. Use a Proxmox snapshot taken before the recovery for a full
  rollback.
- **Space.** The work folder needs about twice the size of the chain. Free space or mount a larger disk at
  `/var/lib/personaldocs`.

## Command reference {#cli}

```
sudo personaldocs recover                                   # guided (all of the above)
sudo personaldocs manage recover list --source local:/media/usb/personaldocs
sudo personaldocs manage recover analyze --source local:/media/usb/personaldocs --key-file /run/key.txt
sudo personaldocs manage recover run --source s3:https://s3.example.com/family-backups/personaldocs \
     --point latest --mode compromise --key-file /run/key.txt --yes
sudo personaldocs manage recover integrations               # verify held integrations again
```

For S3 sources, the bootstrap credentials are read from `PD_RECOVER_S3_ACCESS_KEY` and `PD_RECOVER_S3_SECRET_KEY`. For
Google Drive and OneDrive, the token is read from `PD_RECOVER_ACCESS_TOKEN`. None of them is stored.
