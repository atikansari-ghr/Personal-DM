#!/usr/bin/env bash
# Personal Documents — guided installer for a Debian 13 LXC.
#
# Asks for everything it needs (address, reverse proxy, GitHub access, NAS, backup time, ...) and then installs,
# configures and checks the whole system. Safe to run again: answers are remembered (without secrets) and every
# step is idempotent.
#
#   bash easy-install.sh              # interactive
#   bash easy-install.sh --dry-run    # ask the questions and show what would be done, change nothing
#   PD_ANSWERS=/root/answers.env bash easy-install.sh --yes   # unattended, answers from a file (see docs)
set -Eeuo pipefail
umask 027

DEFAULT_REPO="https://github.com/atikansari-ghr/Personal-DM.git"
CONF_DIR=/etc/personaldocs
ANSWERS_FILE=$CONF_DIR/install-answers.env
TOKEN_FILE=$CONF_DIR/github-token
SRC=/root/personaldocs-src
LOG=/var/log/personaldocs/easy-install.log
DRY=0
YES=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

# ------------------------------------------------------------------ output helpers
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'; else B=''; G=''; Y=''; R=''; C=''; N=''; fi
say() { printf '%s\n' "$*"; }
step() { printf '\n%s==> %s%s\n' "$B$C" "$*" "$N"; }
ok() { printf '%s✔ %s%s\n' "$G" "$*" "$N"; }
warn() { printf '%s! %s%s\n' "$Y" "$*" "$N" >&2; }
fail() { printf '%s✘ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }
run() { # run a command (or print it in --dry-run); output goes to the log as well
  if [ "$DRY" = 1 ]; then printf '   [dry-run] %s\n' "$*"; return 0; fi
  "$@" 2>&1 | tee -a "$LOG"
  return "${PIPESTATUS[0]}"
}
trap 'printf "%s✘ Stopped at line %s. See %s, fix the problem and run this script again — finished steps are skipped.%s\n" "$R" "$LINENO" "$LOG" "$N" >&2' ERR

# ------------------------------------------------------------------ question helpers
# shellcheck source=/dev/null
[ -f "$ANSWERS_FILE" ] && . "$ANSWERS_FILE"   # defaults from a previous run (no secrets)
# shellcheck source=/dev/null
[ -n "${PD_ANSWERS:-}" ] && [ -f "$PD_ANSWERS" ] && . "$PD_ANSWERS"

ask() { # ask VAR "Question" "default" [validator-regex] [error message]
  local var=$1 q=$2 def=${3:-} rx=${4:-} msg=${5:-"Please enter a valid value."} ans
  local cur=${!var:-$def}
  if [ "$YES" = 1 ]; then
    [ -n "$cur" ] || [ -z "$rx" ] || fail "No value for $var in unattended mode."
    printf -v "$var" '%s' "$cur"; return
  fi
  while true; do
    read -rp "$(printf '%s%s%s%s: ' "$B" "$q" "$N" "${cur:+ [$cur]}")" ans || true
    ans=${ans:-$cur}
    if [ -z "$rx" ] || [[ "$ans" =~ $rx ]]; then printf -v "$var" '%s' "$ans"; return; fi
    warn "$msg"
  done
}
ask_secret() { # ask_secret VAR "Question" [optional=1]
  local var=$1 q=$2 optional=${3:-0} ans
  if [ "$YES" = 1 ]; then printf -v "$var" '%s' "${!var:-}"; return; fi
  while true; do
    read -rsp "$(printf '%s%s%s: ' "$B" "$q" "$N")" ans || true; echo
    if [ -n "$ans" ] || [ "$optional" = 1 ]; then printf -v "$var" '%s' "$ans"; return; fi
    warn "This value is required."
  done
}
ask_yn() { # ask_yn VAR "Question" default(y/n)
  local var=$1 q=$2 def=${3:-n} ans
  local cur=${!var:-$def}
  if [ "$YES" = 1 ]; then printf -v "$var" '%s' "$cur"; return; fi
  while true; do
    read -rp "$(printf '%s%s%s [%s]: ' "$B" "$q" "$N" "$( [ "$cur" = y ] && echo Y/n || echo y/N)")" ans || true
    ans=$(echo "${ans:-$cur}" | tr 'A-Z' 'a-z')
    case "$ans" in y|yes) printf -v "$var" y; return ;; n|no) printf -v "$var" n; return ;; esac
  done
}
ask_choice() { # ask_choice VAR "Question" default "1:label" "2:label" ...
  local var=$1 q=$2 def=$3; shift 3
  local cur=${!var:-$def} opt ans
  if [ "$YES" = 1 ]; then printf -v "$var" '%s' "$cur"; return; fi
  say "${B}${q}${N}"
  for opt in "$@"; do say "   ${opt%%:*}) ${opt#*:}"; done
  while true; do
    read -rp "Choose [${cur}]: " ans || true
    ans=${ans:-$cur}
    for opt in "$@"; do [ "$ans" = "${opt%%:*}" ] && { printf -v "$var" '%s' "$ans"; return; }; done
    warn "Enter one of the numbers shown."
  done
}

