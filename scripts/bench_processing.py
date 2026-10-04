"""Indicative processing benchmark with synthetic scans.

Run from backend/ with the service environment, e.g. on the LXC:
  sudo personaldocs manage shell -c "exec(open('/opt/personaldocs/current/scripts/bench_processing.py').read())"
or in development:  cd backend && PYTHONPATH=. N=50 BENCH_USER=son2 ../.venv/bin/python ../scripts/bench_processing.py
Creates documents in a "bench" folder of BENCH_USER; archive and purge them afterwards.
"""
import os, sys, time, resource
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests"))
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "personaldocs.settings")
if not __import__("django.apps", fromlist=["apps"]).apps.ready:
    django.setup()
from fixtures import make_image_pdf, make_text_pdf
from apps.accounts.models import User
from apps.library import storage, services as S
from apps.library.models import Folder
from apps.core import jobs
u = User.objects.get(username=os.environ.get("BENCH_USER", "son2"))
root = Folder.objects.get(owner=u, kind="personal_root")
bench = Folder.objects.filter(parent=root, name="bench").first() or S.create_folder(actor=u, parent=root, name="bench")
N = int(os.environ.get("N", 12))
total_bytes = 0
t0 = time.time()
for i in range(N):
    data = make_image_pdf(f"SYNTHETIC SCAN {i}\nSAMPLE PERSON\nDate of expiry 01/01/2030") if i % 2 == 0 else make_text_pdf(f"Born digital {i}\n" * 40)
    total_bytes += len(data)
    S.create_document(actor=u, folder=bench, owner=u, staged=storage.stage_stream([data], f"bench-{i}.pdf"))
t1 = time.time()
n = jobs.run_pending(max_jobs=1000, heavy_limit=1)
t2 = time.time()
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
print(f"docs={N} (half image-only scans) bytes={total_bytes} upload_s={t1-t0:.2f} processed={n} processing_s={t2-t1:.1f} per_doc_s={(t2-t1)/N:.2f} peak_child_rss_MB={ru.ru_maxrss/1024:.0f} self_rss_MB={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f}")
