from django.core.management.base import BaseCommand, CommandError

from apps.ops import backup


class Command(BaseCommand):
    help = "Run an application-level backup to the configured destination now."

    def handle(self, *args, **opts):
        try:
            result = backup.run_backup()
        except backup.BackupError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f"Backup written to {result['path']} ({result['files']} files, verified={result['verified']})"))
