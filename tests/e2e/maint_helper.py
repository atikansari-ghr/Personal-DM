"""Stand-in for personaldocs-host.service in the browser tests (Change Set AB).

Watches <data>/host for maintenance requests and processes them with the real root helper (host_helper.HostHelper),
which runs a scripted `personaldocs` command. That command sources the real CLI's progress functions (step / meta /
die from scripts/personaldocs) and plays the scenario named in the scenario file, so the browser sees exactly what a
real upgrade, restart or repair reports — without changing this machine.

    python tests/e2e/maint_helper.py DATA_DIR SCENARIO_FILE
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "apps" / "ops"))
from host_helper import HostHelper  # noqa: E402

SCRIPT = r"""#!/usr/bin/env bash
set -Eeuo pipefail
LOG_DIR=/nonexistent; LOG=/dev/null; UNITS=(personaldocs-web personaldocs-worker personaldocs-scheduler)
. "__HELPERS__"
SC=$(cat "__SCENARIO__" 2>/dev/null || echo ok)
P=${SLEEP:-0.8}
echo "personaldocs $* (scripted scenario: $SC)"
case "$1" in
  check-updates)
    step source running "https://github.com/OWNER/Personal-DM.git (main)"; sleep "$P"; step source ok
    step compare running; sleep "$P"; step compare ok available
    jq -cn '{state:"available",installed_version:"0.1.0",installed_revision:"1a2b3c4d5e6f",available_version:"0.2.0",
      available_revision:"6f5e4d3c2b1a",channel:"main",source:"https://github.com/OWNER/Personal-DM.git",tag:"v0.2.0",behind:3,
      commits:["6f5e4d3 Maintenance & Operations in Settings","5e4d3c2 Active Sessions tile","4d3c2b1 Upgrade notes"],warnings:[],
      checked_at:(now|todate)}';;
  upgrade)
    FAIL_OUTCOME=remains_operational
    step lock running; step lock ok
    step preflight running; meta version_from "0.1.0-1a2b3c4d5e"; sleep "$P"; step preflight ok "installed release 0.1.0-1a2b3c4d5e"
    step target running main; meta version_to "0.2.0-6f5e4d3c2b"; sleep "$P"; step target ok "0.2.0-6f5e4d3c2b"
    step disk running; sleep "$P"
    if [ "$SC" = fail-disk ]; then echo "df: /var/lib/personaldocs 812 MB available"; die "less than 2 GB free (812 MB); free space before upgrading"; fi
    step disk ok "18432 MB free"
    step backup running; sleep "$P"
    if [ "$SC" = fail-backup ]; then
      echo "backup: destination 'NAS backups' unreachable (connection timed out)"
      die "pre-upgrade backup failed or could not be verified (fix the destination, or rerun with --skip-backup if you have a verified backup)"
    fi
    meta backup_ref "verified pre-upgrade recovery point (Settings → Backup & Recovery)"; step backup ok "verified recovery point created"
    step backup_verify running; sleep "$P"; meta backup_ref "/var/lib/personaldocs/pre-upgrade/db-20261025-101500.pgdump"; step backup_verify ok "database snapshot readable"
    step fetch running; sleep "$P"; step fetch ok
    step dependencies running; sleep "$P"; step dependencies ok
    step frontend running; sleep "$P"; step frontend ok
    step migrations running; FAIL_OUTCOME=recovery_required; sleep "$P"; step migrations ok
    step restart running; sleep "$P"; step restart ok
    step health running; sleep "$P"; step health ok "all services active; /api/health OK"
    FAIL_OUTCOME=""; meta outcome succeeded; echo "Upgraded 0.1.0 -> 0.2.0";;
  restart)
    step lock running; step lock ok; step restart running "${UNITS[*]}"; sleep "$P"; step restart ok
    step health running; sleep "$P"; step health ok "all services active; /api/health OK";;
  repair)
    step lock running; step lock ok
    for item in ${3//,/ }; do
      step "repair_$item" running; sleep "$P"
      [ "$item" = directories ] && mkdir -p "__DATA__/tmp"
      step "repair_$item" ok
    done
    step health running; sleep "$P"; step health ok;;
  rollback)
    FAIL_OUTCOME=remains_operational; step lock running; step lock ok; step preflight running; step preflight ok
    step compatibility running; sleep "$P"
    die "database contains migrations unknown to 0.1.0-1a2b3c4d5e; a code-only rollback is not safe. Restore the pre-upgrade recovery point instead";;
  *) die "unexpected command $1";;
esac
"""


def main() -> int:
    data, scenario = Path(sys.argv[1]), Path(sys.argv[2])
    work = scenario.parent
    src = (ROOT / "scripts" / "personaldocs").read_text()
    helpers = work / "cli-helpers.sh"
    helpers.write_text(src[src.index("# ------------------------------------------------------------------ helpers"):
                           src.index("# ------------------------------------------------------------------ preflight")])
    cli = work / "personaldocs"
    cli.write_text(SCRIPT.replace("__HELPERS__", str(helpers)).replace("__SCENARIO__", str(scenario)).replace("__DATA__", str(data)))
    cli.chmod(0o755)
    h = HostHelper(data, cli=str(cli))
    h._write("helper.json", {"installed": True, "note": "e2e stand-in"})
    done: set = set()
    while True:  # maintenance requests only (the queue); other host actions are never run on this machine
        for q in sorted((h.dir / "queue").glob("*.json")) if (h.dir / "queue").is_dir() else []:
            h._apply_one(q, done)
            q.unlink(missing_ok=True)
        time.sleep(0.3)


if __name__ == "__main__":
    sys.exit(main())
