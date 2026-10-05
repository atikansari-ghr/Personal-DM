#!/usr/bin/env bash
# Publication safety check for the repository (AT-79). Run before making the repository public and in CI.
#   scripts/privacy_check.sh            current tree only
#   scripts/privacy_check.sh --history  also every committed version (slower)
# Fails on: tracked secret/data files, credential-looking strings, AI assistants named as authors, and
# documentation/screenshot links that do not resolve. It cannot prove absence of private data: review new
# screenshots and documents by eye as well (see docs/RELEASE_CHECKLIST.md).
set -euo pipefail
cd "$(dirname "$0")/.."
fail=0
bad() { echo "FAIL: $*"; fail=1; }

# 1. files that must never be tracked
if git ls-files | grep -E -i '(^|/)(references/|uploads/|backups?/)|\.(pgdump|dump|sqlite3?|env|pem|key|p12|pfx|mmdb|log)$|(^|/)(encryption\.key|secret_key|github-token|\.son1)$' \
  | grep -v -E '^deployment/personaldocs\.env\.example$|^backend/apps/.*/backup\.py$|^docs/guides/backup-restore\.md$'; then
  bad "secret, database, log or private data files are tracked"
fi

# 2. credential-looking strings
CRED='(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gh[ousr]_[A-Za-z0-9]{30,}|-----BEGIN ([A-Z]+ )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|xox[abpr]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{32,}|[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}|https?://[^/ :]+:[^@/ ]{6,}@)'
if git grep -nE "$CRED" -- . ':!scripts/privacy_check.sh' ':!scripts/verify.sh' ':!scripts/personaldocs'; then
  bad "possible credentials in tracked files"
fi
if [ "${1:-}" = "--history" ]; then
  if git log --all -p -G"$CRED" --pretty=format:'commit %h' -- . ':!scripts/privacy_check.sh' ':!scripts/verify.sh' ':!scripts/personaldocs' | grep -E "^\+.*$CRED"; then
    bad "possible credentials in Git history: rotate them and clean the history before publishing"
  fi
fi

# 3. AI assistants must not be presented as project authors (commit trailers are history and stay as they are)
if git grep -n -i -E '(author|maintainer|created by|written by)[^A-Za-z]{0,6}[^\n]{0,40}(claude|anthropic|openai|codex|chatgpt|copilot)' -- . \
  ':!scripts/privacy_check.sh' ':!frontend/package-lock.json'; then
  bad "an AI assistant is named as an author"
fi
if [ -f frontend/package.json ] && grep -q '"author"' frontend/package.json && ! grep -q '"author": "Atik Ansari"' frontend/package.json; then
  bad "frontend/package.json author is not the project author"
fi

# 4. relative links and images in the public documentation resolve
for f in README.md CONTRIBUTING.md SECURITY.md CHANGELOG.md docs/*.md docs/guides/*.md; do
  [ -f "$f" ] || continue
  dir=$(dirname "$f")
  { grep -oE '\]\(([^)#: ]+)(#[^)]*)?\)' "$f" || true; } | sed -E 's/^\]\(([^)#]+).*/\1/' | while read -r link; do
    [ -e "$dir/$link" ] || echo "FAIL: $f links to missing $link"
  done
done | tee /tmp/privacy-links.$$ ; [ -s /tmp/privacy-links.$$ ] && fail=1; rm -f /tmp/privacy-links.$$

[ "$fail" = 0 ] && echo "privacy check: OK" || { echo "privacy check: FAILED"; exit 1; }
