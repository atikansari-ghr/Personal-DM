#!/usr/bin/env bash
# Lifecycle checks for the one-line installer (personal-DM.sh) with stubbed system commands.
#
# Verifies the decisions the script makes (OS and root checks, fresh install vs. upgrade, fail-loudly paths,
# delegation to the tested `personaldocs` CLI / easy-install.sh, no secrets in logs) without touching the
# machine. A real installation must still be tested on a Debian 13 VM/LXC (docs/RELEASE_CHECKLIST.md).
#
#   sudo bash tests/installer/test_personal_dm.sh
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SCRIPT=$ROOT/personal-DM.sh
[ "$(id -u)" -eq 0 ] || { echo "SKIP: run as root (the script refuses to run otherwise)"; exit 0; }
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
pass=0; failn=0
ok() { echo "PASS $*"; pass=$((pass+1)); }
bad() { echo "FAIL $*"; failn=$((failn+1)); }

# ---- sandbox: fake Debian 13, systemd dir, stub commands recording their calls
mkdir -p "$T/bin" "$T/systemd" "$T/prefix" "$T/log"
printf 'ID=debian\nVERSION_ID=13\nPRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n' >"$T/debian13"
printf 'ID=ubuntu\nVERSION_ID=24.04\nPRETTY_NAME="Ubuntu 24.04"\n' >"$T/ubuntu"
for c in systemctl apt-get; do printf '#!/bin/sh\necho "%s $*" >>"%s/calls"\n' "$c" "$T" >"$T/bin/$c"; done
cat >"$T/bin/personaldocs" <<EOF
#!/bin/sh
echo "personaldocs \$*" >>"$T/calls"
[ "\$1" = doctor ] && [ -f "$T/doctor-fails" ] && exit 1
exit 0
EOF
chmod +x "$T/bin/"*
# a local "GitHub" repository with an easy-install.sh stub
git init -q "$T/origin" && mkdir -p "$T/origin/scripts"
printf '#!/bin/sh\necho "easy-install $* ref=$PD_REF" >>"%s/calls"\n' "$T" >"$T/origin/scripts/easy-install.sh"
echo "9.9.9" >"$T/origin/VERSION"
git -C "$T/origin" add -A && git -C "$T/origin" -c user.email=t@example.invalid -c user.name=t commit -qm init && git -C "$T/origin" branch -qM main

runit() { # runit OSFILE args...  -> stdout+stderr in $T/out, exit code in $rc
  local os=$1; shift
  : >"$T/calls"
  PATH="$T/bin:$PATH" PD_OS_RELEASE="$os" PD_SYSTEMD_DIR="$T/systemd" PD_PREFIX="$T/prefix" PD_LOG_DIR="$T/log" \
    PD_SRC="$T/src" PD_REPO_URL="$T/origin" bash "$SCRIPT" "$@" </dev/null >"$T/out" 2>&1
  rc=$?
}
calls() { cat "$T/calls" 2>/dev/null; }

runit "$T/ubuntu" status
[ $rc -ne 0 ] && grep -q "Debian 13 (trixie) only" "$T/out" && ok "refuses other operating systems" || bad "OS check ($rc)"

PATH="$T/bin:$PATH" PD_OS_RELEASE="$T/debian13" PD_SYSTEMD_DIR="$T/nope" bash "$SCRIPT" status </dev/null >"$T/out" 2>&1
[ $? -ne 0 ] && grep -q "systemd is not running" "$T/out" && ok "refuses systems without systemd" || bad "systemd check"

runit "$T/debian13" upgrade
[ $rc -ne 0 ] && grep -q "not installed here yet" "$T/out" && ! calls | grep -q "personaldocs upgrade" && ok "upgrade on a fresh machine fails loudly and changes nothing" || bad "upgrade before install"

runit "$T/debian13" install --yes
[ $rc -eq 0 ] && [ -d "$T/src/.git" ] && calls | grep -q "easy-install --yes ref=main" && ok "fresh install clones the source and starts the guided installer" || { bad "fresh install ($rc)"; cat "$T/out"; }

runit "$T/debian13" install --yes  # second run: source updated in place, installer re-run is safe
[ $rc -eq 0 ] && calls | grep -q "easy-install" && ok "install is idempotent (re-run updates the checkout)" || bad "install re-run"

echo "local edit" >>"$T/src/VERSION"
runit "$T/debian13" install --yes
[ $rc -ne 0 ] && grep -q "local changes" "$T/out" && ok "local changes in the checkout are never overwritten" || bad "dirty checkout"
git -C "$T/src" checkout -q -- VERSION

ln -s "$T/prefix/releases/x" "$T/prefix/current"   # now "installed"
runit "$T/debian13" upgrade --ref main
[ $rc -eq 0 ] && calls | grep -qx "personaldocs upgrade --ref main" && calls | grep -qx "personaldocs doctor" && ok "upgrade delegates to personaldocs upgrade (backup + rollback) then doctor" || { bad "upgrade ($rc)"; calls; }

touch "$T/doctor-fails"
runit "$T/debian13" upgrade
[ $rc -ne 0 ] && grep -q "some checks failed" "$T/out" && ok "a failing health check after upgrade is reported, not hidden" || bad "doctor failure"
rm -f "$T/doctor-fails"

for c in repair doctor status backup; do
  runit "$T/debian13" "$c"
  [ $rc -eq 0 ] && calls | grep -q "^personaldocs $c" && ok "$c delegates to personaldocs $c" || bad "$c"
done

runit "$T/debian13" restore /nonexistent
[ $rc -ne 0 ] && grep -q "Not a folder" "$T/out" && ok "restore validates the backup folder" || bad "restore validation"
mkdir -p "$T/bk"
runit "$T/debian13" --dry-run restore "$T/bk"
[ $rc -eq 0 ] && grep -q "dry-run" "$T/out" && ok "restore dry-run verifies first and changes nothing" || bad "restore dry-run"

runit "$T/debian13" recover-admin 'bad name;rm'
[ $rc -ne 0 ] && grep -q "valid username" "$T/out" && ok "recover-admin validates the username" || bad "recover-admin validation"

runit "$T/debian13" frobnicate
[ $rc -ne 0 ] && grep -q "Unknown command" "$T/out" && ok "unknown commands fail" || bad "unknown command"

runit "$T/debian13" --ref 'main;rm -rf /' status
[ $rc -ne 0 ] && ok "rejects unsafe --ref values" || bad "--ref validation"

if grep -rqiE "token|password=" "$T/log" 2>/dev/null; then bad "log contains secret-like text"; else ok "no secrets in the log"; fi

echo "----"; echo "$pass passed, $failn failed"
[ $failn -eq 0 ]