IP_RX='^([0-9]{1,3}\.){3}[0-9]{1,3}$'
HOST_RX='^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$'
DOMAIN_RX='^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$'
TIME_RX='^([01][0-9]|2[0-3]):[0-5][0-9]$'

# ------------------------------------------------------------------ preflight
[ "$(id -u)" -eq 0 ] || fail "Run as root inside the container (for example: pct enter <id>, then bash easy-install.sh)."
if [ "$DRY" = 1 ]; then LOG=/dev/null; else
  mkdir -p "$(dirname "$LOG")" "$CONF_DIR"; chmod 700 "$CONF_DIR" 2>/dev/null || true
  : >>"$LOG"
fi
. /etc/os-release 2>/dev/null || true
say "${B}Personal Documents — guided installation${N}"
say "Log: $LOG$( [ "$DRY" = 1 ] && echo "   (DRY RUN: nothing will be changed)")"
[ "${ID:-}" = debian ] && [ "${VERSION_ID:-}" = 13 ] || warn "This is ${PRETTY_NAME:-an unknown system}; Debian 13 is the tested target."
UNPRIVILEGED=n
if [ -r /proc/self/uid_map ] && awk 'NR==1 && $1==0 && $2!=0 {f=1} END {exit !f}' /proc/self/uid_map; then UNPRIVILEGED=y; fi
MYIP=$(hostname -I 2>/dev/null | awk '{print $1}')

# ------------------------------------------------------------------ questions
step "1/7  Where the code comes from"
ask PD_REPO "GitHub repository URL" "$DEFAULT_REPO" '^(https://github\.com/[^ ]+|git@github\.com:[^ ]+)$' "Use https://github.com/OWNER/REPO.git"
ask PD_REF "Branch or tag to install" "main" '^[A-Za-z0-9._/-]+$'
GITHUB_TOKEN=""
if [ -s "$TOKEN_FILE" ]; then
  ok "A GitHub token is already stored in $TOKEN_FILE."
else
  say "The repository is private: paste a fine-grained token with read-only 'Contents' access to it."
  say "(GitHub → Settings → Developer settings → Fine-grained tokens. Leave empty if the repository is public.)"
  ask_secret GITHUB_TOKEN "GitHub token (hidden)" 1
fi

step "2/7  Web address and reverse proxy"
ask PD_DOMAIN "Public domain name for the app (e.g. docs.example.com)" "" "$DOMAIN_RX" "Enter a domain like docs.example.com (no https://)."
ask_choice PD_PROXY "Which reverse proxy publishes the app with HTTPS?" "1" \
  "1:Nginx Proxy Manager on another machine" "2:Pangolin (Newt/WireGuard)" "3:A proxy running inside this container / testing only"
if [ "$PD_PROXY" = 3 ]; then
  PD_PROXY_IP=127.0.0.1; PD_BIND_HOST=127.0.0.1
else
  ask PD_PROXY_IP "IP address the proxy connects from (the NPM host, or the Newt/Pangolin site)" "" "$IP_RX" "Enter an IPv4 address."
  PD_BIND_HOST=0.0.0.0
fi
ask PD_PORT "Port the app listens on" "8000" '^[0-9]{2,5}$'
if [ "$PD_BIND_HOST" = 0.0.0.0 ]; then
  ask_yn PD_FIREWALL "Allow only the proxy to reach port $PD_PORT (recommended firewall rule)?" y
else
  PD_FIREWALL=n
fi

step "3/7  Regional settings"
ask PD_TZ "Timezone for expiry reminders" "Asia/Riyadh" '^[A-Za-z_]+(/[A-Za-z0-9_+-]+)*$' "Use a name like Asia/Riyadh or Asia/Kolkata."
[ "$DRY" = 1 ] || [ -e "/usr/share/zoneinfo/$PD_TZ" ] || [ ! -d /usr/share/zoneinfo ] || warn "$PD_TZ was not found in /usr/share/zoneinfo; the app will reject it if it is wrong."

