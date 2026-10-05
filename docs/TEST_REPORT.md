# Test report

Date: 2026-10-03, updated 2026-10-05 (change set J). Revision: the branch head at the commit that adds this file.

## Environment actually used

| Item | Value |
|---|---|
| Host | Cloud development container: Ubuntu 24.04, 4 vCPU, 15 GB RAM, **not** Debian 13 and no systemd |
| Python | 3.13 (virtualenv) |
| PostgreSQL | 16.14 |
| Tesseract / OCRmyPDF | 5.3.4 / 15.2.0 (Ubuntu packages, run via `python3.12 -m ocrmypdf`) |
| LibreOffice | 24.2 (Writer/Calc/Impress) |
| Node / browser | Node 22, Chromium (Playwright 1.56) |

## Commands and results

| Command | Result |
|---|---|
| `scripts/verify.sh` (compile, `manage.py check`, `makemigrations --check`, settings reference, `bash -n` + shellcheck, pytest, `tsc` + `vite build`, repository hygiene) | **All passed** |
| `pytest` (`tests/`) | **232 passed**, 0 failed, 0 skipped (OCR and LibreOffice tests ran; 2026-10-05, change set J: `test_browsing_v3` 7, `test_ocr_quality` 6) |
| `scripts/ocr_benchmark.py` (11 synthetic samples, Tesseract 5.3.4 + osd) | Mean word F1 **0.58 → 0.97** (clean samples unchanged at 1.00; glare 0.00 → 0.70). Per-step table and rejected options in `docs/OCR_BENCHMARK.md` |
| `sudo bash tests/installer/test_personal_dm.sh` (one-line installer with stubbed `systemctl`, `apt-get`, `personaldocs` and a local git origin) | **18/18 passed**: refuses non-Debian-13 and no-systemd, upgrade before install fails without changes, fresh install clones and starts the guided installer, re-run idempotent, local edits never overwritten, upgrade → `personaldocs upgrade` + `doctor`, failing doctor reported, repair/doctor/status/backup delegate, restore validates and dry-runs, username and `--ref` validated, no secrets in the log. **Not run on a real Debian 13 machine**, and the public raw URL was not fetched (repository private) |
| `scripts/e2e.sh` (fresh database: `tests/e2e/flow.mjs` then `tests/e2e/a11y.mjs`) | **13/13 flow steps passed**; accessibility audit: **0 serious/critical violations** across 13 screens × 3 themes, document panel, share dialog and mobile layouts (`docs/a11y-report.json`) |
| `bash scripts/easy-install.sh --dry-run --yes` (answers file) and `scripts/proxmox-create-lxc.sh --dry-run` (piped answers, NAS modes 1 and 2) | Questions, validation, summary and the full command sequence printed; nothing changed on the system. **Not executed for real** (no Proxmox/Debian 13) |
| Guided install in a **Debian 13 (trixie) chroot** (debootstrap; `systemctl` replaced by a test stand-in because a chroot has no PID 1 systemd): `git clone -b <branch>` → `bash scripts/easy-install.sh --yes` → `git pull` + re-run → `personaldocs upgrade` | Found and fixed two installer bugs (a bare `[ -f token ] && …` aborting the install without a token file; virtualenv scripts pointing at a renamed `.tmp` build directory so gunicorn could not start). After the fixes: packages, PostgreSQL 17, release + frontend build, migrations, services, settings, `status`, `doctor` and the setup code all OK; the setup code was accepted over HTTP; re-run and upgrade OK. NAS mounting and the nftables rule were not exercised (chroot) |
| Locale robustness in a fresh Debian 13 chroot, run with **no UTF-8 locale** (`LANG=C`, as from the Proxmox console / `pct enter`) and with an **uninstalled SSH-forwarded locale** (`LANG=en_US.UTF-8 LC_CTYPE=UTF-8`) | Reproduced the field failure (`createdb: new encoding (UTF8) is incompatible with ... SQL_ASCII`) with the previous code; after the fix the install completes on an SQL_ASCII cluster (database created UTF-8 from template0) and on a host where the cluster was never created (created as UTF-8). Services run with `LANG=C.UTF-8`. `personaldocs repair` recreated a dropped database. The browser flow `tests/e2e/flow.mjs` against that installed instance: **13/13 passed** (setup, sign-in, upload + worker OCR, search, settings, themes, help) |
| Service start under a **real systemd** (Debian 13 booted with `systemd-nspawn`) after the field failure `226/NAMESPACE` (LXC without nesting) | Isolation supported: full guided install, `10-hardening.conf` drop-in active (`ProtectSystem=full`, `PrivateTmp=yes`), all services active, browser flow **13/13 passed**. Isolation unavailable (probe forced to fail): `personaldocs repair` removed the drop-in, warned how to enable nesting, all services active and healthy. The firewall fallback was exercised for real (nftables not permitted in the test container → warning, install continued). The AppArmor denial itself could not be recreated outside Proxmox |
| `tests/test_nas.py` (NAS from Settings with a simulated `systemctl`) | Injection attempts rejected, mount units/credentials rendered, request → helper → destination adopted, failure hints, unmount, permissions |
| Change set 2026-10 (`tests/test_security.py` 30, `test_ai.py` 15, `test_passkeys.py` 14, `test_photos.py` 9, extended `test_ops.py` backup round trip) | Trusted-proxy IP parsing and spoofing, login audit and flags, synthetic MaxMind DB (`tests/mmdb_writer.py`), allow/block list, precedence, temporary access, lock-out protection, console recovery, alerts, traffic log/report; AI against a fake OpenAI/Ollama server that records prompts (`tests/fake_ai_server.py`) proving unpermitted documents are never sent; passkeys with a real cryptographic software authenticator (`tests/soft_authenticator.py`). **All passed** |
| `npx vitest run` (frontend) | **17 passed**: `?next=` open-redirect guard, viewer zoom steps/fit maths, offline file types, folder view/sort preference, desktop folder walk (nested folders, empty folders, fallback without the entries API) |
| `tests/e2e/parity.mjs` (via `scripts/e2e.sh`, fresh database; change set J) | **31/31 passed**. New: own library first and expanded, other areas collapsed (AT-92); folder and row menus fully visible above every panel (checked with `elementFromPoint`), inside the viewport also at the bottom edge, one at a time, outside click, keyboard open/arrows/Escape with focus returned (AT-85); rename and archive with confirmation and audit entry (AT-86); new sub-folder gets 📁, icon picker, reset to default (AT-87/88); Details view sorting by column, view and sort followed to a second session, empty state (AT-89); two files dropped with a synthetic DataTransfer uploaded with the progress card (AT-90); OCR confidence badge and Re-run OCR with rotation (AT-93/94). Earlier checks: | own-area label; file-type icons (list, grid); drag and drop of documents (chip and tree) and folders, refused drop into own sub-folder; Move to… (desktop, phone portrait, phone landscape by touch); PDF viewer (zoom steps, %, fit page/width, 100%, pages, keyboard, resize, stored file unchanged); image viewer (PNG/JPEG/WebP aspect ratio, scrolling); damaged PDF, anonymous preview refused, no requests to other sites; dashboard widgets + order; notification matrix; backup frequency fields; import into a chosen sub-folder with the exact final tree; 22 screens without horizontal overflow at 820×1180, 390×844, 844×390; viewer controls reachable and ≥ 24 px; preferences synced desktop ↔ phone; no page errors |
| `tests/e2e/a11y.mjs` (extended: notifications matrix, widgets, security, AI, login audit, import, full-page viewer, Move to dialog, open actions menu, Details view) | **0 serious/critical** violations in 3 themes; found and fixed in change set J: keyboard-opened menus did not move focus into the menu (found and fixed: nested interactive document rows, unfocusable viewer scroll area, low-contrast label) |
| `scripts/privacy_check.sh --history` | **OK**: no tracked secret/data files, no credential patterns in tree or history, no AI assistant as author, all README/doc links and images resolve |
| `npm audit --omit=dev` | **0 vulnerabilities** after upgrading PDF.js 5.7 → 6.4.299 (high: script execution from a malicious PDF) and React Router 6 → 7.18 (open redirect) |
| veraPDF 1.30.2 on OCRmyPDF output (`tests/test_pdfa.py`) | PDF/A-2b **compliant**; plain PDFs correctly rejected |

