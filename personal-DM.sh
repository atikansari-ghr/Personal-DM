#!/usr/bin/env bash
# Personal Documents Management System — one-line installer and maintenance menu (Debian 13).
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)"
#
# Without a command it shows a menu. Commands for unattended use (add them after `--`, e.g.
#   bash -c "$(curl -fsSL .../personal-DM.sh)" -- upgrade):
#   install          fresh installation (guided questions; safe to run again)
#   upgrade          back up, then upgrade to the latest version (data is kept; rolls back on failure)
#   repair           reinstall services and permissions, keep data
#   doctor           run all health checks
#   status           show services and version
#   backup           make an application backup now (to the configured destination)
#   restore DIR      restore an application backup (asks for confirmation)
#   recover-admin U  reset the password/2FA of administrator U (prints a one-time password)
#   help             this text
# Options: --ref BRANCH|TAG (default main), --dry-run (show what would happen), --yes (no questions where possible)
#
# Needs: Debian 13 (trixie), root, systemd, Internet access to deb.debian.org and github.com.
# Logs: /var/log/personaldocs/personal-DM.log (this script), /var/log/personaldocs/install.log (installer).
set -Eeuo pipefail
umask 027
export LANG=C.UTF-8 LC_ALL=C.UTF-8

REPO_URL=${PD_REPO_URL:-https://github.com/atikansari-ghr/Personal-DM.git}  # override for a fork or mirror
SRC=${PD_SRC:-/root/personaldocs-src}
CONF_DIR=/etc/personaldocs
TOKEN_FILE=$CONF_DIR/github-token
LOG_DIR=${PD_LOG_DIR:-/var/log/personaldocs}
LOG=$LOG_DIR/personal-DM.log
PREFIX=${PD_PREFIX:-/opt/personaldocs}
OS_RELEASE=${PD_OS_RELEASE:-/etc/os-release}      # test hooks (tests/installer/test_personal_dm.sh)
SYSTEMD_DIR=${PD_SYSTEMD_DIR:-/run/systemd/system}
REF=main
DRY=0
YES=0
CMD=""
ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --ref) [ $# -ge 2 ] || { echo "--ref needs a branch or tag" >&2; exit 2; }; REF=$2; shift 2 ;;
    --ref=*) REF=${1#--ref=}; shift ;;
    --dry-run) DRY=1; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help|help) CMD=help; shift ;;
    --) shift ;;
    -*) echo "Unknown option: $1 (see: help)" >&2; exit 2 ;;
    *) if [ -z "$CMD" ]; then CMD=$1; else ARGS+=("$1"); fi; shift ;;
  esac
done
[[ "$REF" =~ ^[A-Za-z0-9._/-]{1,100}$ ]] || { echo "Invalid --ref" >&2; exit 2; }

# ------------------------------------------------------------------ output
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'; else B=''; G=''; Y=''; R=''; C=''; N=''; fi
say() { printf '%s\n' "$*"; }
step() { printf '\n%s==> %s%s\n' "$B$C" "$*" "$N"; }
ok() { printf '%s✔ %s%s\n' "$G" "$*" "$N"; }
warn() { printf '%s! %s%s\n' "$Y" "$*" "$N" >&2; }
fail() { printf '%s✘ %s%s\n' "$R" "$*" "$N" >&2; printf '  Log: %s\n' "$LOG" >&2; exit 1; }
run() { # run a command, logging its output; in --dry-run only print it
  if [ "$DRY" = 1 ]; then printf '   [dry-run] %s\n' "$*"; return 0; fi
  printf '\n$ %s\n' "$*" >>"$LOG"
  "$@" 2>&1 | tee -a "$LOG"
  return "${PIPESTATUS[0]}"
}
on_error() { printf '%s✘ Failed (exit %s) at line %s. Nothing after this step was changed. Details: %s%s\n' "$R" "$1" "$2" "$LOG" "$N" >&2; }
trap 'on_error $? $LINENO' ERR

usage() { sed -n '2,/^set -Eeuo/p' "${BASH_SOURCE[0]:-$0}" 2>/dev/null | grep '^#' | sed 's/^# \{0,1\}//' || true; }
if [ "$CMD" = help ]; then
  usage
  # when run through `bash -c "$(curl ...)"` the file is not on disk: print the essentials
  [ -f "${BASH_SOURCE[0]:-}" ] || say "Commands: install | upgrade | repair | doctor | status | backup | restore DIR | recover-admin USER | help"
  exit 0
fi

# ------------------------------------------------------------------ checks
[ "$(id -u)" -eq 0 ] || fail "Run this as root (for example: sudo -i, or pct enter <id> on Proxmox)."
# shellcheck source=/dev/null
. "$OS_RELEASE" 2>/dev/null || true
if [ "${ID:-}" != debian ] || [ "${VERSION_ID:-}" != 13 ]; then
  if [ "${PD_ALLOW_UNSUPPORTED_OS:-0}" = 1 ]; then warn "Not Debian 13 (${PRETTY_NAME:-unknown}); continuing because PD_ALLOW_UNSUPPORTED_OS=1."
  else fail "This installer supports Debian 13 (trixie) only; found ${PRETTY_NAME:-an unknown system}."; fi
