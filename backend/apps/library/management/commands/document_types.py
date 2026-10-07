"""`personaldocs manage document_types report` — how many documents are typed, untyped or have a suggestion."""
from django.core.management.base import BaseCommand

from apps.library import doctypes


class Command(BaseCommand):
    help = "Report document type coverage (read-only). Types are assigned only by people; nothing is changed here."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="report", choices=["report"])

    def handle(self, *args, **opts):
        r = doctypes.report()
        self.stdout.write(f"typed documents:            {r['typed']}")
        self.stdout.write(f"untyped documents:          {r['untyped']}")
        self.stdout.write(f"  with a pending suggestion: {r['with_suggestions']}")
        self.stdout.write(f"  in a folder that suggests a type: {r['folder_suggestions']}")
        self.stdout.write(f"values waiting for review after a type change: {r['unmapped_values']}")
        self.stdout.write("Review suggestions in Settings → Documents & folders → Document types → Review untyped documents.")
