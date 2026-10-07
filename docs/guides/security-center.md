# Security center

**Settings → Security** is for the main administrator and for accounts with the **Administrator** role (set in Settings → Family & access → Edit). It has these views: Overview, Antivirus, Security test, OS updates, Firewall, Security records, Storage and (main administrator) Access policy. None of these checks proves the system is free of vulnerabilities.

## Internet Ready {#internet-ready}

Set **Deployment exposure** to *LAN only* or *Published on the Internet*. An Internet-facing installation is reported as **Internet Ready** only when all of these pass for its public address (`PD_PUBLIC_ORIGIN`):

- the address uses HTTPS with a valid TLS certificate;
- plain HTTP redirects to HTTPS;
- session and CSRF cookies are Secure (and HttpOnly);
- security headers are present (X-Content-Type-Options, Referrer-Policy, CSP or X-Frame-Options);
- HSTS is sent (one year by default; `PD_HSTS_SECONDS` changes it).

A LAN-only installation may use plain HTTP but is never shown as Internet Ready. **Check HTTPS now** re-runs these checks; only your own public address is contacted.

## Basic Internet Security Test {#test}

**Run Security Test** runs only when an administrator starts it — never during install or upgrade. It is a baseline of **this application and this server**; it never scans other devices on your network. Categories:

| Category | Examples |
| --- | --- |
| HTTPS & TLS | the Internet Ready checks above |
| Framework & configuration | debug mode off, allowed host names, strong secret key, `manage.py check --deploy` |
| Authentication & access control | protected pages refuse anonymous access, a member cannot open another member's private document, administrators use two-step verification, failed sign-ins are blocked |
| Web baseline (OWASP-style) | no exposed `.env`/`.git`/settings files or path traversal, no open redirect, TRACE disabled, no permissive CORS, server version hidden |
| Upload security | ClamAV running with fresh signatures |
| Dependencies | `pip-audit` (install with `sudo personaldocs repair --with-security-tools`) and `npm audit` when available |
| Secrets & file permissions | no private keys or tokens in the application files; keys and documents not readable by other users |
| Host | firewall active, no unexpected listening services, ClamAV/PostgreSQL not exposed, reboot pending, security updates pending, service hardening |

Each finding shows **Passed / Warning / Failed**, a severity (Critical, High, Medium, Low), the affected check and how to fix it. Results are compared with the previous run (*new*, *persisting*, *resolved*) and kept for **one year**.

**Warning-only policy:** Critical and High findings never block anything — the site keeps working — but the result is clearly marked *Failed*, never described as a pass, stays in the history and puts Security Health at risk until resolved. Administrators are notified.

## OS security updates and reboot {#updates}

The **OS updates** view lists pending **Debian security updates** (checked through the root host helper; *Check for updates* refreshes the list). Personal DM never installs updates on its own.

**Install security updates…** first takes a **database and settings backup** (an application backup, not a Proxmox/LXC snapshot — take one on the host for a full rollback). If that backup fails, nothing is installed unless you tick *Install anyway without a backup* and give a reason; the override is audited. Only security updates are installed. Logs of every run are kept, and **Reboot required** is shown when packages need it.

**Reboot server…** lists what would be interrupted (signed-in sessions, OCR/antivirus/AI jobs), stops the worker and scheduler (the current job finishes first) and reboots. Duplicate reboot requests are refused. After the restart the page shows whether the database, worker, scheduler and antivirus are back. If the host helper is not installed, the page says so and shows the commands to run on the server (`sudo apt-get update && sudo apt-get upgrade && sudo reboot`).

The **host helper** is a small root service (`personaldocs-host.path`) installed by `personaldocs install/upgrade/repair`. It accepts only fixed actions: inspect, check updates, install security updates, update ClamAV signatures, repair antivirus (`antivirus_repair`, the fixed steps of [Diagnose / Repair](antivirus.md#repair)), reboot.

## Firewall monitoring {#firewall}

The **Firewall** view shows whether ufw or nftables is active, how many rules exist and which services listen on the network. Expected: SSH (22) and the Personal DM web port (8000, behind your proxy). ClamAV (3310) and PostgreSQL (5432) must listen on localhost only. Personal DM **only reports**; it has no control to enable or disable the firewall or open or close ports. Manage the firewall on the host, for example:

```bash
sudo apt-get install ufw
sudo ufw allow 22/tcp
sudo ufw allow from <proxy-ip> to any port 8000 proto tcp
sudo ufw enable
```

## Security Health score {#score}

The **Security Health** widget (administrators only, also on the Overview) shows a **score from 0 to 100** and a status: **Healthy** (90–100), **Attention** (70–89) or **At Risk** (below 70). Each item links to its page. The score is the sum of:

| Component | Points | Full points when |
| --- | --- | --- |
| Antivirus | 20 | ClamAV **Healthy**: reachable and a real scan succeeds, with current signatures (Degraded/stale 12, critically stale 5, off, **Unavailable** or **Error** 0) |
| HTTPS / TLS | 20 | Internet Ready (LAN only: 15) |
| Internet security test | 20 | passed within 90 days (warnings 12, High findings 5, Critical 0, never run 5) |
| Debian security updates | 15 | none pending (not checked 7, pending 5) |
| Firewall | 10 | active (not checked 5; inactive: LAN 5, Internet 0) |
| Reboot status | 10 | no reboot needed (required 3) |
| authentik | 5 | not used, or reachable (unreachable 1) |

It is a summary for your own installation, not an industry certification. **These conditions force At Risk regardless of the score**, and the reason is shown prominently: malware in quarantine (or a detected threat), failed HTTPS on an Internet-facing deployment, an inactive firewall on an Internet-facing deployment, critically stale antivirus definitions, unresolved Critical findings in the latest security test, and antivirus **Unavailable** or **Error** ("Antivirus is not scanning: …").

The antivirus state comes from what ClamAV does now: the daemon must answer **and** scan a small clean test buffer, and the last [self-test](antivirus.md#self-test) must have passed. Engine and signature versions cached from an earlier contact do not count. See [status and health states](antivirus.md#status).

## Security records: retention and purge {#retention}

Antivirus events, sign-in records and authentik events, security-test history, OS update and reboot records (with their logs) and security alerts are kept for **one year** (Security record retention, minimum 365 days) and then removed by the nightly maintenance.

To free disk space, **Security records** offers a **Cleanup analysis** first: chosen categories, the date limit, the number of records, the estimated space and the protected records. Purging needs confirmation. Records younger than 30 days cannot be purged; purging records younger than the retention period shows a warning. Always kept: the record of every purge (written after the deletion, so a purge never erases its own record), records about files still in quarantine and the latest security test. Original documents are never touched.

## Storage Health {#storage}

**Storage** shows total, used and free space and the share used by documents, previews and thumbnails, OCR copies, the database, log files, the antivirus quarantine, local pre-update backups and temporary files. **Storage warning at** (80 %) and **Storage critical at** (90 %) trigger notifications to administrators.

**Safe cleanup** only offers regenerable or expired data: temporary files older than 24 hours, previews/OCR copies of files that no longer exist, and security records past their retention. It shows the space each would free and asks for confirmation. **Original documents are never deleted** by any cleanup, purge, antivirus, update or maintenance workflow; quarantined files are handled only through the quarantine review; NAS backups are pruned only by the backup retention setting.
