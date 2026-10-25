# Test report

Date: 2026-10-03, updated 2026-10-06 (change sets K and L), 2026-10-07 (change sets M, N, O and P) and 2026-10-08 (change sets Q and R) 2026-10-09 (change set S) and 2026-10-11 (change set T). Revision: the branch head at the commit that adds this file.

## Environment actually used

| Item | Value |
|---|---|
| Host | Cloud development container: Ubuntu 24.04, 4 vCPU, 15 GB RAM, **not** Debian 13 and no systemd |
| Python | 3.13 (virtualenv) |
| PostgreSQL | 16.14 |
| Tesseract / OCRmyPDF | 5.3.4 / 15.2.0 (Ubuntu packages, run via `python3.12 -m ocrmypdf`) |
| LibreOffice | 24.2 (Writer/Calc/Impress) |
| Node / browser | Node 22, Chromium (Playwright 1.56) |
| PaddleOCR (change set Q) | PaddlePaddle 3.2.2, PaddleOCR 3.7.0, PaddleX 3.7.2 in a separate Python 3.13 virtualenv; PP-OCRv5 mobile detection and en/arabic/devanagari/te/ta recognition models, PP-LCNet document-orientation model; CPU with AVX, no GPU |
| ClamAV (change sets M and P) | 1.5.4 daemon in the development container, used only by `tests/test_antivirus_live.py` and by running the change set P diagnosis tool against it. Debian 13 ClamAV packaging (`clamav-daemon` / `clamav-freshclam` 1.4.3+dfsg-1) was checked from the package unit files and reproduced by a simulated host in `tests/test_auth_password_clamav.py`; no real Debian 13 systemd host was available |

## Commands and results

