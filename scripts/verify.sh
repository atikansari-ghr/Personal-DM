#!/usr/bin/env bash
# Local verification before pushing (CI runs the same steps). Requires a PostgreSQL the tests can use:
#   PD_DB_HOST/PD_DB_USER/PD_DB_PASSWORD (defaults: 127.0.0.1 / personaldocs / "").
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
export PD_TESTING=1
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

step "Python compile"
$PY -m compileall -q backend tests >/dev/null

step "Django system checks"
(cd backend && PD_DEBUG=1 ../$PY manage.py check)

step "Migrations are up to date"
(cd backend && PD_DEBUG=1 ../$PY manage.py makemigrations --check --dry-run >/dev/null) || { echo "Model changes without migrations"; exit 1; }

step "Settings reference is current"
(cd backend && PD_DEBUG=1 ../$PY manage.py settings_reference --check)

step "Shell scripts"
bash -n scripts/personaldocs scripts/verify.sh scripts/dev-server.sh scripts/easy-install.sh scripts/proxmox-create-lxc.sh
if command -v shellcheck >/dev/null; then shellcheck -S warning personal-DM.sh; shellcheck -S error scripts/personaldocs scripts/verify.sh scripts/dev-server.sh scripts/easy-install.sh scripts/proxmox-create-lxc.sh; fi
if [ "$(id -u)" -eq 0 ]; then step "Installer lifecycle (stubbed)"; bash tests/installer/test_personal_dm.sh | tail -1; fi

step "Backend tests"
$PY -m pytest -q -W ignore::UserWarning ${PYTEST_ARGS:-}

step "Frontend unit tests, type check and build"
(cd frontend && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npx vitest run && npm run build)

step "Repository hygiene (no secrets, private data or AI authorship; documentation links resolve)"
scripts/privacy_check.sh
printf '\n\033[32mAll checks passed.\033[0m\n'
