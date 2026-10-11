"""Full-system disaster recovery from encrypted recovery points (Change Set T). Run as the service user with the web
application, worker and scheduler stopped:  sudo personaldocs recover  (interactive wrapper around this command)."""
import getpass
import json
import os

from django.core.management.base import BaseCommand, CommandError

from apps.ops import bk_crypto as C
from apps.ops import bk_recover as R


class Command(BaseCommand):
    help = "Inspect, analyse and run a full-system recovery (list | analyze | run | integrations | status)."
    requires_system_checks = []  # works on a clean server with an empty database

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "analyze", "run", "integrations", "status"])
        parser.add_argument("--source", help="local:/path | nas:/mnt/path | s3:https://endpoint/bucket/prefix | gdrive:<folder id> | onedrive:<folder>")
        parser.add_argument("--point", default="latest")
        parser.add_argument("--key-file", help="File containing the Backup Recovery Key (PDRK1-…). Default: prompt")
        parser.add_argument("--emergency-package", help="Emergency Recovery Package (.pdrp) instead of the key")
        parser.add_argument("--passphrase-file", help="File with the Emergency Recovery Package passphrase. Default: prompt")
        parser.add_argument("--mode", choices=["normal", "compromise"], default="normal")
        parser.add_argument("--reset-mfa", action="store_true", help="Compromise mode only: also reset passkeys and authenticator apps")
        parser.add_argument("--yes", action="store_true", help="Confirm replacing the current database and files")
        parser.add_argument("--json", action="store_true")

    def _key(self, o) -> bytes:
        if o["emergency_package"]:
            pw = open(o["passphrase_file"]).read().strip() if o["passphrase_file"] else getpass.getpass("Emergency package passphrase: ")
            return R.key_from(emergency_file=o["emergency_package"], passphrase=pw)
        if o["key_file"]:
            return R.key_from(open(o["key_file"]).read().strip())
        if os.environ.get("PD_RECOVERY_KEY"):
            return R.key_from(os.environ["PD_RECOVERY_KEY"])
        return R.key_from(getpass.getpass("Backup Recovery Key (PDRK1-…): "))

    def handle(self, *args, **o):
        say = self.stdout.write
        try:
            if o["action"] == "status":
                st = R.load_state()
                say(json.dumps({"in_progress": R.marker().exists(), "done": st.get("done", []), "point": st.get("point"),
                                "failed_at": st.get("failed_at")}, indent=1))
                return
            if o["action"] == "integrations":
                from apps.ops import bk_integrations as I

                I.verify()
                say(json.dumps(I.summary(), indent=1))
                return
            if not o["source"]:
                raise CommandError("--source is required.")
            prov = R.source_provider(o["source"])
            if o["action"] == "list":
                pts = R.list_points(prov)
                if o["json"]:
                    say(json.dumps(pts, indent=1))
                for p in pts:
                    say(f"{p['created_at'][:16]}  {p['kind']:<11} {p['point']}  key gen {p['generation']}  app {p['app_version']}"
                        f"  chain {len(p['chain'])}")
                if not pts:
                    say("No recovery points found at this source.")
                return
            key = self._key(o)
            if o["action"] == "analyze":
                st = R.fetch(prov, o["point"], key, say)
                st["verification"] = R.verify(st, say)
                R.save_state(st)
                a = R.analyze(st, o["mode"])
                say(json.dumps(a, indent=1, default=str))
                return
            if not o["yes"]:
                raise CommandError("Recovery replaces the current database and files. Review 'analyze' first, stop the services, "
                                   "then re-run with --yes.")
            report = R.run(prov, o["point"], key, mode=o["mode"], reset_mfa=o["reset_mfa"], say=say)
            say(self.style.SUCCESS(f"\nRecovery {report['status'].replace('_', ' ')}. Report: {report.get('run')}"))
            for f in report["follow_up"]:
                say(f"  - {f}")
        except (R.RecoverError, C.DecryptError) as exc:
            raise CommandError(str(exc))
