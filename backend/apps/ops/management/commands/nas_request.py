import json

from django.core.management.base import BaseCommand, CommandError

from apps.ops import nas


class Command(BaseCommand):
    help = "Validate the NAS settings and queue a mount (or --unmount) request for the root helper."

    def add_arguments(self, parser):
        parser.add_argument("--unmount", action="store_true")
        parser.add_argument("--sync", action="store_true", help="Only adopt the result of the last request")

    def handle(self, *args, **opts):
        if opts["sync"]:
            self.stdout.write(json.dumps(nas.sync()))
            return
        try:
            nas.request_apply(None, "unmount" if opts["unmount"] else "mount")
        except nas.NasError as exc:
            raise CommandError(str(exc))
        self.stdout.write("NAS request queued")
