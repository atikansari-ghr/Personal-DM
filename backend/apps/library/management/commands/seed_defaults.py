from django.core.management.base import BaseCommand

from apps.library.models import DocumentType
from apps.library.ocr_policy import TEMPLATE_FIELDS

DEFAULT_TYPES = [
    ("Passport", "passport", True, "🛂"), ("Visa", "visa", True, "🛃"), ("Iqama / Residence permit", "iqama", True, "🪪"),
    ("National ID", "national_id", False, "🪪"), ("Aadhaar card", "national_id", False, "🪪"), ("PAN card", "national_id", False, "🪪"),
    ("Driving license", "driving_license", True, "🚗"), ("Employee / company ID", "employee_id", True, "💼"), ("Vehicle registration", "generic", True, "🚗"),
    ("Insurance policy", "insurance", True, "🛡️"), ("Birth certificate", "certificate", False, "📜"),
    ("Marriage certificate", "certificate", False, "📜"), ("School certificate", "certificate", False, "🎓"),
    ("Degree / marks memo", "certificate", False, "🎓"), ("Medical report", "generic", False, "🩺"),
    ("Property deed", "generic", False, "🏠"), ("Tax receipt", "generic", False, "🧾"), ("Bank document", "generic", False, "🏦"),
    ("Ticket / itinerary", "generic", False, "✈️"), ("Application form", "generic", False, "📝"), ("Other", "generic", False, "📁"),
]


class Command(BaseCommand):
    help = "Create optional default document types (idempotent; existing types are left unchanged)."

    def handle(self, *args, **opts):
        n = 0
        for name, template, expiry, emoji in DEFAULT_TYPES:
            _, created = DocumentType.objects.get_or_create(name=name, defaults={
                "template": template, "has_expiry": expiry, "emoji": emoji, "ocr_languages": ["eng"],
                "ocr_fields": TEMPLATE_FIELDS.get(template, [])})
            n += created
        self.stdout.write(f"created {n} document type(s)")
