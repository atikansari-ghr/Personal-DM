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
| WhatsApp | Planned for a later release — not available |

The administrator chooses default channels and may make channels **required**; users cannot turn required channels off. If a channel cannot deliver (no email address, Telegram not linked), the person sees the reason in **My account → Notifications** and the delivery is recorded as skipped — never as sent.

Messages contain only the person's name, document type, expiry date, days remaining and a link that requires sign-in. Never a document number or attachment.

## Other alerts {#other-alerts}

Besides expiry reminders, the app notifies you when:

| Event | Who |
|---|---|
| Someone gives you (or your group) access to a folder or document | The person or group members |
| A folder import finishes | The person who started it |
| A document you uploaded could not be processed | The uploader |
| A backup fails | Main administrators (at most once a day) |
| The integrity check finds problems | Main administrators (at most once a day) |

These always appear in the in-app feed. They are also sent to your email/Telegram channels unless you turn off **Other alerts by email/Telegram** in My account → Notifications. External messages only say what happened and link to the app; they never contain document numbers or files.
