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

## Upgrading to Change Set P (passkey sign-in, password reset, ClamAV repair) {#change-set-p}

```
sudo personaldocs upgrade
# or: bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
sudo personaldocs antivirus status   # every ClamAV check and the likely cause of any problem
sudo personaldocs doctor             # starts with the same ClamAV diagnosis, then the app checks
```

(The change prompt for this release called it "Change Set O" with tests AT-176..AT-190. Those numbers were already
used by the rich notifications release, so in this repository it is **Change Set P** with tests **AT-196..AT-210**:
prompt AT-176 is AT-196, AT-177 is AT-197, and so on up to AT-190, which is AT-210.)

No new system packages and no new Python packages. This release adds **two database migrations**, applied
automatically after the verified backup:

- `accounts.0007_passkey_mode`: replaces the on/off setting `auth.allow_passwordless` with **Passkey sign-in mode**
  (`auth.passkey_mode`). An explicit earlier choice is kept: saved *off* becomes **Password + Passkey**, saved *on*
  becomes **Passwordless**, never chosen becomes **Passwordless** (the new default). In passwordless mode it also turns
  passwordless sign-in on for accounts that already have a discoverable passkey. See
  [passkeys after upgrading](passkeys.md#upgrade).
- `notify.0003_template_brand_footer`: **Branding name** and **Footer / help text** for notification templates.

**The ClamAV repair runs automatically.** The post-upgrade step (which `personaldocs upgrade` and the one-line
upgrade run for you) now runs the [antivirus repair](antivirus.md#repair) instead of assuming that installed packages
mean antivirus works. It:

- rewrites `LocalSocket` in `/etc/clamav/clamd.conf` to the systemd socket path `/run/clamav/clamd.ctl` (the original
  is backed up once as `/etc/clamav/clamd.conf.personaldocs-backup`) and removes any TCP listener;
- installs the restart drop-in `/etc/systemd/system/clamav-daemon.service.d/50-personaldocs.conf` and the tmpfiles
  entry `/etc/tmpfiles.d/personaldocs-clamav.conf`;
- downloads missing signatures, starts the socket and the daemon in the right order, and runs a clean + EICAR
  self-test.

This can take **a few minutes** (up to 4 minutes of waiting) while clamd loads its signatures. It fixes the
"Unavailable … `/run/clamav/clamd.ctl` (FileNotFoundError)" state described in
[antivirus troubleshooting](antivirus.md#socket-missing). If it reports a problem, the upgrade itself still
completes; run `sudo personaldocs antivirus repair` again after fixing the cause (for example too little memory).

What changes:

- **Passwordless is the default** unless it was explicitly turned off before. The sign-in page shows **Sign in with
  Passkey** before the password, and people who already have a discoverable passkey can use it straight away. See
  [the sign-in screen](passkeys.md#sign-in-screen).
- People can sign in with their **email address** instead of the username (when it belongs to exactly one active
  account).
- **Administrators** (the Administrator role) can now reset the passwords of accounts that are not main
  administrators, in Settings → Users. See [password reset](password-reset.md).
- A **temporary password reset always signs the person out** on every device.
- New security notifications (password reset requested, administrator reset, temporary password issued, password
  reset completed, account locked, Google linked or removed) with [mandatory security text](notifications.md#security-templates).
- The Antivirus page shows **Healthy / Degraded / Unavailable / Error** based on a real scan, and **Run self-test** and
  **Diagnose / Repair**. Unavailable and Error now put Security Health **At Risk**.

Check by hand after upgrading:

1. Settings → Security → Antivirus shows **Healthy** and **Run self-test** passes.
2. **Reboot the LXC once** (or `pct reboot <id>` on the Proxmox host) and check the Antivirus page again; reboot
   persistence has not been tested on a real host yet.
3. Sign in with **Sign in with Passkey** on each device and browser you use.
4. Send a password reset email to yourself (Forgot password? on the sign-in page) and check that it arrives and the
   link works once.
5. If you prefer passkeys only after the password, set Settings → Authentication → **Passkey sign-in mode** to
   *Password + Passkey*.

To go back, restore the pre-upgrade backup: this release adds migrations, so `sudo personaldocs rollback` is refused
unless the previous release knows them (see [Rollback](#rollback)). The ClamAV changes are host configuration and stay
in place; they also work with the previous release. To restore Debian's ClamAV configuration, copy
`/etc/clamav/clamd.conf.personaldocs-backup` back to `/etc/clamav/clamd.conf` and restart `clamav-daemon`. The drop-in
and tmpfiles files can stay.

## Upgrading to the rich notifications release (Change Set O) {#change-set-o}

```
sudo personaldocs upgrade
# or: bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
```

No extra post-upgrade step is needed for this release. If you are coming from a release **before Change Set M**,
the `sudo personaldocs post-upgrade` step described [below](#change-set-m) still applies once. No new system packages
are installed; two small Python packages for Web Push, `http-ece` 1.2.1 and `py-vapid` 1.9.4, are installed
automatically with the release.

This release adds **one database migration**, applied automatically after the verified backup:

- `notify.0002_rich_notifications`: event, category, severity, icon, summary, details and a TEST flag on in-app
  notifications; event, severity, the HTML part, the push payload, the provider's message id and a TEST flag on
  outgoing messages; new tables for push subscriptions, notification templates and expiry snoozes. Its data step
  sorts existing in-app notifications into categories by their kind; their title, text, links and read state are
  unchanged.

What changes and what stays:

- Existing SMTP and Telegram configuration, everyone's preferences, the critical events and their channels and the
  expiry schedules are unchanged.
- Email becomes an HTML message with a plain-text part; Telegram messages get formatting and buttons (buttons only on
  an `https://` address); the in-app list becomes the Notification Center with banners.
- Push is a new channel. It is **never added to anyone's channels automatically**; it needs the `https://` address.
- The keys for signing push messages are created on first use, stored encrypted in the database and included in
  backups.

After upgrading (optional):

1. **Settings → Notifications → Templates**: review the wording of the events you care about and use
   **Send a TEST message to yourself** to see the email, Telegram, in-app and push versions. See
   [templates](notifications.md#templates).
2. Decide on **Include document numbers in email/Telegram** (off by default) and the **repeat cooldown** (24 hours).
   See [privacy](notifications.md#privacy) and [noise control](notifications.md#noise).
3. Family members who want push turn it on **per device** in My account → Notifications → *Push notifications on
   this device* (on iPhone/iPad after adding the app to the Home Screen). See [push](notifications.md#push).

To go back, restore the pre-upgrade backup: this release adds a migration, so `sudo personaldocs rollback` is refused
unless the previous release knows it (see [Rollback](#rollback)).

## Upgrading to the document types release (Change Set N) {#change-set-n}

```
sudo personaldocs upgrade
# or: bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
sudo personaldocs doctor     # info line: typed / untyped / with suggestions
```

No extra post-upgrade step is needed for this release. If you are coming from a release **before Change Set M**,
the `sudo personaldocs post-upgrade` step described [below](#change-set-m) still applies once. No new system packages
are installed.

This release adds **one database migration**, applied automatically after the verified backup:

- `library.0009_document_type_templates`: document type templates (fields with type, role, required, OCR/AI and
  search flags), per-type reminder days, the source and confirmation of each document's type, pending type
  suggestions, provenance of each detail, and the suggested type of a folder. Its data step:
  - gives every existing type its template: the standard fields of its starting template plus the fields its OCR
    policy listed;
  - keeps the type of every **typed** document and marks it confirmed with the source *Migrated*;
  - leaves **untyped** documents untyped (types are not guessed from field names);
  - turns values of typed documents that are not in the template into **additional details** of that document,
    except confirmed issue, expiry and "does not expire" values, whose field is added to the template so dates and
    reminders keep working;
  - deletes nothing.

After upgrading (optional):

1. `sudo personaldocs manage document_types report` prints how many documents are typed, untyped and have
   suggestions.
2. Set a **suggested document type** on folders that hold one kind of document (folder ⋮ → *Suggested document
   type…*). It only affects new uploads. See [folder suggestions](document-types.md#folder-suggestions).
3. **Settings → Documents & folders → Document types → Review untyped documents**: assign types to older untyped
   documents; nothing is applied until you confirm. See [review](document-types.md#review-untyped).
4. Check the templates and reminder days of the types you use. See [managing types](document-types.md#manage).

To go back, restore the pre-upgrade backup: this release adds a migration, so `sudo personaldocs rollback` is refused
unless the previous release knows it (see [Rollback](#rollback)).

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
