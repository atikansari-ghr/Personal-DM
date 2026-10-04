<!-- audience: admin -->
# Testing and release maintenance

## Local verification {#verify}

```
scripts/verify.sh
```

Runs Python byte-compilation and Django checks, migration drift check, the backend test suite (pytest), settings-reference freshness, shell syntax checks, the frontend type check and production build. Run it before every push; CI repeats it.

## Test layout {#layout}

- `tests/test_*.py` — API, permission, processing, reminder, auth, import, backup and email-import tests mapped to acceptance IDs (see `docs/TRACEABILITY.md`). Tests marked `tools` need Tesseract/OCRmyPDF/LibreOffice.
- `tests/e2e/flow.mjs` — browser flow (Playwright/Chromium) against a running instance with a fresh database; saves screenshots to `docs/screenshots/`.
- `tests/e2e/a11y.mjs` — accessibility audit with axe-core (WCAG 2.1 A/AA rules) over the main screens, a document panel, the share dialog and mobile layouts, in all three themes, plus a keyboard check of the resizable panels. Run it after `flow.mjs` on the same instance (`cd tests/e2e && npm ci` first). It fails on serious or critical violations and writes `docs/a11y-report.json`.

All fixtures are synthetic. Never add real documents or names.

## Releasing {#release}

Follow `docs/RELEASE_CHECKLIST.md`: bump `VERSION`, update `CHANGELOG.md`, run verification, tag `vX.Y.Z`, and let CI attach the built frontend (`frontend-dist.tar.gz`) to the release so servers do not need to build it.
