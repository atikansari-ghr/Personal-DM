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
if command -v shellcheck >/dev/null; then shellcheck -S error scripts/personaldocs scripts/verify.sh scripts/dev-server.sh scripts/easy-install.sh scripts/proxmox-create-lxc.sh; fi

step "Backend tests"
$PY -m pytest -q -W ignore::UserWarning ${PYTEST_ARGS:-}

step "Frontend type check and build"
(cd frontend && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npm run build)

step "Repository hygiene (no secrets or private data committed)"
if git ls-files | grep -E '(^|/)(references/|.*\.(pgdump|dump|sqlite3|env)$|encryption\.key|secret_key|github-token)' | grep -v 'personaldocs.env.example'; then
  echo "Private or secret files are tracked"; exit 1
fi
if git grep -nE '(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (RSA |OPENSSH )?PRIVATE KEY-----)' -- . ':!scripts/verify.sh' ':!scripts/personaldocs'; then
  echo "Possible credential committed"; exit 1
fi
printf '\n\033[32mAll checks passed.\033[0m\n'
