# ADR 0009: Notification classes, safe moves and the in-app viewer

Status: accepted (2026-10)

## Context

The public-release change set asked for critical vs optional notifications, detailed but safe templates, reliable
drag and drop with a non-drag fallback, an import destination picker, and zoom/fit controls in the viewer.
Investigation found that drag-to-move did not exist in the UI (dragging only started the browser's native drag of
text or thumbnails), that members could not move their own documents between their own folders (every move of an
inheriting item required "manage permissions"), that folder moves were not atomic or serialised, and that the PDF
preview depended on the browser's built-in viewer.

## Decisions

1. **Notification catalogue** (`notify/event_defs.py`, `notify/catalog.py`). Each event has a key, label, group and
   default channels. The main administrator chooses the critical events and the critical channels (settings);
   people choose the rest per event and channel (`me.notification_prefs`). Channel resolution is
   `chosen ∪ locked` where locked = critical channels (+ in-app) for critical events and required channels for
   expiry reminders. Undeliverable required channels are recorded as *skipped* with the reason, never as sent;
   installation-level gaps (channel not configured) are shown to the administrator only.
2. **One template** (`notify/templates.py`) for in-app, email and Telegram. Names are shown in full in the app and
   masked in external messages (digit runs ≥ 6) or hidden entirely by setting. Bulk actions produce one summary per
   recipient; imported files do not trigger per-file processing messages.
3. **Moves** run in a transaction with row locks; folder moves also take a PostgreSQL advisory lock so two opposite
   concurrent moves cannot create a cycle. A non-administrator needs "manage permissions" only when the move would
   *widen* access (someone gains a capability through the new parent), computed from the inherited rule set and
   folder owners (delegations).
4. **Drag and drop and Move to…** share the client-side reasons and the same server endpoints. Touch devices use
   Move to…; a global guard stops dropped files from navigating away from the app.
5. **Viewer:** PDF.js (legacy build, loaded on demand) renders PDFs to canvases from the authenticated preview
   endpoint; fonts, character maps and decoders are served by the app, so no document or request leaves the
   server. `isEvalSupported` is off and the CSP is unchanged. The browser's PDF viewer remains as a fallback.
6. **File types** come from validated MIME types (Office containers are checked, archives detected); Office files
   whose content does not match their extension are stored but never sent to the converter.

## Consequences

- New settings: `notifications.critical_events`, `notifications.critical_channels`, `notifications.include_names`,
  `me.notification_prefs`, `backup.enabled|frequency|weekday|month_day`; `me.dashboard_widgets` became an ordered
  list. No database migrations were needed; older values are converted when read.
- The frontend bundle gains PDF.js (~0.5 MB, loaded only when a document is viewed) and ~4 MB of static PDF.js
  assets.