step "4/7  Backups to your NAS"
if [ "$UNPRIVILEGED" = y ]; then
  warn "This is an UNPRIVILEGED container: it cannot mount NFS/SMB itself. Either let the Proxmox host bind-mount the share"
  warn "(choose 3) or recreate the container privileged with the 'mount=nfs;cifs' feature (scripts/proxmox-create-lxc.sh)."
fi
ask_choice PD_NAS "How should backups reach the NAS?" "$( [ "$UNPRIVILEGED" = y ] && echo 3 || echo 1)" \
  "1:NFS share (the app mounts it)" "2:SMB / Windows share (the app mounts it)" "3:Already mounted into this container (Proxmox bind mount)" "4:Decide later in Settings"
NAS_PASSWORD=""
case "$PD_NAS" in
  1|2)
    ask PD_NAS_SERVER "NAS server (hostname or IP)" "" "$HOST_RX" "Enter a hostname or IP address."
    if [ "$PD_NAS" = 1 ]; then
      ask PD_NAS_SHARE "NFS export path (e.g. /volume1/backups)" "" '^/[A-Za-z0-9/_. $-]+$' "NFS exports start with /"
    else
      ask PD_NAS_SHARE "SMB share name (e.g. backups)" "" '^[A-Za-z0-9_. $-]+$' "Use the share name only, e.g. backups"
      ask PD_NAS_USER "SMB username" "" '^[^[:space:],=\\"'"'"']+$' "No spaces, commas, quotes or '='."
      ask_secret NAS_PASSWORD "SMB password (hidden)"
      ask PD_NAS_DOMAIN "SMB domain/workgroup (optional)" "" '^[^[:space:],=\\"'"'"']*$'
    fi
    ask PD_NAS_SUBFOLDER "Folder on the share for these backups" "personaldocs" '^[A-Za-z0-9_.-]+$'
    ;;
  3)
    ask PD_NAS_PATH "Folder inside this container where the share is mounted" "/mnt/nas-backup/personaldocs" '^/[A-Za-z0-9/_.-]+$'
    ;;
esac
ask PD_BACKUP_TIME "Daily backup time (24h, HH:MM)" "02:30" "$TIME_RX" "Use HH:MM, e.g. 02:30"

step "5/7  Optional components"
ask_yn PD_VERAPDF "Install veraPDF for full PDF/A validation (~250 MB, uses Java)?" n

# ------------------------------------------------------------------ confirmation
ORIGIN="https://$PD_DOMAIN"
step "6/7  Summary"
cat <<EOF
  Repository         $PD_REPO ($PD_REF)$( [ -n "$GITHUB_TOKEN" ] && echo ", token provided" )
  Public address     $ORIGIN
  Listens on         $PD_BIND_HOST:$PD_PORT   (container IP: ${MYIP:-unknown})
  Trusted proxy      $PD_PROXY_IP$( [ "$PD_FIREWALL" = y ] && echo "   + firewall: only the proxy may connect")
  Timezone           $PD_TZ
  Backups            $(case "$PD_NAS" in 1) echo "NFS $PD_NAS_SERVER:$PD_NAS_SHARE → $PD_NAS_SUBFOLDER";; 2) echo "SMB //$PD_NAS_SERVER/$PD_NAS_SHARE as $PD_NAS_USER → $PD_NAS_SUBFOLDER";; 3) echo "existing folder $PD_NAS_PATH";; *) echo "configure later in Settings";; esac), daily at $PD_BACKUP_TIME
  veraPDF            $PD_VERAPDF
EOF
if [ "$YES" != 1 ]; then
  ask_yn GO "Start the installation now?" y
  [ "$GO" = y ] || { say "Cancelled. Nothing was changed."; exit 0; }
fi

# remember answers (never secrets) for the next run
if [ "$DRY" = 0 ]; then
  umask 077
  {
    for v in PD_REPO PD_REF PD_DOMAIN PD_PROXY PD_PROXY_IP PD_PORT PD_FIREWALL PD_TZ PD_NAS PD_NAS_SERVER PD_NAS_SHARE PD_NAS_USER \
             PD_NAS_DOMAIN PD_NAS_SUBFOLDER PD_NAS_PATH PD_BACKUP_TIME PD_VERAPDF; do
      printf '%s=%q\n' "$v" "${!v:-}"
    done
  } >"$ANSWERS_FILE"
  umask 027
fi

# ------------------------------------------------------------------ installation
step "7/7  Installing (10–25 minutes; progress is logged to $LOG)"

