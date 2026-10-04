"""Apply settings from a JSON file ({"key": value, ...}) with full validation. Used by the guided installer so
secrets (e.g. the SMB password) never appear in command-line arguments. The file is deleted afterwards."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core import config
from apps.core.registry import BY_KEY, GLOBAL, SettingError


class Command(BaseCommand):
    help = "Apply validated global settings from a JSON file and delete the file."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--keep", action="store_true", help="Do not delete the file")

    def handle(self, *args, file, keep, **opts):
        path = Path(file)
        try:
            values = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise CommandError(f"Cannot read {file}: {exc}")
        finally:
            if not keep:
                path.unlink(missing_ok=True)
        errors = []
        for key, value in values.items():
            defn = BY_KEY.get(key)
            if defn is None or defn.scope != GLOBAL:
                errors.append(f"{key}: unknown setting")
                continue
            try:
                config.set_value(key, value)
                self.stdout.write(f"set {key}" if not defn.secret else f"set {key} (secret)")
            except SettingError as exc:
                errors.append(f"{defn.label}: {exc}")
        if errors:
            raise CommandError("; ".join(errors))
