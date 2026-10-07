# Expiry reminders

## Schedule {#schedule}

The main administrator sets one schedule in **Settings → Notifications** (default **90, 60, 30, 7 days before, and on the expiry day**) and the time of day reminders are sent (default 08:00). Example: *90* means a reminder 90 days before expiry.

Rules:

- Only **confirmed** expiry dates count; suggestions from OCR never trigger reminders.
- Each threshold is sent once per document and expiry date.
- Reminders stop after the expiry day. Expired documents stay labelled *Expired* until renewed or archived — they are never deleted automatically.
- If the server was down or a document is added close to its expiry, only the most relevant reminder is sent (for example a document imported 20 days before expiry gets the 30-day reminder once, not 90/60/30 together).
- Changing or correcting an expiry date starts a fresh schedule and cancels pending messages for the old date.
- Renewed (superseded) and archived documents get no reminders.
- Changing the reminder days applies from the next run; reminders already sent are not repeated.
- Retries and restarts never send duplicates.

## Document types and the expiry field {#types}

- The expiry date of a document is the **confirmed** value of the field with the **expiry role** in its document
  type's template (for example *Expiry date* for a Passport, *End date* for Insurance). Unconfirmed OCR or Local AI
  suggestions never set it.
- A type can have its own **reminder days** (Settings → Documents & folders → Document types → edit the type), for
  example 180, 90 and 30 for passports. An empty list uses the global schedule above.
- A confirmed value of a field with the *No expiry* role ("Does not expire") keeps the document out of expiry lists.
- Changing a document's type works the expiry date out again. If the new type has no expiry field, or the old value
  waits under *Previous details*, reminders for that document stop until the value is mapped. Pending reminders for
  the old date are cancelled; no date is invented.