fi
command -v systemctl >/dev/null && [ -d "$SYSTEMD_DIR" ] || fail "systemd is not running. Use a Debian 13 VM or a systemd-based LXC container."
if [ "$DRY" = 0 ]; then mkdir -p "$LOG_DIR"; chmod 750 "$LOG_DIR"; touch "$LOG"; chmod 640 "$LOG"; fi
[ "$DRY" = 1 ] && LOG=/dev/null
printf '\n===== %s personal-DM.sh %s (ref %s)\n' "$(date -Is)" "${CMD:-menu}" "$REF" >>"$LOG" 2>/dev/null || true

installed() { [ -L "$PREFIX/current" ] && command -v personaldocs >/dev/null 2>&1; }
need_installed() { installed || fail "Personal Documents Management System is not installed here yet. Choose 'install' first."; }

git_auth() { # git with the stored token (never on the command line or in a URL), or anonymous
  if [ -s "$TOKEN_FILE" ]; then
    git -c credential.helper= -c "credential.helper=!f(){ echo username=x-access-token; printf 'password=%s\n' \"\$(cat $TOKEN_FILE)\"; }; f" "$@"
  else
    GIT_TERMINAL_PROMPT=0 git "$@"
  fi
}

ensure_tools() {
  local missing=()
  for t in git curl; do command -v "$t" >/dev/null || missing+=("$t"); done
  dpkg -s ca-certificates >/dev/null 2>&1 || missing+=(ca-certificates)
  [ ${#missing[@]} -eq 0 ] && return
  step "Installing prerequisites: ${missing[*]}"
  run apt-get update -q
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends "${missing[@]}"
}

ask_token() { # private repository: store a read-only token once (same file the installer and upgrades use)
  [ "$YES" = 1 ] && fail "The repository could not be read anonymously. Store a read-only GitHub token in $TOKEN_FILE (chmod 600) and run again."
  [ -t 0 ] || fail "The repository could not be read anonymously and there is no terminal to ask for a token."
  warn "The repository could not be read anonymously (it may be private)."
  say "Paste a fine-grained GitHub token with read-only 'Contents' access to the repository (input is hidden)."
  local tok=""
  read -rsp "Token: " tok || true; echo
  [ -n "$tok" ] || fail "No token given."
  [[ "$tok" =~ ^[A-Za-z0-9_]+$ ]] || fail "That does not look like a GitHub token."
  if [ "$DRY" = 0 ]; then
    install -d -m 750 "$CONF_DIR"
    install -m 600 /dev/null "$TOKEN_FILE"
    printf '%s' "$tok" >"$TOKEN_FILE"
  fi
  ok "Token stored in $TOKEN_FILE (readable by root only)."
}

fetch_source() { # clone or update /root/personaldocs-src to $REF, keeping local edits safe
  step "Getting the source code ($REF)"
  if [ "$DRY" = 1 ]; then say "   [dry-run] clone/update $REPO_URL into $SRC at $REF"; return; fi
  if [ -d "$SRC/.git" ]; then
    if [ -n "$(git -C "$SRC" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
      fail "$SRC has local changes. Move them away (git -C $SRC stash) or delete the folder, then run again."
    fi
    git_auth -C "$SRC" fetch --quiet --tags origin >>"$LOG" 2>&1 || { ask_token; git_auth -C "$SRC" fetch --quiet --tags origin >>"$LOG" 2>&1 || fail "Could not update $SRC from GitHub."; }
  else
    rm -rf "$SRC.partial"
    git_auth clone --quiet "$REPO_URL" "$SRC.partial" >>"$LOG" 2>&1 || { ask_token; git_auth clone --quiet "$REPO_URL" "$SRC.partial" >>"$LOG" 2>&1 || fail "Could not download the repository."; }
    mv "$SRC.partial" "$SRC"
  fi
  if git -C "$SRC" show-ref --verify --quiet "refs/remotes/origin/$REF"; then git -C "$SRC" checkout --quiet --detach "origin/$REF"
  else git -C "$SRC" checkout --quiet --detach "$REF" 2>>"$LOG" || fail "Branch or tag '$REF' does not exist."; fi
  ok "Source: $SRC at $(git -C "$SRC" rev-parse --short HEAD) ($(cat "$SRC/VERSION" 2>/dev/null || echo unknown))"
}

# ------------------------------------------------------------------ actions
do_install() {
  if installed; then
    warn "Already installed ($(personaldocs status 2>/dev/null | head -1 || echo 'see personaldocs status'))."
    say "Running the guided installer again is safe: answers are remembered and finished steps are skipped."
    say "To update to the latest version use 'upgrade' instead."
    if [ "$YES" != 1 ] && [ -t 0 ]; then
      read -rp "Run the guided installer again anyway? [y/N] " a || true
      [[ "${a:-n}" =~ ^[Yy] ]] || { say "Nothing changed."; return; }
    fi
  fi
  ensure_tools
  fetch_source
  step "Starting the guided installer"
  local opts=()
  [ "$DRY" = 1 ] && opts+=(--dry-run)
  [ "$YES" = 1 ] && opts+=(--yes)
  if [ "$DRY" = 1 ] && [ ! -f "$SRC/scripts/easy-install.sh" ]; then say "   [dry-run] bash $SRC/scripts/easy-install.sh ${opts[*]}"; return; fi
  PD_REF=$REF bash "$SRC/scripts/easy-install.sh" "${opts[@]}"
}

do_upgrade() {
  need_installed
  ensure_tools
  step "Upgrading (a backup is taken first; on failure the previous version is restored)"
  run personaldocs upgrade --ref "$REF"
  # releases that add system components (e.g. ClamAV, host helper) finish their setup here
  if grep -q 'post-upgrade)' "$(command -v personaldocs)" 2>/dev/null; then
    step "Setting up new components (antivirus, host helper)"
    run personaldocs post-upgrade
  fi
  step "Health check"
  run personaldocs doctor || fail "The upgrade finished but some checks failed (listed above). Run 'repair', or 'personaldocs rollback' to go back."
  ok "Upgrade complete."
}

do_simple() { # status | doctor | repair | backup
  need_installed
  case "$1" in
    repair) step "Repairing services and permissions (data is kept)"; run personaldocs repair ;;
    backup) step "Backing up"; run personaldocs backup ;;
    doctor) step "Health checks"; run personaldocs doctor ;;
    status) run personaldocs status ;;
  esac
}

