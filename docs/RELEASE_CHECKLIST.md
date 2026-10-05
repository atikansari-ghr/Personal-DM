# Release checklist

Copy into the release PR/issue and tick every item. A skipped mandatory item is not a pass.

## Code and tests
- [ ] `scripts/verify.sh` passes locally (compile, checks, migrations, settings reference, shell, pytest incl. OCR/LibreOffice tests, frontend build, hygiene)
- [ ] CI green on the release commit
- [ ] `scripts/e2e.sh` passes against a fresh database (flow 13/13, accessibility 0 serious, parity all steps)
- [ ] `sudo bash tests/installer/test_personal_dm.sh` (one-line installer lifecycle, stubbed) passes
- [ ] OCR benchmark re-run if `ocr.py`/`extraction.py` changed (`scripts/ocr_benchmark.py`), `docs/OCR_BENCHMARK.md` updated
- [ ] `npm audit --omit=dev` in `frontend/` reports no high/critical issues
- [ ] Dependency review: `pip list --outdated`, `npm outdated`, security advisories for Django, cryptography, Pillow, pypdf, PyJWT
- [ ] No critical security, data-loss or core-flow defects open

## Operations (on a Debian 13 LXC)
- [ ] One-line installer on a fresh Debian 13 machine: `bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)"` (needs the repository to be public), then `-- upgrade`, `-- doctor`, `-- status`, `-- backup`, `-- restore DIR --dry-run`
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
- [ ] Real client IP through NPM/Pangolin shown in *Your connection* and the login audit
- [ ] GeoIP update from MaxMind; *Test an address*; failed update keeps the previous database
- [ ] Access policy applied with lock-out confirmation; `personaldocs access-policy off|rollback` recovers
- [ ] Traffic analytics report generated on the LXC
- [ ] Passkey registration and sign-in (2FA and passwordless) on at least one phone and one desktop; TOTP autofill from a password manager
- [ ] Local AI profile test, analysis, assistant and semantic search against a LAN AI server; AI server off → core features unaffected

## Documentation
- [ ] `VERSION` bumped; `CHANGELOG.md` updated
- [ ] `docs/TEST_REPORT.md` updated with environments, commands, results and remaining gaps
- [ ] `docs/TRACEABILITY.md` statuses current
- [ ] `docs/IMPLEMENTATION_STATUS.md` updated
- [ ] Screenshots refreshed if the UI changed

## Public repository (only when the owner decides to publish)
- [x] License: MIT (`LICENSE`, README badge and section)
- [ ] `scripts/privacy_check.sh --history` passes; any secret ever committed has been rotated and the history cleaned with the owner's approval
- [ ] Screenshots in `docs/images/screenshots/` reviewed by eye: only synthetic names, documents, domains and IPs
- [ ] README feature claims match `docs/IMPLEMENTATION_STATUS.md`; no AI assistant listed as author
- [ ] GitHub private vulnerability reporting enabled (SECURITY.md)
- [ ] Repository visibility changed by the owner (Settings → General → Danger zone)
- [ ] Raw installer URL returns the script (`curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh | head -3`)
- [ ] README renders on GitHub: badges, screenshots near the top, one-line install, Ko-fi link; `.github/FUNDING.yml` shows the Sponsor button
- [ ] Topics added by the owner (recommended: document-management, self-hosted, family, ocr, tesseract, django, react, pwa, webauthn, passkeys, local-ai, goaccess, privacy, debian, proxmox)

## Publish
- [ ] Tag `vX.Y.Z` and push; confirm `frontend-dist.tar.gz` is attached to the GitHub release
- [ ] `sudo personaldocs upgrade --ref vX.Y.Z` on production; `personaldocs status` OK
