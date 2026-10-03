# Test report

Date: 2026-10-03. Revision: the branch head at the commit that adds this file.

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
| `pytest` (`tests/`) | **81 passed**, 0 failed, 0 skipped (OCR and LibreOffice tests ran) |
| `node tests/e2e/flow.mjs` against gunicorn + worker on a fresh database | **13/13 steps passed** (`docs/screenshots/e2e-results.json`) |

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
| Restore into a clean LXC (AT-24) | Same | Back up on server A, install on server B, `personaldocs restore <dir>`; verify sign-in, permissions, document versions, SMTP password still decrypts |
| Real SMTP / Telegram delivery (AT-17) | No provider credentials | Configure in Settings → Connections, use *Send test* buttons, then *Run reminder check now* with a document expiring in 7 days |
| Real IMAP mailbox (AT-19) | No mailbox credentials | Add a test mailbox (e.g. a local Dovecot or an app-password Gmail account), send a matching attachment, *Check now* twice and confirm a single import |
| Live Google sign-in (AT-21) | No Google Cloud project | Follow `guides/google.md`, link an account, sign in through Google, unlink |
| Real-device PWA (AT-14) | No physical devices | Install on Android Chrome and iOS Safari; test camera upload, share-in (Android) and share-out; record results |
| Browser offline behaviour (AT-15) | Not automated | Save a document offline, go offline (DevTools), open it; sign out and in as another user (not listed); revoke access, reconnect, confirm removal |
| Resource-constrained load and disk-full (AT-27) | Host differs | On the LXC run `scripts/bench_processing.py` with `N=200` (instructions in the file header) while watching `free`/`top`; fill the disk to <512 MB free and confirm uploads are refused with a clear message |
| Accessibility audit | Not run | Run axe or Lighthouse against each page in all three themes |
| PDF/A validation with veraPDF | Not installed | `verapdf derivatives/**/searchable.pdf` |
