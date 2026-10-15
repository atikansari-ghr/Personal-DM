"""Safe post-upgrade performance maintenance (Change Set X); run by ``personaldocs post-upgrade`` and safe to rerun.

    python manage.py perf_maintenance [--no-analyze]

Steps (each logged; none deletes documents, history or settings):
1. Refresh PostgreSQL planner statistics (ANALYZE) so new indexes and changed data are planned well.
2. Check index validity: an index built CONCURRENTLY that was interrupted stays INVALID; ours are rebuilt
   concurrently (no lock on reading/writing documents), any other invalid index is reported.
3. Empty the shared cache (derived summaries only; rebuilt on demand).
4. Remove leftover temporary probe files of the storage-latency check.
5. Check the built app: index.html present, compressed copies present.
6. Remove performance measurements older than the retention period.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand
from django.db import connection

OWN_INDEXES = {"doc_active_folder_idx"}


class Command(BaseCommand):
    help = "Safe performance maintenance after an upgrade (statistics, index validity, cache, temporary files)."

    def add_arguments(self, parser):
        parser.add_argument("--no-analyze", action="store_true")

    def handle(self, *args, **o):
        from apps.core import perf

        done, problems = [], []
        t = time.monotonic()
        if not o["no_analyze"]:
            with connection.cursor() as cur:
                cur.execute("ANALYZE")
            done.append(f"statistics refreshed ({time.monotonic() - t:.1f} s)")
        with connection.cursor() as cur:
            cur.execute("SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid WHERE NOT i.indisvalid")
            invalid = [r[0] for r in cur.fetchall()]
        for name in invalid:
            if name in OWN_INDEXES:
                with connection.cursor() as cur:
                    cur.execute(f'REINDEX INDEX CONCURRENTLY "{name}"')
                done.append(f"index {name} rebuilt")
            else:
                problems.append(f"index {name} is invalid (not created by this release; check with a database administrator)")
        if not invalid:
            done.append("all indexes valid")
        cache_dir = Path(settings.DATA_DIR) / "cache" / "shared"
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
            done.append("shared cache emptied")
        tmp = Path(settings.TMP_DIR)
        removed = 0
        if tmp.exists():
            for p in tmp.glob(".perf-probe-*"):
                if time.time() - p.stat().st_mtime > 3600:
                    p.unlink(missing_ok=True)
                    removed += 1
        done.append(f"{removed} leftover probe file(s) removed")
        dist = Path(settings.FRONTEND_DIST)
        if not (dist / "index.html").exists():
            problems.append(f"the app is not built ({dist}/index.html missing)")
        else:
            compressed = len(list((dist / "static" / "app").glob("*.br")))
            done.append(f"app files present ({compressed} compressed copies)")
            if not compressed:
                problems.append("no compressed copies of the app files: rebuild the frontend (npm run build)")
        done.append(f"{perf.purge()} old performance measurement(s) removed")
        for line in done:
            self.stdout.write(f"  ok: {line}")
        for line in problems:
            self.stdout.write(self.style.WARNING(f"  warning: {line}"))
        perf.event("maintenance", "Post-upgrade performance maintenance: " + "; ".join(done + problems)[:280])
        if problems:
            raise SystemExit(1)
