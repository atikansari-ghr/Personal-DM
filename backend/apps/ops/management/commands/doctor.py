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
        icons = ["manifest.webmanifest", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png",
                 "favicon.ico", "favicon-32.png"]
        missing = [f for f in icons if not (settings.FRONTEND_DIST / f).exists()]
        report("app icons and manifest (PWA identity)", not missing,
               ("missing: " + ", ".join(missing)) if missing else "served without sign-in; check the proxy with: sudo personaldocs check-access")
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
        try:
            self._ocr_checks(report, warn, info)
        except Exception as exc:  # noqa: BLE001
            warn("OCR engine checks could not run", exc.__class__.__name__)
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

    def _ocr_checks(self, report, warn, info):
        """Change Set Q: PaddleOCR / PP-OCRv5 — versions, models, a real inference self-test, queue and storage."""
        from apps.core import config
        from apps.core.models import Job
        from apps.library import ocr_admin, ocr_engines

        if not config.get("processing.ocr_enabled"):
            info("OCR", "turned off in Settings → OCR & processing")
            return
        engine = config.get("processing.ocr_engine")
        info("OCR default engine", ocr_engines.ENGINE_LABELS.get(engine, engine))
        st = ocr_engines.paddle_status(refresh=True)
        (report if engine == "paddleocr" else lambda n, ok, d: (info if ok else warn)(n, d))(
            "PaddleOCR installed", bool(st.get("installed") and not st.get("error")),
            (f"PaddleOCR {st.get('paddleocr')}, PaddlePaddle {st.get('paddle')} ({st.get('python')})" if st.get("installed")
             else f"{st.get('python')} missing") + (f" — {st.get('error')}" if st.get("error") else "")
            + ("" if st.get("installed") else " → sudo personaldocs repair"))
        if st.get("installed") and st.get("cpu_avx") is False:
            report("CPU supports AVX (needed by PaddlePaddle)", False, "set the container CPU type to host / x86-64-v2-AES or newer")
        if st.get("installed"):
            report("PP-OCRv5 models for the offered language profiles", not st.get("missing_models"),
                   "all present" if not st.get("missing_models") else "missing: " + ", ".join(st["missing_models"])
                   + " → sudo personaldocs ocr install-models")
            res = ocr_engines.paddle_selftest()
            report("PaddleOCR inference self-test (import alone is not enough)", bool(res.get("healthy")),
                   f"read “{res.get('text', '')}” in {res.get('seconds', '?')} s" if res.get("ok") else str(res.get("message")))
        tess = ocr_engines.tesseract_version()
        info("Tesseract (Legacy / fallback)", tess)
        info("OCR language profiles offered", ", ".join(ocr_engines.offered_profiles()))
        info("OCR queue", f"{Job.objects.filter(kind='ocr_run', status=Job.QUEUED).count()} queued, "
                          f"{Job.objects.filter(kind='ocr_run', status=Job.RUNNING).count()} running, "
                          f"{config.get('processing.heavy_concurrency')} at a time, PaddleOCR limit {config.get('processing.paddle_memory_mb')} MB")
        tmp = Path(settings.TMP_DIR)
        if tmp.exists():
            mode = tmp.stat().st_mode & 0o777
            (info if not mode & 0o007 else warn)("OCR temporary directory", f"{tmp} (mode {oct(mode)})" +
                                               ("" if not mode & 0o007 else " — readable by other users; chmod 750"))
        usage = ocr_admin.storage_usage()
        orphans = ocr_admin.orphan_analysis(summary=True)
        info("OCR data stored", f"{usage['total'] // 1024} KB (text, blocks, searchable copies, AI chunks)")
        if orphans["count"]:
            warn("Orphaned OCR data", f"{orphans['count']} item(s), {orphans['bytes'] // 1024} KB — Settings → OCR & processing → "
                                      "Existing OCR Data → Analyze / Clean")

    def _operations_checks(self, report, warn, info):
        """Change Set M: antivirus, signatures, host helper, exposure, storage thresholds, pending reboot."""
        from apps.core import config
        from apps.ops import host
        from apps.security import antivirus

        if config.get("antivirus.enabled"):
            h = antivirus.health(refresh=True)
            info("ClamAV socket used by the app", str(h.get("socket")))
            report("ClamAV scanner operational (reachable and scans)", h.get("state") in ("healthy", "degraded"),
                   f"{h.get('state_label')}: " + (h.get("error") or h.get("engine") or "")
                   + ("" if h.get("state") in ("healthy", "degraded") else " → sudo personaldocs antivirus repair"))
            if h.get("state") in ("healthy", "degraded"):
                st = antivirus.self_test()
                report("ClamAV self-test (clean file + EICAR, temporary files removed)", st["ok"], st["detail"])
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
        from apps.library import doctypes

        r = doctypes.report()
        info("document types", f"{r['typed']} typed, {r['untyped']} untyped ({r['with_suggestions']} with a suggestion), "
                               f"{r['unmapped_values']} previous values to review")
        if Path("/run/reboot-required").exists():
            warn("reboot required", "updated system packages need a reboot (Settings → Security → OS updates)")
