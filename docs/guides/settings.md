# Settings overview

Every setting shows a description, default, allowed values, who can change it, and what changing it does. The full generated list is in `docs/SETTINGS_REFERENCE.md`.

## General {#general}

Application name, installation timezone (used for reminders), date display format, and the installation identity used in backup names.

## Family & access {#family}

Members (add, deactivate; documents are never deleted), groups and heads, delegation. Folder permissions are managed on each folder (**Who has access**). See [Extended family](extended-family.md).

## Documents & folders {#documents}

Stored filename template, upload size limit, blocked extensions, emoji suggestions, approved server import folders, document types, tags, issuers and custom fields.

## OCR & processing {#processing}

OCR on/off, the OCR policy per document type (Disabled, Manual, Automatic; languages, expected fields, AI permission), untyped documents, OCR languages offered, concurrency, timeouts, size, page, queue and attempt limits, **Pause OCR queue**, and the processing queue with retry. See [selective OCR](ocr-corrections.md#selective).

## Overview & sign-in {#overview}

Administrators only: holiday countries and corrections, Hijri date adjustment, the weather provider (off by default), and the sign-in page design, wallpaper, title, tagline and logo. See [Overview](overview.md) and [sign-in page designs](login-designs.md).

## Notifications and connections {#notifications}

Reminder days and time, recipients, default and required channels for reminders, **critical notifications** and their channels, names in external messages, delivery problems, message preview, delivery history; SMTP and Telegram setup with tests; WhatsApp status (planned). Each person chooses optional notifications per event and channel under My account → Notifications. See [notifications](expiry-rules.md#critical).

## Authentication {#authentication}

Session length, reset-link lifetime, sign-in rate limit, Google sign-in with diagnostics.

## Storage & backup {#storage}

Backup destination, schedule (daily, weekly or monthly; see [schedule](backup-restore.md#schedule)), retention, keys, *Back up now*, next run and last result, integrity check.

## Activity & health {#activity}

Service and tool health, disk space, failed jobs, the audit log with filters, and audit retention (default 730 days; 0 keeps forever). The audit log is not tamper-proof against someone with root access to the server.

## Secrets {#secrets}

Passwords and tokens are stored encrypted and never displayed again. Leave a secret field empty to keep the stored value; use *Clear stored value* to remove it.

## Future features {#future}

**WhatsApp** notifications are planned; no provider is integrated yet. Local AI, which used to be listed here, is now available:
see [Local AI](local-ai.md).

## Security & access {#security}

Login audit retention, failed-sign-in protection, GeoIP (MaxMind) credentials, traffic analytics and security alerts, plus the
country/IP access policy. See [Security & access](security-access.md).

## Local AI {#local-ai}

AI server profiles and feature switches (OCR assist, smart organisation, semantic search, document assistant). See [Local AI](local-ai.md).
