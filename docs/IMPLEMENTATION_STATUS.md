# Implementation status

Last updated: 2026-10-05 · Version 0.1.0 (pre-release)

## Summary

Every internal build stage (1–8) is implemented, plus change set 2026-10 (profile photos, optional Local AI, login audit, real client IP, GeoIP, country/IP access policy, security alerts, traffic analytics, passkeys and authentication policy) and change sets H/I (UI, import destinations, critical/optional notifications, backup schedules, drag and drop and Move to, full-page viewer, mobile/PWA parity, public-release readiness): data model, settings registry, setup, accounts, permissions, delegation, authentication (password, TOTP, Google linking, console recovery), storage, versions, renewals, archive, imports, OCR/previews/extraction, search, UI/PWA/themes, offline/export, reminders over three channels, sharing, IMAP import, audit, backup/restore/integrity, native operations tooling, CI and documentation.

**Release readiness: not yet approved for family production use.** The code and its automated tests are complete for the initial scope. The remaining release gates need environments that were not available in the build container (see Blockers). Per the release rules, the first family release should wait until AT-26 (Debian 13 install/upgrade) and AT-24 (restore on a clean LXC) have been validated on the real Proxmox host.

## Completed (with evidence)

- Backend: 219 automated tests passing (incl. `test_security` 30, `test_ai` 15, `test_passkeys` 14, `test_photos` 9, `test_browser_moves` 11, `test_notification_policy` 7, `test_backup_schedule` 3, `test_preferences` 3). Frontend: 13 unit tests (vitest). (`docs/TEST_REPORT.md`).
- Frontend: type-checked production build; 13-step browser end-to-end flow; 24 parity/viewer checks (`tests/e2e/parity.mjs`) at desktop, tablet, phone portrait and landscape; accessibility audit with 0 serious/critical violations in 3 themes; README screenshots in `docs/images/screenshots/`.
- Tooling: guided installers `scripts/proxmox-create-lxc.sh` (Proxmox host: creates the container) and `scripts/easy-install.sh` (inside the LXC: asks all parameters and installs, configures, connects the NAS, backs up and checks); `scripts/personaldocs` (install, upgrade, rollback, repair, status, doctor, backup, restore, integrity, recover-admin, setup-token, logs, manage, nas-apply), systemd units, `scripts/verify.sh`, GitHub Actions CI with prebuilt frontend release asset.
- New migrations: `security.0001_initial`, `ai.0001_initial`, `accounts.0003_profile_photo`, `accounts.0004_passkeys` (additive; applied by `personaldocs upgrade`).
- Documentation: 30 bundled guides, `docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md`, README, CONTRIBUTING, SECURITY (`docs/guides/`), requirements, traceability, architecture and 9 ADRs, generated settings reference, test report, release checklist, changelog.

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
| Public release | The owner's decision on a license and on making the repository public (not done; see Next steps) |
| AT-27 resource-constrained load | Benchmark on the 2 vCPU / 4 GB LXC with realistic multi-page scans |

None of these are being reported as passed. Exact steps are in `docs/TEST_REPORT.md`.

## Known limitations and simplifications

- The six annotated reference screenshots mentioned in the change prompt arrived during the work as chat images; they were used as requirements only and are not committed.
- Drag and drop needs a mouse/trackpad; touch screens use **Move to…** (same server checks).
- PDF.js renders pages as images (no selectable text layer in the viewer); the recognised text is in the **Text** tab.

- Browser offline storage behaviour (quota, account switching) is implemented but covered by manual steps, not automated tests.
- The audit log records document views on the detail endpoint. File and preview fetches are not individually audited, except downloads.
- The accessibility audit is automated (axe-core, WCAG 2.1 A/AA) and clean; a manual screen-reader review has not been done.

## Next executable steps

1. Push the repository to the private GitHub remote. Create a fine-grained read-only token.
2. On the Proxmox host run `scripts/proxmox-create-lxc.sh` (or create a Debian 13 LXC and run `scripts/easy-install.sh` inside it), following `docs/guides/installation.md#guided`. Record results in `TEST_REPORT.md`.
3. Configure NPM or Pangolin, then check the NAS connection in Settings → Storage & backup. Run *Back up now*, then a restore drill on a second LXC.
4. Configure SMTP, Telegram and, optionally, Google. Run the live checks listed in the test report.
5. Run `scripts/bench_processing.py` on the LXC with realistic scans. Tune `processing.heavy_concurrency` and `PD_PROCESS_MEMORY_LIMIT_MB`.
6. Tag `v0.1.0` once the gates pass (`docs/RELEASE_CHECKLIST.md`).
7. Public release (owner decisions): choose a license (add `LICENSE`), enable GitHub private vulnerability reporting, run `scripts/privacy_check.sh --history`, then change the repository visibility in GitHub settings.

## Session log

- 2026-10-05 (change sets H/I): folder tree identity, validated file-type icons, atomic and serialised moves (fixed: members could not move their own documents; concurrent opposite moves could orphan folders; moves into archived folders), drag and drop and Move to…, PDF.js viewer with zoom/fit, import destination picker with exact preview, dashboard widget editor, critical/optional notification catalogue with templates and bulk summaries, daily/weekly/monthly backups, tablet overflow fixes, malformed-filter 500 fixed, open-redirect hardening of `?next=`, dependency upgrades (PDF.js 6.4 for GHSA-hq66-cqwq-w95j, React Router 7.18 for GHSA-wrjc-x8rr-h8h6), public README/guides/SECURITY/CONTRIBUTING, privacy check (tree and history clean; one real LAN address replaced in code/tests).

- 2026-10-05: change set 2026-10 implemented (AT-31..AT-50, passkeys) with 74 new tests; docs, traceability, settings reference and upgrade notes updated. Live validation of proxies, MaxMind, AI servers and real authenticators is listed under Blockers.

- 2026-10-04: closed the previous limitations — resizable panels (mouse and keyboard, remembered per account), per-device session list with individual sign-out, optional folder templates for new members, event notifications (access granted, import finished, processing failed, backup failed, integrity problems), PDF/A-2b validation (veraPDF when installed, structural check otherwise), automated accessibility audit with a CI end-to-end job. Fixed during verification: an outbox duplicate-key insert could break an enclosing transaction (now a savepoint); changing your own password signed out the current device (now only other devices).

- 2026-10-03: initial implementation of the whole scope. Commands run are summarised in `TEST_REPORT.md`. Fixed during verification: a row lock on an outer join in processing; backup folder name collisions and pruning order (now sorted by manifest time); `on_commit` handling in tests; idempotent retry of completed browser import items; Chrome PDF preview blocked by CSP sandbox (sandbox now applied only to non-PDF/image responses).
- 2026-10-04: NAS connection moved into Settings → Storage & backup (NFS or SMB, validated fields, Connect/Disconnect, live status and actionable errors). The web app writes a request file; a path-activated root helper (standard library only, re-validates every field, fixed mount unit `/mnt/pdnas`, SMB credentials in a root-only file) mounts the share, creates the backup folder, checks write access and the app adopts it as the backup destination. New guided installers ask every parameter and perform the whole LXC installation; `manage.py apply_settings` applies validated settings from a file.
