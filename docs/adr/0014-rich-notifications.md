# ADR 0014: Rich notifications from one structured message

Status: accepted (2026-10-07, change set O)

## Context

- Notifications went to three channels: in-app (`Notification` rows), email and Telegram (`OutboxMessage` with a
  plain-text body, delivered by the worker). There was no push channel.
- One plain-text layout (`notify/templates.py::render`) produced every body. Each call site (`notify/events.py`,
  `notify/expiry.py`, `security/alerts.py`, `security/antivirus.py`, `security/center.py`, `views_center.py`, the
  passkey, TOTP and recovery events) built its own strings. Telegram got the same text as email, and the in-app feed
  showed a title with a generic icon, so severity and the affected document or device were not visible at a glance.
- Families read notifications mostly on phones, often from the lock screen. Expiry reminders and security alerts
  need to say clearly how urgent they are and what to do next.
- Notification content mixes trusted wording with untrusted values (document and folder names, OCR-derived details,
  device strings), and administrators want to adjust wording without code changes.
- Links in messages travel outside the application (mailboxes, chats, lock screens) and may be forwarded.

## Decisions

1. **One structured message, many renderers.** Every event builds a `Message` (event, severity, category, icon,
   title, heading, summary, details, actions, guidance, items, link, placeholder context, TEST flag) in
   `notify/rich.py`. Channel renderers (`render_in_app`, `render_email`, `render_telegram`, `render_push`) only lay it
   out. Severity, category and icon defaults live in the event catalogue (`event_defs.py`), the icon map in
   `icons.py`. Older call sites go through `from_legacy`.
2. **Conservative formats.** Email is multipart: the earlier plain-text layout plus a table-based HTML part with
   inline styles, no JavaScript, no images and no tracking pixels, and `dir="auto"`. Telegram uses its HTML parse mode
   and falls back to plain text if rejected. Severity is always written as text, never shown by colour alone.
3. **Escape in the renderer.** Values are escaped by the renderer for its own output format, never by the caller.
   Template text is plain text; HTML in it is shown as text.
4. **Actions are application paths.** Actions are paths inside the app, without tokens; opening one requires sign-in
   and the normal permission checks. `safe_path` refuses API paths and quarantine releases, so a release can never be
   triggered from a message. Actions that change state from a notification (Snooze) are in-app only and go through an
   authenticated API call that re-checks access.
5. **Templates change presentation, not behaviour.** `NotificationTemplate` overrides title/subject, heading, summary,
   icon, severity shown and action labels per event and channel. Placeholders come from an allowlist; unknown
   placeholders and other braces are refused. Recipients, channels, details and action targets are not templated, and
   `floor_severity` keeps critical events at Warning or above. Previews and TEST sends use sample data, and a TEST send
   creates no real event, only the audit entry `notifications.test_sent`.
6. **Web Push with standard, maintained libraries.** Push uses VAPID and aes128gcm (`py-vapid`, `http-ece`) rather
   than a hand-written implementation. The key pair is created on first use and stored encrypted in the database so
   it survives restores. Subscriptions are accepted only for HTTPS endpoints on the known push services, which keeps
   the server from calling internal addresses. The lock-screen content is limited by each person's `me.push_preview`;
   sensitive details are never rendered for push. Push is opt-in per device and never added to anyone's channels by
   the migration.
7. **Sensitive details are opt-in and masked.** The document number is a detail marked sensitive: hidden by default,
   masked to the last four characters in email, Telegram and in-app when `notifications.include_document_number` is
   on, and never in push.
8. **Noise control at the source.** Recurring conditions carry a cooldown group; the same group is not sent to the
   same person again within `notifications.repeat_cooldown_hours`, independent of the daily idempotency key. New
   critical events and expiry schedules are not affected.
9. **Honest delivery states.** The delivery history shows queued, retrying, sent, failed and skipped, plus the
   provider's message id as "accepted by the provider". It never claims delivery to the device, which these providers
   do not report.

## Consequences

- New channels or layouts need only a renderer; wording and severity stay consistent across channels.
- Administrators can change wording safely, but cannot add fields, recipients or links through templates; a request
  for more content needs a code change to the event.
- HTML email appearance varies between mail programs; the plain-text part carries the same content.
- Push depends on the HTTPS address and on the browser's push service; on iPhone/iPad the app must be on the Home
  Screen. Browsers whose push service is not on the allowlist cannot subscribe.
- The migration (`notify.0002_rich_notifications`) adds fields and tables and classifies existing in-app
  notifications without changing their text; rollback to a release without it requires restoring the pre-upgrade
  backup.
- Two Python dependencies (`http-ece`, `py-vapid`) must be kept up to date with the other cryptography dependencies.
