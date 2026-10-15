"""Server-side benchmark of the main API requests (Change Set X).

Runs inside one Django process against the configured database (normally the synthetic dataset from
``perf_dataset``), signed in through the real sign-in endpoint. For every request it records the median and the
slowest of several runs, the number of database queries, the database time and the response size, and writes JSON:

    python manage.py perf_bench --out perf-before.json [--runs 7] [--compare perf-before.json]

With ``--budget`` it fails (exit 1) when a request needs more queries or time than its budget: the permanent
performance regression gate (``tests/test_performance.py`` runs the same budgets on a smaller dataset).
"""
from __future__ import annotations

import json
import statistics
import time

from django.core.management import BaseCommand, CommandError
from django.db import connection, reset_queries
from django.test import Client
from django.test.utils import CaptureQueriesContext

PASSWORD = "Sample-Passw0rd!"


def requests_for(admin: bool, ids: dict) -> list[tuple[str, str]]:
    """(name, url) pairs. ids: big_folder, folder, document, search."""
    common = [
        ("branding (sign-in page)", "/api/branding"),
        ("session", "/api/session"),
        ("dashboard", "/api/dashboard"),
        ("settings (all values)", "/api/settings"),
        ("folders (tree)", "/api/folders"),
        ("folder documents, large folder, first page", f"/api/documents?folder={ids['big_folder']}&limit=100"),
        ("folder documents, large folder, 200", f"/api/documents?folder={ids['big_folder']}&limit=200"),
        ("folder documents, normal folder", f"/api/documents?folder={ids['folder']}&limit=100"),
        ("document details", f"/api/documents/{ids['document']}"),
        ("folder details", f"/api/folders/{ids['folder']}"),
        ("metadata (types, tags)", "/api/metadata"),
        ("notification banners (unread 5)", "/api/notifications?status=unread&limit=5"),
        ("notification centre", "/api/notifications"),
        ("my notification preferences", "/api/me/notification-preferences"),
        ("my sessions", "/api/me/sessions"),
        ("search", f"/api/documents?q={ids['search']}&limit=50"),
        ("help index", "/api/help"),
        ("sign-in map (7 days)", "/api/security/map"),
    ]
    if not admin:
        return common
    return common + [
        ("admin: family members", "/api/family/members"),
        ("admin: document types", "/api/document-types"),
        ("admin: activity log", "/api/audit"),
        ("admin: jobs", "/api/jobs"),
        ("admin: health", "/api/admin/health"),
        ("admin: security health", "/api/security/health"),
        ("admin: login audit", "/api/admin/security/logins"),
        ("admin: backup overview", "/api/backup/overview"),
        ("admin: connections", "/api/admin/connections"),
        ("admin: sign-in designs", "/api/signin-designs"),
    ]