The end-to-end flow covers: the setup wizard creating six accounts, sign-in, uploading a synthetic image-only "passport" scan, OCR, dashboard, the three-panel browser with PDF preview, confirming suggested dates (generated name "Sam Sample Passport (2016–2026)"), search, admin notification and family settings, switching to the blue theme, bundled help, and a second user on a mobile viewport (forced password change, independent green theme, no horizontal overflow, manifest checks). It also asserts there are no uncaught page errors.

Screenshots of the real application with synthetic data are in `docs/screenshots/`.

## Processing measurement (indicative)

12 synthetic single-page PDFs (6 image-only scans, 6 born-digital), heavy-job concurrency 1, `OMP_THREAD_LIMIT=1`:

```
processing 8.1 s total (0.68 s/document), peak converter RSS 74 MB, worker RSS 95 MB
storage: originals 448 KB, derivatives 696 KB (searchable PDF/A + thumbnails ≈ 1.5× originals for small scans)
```

This ran on a 4 vCPU / 15 GB host, so it does **not** prove the 2 vCPU / 4 GB target. Multi-page scans and large Office files will take much longer. Re-run `scripts/bench_processing.py` on the real LXC (see Pending).

## Not tested / pending (with reproducible steps)

| Item | Why | How to validate |
|---|---|---|
| AT-26 install, upgrade, rollback and repair on Debian 13 | No Debian 13 LXC with systemd available | Create a fresh Debian 13 LXC (2 vCPU / 4 GB, nesting on). Follow `guides/installation.md`. Interrupt the install (Ctrl-C during packages) and rerun. Tag v0.1.1 and run `personaldocs upgrade --ref v0.1.1`, then `personaldocs rollback`, then `personaldocs repair`. Check `status`/`doctor` after each step. |
| Private update flow (AT-30) | Same | As above, using a fine-grained read-only token in `/etc/personaldocs/github-token`; confirm the token never appears in `/var/log/personaldocs/install.log` or `ps` output |
| Guided installers and real NAS mounting | No Proxmox host or NAS | On the Proxmox host run `bash proxmox-create-lxc.sh --dry-run`, then for real with NAS mode 1; in the app use Settings → Storage & backup → *Connect NAS* with an NFS export and then an SMB share; confirm `/mnt/pdnas/personaldocs` holds the backup and `ps`/logs never show the token or SMB password. Repeat with NAS mode 2 (unprivileged + host bind mount) |
| Restore into a clean LXC (AT-24) | Same | Back up on server A, install on server B, `personaldocs restore <dir>`; verify sign-in, permissions, document versions, SMTP password still decrypts |
| Real SMTP / Telegram delivery (AT-17) | No provider credentials | Configure in Settings → Connections, use *Send test* buttons, then *Run reminder check now* with a document expiring in 7 days |
| Real IMAP mailbox (AT-19) | No mailbox credentials | Add a test mailbox (e.g. a local Dovecot or an app-password Gmail account), send a matching attachment, *Check now* twice and confirm a single import |
| Live Google sign-in (AT-21) | No Google Cloud project | Follow `guides/google.md`, link an account, sign in through Google, unlink |
| Real-device PWA (AT-14) | No physical devices | Install on Android Chrome and iOS Safari; test camera upload, share-in (Android) and share-out; record results |
| Browser offline behaviour (AT-15) | Not automated | Save a document offline, go offline (DevTools), open it; sign out and in as another user (not listed); revoke access, reconnect, confirm removal |
| Resource-constrained load and disk-full (AT-27) | Host differs | On the LXC run `scripts/bench_processing.py` with `N=200` (instructions in the file header) while watching `free`/`top`; fill the disk to <512 MB free and confirm uploads are refused with a clear message |
| Real client IP through NPM/Pangolin (AT-39/41) | No reverse proxy here | Set `PD_TRUSTED_PROXY_IPS` to the proxy address; sign in via the public URL; Settings → Security & access → *Your connection* shows your public IP and "via trusted proxy"; Login audit shows it |
| MaxMind GeoIP download (AT-40/49) | No MaxMind credentials | Enter account ID + license key, *Update now*; *Test an address* with a known public IP; then enter a wrong key and confirm the old database stays active |
| Country policy on the real proxy (AT-42..45, AT-50) | Same | Allow list with your country, check a foreign VPN exit gets "Access not allowed"; add temporary access; recover with `sudo personaldocs access-policy off` from `pct enter` |
| GoAccess report on the LXC (AT-47) | Tested with goaccess 1.8.1 on the build host only | Enable traffic analytics, wait for the hourly job (or `manage.py shell` → enqueue `goaccess_report`), open Activity → Traffic analytics |
| Local AI with LM Studio / Ollama (AT-31..36) | No AI server | Follow `guides/local-ai.md#lm-studio`, *Test connection*, *Analyse again* on a document, ask the assistant, *Rebuild semantic index*; stop the server and confirm uploads/OCR/search still work |
| Passkeys and TOTP autofill on real clients | No devices | On the HTTPS origin: add passkeys on iPhone, Android, Windows Hello and a password manager; sign in with password+passkey and passwordless; confirm Bitwarden/1Password fill the TOTP field |
| Installed PWA and touch on real phones/tablets (AT-76, AT-83) | Emulated viewports only | Install on Android and iOS; repeat parity checks by hand: Move to…, viewer toolbar swipe/pinch, notification matrix, import |
| New notification templates in a real inbox/Telegram (AT-69) | No credentials | Configure SMTP/Telegram, upload two files into another member's folder, check one summary arrives with names masked |
| Weekly/monthly backups on the LXC (AT-71) | No NAS here | Set weekly for tomorrow's day, confirm the run, the next-run display and retention |
| Screen-reader review | Automated audit only | Walk through setup, upload and settings with NVDA/VoiceOver |
| One-line installer on real Debian 13 (AT-98/99) | No Debian 13 VM with systemd; repository private so the raw URL needs authentication | Make the repository public (owner decision) or use a checkout. On a fresh Debian 13 VM run the one-liner, answer the questions, then `-- status`, `-- doctor`, `-- backup`, `-- upgrade`, and `-- restore DIR --dry-run`; check `/var/log/personaldocs/personal-DM.log` contains no token |
| Real desktop drag of folders (AT-90/91) | Synthetic DataTransfer only | Drag a nested folder from Windows Explorer into Chrome/Edge, from Finder into Safari/Chrome, and from a Linux file manager into Firefox; confirm the tree under the drop target and the progress card |
| OCR on real phone photos | Synthetic benchmark only (no real IDs may be used) | Photograph a non-sensitive printed test card (e.g. the synthetic samples printed on paper) sideways and upside down; check the Text tab confidence, the suggested fields and *Re-run OCR* |