See [document types](document-types.md#reminders).

## Timezone {#timezone}

Days are counted in the installation timezone (**Settings → General**, default Asia/Riyadh). Expiry dates are calendar dates without time.

## Recipients {#recipients}

- the document owner,
- the head of the owner's reminder group,
- delegates of that group with *Receive reminders*.

Each person receives one message even if they hold several roles. Disabled accounts receive nothing. Recipients are worked out when the reminder is sent, so a new head receives future reminders.

## Channels {#channels}

| Channel | Requirements |
|---|---|
| In-app | Always on |
| Email | SMTP configured by the administrator and an email address on the profile |
| Telegram | Telegram configured by the administrator and linked by the person |
| Push | The HTTPS address, push allowed by the administrator, and turned on by the person on each device ([push](notifications.md#push)) |
| WhatsApp | Planned for a later release — not available |

The administrator chooses default channels and may make channels **required**; users cannot turn required channels off. If a channel cannot deliver (no email address, Telegram not linked), the person sees the reason in **My account → Notifications** and the delivery is recorded as skipped — never as sent.

Push is never added to anyone's channels automatically. What each message contains is described [below](#message).

## What an expiry message contains {#message}

| Detail | Source |
|---|---|
| Title, e.g. "📅 Passport Expiry Alert" | The [document type](document-types.md#reminders); "Document (type not assigned)" when the document has no type |
| Name | The confirmed full name from the details, otherwise the owner |
| Expiry date and days remaining | The confirmed value of the field with the expiry role, in the installation time zone and date format |
| Folder | Where the document is kept |
| Document number | Hidden by default. Shown masked (last four characters) in email, Telegram and in-app only when the administrator turns on **Include document numbers in email/Telegram**; never in push |

Severity: 7 days or less, or the expiry day itself, is **Critical**; up to 60 days **Warning**; otherwise
**Information**. Unconfirmed OCR or Local AI values are never shown. There is never an attachment.

Actions: **Open Document**, **Go to Folder**, **View Expiry Reminders** and, in the app only, **Snooze 7 days**
(pauses this document's reminders for you for a week). Links require signing in and the normal permissions.
Layout per channel, icons and privacy: [notifications](notifications.md#document-types).

## Critical and optional notifications {#critical}

Every notification belongs to one of two classes.

**Critical notifications** are chosen by the main administrator in **Settings → Notifications → Critical notifications**.
Family members cannot turn them off. They always arrive in-app and on every channel listed under **Channels for
critical notifications** (default: in-app, email and Telegram). By default these are critical:
- new passkey registered, passkey removed
- authenticator app turned on or off, recovery codes regenerated, passwordless sign-in turned on or off
- two-step verification reset by an administrator or from the server console
- sign-in from a new country
- authentik account linked or unlinked
- for administrators: repeated failed sign-ins and automatic blocks, sign-ins allowed only by temporary country
  access, access-policy changes, authentication-policy changes, failed backups and integrity problems

The administrator can make any other event critical as well, or take one off the list.

**When a required channel cannot deliver**, nothing is pretended: the message is recorded as *skipped* with the
reason (no email address on the profile, Telegram not linked) and shown
- to the person, in red at the top of **My account → Notifications**
- to the administrator, under **Settings → Notifications → Delivery problems**

If email or Telegram is not configured for the whole installation yet, only the administrator is told (members
cannot fix that). Critical messages then still arrive in-app.

## Choosing your optional notifications {#optional}

**My account → Notifications → Optional notifications** is a table of events and channels (In-app, Email,
Telegram, Push). Tick exactly the combinations you want; each change is saved immediately and follows your account on
every device.

| Event | Default |
|---|---|
| Expiry reminders | In-app + the administrator's default channels (required channels are locked on) |
| Documents added (by someone else or by an import) | In-app, email |
| Documents archived or permanently deleted by someone else | In-app, email |
| Access given to you | In-app, email |
| Import finished | In-app, email |
| OCR / processing finished | Off |
| OCR / processing failed | In-app, email |
| Sign-in from a new address | In-app |
| Every sign-in (device, address, country) | Off |
| GeoIP / traffic report problems (administrators) | In-app, email |
| Documents moved, restored, re-typed or confirmed by someone else | In-app |

A channel the administrator has not configured is greyed out. Your choices never switch off a critical
notification or a required channel. If you had chosen channels or "Other alerts by email/Telegram" before this
version, those choices are used as your starting point.

## What messages look like {#templates}

Every channel is rendered from the same structured message (see [notifications](notifications.md#channels)): a card
in the Notification Center, an HTML email with a plain-text part, a formatted Telegram message with buttons, and a
short push notification. The plain-text part of an email keeps this layout:

```
Notification from Personal Documents Management System
Account: son1 (Son1)

2 files imported to your account
Imported by A. Ansari.

Folder: Family library / Son1 / Education
Date/time: 05 Oct 2026 14:31 (Asia/Riyadh)

Files:
1. Report card 2025
2. Fee receipt

Review: https://docs.example.com/folders/…
```

Sign-in alerts add the **IP address**, **Country** (from the local GeoIP database), **Sign-in method** and
**Device**. Passkey alerts name the passkey, for example "New passkey “Office laptop” registered".

Rules:
- **Never included:** passwords, one-time codes, TOTP seeds, recovery codes, passkey material, tokens, API keys,
  file contents, or anything about documents the recipient cannot open. Document numbers only masked and only when
  the administrator allows it (never in push); see [privacy](notifications.md#privacy).
- **Names:** folder, document and file names appear in full inside the app. In email and Telegram, long digit runs
  (often document numbers) are masked, e.g. `Passport Z99•••••`. Turn off **Include names in email/Telegram** to
  send only counts and a link.
- **Links** open the app and still require signing in and the normal permissions.
- **Bulk actions are summarised:** uploading 40 files or importing a folder produces one message per person with
  the first 10 names and "… and 30 more (see the report)", never 40 messages. Processing results of imported files
  are part of the import summary.
- **Archive vs delete:** "archived" means hidden but restorable by the main administrator; "permanently deleted"
  says it cannot be undone.

## Other alerts {#other-alerts}

The events above replace the earlier single "Other alerts by email/Telegram" switch. Backup failures and integrity
problems are sent at most once a day; security alerts are throttled so an attack produces one message, not
thousands. Recurring conditions follow the repeat cooldown described in [noise control](notifications.md#noise).
