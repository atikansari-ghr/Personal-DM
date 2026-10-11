# ADR 0021: Notification routing, fallback, Discord and the WhatsApp Personal bridge

Status: accepted (2026-10-11, change set T).

## Context

People asked for these channels:

- Discord;
- WhatsApp, because most of the family read it;
- per-topic channel choice;
- quiet nights;
- summaries instead of many single messages.

Delivery already went through the outbox with retries (ADR 0014). There is no official WhatsApp API for personal
accounts.

## Decision

1. **Route categories.** Each event belongs to one route category (security, backup, documents, reminders, system…)
   through `route_of()`. A person chooses channels per category. The choice is stored in `me.notification_routing`,
   together with a fallback chain and a digest mode.
2. **Fallback.**
   - When the primary channel fails after the configured number of attempts, or is disconnected, the message is
     queued **once** on the next channel in the chain. The fallback is linked through `fallback_of`.
   - A successful primary delivery cancels the fallback, so a message is never delivered twice.
3. **Quiet Hours and digests.**
   - Normal messages are held until the quiet period ends, in the person's own time zone.
   - Messages are urgent only when their severity is *critical* or the event is defined as critical; urgent messages
     always go through. Text that the template requires does not make a message urgent.
   - A digest collects messages and sends one summary at the person's digest time, daily or weekly.
4. **Discord:**
   - Each person has their own webhook, stored encrypted and shown masked.
   - The connection test reads the webhook's details without posting.
   - The message is an embed with no document content.
5. **WhatsApp Personal (experimental):**
   - It is a separate Node service (`bridge/whatsapp`, Baileys pinned to a checked version), bound to localhost and
     installed only on request.
   - One linked-device session per person, stored separately.
   - The application can only send notification text to the person's own number. There is no composer, no contacts and
     no other recipients.
   - The bridge reports its version. The application refuses an incompatible bridge.
   - `personaldocs whatsapp-bridge update` keeps the previous version for `rollback`.
   - If the bridge is down, only WhatsApp deliveries fail; they then fall back.
6. **Opt-in only.** The migration enables neither Discord nor WhatsApp for anyone.
7. **Delivery status.** People see their own delivery history: channel, status and time, without the message bodies of
   other people. Administrators see counts per channel and state only.
8. **Sandbox mode** (`PD_SANDBOX`) disables delivery and the scheduler. Recovery validation uses it, so a restored copy
   never sends messages.

## Consequences

- WhatsApp may break when WhatsApp changes its protocol. It is labelled experimental, isolated from the other channels,
  and covered by fallback.
- Signal is not offered.
