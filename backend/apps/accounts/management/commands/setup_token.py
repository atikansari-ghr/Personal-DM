from django.core.management.base import BaseCommand, CommandError

from apps.accounts import services as S


class Command(BaseCommand):
    help = "Print a one-time code (valid 24h) that unlocks the first-run setup wizard."

    def handle(self, *args, **opts):
        try:
            token = S.new_setup_token()
        except S.AccountError as exc:
            raise CommandError(str(exc))
        self.stdout.write("One-time setup code (valid 24 hours, shown once):")
        self.stdout.write(f"  {token}")
        self.stdout.write("Open the web app and enter this code on the setup screen.")
