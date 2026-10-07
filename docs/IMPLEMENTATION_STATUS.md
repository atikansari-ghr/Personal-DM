# Implementation status

Last updated: 2026-10-07 · Version 0.1.0 (pre-release)

## Summary

Every internal build stage (1–8) is implemented, plus change set 2026-10 (profile photos, optional Local AI, login audit, real client IP, GeoIP, country/IP access policy, security alerts, traffic analytics, passkeys and authentication policy) change sets H/I (UI, import destinations, critical/optional notifications, backup schedules, drag and drop and Move to, full-page viewer, mobile/PWA parity, public-release readiness) and change set J (portal overflow menus with rename/archive/permanent delete, folder icons, List/Thumbnails/Details views with sorting, desktop file-and-folder drop with hierarchy, own library first, measured OCR preprocessing with confidence and re-run, "No expiry", the public title, the one-line installer `personal-DM.sh` and a LinkedIn-ready README), change set K (selective multilingual OCR with a policy per document type, source/page/language selection, OCR review queue and Remove OCR data; the customizable Overview with Today/Hijri, weather, month calendar and holidays; sign-in page designs and custom wallpaper) change set L (setup creates only the Main Administrator, optional family members) and change set M (ClamAV antivirus with quarantine, authentik sign-in, the Administrator role, the security center with Internet Ready, the Basic Internet Security Test, OS security updates and controlled reboot through a root host helper, firewall monitoring, the Security Health score, security record retention and Storage Health): data model, settings registry, setup, accounts, permissions, delegation, authentication (password, TOTP, Google linking, console recovery), storage, versions, renewals, archive, imports, OCR/previews/extraction, search, UI/PWA/themes, offline/export, reminders over three channels, sharing, IMAP import, audit, backup/restore/integrity, native operations tooling, CI and documentation.

**Release readiness: not yet approved for family production use.** The code and its automated tests are complete for the initial scope. The remaining release gates need environments that were not available in the build container (see Blockers). Per the release rules, the first family release should wait until AT-26 (Debian 13 install/upgrade) and AT-24 (restore on a clean LXC) have been validated on the real Proxmox host.

**Acceptance scenarios AT-01…AT-160** (150 scenarios; the numbers AT-51…AT-60 were never assigned). The status of
each one is in [TRACEABILITY.md](TRACEABILITY.md). Summary, based on the latest recorded runs in
[TEST_REPORT.md](TEST_REPORT.md):

| Result | Count | Scenarios |
|---|---|---|
| Passed (automated tests, or for AT-136 a documented review) | 116 | all scenarios not listed below |
| Passed in automated tests; real-environment validation still pending | 28 | AT-17, 19, 21, 31, 39, 40, 69, 71, 76, 83, 90, 91, 98, 99, 111, 122, 125, 130, 134, 140, 142, 146, 147, 148, 149, 153, 154, 155 |
| Blocked (external environment) | 5 | AT-14, AT-26 (Pending-env); AT-24, AT-27, AT-30 (Partial: the remaining part needs a real Debian 13 LXC) |
| Not run (manual steps, not automated) | 1 | AT-15 |

The pending real-environment parts (real hardware, real providers or credentials) are listed under Blockers below and
are not reported as passed.

## Completed (with evidence)

- Change set M (2026-10-07): new backend tests `tests/test_antivirus.py` (9, fake clamd with the EICAR test string,
  AT-138…AT-145, AT-160), `tests/test_antivirus_live.py` (1, executed against a **real ClamAV 1.5.4 daemon** in the
  development container: EICAR detected and quarantined, a clean file reported clean; skipped where no clamd runs),
  `tests/test_authentik.py` (5, fake OIDC provider with real RS256 tokens and PKCE, AT-146…AT-148) and
  `tests/test_security_center.py` (17, AT-149…AT-160 with stubbed HTTPS responses and host commands): all passed.
  Full backend suite: **296 passed** tests. `scripts/e2e.sh`: **51 PASS, 0 FAIL**, adding antivirus quarantine and
  release with EICAR, the security center overview, security test, storage, OS updates, firewall and records views,
  and the authentik settings and sign-in button; the accessibility audit includes the security views.

- Change sets K and L (2026-10-06): new backend tests `tests/test_selective_ocr.py` (11, AT-101…AT-115),
  `tests/test_overview.py` (15, AT-116…AT-130 backend parts, including a fake local weather server) and
  `tests/test_family_setup.py` (AT-131…AT-135, AT-137); the full backend suite passes (for the current count see the
  `scripts/verify.sh` output). `scripts/e2e.sh`: 48 PASS, 0 FAIL, covering the setup wizard (administrator plus
  optional members), manual OCR on a passport, selective OCR and the review queue, Overview customize / weather (fake
  local provider) / calendar / holidays, holiday countries and corrections, all five sign-in designs at desktop and
  phone, and the accessibility audit (now also `/ocr-review` and `/settings/overview`) with 0 blocking violations in
  3 themes. OCR contrast fix with a sparse-ink regression sample; benchmark mean F1 0.61 → 0.97 (12 samples).
