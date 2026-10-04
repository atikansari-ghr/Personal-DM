from django.core.management.base import BaseCommand

from apps.library import storage
from apps.library.models import DocumentVersion
from apps.library.pdfa import validate, verapdf_cmd


class Command(BaseCommand):
    help = "Re-validate searchable PDF/A copies (veraPDF when installed, otherwise a structural check) and store the results."

    def add_arguments(self, parser):
        parser.add_argument("--failed-only", action="store_true", help="Only versions not yet marked compliant")

    def handle(self, *args, **opts):
        self.stdout.write(f"validator: {'veraPDF at ' + verapdf_cmd() if verapdf_cmd() else 'built-in structural check'}")
        qs = DocumentVersion.objects.exclude(searchable_path="")
        if opts["failed_only"]:
            qs = qs.filter(pdfa=False)
        ok = bad = 0
        for v in qs.iterator():
            report = validate(storage.resolve_derivative(v.searchable_path))
            DocumentVersion.objects.filter(pk=v.pk).update(pdfa=bool(report.get("compliant")), pdfa_report=report)
            ok, bad = (ok + 1, bad) if report.get("compliant") else (ok, bad + 1)
            if not report.get("compliant"):
                self.stdout.write(f"NOT COMPLIANT {v.id}: " + "; ".join(r.get("description", "") for r in report.get("failed_rules", [])[:3]))
        self.stdout.write(f"compliant: {ok}, not compliant: {bad}")