do_restore() {
  need_installed
  local dir=${ARGS[0]:-}
  if [ -z "$dir" ] && [ -t 0 ]; then read -rp "Backup folder to restore (e.g. /mnt/pdnas/personaldocs/2026-01-31_0200): " dir || true; fi
  [ -n "$dir" ] || fail "Give the backup folder: restore /path/to/backup"
  [ -d "$dir" ] || fail "Not a folder: $dir"
  step "Verifying the backup first"
  run personaldocs restore "$dir" --verify-only
  step "Restoring (you will be asked to type RESTORE)"
  [ "$DRY" = 1 ] && { say "   [dry-run] personaldocs restore $dir"; return; }
  personaldocs restore "$dir"
}

do_recover() {
  need_installed
  local user=${ARGS[0]:-}
  if [ -z "$user" ] && [ -t 0 ]; then read -rp "Administrator username: " user || true; fi
  [[ "$user" =~ ^[A-Za-z0-9._@+-]{1,150}$ ]] || fail "Give a valid username: recover-admin USERNAME"
  step "Recovering administrator access for $user"
  [ "$DRY" = 1 ] && { say "   [dry-run] personaldocs recover-admin $user"; return; }
  personaldocs recover-admin "$user"  # prints a one-time password to this terminal only (not logged)
}

menu() {
  say "${B}Personal Documents Management System${N} — installer and maintenance"
  if installed; then say "Installed: $(cat "$PREFIX/current/VERSION" 2>/dev/null || echo yes)"; else say "Not installed on this machine yet."; fi
  say ""
  say "  1) Install (fresh install or re-run the guided setup)"
  say "  2) Upgrade to the latest version"
  say "  3) Repair"
  say "  4) Health check (doctor)"
  say "  5) Status"
  say "  6) Back up now"
  say "  7) Restore a backup"
  say "  8) Recover administrator access"
  say "  q) Quit"
  local c=""
  read -rp "Choose [$(installed && echo 2 || echo 1)]: " c || true
  c=${c:-$(installed && echo 2 || echo 1)}
  case "$c" in
    1) do_install ;; 2) do_upgrade ;; 3) do_simple repair ;; 4) do_simple doctor ;; 5) do_simple status ;;
    6) do_simple backup ;; 7) do_restore ;; 8) do_recover ;; q|Q) say "Bye." ;;
    *) fail "Unknown choice: $c" ;;
  esac
}

case "${CMD:-}" in
  "") if [ -t 0 ] && [ "$YES" != 1 ]; then menu; elif installed; then do_upgrade; else do_install; fi ;;
  install) do_install ;;
  upgrade) do_upgrade ;;
  repair|doctor|status|backup) do_simple "$CMD" ;;
  restore) do_restore ;;
  recover-admin) do_recover ;;
  *) fail "Unknown command: $CMD (see: help)" ;;
esac
say ""
say "Logs: $LOG_DIR/  ·  Help: https://github.com/atikansari-ghr/Personal-DM#readme"
