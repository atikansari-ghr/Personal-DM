"""ClamAV checks as the Personal DM service account (the identity that must reach clamd's socket).

    manage antivirus status              read-only diagnosis (socket, access, engine, operational state)
    manage antivirus selftest            clean file + EICAR test pattern through the upload scan path
    manage antivirus sync-socket PATH    store the effective socket path (set by personaldocs antivirus repair)
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core import audit, config
from apps.ops.clamav_check import format_report
from apps.security import antivirus as av


class Command(BaseCommand):
    help = "Antivirus (ClamAV) status, self-test and socket path."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("status", "selftest", "sync-socket"))
        parser.add_argument("path", nargs="?")

    def handle(self, *args, action, path=None, **opts):
        if action == "sync-socket":
            if not path or not path.startswith("/") or "\0" in path or len(path) > 200:
                raise CommandError("give the absolute socket path")
            if config.get("antivirus.socket") != path:
                old = config.get("antivirus.socket")
                config.set_value("antivirus.socket", path)
                audit.record("antivirus.socket_changed", actor=None, old=old, new=path, source="personaldocs antivirus repair")
                self.stdout.write(f"antivirus.socket: {old} -> {path}")
            else:
                self.stdout.write(f"antivirus.socket already {path}")
            return
        if action == "status":
            self.stdout.write(format_report(av.diagnose()))
            h = av.health(refresh=True)
            self.stdout.write(f"Application view: {h['state_label']} (socket {h.get('socket')}) {h.get('error') or ''}".rstrip())
            return
        if not config.get("antivirus.enabled"):
            raise CommandError("Antivirus scanning is turned off in Settings → Security → Antivirus.")
        res = av.self_test()
        self.stdout.write(f"Application self-test via {res['socket']}: {'PASSED' if res['ok'] else 'FAILED'} — {res['detail']}"
                          f" (temporary files removed: {'yes' if res['artifacts_removed'] else 'NO'})")
        if not res["ok"]:
            raise CommandError("antivirus self-test failed")