say "• Base tools"
run apt-get update -q
run env DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends git ca-certificates curl

if [ -n "$GITHUB_TOKEN" ]; then
  say "• Storing the GitHub token (root-only file)"
  if [ "$DRY" = 0 ]; then install -m 600 /dev/null "$TOKEN_FILE"; printf '%s' "$GITHUB_TOKEN" >"$TOKEN_FILE"; fi
  unset GITHUB_TOKEN
fi
git_auth() {
  if [ -s "$TOKEN_FILE" ]; then
    git -c credential.helper= -c "credential.helper=!f(){ echo username=x-access-token; printf 'password=%s\n' \"\$(cat $TOKEN_FILE)\"; }; f" "$@"
  else
    git "$@"
  fi
}

say "• Downloading the application"
if [ -d "$SRC/.git" ]; then
  run git_auth -C "$SRC" remote set-url origin "$PD_REPO"
  run git_auth -C "$SRC" fetch --quiet --tags origin || fail "Could not download from GitHub. Check the token (Contents: read-only) and network."
  run git -C "$SRC" checkout --quiet --detach "origin/$PD_REF" 2>/dev/null || run git -C "$SRC" checkout --quiet --detach "$PD_REF"
else
  run git_auth clone --quiet "$PD_REPO" "$SRC" || fail "Could not download from GitHub. Check the token (Contents: read-only) and network."
  run git -C "$SRC" checkout --quiet --detach "$PD_REF" 2>/dev/null || run git -C "$SRC" checkout --quiet --detach "origin/$PD_REF"
fi

say "• Installing packages, database, application and services"
INSTALL_ARGS=(install --public-origin "$ORIGIN" --bind "$PD_BIND_HOST:$PD_PORT" --repo "$PD_REPO" --ref "$PD_REF")
[ "$PD_VERAPDF" = y ] && INSTALL_ARGS+=(--with-verapdf)
run env PD_QUIET_TOKEN=1 bash "$SRC/scripts/personaldocs" "${INSTALL_ARGS[@]}"

ENV_FILE=$CONF_DIR/personaldocs.env
say "• Trusting the reverse proxy at $PD_PROXY_IP"
if [ "$DRY" = 0 ]; then
  sed -i "s|^PD_TRUSTED_PROXY_IPS=.*|PD_TRUSTED_PROXY_IPS=127.0.0.1,$PD_PROXY_IP|" "$ENV_FILE"
  grep -q '^PD_BEHIND_PROXY=' "$ENV_FILE" && sed -i 's|^PD_BEHIND_PROXY=.*|PD_BEHIND_PROXY=1|' "$ENV_FILE" || echo 'PD_BEHIND_PROXY=1' >>"$ENV_FILE"
fi
run systemctl restart personaldocs-web

if [ "$PD_FIREWALL" = y ]; then
  say "• Firewall: only $PD_PROXY_IP may reach port $PD_PORT"
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends nftables
  if [ "$DRY" = 0 ]; then
    install -d /etc/nftables.d
    cat >/etc/nftables.d/personaldocs.nft <<EOF
# Managed by Personal Documents easy-install.sh
table inet personaldocs {
  chain input {
    type filter hook input priority 0; policy accept;
    tcp dport $PD_PORT ip saddr != { 127.0.0.1, $PD_PROXY_IP } drop
  }
}
EOF
    grep -q 'nftables.d/personaldocs.nft' /etc/nftables.conf 2>/dev/null || echo 'include "/etc/nftables.d/personaldocs.nft"' >>/etc/nftables.conf
  fi
  run systemctl enable nftables
  run systemctl restart nftables
fi

