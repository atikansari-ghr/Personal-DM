# ADR-0005: Threshold marks + keyed outbox for reminders

- Status: accepted

## Decision
Each run computes, per active document with a confirmed expiry date, the smallest reached threshold; it is sent once (`ExpiryMark` action=sent) and larger unsent thresholds are marked skipped. Deliveries are rows in `OutboxMessage` with a unique key per (document, expiry date, threshold, recipient, channel). In-app notifications are written immediately; email/Telegram are delivered by the scheduler with retry/backoff and redacted errors. Missing channel configuration produces *skipped* rows with an actionable reason.

## Consequences
Restarts, retries and duplicate runs cannot send duplicates; catch-up never floods; changed dates naturally start a new schedule.
