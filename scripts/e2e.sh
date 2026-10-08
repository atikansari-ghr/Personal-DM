#!/usr/bin/env bash
# Browser end-to-end flow, accessibility audit and desktop/tablet/mobile parity checks against a throwaway instance.
# Needs an EMPTY database configured through PD_DB_* (it runs the first-run setup), Chromium for Playwright,
# and `npm ci` in tests/e2e. Usage: scripts/e2e.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
export PD_DEBUG=1 PD_PUBLIC_ORIGIN=http://localhost:8000
export PD_DATA_DIR=${PD_DATA_DIR:-$(mktemp -d)/data} PD_CONFIG_DIR=${PD_CONFIG_DIR:-$(mktemp -d)/config}
LOGDIR=$(mktemp -d)
(cd backend && ../$PY manage.py migrate --noinput >/dev/null)
# Antivirus: use a local clamd when one runs, otherwise the fake clamd from the tests (EICAR test string only).
CLAMD_SOCK=/run/clamav/clamd.ctl
FAKE_CLAMD=""
if [ ! -S "$CLAMD_SOCK" ]; then
  CLAMD_SOCK="$LOGDIR/clamd.sock"
  $PY tests/fake_clamd.py "$CLAMD_SOCK" >"$LOGDIR/clamd.log" 2>&1 &
  FAKE_CLAMD=$!
  for _ in $(seq 1 20); do [ -S "$CLAMD_SOCK" ] && break; sleep 0.5; done
fi
(cd backend && ../$PY manage.py shell -c "from apps.core import config; config.set_value('antivirus.socket', '$CLAMD_SOCK')" >/dev/null)
TOKEN=$(cd backend && ../$PY manage.py setup_token | sed -n 2p | tr -d ' ')
FIXTURE="$LOGDIR/scan.pdf"
$PY -c "import sys; sys.path.insert(0, 'tests'); from fixtures import make_image_pdf; open('$FIXTURE', 'wb').write(make_image_pdf('SAMPLE DOCUMENT - NOT A REAL PASSPORT\nSurname ANSARI  Given names AB\nDate of issue 19 Oct 2016\nDate of expiry 18 Oct 2026'))"
(cd backend && exec ../.venv/bin/gunicorn personaldocs.wsgi -b 127.0.0.1:8000 -w 2 --timeout 300 >"$LOGDIR/web.log" 2>&1) &
WEB=$!
(cd backend && exec ../$PY manage.py worker >"$LOGDIR/worker.log" 2>&1) &
WORKER=$!
trap 'kill $WEB $WORKER $FAKE_CLAMD 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break; sleep 1; done
BASE=http://localhost:8000 SETUP_TOKEN="$TOKEN" FIXTURE="$FIXTURE" node tests/e2e/flow.mjs
BASE=http://localhost:8000 node tests/e2e/a11y.mjs
$PY tests/e2e/make_parity_fixtures.py "$LOGDIR/parity" >/dev/null
BASE=http://localhost:8000 PARITY="$LOGDIR/parity" node tests/e2e/parity.mjs
# application-wide layout audit at seven viewport classes + document-header geometry regression (Change Set R)
BASE=http://localhost:8000 node tests/e2e/layout.mjs
