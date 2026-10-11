<!-- reviewed: 2026-10-11 -->
# WhatsApp Personal (experimental)

> [!WARNING]
> **Experimental. Unofficial. Self-hosted.** WhatsApp Personal links your own WhatsApp account to Personal DM as a
> linked device and sends you your notifications as messages to yourself. It is **not** the WhatsApp Business Platform.
> It is **not** supported or endorsed by WhatsApp or Meta. WhatsApp can disconnect linked devices or change its
> protocol at any time, and such use may conflict with WhatsApp's terms. Use it at your own risk, and keep another
> channel (Email or Telegram) in your [fallback chain](notifications.md#fallback).

## What it is and is not {#scope}

- **Notification-only.** It sends Personal DM notifications (expiry, sharing, security and sign-in, backup and recovery,
  storage and system, OCR and antivirus, digests) to **your own** WhatsApp account only.
- It has **no** message composer, bulk or marketing sending, contact list, chat reading, automatic replies or general
  messaging.
- Each person links their own account. One person's session can never send as someone else.
- If the bridge stops or WhatsApp breaks compatibility, Personal DM and every other channel keep working.

## Install and enable (administrator) {#enable}

1. On the server, run:

   ```
   sudo personaldocs whatsapp-bridge install
   ```

   This installs Node.js from Debian if needed, and the **tested, pinned** bridge version. It then runs a self-test and
   starts the service `personaldocs-whatsapp` (listening on `127.0.0.1:8095` only).
2. Open **Settings → Connections**, turn on **WhatsApp Personal (experimental, unofficial)** and click **Save**.
3. Check **Settings → Notifications → Notification delivery health**. The bridge should show
   *Running (tested version)*.

It is off by default and is never turned on automatically, also not on upgrade.

### The bridge {#bridge}

| Item | Detail |
| --- | --- |
| Service | `personaldocs-whatsapp` (systemd). Bounded restarts: after 5 failures in 15 minutes it stops, and an incompatible library version is never restarted. |
| Address | `http://127.0.0.1:8095` (*WhatsApp bridge address*). Only loopback addresses are accepted. |
| Access | A random token in `/etc/personaldocs/whatsapp-bridge.token`. |
| Sessions | One encrypted file per linked person in `/var/lib/personaldocs/whatsapp/sessions/`. They are part of the encrypted backup's secrets package. |
| Version | Pinned in `bridge/whatsapp/compat.json`, together with the compatibility, licence and security review in `bridge/whatsapp/README.md`. |

## Link your WhatsApp {#link}

1. Open **My account → Notifications → WhatsApp Personal** and click **Link WhatsApp**.
2. On your phone, open **WhatsApp → Settings → Linked devices → Link a device**.
3. Scan the QR code shown in Personal DM within about a minute, then click **I scanned it**.
4. The status changes to **Connected** and shows the last digits of your number.
5. Click **Send test**. A test message arrives in your "Message yourself" chat.
6. Choose **WhatsApp Personal** per category in [Routing by category](notifications.md#routing), ideally as the first
   item of a fallback chain.

> [!NOTE]
> **Privacy** The QR code is shown only to you, while you are linking. It is never stored, logged or included in
> screenshots. The linked-device credentials stay in the bridge, encrypted per person. Personal DM's database stores
> only the state and the last digits of the number.

## States {#states}

| State | Meaning and what to do |
| --- | --- |
| **Connected** | Notifications are delivered. |
| **Waiting for QR scan** | Scan the code, or click **Link WhatsApp** again for a new one. |
| **Disconnected** | Temporary; the bridge retries a few times. Then click **Link again (new QR)**. |
| **Degraded** | The bridge is not running or is not compatible. Ask the administrator (see [Updates](#updates)). |
| **Reconnect Required** | WhatsApp ended the linked-device session, or a Compromise recovery reset it. Link again with a new QR code. |

**Unlink** logs the linked device out and deletes the session.

## Updates and rollback {#updates}

```
sudo personaldocs whatsapp-bridge status     # installed and tested version, service, bridge health
sudo personaldocs whatsapp-bridge update     # only to the version tested with this Personal DM release
sudo personaldocs whatsapp-bridge rollback   # back to the previous bridge version
sudo personaldocs whatsapp-bridge disable    # stop the bridge and turn the feature off
```

An update first archives the encrypted sessions. It then installs the new version next to the old one, runs a self-test
and a health check, and switches over only when both pass; otherwise it rolls back automatically. Upstream releases are
never followed automatically. When Personal DM ships a newly tested version, the delivery-health card says *a tested
update is available*. Updates are audited.

## After a recovery {#recovery}

- **Normal disaster recovery:** the encrypted sessions are restored and reconnected. A session WhatsApp rejects shows
  **Reconnect Required**.
- **Compromise recovery:** restored sessions are never trusted. Everyone links again with a new QR code.

## Troubleshooting {#troubleshooting}

| Symptom | Fix |
| --- | --- |
| *The WhatsApp bridge is not running* | `sudo systemctl status personaldocs-whatsapp` and `journalctl -u personaldocs-whatsapp -n 50`, then `sudo personaldocs whatsapp-bridge install`. |
| *Incompatible bridge version* | `sudo personaldocs whatsapp-bridge update` (tested version) or `rollback`. |
| Messages stop after a while | WhatsApp ended the session: link again. Keep Email or Telegram in your fallback chain. |
