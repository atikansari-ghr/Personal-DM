<!-- audience: admin -->
<!-- reviewed: 2026-10-16 -->
# Performance

Personal DM is built to stay quick on a small server: the reference installation is a Debian 13 Proxmox container
with **6 GB of memory**. This guide explains what to expect, how the app keeps signing in and browsing quick while
OCR, antivirus scans and backups run, where to look when it feels slow, and what the upgrade does.

## What to expect {#targets}

| Screen or action | Target |
| --- | --- |
| Sign-in page usable | 1.5 s or less |
| Dashboard after signing in | 2 s or less |
| Settings, first section | 1.5 s or less |
| Settings, a section opened before | 0.5 s or less |
| A folder's first documents | 1 s or less |
| Opening a document's details | 1 s or less |
| Search in a family library | 1–2 s |
| A typical request | 0.5 s or less (preferably) |

The measurements behind these targets, and how to repeat them, are in `docs/PERFORMANCE.md` in the repository. Your
own times depend on your server, your network and your library: use **Settings → Performance** to see them.

## How the app stays quick {#how}

- **Settings loads one section at a time.** Opening Settings loads only the section you see. Other sections load
  when you open them, and a section you opened before appears at once and is refreshed in the background. A change
  you save is always read back fresh. Links to a section, **Back** and **Forward** work as before.
- **Screens load when you open them.** The sign-in page downloads only what it needs (about 90 KB). The rest of the
  app is fetched in the background while you sign in, and every app file is sent compressed.
- **Large folders load in pages.** A folder shows its first 100 documents straight away and loads more as you scroll
  (or with **Load more**). The order and the total are the same as before; selecting **Select all** selects the
  documents already loaded. Lists never download the files themselves: previews and downloads load only when you
  open them. Thumbnails load as they come into view.
- **Fewer database round trips.** Lists, the dashboard, notification preferences and the session check read what
  they need in a few queries, however many documents you have.

## Caches and freshness {#caching}

Personal DM caches only data that is the same for everyone allowed to see it, and keeps it short-lived:

| Data | How fresh |
| --- | --- |
| Signing in, permissions, sessions, documents, details, uploads, archive, sharing | Always read fresh, on every request |
| Settings | Read once per request; a saved change applies from the next request, in every server process |
| Sign-in page design (public) | Cached until a design or the sign-in title changes |
| Backup and security health summaries (administrators) | Up to 30 s old; refreshed at once when a backup, scan or security job ends or a related setting changes |

Passwords, keys, tokens and other secrets are never cached. No external cache service (such as Redis) is needed.

## Background work and adaptive throttling {#throttling}

Background work runs one job at a time at a lower priority than the web service, so signing in and browsing come
first. Text recognition (PaddleOCR) keeps its single worker.

When the server stays under **heavy load for about two minutes** (CPU, memory, swap or disk), Personal DM stops
*starting* non-urgent background work until the load has been normal for about three minutes:

- **Postponed:** OCR runs, bulk OCR, library antivirus scans, local AI tasks, traffic reports, GeoIP updates,
  integrity checks, server imports, mailbox checks.
- **Never postponed:** notifications and security alerts, sign-in related work, the antivirus check of a new upload,
  backups and their verification, recovery and key rotation.
- A running job is never interrupted; it finishes normally.
- A postponed job starts after at most **15 minutes** even if the load stays high, so nothing waits forever.
- Short spikes are ignored. Every start and end is listed under **Recent performance events**.

While it is active, **Settings → Performance** shows **Background processing throttled** with the reason.

**Settings** (main administrator, Settings → Performance):

| Setting | Default |
| --- | --- |
| Adaptive background throttling | On |
| Throttle when CPU busy above | 90 % |
| Throttle when available memory below | 10 % |
| Throttle when swap used above | 50 % |
| Throttle when disk pressure above | 40 % (where the container reports disk pressure) |
| Longest postponement | 15 minutes |

The defaults suit a 6 GB container. Lower the CPU value only if browsing feels slow while OCR runs; raise it if
background work seems to wait too often.

