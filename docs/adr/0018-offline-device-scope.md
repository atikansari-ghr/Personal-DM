# ADR 0018: Offline copies scoped by account + device, with server-authoritative sync

Status: accepted (2026-10-09, change set S). The change prompt called it "Change Set R" with AT-226…AT-250. Those
numbers were already used, so it is Change Set S with AT-251…AT-275 here (prompt AT-n = AT-(n+25)).

## Context

Before this change, offline use was a per-document "Save for offline use":

- a localStorage index per account and a Cache Storage bucket per account;
- revocation by asking `/api/offline/validate` about the cached version ids.

This had four gaps:

- no folders, no subfolder choice, no size estimate;
- no notion of a device, so nothing could be managed or audited per device;
- updates were only flagged;
- the administrator could not turn offline copies off for a person.

## Decision

1. **Scope = account + device + target.**
   - A device is one browser profile or one installed app (`OfflineDevice`, a server-issued id that is not a secret
     and is kept in that browser's local storage per account).
   - Selections (`OfflineSelection`) are a folder (recursive or not) or a document, and belong to one device.
2. **Server-authoritative sync.**
   - The device sends what it holds (`/api/offline/sync`).
   - The server computes the permitted set with the normal permission engine (download capability), and excludes
     archived and quarantined documents.
   - It returns that set plus the list to delete. Newer versions are downloaded, or flagged when automatic updates
     are off.
   - Folder paths are revealed only from the selected folder down. A selection whose folder is no longer visible is
     named "Folder no longer available".
3. **Separate storage per kind.**

   | What | Where |
   | --- | --- |
   | App shell | `pd-shell-*` (service worker) |
   | Originals | `pd-offline-<account>` |
   | Recognised text (only with the admin policy) | `pd-offline-text-<account>` |
   | Index | localStorage |

   API answers are never cached. The text policy is independent and default off, and the text disappears at the next
   sync after OCR removal.
4. **Administrator control:**
   - global switch;
   - per-person capability (`User.offline_allowed`);
   - per-device wipe (one-shot at the next sync);
   - sign-out policy (user choice or always remove);
   - lock after N days without sync;
   - suggested quota and large-download warning.
5. **Upgrade compatibility.** Copies saved with the old index are kept. At the first sync they become document
   selections of the device.

## Consequences

- Revocation and policy changes take effect at the device's next sync: on start, on reconnect, every 15 minutes and on
  the Offline access page. A device that stays offline cannot be reached. It locks its copies after the configured
  days, enforced by the app, not cryptographically. This is documented to users and administrators.
- Device registration is per account per browser profile. Clearing site data creates a new device; the old one can be
  forgotten from any other device.
- The server stores selections and sync reports (counts and bytes) but never titles or content of what a device holds.
