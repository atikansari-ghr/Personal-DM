#!/usr/bin/env python3
"""Basic family-scale concurrent use (Change Set X): several people browsing at the same time.

Each simulated person signs in, then repeatedly opens the dashboard data, the folder tree, a folder's documents,
a document and the notification count, like someone clicking through the app. Reports the median and 95th
percentile response time of all requests and the throughput. Standard library only.

    python3 scripts/perf_load.py --base http://localhost:8001 --users dad,mom,son1,daughter,son2,son3 \
        --password 'Sample-Passw0rd!' --seconds 30 [--slow-request /api/...]

``--slow-request`` additionally keeps one long request running the whole time (for example a large download),
to show whether one slow request makes everyone else wait.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import statistics
import threading
import time
import urllib.request


def session(base, user, password):
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.open(base + "/api/session").read()
    csrf = next((c.value for c in jar if c.name.endswith("csrftoken")), "")
    req = urllib.request.Request(base + "/api/auth/login", data=json.dumps({"username": user, "password": password}).encode(),
                                 headers={"Content-Type": "application/json", "X-CSRFToken": csrf, "Referer": base + "/login"})
    op.open(req).read()
    return op


def person(base, user, password, until, out, errors):
    try:
        op = session(base, user, password)
        folders = json.loads(op.open(base + "/api/folders").read())["folders"]
        withdocs = [f for f in folders if f.get("count")] or folders
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{user}: {exc}")
        return
    i = 0
    while time.time() < until:
        f = withdocs[i % len(withdocs)]["id"]
        for url in ("/api/dashboard", "/api/folders", f"/api/documents?folder={f}&limit=100",
                    "/api/notifications?status=unread&limit=5"):
            t = time.perf_counter()
            try:
                body = op.open(base + url).read()
                out.append((time.perf_counter() - t) * 1000)
                if "documents?" in url:
                    docs = json.loads(body).get("documents") or []
                    if docs:
                        t = time.perf_counter()
                        op.open(base + f"/api/documents/{docs[0]['id']}").read()
                        out.append((time.perf_counter() - t) * 1000)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{user} {url}: {exc}")
        i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8001")
    ap.add_argument("--users", default="dad,mom,son1,daughter,son2,son3")
    ap.add_argument("--password", default="Sample-Passw0rd!")
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--slow-request", default="")
    ap.add_argument("--out")
    a = ap.parse_args()
    until = time.time() + a.seconds
    times, errors = [], []
    threads = [threading.Thread(target=person, args=(a.base, u, a.password, until, times, errors)) for u in a.users.split(",")]
    if a.slow_request:
        def slow():
            op = session(a.base, a.users.split(",")[0], a.password)
            while time.time() < until:
                try:
                    op.open(a.base + a.slow_request, timeout=600).read()
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"slow: {exc}")
        threads.append(threading.Thread(target=slow))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    times.sort()
    res = {"requests": len(times), "per_second": round(len(times) / a.seconds, 1),
           "median_ms": round(statistics.median(times), 1) if times else None,
           "p95_ms": round(times[int(len(times) * 0.95) - 1], 1) if times else None,
           "max_ms": round(times[-1], 1) if times else None, "errors": errors[:5], "error_count": len(errors)}
    print(json.dumps(res))
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(res, fh)


if __name__ == "__main__":
    main()
