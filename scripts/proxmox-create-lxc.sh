#!/usr/bin/env bash
# Personal Documents Management System — create the Debian 13 LXC on a Proxmox VE host and run the guided installer inside it.
#
# Run on the Proxmox host as root. It asks for the container settings, downloads the Debian 13 template if
# needed, creates and starts the container (privileged + mount=nfs;cifs when the app should mount the NAS
# itself, or unprivileged + a host bind mount), copies scripts/easy-install.sh into it and starts it.
#
#   bash proxmox-create-lxc.sh [--dry-run]
set -Eeuo pipefail

REPO_API="https://api.github.com/repos/atikansari-ghr/Personal-DM/contents/scripts/easy-install.sh"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'; else B=''; G=''; Y=''; R=''; N=''; fi
say() { printf '%s\n' "$*"; }
warn() { printf '%s! %s%s\n' "$Y" "$*" "$N" >&2; }
fail() { printf '%s✘ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }
run() { if [ "$DRY" = 1 ]; then printf '   [dry-run] %s\n' "$*"; else "$@"; fi; }
ask() { local var=$1 q=$2 def=${3:-} rx=${4:-} ans; while true; do read -rp "$(printf '%s%s%s%s: ' "$B" "$q" "$N" "${def:+ [$def]}")" ans || true; ans=${ans:-$def}; if [ -z "$rx" ] || [[ "$ans" =~ $rx ]]; then printf -v "$var" '%s' "$ans"; return; fi; warn "Invalid value."; done; }
ask_secret() { local var=$1 q=$2 ans; read -rsp "$(printf '%s%s%s: ' "$B" "$q" "$N")" ans || true; echo; printf -v "$var" '%s' "$ans"; }
ask_yn() { local var=$1 q=$2 def=$3 ans; read -rp "$(printf '%s%s%s [%s]: ' "$B" "$q" "$N" "$( [ "$def" = y ] && echo Y/n || echo y/N)")" ans || true; ans=$(echo "${ans:-$def}" | tr 'A-Z' 'a-z'); [[ "$ans" == y* ]] && printf -v "$var" y || printf -v "$var" n; }

[ "$(id -u)" -eq 0 ] || fail "Run as root on the Proxmox host."
command -v pct >/dev/null && command -v pveam >/dev/null || { [ "$DRY" = 1 ] || fail "This must run on a Proxmox VE host (pct/pveam not found)."; }

say "${B}Personal Documents Management System — create container on Proxmox${N}$( [ "$DRY" = 1 ] && echo '  (DRY RUN)')"
NEXTID=$( (pvesh get /cluster/nextid 2>/dev/null) || echo 210)
ask CTID "Container ID" "$NEXTID" '^[0-9]{3,9}$'
if [ "$DRY" = 0 ] && pct status "$CTID" >/dev/null 2>&1; then fail "Container $CTID already exists."; fi
ask CT_HOST "Hostname" "personaldocs" '^[a-z0-9][a-z0-9-]{0,62}$'
say "Storages that can hold containers:"; (pvesm status -content rootdir 2>/dev/null | awk 'NR>1 {print "   " $1 " (" $2 ", free " int($6/1048576) " GB)"}') || true
ask CT_STORAGE "Storage for the container disk" "local-lvm" '^[A-Za-z0-9_.-]+$'
ask CT_DISK "Disk size (GB)" "50" '^[0-9]{2,5}$'
ask CT_CORES "CPU cores" "2" '^[0-9]{1,2}$'
ask CT_MEM "Memory (MB)" "4096" '^[0-9]{3,6}$'
ask CT_BRIDGE "Network bridge" "vmbr0" '^[A-Za-z0-9_.-]+$'
ask CT_IP "IP address with prefix (e.g. 192.168.1.50/24) or 'dhcp'" "dhcp" '^(dhcp|([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2})$'
CT_GW=""
[ "$CT_IP" = dhcp ] || ask CT_GW "Gateway" "" '^([0-9]{1,3}\.){3}[0-9]{1,3}$'
ask_secret CT_PASS "Root password for the container (hidden; leave empty to use an SSH key)"
CT_SSHKEY=""
[ -n "$CT_PASS" ] || ask CT_SSHKEY "Path to an SSH public key file" "/root/.ssh/authorized_keys" '^/.+'

say ""
say "${B}NAS backups${N}"
say "   1) The app mounts the NAS itself (NFS/SMB) — creates a PRIVILEGED container with feature mount=nfs;cifs"
say "   2) This Proxmox host mounts the NAS and passes a folder in — UNPRIVILEGED container (more isolated)"
say "   3) No NAS for now"
ask NAS_MODE "Choose" "1" '^[123]$'
HOST_NAS=""
if [ "$NAS_MODE" = 2 ]; then
  ask HOST_NAS "Folder on this host where the NAS is already mounted (a sub-folder will be created)" "/mnt/nas-backup" '^/[A-Za-z0-9/_.-]+$'
  [ "$DRY" = 1 ] || mountpoint -q "$HOST_NAS" || warn "$HOST_NAS is not a mount point on this host. Mount the NAS there first (e.g. via /etc/fstab)."
fi

# ---------------------------------------------------------------- template
say ""
say "${B}Debian 13 template${N}"
run pveam update >/dev/null
TEMPLATE=$( (pveam available --section system 2>/dev/null | awk '{print $2}' | grep -E '^debian-13-standard_.*_amd64\.tar\.(zst|gz|xz)$' | sort -V | tail -1) || true)
[ -n "$TEMPLATE" ] || { [ "$DRY" = 1 ] && TEMPLATE="debian-13-standard_13.x-1_amd64.tar.zst"; } || fail "No Debian 13 template found in 'pveam available'."
ask TPL_STORAGE "Storage for templates" "local" '^[A-Za-z0-9_.-]+$'
if [ "$DRY" = 1 ] || ! pveam list "$TPL_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
  say "Downloading $TEMPLATE"
  run pveam download "$TPL_STORAGE" "$TEMPLATE"
fi

# ---------------------------------------------------------------- create
NET="name=eth0,bridge=$CT_BRIDGE,ip=$CT_IP"; [ -n "$CT_GW" ] && NET="$NET,gw=$CT_GW"
ARGS=(--hostname "$CT_HOST" --cores "$CT_CORES" --memory "$CT_MEM" --swap 1024 --rootfs "$CT_STORAGE:$CT_DISK"
      --net0 "$NET" --onboot 1 --ostype debian)
if [ "$NAS_MODE" = 1 ]; then ARGS+=(--unprivileged 0 --features "nesting=1,mount=nfs;cifs"); else ARGS+=(--unprivileged 1 --features nesting=1); fi
[ -n "$CT_SSHKEY" ] && ARGS+=(--ssh-public-keys "$CT_SSHKEY")
say ""
say "${B}Creating container $CTID${N}"
run pct create "$CTID" "$TPL_STORAGE:vztmpl/$TEMPLATE" "${ARGS[@]}"
if [ "$NAS_MODE" = 2 ]; then
  run mkdir -p "$HOST_NAS/personaldocs"
  run chown 100000:100000 "$HOST_NAS/personaldocs"   # unprivileged containers map root to 100000; the app user is fixed up inside
  run pct set "$CTID" -mp0 "$HOST_NAS/personaldocs,mp=/mnt/nas-backup/personaldocs"
fi
run pct start "$CTID"
say "Waiting for the container network…"
if [ "$DRY" = 0 ]; then
  for _ in $(seq 1 60); do pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 && break; sleep 2; done
  pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 || fail "The container has no network/DNS. Check the bridge, IP and gateway."
fi
if [ -n "$CT_PASS" ]; then
  say "Setting the container root password"
  # via stdin, so the password never appears in a process list
  if [ "$DRY" = 1 ]; then say "   [dry-run] pct exec $CTID -- chpasswd  (password on stdin)"
  else printf 'root:%s\n' "$CT_PASS" | pct exec "$CTID" -- chpasswd; fi
fi
unset CT_PASS

# ---------------------------------------------------------------- installer script
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
GITHUB_TOKEN=""
if [ -f "$HERE/easy-install.sh" ]; then
  INSTALLER="$HERE/easy-install.sh"
else
  say "The guided installer will be downloaded from the private GitHub repository."
  ask_secret GITHUB_TOKEN "GitHub fine-grained token (read-only Contents; hidden)"
  INSTALLER=$(mktemp)
  HDR=$(mktemp); chmod 600 "$HDR"; printf 'Authorization: Bearer %s\n' "$GITHUB_TOKEN" >"$HDR"
  run curl -fsSL -H @"$HDR" -H "Accept: application/vnd.github.raw" "$REPO_API" -o "$INSTALLER" || { rm -f "$HDR"; fail "Download failed (check the token)."; }
  rm -f "$HDR"
fi
run pct exec "$CTID" -- mkdir -p /etc/personaldocs
run pct push "$CTID" "$INSTALLER" /root/easy-install.sh --perms 0700
if [ -n "$GITHUB_TOKEN" ]; then
  TOK=$(mktemp); chmod 600 "$TOK"; printf '%s' "$GITHUB_TOKEN" >"$TOK"
  run pct push "$CTID" "$TOK" /etc/personaldocs/github-token --perms 0600
  rm -f "$TOK"; unset GITHUB_TOKEN
fi
if [ "$NAS_MODE" = 2 ]; then
  run pct exec "$CTID" -- bash -c 'printf "PD_NAS=3\nPD_NAS_PATH=/mnt/nas-backup/personaldocs\n" >> /etc/personaldocs/install-answers.env'
elif [ "$NAS_MODE" = 3 ]; then
  run pct exec "$CTID" -- bash -c 'printf "PD_NAS=4\n" >> /etc/personaldocs/install-answers.env'
fi

say ""
say "${G}Container $CTID is ready.${N} Starting the guided installer inside it…"
run pct exec "$CTID" -- bash /root/easy-install.sh
say ""
say "To open a shell in the container later: pct enter $CTID"
