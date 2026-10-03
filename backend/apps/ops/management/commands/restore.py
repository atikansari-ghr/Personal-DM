from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.ops import backup


class Command(BaseCommand):
    help = "Verify and restore an application backup (stop web/worker/scheduler first)."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--verify-only", action="store_true")
        parser.add_argument("--no-key", action="store_true", help="Do not restore the encryption key from the backup")
        parser.add_argument("--yes", action="store_true", help="Confirm replacing the current database")

    def handle(self, *args, path, verify_only, no_key, yes, **opts):
        p = Path(path)
        if not (p / "manifest.json").exists():
            raise CommandError("Not a Personal Documents backup folder (manifest.json missing).")
        check = backup.verify_backup(p)
        self.stdout.write(f"Verification: {'OK' if check['ok'] else 'FAILED'} ({check['files']} files, {len(check['bad'])} problems)")
        if verify_only:
            return
        if not yes:
            raise CommandError("Restoring replaces the current database. Re-run with --yes after stopping the services.")
        try:
            result = backup.restore_backup(p, include_key=not no_key)
        except backup.BackupError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f"Restored {result['files_restored']} originals; key restored: {result['key_restored']}"))
