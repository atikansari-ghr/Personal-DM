import json

from django.core.management.base import BaseCommand

from apps.ops import integrity


class Command(BaseCommand):
    help = "Check storage integrity. --repair shows planned safe repairs; add --confirm to apply them."

    def add_arguments(self, parser):
        parser.add_argument("--no-checksums", action="store_true")
        parser.add_argument("--repair", action="store_true")
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **opts):
        if opts["repair"]:
            for a in integrity.repair(dry_run=not opts["confirm"]):
                self.stdout.write(("APPLIED: " if opts["confirm"] else "PLAN: ") + a)
            return
        report = integrity.check(verify_checksums=not opts["no_checksums"])
        self.stdout.write(json.dumps(report, indent=1))
        if not report["ok"]:
            raise SystemExit(2)