## Settings → Performance {#dashboard}

Administrators see:

- current CPU, available memory, swap, load, a 4 KB storage write time, disk pressure, database connections and the
  job queue;
- whether background processing is throttled, and why;
- warnings (for example little memory, swap in use, slow storage, a growing queue, a worker that stopped reporting);
- trends for response time, CPU, memory and the queue;
- **Slowest requests** and all requests by type, with average and slowest time, database queries and server errors;
- background job durations and failures;
- cache use and loading problems reported by browsers;
- recent performance events (slow requests, throttling, maintenance).

Requests are listed by their type (for example `GET api/documents/<uuid:pk>`), never by address: no names,
search words, document numbers, IP addresses or document contents are stored. Measurements are 10-minute summaries,
kept for **14 days** (Settings → Performance → *Keep performance measurements*). Requests slower than 2 s (adjustable)
are listed as slow.

**Download Diagnostic Report** (main administrator) saves the same information plus the environment (versions, CPU
count, database size and memory settings, performance settings) as a JSON file you can keep or share with someone
helping you. It contains no passwords, keys, tokens or document data. Downloading it is recorded in the activity log.

## Server settings {#runtime}

The web service runs **2 processes with 4 threads each** (`PD_WEB_WORKERS=2`, `PD_WEB_THREADS=4` in
`/etc/personaldocs/personaldocs.env`). Threads let a slow request, such as a large download, wait without holding
up everyone else. On the test server this answered about 48 % more requests per second under background load than
2 single-threaded processes, for about 13 MB more memory per process.

App files carry a fingerprint in their name and are cached by browsers for a long time; a new release has new
names, and the app page itself is always re-checked, so nobody keeps an old version after an upgrade.

These are starting points measured on one server, not universal values. Change them only when Settings →
Performance shows a reason, and restart afterwards: `sudo systemctl restart personaldocs-web`.

Memory on a 6 GB container, roughly: web service 2 × 130 MB, job worker up to 4 GB during OCR (systemd limit),
PostgreSQL (defaults), ClamAV about 1–1.5 GB, the rest for the system and the file cache.

## After an upgrade {#maintenance}

`sudo personaldocs upgrade` runs these steps after the database migrations, and they are safe to run again
(`sudo personaldocs post-upgrade`):

1. Refreshes the database statistics (`ANALYZE`).
2. Checks that every index is valid and rebuilds an interrupted one of its own without locking documents.
3. Empties the shared cache (it refills on demand) and removes leftover temporary files.
4. Checks that the app files are built and compressed.
5. Removes performance measurements older than the retention period.

Nothing is deleted from your documents, history or settings. The result is listed in the upgrade output and under
**Recent performance events**.

## When it feels slow {#troubleshooting}

1. Open **Settings → Performance** and read the warnings.
2. **Throttled for a long time?** The server is busy for longer than expected. Check what runs under **Background
   jobs**; a large import or a full library scan can take hours. Consider more CPU for the container.
3. **Swap in use or little memory available?** Check `free -m`. Give the container more memory or lower
   *Concurrent OCR/conversion jobs* (Settings → OCR & processing).
4. **Slow storage** (a 4 KB write over 200 ms)? The data disk or NAS is the bottleneck: check the Proxmox storage.
5. **One request type is slow?** Download the Diagnostic Report and include it when asking for help.
6. **Worker or scheduler not reporting?** `sudo systemctl status personaldocs-worker personaldocs-scheduler`.

## Rollback {#rollback}

This release adds two database migrations (the measurement tables and one index). `personaldocs rollback` refuses
to switch back while the database contains migrations the previous release does not know, so reverse them first:

```
sudo personaldocs manage migrate library 0011   # drops the index doc_active_folder_idx (concurrently)
sudo personaldocs manage migrate core 0006      # drops the performance measurement tables
sudo personaldocs rollback
```

Only the measurements are lost; documents, history and settings are not touched. The performance settings stay
stored and are ignored by the previous release. Alternatively restore the pre-upgrade backup.
