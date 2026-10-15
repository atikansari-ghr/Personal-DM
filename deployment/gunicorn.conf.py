"""Gunicorn settings for personaldocs-web (Change Set X).

Measured on the synthetic performance dataset with six people browsing at once while two CPU-heavy background
processes shared the same two CPU cores (docs/PERFORMANCE.md): two workers with four threads each answered
36 requests/s (median 142 ms) where two single-threaded workers answered 24.5/s (median 222 ms). Threads let a slow
request (a large download, a long report) wait without holding up everyone else, for about 13 MB more memory per
worker. Values come from the environment file with these defaults, so an older environment file still works.

    PD_WEB_WORKERS  processes (default 2)          PD_WEB_THREADS  threads per process (default 4)
"""
import os

workers = int(os.environ.get("PD_WEB_WORKERS") or 2)
threads = int(os.environ.get("PD_WEB_THREADS") or 4)
worker_class = "gthread" if threads > 1 else "sync"
keepalive = 5  # keep browser connections open between the requests of one screen
