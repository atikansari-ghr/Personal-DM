# Settings overview

Every setting shows a description, default, allowed values, who can change it, and what changing it does. The full generated list is in `docs/SETTINGS_REFERENCE.md`.

## General {#general}

Application name, installation timezone (used for reminders), date display format, and the installation identity used in backup names.

## Family & access {#family}

Members, groups and heads, delegation. Folder permissions are managed on each folder (**Who has access**). See [Extended family](extended-family.md).

## Documents & folders {#documents}

Stored filename template, upload size limit, blocked extensions, emoji suggestions, approved server import folders, document types, tags, issuers and custom fields.

## OCR & processing {#processing}

OCR on/off, language, concurrency, timeouts and size limits, and the processing queue with retry.

## Notifications and connections {#notifications}

Reminder days and time, recipients, default and required channels, message preview, delivery history; SMTP and Telegram setup with tests; WhatsApp status (planned).

## Authentication {#authentication}

Session length, reset-link lifetime, sign-in rate limit, Google sign-in with diagnostics.

## Storage & backup {#storage}

Backup destination, schedule, retention, keys, *Back up now*, integrity check.

## Activity & health {#activity}

Service and tool health, disk space, failed jobs, the audit log with filters, and audit retention (default 730 days; 0 keeps forever). The audit log is not tamper-proof against someone with root access to the server.

## Secrets {#secrets}

Passwords and tokens are stored encrypted and never displayed again. Leave a secret field empty to keep the stored value; use *Clear stored value* to remove it.

## Future features {#future}

**Local AI** (model-assisted OCR, classification suggestions, chat with documents, semantic similarity) is planned for a later release. It will be disabled by default, use only a server you choose (on the same LXC or another local machine), never fall back to cloud services, respect document permissions and treat document text as untrusted input. A curated model list with hardware needs and measured accuracy will be provided then. **WhatsApp** notifications are also planned; no provider is integrated yet.
