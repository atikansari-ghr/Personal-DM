#!/usr/bin/env bash
# Development helper: run web + worker (+ scheduler) against a local PostgreSQL. Not for production.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${PD_DEBUG:=1}" "${PD_DATA_DIR:=/tmp/pd-dev/data}" "${PD_CONFIG_DIR:=/tmp/pd-dev/config}" "${PD_PUBLIC_ORIGIN:=http://localhost:8000}"
export PD_DEBUG PD_DATA_DIR PD_CONFIG_DIR PD_PUBLIC_ORIGIN
LOGDIR="${LOGDIR:-/tmp/pd-dev/logs}"; mkdir -p "$LOGDIR"
cd backend
../.venv/bin/python manage.py migrate --noinput >/dev/null
../.venv/bin/gunicorn personaldocs.wsgi -b 127.0.0.1:8000 -w 2 --timeout 300 >"$LOGDIR/web.log" 2>&1 &
../.venv/bin/python manage.py worker >"$LOGDIR/worker.log" 2>&1 &
if [ "${WITH_SCHEDULER:-0}" = 1 ]; then ../.venv/bin/python manage.py scheduler >"$LOGDIR/scheduler.log" 2>&1 & fi
echo "web on http://127.0.0.1:8000, logs in $LOGDIR"
