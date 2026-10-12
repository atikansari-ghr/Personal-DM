<!-- reviewed: 2026-10-12 -->
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
2. Open **Settings → Connections** and scroll to **WhatsApp Personal**. The **Bridge service** panel shows what the
   server really reports:

   | Row | Expected value |
   | --- | --- |
   | Installed | Yes |
   | systemd service | active |
   | Reachable from Personal DM | Yes (127.0.0.1) |
   | Bridge version / Protocol | 1.0.0 / 1 (expected 1) |
   | Compatibility | Compatible (tested version) |

   Before you turn it on, the badge reads **Installed and running - turned off**.
3. Turn on **WhatsApp Personal (experimental, unofficial)** and click **Save settings**. The badge changes to
   **Running**. No restart is needed: everyone can link their phone at once.

![WhatsApp Personal in Settings → Connections with the bridge service panel](../images/screenshots/connections-whatsapp.png)

The screenshot comes from the test system, which has no systemd and uses the test bridge, so *Installed* and
*systemd service* show **Unknown** there. On a server installed with `personal-DM.sh` they show **Yes** and **active**.

It is off by default and is never turned on automatically, also not on upgrade. At the top of **Settings → Connections**,
the **Notification providers** cards show every channel with its scope, status and a **Configure** link.

| Bridge badge | Meaning | Fix |
| --- | --- | --- |
| **Not installed** | The bridge files are missing. | `sudo personaldocs whatsapp-bridge install` |
| **Service stopped** / **Service unavailable** | systemd reports the service inactive, or it does not answer on 127.0.0.1. | `sudo systemctl start personaldocs-whatsapp`; `journalctl -u personaldocs-whatsapp -n 50` |
| **Incompatible bridge version** | The bridge speaks another protocol. | `sudo personaldocs whatsapp-bridge update` or `rollback` |
| **Degraded (untested version)** | Compatible protocol, but not a tested version. | `sudo personaldocs whatsapp-bridge update` |

While the bridge is unavailable, people see **Service unavailable** on their card and their fallback channels are used.
Other channels are never affected.

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
3. Scan the QR code shown in Personal DM. The code refreshes by itself about every minute; **New QR code** makes a fresh
   one at once.
4. A few seconds after the scan, the status changes to **Connected** and shows the last digits of your number.
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
| **Degraded** | The bridge is not running or is not compatible. Click **Reconnect**, or ask the administrator (see [Updates](#updates)). |
| **Disabled by Admin** | WhatsApp Personal is turned off for the installation. The administrator turns it on in Settings → Connections. |
| **Service unavailable** | The administrator turned it on, but the bridge does not answer. Your fallback chain is used meanwhile. |
| **Reconnect Required** | WhatsApp ended the linked-device session, or a Compromise recovery reset it. Link again with a new QR code. |

**Reconnect** asks the bridge to restore the connection without a new QR code. **Unlink** logs the linked device out and deletes the session. The card also shows when your last WhatsApp notification was delivered.

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
| Install says *the pinned WhatsApp library is missing* (`Cannot find package '@whiskeysockets/baileys'`) | Fixed in the release after Change Set T: the first install installed the library readable only by root. Upgrade (`sudo personaldocs upgrade`) and run `sudo personaldocs whatsapp-bridge install` again. Nothing was changed by the failed attempt. |
| *Incompatible bridge version* | `sudo personaldocs whatsapp-bridge update` (tested version) or `rollback`. |
| Messages stop after a while | WhatsApp ended the session: link again. Keep Email or Telegram in your fallback chain. |
