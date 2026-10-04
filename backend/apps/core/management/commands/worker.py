"""Processing worker: `manage.py worker` (systemd: personaldocs-worker.service)."""
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from apps.core import config, jobs


class Command(BaseCommand):
    help = "Run background jobs (OCR, previews, imports, backups). Use --once to drain the queue and exit."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--sleep", type=float, default=2.0)

    def handle(self, *args, **opts):
        from apps.library import storage
        from apps.notify.models import SchedulerRun

        storage.ensure_dirs()
        stop = {"flag": False}

        def _term(*_):
            stop["flag"] = True  # finish the current job, then exit (graceful shutdown)

        signal.signal(signal.SIGTERM, _term)
        signal.signal(signal.SIGINT, _term)
        if opts["once"]:
            n = jobs.run_pending(max_jobs=10000, heavy_limit=int(config.get("processing.heavy_concurrency")))
            self.stdout.write(f"processed {n} job(s)")
            return
        wid = jobs.worker_id()
        self.stdout.write(f"worker {wid} started")
        last_beat = 0.0
        while not stop["flag"]:
            close_old_connections()
            if time.time() - last_beat > 30:
                SchedulerRun.objects.update_or_create(name="worker_heartbeat", defaults={"last_run_at": timezone.now()})
                last_beat = time.time()
            job = jobs.claim(wid, heavy_limit=int(config.get("processing.heavy_concurrency")))
            if job is None:
                time.sleep(opts["sleep"])
                continue
            jobs.run_job(job)
        self.stdout.write("worker stopped")