class Command(BaseCommand):
    help = "Measure server time, query count and size of the main API requests."

    def add_arguments(self, parser):
        parser.add_argument("--out", help="Write results as JSON to this file")
        parser.add_argument("--runs", type=int, default=7)
        parser.add_argument("--compare", help="Earlier JSON result to compare against")
        parser.add_argument("--budget", action="store_true", help="Fail when a request exceeds its query/time budget")

    def handle(self, *args, **o):
        from apps.library.models import Document, Folder

        from django.db.models import Count

        folders = (Folder.objects.filter(archived_at__isnull=True, kind=Folder.NORMAL)
                   .annotate(n=Count("documents")).order_by("-n"))
        if not folders.exists():
            raise CommandError("No folders: run perf_dataset first (in a test database).")
        big = folders.first()
        normal = folders.filter(n__gte=5, n__lte=40).first() or folders.last()
        doc = Document.objects.filter(folder=normal, archived_at__isnull=True).first()
        ids = {"big_folder": big.pk, "folder": normal.pk, "document": doc.pk, "search": "renewal"}
        results = {"dataset": {"documents": Document.objects.count(), "folders": Folder.objects.count(),
                               "big_folder_documents": big.n}, "users": {}}
        for username, admin in (("dad", True), ("son1", False)):
            c = Client()
            t = time.perf_counter()
            r = c.post("/api/auth/login", {"username": username, "password": PASSWORD}, content_type="application/json")
            login_ms = (time.perf_counter() - t) * 1000
            if r.status_code != 200:
                raise CommandError(f"Sign-in as {username} failed: {r.status_code} {r.content[:200]!r}")
            rows = {"sign-in (password)": {"median_ms": round(login_ms, 1)}}
            uids = self._ids_for(c, ids)  # folders and a document this person may open
            for name, url in requests_for(admin, uids):
                rows[name] = self._measure(c, url, o["runs"])
            results["users"][username] = rows
        self._print(results, json.load(open(o["compare"])) if o.get("compare") else None)
        if o.get("out"):
            with open(o["out"], "w") as fh:
                json.dump(results, fh, indent=1)
        if o["budget"]:
            failures = budget_failures(results)
            if failures:
                raise CommandError("Performance budget exceeded:\n" + "\n".join(failures))

    def _ids_for(self, c, ids):
        import json as _json

        folders = [f for f in _json.loads(c.get("/api/folders").content)["folders"] if not f.get("path_only")]
        if not folders:
            return ids
        big = max(folders, key=lambda f: f.get("count") or 0)
        normal = next((f for f in folders if 5 <= (f.get("count") or 0) <= 40), big)
        docs = _json.loads(c.get(f"/api/documents?folder={normal['id']}&limit=1").content).get("documents") or []
        return {**ids, "big_folder": big["id"], "folder": normal["id"], "document": docs[0]["id"] if docs else ids["document"]}

    def _measure(self, c, url, runs):
        times, db_ms, queries, size, status = [], [], 0, 0, 0
        c.get(url)  # warm-up (imports, first-use caches)
        for _ in range(runs):
            reset_queries()
            with CaptureQueriesContext(connection) as q:
                t = time.perf_counter()
                r = c.get(url)
                times.append((time.perf_counter() - t) * 1000)
            queries = len(q.captured_queries)
            db_ms.append(sum(float(x.get("time") or 0) for x in q.captured_queries) * 1000)
            size, status = len(r.content), r.status_code
        return {"url": url, "status": status, "median_ms": round(statistics.median(times), 1),
                "max_ms": round(max(times), 1), "queries": queries, "db_ms": round(statistics.median(db_ms), 1),
                "bytes": size}

    def _print(self, results, before):
        for user, rows in results["users"].items():
            self.stdout.write(f"\n{user}")
            self.stdout.write(f"  {'request':48} {'median':>8} {'max':>8} {'queries':>8} {'db ms':>7} {'KB':>7}  before")
            for name, r in rows.items():
                prev = (before or {}).get("users", {}).get(user, {}).get(name)
                was = f"{prev['median_ms']} ms / {prev.get('queries', '-')} q" if prev else ""
                self.stdout.write(f"  {name[:48]:48} {r['median_ms']:>8} {r.get('max_ms', ''):>8} {r.get('queries', ''):>8} "
                                  f"{r.get('db_ms', ''):>7} {round(r.get('bytes', 0) / 1024, 1):>7}  {was}")


# Budgets: the regression gate. Generous enough for a slower server, tight enough to catch an N+1 query
# (a query count that grows with the data) or an unpaginated list. Times are server-side, in-process.
BUDGETS = {
    "default": {"queries": 40, "median_ms": 500},
    "sign-in (password)": {"median_ms": 1500},
}


def budget_failures(results) -> list[str]:
    out = []
    for user, rows in results["users"].items():
        for name, r in rows.items():
            b = BUDGETS.get(name, BUDGETS["default"])
            if "queries" in b and r.get("queries", 0) > b["queries"]:
                out.append(f"{user} {name}: {r['queries']} queries (budget {b['queries']})")
            if r.get("median_ms", 0) > b["median_ms"]:
                out.append(f"{user} {name}: {r['median_ms']} ms (budget {b['median_ms']} ms)")
            if r.get("status", 200) >= 400:
                out.append(f"{user} {name}: HTTP {r['status']}")
    return out