- Backend: 232 automated tests passing (incl. `test_security` 30, `test_ai` 15, `test_passkeys` 14, `test_photos` 9, `test_browser_moves` 11, `test_browsing_v3` 7, `test_ocr_quality` 6, `test_notification_policy` 7, `test_backup_schedule` 3, `test_preferences` 3). Frontend: 17 unit tests (vitest). One-line installer: 18 stubbed lifecycle checks. OCR benchmark: mean F1 0.61 → 0.97. (`docs/TEST_REPORT.md`).
- Frontend: type-checked production build; browser end-to-end flow (`tests/e2e/flow.mjs`) and parity/viewer/browsing checks (`tests/e2e/parity.mjs`; 48 PASS, 0 FAIL in `scripts/e2e.sh` on 2026-10-06; 31/31 at change set J) at desktop, tablet, phone portrait and landscape; accessibility audit with 0 serious/critical violations in 3 themes; README screenshots in `docs/images/screenshots/`.
- Tooling: one-line installer `personal-DM.sh` (menu + commands, delegates to the tools below); guided installers `scripts/proxmox-create-lxc.sh` (Proxmox host: creates the container) and `scripts/easy-install.sh` (inside the LXC: asks all parameters and installs, configures, connects the NAS, backs up and checks); `scripts/personaldocs` (install, upgrade, rollback, repair, status, doctor, backup, restore, integrity, recover-admin, setup-token, logs, manage, nas-apply), systemd units, `scripts/verify.sh`, GitHub Actions CI with prebuilt frontend release asset.
- New migrations: `security.0001_initial`, `ai.0001_initial`, `accounts.0003_profile_photo`, `accounts.0004_passkeys`, `library.0004_ocr_quality_no_expiry`, `library.0005_subfolder_default_icon` (data: automatic sub-folder icons → 📁), `core.0002_public_title` (data: old default name → new title), `library.0006_selective_ocr`, `library.0007_selective_ocr_defaults` (data: existing installations keep automatic OCR with AI allowed; new installations Manual), `core.0003_overview` (weather cache, holiday corrections), `accounts.0005_administrator_role`, `accounts.0006_external_identity` (authentik links), `library.0008_antivirus` (data: existing files marked Not scanned), `security.0002_antivirus`, `security.0003_security_center` — applied by `personaldocs upgrade`.
- Documentation: 35 bundled guides (new: antivirus, authentik, security center), `docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md`, README, CONTRIBUTING, SECURITY (`docs/guides/`), requirements, traceability, architecture and 12 ADRs, generated settings reference, test report, release checklist, changelog.

## Blockers (external validation)

| Gate | Needed |
|---|---|
| AT-26 native install, interrupted rerun, upgrade, rollback, repair | A fresh Debian 13 LXC on the Proxmox host, plus the real private repository URL and a read-only token |
| AT-24 restore on a clean LXC | Second LXC (or reinstall) and a mounted NAS share |
| Guided installers and NAS mounting on real hosts | A Proxmox host, a privileged LXC with `mount=nfs;cifs`, and a real NFS/SMB share (only dry runs and a simulated `systemctl` were possible here) |
| AT-17 live SMTP/Telegram | SMTP relay credentials; a Telegram bot token |
| AT-19 live IMAP | A test mailbox |
| AT-21 live Google | A Google Cloud OAuth client and the public HTTPS origin |
| AT-14 real devices | An Android phone and an iPhone |
| AT-39/41 real proxy IPs | Sign-ins through the real NPM / Pangolin (Newt) with `PD_TRUSTED_PROXY_IPS` set; check *Your connection* |
| AT-40/49 MaxMind download | A MaxMind account ID and GeoLite2 license key (download path tested only with a simulated server) |
| AT-31..36 live AI servers | LM Studio and/or Ollama on the LAN with a text and an embedding model (tested against a fake OpenAI/Ollama server) |
| Passkeys / TOTP autofill on real clients | iPhone, Android, Windows Hello, Bitwarden/1Password on the HTTPS origin (tested with a software WebAuthn authenticator) |
| AT-76/83 real devices | Installed PWA on a real Android phone and iPhone/iPad (automated checks used emulated viewports) |
| AT-69 real delivery | SMTP and Telegram credentials to see the new templates in a real inbox/chat |
| Public release | Making the repository public (owner action in GitHub settings; license chosen: MIT) |
| AT-98/99 one-line installer for real | A fresh Debian 13 VM/LXC with systemd, and a **public** repository so the raw URL works (tested here with stubbed system commands only) |
| AT-90/91 real desktop drag | Dragging a folder from Windows Explorer / Finder into Chrome, Edge, Firefox and Safari (tested with a synthetic DataTransfer and unit-tested folder walk) |
| AT-111 real Arabic/Hindi scans | Non-sensitive printed Arabic and Hindi test pages on the production server (only synthetic samples were used) |
| AT-125 real weather provider | Outbound internet access from the LXC to Open-Meteo (tested with a fake local provider) |
| AT-128/130 real phones | Sign-in designs on a real Android phone and iPhone (emulated viewports only) |
| AT-27 resource-constrained load | Benchmark on the 2 vCPU / 4 GB LXC with realistic multi-page scans |
| AT-146..148 real authentik | A real authentik server with an OAuth2/OpenID provider (tested against a local fake OIDC provider with real RS256 tokens and PKCE) |
| AT-149 Internet Ready on the real path | Public DNS, a valid TLS certificate and an Internet-accessible staging site (the passing path was tested only with mocked responses) |
| AT-153..155 real host helper | Debian 13 with systemd: `personaldocs-host.path` as root installing apt security updates, rebooting and inspecting ufw/nftables (tested with stubbed commands only) |
| AT-140/142 ClamAV on Debian 13 | `clamav-daemon` and automatic `clamav-freshclam` updates on Debian 13 (the live scan test ran against ClamAV 1.5.4 in the development container; freshclam updates were not exercised) |
| Change set M install/upgrade | A real Proxmox/LXC install and an upgrade from the previous release: ClamAV memory use on 4 GB, `--without-antivirus`, host helper installation, `status`/`doctor` output |

