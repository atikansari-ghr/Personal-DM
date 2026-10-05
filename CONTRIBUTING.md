# Contributing

Thank you for helping. Personal Documents is maintained by Atik Ansari; contributions are reviewed before merging.

## Ground rules

1. **Synthetic data only.** Never commit real documents, scans, names, ID or passport numbers, OCR text, emails,
   phone numbers, IP addresses of real installations, databases, backups, logs, keys or tokens — not in code, tests,
   fixtures, screenshots or issues. Use the "Sample" family (`Alex Sample`, `Sam Sample`, …) and the generators in
   `tests/fixtures.py` and `tests/e2e/make_parity_fixtures.py`.
2. **Security first.** Permissions are checked on the server for every route; do not rely on hiding controls. Never
   log secrets or document contents. Read [SECURITY.md](SECURITY.md).
3. **Small, reviewable changes** that follow the existing structure (Django apps under `backend/apps/`, React pages
   and components under `frontend/src/`). New settings go through the settings registry
   (`backend/apps/core/registry.py`) with a help link to a guide anchor.
4. **Documentation with the change.** Update the relevant guide in `docs/guides/` (they are bundled in the app),
   `CHANGELOG.md`, and regenerate the settings reference:
   `cd backend && PD_DEBUG=1 ../.venv/bin/python manage.py settings_reference`.
5. **Tests with the change.** Backend tests in `tests/` (pytest), browser checks in `tests/e2e/`. Do not claim
   something works unless a test or a documented manual check shows it.

## Setting up

See [Development and testing](README.md#development-and-testing) in the README.

## Before opening a pull request

```bash
scripts/verify.sh   # compile, Django checks, migrations, settings reference, shellcheck, pytest,
                    # frontend type check and build, privacy/authorship/link check
scripts/e2e.sh      # optional locally, runs in CI: browser flow, accessibility, desktop/tablet/phone parity
```

- Describe what changed and how you tested it.
- Add screenshots only from a test instance with synthetic data.
- Keep commits focused; the maintainer may squash.

## Authorship

The project author and maintainer is Atik Ansari. Contributors are credited in the Git history. Tools and AI
assistants used while writing code are not project authors and must not be listed as such in project metadata or
documentation.

## License

No license has been chosen yet (see the README). By contributing you agree that the maintainer may publish your
contribution under the license eventually chosen for the project.
