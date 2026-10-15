"""Create the synthetic performance dataset (Change Set X).

A representative family installation, larger than most families need, used to expose scaling problems
(N+1 queries, unpaginated lists, slow counts) without real family data. Every name, number and address is
generated: names come from a fixed sample list, document numbers are random strings, IP addresses are from the
documentation ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32).

    python manage.py perf_dataset --yes            # into an EMPTY database (refuses otherwise)

Sizes (defaults; adjustable): 6 people, about 400 folders (one personal tree per person, two very large
folders), 8,000 documents with a current version and 4 details each, 3,000 notifications, 30,000 activity-log
entries, 5,000 sign-in events and 600 background jobs. The files themselves are not created: list and detail views
never read the file (previews and downloads are measured separately with real uploads in the browser tests).
"""
from __future__ import annotations

import random
import uuid
from datetime import date, timedelta

from django.core.management import BaseCommand, CommandError, call_command
from django.db import connection, transaction
from django.utils import timezone

FAMILY = [("dad", "Alex Sample"), ("mom", "Maria Sample"), ("son1", "Sam Sample"), ("daughter", "Dana Sample"),
          ("son2", "Theo Sample"), ("son3", "Leo Sample")]
PASSWORD = "Sample-Passw0rd!"
TOPICS = ["Passports", "Residence", "Insurance", "Bank", "School", "Medical", "Vehicle", "House", "Utilities", "Tax",
          "Travel", "Warranty", "Employment", "Certificates", "Receipts", "Pension", "Phone", "Internet"]
WORDS = ["annual", "statement", "renewal", "policy", "card", "letter", "invoice", "receipt", "certificate", "report",
         "contract", "notice", "summary", "application", "approval", "copy", "scan", "form"]