None of these are being reported as passed. Exact steps are in `docs/TEST_REPORT.md`.

## Known limitations and simplifications

- The six annotated reference screenshots mentioned in the change prompt arrived during the work as chat images; they were used as requirements only and are not committed.
- Drag and drop needs a mouse/trackpad; touch screens use **Move to…** (same server checks).
- PDF.js renders pages as images (no selectable text layer in the viewer); the recognised text is in the **Text** tab.
- English, Arabic and Hindi are offered by default; Arabic and Hindi recognition was only checked with synthetic
  samples, not with real scans. Strong glare is still the weakest case in the benchmark (F1 0.70): ink that is
  washed out in the photo cannot be recovered, so the guide tells people to retake such photos.
- Folders dropped from the desktop in a browser without the File and Directory Entries API are reported and not
  uploaded; such users should use **Import folder**.
- The four annotated V3 screenshots (menu clipping, rename/delete, sub-folder icon/views, drag-drop, OCR junk) were
  used as requirements only and are not committed.

- Browser offline storage behaviour (quota, account switching) is implemented but covered by manual steps, not automated tests.
- The audit log records document views on the detail endpoint. File and preview fetches are not individually audited, except downloads.
- The accessibility audit is automated (axe-core, WCAG 2.1 A/AA) and clean; a manual screen-reader review has not been done.
- Antivirus is fail-open: when ClamAV is down, files stay usable and are marked Not scanned. Archives are scanned as
  one file with ClamAV's limits; a Clean archive does not prove each inner file was inspected.
- The Basic Internet Security Test is a baseline of this application and this host only. It is not a penetration test
  and does not prove the system is free of vulnerabilities. The Security Health score is a summary, not a certification.
- Firewall support is monitoring only; rules are changed on the host.
- The new `personaldocs doctor` and `status` checks (ClamAV, signatures, host helper, Internet HTTPS, storage
  thresholds, pending reboot) have no dedicated automated test; they are covered only by the pending Debian 13 run.

## Next executable steps

1. Push the repository to the private GitHub remote. Create a fine-grained read-only token.
2. On the Proxmox host run `scripts/proxmox-create-lxc.sh` (or create a Debian 13 LXC and run `scripts/easy-install.sh` inside it), following `docs/guides/installation.md#guided`. Record results in `TEST_REPORT.md`.
3. Configure NPM or Pangolin, then check the NAS connection in Settings → Storage & backup. Run *Back up now*, then a restore drill on a second LXC.
4. Configure SMTP, Telegram and, optionally, Google. Run the live checks listed in the test report.
5. On the LXC check `personaldocs status` (ClamAV, freshclam, host helper), run **Scan entire existing library**,
   **Check for updates** and the **Basic Internet Security Test**, and connect a test authentik provider; record the
   results in `TEST_REPORT.md`.
6. Run `scripts/bench_processing.py` on the LXC with realistic scans. Tune `processing.heavy_concurrency` and `PD_PROCESS_MEMORY_LIMIT_MB`.
7. Tag `v0.1.0` once the gates pass (`docs/RELEASE_CHECKLIST.md`).
8. Public release (owner decisions): enable GitHub private vulnerability reporting, run `scripts/privacy_check.sh --history`, then change the repository visibility in GitHub settings.

