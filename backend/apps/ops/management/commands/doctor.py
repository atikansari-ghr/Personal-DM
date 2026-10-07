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

        def warn(name, detail=""):
            self.stdout.write(f"[WARN] {name}{(' - ' + detail) if detail else ''}")

        def info(name, detail=""):
            self.stdout.write(f"[INFO] {name}{(' - ' + detail) if detail else ''}")

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
        from apps.library import ocr_policy

        missing = ocr_policy.missing_languages()
        report("OCR language packs installed", not missing,
               f"missing: {', '.join(missing)} (run `sudo personaldocs repair`)" if missing else ", ".join(ocr_policy.installed_languages()))
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
        try:
            self._security_checks(report, warn, info)
        except Exception as exc:  # noqa: BLE001 - diagnostics must not crash
            warn("security checks could not run", exc.__class__.__name__)
        try:
            self._operations_checks(report, warn, info)
        except Exception as exc:  # noqa: BLE001
            warn("antivirus/host checks could not run", exc.__class__.__name__)
        raise SystemExit(0 if ok else 1)

    def _security_checks(self, report, warn, info):
        import os
        from datetime import date, timedelta

        from django.utils import timezone

        from apps.core import config
        from apps.security import geoip, netutil, traffic
        from apps.security.models import GeoPolicy, LoginEvent

        # Real client IP behind NPM / Pangolin
        info("trusted proxies", ", ".join(str(n) for n in netutil.trusted_networks()) or "none")
        recent = list(LoginEvent.objects.filter(at__gte=timezone.now() - timedelta(days=14)).values_list("ip", flat=True)[:30])
        hints = netutil.proxy_diagnostics([str(i) for i in recent if i])
        for h in hints:
            warn("real client IP", h)
        if recent and not hints:
            report("real client IPs recorded", True, f"{len(set(recent))} distinct addresses in recent sign-ins")
        # Access policy and GeoIP
        pol = GeoPolicy.get()
        gst = geoip.status()
        if os.environ.get("PD_ACCESS_POLICY_DISABLED") == "1":
            warn("access policy", "emergency switch PD_ACCESS_POLICY_DISABLED=1 is set: country/IP rules are NOT enforced")
        if pol.enabled and pol.mode != "off":
            report("access policy GeoIP database", gst["installed"] and not (gst["last_error"] and not gst["build_date"]),
                   f"mode={pol.mode}; without it every public address counts as 'unknown' ({pol.unknown_action})")
        else:
            info("access policy", "geographic filtering off")
        if gst["installed"]:
            age = (date.today() - date.fromisoformat(gst["build_date"])).days if gst["build_date"] else None
            if age is not None and age > 45:
                warn("GeoIP database age", f"{age} days old; update it (Settings → Security & access)")
            else:
                report("GeoIP database", True, f"{gst['database_type']} from {gst['build_date']}")
        if gst["last_error"]:
            warn("GeoIP last update", gst["last_error"])
        # GoAccess
        if config.get("goaccess.enabled"):
            st = traffic.status()
            report("access log configured", bool(st["access_log"]), st["access_log"] or "set PD_ACCESS_LOG (personaldocs repair does this)")
            if not st["goaccess_installed"]:
                warn("GoAccess", "not installed; the built-in summary is used (apt-get install goaccess)")
            last = st["last_report"]
            if not last or last < (timezone.now() - timedelta(hours=3)).isoformat():
                warn("traffic report", "older than 3 hours or missing; is personaldocs-scheduler running?")
            if st["error"]:
                warn("GoAccess report", st["error"])
        # Passkeys / WebAuthn
        if config.get("auth.allow_passkeys"):
            from apps.accounts.passkeys import diagnostics

            for name, good, detail in diagnostics():
                (report if good else lambda n, g, d: warn(n, d + " (passkeys will not work)"))(f"passkeys: {name}", good, detail)
        # Local AI
        if config.get("ai.enabled"):
            from apps.ai.models import AIJob, AIProfile

            profiles = AIProfile.objects.filter(enabled=True)
            report("Local AI default profile", profiles.filter(is_default=True).exists() or profiles.count() == 1,
                   "Settings → Local AI → Add AI profile")
            for p in profiles.filter(privacy="external"):
                warn("Local AI external endpoint", f"profile '{p.name}' may send document text outside your network")
            failed = AIJob.objects.filter(status="failed", created_at__gte=timezone.now() - timedelta(days=1)).count()
            if failed:
                warn("Local AI jobs", f"{failed} failed in the last 24 hours (Settings → Local AI → AI jobs)")

    def _operations_checks(self, report, warn, info):
        """Change Set M: antivirus, signatures, host helper, exposure, storage thresholds, pending reboot."""
        from apps.core import config
        from apps.ops import host
        from apps.security import antivirus

        if config.get("antivirus.enabled"):
            h = antivirus.health(refresh=True)
            report("ClamAV daemon reachable", h.get("status") != "unavailable",
                   h.get("engine") or h.get("error") or "")
            if h.get("signatures_date"):
                detail = f"version {h.get('signatures')}, {h.get('signature_age_days')} days old"
                if h.get("critically_stale"):
                    report("ClamAV signatures up to date", False, detail + " (check clamav-freshclam)")
                elif h.get("stale"):
                    warn("ClamAV signatures", detail)
                else:
                    info("ClamAV signatures", detail)
            from apps.library.models import DocumentVersion

            stuck = DocumentVersion.objects.filter(av_status="pending").count()
            if stuck:
                info("files waiting for an antivirus scan", str(stuck))
        else:
            warn("antivirus scanning", "turned off in Settings → Security → Antivirus")
        if host.installed():
            info("host helper", "installed (Settings → Security can check updates, firewall and reboot)")
        else:
            warn("host helper", "not installed; run `sudo personaldocs repair`")
        if config.get("security.deployment") == "internet" and not settings.PUBLIC_ORIGIN.startswith("https://"):
            report("Internet-facing deployment uses HTTPS", False, "set PD_PUBLIC_ORIGIN to the https:// address")
        warn_pct, crit_pct = int(config.get("storage.warn_percent")), int(config.get("storage.critical_percent"))
        import shutil as _sh

        du = _sh.disk_usage(settings.DATA_DIR if Path(settings.DATA_DIR).exists() else "/")
        pct = du.used / du.total * 100 if du.total else 0
        if pct >= crit_pct:
            report("storage below the critical threshold", False, f"{pct:.0f}% used (critical at {crit_pct}%)")
        elif pct >= warn_pct:
            warn("storage", f"{pct:.0f}% used (warning at {warn_pct}%)")
        if Path("/run/reboot-required").exists():
            warn("reboot required", "updated system packages need a reboot (Settings → Security → OS updates)")
