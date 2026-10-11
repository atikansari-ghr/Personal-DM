# WhatsApp Personal bridge (experimental, unofficial, self-hosted)

> [!WARNING]
> **Experimental. Unofficial. Self-hosted.** This is not the WhatsApp Business Platform. It is not supported or
> endorsed by WhatsApp or Meta. WhatsApp may disconnect linked devices or change its protocol at any time.

This optional component lets each person link **their own** WhatsApp account to Personal DM as a linked device.
Personal DM then sends that person their own notifications, as a message to themselves. It is a notification
channel only.

| Topic | Decision |
| --- | --- |
| Library | `@whiskeysockets/baileys` **6.7.24**, pinned in `package.json` and `package-lock.json` (MIT licence). |
| Why this version | The 6.7 line is the maintained stable release. The 7.0 release candidates are not used. |
| Updates | `sudo personaldocs whatsapp-bridge update` installs only the version listed in `compat.json` (`tested_versions`). Upstream releases are never followed automatically. |
| Runtime | Node.js 20+ from Debian 13. Native systemd service `personaldocs-whatsapp`; no Docker. |
| Network | Listens on `127.0.0.1:8095` only. Every request needs the shared token in `/etc/personaldocs/whatsapp-bridge.token`. |
| Session storage | One file per session in `/var/lib/personaldocs/whatsapp/sessions/`. AES-256-GCM, with a key derived (HKDF-SHA256) from the token and the session id. |
| Scope | The send call has no recipient parameter. A session can only message its own account. There is no composer, bulk sending, contact list, chat reading or auto-reply. Incoming messages are not handled. |
| Failure behaviour | Reconnects are bounded (5 tries with back-off). Then the session is *Degraded*. If the library is incompatible, the bridge exits with code 3 and systemd does not restart it (`RestartPreventExitStatus=3`). Personal DM and the other channels keep working. |
| Rollback | `sudo personaldocs whatsapp-bridge rollback`. The sessions are archived (still encrypted) before every update. |

## Review summary (2026-10)

- **Compatibility:** the library loads under Node 22. The offline self-test (`node server.mjs --selftest`) passes. A
  live start reached WhatsApp and produced a linking QR code. Linking a real phone was **not** tested in CI; it needs
  a real account and is recorded as *Requires Real Account* in `docs/TEST_REPORT.md`.
- **Licence:** MIT for the bridge and the library. The npm dependency tree is listed in `package-lock.json`.
- **Security:**
  - loopback-only HTTP with token authentication (timing-safe comparison);
  - 16 KB request limit and per-session send rate limit (30 per minute);
  - credentials never leave the process; npm runs with `--ignore-scripts`;
  - systemd limits: `MemoryMax=400M`, `NoNewPrivileges`, `UMask=0077`.

## Files

- `server.mjs`: the bridge.
- `compat.json`: protocol version, pinned version and tested versions (read by Personal DM).
- `package.json`, `package-lock.json`: pinned dependencies.
