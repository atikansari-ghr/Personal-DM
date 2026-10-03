# Implementation status

Last updated: 2026-10-03 · Version 0.1.0 (pre-release) · Branch `claude/wizardly-einstein-7gjfr0`

## Summary

Every internal build stage (1–8) is implemented: data model, settings registry, setup, accounts, permissions, delegation, authentication (password, TOTP, Google linking, console recovery), storage, versions, renewals, archive, imports, OCR/previews/extraction, search, UI/PWA/themes, offline/export, reminders over three channels, sharing, IMAP import, audit, backup/restore/integrity, native operations tooling, CI and documentation.

**Release readiness: not yet approved for family production use.** The code and its automated tests are complete for the initial scope. The remaining release gates need environments that were not available in the build container (see Blockers). Per the release rules, the first family release should wait until AT-26 (Debian 13 install/upgrade) and AT-24 (restore on a clean LXC) have been validated on the real Proxmox host.

## Completed (with evidence)

- Backend: 80 automated tests passing (`docs/TEST_REPORT.md`).
- Frontend: type-checked production build; 13-step browser end-to-end flow passing on desktop and mobile viewports; screenshots in `docs/screenshots/`.
- Tooling: `scripts/personaldocs` (install, upgrade, rollback, repair, status, doctor, backup, restore, integrity, recover-admin, setup-token, logs, manage), systemd units, `scripts/verify.sh`, GitHub Actions CI with prebuilt frontend release asset.
- Documentation: 25 bundled guides (`docs/guides/`), requirements, traceability, architecture and 6 ADRs, generated settings reference, test report, release checklist, changelog.

## Blockers (external validation)

| Gate | Needed |
|---|---|
| AT-26 native install, interrupted rerun, upgrade, rollback, repair | A fresh Debian 13 LXC on the Proxmox host, plus the real private repository URL and a read-only token |
| AT-24 restore on a clean LXC | Second LXC (or reinstall) and a mounted NAS share |
| AT-17 live SMTP/Telegram | SMTP relay credentials; a Telegram bot token |
| AT-19 live IMAP | A test mailbox |
| AT-21 live Google | A Google Cloud OAuth client and the public HTTPS origin |
| AT-14 real devices | An Android phone and an iPhone |
| AT-27 resource-constrained load | Benchmark on the 2 vCPU / 4 GB LXC with realistic multi-page scans |

None of these are being reported as passed. Exact steps are in `docs/TEST_REPORT.md`.

## Known limitations and simplifications

- Panels in the three-panel view are fixed-width responsive columns (not draggable).
- The "Active sessions" panel shows the current session and offers "sign out other devices"; it does not list each device.
- Browser offline storage behaviour (quota, account switching) is implemented but covered by manual steps, not automated tests.
- PDF/A conformance relies on OCRmyPDF's own validation (exit status); veraPDF is not run.
- Only expiry events generate external notifications. Other events appear in the audit log.
- Optional folder templates for new members are not provided as a separate feature. Administrators create or import any structure; emoji suggestions apply automatically.
- The audit log records document views on the detail endpoint. File and preview fetches are not individually audited, except downloads.

## Next executable steps

1. Push the repository to the private GitHub remote. Create a fine-grained read-only token.
2. Create a Debian 13 LXC (2 vCPU / 4 GB / 50 GB) and follow `docs/guides/installation.md`. Record results in `TEST_REPORT.md`.
3. Configure NPM or Pangolin, then the NAS backup. Run *Back up now*, then a restore drill on a second LXC.
4. Configure SMTP, Telegram and, optionally, Google. Run the live checks listed in the test report.
5. Run `scripts/bench_processing.py` on the LXC with realistic scans. Tune `processing.heavy_concurrency` and `PD_PROCESS_MEMORY_LIMIT_MB`.
6. Tag `v0.1.0` once the gates pass (`docs/RELEASE_CHECKLIST.md`).

## Session log

- 2026-10-03: initial implementation of the whole scope. Commands run are summarised in `TEST_REPORT.md`. Fixed during verification: a row lock on an outer join in processing; backup folder name collisions and pruning order (now sorted by manifest time); `on_commit` handling in tests; idempotent retry of completed browser import items; Chrome PDF preview blocked by CSP sandbox (sandbox now applied only to non-PDF/image responses).
