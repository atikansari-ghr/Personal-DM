# Settings reference

Generated from `backend/apps/core/registry.py` by `manage.py settings_reference`. Do not edit by hand.

## Section: general

### Application name (`general.app_name`)

Name shown in the header, browser tab and notifications.

- **Default:** `'Personal Documents Management System'`
- **Allowed values:** –60
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Changes the visible name immediately.
- **Restart needed:** no
- **Learn more:** [settings#general](guides/settings.md#general)

### Installation timezone (`general.timezone`)

Timezone used for expiry calculations, reminder send time and date display.

- **Default:** `'Asia/Riyadh'`
- **Allowed values:** timezone
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Reminder day boundaries and send time follow this timezone from the next scheduler run.
- **Restart needed:** no
- **Learn more:** [expiry-rules#timezone](guides/expiry-rules.md#timezone)
- **Example:** Asia/Riyadh

### Date display (`general.date_format`)

How dates are displayed throughout the app.

- **Default:** `'d MMM yyyy'`
- **Allowed values:** d MMM yyyy, yyyy-MM-dd, dd/MM/yyyy, MM/dd/yyyy
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Display only; stored values are unaffected.
- **Restart needed:** no
- **Learn more:** [settings#general](guides/settings.md#general)

### Installation identity (`general.installation_id`)

Label identifying this installation in backups and diagnostics.

- **Default:** `'personaldocs'`
- **Allowed values:** –60
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Used in backup folder names and diagnostics.
- **Restart needed:** no
- **Learn more:** [backup-restore#identity](guides/backup-restore.md#identity)

## Section: documents

### Stored filename template (`documents.filename_template`)

Managed path used for newly uploaded originals, relative to the storage folder. Existing files are not renamed.

- **Default:** `'{owner}/{year}/{title}--{version_id}'`
- **Allowed values:** –200
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Applies to new uploads only; existing originals keep their path.
- **Restart needed:** no
- **Learn more:** [originals-versions#naming](guides/originals-versions.md#naming)
- **Example:** {owner}/{type}/{title}--{version_id}

### Maximum upload size (MB) (`documents.max_upload_mb`)

Largest single file accepted.

- **Default:** `512`
- **Allowed values:** 1–10240
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Larger uploads are rejected before storage.
- **Restart needed:** no
- **Learn more:** [folder-imports#limits](guides/folder-imports.md#limits)
- **Example:** 512

### Blocked extensions (`documents.blocked_extensions`)

Comma separated extensions that are refused at upload (they would never execute anyway).

- **Default:** `''`
- **Allowed values:** str
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Refuses matching uploads.
- **Restart needed:** no
- **Learn more:** [office-dicom#formats](guides/office-dicom.md#formats)
- **Example:** exe,bat

### Suggest folder emoji (`documents.emoji_suggestions`)

Suggest an icon from the name (Travel ✈️, Passport 🛂 …) for folders created directly in a person's or the family area. Deeper sub-folders get the standard 📁 icon; anyone can choose another icon.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** New folders get a suggested emoji; existing overrides stay.
- **Restart needed:** no
- **Learn more:** [folder-imports#emoji](guides/folder-imports.md#emoji)

### Folder template for new members (`documents.member_template`)

Optional folders (one path per line, use / for sub-folders) offered when adding a person or applied to an existing folder. Nothing is created unless you choose to apply it.

- **Default:** `'Identity/Passport\nIdentity/Visa & Residence\nIdentity/National ID\nEducation\nMedical\nTravel\nBanking & Finance\nInsurance\nVehicle\nHouse & Property\nCertificates'`
- **Allowed values:** –4000
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Used the next time a template is applied; existing folders are never removed or renamed.
- **Restart needed:** no
- **Learn more:** [folder-imports#templates](guides/folder-imports.md#templates)
- **Example:** Identity/Passport

### Approved server import folders (`documents.import_roots`)

Server/NAS paths (one per line) from which the main administrator may import. Sources are copied, never modified.

- **Default:** `''`
- **Allowed values:** str
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Only listed folders can be scanned by the server import wizard.
- **Restart needed:** no
- **Learn more:** [folder-imports#server](guides/folder-imports.md#server)
- **Example:** /mnt/nas/old-documents

## Section: processing

### Local OCR (`processing.ocr_enabled`)

Run local English OCR (Tesseract) on scans and images.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** When off, scans are stored and previewed but not text-searchable.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#ocr](guides/ocr-corrections.md#ocr)

### OCR language (`processing.ocr_language`)

Tesseract language pack used.

- **Default:** `'eng'`
- **Allowed values:** eng
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Only English is supported in the initial release.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#ocr](guides/ocr-corrections.md#ocr)

### Concurrent OCR/conversion jobs (`processing.heavy_concurrency`)

How many expensive jobs run at once. 1 is recommended for 2 vCPU / 4 GB.

- **Default:** `1`
- **Allowed values:** 1–8
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Higher values use more CPU and memory; takes effect when the worker restarts.
- **Restart needed:** yes (worker)
- **Learn more:** [ocr-corrections#limits](guides/ocr-corrections.md#limits)
- **Example:** 1

### Processing timeout (seconds) (`processing.timeout_seconds`)

Maximum time for one OCR or conversion step.

- **Default:** `600`
- **Allowed values:** 30–7200
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Jobs exceeding this fail with a timeout error and can be retried.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#limits](guides/ocr-corrections.md#limits)

### Maximum pages for OCR (`processing.max_pages`)

PDFs above this page count are stored without OCR.

- **Default:** `300`
- **Allowed values:** 1–5000
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Protects the server from very large scans.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#limits](guides/ocr-corrections.md#limits)

### Maximum image size (megapixels) (`processing.max_image_megapixels`)

Images above this are refused for processing (decompression bomb protection).

- **Default:** `120`
- **Allowed values:** 1–1000
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Larger images are stored but not processed.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#limits](guides/ocr-corrections.md#limits)

## Section: notifications

### Expiry reminder days (`notifications.expiry_days`)

Days before expiry when reminders are sent. 0 means on the expiry day. Reminders stop after the expiry day.

- **Default:** `[90, 60, 30, 7, 0]`
- **Allowed values:** int_list
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Applies from the next scheduler run; already-passed thresholds are not re-sent.
- **Restart needed:** no
- **Learn more:** [expiry-rules#schedule](guides/expiry-rules.md#schedule)
- **Example:** 90 means notify 90 days before expiry

### Reminder send time (`notifications.send_time`)

Local time of day reminders are sent.

- **Default:** `'08:00'`
- **Allowed values:** time
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Next run uses the new time.
- **Restart needed:** no
- **Learn more:** [expiry-rules#schedule](guides/expiry-rules.md#schedule)
- **Example:** 08:00

### Notify document owner (`notifications.notify_owner`)

Owner receives expiry reminders.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Disabling stops owner reminders.
- **Restart needed:** no
- **Learn more:** [expiry-rules#recipients](guides/expiry-rules.md#recipients)

### Notify head of family (`notifications.notify_head`)

The owner's designated family head receives reminders.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Disabling stops head reminders.
- **Restart needed:** no
- **Learn more:** [expiry-rules#recipients](guides/expiry-rules.md#recipients)

### Default channels for expiry reminders (`notifications.default_channels`)

Channels used for expiry reminders by people who have not chosen their own.

- **Default:** `['in_app', 'email']`
- **Allowed values:** channel_list
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Affects people without personal preferences.
- **Restart needed:** no
- **Learn more:** [expiry-rules#channels](guides/expiry-rules.md#channels)

### Required channels for expiry reminders (`notifications.required_channels`)

Channels people cannot turn off for expiry reminders. In-app is always on.

- **Default:** `['in_app']`
- **Allowed values:** channel_list
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** People see these channels locked on; missing contact details are flagged.
- **Restart needed:** no
- **Learn more:** [expiry-rules#channels](guides/expiry-rules.md#channels)

### Critical notifications (`notifications.critical_events`)

Events people cannot turn off. They always arrive in-app and on the critical channels below.

- **Default:** `['security.passkey_added', 'security.passkey_removed', 'security.totp_enabled', 'security.totp_disabled', 'security.recovery_codes', 'security.passwordless', 'security.admin_recovery', 'security.new_country', 'security.failed_logins', 'security.policy_exception', 'security.policy_change', 'security.auth_policy', 'backup.failed', 'integrity.failed']`
- **Allowed values:** security.passkey_added, security.passkey_removed, security.totp_enabled, security.totp_disabled, security.recovery_codes, security.passwordless, security.admin_recovery, security.new_country, security.new_ip, account.login, security.failed_logins, security.policy_exception, security.policy_change, security.auth_policy, security.health, backup.failed, integrity.failed, expiry.reminder, document.added, document.archived, document.shared, import.finished, processing.completed, processing.failed
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Applies to the next notification; people see these locked on.
- **Restart needed:** no
- **Learn more:** [expiry-rules#critical](guides/expiry-rules.md#critical)

### Channels for critical notifications (`notifications.critical_channels`)

Every critical notification is also sent on these channels. Missing email addresses or unlinked Telegram are flagged to the person and to you, never reported as sent.

- **Default:** `['in_app', 'email', 'telegram']`
- **Allowed values:** channel_list
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Applies to the next notification.
- **Restart needed:** no
- **Learn more:** [expiry-rules#critical](guides/expiry-rules.md#critical)

### Include names in email/Telegram (`notifications.include_names`)

Show folder, document and file names in external messages (long numbers are always masked). Turn off to send only counts and a sign-in link.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [expiry-rules#templates](guides/expiry-rules.md#templates)

## Section: connections

### Email (SMTP) enabled (`smtp.enabled`)

Send notification and password-reset email.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** smtp.host, smtp.from_address
- **Effect of changing:** When off, no email is sent and email channels show 'not configured'.
- **Restart needed:** no
- **Learn more:** [smtp#setup](guides/smtp.md#setup)

### SMTP host (`smtp.host`)

Mail server hostname.

- **Default:** `''`
- **Allowed values:** –200
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [smtp#setup](guides/smtp.md#setup)
- **Example:** smtp.example.com

### SMTP port (`smtp.port`)

Mail server port.

- **Default:** `587`
- **Allowed values:** 1–65535
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [smtp#setup](guides/smtp.md#setup)

### SMTP security (`smtp.security`)

Connection security.

- **Default:** `'starttls'`
- **Allowed values:** starttls, ssl, none
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [smtp#setup](guides/smtp.md#setup)

### SMTP username (`smtp.username`)

Login name for the mail server (optional).

- **Default:** `''`
- **Allowed values:** –200
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [smtp#setup](guides/smtp.md#setup)

### SMTP password (`smtp.password`)

Stored encrypted. Leave empty to keep the current value.

- **Default:** (secret, not shown)
- **Allowed values:** secret
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [smtp#setup](guides/smtp.md#setup)

### From address (`smtp.from_address`)

Sender address for outgoing email.

- **Default:** `''`
- **Allowed values:** email
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [smtp#setup](guides/smtp.md#setup)
- **Example:** documents@example.com

### Telegram enabled (`telegram.enabled`)

Send notifications through your Telegram bot.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** telegram.bot_token
- **Effect of changing:** When off, Telegram channels are unavailable.
- **Restart needed:** no
- **Learn more:** [telegram#setup](guides/telegram.md#setup)

### Telegram bot token (`telegram.bot_token`)

Token from @BotFather. Stored encrypted.

- **Default:** (secret, not shown)
- **Allowed values:** secret
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [telegram#setup](guides/telegram.md#setup)

### Telegram bot username (`telegram.bot_username`)

Used to build the link shown to users.

- **Default:** `''`
- **Allowed values:** –64
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [telegram#setup](guides/telegram.md#setup)
- **Example:** MyFamilyDocsBot

### WhatsApp (`whatsapp.status`)

Personal WhatsApp notifications are a later-phase feature.

- **Default:** `'planned'`
- **Allowed values:** planned
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Not available in this release.
- **Restart needed:** no
- **Learn more:** [settings#future](guides/settings.md#future)

## Section: authentication

### Session length (days) (`auth.session_days`)

How long a 'Remember me' sign-in lasts.

- **Default:** `14`
- **Allowed values:** 1–90
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Applies to new sign-ins.
- **Restart needed:** no
- **Learn more:** [totp-recovery#sessions](guides/totp-recovery.md#sessions)

### Password reset link lifetime (minutes) (`auth.reset_token_minutes`)

How long an emailed reset link remains valid.

- **Default:** `30`
- **Allowed values:** 5–1440
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [totp-recovery#reset](guides/totp-recovery.md#reset)

### Failed sign-ins before delay (`auth.login_rate_limit`)

Failed attempts per account/IP within 15 minutes before further attempts are refused.

- **Default:** `8`
- **Allowed values:** 3–100
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [totp-recovery#sessions](guides/totp-recovery.md#sessions)

### Allow authenticator apps (TOTP) (`auth.allow_totp`)

People may set up a standard authenticator app or password manager for one-time codes.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Turning it off only stops new set-ups; people who already use one keep it, so nobody is locked out.
- **Restart needed:** no
- **Learn more:** [totp-recovery#totp](guides/totp-recovery.md#totp)

### Allow passkeys (`auth.allow_passkeys`)

People may register passkeys (phone, computer, password manager or security key) as a second step after the password.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Turning it off only stops new registrations; existing passkeys keep working until removed.
- **Restart needed:** no
- **Learn more:** [passkeys#enable](guides/passkeys.md#enable)

### Allow passwordless passkey sign-in (`auth.allow_passwordless`)

People who turn it on for their own account can sign in with a passkey alone (the passkey verifies them with fingerprint, face or PIN).

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** auth.allow_passkeys
- **Effect of changing:** Turning it off stops passwordless sign-in immediately; everyone can still use their password.
- **Restart needed:** no
- **Learn more:** [passkeys#passwordless](guides/passkeys.md#passwordless)

### Require two-step verification (`auth.require_2fa`)

Who must use a second step (passkey or authenticator app). People without one are asked to set it up right after signing in.

- **Default:** `'none'`
- **Allowed values:** none, admins, all
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Nobody is locked out: they sign in with their password and are then guided to set up a passkey or authenticator app.
- **Restart needed:** no
- **Learn more:** [passkeys#policy](guides/passkeys.md#policy)

### Re-confirmation window (minutes) (`auth.recent_auth_minutes`)

How long after confirming it's you (password or passkey) sensitive changes are allowed: passkeys, authenticator app, recovery codes, passwordless.

- **Default:** `10`
- **Allowed values:** 2–60
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [passkeys#recent-auth](guides/passkeys.md#recent-auth)

### Google sign-in enabled (`google.enabled`)

Allow linked Google accounts to sign in. Disabled until client ID and secret are configured.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** google.client_id, google.client_secret
- **Effect of changing:** Disabling blocks new Google sign-ins immediately; existing sessions continue until they expire or are signed out.
- **Restart needed:** no
- **Learn more:** [google#enable](guides/google.md#enable)

### Google OAuth client ID (`google.client_id`)

Web application client ID from Google Cloud Console.

- **Default:** `''`
- **Allowed values:** –200
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [google#credentials](guides/google.md#credentials)

### Google OAuth client secret (`google.client_secret`)

Stored encrypted and never shown again.

- **Default:** (secret, not shown)
- **Allowed values:** secret
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [google#credentials](guides/google.md#credentials)

## Section: storage

### NAS connection (`nas.type`)

How the backup share is reached. 'Already mounted' means Proxmox (or you) mounted it into the container; NFS/SMB lets the app mount it.

- **Default:** `'none'`
- **Allowed values:** none, nfs, smb
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Click 'Connect NAS' after changing. The share is mounted at /mnt/pdnas and used as the backup destination.
- **Restart needed:** no
- **Learn more:** [backup-restore#nas](guides/backup-restore.md#nas)

### NAS server (`nas.server`)

Hostname or IP address of the NAS.

- **Default:** `''`
- **Allowed values:** –253
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#nas](guides/backup-restore.md#nas)
- **Example:** 192.168.1.20

### Share / export (`nas.share`)

NFS export path (e.g. /volume1/backups) or SMB share name (e.g. backups).

- **Default:** `''`
- **Allowed values:** –200
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#nas](guides/backup-restore.md#nas)
- **Example:** /volume1/backups

### Folder on the share (`nas.subfolder`)

Sub-folder used for this installation's backups (created if missing).

- **Default:** `'personaldocs'`
- **Allowed values:** –100
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#nas](guides/backup-restore.md#nas)

### SMB username (`nas.username`)

Account on the NAS (SMB only).

- **Default:** `''`
- **Allowed values:** –100
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#nas](guides/backup-restore.md#nas)

### SMB password (`nas.password`)

Stored encrypted; written to a root-only credentials file when mounting.

- **Default:** (secret, not shown)
- **Allowed values:** secret
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#nas](guides/backup-restore.md#nas)

### SMB domain/workgroup (`nas.domain`)

Optional (SMB only).

- **Default:** `''`
- **Allowed values:** –100
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#nas](guides/backup-restore.md#nas)

### Protocol version (`nas.version`)

NFS version (3, 4, 4.1) or SMB dialect (3.0, 2.1).

- **Default:** `''`
- **Allowed values:** –10
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#nas](guides/backup-restore.md#nas)
- **Example:** 4.1

### Backup destination (`backup.target`)

Mounted NAS/file-share path for backups.

- **Default:** `''`
- **Allowed values:** path
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Backups are refused when this path is not a mount point or lacks the marker file.
- **Restart needed:** no
- **Learn more:** [backup-restore#target](guides/backup-restore.md#target)
- **Example:** /mnt/nas-backup/personaldocs

### Require mounted destination (`backup.require_mount`)

Refuse to back up unless the destination is a mount point (prevents filling the local disk).

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#target](guides/backup-restore.md#target)

### Automatic backups (`backup.enabled`)

Run backups automatically on the schedule below. Back up now always works.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#schedule](guides/backup-restore.md#schedule)

### Backup frequency (`backup.frequency`)

Daily, weekly (choose the day) or monthly (choose the day of the month).

- **Default:** `'daily'`
- **Allowed values:** daily, weekly, monthly
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** backup.enabled
- **Effect of changing:** The next run is shown in Backup status.
- **Restart needed:** no
- **Learn more:** [backup-restore#schedule](guides/backup-restore.md#schedule)

### Backup time (`backup.schedule_time`)

Local time of the automatic backup (installation timezone).

- **Default:** `'02:30'`
- **Allowed values:** time
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** backup.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#schedule](guides/backup-restore.md#schedule)
- **Example:** 02:30

### Day of the week (`backup.weekday`)

Used when the frequency is weekly.

- **Default:** `'sun'`
- **Allowed values:** mon, tue, wed, thu, fri, sat, sun
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** backup.frequency
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#schedule](guides/backup-restore.md#schedule)

### Day of the month (`backup.month_day`)

Used when the frequency is monthly. 29–31 run on the last day of shorter months.

- **Default:** `1`
- **Allowed values:** 1–31
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** backup.frequency
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#schedule](guides/backup-restore.md#schedule)
- **Example:** 1

### Backups to keep (`backup.keep_daily`)

Number of most recent successful backups retained, whatever the frequency (proposed default, not a user decision).

- **Default:** `14`
- **Allowed values:** 1–365
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Older backups beyond this count are pruned; the newest verified backup is never pruned.
- **Restart needed:** no
- **Learn more:** [backup-restore#retention](guides/backup-restore.md#retention)

### Include encryption key in backup (`backup.include_keys`)

Include the integration-secret encryption key so restores can decrypt SMTP/Telegram/email credentials. Protect the backup share accordingly.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#keys](guides/backup-restore.md#keys)

## Section: activity

### Audit log retention (days) (`audit.retention_days`)

Audit events older than this are deleted. 0 keeps forever.

- **Default:** `730`
- **Allowed values:** 0–36500
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [settings#activity](guides/settings.md#activity)

## Section: security

### Login audit retention (days) (`security.login_audit_retention_days`)

Sign-in records older than this are deleted by the nightly maintenance. 0 keeps them forever.

- **Default:** `365`
- **Allowed values:** 0–3650
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Applies at the next nightly maintenance run.
- **Restart needed:** no
- **Learn more:** [security-access#login-audit](guides/security-access.md#login-audit)

### Failed sign-ins before automatic block (`security.escalation_failures`)

Failed sign-ins from one public address within an hour that add a temporary automatic block (0 disables). LAN addresses are never blocked.

- **Default:** `20`
- **Allowed values:** 0–1000
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#login-protection](guides/security-access.md#login-protection)

### Automatic block duration (minutes) (`security.escalation_minutes`)

How long an address stays blocked after too many failed sign-ins.

- **Default:** `60`
- **Allowed values:** 5–10080
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#login-protection](guides/security-access.md#login-protection)

### MaxMind account ID (`geoip.account_id`)

Free GeoLite2 account used to download the country database.

- **Default:** `''`
- **Allowed values:** –20
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#geoip](guides/security-access.md#geoip)
- **Example:** 123456

### MaxMind license key (`geoip.license_key`)

Stored encrypted and never shown again. Sent only to MaxMind when downloading.

- **Default:** (secret, not shown)
- **Allowed values:** secret
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#geoip](guides/security-access.md#geoip)

### GeoIP database edition (`geoip.edition`)

Country is enough for access control; City adds approximate cities to reports.

- **Default:** `'GeoLite2-Country'`
- **Allowed values:** GeoLite2-Country, GeoLite2-City
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#geoip](guides/security-access.md#geoip)

### Update GeoIP weekly (`geoip.auto_update`)

Download a fresh database every Wednesday night when credentials are set. A failed update keeps the current database.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** geoip.license_key
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#geoip](guides/security-access.md#geoip)

### Traffic analytics (GoAccess) (`goaccess.enabled`)

Build hourly traffic reports from the access log for Activity & health → Traffic analytics. Uses GoAccess when installed, otherwise a built-in summary.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Reports refresh hourly; nothing is exposed publicly.
- **Restart needed:** no
- **Learn more:** [security-access#goaccess](guides/security-access.md#goaccess)

### Alert: repeated failed sign-ins (`alerts.failed_logins`)

Notify administrators about repeated failures and automatic blocks.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#alerts](guides/security-access.md#alerts)

### Alert: sign-in from a new country (`alerts.new_country`)

Notify the person and administrators when an account signs in from a country it never used before.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#alerts](guides/security-access.md#alerts)

### Alert: sign-in from a new address (`alerts.new_ip`)

Notify the person and administrators about sign-ins from a new IP address (can be frequent on mobile networks).

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#alerts](guides/security-access.md#alerts)

### Alert: sign-in via temporary access (`alerts.policy_exception`)

Notify administrators when a sign-in was only possible because of a temporary travel exception.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#alerts](guides/security-access.md#alerts)

### Alert: access policy changes (`alerts.policy_changes`)

Notify administrators when the country policy, trusted/blocked IPs or temporary access change or expire.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#alerts](guides/security-access.md#alerts)

### Alert: GeoIP/GoAccess problems (`alerts.health`)

Notify administrators when a GeoIP update or traffic report fails.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#alerts](guides/security-access.md#alerts)

### Alert: account security changes (`alerts.account_security`)

Notify the person (and administrators for admin actions) about passkeys, authenticator app, recovery codes and passwordless sign-in changes.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-access#alerts](guides/security-access.md#alerts)

## Section: ai

### Local AI enabled (`ai.enabled`)

Master switch for all AI features. Off by default; uploads, OCR, search and reminders never depend on it.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Turning it off stops new AI jobs immediately; existing suggestions stay until reviewed.
- **Restart needed:** no
- **Learn more:** [local-ai#enable](guides/local-ai.md#enable)

### OCR assist (`ai.ocr_assist`)

After OCR, ask the AI to suggest title, dates and document number for review.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** ai.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [local-ai#ocr-assist](guides/local-ai.md#ocr-assist)

### Smart organisation (`ai.smart_organization`)

Suggest document type, issuer, tags and folder for review.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** ai.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [local-ai#smart-organization](guides/local-ai.md#smart-organization)

### Semantic search (`ai.semantic_search`)

Create embeddings of document text so searches can match meaning, not only words.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** ai.enabled
- **Effect of changing:** Use 'Rebuild semantic index' after enabling it.
- **Restart needed:** no
- **Learn more:** [local-ai#semantic-search](guides/local-ai.md#semantic-search)

### Document assistant (`ai.assistant`)

Answer questions using only documents the asking person may open.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** ai.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [local-ai#assistant](guides/local-ai.md#assistant)

### Who may use AI (`ai.allowed_users`)

Everyone (each person only on their own permitted documents) or administrators only.

- **Default:** `'everyone'`
- **Allowed values:** everyone, admins
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [local-ai#permissions](guides/local-ai.md#permissions)

### Analyse new uploads automatically (`ai.auto_analyze`)

Queue OCR assist / smart organisation / embeddings after each upload is processed.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** ai.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [local-ai#ocr-assist](guides/local-ai.md#ocr-assist)

### Parallel AI jobs (`ai.max_parallel`)

AI jobs running at the same time. Keep 1 on a 2-CPU container so documents are never delayed.

- **Default:** `1`
- **Allowed values:** 1–4
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [local-ai#resources](guides/local-ai.md#resources)

### AI diagnostic logging (`ai.debug_logging`)

Log request and response sizes (never their content) for troubleshooting.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [local-ai#troubleshooting](guides/local-ai.md#troubleshooting)

## Section: appearance

### Theme (`me.theme`)

Colour theme for your account on every device.

- **Default:** `'green'`
- **Allowed values:** green, blue, mono
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Applies immediately on all your devices.
- **Restart needed:** no
- **Learn more:** [themes#choose](guides/themes.md#choose)

### Default document layout (`me.layout`)

Three-panel browser or full-page viewer.

- **Default:** `'three_panel'`
- **Allowed values:** three_panel, full_page
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [themes#layout](guides/themes.md#layout)

### Folder view (`me.doc_view`)

How documents are shown in folders: list, thumbnails or details.

- **Default:** `'list'`
- **Allowed values:** list, thumbnails, details
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Applies on all your devices.
- **Restart needed:** no
- **Learn more:** [getting-started#views](guides/getting-started.md#views)

### Sort documents by (`me.doc_sort`)

Order of documents in folders.

- **Default:** `'-added'`
- **Allowed values:** -added, added, name, -name, size, -size, expiry, -expiry, type, -type
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Applies on all your devices.
- **Restart needed:** no
- **Learn more:** [getting-started#views](guides/getting-started.md#views)

## Section: my_notifications

### My notifications (`me.notification_prefs`)

Which optional notifications you receive, per channel.

- **Default:** `{}`
- **Allowed values:** event_matrix
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [expiry-rules#optional](guides/expiry-rules.md#optional)

### My notification channels (`me.channels`)

Channels you want reminders on. Required channels stay on.

- **Default:** `None`
- **Allowed values:** channel_list
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [expiry-rules#channels](guides/expiry-rules.md#channels)

### Other alerts by email/Telegram (`me.event_alerts`)

Also send access, import and (for administrators) backup and integrity alerts to your email/Telegram channels. They always appear in the in-app feed.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [expiry-rules#other-alerts](guides/expiry-rules.md#other-alerts)

## Section: appearance

### Dashboard widgets (`me.dashboard_widgets`)

Choose what your dashboard shows and in which order. Saved to your account, so every device shows the same.

- **Default:** `['documents', 'members', 'expiring', 'storage', 'review', 'family', 'saved_views', 'recent', 'upcoming', 'review_queue', 'backup']`
- **Allowed values:** documents, members, expiring, storage, review, family, saved_views, recent, upcoming, review_queue, backup
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Applies on all your devices.
- **Restart needed:** no
- **Learn more:** [getting-started#dashboard](guides/getting-started.md#dashboard)