say "• Applying app settings"
SETTINGS_JSON=$(mktemp /tmp/pd-settings.XXXXXX)
{
  printf '{"general.timezone": "%s", "backup.schedule_time": "%s"' "$PD_TZ" "$PD_BACKUP_TIME"
  case "$PD_NAS" in
    1) printf ', "nas.type": "nfs", "nas.server": "%s", "nas.share": "%s", "nas.subfolder": "%s"' "$PD_NAS_SERVER" "$PD_NAS_SHARE" "$PD_NAS_SUBFOLDER" ;;
    2) printf ', "nas.type": "smb", "nas.server": "%s", "nas.share": "%s", "nas.subfolder": "%s", "nas.username": "%s", "nas.domain": "%s"' \
         "$PD_NAS_SERVER" "$PD_NAS_SHARE" "$PD_NAS_SUBFOLDER" "$PD_NAS_USER" "${PD_NAS_DOMAIN:-}"
       # the password is JSON-escaped with python to survive any characters
       printf ', "nas.password": %s' "$(NAS_PASSWORD="$NAS_PASSWORD" python3 -c 'import json, os; print(json.dumps(os.environ["NAS_PASSWORD"]))')" ;;
    3) printf ', "nas.type": "none", "backup.target": "%s"' "$PD_NAS_PATH" ;;
  esac
  printf '}\n'
} >"$SETTINGS_JSON"
unset NAS_PASSWORD
if [ "$DRY" = 0 ]; then chown personaldocs "$SETTINGS_JSON"; chmod 600 "$SETTINGS_JSON"; fi
run personaldocs manage apply_settings "$SETTINGS_JSON" || { rm -f "$SETTINGS_JSON"; fail "Some settings were rejected (see above)."; }
rm -f "$SETTINGS_JSON"

NAS_OK=n
case "$PD_NAS" in
  1|2)
    say "• Connecting the NAS"
    if run personaldocs nas-apply --from-settings; then NAS_OK=y; ok "NAS connected"; else
      warn "The NAS could not be connected yet (details above). Fix it later in Settings → Storage & backup → Connect NAS."
    fi ;;
  3)
    say "• Preparing the backup folder $PD_NAS_PATH"
    if [ "$DRY" = 1 ] || [ -d "$PD_NAS_PATH" ]; then
      if run touch "$PD_NAS_PATH/.personaldocs-backup-target" && run chown personaldocs: "$PD_NAS_PATH" "$PD_NAS_PATH/.personaldocs-backup-target"; then
        NAS_OK=y
      else
        warn "Cannot prepare $PD_NAS_PATH. On the Proxmox host make the folder writable for the container (unprivileged: chown 100000:100000), then re-run."
      fi
    else
      warn "$PD_NAS_PATH does not exist. Add the Proxmox bind mount (see docs/guides/backup-restore.md#lxc-requirements), then re-run this script."
    fi ;;
esac

if [ "$NAS_OK" = y ]; then
  say "• First backup (checks the destination end to end)"
  run personaldocs backup || warn "The first backup failed; see Settings → Storage & backup."
fi

say "• Health check"
run personaldocs status || true
run personaldocs doctor || warn "Some diagnostics need attention (listed above). Items like 'public origin uses HTTPS' are fine once the proxy is set up."

TOKEN_LINE="(dry run)"
if [ "$DRY" = 0 ]; then
  TOKEN_LINE=$(personaldocs setup-token 2>/dev/null | sed -n 2p | tr -d ' ' || true)
  [ -n "$TOKEN_LINE" ] || TOKEN_LINE="setup already completed"
fi

# ------------------------------------------------------------------ summary
step "Done"
cat <<EOF
${B}1. Publish the app with your reverse proxy${N}
EOF
if [ "$PD_PROXY" = 1 ]; then cat <<EOF
   Nginx Proxy Manager → Hosts → Proxy Hosts → Add:
     Domain names:      $PD_DOMAIN
     Scheme / Forward:  http  ${MYIP:-<container-ip>}  port $PD_PORT
     SSL tab:           Request a new certificate, Force SSL, HTTP/2
     Advanced tab:
       client_max_body_size 1024m;
       proxy_request_buffering off;
       proxy_read_timeout 600s;
       proxy_send_timeout 600s;
EOF
elif [ "$PD_PROXY" = 2 ]; then cat <<EOF
   Pangolin → Resources → Add HTTP resource:
     Domain:  $PD_DOMAIN      Target: http://${MYIP:-<container-ip>}:$PD_PORT
     If Pangolin authentication is on, add bypass rules for /s/* and /api/auth/google/callback.
EOF
else cat <<EOF
   Point your local proxy at http://127.0.0.1:$PD_PORT and serve it as $ORIGIN.
EOF
fi
cat <<EOF

${B}2. Open ${ORIGIN} and enter this one-time setup code:${N}
     ${G}${TOKEN_LINE}${N}
   (valid 24 hours; get a new one with: personaldocs setup-token)

${B}3. Backups${N}: $( [ "$NAS_OK" = y ] && echo "connected — daily at $PD_BACKUP_TIME" || echo "not connected yet — Settings → Storage & backup")
${B}4. Optional${N}: email, Telegram and Google sign-in in Settings → Connections / Authentication.

Re-run this script any time to change answers; use 'personaldocs upgrade' for updates.
Log: $LOG
EOF
