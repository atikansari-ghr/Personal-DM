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

### Text recognition (OCR) (`processing.ocr_enabled`)

Master switch for local OCR (PaddleOCR PP-OCRv5, or Tesseract Legacy). Which documents are recognised is decided per document type below.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** When off, nothing is recognised; documents are still stored, previewed and searchable by their details.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#selective](guides/ocr-corrections.md#selective)

### OCR engine (`processing.ocr_engine`)

PaddleOCR PP-OCRv5 is the default engine. Tesseract stays available as Legacy while results are compared. Changing the engine never re-processes existing documents.

- **Default:** `'paddleocr'`
- **Allowed values:** paddleocr, tesseract
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Applies to OCR runs requested from now on. Existing recognised text keeps its engine label.
- **Restart needed:** no
- **Learn more:** [ocr-engines#engine](guides/ocr-engines.md#engine)

### Use Tesseract when PaddleOCR is unavailable (`processing.ocr_engine_fallback`)

If PaddleOCR is not installed or fails its health check, run Tesseract instead and record that the fallback was used. Off: the OCR job fails with a clear message.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** processing.ocr_engine
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [ocr-engines#fallback](guides/ocr-engines.md#fallback)

### OCR language profiles offered (`processing.ocr_profiles`)

Language profiles people can choose when running OCR. Each profile routes to the matching PP-OCRv5 recognition models (and to the Tesseract language packs for Legacy runs).

- **Default:** `['en', 'ar_en', 'hi_en']`
- **Allowed values:** en, ar_en, hi_en, te_en, ta_en
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Run `sudo personaldocs ocr install-models` after adding a profile (the upgrade and repair do it too).
- **Restart needed:** no
- **Learn more:** [ocr-engines#profiles](guides/ocr-engines.md#profiles)

### Default language profile (`processing.ocr_default_profile`)

Used when the document type has no profile of its own.

- **Default:** `'en'`
- **Allowed values:** en, ar_en, hi_en, te_en, ta_en
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [ocr-engines#profiles](guides/ocr-engines.md#profiles)

### PP-OCRv5 model size (advanced) (`processing.paddle_model`)

Mobile models are fast and small enough for a 2 vCPU / 6 GB container. Server detection is more accurate on dense pages but slower and uses more memory.

- **Default:** `'mobile'`
- **Allowed values:** mobile, server
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Server detection needs its model downloaded (`sudo personaldocs ocr install-models`).
- **Restart needed:** no
- **Learn more:** [ocr-engines#advanced](guides/ocr-engines.md#advanced)

### PaddleOCR CPU threads (advanced) (`processing.paddle_cpu_threads`)

CPU threads one OCR job may use. Keep at or below the number of vCPUs minus one so the web app stays responsive.

- **Default:** `2`
- **Allowed values:** 1–16
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [ocr-engines#advanced](guides/ocr-engines.md#advanced)

### Detect page orientation (PaddleOCR) (`processing.paddle_orientation`)

Turn sideways or upside-down photos and scans the right way before recognition.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [ocr-engines#preprocessing](guides/ocr-engines.md#preprocessing)

### Detect text-line orientation (PaddleOCR) (`processing.paddle_textline`)

Turns individual upside-down lines. Off by default: in the benchmark it flipped every line of a Hindi + English card (20 % instead of 100 % accuracy). Turn on only for pages with mixed-direction lines.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [ocr-engines#preprocessing](guides/ocr-engines.md#preprocessing)

### Flatten curved photos (PaddleOCR) (`processing.paddle_unwarping`)

Straightens photographed pages that are bent or curved. Can make clean flat scans worse, so it is off by default; compare results in Test OCR before turning it on.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [ocr-engines#preprocessing](guides/ocr-engines.md#preprocessing)

### PaddleOCR memory limit (MB) (`processing.paddle_memory_mb`)

Hard limit for one OCR process. A job above it fails safely instead of slowing the whole server.

- **Default:** `3000`
- **Allowed values:** 1024–32768
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** About 1.5 GB is used by a two-language profile; 3000 leaves room for large pages.
- **Restart needed:** no
- **Learn more:** [ocr-engines#limits](guides/ocr-engines.md#limits)

### OCR languages offered (Tesseract Legacy) (`processing.ocr_languages`)

Tesseract language packs offered for Legacy OCR runs. The installer installs the matching packs; the health check reports missing ones.

- **Default:** `['eng', 'ara', 'hin']`
- **Allowed values:** eng, ara, hin, urd, tel, tam, mal, kan, ben, mar, guj, pan, fra, deu, spa, fas, tur
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Run `sudo personaldocs repair` after adding a language to install its pack.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#languages](guides/ocr-corrections.md#languages)

### OCR for documents without a type (`processing.ocr_untyped_mode`)

Disabled: never. Manual: only when someone runs OCR. Automatic: the primary file is recognised after upload.

- **Default:** `'manual'`
- **Allowed values:** disabled, manual, automatic
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Applies to new uploads and to the Run OCR button.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#selective](guides/ocr-corrections.md#selective)

### Local AI for documents without a type (`processing.ocr_untyped_ai_allowed`)

Allow Local AI to read the recognised text of documents without a type (when Local AI is on).

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Off: Local AI never receives their text.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#ai](guides/ocr-corrections.md#ai)

### Pause OCR queue (`processing.ocr_paused`)

Queued OCR jobs wait until the queue is resumed. Uploads, previews and search keep working.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Resuming continues the waiting jobs in order.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#limits](guides/ocr-corrections.md#limits)

### Maximum file size for OCR (MB) (`processing.ocr_max_file_mb`)

Files above this size are stored and previewed but cannot be sent to OCR.

- **Default:** `50`
- **Allowed values:** 1–2000
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#limits](guides/ocr-corrections.md#limits)

### Maximum queued OCR jobs (`processing.ocr_queue_max`)

New OCR requests are refused with a clear message while this many are waiting.

- **Default:** `50`
- **Allowed values:** 1–10000
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#limits](guides/ocr-corrections.md#limits)

### OCR retries (`processing.ocr_max_attempts`)

How many times a failed OCR job is attempted before it is marked Failed.

- **Default:** `2`
- **Allowed values:** 1–10
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [ocr-corrections#limits](guides/ocr-corrections.md#limits)

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

### Maximum pages per OCR job (`processing.max_pages`)

OCR requests covering more pages than this are refused (choose a page range instead).

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

- **Default:** `['security.password_reset_requested', 'security.password_admin_reset', 'security.temporary_password', 'security.password_changed', 'security.account_locked', 'security.passkey_added', 'security.passkey_removed', 'security.totp_enabled', 'security.totp_disabled', 'security.recovery_codes', 'security.passwordless', 'security.admin_recovery', 'security.new_country', 'security.risky_signin', 'security.device_unrecognized', 'security.failed_logins', 'security.authentik', 'security.google', 'security.policy_exception', 'security.policy_change', 'security.auth_policy', 'antivirus.threat', 'antivirus.released', 'antivirus.unavailable', 'antivirus.definitions', 'security.operations', 'backup.failed', 'backup.partial', 'backup.verification', 'backup.destination', 'backup.pre_change_blocked', 'backup.config_changed', 'backup.deleted', 'backup.downloaded', 'recovery.key_revealed', 'recovery.key_rotated', 'recovery.emergency', 'recovery.full', 'recovery.compromise', 'whatsapp.relink_required', 'whatsapp.incompatible', 'integrity.failed']`
- **Allowed values:** security.password_reset_requested, security.password_admin_reset, security.temporary_password, security.password_changed, security.account_locked, security.passkey_added, security.passkey_removed, security.totp_enabled, security.totp_disabled, security.recovery_codes, security.passwordless, security.admin_recovery, security.new_country, security.new_ip, security.risky_signin, security.device_unrecognized, account.login, security.failed_logins, security.authentik, security.google, security.policy_exception, security.policy_change, security.auth_policy, security.health, antivirus.threat, antivirus.released, antivirus.unavailable, antivirus.definitions, security.operations, backup.failed, backup.succeeded, backup.partial, backup.verification, backup.destination, backup.retention, backup.pre_change, backup.pre_change_blocked, backup.config_changed, backup.deleted, backup.downloaded, recovery.key_revealed, recovery.key_rotated, recovery.emergency, recovery.restore, recovery.full, recovery.compromise, recovery.validation, whatsapp.relink_required, whatsapp.incompatible, integrity.failed, expiry.reminder, document.added, document.archived, document.shared, document.changed, import.finished, processing.completed, processing.failed
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

### Notification Detail Level (`notifications.detail_level`)

Full Details: notifications show complete names, document numbers and IP addresses on every channel, but only what the recipient may already see. Minimal Details: a short summary and a link to the app. Each person can choose their own level; passwords, keys and codes are never sent.

- **Default:** `'full'`
- **Allowed values:** full, minimal
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Applies to the next notification.
- **Restart needed:** no
- **Learn more:** [notifications#detail-level](guides/notifications.md#detail-level)

## Section: notifications_hidden

### Include names in email/Telegram (replaced) (`notifications.include_names`)

Replaced by Notification Detail Level (Change Set W). Kept so a rollback keeps its value.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [notifications#detail-level](guides/notifications.md#detail-level)

### Include document numbers in email/Telegram (replaced) (`notifications.include_document_number`)

Replaced by Notification Detail Level (Change Set W). Kept so a rollback keeps its value.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [notifications#detail-level](guides/notifications.md#detail-level)

## Section: notifications

### Push notifications (PWA) (`notifications.push_enabled`)

Let people receive notifications on their phone or computer through the installed app (Web Push). Needs the HTTPS address; only known push services (Apple, Google, Mozilla, Microsoft) are contacted.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** When off, push is not offered and nothing is sent.
- **Restart needed:** no
- **Learn more:** [notifications#push](guides/notifications.md#push)

### Repeat cooldown for recurring conditions (`notifications.repeat_cooldown_hours`)

A recurring condition (antivirus unavailable, storage nearly full, update failures …) is notified again only after this many hours. New critical events (malware found, failed backups) are always sent at once.

- **Default:** `24`
- **Allowed values:** 1–168
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [notifications#noise](guides/notifications.md#noise)

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

### Discord webhooks (`discord.enabled`)

Let people send their own notifications to a Discord channel through an official Discord webhook they add in My account → Notifications. Each webhook is stored encrypted.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** When off, Discord delivery stops for everyone; saved webhooks are kept.
- **Restart needed:** no
- **Learn more:** [discord#setup](guides/discord.md#setup)

### WhatsApp Personal (experimental, unofficial) (`whatsapp.enabled`)

Optional self-hosted bridge that links each person's own WhatsApp account as a linked device and sends them their Personal DM notifications. It is not the WhatsApp Business Platform and is not supported or endorsed by WhatsApp or Meta; WhatsApp may disconnect linked devices at any time.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Install the bridge first (sudo personaldocs whatsapp-bridge install). Off by default; never enabled automatically.
- **Restart needed:** no
- **Learn more:** [whatsapp-personal#enable](guides/whatsapp-personal.md#enable)

### WhatsApp bridge address (`whatsapp.bridge_url`)

Local address of the personaldocs-whatsapp service. Only loopback addresses are accepted.

- **Default:** `'http://127.0.0.1:8095'`
- **Allowed values:** –100
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** whatsapp.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [whatsapp-personal#bridge](guides/whatsapp-personal.md#bridge)

## Section: notifications

### Fall back after failed attempts (`notifications.fallback_after_attempts`)

When a person set a fallback chain (for example WhatsApp → Telegram → Email), the next channel is tried after this many failed delivery attempts. A disconnected channel falls back at once.

- **Default:** `2`
- **Allowed values:** 1–5
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [notifications#fallback](guides/notifications.md#fallback)

## Section: connections

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

### Passkey sign-in mode (`auth.passkey_mode`)

Passwordless: the sign-in page offers Sign in with Passkey before any password, and a passkey (verified with fingerprint, face or PIN) signs the person in on its own. Password + Passkey: passkeys are only used as the second step after the password.

- **Default:** `'passwordless'`
- **Allowed values:** passwordless, mfa
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** auth.allow_passkeys
- **Effect of changing:** Switching to Password + Passkey stops passwordless sign-in immediately; everyone can still use their password. The main administrator's password and recovery codes always keep working.
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

## Section: nas_hidden

### NAS connection (`nas.type`)

Connection of the NAS backup destination (edited in Backup & Recovery → Destinations). 'Already mounted' means Proxmox (or you) mounted it into the container; NFS/SMB lets the app mount it.

- **Default:** `'none'`
- **Allowed values:** none, nfs, smb
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Edited in Backup & Recovery → Destinations; Test Connection mounts the share at /mnt/pdnas.
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

## Section: backup_hidden

### Destination space warning (`backup.space_warning_pct`)

Warn the main administrator when a backup destination has less free space than this (percent of its size). A destination may override it.

- **Default:** `20`
- **Allowed values:** 1–90
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#capacity](guides/backup-restore.md#capacity)
- **Example:** 20

### Destination space critical (`backup.space_critical_pct`)

Critical alert below this much free space (percent). Valid backups are never deleted to make room.

- **Default:** `10`
- **Allowed values:** 1–90
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#capacity](guides/backup-restore.md#capacity)
- **Example:** 10

## Section: storage

### Legacy backup folder (`backup.target`)

Folder of backups made before encrypted recovery points (format 1). New backups use Backup & Recovery destinations; this value was migrated into a destination.

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

### Legacy backups to keep (`backup.keep_daily`)

Only for the old folder backups (format 1). Encrypted recovery points use the policy retention (default 4 weeks).

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

### Recovery validation database (`recovery.validation_database`)

PostgreSQL URL of a SEPARATE, isolated database used only for Automated Recovery Validation (postgresql://user:password@host:5432/dbname). Stored encrypted. Leave empty to keep validation off.

- **Default:** (secret, not shown)
- **Allowed values:** secret
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#validation](guides/backup-restore.md#validation)
- **Example:** postgresql://pdvalidate:…@192.0.2.20/pd_validation

### Recovery validation folder (`recovery.validation_dir`)

Empty folder for the restored files during validation (must not be the production data folder).

- **Default:** `''`
- **Allowed values:** path
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [backup-restore#validation](guides/backup-restore.md#validation)
- **Example:** /srv/pd-validation

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

### Sign-in map (`security.map_enabled`)

Show sign-ins on a map (Trusted Zone pins and approximate GeoIP positions). Uses online map tiles; sign-in addresses are never sent to the tile server or a geolocation service.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-map#map](guides/security-map.md#map)

### Map provider (`security.map_provider`)

Where the sign-in map comes from. OpenFreeMap (default) draws the map in the browser with ENGLISH place names and needs no key. OpenStreetMap standard tiles show local-language names and are for low-volume use only; MapTiler and Stadia Maps need your own API key; Custom uses the tile server below.

- **Default:** `'openfreemap'`
- **Allowed values:** openfreemap, osm, maptiler, stadia, custom
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** security.map_enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-map#provider](guides/security-map.md#provider)

### Map provider API key (`security.map_api_key`)

Key for MapTiler or Stadia Maps. Stored encrypted; restrict it to this site's address at the provider (the browser loads the tiles, so a map key is visible to signed-in people).

- **Default:** (secret, not shown)
- **Allowed values:** secret
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** security.map_enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-map#provider](guides/security-map.md#provider)

### Custom tile server (`security.map_tile_url`)

Used when the map provider is Custom: address template of a tile server you may use (https, with {z}/{x}/{y}). The browser requests ordinary picture tiles from it.

- **Default:** `'https://tile.openstreetmap.org/{z}/{x}/{y}.png'`
- **Allowed values:** –300
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** security.map_enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-map#tiles](guides/security-map.md#tiles)
- **Example:** https://tile.openstreetmap.org/{z}/{x}/{y}.png

### Custom map attribution (`security.map_attribution`)

Credit line required by your custom tile server (the presets show their own).

- **Default:** `'© OpenStreetMap contributors'`
- **Allowed values:** –200
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** security.map_enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-map#tiles](guides/security-map.md#tiles)

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

## Section: overview

### Holiday countries (`overview.holiday_countries`)

Countries whose public holidays appear in the calendar and the Upcoming holidays widget. Holiday dates come from the bundled holidays library; Islamic dates are calculated and shown as provisional until you confirm them below.

- **Default:** `['SA', 'IN']`
- **Allowed values:** country_list
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Applies to everyone's Overview immediately.
- **Restart needed:** no
- **Learn more:** [overview#holidays](guides/overview.md#holidays)
- **Example:** SA, IN

### Hijri date adjustment (days) (`overview.hijri_adjust`)

The Hijri date follows the Umm al-Qura calendar. If the local moon sighting differs, shift it by up to two days.

- **Default:** `0`
- **Allowed values:** -2–2
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [overview#hijri](guides/overview.md#hijri)

### Weather widget (`weather.enabled`)

Fetch the weather for the city each person chooses. The provider only receives the city coordinates, never documents or names. Off by default.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [overview#weather](guides/overview.md#weather)

### Weather provider (`weather.provider`)

Service used for forecasts and city search.

- **Default:** `'open_meteo'`
- **Allowed values:** open_meteo
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** weather.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [overview#weather](guides/overview.md#weather)

### Forecast address (`weather.base_url`)

Forecast API address. Change it only for a commercial plan or a self-hosted mirror.

- **Default:** `'https://api.open-meteo.com/v1/forecast'`
- **Allowed values:** –300
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** weather.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [overview#weather](guides/overview.md#weather)

### City search address (`weather.geocoding_url`)

Geocoding API used when someone searches for a city.

- **Default:** `'https://geocoding-api.open-meteo.com/v1/search'`
- **Allowed values:** –300
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** weather.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [overview#weather](guides/overview.md#weather)

### Weather API key (`weather.api_key`)

Only needed for a commercial plan. Stored encrypted and never shown again.

- **Default:** (secret, not shown)
- **Allowed values:** secret
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** weather.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [overview#weather](guides/overview.md#weather)

### Weather cache (minutes) (`weather.cache_minutes`)

How long a forecast is reused before the provider is asked again.

- **Default:** `30`
- **Allowed values:** 10–360
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** weather.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [overview#weather](guides/overview.md#weather)

### Temperature units (`weather.units`)

Units for every account.

- **Default:** `'celsius'`
- **Allowed values:** celsius, fahrenheit
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** weather.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [overview#weather](guides/overview.md#weather)

## Section: overview_hidden

### Default city (`weather.default_city`)

City shown to people who have not chosen their own.

- **Default:** `None`
- **Allowed values:** json
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** weather.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [overview#weather](guides/overview.md#weather)

## Section: login

### Sign-in page design (`login.design`)

Wallpaper on the left of the sign-in page. Sign-in works the same with every design.

- **Default:** `'minimal'`
- **Allowed values:** minimal, nature, travel, family, neutral, custom
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [login-designs#presets](guides/login-designs.md#presets)

## Section: login_hidden

### Active sign-in design (`login.active_design`)

Id of the active named design (Change Set W).

- **Default:** `None`
- **Allowed values:** json
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [login-designs#designs](guides/login-designs.md#designs)

### Previous sign-in design (`login.previous_design`)

Id of the design before the last change (Revert).

- **Default:** `None`
- **Allowed values:** json
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [login-designs#activate](guides/login-designs.md#activate)

### Sign-in design rotation (`login.rotation`)

{enabled, mode: sequential|random, pool: [design ids], frequency: daily|weekly|monthly, time, weekday, month_day}.

- **Default:** `{'enabled': False, 'mode': 'sequential', 'pool': [], 'frequency': 'weekly', 'time': '06:00', 'weekday': 'mon', 'month_day': 1}`
- **Allowed values:** json
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [login-designs#rotation](guides/login-designs.md#rotation)

## Section: login

### Sign-in title (`login.title`)

Heading on the sign-in page.

- **Default:** `'Personal Documents Management System'`
- **Allowed values:** –80
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [login-designs#branding](guides/login-designs.md#branding)

### Tagline (`login.tagline`)

Short line under the title. Leave empty to hide it.

- **Default:** `'Your family documents, safely in one place.'`
- **Allowed values:** –120
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [login-designs#branding](guides/login-designs.md#branding)

### Wallpaper overlay (%) (`login.overlay`)

Lightens the wallpaper so text stays readable.

- **Default:** `0`
- **Allowed values:** 0–80
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [login-designs#wallpaper](guides/login-designs.md#wallpaper)

### Wallpaper position (`login.position`)

Which part of a custom wallpaper stays visible when it is cropped.

- **Default:** `'center'`
- **Allowed values:** center, top, bottom, left, right
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [login-designs#wallpaper](guides/login-designs.md#wallpaper)

## Section: login_hidden

### Custom wallpaper file (`login.wallpaper_file`)

Set by uploading a wallpaper.

- **Default:** `''`
- **Allowed values:** –80
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [login-designs#wallpaper](guides/login-designs.md#wallpaper)

### Logo file (`login.logo_file`)

Set by uploading a logo.

- **Default:** `''`
- **Allowed values:** –80
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [login-designs#branding](guides/login-designs.md#branding)

## Section: antivirus

### Antivirus scanning (ClamAV) (`antivirus.enabled`)

Scan every new file in the background with the local ClamAV daemon. Files stay usable while they are scanned; a detected threat is quarantined.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [antivirus#overview](guides/antivirus.md#overview)

### ClamAV socket (`antivirus.socket`)

Local Unix socket of clamd. ClamAV is never contacted over the network.

- **Default:** `'/run/clamav/clamd.ctl'`
- **Allowed values:** path
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** antivirus.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [antivirus#install](guides/antivirus.md#install)
- **Example:** /run/clamav/clamd.ctl

### Maximum scan size (MB) (`antivirus.max_scan_mb`)

Larger files are stored normally but marked Not scanned — size limit exceeded. Above 200 MB a scan can use a lot of memory on a 4 GB server.

- **Default:** `50`
- **Allowed values:** 1–1024
- **Scope:** global · **Editable by:** each user
- **Depends on:** antivirus.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [antivirus#size](guides/antivirus.md#size)

### Re-scan the whole library (`antivirus.scan_frequency`)

Scheduled re-scan of every stored file with the newest signatures.

- **Default:** `'disabled'`
- **Allowed values:** disabled, daily, weekly, monthly
- **Scope:** global · **Editable by:** each user
- **Depends on:** antivirus.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [antivirus#schedule](guides/antivirus.md#schedule)

### Re-scan time (`antivirus.scan_time`)

Local time (installation timezone) when a scheduled re-scan starts.

- **Default:** `'02:30'`
- **Allowed values:** time
- **Scope:** global · **Editable by:** each user
- **Depends on:** antivirus.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [antivirus#schedule](guides/antivirus.md#schedule)

### Re-scan day of week (`antivirus.scan_weekday`)

Used by the weekly schedule.

- **Default:** `'sun'`
- **Allowed values:** mon, tue, wed, thu, fri, sat, sun
- **Scope:** global · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [antivirus#schedule](guides/antivirus.md#schedule)

### Re-scan day of month (`antivirus.scan_month_day`)

Used by the monthly schedule; 29–31 run on the last day of shorter months.

- **Default:** `1`
- **Allowed values:** 1–31
- **Scope:** global · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [antivirus#schedule](guides/antivirus.md#schedule)

### Definitions out of date after (days) (`antivirus.stale_days`)

Signatures older than this show a warning and alert administrators.

- **Default:** `2`
- **Allowed values:** 1–30
- **Scope:** global · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [antivirus#signatures](guides/antivirus.md#signatures)

### Definitions critically stale after (days) (`antivirus.critical_stale_days`)

Signatures older than this put Security Health at risk.

- **Default:** `7`
- **Allowed values:** 2–90
- **Scope:** global · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [antivirus#signatures](guides/antivirus.md#signatures)

## Section: identity

### Sign in with authentik (`authentik.enabled`)

Offer sign-in through your authentik server (OpenID Connect). Local sign-in always stays available.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#setup](guides/authentik.md#setup)

### Issuer / discovery URL (`authentik.issuer`)

The provider's issuer URL; /.well-known/openid-configuration is read from it.

- **Default:** `''`
- **Allowed values:** –300
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** authentik.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#setup](guides/authentik.md#setup)
- **Example:** https://auth.example.com/application/o/personal-dm/

### Client ID (`authentik.client_id`)

From the authentik OAuth2/OpenID provider.

- **Default:** `''`
- **Allowed values:** –200
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** authentik.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#setup](guides/authentik.md#setup)

### Client secret (`authentik.client_secret`)

Stored encrypted and never shown again.

- **Default:** (secret, not shown)
- **Allowed values:** secret
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** authentik.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#setup](guides/authentik.md#setup)

### Scopes (`authentik.scopes`)

Requested scopes; openid is always included.

- **Default:** `'openid profile email'`
- **Allowed values:** –200
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** authentik.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#setup](guides/authentik.md#setup)

### Button label (`authentik.button_label`)

Text of the sign-in button.

- **Default:** `'Sign in with authentik'`
- **Allowed values:** –60
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** authentik.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#button](guides/authentik.md#button)

### Show authentik logo (`authentik.show_logo`)

Show the authentik mark on the sign-in button.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** authentik.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#button](guides/authentik.md#button)

### Account provisioning (`authentik.provisioning`)

Existing accounts only: people link authentik from their own account first. Automatic: unknown authentik users get a new member account (never the main administrator).

- **Default:** `'existing_only'`
- **Allowed values:** existing_only, auto
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** authentik.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#provisioning](guides/authentik.md#provisioning)

### Username claim (`authentik.username_claim`)

Claim used as the username of automatically created accounts.

- **Default:** `'preferred_username'`
- **Allowed values:** –60
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#claims](guides/authentik.md#claims)

### Display name claim (`authentik.name_claim`)

Claim used as the display name of new accounts.

- **Default:** `'name'`
- **Allowed values:** –60
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#claims](guides/authentik.md#claims)

### Email claim (`authentik.email_claim`)

Shown on the link; never used to link accounts automatically.

- **Default:** `'email'`
- **Allowed values:** –60
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#claims](guides/authentik.md#claims)

### Groups claim (`authentik.groups_claim`)

Claim that lists the person's authentik groups.

- **Default:** `'groups'`
- **Allowed values:** –60
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#groups](guides/authentik.md#groups)

### Map authentik groups to roles (`authentik.group_mapping_enabled`)

Off by default. Groups only set the Member/Administrator role; document and folder access never comes from groups.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** authentik.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#groups](guides/authentik.md#groups)

## Section: identity_hidden

### Group-to-role mapping (`authentik.group_mapping`)

authentik group name → Member or Administrator.

- **Default:** `{}`
- **Allowed values:** json
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [authentik#groups](guides/authentik.md#groups)
- **Example:** {"pdm-admins": "administrator"}

## Section: security_center

### Deployment exposure (`security.deployment`)

Internet-facing deployments must pass the HTTPS checks to be reported as Internet Ready.

- **Default:** `'lan'`
- **Allowed values:** lan, internet
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-center#internet-ready](guides/security-center.md#internet-ready)

### Security record retention (days) (`security.log_retention_days`)

Antivirus events, security tests, OS update runs, authentik and security alerts are kept at least one year.

- **Default:** `365`
- **Allowed values:** 365–3650
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-center#retention](guides/security-center.md#retention)

### Storage warning at (% used) (`storage.warn_percent`)

Show a warning and notify administrators.

- **Default:** `80`
- **Allowed values:** 50–99
- **Scope:** global · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-center#storage](guides/security-center.md#storage)

### Storage critical at (% used) (`storage.critical_percent`)

Critical storage alert.

- **Default:** `90`
- **Allowed values:** 51–100
- **Scope:** global · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [security-center#storage](guides/security-center.md#storage)

## Section: offline

### Offline copies (`offline.enabled`)

Allow people to keep chosen folders and documents on their own devices for use without a connection. Turning it off removes offline copies at each device's next sync.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Devices remove their offline copies at the next sync.
- **Restart needed:** no
- **Learn more:** [offline-export#admin](guides/offline-export.md#admin)

### Update offline copies automatically (`offline.auto_update`)

When a newer version of an offline document exists, devices download it at the next sync. Off: the copy is marked 'Update available' until the person updates it.

- **Default:** `True`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** offline.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [offline-export#updates](guides/offline-export.md#updates)

### Keep recognised text offline (`offline.cache_text`)

Also store recognised (OCR) and extracted text on devices, so offline copies can show their text. Off by default for privacy. When OCR is removed from a document, its offline text is removed at the next sync.

- **Default:** `False`
- **Allowed values:** bool
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** offline.enabled
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [offline-export#text](guides/offline-export.md#text)

### On sign-out (`offline.logout_policy`)

What happens to a person's offline copies on a device when they sign out.

- **Default:** `'user_choice'`
- **Allowed values:** user_choice, always_clear
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [offline-export#signout](guides/offline-export.md#signout)

### Lock offline copies after (days without sync) (`offline.max_days_without_sync`)

Offline copies stay readable without a connection for this many days after the last successful sync, then are locked until the device connects and signs in again. 0 = never lock.

- **Default:** `30`
- **Allowed values:** 0–365
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [offline-export#signout](guides/offline-export.md#signout)

### Suggested space per device (MB) (`offline.device_quota_mb`)

People are warned before an offline selection would use more than this on one device. Browsers also enforce their own limit.

- **Default:** `2048`
- **Allowed values:** 100–200000
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [offline-export#quota](guides/offline-export.md#quota)

### Large download warning (MB) (`offline.large_download_mb`)

Ask for confirmation before making a folder available offline when it is larger than this.

- **Default:** `500`
- **Allowed values:** 10–100000
- **Scope:** global · **Editable by:** main administrator
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [offline-export#quota](guides/offline-export.md#quota)

## Section: appearance

### Theme (`me.theme`)

Colour theme for your account on every device.

- **Default:** `'green'`
- **Allowed values:** green, blue, dark, glass_light, glass_dark, mono
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

### Notification detail (`me.notification_detail`)

How much your notifications show. Full Details: complete names, document numbers and IP addresses you may already see. Minimal Details: a short summary and a link to the app. Use system default follows the administrator's setting.

- **Default:** `'system'`
- **Allowed values:** system, full, minimal
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [notifications#detail-level](guides/notifications.md#detail-level)

### Push notification detail (`me.push_preview`)

What your phone or computer may show on the lock screen. Minimal: only that something needs attention. Standard: the alert title and a short summary without names. Detailed: also document names. Document numbers and text are never shown.

- **Default:** `'standard'`
- **Allowed values:** minimal, standard, detailed
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [notifications#push](guides/notifications.md#push)

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

### Overview widgets (`me.dashboard_widgets`)

Choose what your Overview shows and in which order. Saved to your account, so every device shows the same. Use Customize Overview for sizes and styles.

- **Default:** `['date', 'weather', 'summary', 'calendar', 'holidays', 'upcoming', 'shared', 'recent', 'activity', 'review_queue', 'backup', 'my_recovery', 'security']`
- **Allowed values:** documents, members, expiring, storage, review, family, saved_views, recent, upcoming, review_queue, backup, my_recovery, date, weather, summary, calendar, holidays, shared, activity, security
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Applies on all your devices.
- **Restart needed:** no
- **Learn more:** [overview#customize](guides/overview.md#customize)

## Section: appearance_hidden

### Overview layout (`me.overview_layout`)

Size, style and options of each Overview widget.

- **Default:** `{}`
- **Allowed values:** overview_layout
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [overview#customize](guides/overview.md#customize)

### Weather city (`me.weather_city`)

City for your weather widget.

- **Default:** `None`
- **Allowed values:** json
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [overview#weather](guides/overview.md#weather)

## Section: my_notifications_hidden

### Notification routing (`me.notification_routing`)

Per category: fallback chain (first available channel wins) and delivery (immediately, daily or weekly digest).

- **Default:** `{}`
- **Allowed values:** json
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [notifications#routing](guides/notifications.md#routing)

### Quiet hours (`me.quiet_hours`)

Hold normal notifications on external channels during these hours. Critical security and backup alerts are never held.

- **Default:** `{'enabled': False, 'start': '22:00', 'end': '07:00'}`
- **Allowed values:** json
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [notifications#quiet-hours](guides/notifications.md#quiet-hours)

### My timezone (`me.timezone`)

Used for quiet hours and digests. Empty = the installation timezone.

- **Default:** `''`
- **Allowed values:** –60
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [notifications#quiet-hours](guides/notifications.md#quiet-hours)
- **Example:** Europe/Berlin

### Digest time (`me.digest_time`)

Local time when daily and weekly digests are sent (weekly: Mondays).

- **Default:** `'08:00'`
- **Allowed values:** time
- **Scope:** user · **Editable by:** each user
- **Depends on:** nothing
- **Effect of changing:** Takes effect immediately.
- **Restart needed:** no
- **Learn more:** [notifications#digests](guides/notifications.md#digests)
