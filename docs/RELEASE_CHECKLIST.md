# Release checklist

Copy into the release PR/issue and tick every item. A skipped mandatory item is not a pass.

## Code and tests
- [ ] `scripts/verify.sh` passes locally (compile, checks, migrations, settings reference, shell, pytest incl. OCR/LibreOffice tests, frontend build, hygiene)
- [ ] CI green on the release commit
- [ ] `node tests/e2e/flow.mjs` passes against a fresh database (13/13)
- [ ] Dependency review: `pip list --outdated`, `npm outdated`, security advisories for Django, cryptography, Pillow, pypdf, PyJWT
- [ ] No critical security, data-loss or core-flow defects open

## Operations (on a Debian 13 LXC)
- [ ] Fresh install from the private repository with a read-only token; token absent from logs and `ps`
- [ ] Interrupted install rerun completes
- [ ] Upgrade from the previous tag: pre-upgrade backup taken, migrations applied, health OK
- [ ] Failed upgrade simulation leaves the previous release running
- [ ] Rollback refused when the schema is incompatible, works when compatible
- [ ] `personaldocs repair` on a deliberately broken install (stopped service, wrong permissions) succeeds without data loss
- [ ] Backup to NAS verified; NAS unmounted → backup refused with a clear message
- [ ] Restore drill on a clean LXC: sign-in, permissions, versions, settings, integration secrets
- [ ] `personaldocs integrity` clean

## Integrations (when configured)
- [ ] SMTP test email and a real expiry reminder (no document number in the message)
- [ ] Telegram link and reminder
- [ ] IMAP import idempotent across two polls
- [ ] Google link, sign-in, unlink; unknown account refused

## Documentation
- [ ] `VERSION` bumped; `CHANGELOG.md` updated
- [ ] `docs/TEST_REPORT.md` updated with environments, commands, results and remaining gaps
- [ ] `docs/TRACEABILITY.md` statuses current
- [ ] `docs/IMPLEMENTATION_STATUS.md` updated
- [ ] Screenshots refreshed if the UI changed

## Publish
- [ ] Tag `vX.Y.Z` and push; confirm `frontend-dist.tar.gz` is attached to the GitHub release
- [ ] `sudo personaldocs upgrade --ref vX.Y.Z` on production; `personaldocs status` OK