## Session log

- 2026-10-07 (change set M): ClamAV antivirus (background scan over the local clamd socket, fail-open, statuses,
  quarantine with main-administrator release and delete, size limit, library scan with pause/resume/cancel and
  schedule, freshclam and Update now, critical alerts, quarantine excluded from backups and integrity reports),
  authentik OpenID Connect sign-in (PKCE, state, nonce, explicit linking, provisioning, group-to-role mapping), the
  Administrator role, the security center (Internet Ready and HSTS, Basic Internet Security Test, OS security updates
  and controlled reboot through the root host helper, firewall monitoring, Security Health score, security record
  retention and purge, Storage Health and safe cleanup), installer, `status` and `doctor` additions; Settings →
  Security reorganised (access policy under Security → Access policy); the "administrators" 2FA policy now covers
  Administrators.

- 2026-10-06 (change sets K and L): selective OCR (policy per type Disabled/Manual/Automatic, languages, expected
  fields and AI permission; custom types; source, page and language selection; front and back as one job; states,
  cancel, Mark reviewed, Remove OCR data; OCR review queue; limits and pause; language packs via doctor/repair),
  Overview widgets (Today with Hijri via `hijridate`, weather proxy with cache, month calendar, upcoming holidays from
  the `holidays` library with administrator corrections, Documents summary, Shared with me, Recent activity;
  Customize Overview with sizes and styles), sign-in designs (five bundled presets, custom wallpaper and logo,
  re-encoded and stripped of metadata), and the admin-only setup with optional members. Fixed: the OCR contrast
  stretch clipped sparse ink and erased text (regression sample added); calendar accessibility roles.

- 2026-10-05 (change set J): portal overflow menus (fixed: menus clipped by the breadcrumb bar and scrolling panels; keyboard-opened menus did not receive focus), document rename/archive/permanent delete and folder rename/icon/share/archive from the menu, standard 📁 for sub-folders with an approved icon picker and data migration, List/Thumbnails/Details with server-side sorting saved per account, desktop file-and-folder drop with hierarchy, own library first and expanded, OCR rework (root causes: EXIF orientation ignored, no rotation/skew handling, month-first dates rejected, header/value columns not paired; benchmark 0.61 → 0.97), "No expiry" documents, public title, demo owner (now the demo label A. Ansari), `personal-DM.sh`, LinkedIn-ready README, Ko-fi `FUNDING.yml`.

- 2026-10-05 (change sets H/I): folder tree identity, validated file-type icons, atomic and serialised moves (fixed: members could not move their own documents; concurrent opposite moves could orphan folders; moves into archived folders), drag and drop and Move to…, PDF.js viewer with zoom/fit, import destination picker with exact preview, dashboard widget editor, critical/optional notification catalogue with templates and bulk summaries, daily/weekly/monthly backups, tablet overflow fixes, malformed-filter 500 fixed, open-redirect hardening of `?next=`, dependency upgrades (PDF.js 6.4 for GHSA-hq66-cqwq-w95j, React Router 7.18 for GHSA-wrjc-x8rr-h8h6), public README/guides/SECURITY/CONTRIBUTING, privacy check (tree and history clean; one real LAN address replaced in code/tests).

- 2026-10-05: change set 2026-10 implemented (AT-31..AT-50, passkeys) with 74 new tests; docs, traceability, settings reference and upgrade notes updated. Live validation of proxies, MaxMind, AI servers and real authenticators is listed under Blockers.

- 2026-10-04: closed the previous limitations — resizable panels (mouse and keyboard, remembered per account), per-device session list with individual sign-out, optional folder templates for new members, event notifications (access granted, import finished, processing failed, backup failed, integrity problems), PDF/A-2b validation (veraPDF when installed, structural check otherwise), automated accessibility audit with a CI end-to-end job. Fixed during verification: an outbox duplicate-key insert could break an enclosing transaction (now a savepoint); changing your own password signed out the current device (now only other devices).

- 2026-10-03: initial implementation of the whole scope. Commands run are summarised in `TEST_REPORT.md`. Fixed during verification: a row lock on an outer join in processing; backup folder name collisions and pruning order (now sorted by manifest time); `on_commit` handling in tests; idempotent retry of completed browser import items; Chrome PDF preview blocked by CSP sandbox (sandbox now applied only to non-PDF/image responses).
- 2026-10-04: NAS connection moved into Settings → Storage & backup (NFS or SMB, validated fields, Connect/Disconnect, live status and actionable errors). The web app writes a request file; a path-activated root helper (standard library only, re-validates every field, fixed mount unit `/mnt/pdnas`, SMB credentials in a root-only file) mounts the share, creates the backup folder, checks write access and the app adopts it as the backup destination. New guided installers ask every parameter and perform the whole LXC installation; `manage.py apply_settings` applies validated settings from a file.