class Command(BaseCommand):
    help = "Create the synthetic performance dataset in an empty database (never in production data)."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirm: create synthetic data in this database")
        parser.add_argument("--documents", type=int, default=8000)
        parser.add_argument("--folders", type=int, default=400)
        parser.add_argument("--audit", type=int, default=30000)
        parser.add_argument("--signins", type=int, default=5000)
        parser.add_argument("--notifications", type=int, default=3000)
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, *args, **o):
        from apps.accounts.models import User
        from apps.library.models import Document

        if not o["yes"]:
            raise CommandError("This creates thousands of synthetic records. Run it only in a test database, with --yes.")
        if Document.objects.exists() or User.objects.filter(is_active=True).count() > 1:
            raise CommandError("The database already holds documents or people. Use an empty test database.")
        rnd = random.Random(o["seed"])
        call_command("seed_defaults", verbosity=0)
        users = self._family()
        with transaction.atomic():
            folders = self._folders(rnd, users, o["folders"])
            docs = self._documents(rnd, users, folders, o["documents"])
            self._logs(rnd, users, docs, o)
        with connection.cursor() as cur:  # the same weights as library.search.update_search_vector
            cur.execute("""UPDATE library_document SET search_vector =
                           setweight(to_tsvector('english', title), 'A') ||
                           setweight(to_tsvector('english', content_text), 'C')""")
            cur.execute("ANALYZE")
        self.stdout.write(self.style.SUCCESS(
            f"Synthetic dataset: {len(users)} people, {len(folders)} folders, {len(docs)} documents. Password for every "
            f"person: {PASSWORD}"))

    # ------------------------------------------------------------------ people and folders
    def _family(self):
        from apps.accounts import services as S
        from apps.accounts.models import User

        S.complete_setup({"group_name": "Sample family", "timezone": "Asia/Riyadh", "members": [
            {"slot": u, "display_name": n, "username": u, "password": PASSWORD} for u, n in FAMILY]})
        User.objects.update(must_change_password=False)
        return list(User.objects.filter(is_active=True).order_by("pk"))

    def _folders(self, rnd, users, n):
        from apps.library.models import Folder

        roots = list(Folder.objects.filter(kind=Folder.PERSONAL_ROOT, archived_at__isnull=True))
        roots += list(Folder.objects.filter(kind=Folder.SHARED, archived_at__isnull=True))
        out = list(Folder.objects.filter(archived_at__isnull=True))
        frontier = list(roots)
        made = 0
        while made < n:
            parent = rnd.choice(frontier)
            name = f"{rnd.choice(TOPICS)} {rnd.randint(2015, 2026)} {made}"
            f = Folder.objects.create(parent=parent, name=name, owner_id=parent.owner_id, group_id=parent.group_id,
                                      kind=Folder.NORMAL, created_by=users[0])
            out.append(f)
            if len(frontier) < 200 or rnd.random() < 0.3:
                frontier.append(f)
            made += 1
        return out

    def _documents(self, rnd, users, folders, n):
        from apps.library.models import Document, DocumentField, DocumentType, DocumentVersion, Folder

        types = list(DocumentType.objects.filter(archived=False))
        big = [f for f in folders if f.kind == Folder.NORMAL][:2]  # two very large folders (1,500 documents each)
        today = date.today()
        docs, versions, fields = [], [], []
        for i in range(n):
            folder = big[i % 2] if i < 3000 and big else rnd.choice(folders)
            owner_id = folder.owner_id or rnd.choice(users).pk
            t = rnd.choice(types) if types and rnd.random() < 0.8 else None
            title = f"{rnd.choice(TOPICS)} {rnd.choice(WORDS)} {rnd.choice(WORDS)} {i}"
            expiry = today + timedelta(days=rnd.randint(-400, 1500)) if rnd.random() < 0.5 else None
            d = Document(id=uuid.uuid4(), folder=folder, owner_id=owner_id, title=title, doc_type=t, type_confirmed=bool(t),
                         type_source="manual" if t else "", expiry_date=expiry, state=Document.READY,
                         ocr_state=rnd.choice(["not_processed", "confirmed", "needs_review"]),
                         content_text=" ".join(rnd.choice(WORDS) for _ in range(60)), created_by_id=owner_id)
            v = DocumentVersion(id=uuid.uuid4(), document=d, number=1, original_name=f"scan-{i}.pdf",
                                storage_path=f"perf/{d.id}.pdf", size=rnd.randint(40_000, 4_000_000),
                                sha256=uuid.uuid4().hex + uuid.uuid4().hex, mime="application/pdf", format_class="pdf",
                                page_count=rnd.randint(1, 6), state="ready", av_status="clean", created_by_id=owner_id)
            docs.append(d)
            versions.append(v)
            for key in ("full_name", "document_number", "issue_date", "expiry_date"):
                value = {"full_name": rnd.choice(FAMILY)[1], "document_number": uuid.uuid4().hex[:9].upper(),
                         "issue_date": (today - timedelta(days=rnd.randint(30, 3000))).isoformat(),
                         "expiry_date": expiry.isoformat() if expiry else ""}[key]
                fields.append(DocumentField(document=d, key=key, value=value, status="confirmed", source="manual",
                                            confidence=round(rnd.uniform(0.5, 1.0), 2)))
        Document.objects.bulk_create(docs, batch_size=1000)
        DocumentVersion.objects.bulk_create(versions, batch_size=1000)
        for d, v in zip(docs, versions):
            d.current_version_id = v.id
        Document.objects.bulk_update(docs, ["current_version"], batch_size=1000)
        DocumentField.objects.bulk_create(fields, batch_size=2000)
        # timestamps spread over three years (auto_now_add set them all to now)
        with connection.cursor() as cur:
            cur.execute("UPDATE library_document SET created_at = now() - (random() * interval '1100 days')")
        return docs

    # ------------------------------------------------------------------ notifications, activity, sign-ins, jobs
    def _logs(self, rnd, users, docs, o):
        from apps.core.models import AuditEvent, Job
        from apps.notify.models import Notification
        from apps.security.models import LoginEvent

        now = timezone.now()
        nets = ["192.0.2.", "198.51.100.", "203.0.113."]
        Notification.objects.bulk_create([
            Notification(user=rnd.choice(users), kind="expiry", title=f"Sample notification {i}", body="Synthetic.",
                         event="expiry.reminder", category="documents", severity=rnd.choice(["info", "warning", "critical"]),
                         summary="Synthetic notification", read_at=None if rnd.random() < 0.3 else now,
                         document=rnd.choice(docs) if rnd.random() < 0.5 else None)
            for i in range(o["notifications"])], batch_size=1000)
        actions = ["document.view", "document.upload", "document.update", "folder.create", "auth.login", "settings.update"]
        AuditEvent.objects.bulk_create([
            AuditEvent(actor=rnd.choice(users), action=rnd.choice(actions), target_type="document",
                       target_id=str(rnd.choice(docs).id), ip=rnd.choice(nets) + str(rnd.randint(1, 254)))
            for _ in range(o["audit"])], batch_size=2000)
        LoginEvent.objects.bulk_create([
            LoginEvent(at=now - timedelta(minutes=rnd.randint(1, 500_000)), user=rnd.choice(users),
                       result=rnd.choice(["success"] * 9 + ["failure"]), method="password",
                       ip=rnd.choice(nets) + str(rnd.randint(1, 254)) if rnd.random() < 0.9 else f"2001:db8::{rnd.randint(1, 999)}",
                       country="SA", browser="Firefox", os="Linux", device="desktop", network="public", risk="normal",
                       location="Sample City", lat=24.7 + rnd.random(), lon=46.6 + rnd.random(), coord_source="geoip_city")
            for _ in range(o["signins"])], batch_size=2000)
        Job.objects.bulk_create([
            Job(kind=rnd.choice(["thumbnail", "process_document", "av_scan"]), status=Job.DONE, run_after=now,
                finished_at=now, payload={}) for _ in range(600)], batch_size=1000)
        with connection.cursor() as cur:
            cur.execute("UPDATE core_auditevent SET at = now() - (random() * interval '700 days')")
