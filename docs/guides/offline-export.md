# Offline access and exports

## Keeping folders and documents offline {#offline}

You can keep chosen folders and documents on **this device** — this browser, or the installed app — for use without
a connection. Nothing is stored offline unless you choose it; simply viewing a document does not cache it.

- **A folder:** open its **⋮** menu → **Make available offline…**, then choose
  - **This folder and all subfolders** (recommended), or
  - **This folder only**.

  The dialog shows the number of documents and subfolders, the estimated size and the free browser storage. It warns
  before a large download. Documents added to the folder later are downloaded at the next sync.
- **A document:** **⋮** → **Make available offline**.
- **⋮ → Update offline copy** downloads the newest version now. **⋮ → Remove offline copy** deletes the copy from this
  device. A document that is offline because its folder is stays until you remove the folder's offline copy.

You need download permission. Folders and documents you can only view are not offered.

### Status {#status}

Each document shows its offline status with an icon **and** text, never colour alone:

| Status | Meaning |
| --- | --- |
| Available offline | The copy on this device matches the newest version you may access. |
| Downloading / Updating *n %* | The copy is being downloaded (progress is announced to screen readers). |
| Update available | A newer version exists; the older copy stays usable until you update (automatic updates off). |
| Outdated — not checked for a week | The device has not been able to check with the server for more than 7 days. |
| Offline copy failed | The last download failed (for example no storage left); the reason is shown. An older copy stays usable. |
| Locked — connect to unlock | No sync for longer than the administrator allows; connect and sign in again. |
| Not available offline | Shown in the document's footer only. |

Folders kept offline have a small marker in the folder tree.

### The Offline access page {#page}

**Offline access** (sidebar) shows, for this device:

- the device's name (renamable) and the last sync;
- how many documents are offline, their size, and the offline folders;
- pending updates and failures;
- browser storage used, the browser's limit and the suggested limit set by your administrator.

**Sync now** checks for changes. **Update all** downloads every pending update. **Manage storage** lets you:

- ask the browser to protect the storage;
- keep copies after sign-out;
- remove every offline copy from this device.

Your other devices are listed too: you can rename them, or **Forget** one so it deletes its copies when it next connects.

### Updates {#updates}

When the app starts, when the connection returns, every 15 minutes, and on the Offline access page, the device sends
the server the list of copies it holds. The server answers with what this device may hold **now**. Then the device:

- downloads what is new;
- updates or flags newer versions;
- deletes everything else: copies that were deselected, archived, quarantined by the antivirus, or that you no longer
  have download access to.

If automatic updates are off (administrator setting), newer versions show **Update available** instead.

### Recognised text offline {#text}

Recognised (OCR) and extracted text is **not** kept offline unless the administrator turns on *Keep recognised text
offline*. When it is on, the text is stored apart from the files. It is updated when the text changes. When OCR data is
removed from a document, or the setting is turned off, the text is deleted at the next sync.

### Sign-out, other accounts and lost devices {#signout}

- Offline copies belong to **your account on this device**. Another person signing in on the same browser sees none of
  them. Making a folder available offline on your computer downloads nothing to your phone.
- By default your copies are **deleted when you sign out**. You can choose **Keep my offline copies on this device
  after I sign out**, unless your administrator requires removal at sign-out.
- The administrator can turn offline copies off for everyone, or for one person. They can also remove the copies from
  one device. Each takes effect at that device's next sync.
- **Limitation:** a server cannot erase files from a device that stays completely offline. Such a device:
  - keeps them readable until it has gone *Lock offline copies after* days without a sync (default 30);
  - then locks them in the app until it connects and signs in again.

  Locking is enforced by the app on the device. Someone with full control of the device and browser storage could
  still read files that were never removed. For a lost device, also sign it out in **Settings → My account → Password
  & security → Sessions**.

### Limits {#quota}

Browsers limit how much they store and may delete data when the device is low on space (use **Protect storage**).

The administrator sets a suggested size per device: you are warned before going over it, and before large
downloads. The browser's own limit always applies. Large libraries (for example 10 GB) usually do not fit on a phone;
use the export below.

### How it is stored {#storage}

The browser keeps four things apart:

| What | Where |
| --- | --- |
| App shell (pages, scripts, icons; no user data) | Service-worker cache `pd-shell-*` |
| Your offline files | Cache `pd-offline-<account>` |
| Offline text, only when allowed | Cache `pd-offline-text-<account>` |
| Titles, sizes and status | Local storage `pd-offline-index-<account>` |

API answers, previews and public share pages are never cached.

Selections, device names and sync reports (counts and sizes only, no titles or text) are kept on the server. Saving,
updating and removing copies is recorded in the audit log.

## Administrator settings {#admin}

**Settings → Offline & PWA**:

| Setting | Effect |
| --- | --- |
| *Offline copies* | Allow or turn off offline copies for everyone. |
| *Update offline copies automatically* | Download newer versions at sync. |
| *Keep recognised text offline* | Off by default. |
| *On sign-out* | Remove copies at sign-out unless the person chose to keep them, or always remove them. |
| *Lock offline copies after (days without sync)* | 0 = never lock. |
| *Suggested space per device* and *Large download warning* | Warnings before a selection exceeds these sizes. |

**People and devices**:

- turn offline copies on or off per person;
- see each device's copies, size, failures and last sync;
- **Remove copies** from one device (at its next sync).

## Exporting your library {#export}

**Offline access → Export my whole library** downloads every document you can download, in its folder structure. It
comes as one or more ZIP parts (512 MB, 2 GB or 4 GB).

- Each part contains `MANIFEST.json` and `SHA256SUMS.txt` for checking integrity.
- The export is streamed, so the server does not need extra disk space to build it.
- A single folder (for example a DICOM study) can be downloaded with **Download folder (ZIP)**.
- Exported files are outside the app: their use cannot be tracked or revoked.