| Command | Result |
|---|---|
| `scripts/verify.sh` (compile, `manage.py check`, `makemigrations --check`, settings reference, `bash -n` + shellcheck, pytest, `tsc` + `vite build`, repository hygiene) | **All passed** |
| `pytest` (`tests/`) | **232 passed**, 0 failed, 0 skipped (OCR and LibreOffice tests ran; 2026-10-05, change set J: `test_browsing_v3` 7, `test_ocr_quality` 6) |
| Change sets K and L (`tests/test_selective_ocr.py` 11, `tests/test_overview.py` 15, `tests/test_family_setup.py`; full `pytest tests` run on 2026-10-06) | **All passed**; full backend suite: 264 tests passed (`scripts/verify.sh`, which also ran the 18 stubbed installer checks, 17 frontend unit tests, type check, build and privacy check). Selective OCR policy, custom/archived types (409 for built-in or in-use types), source and page selection, front and back as one job, primary source, Remove OCR data and search, re-runs keep confirmed values, English/Arabic/Hindi with missing packs reported, states, review queue permissions, limits, cancel and pause, AI only for permitted types; Overview widgets, layout limits and styles, Gregorian/Hijri in the installation timezone, calendar, Saudi and Indian holidays with status and source, countries and corrections, weather off by default and against a **fake local weather server** (cache, stale, unavailable), sign-in presets, wallpaper upload/rejections/removal, identical sign-in methods; setup with only the Main Administrator, optional members, members added later, earlier six-account installations kept, deactivation keeps documents (DELETE 405) |
| Change set S (2026-10-09: `tests/test_offline_sync.py` 9, `tests/test_pwa_identity.py` 4; browser `offline.mjs` 9, `pwa.mjs` 4, `themes.mjs` 6, `screenshots.mjs` 5; accessibility audit in 6 themes) | Full backend suite: **all passed** (about 380 passed, 5 skipped live tests, 0 failed). Final `scripts/e2e.sh` from a fresh database: flow 14, accessibility **no serious or critical violations in Default Green, Blue, Dark, Glass Light, Glass Dark and Black & White**, parity, layout **25 PASS, 0 FAIL**, offline **9/9**, PWA **4/4**, themes **6/6**. The screenshot step first failed on false positives of its own privacy gate (a deliberately long synthetic file name); after fixing the rule (and the Overview circle widget and two capture states found by reviewing the images), flow + parity + layout + screenshots were run again from a fresh database: **94 PASS, 0 FAIL** (layout 25/25, screenshots 5/5). Defects found and fixed by these tests and the image review: Overview *circle* widget stretched into an oval; Offline page cards squeezed at 390–430 px (layout audit); manifest served as `application/octet-stream`; offline text cache re-created after sign-out by a still-running sync; theme colour applied late on reload |
| Change set R (`tests/e2e/layout.mjs`, AT-231…AT-245; 2026-10-08) | **25 PASS, 0 FAIL**, 0 layout defects. 27 screens × 7 viewports (1920×1080, 1440×900, 1366×768, 1180×820, 820×1180, 430×932, 390×844); header geometry baseline written and reviewed. Run against the unfixed build: **137 defects, 24 of 25 steps failed**. Full browser suite: flow + accessibility + parity **89 PASS, 0 FAIL**, no serious or critical accessibility violations |
| Change set Q (`tests/test_ocr_engines_lifecycle.py` 21 incl. 3 live, AT-211…AT-230; 2026-10-08) | **All 21 passed**: 18 via the fake worker protocol, and **3 live against the real PP-OCRv5 runtime** (self-test + document run, Arabic + English, Hindi + English upright). Full backend suite: **372 passed**, 0 failed, 0 skipped (live PP-OCRv5 tests included). `manage.py doctor` with the real runtime: all OCR checks OK, including the inference self-test ("PERSONAL DOCUMENTS OCR SELF TEST 2027" read in 2.6–3.8 s) |
| `scripts/ocr_engine_benchmark.py` (21 synthetic samples, PP-OCRv5 mobile vs Tesseract 5.3.4; 2026-10-08) | PP-OCRv5 mean character accuracy **98.8 %** vs Tesseract **93.7 %**; English word F1 1.00 vs 0.97; 5.7 vs 2.6 s/page; peak child RSS 1.9 GB vs 0.5 GB. A first run with text-line orientation on read Hindi + English at 20 % (every line flipped), so that option now defaults to off. Real-document categories: **Not Run**. See [benchmark](OCR_BENCHMARK.md#engines) |
| `scripts/e2e.sh` (2026-10-08, change set Q, **with the real PP-OCRv5 runtime**: browser flow, accessibility audit, parity checks) | **64 PASS, 0 FAIL** (no serious or critical accessibility violations). New steps: *AT-213/217/218 OCR engine label, Remove OCR data and Disable OCR for this document* and *AT-211/221/225/226 OCR engines (real self-test), Existing OCR data, orphans and Test OCR / Compare engines*; the selective OCR step now checks the PP-OCRv5 default and its profiles. Found and fixed: the ⋮ menu closed when a long menu itself scrolled. Also run **without** the PaddleOCR runtime (as in CI): **64 PASS, 0 FAIL**, after fixing the Run OCR dialog, which sent the default engine explicitly and so disabled the Tesseract fallback |
| Change set P (`tests/test_auth_password_clamav.py` 18, AT-196…AT-210; `tests/test_antivirus_live.py`; 2026-10-07) | **All 18 passed**; live ClamAV tests **passed** against a real clamd 1.5.4; earlier tests updated (passkey policy in `test_passkeys.py`, the HTML password reset email in `test_auth.py`, the account-locked alert in `test_security.py`); full backend suite: **350 passed** (fresh test database, including the live ClamAV tests). Covered with a software WebAuthn authenticator, mocked SMTP and a **simulated Debian 13 host** (fake `systemctl`, `dpkg`, `clamconf`, `freshclam`, `runuser` and a fake clamd on the socket): Sign in with Passkey offered before the password, passwordless without username or password (user verification required, replay refused), both passkey modes and main administrator recovery, audited passkey management, temporary password shown once / hash only / never sent / forced change / sessions ended, branded single-use expiring reset email never stored in the outbox, Main Administrator protection, security templates with protected mandatory text, account-locked and link events, the missing-socket / LocalSocket-mismatch state and the skipped-start-condition state diagnosed by cause and not by cached metadata, repair (clamd.conf, drop-in, tmpfiles, unit order, idempotency, service-account access, self-test), the host-helper action, persistence configuration, clean + EICAR self-test without artifacts, admin-only endpoints, upload/quarantine after repair, Security Health from the operational state |
| `scripts/e2e.sh` (2026-10-07, change set P: browser flow, accessibility audit, parity checks) | **62 PASS, 0 FAIL** (no serious or critical accessibility violations). New steps: *AT-196 Sign in with Passkey on the first sign-in screen*, *AT-200/201 administrator resets a password: temporary password shown once* and *AT-205..207 antivirus: Diagnose / Repair panel and clean + EICAR self-test*. New screenshots: `login-passkey.png`, `admin-reset-password.png`, `security-antivirus-diagnose.png` |
| Change set O (`tests/test_rich_notifications.py` 19, AT-176…AT-193 and AT-195; 2026-10-07) | **All 19 passed**; the affected earlier suites (expiry, events, notification policy, security, antivirus, passkeys, auth, security center, document types, authentik): **125 passed** after the change; full backend suite: **331 passed** (330 in the full run plus the live ClamAV test re-run once the local daemon was started). Covered with mocked SMTP, Telegram and push service: one event rendered for every channel, multipart email (no scripts, images or tracking, `dir="auto"`), Telegram HTML with escaping, buttons only on https and plain-text fallback, Notification Center filters, unread and cursor, critical notifications kept, push payload encrypted (decrypted with the subscriber key in the test) with lock-screen privacy and an endpoint allowlist (`http://`, `127.0.0.1`, unknown hosts and URLs with credentials refused), event-specific actions, quarantine release never in a message, Template Manager, injection payloads (`<script>`, `<img onerror>`, Markdown, Telegram markup) escaped, previews and TEST sends (only the audit entry `notifications.test_sent`), critical never below Warning, repeat cooldown, Unicode/RTL/time zone/date format, delivery history states with redacted errors, document type and masked document number, security event severity and audience, links never granting access, existing configuration kept by the migration |
| `scripts/e2e.sh` (2026-10-07, change set O: browser flow, accessibility audit, parity checks) | **59 PASS, 0 FAIL**. New steps: *AT-176..186 rich notifications: TEST messages, Notification Center, banners, template manager* (desktop) and `AT-194 <viewport>: Notification Center cards, filters and actions by touch without clipping` for tablet, mobile-portrait and mobile-landscape; `/notifications` and `/settings/notifications` in the overflow route list and the accessibility audit. Screenshots regenerated: `notification-center.png`, `notification-banner.png`, `notification-template-email.png`, `notification-template-telegram.png`, `mobile-notifications.png` |
| Change set N (`tests/test_document_types.py` 16, AT-161…AT-174; 2026-10-07) | **All 16 passed**; full backend suite: **312 passed**. Covered: an untyped document with OCR details can be typed and keeps its type after a reload (the original defect), folder and type independent, type administration with delete refused while in use and reassignment (the older `DELETE /api/metadata/type/<id>` no longer untypes documents), template fields configuring the Details panel, the Passport template and value validation, folder suggested type as a suggestion only, OCR type suggestion with Accept / Change / Ignore and the confirmed type kept, value provenance and protection of confirmed values, type change with kept / previous / new fields and map / keep / remove, expiry role lost stops reminders only after review, re-map of existing OCR text without a new scan, one-off details and administrator-only promotion, permissions (viewer, editor, main administrator, no access → 404, bulk skips documents the person may not edit), search / OCR review type filter / expiry-role reminders with per-type reminder days, and the migration (no data lost, untyped documents not guessed, report counts). Not covered by a dedicated test: the bulk skip of documents with another confirmed type and the bulk preview counts |
| `scripts/e2e.sh` (2026-10-07, change set N: browser flow, accessibility audit, parity checks) | **55 PASS, 0 FAIL**. New steps: *AT-161..175 document types: set from Details, suggestion, safe change, custom detail, templates* (desktop) and `AT-175 <viewport>: Details, type selection and previous values work by touch without clipping` for tablet, mobile-portrait and mobile-landscape. The accessibility audit now includes `/settings/documents`: no serious or critical violations. In one earlier run with the local ClamAV daemon stopped, two desktop drag/move parity steps failed; they passed again in the full rerun with the daemon running, which is the result reported here |
| Change set M (`tests/test_antivirus.py` 9, `tests/test_antivirus_live.py` 1, `tests/test_authentik.py` 5, `tests/test_security_center.py` 17; 2026-10-07) | **All passed**; full backend suite: **296 passed** tests. Antivirus against the local fake clamd (`tests/fake_clamd.py`) with the EICAR test string: background scan with the file usable at once, ClamAV unavailable → Not scanned with alert, quarantine blocks preview/download/share/export/OCR/AI, release only by the main administrator with confirmation and reason, signature age, Update now and stale alerts, size limit, member vs administrator views, library scan with pause/resume/cancel and schedule, originals never deleted. **Live:** `test_antivirus_live` ran against a real ClamAV 1.5.4 daemon in the development container (EICAR detected and quarantined, a clean file clean); it is skipped where no clamd runs. authentik against a local fake OIDC provider (`tests/fake_oidc.py`) with real RS256 ID tokens and PKCE: sign-in button and local fallback, token checks, no linking by email, explicit links, provisioning and group mapping, connection test. Security center with stubbed HTTPS responses and stubbed host commands: Internet Ready, manual baseline test limited to application and host, access-control leak reported Critical, warning-only policy, comparison and one-year history, OS updates with logs, pre-update backup and override, reboot safeguards, firewall monitoring without controls, Security Health score and forcing conditions, record retention and purge, Storage Health and safe cleanup, no workflow deletes originals |
| `scripts/e2e.sh` (2026-10-07, fresh database: browser flow, accessibility audit, parity checks) | **51 PASS, 0 FAIL**. New steps: AT-138/140/141 antivirus background scan, quarantine and release with the EICAR test string; AT-149/150/156/159 security center overview with the health score, Internet security test, storage, and the OS updates, firewall (no firewall controls) and security records views; AT-146 authentik settings and the sign-in button. The accessibility audit now includes the security center views |
| `scripts/e2e.sh` (2026-10-06, fresh database: browser flow, accessibility audit, parity checks at desktop, tablet and phone) | **48 PASS, 0 FAIL**. New steps: AT-101/106/112 selective OCR (Manual by default, chosen pages and languages, review queue); AT-116…121/125/127 Overview customize, weather city with a fake local provider, calendar and holidays; AT-123/124 holiday countries and corrections in settings; AT-128/130 all five sign-in designs at desktop and phone with the same sign-in methods. Accessibility audit now includes `/ocr-review` and `/settings/overview`: 0 blocking violations in 3 themes |
| `scripts/ocr_benchmark.py` (12 synthetic samples, Tesseract 5.3.4 + osd) | Mean word F1 **0.61 → 0.97** (clean samples unchanged at 1.00; glare 0.00 → 0.70). Change set K: the contrast stretch no longer clips sparse ink; a regression sample with less than 1 % ink was added. Per-step table and rejected options in `docs/OCR_BENCHMARK.md` |
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

The end-to-end flow covers: the setup wizard creating the Main Administrator (demo label A. Ansari) and then, in the optional step, the demo members Mom, Son1, Son2, Son3 and Daughter (demo labels for the screenshots, never created automatically), sign-in, uploading a synthetic image-only "passport" scan, checking that nothing is recognised until OCR is run manually (the passport type is Manual), running OCR, the Overview with date, holidays and the recent document, the three-panel browser with PDF preview, confirming suggested dates (generated name "Son1 Passport (2016–2026)"), search, admin notification and family settings, switching to the blue theme, bundled help, and a second user on a mobile viewport (forced password change, independent green theme, no horizontal overflow, manifest checks). It also asserts there are no uncaught page errors.

Screenshots of the real application with synthetic data are in `docs/screenshots/`.

## Follow-up: cards and tiles fit at every width and browser zoom {#layout-zoom}

Reported: the Clear Safe Caches card on Settings → Maintenance & Operations cut off its five-column table at the card
edge. Root cause: wide tables inside narrow grid cards, hidden by `overflow-x: auto` on the card (the content scrolled
inside the card instead of fitting it). The layout audit did not look inside cards and did not cover
`/settings/system` or Active Sessions.

| Check | Result |
|---|---|
| `tests/e2e/layout.mjs` with the new **clipped** check (content wider than its card or tile), the two new screens and six browser zoom levels (50, 67, 125, 150, 200, 300 % of 1440×900), first run before fixing | **27 PASS, 4 FAIL**: Active Sessions table 229 px wider than its card at 820 px and 109 px at 150 % zoom; Family members table 87 px at 820 px; Offline "Manage storage" 14/54 px on 430/390 px phones (long button label). Maintenance page already fitted after the Clear Safe Caches rewrite |
| Same suite after the fixes (fresh database; flow.mjs, then layout.mjs; 29 screens × 7 viewports + 6 zoom levels) | **31 PASS, 0 FAIL**, 0 layout defects; header geometry baseline unchanged |
| Full-page screenshots of Maintenance, Active Sessions and Family at 1920 px, 125 % and 200 % zoom and 820 px, reviewed by eye | Clear Safe Caches spans the row as a stacked list; key/value tables stack label over value in narrow cards; session rows stack at tablet width |
| `npx tsc --noEmit`, `npm run build`, `npx vitest run` | clean, built, 17 passed |

## Change set AB: Maintenance & Operations in the web interface, Active Sessions {#change-set-ab}

**Numbering.** Prompt AT-456…AT-475 → **AT-481…AT-500** (the prompt's numbers are taken). Per-scenario status:
[TRACEABILITY.md](TRACEABILITY.md#change-set-ab). Design: [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-ab).

**Environment.** Development container (Ubuntu 24.04, PostgreSQL 16, Python 3.13, Node 22, Chromium via Playwright, jq,
shellcheck), 2026-10-25. No Debian 13 host, no systemd. Root operations ran through the **real** host helper
(`host_helper.py`) and the **real** CLI progress functions (`step`/`meta`/`die` from `scripts/personaldocs`) with a
scripted `personaldocs` command (`_fake_cli` in the tests, `tests/e2e/maint_helper.py` in the browser tests); the
Debian packaging work of a real upgrade, rollback, repair or service restart was **not** performed. GeoIP city
results were emulated. All data is synthetic.

| Command | Result |
|---|---|
| `pytest tests/test_change_ab.py` | **38 passed** (AT-481…AT-500 backend scenarios, CLI progress protocol, shellcheck, health/system info/caches) |
| Final: `pytest tests/test_change_ab.py tests/test_ops.py tests/test_corrective_v.py tests/test_sessions.py tests/test_overview.py tests/test_rich_notifications.py` (after the screenshots) | **128 passed, 0 failed** — incl. the documentation checker; earlier in this change: `test_signin_security`, `test_security`, `test_change_aa`, `test_templates` passed (sessions, sign-in security, Trusted Zones, tooltips/help, docs checker, Overview layouts, notifications) |
| Full `pytest` (run before the final screenshots and report existed) | **655 tests: 647 passed, 6 skipped (ClamAV daemon, real PaddleOCR/light-ocr runtimes), 2 failed**: `test_at309_backup_health_from_verified_state_admin_only` — container disk about 10 % free, fails identically on `main` (environmental); `test_at332_at334_documentation_checker_passes` — failed only because the Change Set AB screenshots were not captured yet; passes after capture (re-run below) |
| `scripts/e2e.sh` (fresh database `e2e_ab`) | flow, accessibility, parity, layout, offline, PWA, themes, recovery: all PASS; corrective: 38 PASS, 1 FAIL — the new AB step failed on a **test selector** (the step-up "Confirm" locator also matched "Confirm and repair"); everything before it (Doctor, Check for Updates, successful and failed upgrade, relogin, concurrency) had passed |
| Corrective AB step re-run (`E2E_ONLY="Change Set AB"`, same database) after the selector fixes | **PASS** *AT-481…AT-500 Change Set AB*: family member refused; Doctor via the UI with grouped results; Check for Updates; Update Application with confirmation, step-up, live steps and Succeeded; the same job and steps after a new sign-in; forced failed backup → *Existing Version Remains Operational*, Technical Details and Full Log; second system operation refused (409); repair of a deleted data directory: plan → confirm with step-up → repaired and verified; Job History filter; Active Sessions tile → View All → details → **Terminate Session** (that browser refused at once, the administrator's session unaffected); the tile resized to large and kept after reload |
| Screenshot step re-run (`E2E_ONLY="Change Set AB"`) | **PASS** *AT-499*: 9 captures with the quality and privacy gates (maintenance-operations, upgrade running, upgrade failed with Technical Details, Doctor, Repair Plan, Job History, Active Sessions tile, page, details) |
| Migrations `ops.0004`, `accounts.0010`, `core.0009` forwards, backwards (`core 0008`, `accounts 0009`, `ops 0003`), forwards; `makemigrations --check` | OK |
| `shellcheck -S error scripts/personaldocs`; `manage.py doctor` (sections, NOT CONFIGURED/NOT APPLICABLE) | Passed |
| `npm run build`, `tsc`, `vitest` (17), `scripts/check_docs.py`, `scripts/privacy_check.sh`, settings reference | Passed |

| ID (prompt) | Result |
|---|---|
| AT-481 (456) Permissions | PASS |
| AT-482 (457) Durable jobs | PASS (refresh, relogin, app restart simulated by a new process state; scheduler sync) |
| AT-483 (458) Error visibility | PASS |
| AT-484 (459) Secret redaction and anonymized report | PASS |
| AT-485 (460) Doctor | PASS |
| AT-486 (461) Repair plan | PASS (repair action by the scripted CLI) |
| AT-487 (462) Update check | PASS (scripted CLI); a real `git fetch` from a source: NOT EXECUTED |
| AT-488 (463) Successful WebGUI upgrade | **BLOCKED** — no safe Debian 13 test host in this environment; the orchestration (steps, backup, report, notification, reconnect polling) passed with the scripted CLI |
| AT-489 (464) Upgrade failure | PASS |
| AT-490 (465) Rollback safety | PASS (CLI branches and outcomes; a real rollback on a host: NOT EXECUTED) |
| AT-491 (466) Restart | PASS (scripted CLI; a real systemd restart: NOT EXECUTED) |
| AT-492 (467) Concurrency | PASS |
| AT-493 (468) Active vs Signed In | PASS |
| AT-494 (469) Active Sessions tile | PASS |
| AT-495 (470) Dashboard integration | PASS |
| AT-496 (471) Location/trust | PASS (GeoIP emulated) |
| AT-497 (472) Full Active Sessions | PASS |
| AT-498 (473) Terminate Session | PASS |
| AT-499 (474) Guides/help | PASS |
| AT-500 (475) Release gate | PASS with the exceptions recorded above (AT-488 BLOCKED; environmental `test_at309`) |

## Change set AA: direct Local AI processing, Overview groups and free resize, Document Type field management {#change-set-aa}

**Numbering.** Prompt AT-436…AT-455 → **AT-461…AT-480** (the prompt's "Change Set X" name and numbers are taken).
Per-scenario status: [TRACEABILITY.md](TRACEABILITY.md#change-set-aa). Design and decisions:
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-aa).

**Environment.** Development container (Ubuntu 24.04, PostgreSQL 16, Python 3.13, Tesseract 5, pdftoppm, Node 22,
Chromium via Playwright), 2026-10-25. The Local AI server is emulated by `tests/fake_ai_server.py` (OpenAI-compatible
chat API with `image_url` parts — the request LM Studio receives — plus scripted vision, multi-page and failure
answers). The OCR fallback used the real Tesseract. All files are generated synthetic samples.

| Command | Result |
|---|---|
| `pytest tests/test_change_aa.py` | **21 passed** (AT-461…AT-480, incl. the real Tesseract fallback) |
| `pytest tests/test_ai_intelligence.py tests/test_ai.py tests/test_ai_pipeline.py tests/test_document_types.py tests/test_overview.py tests/test_preferences.py tests/test_corrective_v.py` | Passed (Change Set Y/Z AI behaviour, document types, Overview, help registry unchanged) |
| Full `pytest` | **620 tests: 613 passed, 6 skipped (ClamAV daemon, real PaddleOCR runtime, live light-ocr), 1 failed in this container only**: `test_at309_backup_health_from_verified_state_admin_only` — the container disk has about 10 % free space, so the test backup destination is rated critical ("only 10.0 % free space"); it fails the same way on unmodified `main` and passed when run alone after freeing space. Not caused by this change set. |
| `scripts/e2e.sh` (fresh database) | flow, accessibility, parity, layout (7 viewports), offline, PWA, themes, recovery, corrective and screenshot suites: **163 PASS** incl. the new step *AT-461…AT-480 Change Set AA* (field drag with the mouse and with the keyboard, Archive → Archived Fields → permanent-delete dialog guarded → Restore, Overview group created and a tile moved into it, corner-handle resize persisted after reload, no overlapping tiles, other account unaffected, phone 390 px one column without sideways scrolling and the desktop layout unchanged, Reset Layout, default processing source); **1 FAIL in this container only**: AT-333 (Chromium here cannot load the real OpenFreeMap tiles through the container proxy certificate — unchanged, same as Change Sets Y and Z) |
| Migrations `library.0013` + `ai.0004` forwards, backwards (`library 0012`, `ai 0003`), forwards; `makemigrations --check` | OK |
| `manage.py doctor` (Local profile with a vision model) | *AI default processing source*, *AI Local profile for original documents*, document capabilities and *AI OCR fallback chain* reported, no key |
| `npm run build`, `vitest` (17), `scripts/check_docs.py`, `scripts/privacy_check.sh`, settings reference | Passed |

Found and fixed during the runs (not shipped): the widget selection in Settings → Appearance no longer showed a tile
once groups were saved (now authoritative, with a regression test); tablets showed half-width calendars after the
12-column change (tablet reflow restored to the previous rule, layout audit green); permanent deletion used
`SELECT … FOR UPDATE` with `DISTINCT`; a group left out of a save could drop General's tiles.

**Per test:** AT-461 Passed · AT-462 Passed (Local AI emulated) · AT-463 Passed (Local AI emulated; JPEG, PNG, PDF
single and two pages, TIFF three pages bounded to two, WEBP; TXT refused) · AT-464 Passed (real Tesseract fallback;
malformed and unusable answers) · AT-465 Passed · AT-466 Passed · AT-467 Passed · AT-468 automated rules Passed
(background priority, AI concurrency slot, page and size limits, temporary files removed) · AT-469 Passed · AT-470
Passed · AT-471 Passed · AT-472 Passed · AT-473 Passed · AT-474 Passed · AT-475 Passed · AT-476 Passed · AT-477 Passed
· AT-478 Passed · AT-479 Passed · AT-480 automated part Passed (full `pytest`, `scripts/e2e.sh` with the one
container-only AT-333 failure).

**Blocked / Not Executed** (never reported as passed):

- A **real LM Studio / Ollama vision model** reading documents directly (emulated with the same request shape; which
  formats and page counts a real model handles depends on the model — Test Profile checks it on the server).
- **AT-468** under real concurrent load (direct Local AI + browsing + OCR/ClamAV/backup) on the target 6 GB LXC.
- `personaldocs upgrade` of the production LXC to this release (migrations were run forwards/backwards here).

## Change set Z: AI Document Intelligence and the OCR engine order {#change-set-z}

**Numbering.** Prompt AT-416…AT-435 → **AT-441…AT-460**. Per-scenario status: [TRACEABILITY.md](TRACEABILITY.md#change-set-z).
Design and decisions: [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-z).

**Environment.** Development container (Ubuntu 24.04, PostgreSQL 16, Python 3.13, Tesseract 5, Node 22, Chromium via
Playwright), 2026-10-17. Cloud providers (OpenAI, Anthropic, Gemini, OpenRouter) and the local AI server are emulated by
`tests/fake_ai_server.py` with their request/response shapes; light-ocr ran for real (`@arcships/light-ocr` 0.5.9).

| Command | Result |
|---|---|
| `pytest tests/test_ai_intelligence.py` | **24 passed** (AT-441…AT-459, OCR engine order, light-ocr adapter, cloud providers, profile choice) and AT-460 passed after this report was written; with `PD_TEST_LIGHT_OCR_HOME` set, **the live light-ocr test passed**: real self-test and a real upload recognised by light-ocr (`VALID UNTIL 2031-05-20` read back) |
| Full `pytest` | **603 tests: 596 passed, 6 skipped (ClamAV daemon, real PaddleOCR runtime, live light-ocr), 1 failed: the documentation checker, only because this section did not exist yet; it passes with this report** |
| `scripts/e2e.sh` (fresh database) | flow, accessibility, parity, layout, offline, PWA, themes, recovery and corrective suites: **162 PASS** incl. the new step *AT-441…AT-460 Change Set Z* (engine order card and order setting kept, AI on Demand default, Cloud profile badge / send summary / Last test / key never shown, family member blocked from profiles); **1 FAIL in this container only**: AT-333 (Chromium here cannot load the real OpenFreeMap tiles through the container proxy certificate — unchanged by this change set, same as Change Set Y) |
| Migrations `core.0008` + `ai.0003` forwards, backwards (`ai 0002`, `core 0007`), forwards; `makemigrations --check` | OK; an existing database became *PaddleOCR → Tesseract (Auto)* and *AI on Demand* |
| `manage.py doctor` | AI mode, OCR engine order, light-ocr installed and **real self-test passed (1.6 s)** |
| `npm run build`, `vitest` (17), `shellcheck -S error scripts/personaldocs`, `scripts/check_docs.py`, settings reference | Passed |

**Per test:** AT-441 Passed · AT-442 Passed · AT-443 Passed · AT-444 Passed · AT-445 Passed · AT-446 Passed
(emulated cloud) · AT-447 Passed · AT-448 Passed · AT-449 Passed · AT-450 Passed · AT-451 Passed · AT-452 Passed ·
AT-453 Passed · AT-454 Passed (emulated providers) · AT-455 Passed · AT-456 Passed · AT-457 Passed · AT-458 Passed
for throttling/concurrency rules (real concurrent load: see below) · AT-459 Passed · AT-460 automated part Passed
(full `pytest`, `scripts/e2e.sh` with the one container-only AT-333 failure); production upgrade with light-ocr:
Passed after two fixes (see below).

**Blocked / Not Executed** (never reported as passed):

- Real **OpenAI, Anthropic, Gemini and OpenRouter** accounts (emulated with the same API shapes; AT-446…AT-448, AT-454).
- A real **LM Studio / Ollama** model with the new AI Actions (emulated).
- **Real PaddleOCR** with the engine order (fake worker; live PaddleOCR tests skipped as before).
- **AT-458** under real concurrent OCR, ClamAV and backup load on the target 2-CPU LXC (throttling and concurrency
  rules are unit-tested; the load itself was not run).

**Production upgrade (Debian 13 LXC, Node.js 20), 2026-10-18.** The first `sudo personaldocs upgrade` applied
`core.0008` and `ai.0003` and completed, but the light-ocr self-test failed (*exit 70*) and OCR used the next engine.
Two fixes followed: an 8 GB address-space cap and light-ocr's own error message in every failure, which then showed
the real cause — *Unable to locate @arcships/light-ocr-linux-x64-gnu*, the native platform package that npm skips on
Node 20 because it declares Node ≥ 22 (reproduced here with Node 20.19.5: `npm ci` omits it, `--force` does not
help). The installer now installs that package explicitly at the lockfile's version and sha512. After upgrading
again, the administrator reported **`sudo personaldocs ocr light-ocr` passing and light-ocr working on the production
server** — AT-460 production smoke test for light-ocr: **Passed** (reported by the administrator, not run from this
container).

## Change set Y: OCR → AI document analysis pipeline {#change-set-y}

**Numbering.** Prompt AT-401…AT-415 → **AT-426…AT-440**. Per-scenario status: [TRACEABILITY.md](TRACEABILITY.md#change-set-y).
Root causes and the reproduced failure: [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-y).

**Environment.** Development container (Ubuntu 24.04, PostgreSQL 16, Python 3.13, Tesseract 5, Node 22, Chromium via
Playwright), 2026-10-16. LM Studio is emulated by `tests/fake_ai_server.py` (its documented answer to
`response_format: json_object`, its model-type listing); PaddleOCR by the existing fake worker.

| Command | Result |
|---|---|
| `pytest tests/test_ai_pipeline.py tests/test_ai.py` | **36 passed** (21 new: AT-426…AT-439, the reproduced HTTP 400, sanitizer, roles, long text, test OCR) |
| Full `pytest` | **572 tests: 566 passed, 5 skipped (2 need a running ClamAV, 3 the real PaddleOCR runtime), 1 failed: the documentation checker, only because this section did not exist yet; it passes with this report** |
| `scripts/e2e.sh` (fresh database) | flow, accessibility, parity and layout (25), offline 9, PWA 4, themes 6, recovery 10: all PASS; **corrective 36 PASS** (incl. the new Local AI diagnostics step: OCR test per engine, Tesseract recognises the generated sample); screenshots 7 PASS, 1 FAIL in this container only (AT-333: Chromium here cannot load the real OpenFreeMap tiles through the container's proxy certificate; unchanged by this change set; CI has direct internet access) |
| Migration `ai.0002` forwards, backwards, forwards; `makemigrations --check` | OK; no missing migrations |
| `npm run build` (TypeScript check, build) | Passed |
| `python3 scripts/check_docs.py` | OK |

**Blocked / Not Executed** (never reported as passed):

- Analyze Document against the reported **LM Studio** server (`qwen3-8b`) itself; it was emulated.
- The **real PaddleOCR** runtime with this pipeline (AT-427/428 used the fake worker; the live PaddleOCR tests are
  skipped here as before).
- A real `personaldocs upgrade` and production smoke test (AT-440).

## Change set X: performance {#change-set-x}

**Numbering.** Prompt AT-376…AT-400 → **AT-401…AT-425**. Per-scenario status: [TRACEABILITY.md](TRACEABILITY.md#change-set-x).
Measurements (Before → After → Target): [PERFORMANCE.md](PERFORMANCE.md#results). Root causes:
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-x).

**Environment.** Development container (4 vCPU, 16 GB, Ubuntu 24.04, PostgreSQL 16, Python 3.13, Node 22, Chromium
via Playwright), 2026-10-16. Performance runs on the synthetic dataset (8,000 documents) with the web server pinned
to 2 cores; the browser suites ran on the production gunicorn configuration (2 workers × 4 threads).

| Command | Result |
|---|---|
| `pytest tests/test_performance.py` | **26 passed** |
| Full `pytest` | **553 tests: 547 passed, 5 skipped (2 need a running ClamAV, 3 the real PaddleOCR runtime), 1 failed: the documentation checker, only because this section did not exist yet; it passes with this report** |
| `scripts/e2e.sh` (fresh database, final run) | **161 PASS, 0 FAIL** (exit 0): flow; accessibility; parity and layout (7 viewports); offline 9; PWA 4; themes 6; recovery 10; **corrective 35** (incl. Change Set X: Settings loads only the open section and Backup code only when opened, direct links and Back/Forward, Performance page for administrators only with the report, compressed immutable app files, Performance page at 390 px); screenshots 8 |
| `manage.py perf_bench --budget` (8,000 documents) | every request within budget (40 queries, 500 ms); results in docs/performance/after/after-api.json |
| `tests/e2e/perf.mjs`, `scripts/perf_load.py` | all page targets met, also under background contention (PERFORMANCE.md#results) |
| Live adaptive throttling check | activation after two hot samples, deferrable job held back, recovery after three calm samples (docs/performance/after/throttle-live.txt) |
| `manage.py perf_maintenance` twice | both runs OK, nothing deleted |
| Migrations `library.0012`, `core.0007` forwards, backwards, forwards | OK (also reversing Change Set W's `core.0004`–`0006`) |
| `npm run build` (TypeScript check, build) | Passed; main bundle 252 KB (72 KB Brotli), under the 400 KB budget |
| `python3 scripts/check_docs.py`, `scripts/privacy_check.sh`, `shellcheck -S error` | OK |

**Blocked / Not Executed** (never reported as passed):

- Measurements on a production-equivalent **6 GB Proxmox LXC** (AT-401, AT-418, AT-425): not available; the
  development container with the web server pinned to 2 cores was used, and memory use was measured.
- A real `personaldocs upgrade` and production smoke test (AT-422, AT-425).
- Real OCR, ClamAV and backup load on such a container during browsing (AT-414): contention was simulated with
  CPU-bound processes at the same priorities.
- Firefox and Safari.

**Defects found while testing, all fixed:**

- The admin health summaries (backup and security), cached for 30 s, showed a missing recovery point right after one
  was created outside a job (found by `test_at309_backup_health_*`). Health is no longer cached.
- The Overview loaded the whole Backup & Recovery screen for one status badge (found by the new "Settings loads only
  the open section" browser check); the badge is now its own component.
- The system sampler's first CPU reading in a new process was empty: the first sample now measures over 0.5 s.
- `personaldocs rollback` refuses after an upgrade that added migrations; the upgrade guide (Change Set W and X and
  the general rollback section) now gives the exact steps to reverse them first.

**Environment note.** `test_at309_backup_health_*` also marks a destination *critical* below 10 % free disk; in this
container free space was close to 10 % (26 GB of 252 GB). After removing package caches (10.7 % free) it passes, and
it passed in the final run.

## Change set W: named sign-in designs and rotation, complete details and IPs, Notification Detail Level {#change-set-w}

**Numbering.** The change prompt numbered its tests AT-351…AT-375. Here they are **AT-376…AT-400** (prompt AT-n →
AT-(n+25)). Per-scenario status: [TRACEABILITY.md](TRACEABILITY.md#change-set-w). Root causes:
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-w).

**Environment.** Development container (Ubuntu 24.04, PostgreSQL 16, Python 3.13, Node 22, Chromium via Playwright),
2026-10-15. No real Email, Telegram, WhatsApp, Discord or Web Push accounts and no production address. Wallpapers in
the tests and screenshots are drawn in the browser or generated with Pillow; no photos.

| Command | Result |
|---|---|
| `pytest tests/test_corrective_w.py` | **28 passed** |
| Full `pytest` | **525 tests: 520 passed, 5 skipped, 0 failed** (skipped: 2 need a running ClamAV, 3 need the real PaddleOCR runtime) |
| `scripts/e2e.sh` (fresh database, final run) | **158 PASS, 0 FAIL** (exit 0): flow; accessibility in every theme; parity and layout (7 viewports); offline; PWA; themes; recovery; **corrective 32** (incl. Change Set W: new design → wallpaper → focal point → Set as Active → public sign-in page uses the design with a light palette → Revert; rotation pool, status card, Preview Rotation, single-design pool refused, family member refused; Notification detail per person); **screenshots 8** |
| `npm run build` (TypeScript check and production build) | Passed |
| `python3 scripts/check_docs.py` | **OK** |
| `scripts/privacy_check.sh` | **OK** |

**Blocked / Not Executed** (never reported as passed):

- Delivery of Full and Minimal notifications to real Email, Telegram, WhatsApp, Discord and Web Push accounts (no
  accounts here). Every channel uses the same renderer, which is covered per channel by `test_rich_notifications.py`,
  `test_notification_policy.py`, `test_expiry.py`, `test_events.py` and CW AT-398/AT-399.
- A production smoke test after `sudo personaldocs upgrade` (no production installation here); see
  [upgrades](guides/upgrades.md#change-set-w) and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
- Firefox and Safari.

**Prior suites.** Every earlier backend test file and browser suite ran in the runs above. Tests that asserted the old
masking (document numbers, names and IP addresses in notifications and sign-in views) were changed to assert the
complete values for authorised people and the Minimal Details summary; their checks that secrets never appear were
kept.

**Defects found while testing, all fixed:**

- The notification preferences page ran about 7,300 queries (≈ 21 s on the test server): every event recomputed
  every event's defaults. A matrix toggle looked as if it did not stick until the slow reload returned (found by
  parity AT-68; this predates Change Set W). Now about 380 queries (0.6 s); regression test in
  `test_notification_policy.py`.
- The sign-in preview showed "Sign in with Sign in with authentik": the configured button label already contains the
  words. The preview now shows the label as the real sign-in page does.
- In the narrow Desktop preview of the design editor the title broke inside a word. Narrow previews now scale their
  text.
- Replacing the active design's wallpaper left the old original file behind; backups held only the legacy wallpaper
  and logo; a broken rotation pool could retry on every scheduler tick; the rotation audit entry failed on a reserved
  argument name. All fixed with tests (CW AT-383/AT-384/AT-388/AT-389).
- The parity test expected the Text (OCR) tab to stay open after recognition; Change Set W opens Details by itself, so
  the test now checks that and then reads the confidence on the OCR tab.

## Change set V: NAS in Backup Destinations, English sign-in map, tooltips, Help permissions, WhatsApp pairing {#change-set-v}

**Numbering.** The change prompt numbered its tests AT-331…AT-350. Here they are **AT-356…AT-375** (prompt AT-n →
AT-(n+25)). Per-scenario status: [TRACEABILITY.md](TRACEABILITY.md#change-set-v). Root causes:
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-v).

**Environment.** Development container (Ubuntu 24.04, PostgreSQL 16, Python 3.13, Node 22, Chromium via Playwright
with software WebGL), 2026-10-13. No WhatsApp phone, no SMB/NFS server and no production address. WhatsApp in the
browser suites used `tests/fake_whatsapp_bridge.py`; the bridge's pairing logic is covered by its own unit tests with a
fake socket. In `corrective.mjs` the OpenFreeMap style was answered locally; `screenshots.mjs` used the **real**
OpenFreeMap service through the proxy (the English-labelled map in `security-signin-map.png`).

| Command | Result |
|---|---|
| `npm test` in `bridge/whatsapp` (session manager, fake socket) | **10 passed** |
| `pytest tests/test_corrective_v.py` | **33 passed** |
| Full `pytest` | **494 tests: 491 passed, 3 skipped (need the real PaddleOCR runtime), 0 failed** (after the final e2e run; `test_antivirus_live.py` needs a real ClamAV and was not run) |
| `scripts/e2e.sh` (fresh database, final run) | **155 PASS, 0 FAIL** (exit 0): flow; accessibility in every theme; parity and layout (7 viewports, incl. the new Destinations and sign-in screens); offline 9; PWA 4; themes 6; recovery 10; **corrective 29** (incl. Change Set V: Storage & NAS redirect, NAS fields in the destination, Backup Now + FIFO queue, tooltips in table/dialog/phone, Help for a family member, English vector map, markers/clusters/details/filters, WhatsApp countdown/stages/failure/new QR/verified, diagnostics); **screenshots 8** |
| `npm run build` (TypeScript check and production build) | Passed |
| `python3 scripts/check_docs.py` | **OK** |
| `scripts/privacy_check.sh` | **OK** |
| `shellcheck -S error scripts/personaldocs scripts/e2e.sh` (as in `scripts/verify.sh`) | **OK** |

**Live WhatsApp evidence (no phone).** Bridge 1.1.0 against the real WhatsApp servers from this container: QR codes
were issued, one link attempt stayed open for 300 s (11 codes; WhatsApp closed the QR connection with 408 after
162 s and the bridge reopened it inside the same attempt), then ended as *link expired*. Diagnostics: DNS, network,
clock and storage OK.

**Defects found while testing, all fixed:**

- Administrator console commands (`sudo …`) were visible to family members in seven everyday guides → moved into
  main-administrator sections; a test now fails on any `sudo` line a family member can read.
- A destination at exactly 20 % free space was not *Warning* → thresholds are inclusive.
- A person's first WhatsApp link attempt did not count towards the hourly limit → counted.
- A backup job waiting for a later retry blocked the whole FIFO queue → only due jobs hold the queue.
- **The Content-Security-Policy origin for the map was cached per server worker for a minute**, so after the
  provider changed, other workers still blocked the new provider (*Map unavailable*). Found by the browser suite (the
  map failed only on pages served by the second worker) → every worker re-reads the map settings (one small query) and
  follows a change at once; regression test added.
- The sign-in map filters rendered as five full-width stacked selects → one compact, wrapping row.
- `test_at281_retention_never_deletes_a_needed_base` failed in 2 of 3 runs: the test gives a Full and its incremental
  the same timestamp, and chains were ordered by timestamp only, so the incremental could lead the chain; the chain
  then did not count as usable and retention planned to delete the newest usable chain. Chains now always start with
  their Full (4 of 4 runs pass). In normal operation a Full is always older than its incrementals.

**Blocked / Not Executed (never reported as passed):**

| Scenario | Why |
|---|---|
| AT-369 (prompt AT-344) real phone pairing, scan, verification message, restart restoration | No phone or WhatsApp account available |
| Real multi-phone isolation and real post-link test message (parts of AT-371, AT-372) | Same |
| Mounting a real SMB or NFS share (part of AT-358) | No NAS; mounting is tested with the faked root helper |
| OpenFreeMap from the production address | No production address; tested from this container through the proxy |
| Firefox and Safari | Chromium only |

**Note.** The muted privacy line under the map was reworded after the final screenshots were taken
(*ordinary map data (tiles)* instead of *ordinary picture tiles*); `security-signin-map.png` still shows the old
wording.

## Change set U: corrective fixes for the folder tree, sign-in map, sign-in designs, WhatsApp and Discord {#change-set-u}

**Numbering.** The change prompt numbered its tests AT-311…AT-330. Here they are **AT-336…AT-355** (prompt AT-n →
AT-(n+25)). Per-scenario status: [TRACEABILITY.md](TRACEABILITY.md). Root causes:
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-u).

**Environment.** The same development container (Ubuntu 24.04, PostgreSQL 16, Python 3.13, Node 22, Chromium via
Playwright), 2026-10-12. There was no WhatsApp phone, no Discord server and no production address for real map
tiles. WhatsApp used `tests/fake_whatsapp_bridge.py` (same HTTP API, obviously fake QR), started by `scripts/e2e.sh`.
Map tiles in the corrective suite were answered by `page.route` (no request reached a real provider).

| Command | Result |
|---|---|
| `pytest tests/test_corrective_u.py` | **16 passed** |
| Full `pytest` | **463 tests: 458 passed, 5 skipped (live-only tests), 0 failed** (exit 0, after the final e2e run) |
| `scripts/e2e.sh` (fresh database) | **146 PASS, 0 FAIL** (final run, exit 0): flow 14; accessibility in every theme with **no serious or critical violations**; parity and layout (7 viewports); offline 9; PWA 4; themes 6; recovery 10; **corrective 20** (folder tree geometry at 1440/820/390 px × Green, Blue, Dark, Glass Light, Glass Dark, right-to-left, keyboard; thumbnail luminance × 5 themes; preview/Save/Discard and the public sign-in page; map with a working tile and with 403, 429, 401 and network failures; Test Map Provider; WhatsApp enable → link → fake scan → Send test → routing → disable, bridge down, isolation; Discord; 390 px phone layout); **screenshots 8**. The first full run stopped at the accessibility audit (see defects below) |
| `python3 scripts/check_docs.py` | **OK** (links, anchors, alt text, no orphan screenshots, Learn more links, review dates) |
| `scripts/privacy_check.sh` | **OK** |
| `npm run build` (TypeScript check and production build) | Passed |

**The checks detect the original defects.**

- **Sign-in thumbnails:** with the old CSS restored in the browser (no stacking isolation, wallpaper at
  `z-index: -2`, admin theme colours), the mean brightness of a thumbnail measured **36** in Dark and **53** in Glass
  Dark. The test requires more than 150. With the fix: **231** and **233**.
- **Map:** the test checks that every tile request carries exactly this site's origin as `Referer`. The old
  `same-origin` policy sent none, which is what OpenStreetMap blocks.
- **WhatsApp "Planned":** the tests fail if the text *Planned* appears anywhere in Settings → Connections or in the
  provider API.

**Defects found while writing these tests, all fixed:**

- After the administrator turned WhatsApp off, a person who was still linked saw no **Disabled by Admin** badge. The
  badge is now shown on the full card too.
- The *Map unavailable* link for administrators pointed to `/settings/security#map-provider`. The map provider card is
  on the **Access policy** view, so the link is now `/settings/security?view=access#map-provider`, and the guides
  name that path.
- The first full run's accessibility audit (axe) failed on the sign-in page in Dark and Glass Dark (colour contrast).
  The sign-in page now always uses the green theme, but `.auth` had no background of its own. The dark page colour
  of the last user's theme, set on `<html>`, showed through behind green-theme text. `.auth` now paints its own
  background and text colour.
- The loading skeleton put `aria-label="Loading"` on a plain `div`, which axe reports as a prohibited attribute when
  a card is still loading during the audit. It now has `role="status"`.
- A leftover `whatsapp.status` setting ("Personal WhatsApp notifications are a later-phase feature", value
  `planned`) was removed from the registry and the settings reference. Nothing read it.

**Not run** (never reported as passed): a real phone scanning a real WhatsApp QR code; a real Discord server; real
OpenStreetMap, MapTiler or Stadia Maps tiles from a production address; Firefox and Safari.

## Change set T: encrypted backup and recovery, notification routing, sign-in security, rich guides {#change-set-t}

**Numbering.** The change prompt numbered its tests AT-251…AT-310. Here they are **AT-276…AT-335** (prompt AT-n →
AT-(n+25)). The per-scenario status is in [TRACEABILITY.md](TRACEABILITY.md).

**Environment.** The same development container as above (Ubuntu 24.04, PostgreSQL 16, Python 3.13, Node 22, Chromium
via Playwright). There was no Debian 13 host, no NAS, no S3, no Google or Microsoft account, no WhatsApp phone and no
Discord server. OCRmyPDF ran as `python3.12 -m ocrmypdf` (`PD_OCRMYPDF_CMD`), because the container's system
`ocrmypdf` is broken; the same tests fail on `main` without it.

| Command | Result |
|---|---|
| `pytest tests/test_backup_engine.py tests/test_recovery_api.py tests/test_disaster_recovery.py tests/test_notification_channels.py tests/test_signin_security.py` | All passed: engine 16, recovery API 16, disaster recovery 7 (real `pg_dump`/`pg_restore` against the PostgreSQL test database, including a scratch-database test restore and a restore into a separate validation database), channels 13, sign-in security 9 |
| Full `pytest` (2026-10-11) | **447 tests: 441 passed, 5 skipped (live-only tests), 1 failed.** The failure was `test_at332_at334_documentation_checker_passes`, run before the 15 new screenshots and this section existed; after they were added, `scripts/check_docs.py` passes (see below) |
| `python3 scripts/check_docs.py` | **OK** after the 15 new screenshots were added (links, anchors, alt text, no orphan screenshots, Learn more links, review dates) |
| `scripts/e2e.sh` (fresh database, `PD_E2E_PROXY_CA` set for map tiles behind the sandbox proxy) | **125 PASS, 0 FAIL** (final run, exit 0): flow 14; accessibility with **no serious or critical violations**; parity and layout (all 7 viewports); offline 9; PWA 4; themes 6; **recovery 10** (destination and policy, encrypted point, step-up Recovery Key reveal, Emergency Recovery Package, Recovery Explorer restore with impact analysis, protected deletion, routing and quiet hours, Trusted Zone and sign-in map, Help navigation, 390 px phone layout); **screenshots 7** (the 15 new documentation captures, and guide images load in Help). Earlier runs that failed are listed under defects below |
| `bash -n` + `shellcheck` (`personal-DM.sh`, `scripts/personaldocs`, `scripts/verify.sh`, `scripts/e2e.sh`) | Clean |
| `sudo bash tests/installer/test_personal_dm.sh` (includes menu option 2 *Recover Existing Installation*) | 18/18 passed (stubbed system commands) |
| `scripts/privacy_check.sh` | **OK** |
| `node bridge/whatsapp/server.mjs --selftest` | Passed; a live start produced a real WhatsApp QR code (no phone was linked) |

**Defects found by these tests and the screenshot review, all fixed:**

- Channel labels were renamed ("In-App", "PWA Push"), which broke existing screens and tests. The existing labels are
  back.
- Help on phones and tablets: the hidden guide list overlapped (layout audit), and a long inline URL widened the page by
  25 px at 390 px.
- A new device on a private, non-zone network was rated **Warning**. It is now **Low**, as documented; Warning is for
  new devices on public networks.
- Automated Recovery Validation compared database hosts literally, so `localhost` and an empty host (socket) counted as
  different servers. It could therefore have restored into the production database. They are now the same server, and
  the validation refuses.
- Untyped text inputs (destination dialog, address test, timezone) were unstyled.
- The selected restore point and folder in the Recovery Explorer were white text on pale green.
- The map legend and timeline dots were positioned by a global `.dot` rule, so they appeared in a page corner.
- The routing table squeezed its channel and delivery controls (it inherited fixed cell widths). The WhatsApp badges
  were spread across the card header, and its callout repeated "Experimental".
- Dialogs could be clipped by an ancestor element. They now render at the end of `<body>`.
- Test-only fixes: parity steps follow the new notification and backup screens; the recovery suite keeps its backup
  folder for the screenshot suite; guide images are lazy-loaded, so they are checked by decoding them; the screenshot
  browser proxies only `https://` and pins the proxy CA (TLS checks stay on); the privacy gate allows private networks
  and still blocks public addresses outside the documentation ranges.
- The bridge's `node_modules` had been committed by mistake in an unpushed commit. It was removed from history before
  the first push and is now ignored.

**Screenshot review.** All 15 new captures were checked by eye:

- synthetic names only;
- the Recovery Key is never shown (only its non-secret fingerprint);
- no webhook address and no WhatsApp QR code or session data;
- private Trusted Zone networks and loopback only; no public IP address;
- a synthetic destination path;
- the zone map pin is a generic city-centre point;
- real OpenStreetMap tiles, with the attribution visible.

**Not run (needs real accounts or hardware), so not reported as passed:**

- a clean Debian 13 LXC recovery drill (AT-302, real part);
- live NAS, S3, Google Drive and OneDrive destinations and bootstrap recovery (AT-303/304);
- linking a real WhatsApp phone and a live bridge update (AT-313/315);
- a real Discord server (AT-317);
- Firefox, Safari and real phones.

## Change set S: offline access, PWA identity, themes, screenshots {#change-set-s}

**Investigation and root causes.**
- *iPhone shows "A" instead of the icon.* It could not be reproduced on a physical device here. Found in the code:
  - `/apple-touch-icon.png`, `/apple-touch-icon-precomposed.png` and `/favicon.ico` were answered with `200 text/html`
    (the app page);
  - there was no 180 px Apple icon and no `apple-mobile-web-app-title`.

  iOS cannot use HTML as an icon and builds a letter tile from the page title. A reverse proxy that requires sign-in
  for icon files produces the same symptom; `check-access` now tests for it. iOS keeps a shortcut's first icon, so a
  fresh install is required.
- *Low-detail screenshots.*
  - All 50 were captured at 1× with mixed 1366/1440 widths, as side effects of functional tests.
  - Four had no capture code left and showed older UI.
  - Now: 1440×900 / 390×844 at 2×, settled, with quality and privacy gates.
- *Themes.* 165 colour literals made dark/glass themes impossible without white islands. They are replaced by semantic
  tokens.

**Measured.**
- Glass themes on a phone viewport: 2 blurred layers (navigation, top bar); about 60 fps scrolling the folder list
  under 4× CPU throttling in headless Chromium (`tests/e2e/out/themes/effects.json`).
- Contrast measured on rendered pixels: lowest ratio 5.08:1 (muted text on a card), all ≥ 4.5:1
  (`tests/e2e/out/themes/contrast.json`).

**Acceptance AT-251…AT-275** (prompt AT-226…AT-250):

| Result | Tests |
| --- | --- |
| Passed | AT-251…AT-260, AT-263…AT-266, AT-268…AT-275 |
| Partly | AT-261: markup and assets passed; a physical iPhone/iPad is **Not Run** |
| Partly | AT-262: Chromium installability passed; real Android and desktop installs are **Not Run** |
| Passed in emulation | AT-267: real low-end phones **Not Run** |

**Not run here:**
- a physical iPhone/iPad, Android device and installed desktop apps;
- Firefox and Safari;
- offline use on a real phone in airplane mode;
- glass performance on real low-end devices;
- a real Debian 13 upgrade.

These are on the [release checklist](RELEASE_CHECKLIST.md).

## Acceptance summary (AT-01…AT-355) {#summary}

340 scenarios (AT-51…AT-60 were never assigned). Per-scenario status: [TRACEABILITY.md](TRACEABILITY.md).

| Result | Count | Scenarios |
|---|---|---|
| Passed (automated tests, or for AT-136, AT-245, AT-270, AT-272, AT-274, AT-333 and AT-354 including a documented review) | 277 | all scenarios not listed below |
| Passed in automated tests; real-environment validation pending | 55 | AT-17, 19, 21, 31, 39, 40, 69, 71, 76, 83, 90, 91, 98, 99, 111, 122, 125, 130, 134, 140, 142, 146, 147, 148, 149, 153, 154, 155, 174, 175, 177, 178, 181, 194, 195, 197, 202, 205, 206, 208, 211, 212, 214, 216, 228, 229, 230, 261 (physical iPhone/iPad), 262 (real Android/desktop installs), 267 (real low-end phones), 302 (clean Debian 13 LXC recovery), 303 (live NAS/S3), 313 and 315 (real WhatsApp phone and live bridge update), 317 (real Discord server) |
| Blocked (external environment) | 5 | AT-14, AT-26; AT-24, AT-27, AT-30 (partly automated, the rest needs a real Debian 13 LXC) |
| Not run (manual steps, not automated, or no environment) | 3 | AT-15, AT-241 (installed PWA on a real device), AT-304 (Google Drive / OneDrive recovery needs real accounts) |

Pending external validations for change set M (none reported as passed): a real authentik server; public DNS, a
valid TLS certificate and an Internet-accessible staging site for Internet Ready; the real host helper on Debian 13
(apt security updates, reboot and ufw inspection as root); automatic freshclam updates on Debian 13; a real
Proxmox/LXC install and upgrade.

Pending external validations for change set N (none reported as passed): the installed PWA on real iOS and Android
devices (AT-175); an upgrade of a real Debian 13 / Proxmox installation with existing production data (AT-174).

Change set O: AT-194 is counted from the parity steps of the browser suite (**59 PASS, 0 FAIL**). Pending external
validations (none reported as passed): real SMTP delivery and HTML rendering in Gmail, Outlook and Apple Mail
(AT-177); a real Telegram bot with inline buttons on an https address (AT-178); real Web Push on Android/Chrome, the
iOS/iPadOS Home Screen app, Firefox and Windows (AT-181); the installed PWA on real devices (AT-194); an upgrade of a
real Debian 13 installation (AT-195).

Change set P: see [below](#change-set-p). Pending external validations (none reported as passed): real passkey
platforms (AT-197), real SMTP delivery of the reset email (AT-202), a real Debian 13 / Proxmox LXC upgrade and repair
(AT-205, AT-206) and reboot persistence on a real host (AT-208).

Change set Q: see [below](#change-set-q). Pending external validations (none reported as passed): a fresh install
and an upgrade on a real Debian 13 / Proxmox LXC with 6 GB (AT-211, AT-212, AT-214, AT-229), accuracy on sanitised
real documents (AT-216, AT-230), and a real Local AI server with PP-OCRv5 output (AT-228).

Change set U: see [above](#change-set-u). All 20 scenarios (AT-336…AT-355) passed in automated tests. Not run (none reported as passed): a real WhatsApp phone, a real Discord server, real map tiles from a production address, Firefox and Safari.

Change set R: see [below](#change-set-r). Not run: an installed PWA on a real device (AT-241), browsers other than
Chromium.

## Change set R: UI alignment, responsive layout and visual regression {#change-set-r}

The change prompt numbered the acceptance tests AT-211…AT-225; in this repository they are **AT-231…AT-245**
(prompt AT-n → AT-(n+20)), because AT-211…AT-230 belong to Change Set Q.

**Root cause** (details in [ADR 0017](adr/0017-ui-layout-primitives.md)): the header title was a `flex: 1` item
(`flex-basis: 0`) in a wrapping row next to non-wrapping buttons, so the row never wrapped and the title was
squeezed. Responsive rules followed the window width, not the width of the pane.

**Before/after (synthetic documents, same instance), title width and lines of "Family residence permit renewal
receipt and payment confirmation 2018-19 final copy.JPG":**

| Viewport | Pane before | Title before | Lines before | Pane after | Title after | Lines after |
|---|---|---|---|---|---|---|
| 1920×1080 | 746 | 192 | 6 | 746 | 713 | 2 |
| 1366×768 | 438 | 405 | 3 | 438 | 405 | 3 |
| Tablet landscape 1180×820 | 323 | 290 | 4 | 873 | 841 | 2 |
| Tablet portrait 820×1180 | 273 | 240 | 5 | 513 | 481 | 2 |
| Phone 390×844 | 356 | 324 | 3 | 356 | 324 | 3 |

Images: `docs/images/layout/preview-before-1920.png`, `preview-after-1920.png`, `preview-before-tablet-portrait.png`,
`preview-after-tablet-portrait.png`.

| AT | Prompt AT | Scenario | Status |
|---|---|---|---|
| AT-231 | AT-211 | Screenshot defect reproduced, root cause documented | Passed |
| AT-232 | AT-212 | Preview header uses the panel width and stays aligned | Passed (layout, 7 viewports × 5 names) |
| AT-233 | AT-213 | Short/normal/long/very long file names | Passed |
| AT-234 | AT-214 | Three-panel responsiveness | Passed |
| AT-235 | AT-215 | Icon/text alignment | Passed (no misalignment > 3 px on any audited screen) |
| AT-236 | AT-216 | Badge consistency | Passed |
| AT-237 | AT-217 | Global screen audit | Passed (27 screens × 7 viewports, 0 defects; findings fixed listed below) |
| AT-238 | AT-218 | Desktop visual regression (1920×1080, 1440×900, 1366×768) | Passed (geometry baseline + reviewed screenshots) |
| AT-239 | AT-219 | Tablet portrait/landscape | Passed (emulated in Chromium) |
| AT-240 | AT-220 | Phones ~390/430 px | Passed (emulated in Chromium) |
| AT-241 | AT-221 | Installed PWA | Not Run (no real device / installed PWA in this environment) |
| AT-242 | AT-222 | Menus, dropdowns, dialogs inside the viewport, keyboard/touch reachable | Passed (7 viewports) |
| AT-243 | AT-223 | Accessibility regression | Passed (accessible names, focus ring, axe audit: no serious/critical) |
| AT-244 | AT-224 | Arabic / mixed-character metadata | Passed |
| AT-245 | AT-225 | No fragile workaround | Passed (code review: flex basis, container queries, shared components) |

**Other defects found by the audit and fixed:**

- document list cards, and the shared/search/archive lists: name and details squeezed beside the status badges (61 px
  at 1366 px, 38 px at 430 px); the badges now sit under the name;
- the tab-bar note "No details yet" (42 px);
- the Overview date widget (88 px);
- settings label columns on tablets;
- help table columns (wrapping in 129–136 px columns).

**Reviewed and not changed:** the viewer toolbar keeps its sideways-scrolling single row on narrow panes (all
controls reachable).

**Not tested / limits:**

- Chromium only: Firefox, Safari and Edge are Not Run;
- installed PWA on real devices: Not Run;
- the details/table view and the thumbnail grid with very long names, tooltips and confirmation dialogs other than
  Share / Remove OCR / Disable OCR: Not Run;
- real phones and tablets: Not Run (emulated viewports only).

Affected earlier tests: none failed. The parity selectors for the document "More actions" menu and the Share button
still match (labels kept as accessible names).

## Change set Q: PaddleOCR (PP-OCRv5) and the complete OCR lifecycle {#change-set-q}

The change prompt numbered the acceptance tests AT-191…AT-210. In this repository they are **AT-211…AT-230**
(prompt AT-n → AT-(n+20)).

| AT | Prompt AT | Scenario | Status |
|---|---|---|---|
| AT-211 | AT-191 | PaddleOCR installation, minimal real inference | Passed in the development container (real self-test, doctor, live test, e2e) — fresh install on a real Debian 13 LXC Not Run |
| AT-212 | AT-192 | Upgrade preservation, no automatic re-processing | Passed (migration test) — real upgrade Not Run |
| AT-213 | AT-193 | PP-OCRv5 default, engine/model/profile recorded | Passed (automated, live, e2e) |
| AT-214 | AT-194 | 6 GB resource behaviour, single queued worker | Passed (queue and limits; worker peak RSS 1.3–1.9 GB measured) — real 6 GB LXC under load Not Run |
| AT-215 | AT-195 | Selective OCR modes and per-document override | Passed |
| AT-216 | AT-196 | Language profiles route to the intended models | Passed (routing; real models on synthetic samples for all five profiles) — real-document accuracy Not Run |
| AT-217 | AT-197 | Remove OCR deletes all derived data, keeps originals and confirmed details | Passed (automated, e2e) |
| AT-218 | AT-198 | Document-level Disabled prevents regeneration until enabled | Passed (automated, e2e) |
| AT-219 | AT-199 | Search cleanup | Passed (automated, e2e) |
| AT-220 | AT-200 | Audit privacy | Passed |
| AT-221 | AT-201 | Existing OCR inventory by engine with storage | Passed (automated, e2e) |
| AT-222 | AT-202 | Bulk cleanup | Passed |
| AT-223 | AT-203 | Controlled re-processing | Passed |
| AT-224 | AT-204 | Failed re-processing safety | Passed |
| AT-225 | AT-205 | Orphan dry run and cleanup | Passed (automated, e2e) |
| AT-226 | AT-206 | OCR Test outside the library | Passed (automated, e2e with the real runtime) |
| AT-227 | AT-207 | Compare engines without comparing confidences | Passed (automated, e2e, benchmark) |
| AT-228 | AT-208 | Local AI with PP-OCRv5 output; confirmed data protected | Passed with a mocked AI server — real AI server Not Run |
| AT-229 | AT-209 | Models and configuration persist across restart/upgrade/repair | Passed for configuration and restart — real upgrade/repair/reboot Not Run |
| AT-230 | AT-210 | Representative benchmark | Passed for synthetic samples — real passports, iqamas, IDs, certificates and phone photos Not Run |

**Handover evidence.**

- **Root cause of retained OCR text** (nine causes) and the **previous storage/index map**: see
  [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#change-set-q).
- **Versions:** PaddlePaddle 3.2.2, PaddleOCR 3.7.0, PaddleX 3.7.2 (3.3.1 crashed in oneDNN on CPU).
- **Model and profile:** PP-OCRv5 mobile detection plus per-language mobile recognition; default profile English;
  offered English, Arabic + English, Hindi + English; document orientation on, text-line orientation off.
- **6 GB worker configuration:**
  - one heavy job at a time;
  - 2 threads and a 3000 MB address-space limit per job;
  - worker unit `MemoryHigh=3400M`, `MemoryMax=4000M`, `CPUWeight=50`.
- **Real inference result:** the self-test passed in 2.5–3.8 s. A real document run read "SAMPLE RESIDENCE PERMIT …
  2027-03-15", and the Arabic and Hindi profiles read their scripts (live tests).
- **Benchmarks and comparisons actually executed:** 21 synthetic samples × 2 engines (above), plus Compare engines
  in the browser on a synthetic permit (both engines 100 %). Not executed: any real document category.
- **Removal proof** (`test_at217_at219_at220_*`), all after removal:
  - text, blocks, engine and quality cleared;
  - the stale `searchable.pdf` deleted;
  - semantic chunks, pending AI suggestions and proposals deleted, the queued AI job cancelled;
  - the OCR-only phrase no longer found;
  - the confirmed detail kept with its excerpt cleared;
  - originals and versions unchanged (SHA-256);
  - the audit entry has counts only.

  The browser step repeats it on a real PP-OCRv5 or Tesseract result.
- **Disable proof** (`test_at218_*`):
  - *Automatic* type upload, *Regenerate preview*, a bulk re-process and an explicit Run OCR do not recognise the
    document while it is disabled;
  - after Enable, OCR works again.
- **Storage reclaimed in controlled cleanup tests:**
  - the bulk removal lowers the inventory's text storage (`test_at221_at222_*`);
  - the orphan cleanup removed 8,000 bytes of unreferenced searchable copies and a stale 1,000-byte scratch folder;
  - it kept the referenced copy, the preview, and a copy written within the last hour (`test_at225_*`).
- **Local AI regression:** `tests/test_ai.py` passed (full suite), and `test_at228_*` showed that:
  - a result for removed text is discarded through the OCR epoch;
  - confirmed details are never overwritten.
- **Affected earlier regression tests:** selective OCR (`test_at111` now runs an explicit Tesseract request when
  languages are given), storage health categories (four OCR categories added), and the e2e selective OCR step
  (PP-OCRv5 default and profiles).
- **Not tested:**
  - a real Debian 13 / Proxmox LXC (install, upgrade, repair, reboot, 6 GB under load);
  - model download from Hugging Face on a fresh server (the container used the BOS mirror);
  - real family documents;
  - a real Local AI server;
  - GPU (not supported by design).

## Change set P: passkey sign-in, password reset, security templates, ClamAV repair {#change-set-p}

The change prompt numbered the acceptance tests AT-176…AT-190; in this repository they are **AT-196…AT-210** (prompt
AT-176 → AT-196 … AT-190 → AT-210), because AT-176…AT-195 belong to Change Set O.

**Results.** `tests/test_auth_password_clamav.py`: **18 passed**. `tests/test_antivirus_live.py` (real clamd 1.5.4):
**passed**. Full backend suite: **350 passed**. Browser suite (`scripts/e2e.sh`): **62 PASS, 0 FAIL** (no serious or critical accessibility violations).

| AT | Prompt AT | Scenario | Status |
|---|---|---|---|
| AT-196 | AT-176 | Sign in with Passkey on the first sign-in screen | Passed (automated; e2e step AT-196) |
| AT-197 | AT-177 | Passwordless sign-in without username or password | Passed with a software authenticator — real platforms Not Run |
| AT-198 | AT-178 | Passwordless / Password + Passkey modes; main administrator recovery | Passed |
| AT-199 | AT-179 | Passkey enrolment, rename, removal audited and notified | Passed (automated) |
| AT-200 | AT-180 | Temporary password shown once, forced change, sessions end | Passed (automated; e2e step AT-200/201) |
| AT-201 | AT-181 | Temporary password never stored or sent | Passed (automated; e2e step AT-200/201) |
| AT-202 | AT-182 | Branded, single-use, expiring reset email | Passed (automated, mocked SMTP) — real SMTP and mail clients Not Run |
| AT-203 | AT-183 | Main Administrator protection | Passed (automated) |
| AT-204 | AT-184 | Security templates with mandatory text, branding and footer; account-locked and link events | Passed (automated) |
| AT-205 | AT-185 | Diagnosis finds the socket cause, not cached metadata | Passed on a simulated Debian host and a real clamd — real Debian 13 LXC Not Run |
| AT-206 | AT-186 | Repair restores daemon, socket and service-account access; host-helper action | Passed on a simulated Debian host and a real clamd — real Debian 13 LXC Not Run |
| AT-207 | AT-187 | Clean + EICAR self-test without artifacts; admin-only endpoints | Passed (automated, real clamd; e2e step AT-205..207) |
| AT-208 | AT-188 | Repair persistence | Passed for configuration only — real reboot / LXC restart Not Run |
| AT-209 | AT-189 | Upload scan and quarantine after repair | Passed (automated) |
| AT-210 | AT-190 | Security Health from the operational state | Passed (automated) |

**Handover evidence.**

1. **Root cause of "passkey only after the password".** Passwordless sign-in was gated by `auth.allow_passwordless`
   (off by default) plus a per-person opt-in, so passkeys were only offered as the second step and the "Sign in with
   a passkey" button stayed hidden. Replaced by `auth.passkey_mode` (Passwordless by default) and migration
   `accounts.0007_passkey_mode`.
2. **Root cause of the ClamAV socket failure.** The most likely cause is the `LocalSocket` mismatch with socket
   activation: Debian's `LocalSocket /var/run/clamav/clamd.ctl` differs as a string from the socket unit's
   `/run/clamav/clamd.ctl`, so clamd binds its own socket file and removes it when it stops or restarts. Other causes
   found in the Debian 13 units: a start skipped by `ConditionPathExistsGlob` when signatures are missing, and an
   out-of-memory kill without `Restart=`. The diagnosis on the host names which applies; it was not run on the
   affected real host.
3. **Effective socket path after repair:** `/run/clamav/clamd.ctl`, the path of the systemd socket unit
   `clamav-daemon.socket`; `LocalSocket` is set to the same string and `antivirus.socket` is synced to it.
4. **Daemon and freshclam service evidence:** only from the simulated Debian host (fake `systemctl`) and the real
   clamd in the development container (no systemd). A real `clamav-daemon` restart and freshclam update under systemd:
   Not Run.
5. **Service identity access:** checked by the repair with `runuser` as `personaldocs` (`PING` → `PONG`) and by the
   web app's own diagnosis connecting as the service account (simulated host and real clamd).
6. **Self-test results:** real clamd 1.5.4 — clean text *Clean*, EICAR detected, temporary files removed, no document
   or quarantine entry created. The diagnosis tool against the real daemon stopped: *Unavailable* with
   `FileNotFoundError` reported; running: self-test PASSED.
7. **Persistence:** the drop-in (`Restart=on-failure`, `RestartSec=15s`) and the tmpfiles entry
   (`d /run/clamav 0755 clamav clamav -`) are written and verified as configuration; a real reboot: Not Run.
8. **Password-reset security results:** temporary password 16 characters, stored only as a hash, shown once with
   `Cache-Control: no-store`, never emailed and never written to logs, notifications or the audit record, forced change, every session ended, older
   tokens invalidated; reset email single-use, expires after `auth.reset_token_minutes`, older links invalidated, never
   in the outbox, in-app history, Telegram, push or logs, https required on Internet deployments; an Administrator
   cannot reset a main administrator (403). All passed.
9. **Passkey results per platform:** software authenticator only (`tests/soft_authenticator.py`, and the browser
   suite). iPhone/iPad Safari, Android Chrome, Windows Hello, macOS, Bitwarden/1Password and hardware security keys:
   Not Run.
10. **Per-AT statuses:** the table above.
11. **Regression results:** full backend suite **350 passed**; updated earlier tests (passkey policy, HTML reset email,
    account-locked alert) passed; upload scan and quarantine unchanged (AT-209); browser suite
    **62 PASS, 0 FAIL** (no serious or critical accessibility violations).
12. **Not executed:** a real Debian 13 / Proxmox LXC upgrade and repair; reboot / LXC restart persistence on a real
    host; `clamav-daemon` restart and freshclam update on a real systemd host; real passkey sign-in on physical
    platforms, browsers, password managers and hardware security keys; real SMTP delivery of the reset email to real
    mail clients.

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
| Real client IP through NPM/Pangolin (AT-39/41) | No reverse proxy here | Set `PD_TRUSTED_PROXY_IPS` to the proxy address; sign in via the public URL; Settings → Security → Access policy → *Your connection* shows your public IP and "via trusted proxy"; Login audit shows it |
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
| OCR on real phone photos | Synthetic benchmark only (no real IDs may be used) | Photograph a non-sensitive printed test card (e.g. the synthetic samples printed on paper) sideways and upside down; check the Text tab confidence, the suggested fields and *Re-run OCR…* |
| Real Arabic and Hindi scans on production (AT-111) | Synthetic samples only | On the LXC run `sudo personaldocs doctor` (no missing language packs), upload a non-sensitive printed Arabic page and a Hindi page, choose **Run OCR…** with Arabic or Hindi, and check the text and search |
| Real weather provider (AT-125/126) | Tested with a fake local provider; no internet from the test container | Enable weather in Settings → Overview & sign-in, **Test connection**, choose a city in the widget; then block outbound access and confirm the stale / unavailable message while the Overview still loads |
| Sign-in designs on real phones (AT-128/130) | Emulated viewports only | Open the sign-in page on an Android phone and an iPhone with each preset and a custom wallpaper; confirm the form comes first and every sign-in method is offered |
| Real authentik server (AT-146…AT-148) | Only a local fake OIDC provider was used | Create an OAuth2/OpenID provider and application in authentik ([setup](guides/authentik.md#setup)), **Test connection**, link an account from My account → Password & security, sign in with authentik, then with 2FA enabled; try an unlinked user (refused), automatic provisioning and a group mapping to Administrator; revoke the link |
| Internet Ready on a real public address (AT-149) | No public DNS, certificate or Internet-accessible staging; the passing path was tested only with mocked responses | Publish a staging instance through NPM or Pangolin with a valid certificate and *Force SSL*, set Deployment exposure to *Published on the Internet*, **Check HTTPS now**; then break one check at a time (HTTP without redirect, `PD_HSTS_SECONDS=0`) and confirm it fails |
| Real host helper on Debian 13 (AT-153…AT-155) | No Debian 13 with systemd and root here; tested with stubbed apt, ufw and reboot commands | `systemctl status personaldocs-host.path`; **Check for updates**, **Install security updates…** (pre-update backup in `<data>/pre-update-backups`, log shown), **Reboot server…** with a running job (preflight, drain, health after the restart); Firewall view with ufw active and inactive |
| freshclam automatic updates on Debian 13 (AT-142) | Not exercised in the container | After install, `systemctl status clamav-freshclam`; wait for an hourly check or press **Update now**; confirm the signature date in Settings → Security → Antivirus and that `doctor` reports the age |
| Real Proxmox/LXC install and upgrade of change set M | As AT-26 | Fresh install on a 2 vCPU / 4 GB LXC (check ClamAV memory use with `free`), install with `--without-antivirus`, and an upgrade from the previous release followed by `repair`; check `status` and `doctor`, then **Scan entire existing library** |
| Document types on real devices (AT-175) | Emulated viewports only | Install the PWA on an Android phone and an iPhone; open a document, **Set type** / **Change…**, review **Previous details** (map, keep, remove) and add a detail by touch; confirm nothing is clipped |
| Change set N upgrade with production data (AT-174) | No real installation here; the migration was tested on synthetic data | Take a backup, `sudo personaldocs upgrade` on a Debian 13 / Proxmox installation with existing documents; then `sudo personaldocs manage document_types report` and `doctor`; check that typed documents kept their type (source *Migrated*), untyped ones stayed untyped, expiry dates and reminders are unchanged and no detail was lost |
| Rich email in real mail clients (AT-177) | No SMTP credentials; rendering checked only from the generated HTML | Configure SMTP, then Settings → Notifications → Templates → **Send a TEST message to yourself** (Email) for an expiry reminder and a security alert; open it in Gmail (web and app), Outlook and Apple Mail, in light and dark mode; check the badges, details table, buttons and the plain-text view; confirm no images load and no document number appears unless `notifications.include_document_number` is on (then masked) |
| Telegram buttons with a real bot (AT-178) | No bot token; Telegram mocked | Link Telegram on the https address, send a TEST and a real expiry reminder; check formatting and the inline buttons open the app after sign-in; on an `http://` test address confirm the links are in the text |
| Real Web Push (AT-181) | No real devices or push services; payload encryption verified in the test with a local subscriber key | On the HTTPS address: Android Chrome, iPhone/iPad (Home Screen app), Firefox and Windows (Edge/Chrome) → My account → Notifications → **Turn on for this device**, **Send test push**; check Minimal / Standard / Detailed on the lock screen, that tapping opens the app page, and that **Remove** stops delivery |
| Notification Center on real devices (AT-194) | Emulated viewports only | Installed PWA on a phone and a tablet: filters, **Show details**, actions and banners by touch; nothing clipped |
| Change set O upgrade (AT-195) | No real installation here | `sudo personaldocs upgrade` on Debian 13; confirm the Python packages were installed, SMTP/Telegram settings, preferences, critical events and expiry schedules unchanged, old notifications still listed with their text and read state |
| Full Debian 13 install of this release | As AT-26 | Fresh install and an upgrade from the previous release; confirm the setup wizard creates only the administrator, existing accounts survive the upgrade and `doctor` reports the OCR language packs |
