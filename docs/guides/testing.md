<!-- audience: admin -->
# Testing and release maintenance

## Local verification {#verify}

```
scripts/verify.sh
```

Runs Python byte-compilation and Django checks, migration drift check, the backend test suite (pytest), settings-reference freshness, shell syntax checks, the frontend type check and production build. Run it before every push; CI repeats it.

## Test layout {#layout}

- `tests/test_*.py` — API, permission, processing, reminder, auth, import, backup and email-import tests mapped to acceptance IDs (see `docs/TRACEABILITY.md`). Tests marked `tools` need Tesseract/OCRmyPDF/LibreOffice.
- `tests/e2e/flow.mjs` — browser flow (Playwright/Chromium) against a running instance with a fresh database: setup with the Main Administrator and the optional demo members, sign-in, a passport uploaded and recognised with **Run OCR**, the Overview and more; saves screenshots to `docs/screenshots/`.
- `tests/e2e/parity.mjs` — tablet/phone parity and feature checks (selective OCR and review queue, Overview customize, weather with a fake local provider, holidays, every sign-in design).
- `tests/test_selective_ocr.py`, `tests/test_overview.py` and `tests/test_family_setup.py` — change sets K and L; `test_overview.py` starts a fake local weather server, so no internet access is needed.
- `tests/e2e/a11y.mjs` — accessibility audit with axe-core (WCAG 2.1 A/AA rules) over the main screens, a document panel, the share dialog and mobile layouts, in all three themes, plus a keyboard check of the resizable panels. Run it after `flow.mjs` on the same instance (`cd tests/e2e && npm ci` first). It fails on serious or critical violations and writes `docs/a11y-report.json`.

All fixtures are synthetic. Never add real documents or names. Screenshots use only the demo labels A. Ansari, Mom, Son1, Son2, Son3 and Daughter, added in the optional setup step (see [names in screenshots](setup.md#demo-names)).

## Releasing {#release}

Follow `docs/RELEASE_CHECKLIST.md`: bump `VERSION`, update `CHANGELOG.md`, run verification, tag `vX.Y.Z`, and let CI attach the built frontend (`frontend-dist.tar.gz`) to the release so servers do not need to build it.
