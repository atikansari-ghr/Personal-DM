# Antivirus (ClamAV)

## How scanning works {#overview}

Every new file is scanned in the background by **ClamAV**, the free open-source antivirus engine, running on your own server. Uploads are never held up: a file is stored and usable at once, and its scan status updates a few seconds later. Nothing is ever sent to a cloud scanner. Only file names, sizes, detection names and versions are logged — never file contents or recognised text.

| Status | Meaning |
| --- | --- |
| **Scan pending** | Stored and usable; waiting for its background scan. |
| **Clean** | ClamAV found nothing with the signatures of that moment. |
| **Not scanned** (warning) | ClamAV was unavailable or scanning is turned off. The file stays available. |
| **Not scanned — size limit exceeded** | Larger than the scan limit. Stored normally, never reported as clean. |
| **Scan failed** | ClamAV answered with an error for this file. The file stays available. |
| **Threat detected** / **Quarantined** | Malware found. The file is moved to quarantine and blocked (see below). |
| **Released from quarantine** | The main administrator released it after review. |

A small shield next to a file shows its status in folder lists; the document's **Versions** tab shows the engine, signature version and scan time. Files stored before antivirus scanning existed are marked *Not scanned* until an administrator runs **Scan entire existing library**.

**Fail-open by design:** if ClamAV is down, uploads continue and files stay usable, but they are marked *Not scanned* and administrators receive a critical alert. Re-scan them once ClamAV runs again.

### Archives {#archives}

ZIP, RAR and similar archives are scanned **as one file** by ClamAV with its default archive limits. Personal DM does not unpack archives itself, so a *Clean* result on an archive does not prove that every file inside was inspected individually.

## Installation {#install}

`personaldocs install` and `upgrade` install `clamav-daemon` and `clamav-freshclam` and configure clamd to listen **only on the local Unix socket** `/run/clamav/clamd.ctl` (no TCP port). ClamAV needs about **1.2 GB of memory** for its signatures; on a 2 vCPU / 4 GB container this fits, on smaller machines install with `--without-antivirus` and turn scanning off in Settings → Security → Antivirus. `personaldocs status` and `doctor` show the daemon, the signature updater and the signature age.

## Quarantine and release {#quarantine}

When ClamAV detects a threat, the file is immediately marked *Threat detected*, moved to `<data>/quarantine` (readable only by the service) and **preview, download, sharing, export, OCR and Local AI are blocked** for it. Its metadata stays so the record can be managed, and administrators receive a critical notification.

Only the **main administrator** can act on a quarantined file in Settings → Security → Antivirus:

- **Release…** shows a malware warning and requires a confirmation and a reason (at least 10 characters); the release is audited and administrators are notified.
- **Delete…** permanently deletes the quarantined copy after typing DELETE (the document too, if it was its only file).

Administrators see the quarantine but cannot release files. Quarantined copies are not included in backups.

## Scan size limit {#size}

**Maximum scan size** (default 50 MB) sets the largest file scanned. Larger files are stored and marked *Not scanned — size limit exceeded*. Values above 200 MB can use a lot of memory on a 4 GB server. clamd's own stream limit is set higher by the installer, so the setting in the app decides.

## Scanning the existing library {#schedule}

Administrators can start **Scan entire existing library** (or re-scan one document) under Settings → Security → Antivirus. It runs in the background in small batches with progress, and can be paused, resumed or cancelled. **Re-scan the whole library** can also run Daily, Weekly or Monthly (default: Disabled) at a chosen time; a monthly day that does not exist in a month runs on its last day.

## Signature updates {#signatures}

`clamav-freshclam` updates the signatures automatically (hourly checks). **Update now** runs an immediate update through the root host helper. The page shows the signature version, its date and age, the last manual update and any error. Signatures older than **Definitions out of date after** (default 2 days) show a warning; older than **critically stale** (default 7 days) they put Security Health *At Risk*. ClamAV unavailable, stale definitions, update failures, scan failures, detections and releases are **critical administrator notifications that cannot be turned off**.
