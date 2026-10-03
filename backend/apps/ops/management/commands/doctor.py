"""Diagnostics with redacted output: `personaldocs doctor`."""
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "Diagnose configuration, services, tools, storage and database state (read-only)."

    def handle(self, *args, **opts):
        ok = True

        def report(name, good, detail=""):
            nonlocal ok
            ok = ok and good
            self.stdout.write(f"[{'OK' if good else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")

        try:
            with connection.cursor() as cur:
                cur.execute("SELECT version()")
                report("database reachable", True, cur.fetchone()[0].split(",")[0])
            pending = MigrationExecutor(connection).migration_plan(MigrationExecutor(connection).loader.graph.leaf_nodes())
            report("migrations applied", not pending, f"{len(pending)} pending" if pending else "")
        except Exception as exc:  # noqa: BLE001
            report("database reachable", False, exc.__class__.__name__)
        for d in (settings.DATA_DIR, settings.ORIGINALS_DIR, settings.DERIVATIVES_DIR, settings.STAGING_DIR, settings.TMP_DIR):
            p = Path(d)
            report(f"directory {p}", p.is_dir() and shutil.os.access(p, shutil.os.W_OK))
        from apps.core import crypto

        report("encryption key present", crypto.key_path().exists(), str(crypto.key_path()))
        for name, cmd in (("ocrmypdf", settings.OCRMYPDF_CMD[0]), ("tesseract", settings.TESSERACT_CMD), ("libreoffice", settings.SOFFICE_CMD),
                          ("pdftoppm", settings.PDFTOPPM_CMD), ("pg_dump", settings.PG_DUMP_CMD)):
            report(f"tool {name}", shutil.which(cmd) is not None)
        du = shutil.disk_usage(settings.DATA_DIR if Path(settings.DATA_DIR).exists() else "/")
        report("free disk > 2 GB", du.free > 2 * 1024 ** 3, f"{du.free // 1024 ** 2} MB free")
        report("public origin uses HTTPS", settings.PUBLIC_ORIGIN.startswith("https://"), settings.PUBLIC_ORIGIN)
        report("frontend built", (settings.FRONTEND_DIST / "index.html").exists())
        from apps.ops.backup import BackupError, check_target

        try:
            check_target()
            report("backup destination", True)
        except BackupError as exc:
            report("backup destination", False, str(exc))
        from apps.core.models import Job

        failed = Job.objects.filter(status="failed").count()
        report("no failed jobs", failed == 0, f"{failed} failed" if failed else "")
        raise SystemExit(0 if ok else 1)
