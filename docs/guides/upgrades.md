<!-- audience: admin -->
# Upgrades, rollback and repair

## Upgrade {#upgrade}

```
sudo personaldocs upgrade              # newest commit of the configured branch
sudo personaldocs upgrade --ref v0.2.0 # a specific tag
# or with the one-line installer (also runs the health check afterwards):
bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
```

Steps: take an exclusive lock; check free disk; run a **verified application backup** (aborts if the backup fails — use `--skip-backup` only if you have one); fetch and verify the requested revision; build it in a new release directory; run migration checks; stop the worker and scheduler; apply migrations; switch the `current` symlink; restart; run health checks. The previous and new versions are printed and logged.

If anything fails **before** migrations, the old release keeps running untouched. If health checks fail **after** switching, the previous release is restored automatically when the migrations are backwards-compatible; otherwise you are told to restore the pre-upgrade backup.

## Upgrading to the antivirus, authentik and security center release (Change Set M) {#change-set-m}

```
sudo personaldocs upgrade
sudo personaldocs post-upgrade   # once, when coming from an older release: installs ClamAV and the host helper
sudo personaldocs status     # clamav-daemon, clamav-freshclam and personaldocs-host.path should be active
sudo personaldocs doctor     # ClamAV, signature age, host helper, HTTPS, storage thresholds, pending reboot
```

The upgrade is run by the previously installed `personaldocs` command, which does not know the new installer steps
yet; `post-upgrade` then runs the steps of the new command (ClamAV, host helper units, optional security tools). It is
safe to repeat, keeps all data, keys and accounts, and `sudo personaldocs repair` does the same and more. The one-line
`personal-DM.sh -- upgrade` runs `post-upgrade` for you, and from this release on `personaldocs upgrade` calls it
itself, so later upgrades need no extra step.

This release adds **five database migrations**, applied automatically after the verified backup:

