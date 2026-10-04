from django.core.management.base import BaseCommand

from apps.library.models import Document
from apps.library.search import update_search_vector


class Command(BaseCommand):
    help = "Rebuild full-text search vectors for all documents (safe; used by `personaldocs repair`)."

    def handle(self, *args, **opts):
        n = 0
        for doc in Document.objects.select_related("owner", "doc_type", "correspondent").iterator():
            update_search_vector(doc)
            n += 1
        self.stdout.write(f"reindexed {n} document(s)")