- `accounts.0005_administrator_role`: the **Administrator** role (`is_admin`). No existing account gets it.
- `accounts.0006_external_identity`: authentik account links.
- `library.0008_antivirus`: the scan status per file. Every existing file is marked *Not scanned* ("Stored before
  antivirus scanning was added").
- `security.0002_antivirus` and `security.0003_security_center`: library scan runs, security test history, OS update
  and reboot records, and security records.

After upgrading:

- **Antivirus:** `clamav`, `clamav-daemon` and `clamav-freshclam` are installed and clamd listens only on the local
  socket `/run/clamav/clamd.ctl`. ClamAV needs about **1.2 GB of memory**; on a smaller machine use
  `sudo personaldocs repair --without-antivirus` and turn scanning off in Settings → Security → Antivirus. The first
  signature download can take a few minutes. Then run **Scan entire existing library** in Settings → Security →
  Antivirus so older files get a real status. See [antivirus](antivirus.md#install).
- **Host helper:** `personaldocs-host.path` is installed, so Settings → Security can check and install Debian
  security updates, update ClamAV signatures, inspect the firewall and reboot. Nothing is installed automatically.
  See [OS updates](security-center.md#updates).
- **HSTS:** for an `https://` public origin the app now sends `Strict-Transport-Security` (one year). Set
  `PD_HSTS_SECONDS=0` in `/etc/personaldocs/personaldocs.env` to turn it off, or a smaller value while testing. See
  [reverse proxy](reverse-proxy.md#hsts).
- **Settings → Security reorganised:** it is now the security center (Overview, Antivirus, Security test, OS updates,
  Firewall, Security records, Storage). The country/IP access policy, GeoIP, alerts and traffic analytics moved to
  **Settings → Security → Access policy**; their values are unchanged.
- **Deployment exposure** starts as *LAN only*. If the site is published on the Internet, change it and check
  **Internet Ready**. See [Internet Ready](security-center.md#internet-ready).
- **authentik** stays off until you configure it. See [authentik](authentik.md#setup).
- **Nothing is deleted:** existing accounts, folders, documents, versions and records are kept. Security records are
  kept for one year by default.

To go back, restore the pre-upgrade backup: this release adds migrations, so `sudo personaldocs rollback` is refused
unless the previous release knows them (see [Rollback](#rollback)). ClamAV stays installed; remove it with
`apt-get remove clamav-daemon clamav-freshclam` if wanted.

## Upgrading to the selective OCR / Overview release (Change Sets K and L) {#selective-ocr-overview}

```
sudo personaldocs upgrade
# or: bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
sudo personaldocs doctor     # also reports missing OCR language packs
sudo personaldocs repair     # only if doctor reports a missing language pack
```

This release adds **three database migrations**, applied automatically after the verified backup:

- `library.0006`: OCR state, sources, languages and errors per document, and the OCR policy fields per document type.
- `library.0007`: fills the policy. Each type gets its expected fields and English as default language, and the
  *Employee / company ID* type is added. On an **existing installation** (setup already completed) every type and
  untyped documents are set to **Automatic with AI allowed**, so uploads are recognised as before. Documents that
  were already recognised get the state *Confirmed* (or *Needs review* if suggestions are open). **New
  installations** start with **Manual** OCR and no AI access to recognised text.
- `core.0003`: the weather cache and holiday corrections tables.

After upgrading:

- **Accounts:** every existing account, folder and document is kept. No accounts are added or removed. New
  installations create only the Main Administrator; see [setup](setup.md#six-accounts).
- **Python packages:** the new dependencies (`holidays`, `hijridate`, `python-dateutil`, `six`) are installed by the
  upgrade in the new release.
- **OCR language packs:** upgrade and repair install the Tesseract packs for the offered languages (English, Arabic
  and Hindi by default: `tesseract-ocr-ara`, `tesseract-ocr-hin`). If `doctor` lists a missing pack, run
  `sudo personaldocs repair`.
- **OCR policy:** review **Settings → OCR & processing → OCR policy per document type** and switch types to *Manual*
  or *Disabled* where automatic OCR or AI is not wanted. See [selective OCR](ocr-corrections.md#selective).
- **Overview:** people who had saved a widget choice keep it; they add the new widgets (Today, Weather, Month
  calendar, Upcoming holidays, Documents summary, Shared with me, Recent activity) with **Customize Overview**.
  People who never chose get the new default set. See [Overview](overview.md).
- **Weather** is off until an administrator enables it in Settings → Overview & sign-in.
- **Sign-in page:** uses the *Minimal* design and the default title until you change it. See
  [sign-in page designs](login-designs.md).

To go back, `sudo personaldocs rollback` works only while the previous release knows every applied migration; this
release adds migrations, so otherwise restore the pre-upgrade backup (see [Rollback](#rollback)).

## Upgrading to the browsing, OCR and installer release (Change Set J) {#change-set-j}

```
sudo personaldocs upgrade
sudo personaldocs repair     # installs tesseract-ocr-osd (orientation detection) on older installations
sudo personaldocs doctor
```

This release adds **three database migrations**, applied automatically by the upgrade after its verified backup:

- `library.0004`: OCR quality per version and the "Does not expire" flag. Existing documents are unchanged.
- `library.0005`: sub-folders whose icon was assigned automatically now use the standard 📁 icon. Folders directly
  in a person's area keep their suggested icon, and icons someone chose are kept.
- `core.0002`: if the application name is still the old default "Personal Documents", it becomes "Personal
  Documents Management System". A name you chose is kept.

After upgrading:

- **Folder view:** each person's view (List, Thumbnails, Details) and sort order are now saved to their account.
  The first time, everyone starts with List / Newest first.
- **OCR:** new uploads use the improved pipeline. To improve an older scan, open it and use **Re-run OCR…** in the
  Text (OCR) tab.
  Confirmed details are never overwritten.
- **One-line installer:** from now on you can also upgrade with
  `bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade`
  (the raw URL works only while the repository is public).
- **Browser cache:** the app reloads its new version automatically; if a page looks old, reload it once.

## Upgrading to the public-release corrections (October 2026) {#change-set-2026-10-ui}

Same commands as below — `sudo personaldocs upgrade`, then (once, if you never ran it after the security release)
`sudo personaldocs repair`, then `sudo personaldocs doctor`. This step adds **no database migrations**; all new
options are stored as settings. After upgrading:

- **Notifications:** your earlier channel choices become the starting point of the new per-event table. Check
  **Settings → Notifications → Critical notifications / Channels for critical notifications / Delivery problems**:
  if email or Telegram are not configured yet, either configure them (Settings → Connections) or remove them from
  the critical channels.
- **Backups** keep running daily at the same time; choose weekly or monthly in Settings → Storage & backup if you
  prefer.
- **Dashboard** (now called Overview): your previous widget list is kept (sections that were always shown stay
  visible); use **Customize Overview** to change it.
- **Browser cache:** the app reloads its new version automatically; if a page looks old, reload it once.

## Upgrading from the previous release (profile photos, Local AI, security, passkeys) {#change-set-2026-10}

```
sudo personaldocs upgrade     # backup, new release, migrations, restart, health check
sudo personaldocs repair      # runs the NEW personaldocs command once: GoAccess + access log (safe, keeps all data)
sudo personaldocs doctor
```

The second command is needed only once, when coming from a release older than this change set: the upgrade is run by
the previously installed `personaldocs` command, which does not yet know the new steps. Together they:
- back up first
- apply the new database tables (login audit, access policy, AI, passkeys, profile photos) without touching existing data
- install the new Python libraries in the new release
- install GoAccess when possible (never fatal)
- add the access log and its rotation, and restart the services

Nothing changes for existing users until you switch features on:
- country filtering is off
- Local AI is off
- two-step verification is not required
- existing authenticator apps keep working
- passwordless sign-in is off

Afterwards, optionally:
1. Settings → Security & access (since Change Set M: Settings → Security → Access policy): enter MaxMind credentials and **Update now** for GeoIP; review alerts; enable traffic analytics.
2. Settings → Authentication: decide on passkeys / passwordless / required two-step verification.
3. Settings → Local AI: add a profile pointing at your LAN AI server.
4. `sudo personaldocs doctor` to confirm the real client IP, GeoIP, passkey origin and AI checks.

## Rollback {#rollback}

```
sudo personaldocs rollback
```

Switches back to the previous release only if its code knows every migration applied in the database (same schema). If the newer version changed the schema, running old code is refused — restore the pre-upgrade backup instead (`personaldocs restore /mnt/nas-backup/personaldocs/backup-...`).

## Repair {#repair}

```
sudo personaldocs repair
```

Diagnoses first, then: reinstalls missing packages, fixes ownership and permissions of data and config, recreates missing directories, reinstalls systemd units, applies pending migrations, requeues jobs whose worker died, rebuilds search vectors, restarts services. It **never** recreates the database, regenerates keys, deletes originals or re-runs account setup.

Separate operations:

| Operation | Command | Destructive? |
|---|---|---|
| Safe repair | `personaldocs repair` | No |
| Storage repair | `personaldocs integrity --repair --confirm` | No (orphans are quarantined) |
| Restore from backup | `personaldocs restore PATH --yes` | Replaces the database |
| Permanent deletion | Archive page, one document at a time | Yes |
