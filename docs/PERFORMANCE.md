# Performance: measurements, targets and how to repeat them (Change Set X)

The administrator guide is [guides/performance.md](guides/performance.md). This page records how performance is
measured, the BEFORE and AFTER results of Change Set X, and the regression gate. Raw results are in
[`performance/before/`](performance/before/) and [`performance/after/`](performance/after/).

## Test environment and conditions {#environment}

| | |
| --- | --- |
| Machine | Development container: 4 vCPU, 16 GB RAM, no swap, local SSD; Ubuntu 24.04, PostgreSQL 16 (default settings: shared_buffers 128 MB, work_mem 4 MB, max_connections 100), Python 3.13, Node 22 |
| Production-equivalent 6 GB LXC | **Not available here (Blocked / Not Executed).** To approach it, the web server was pinned to **2 CPU cores** (`taskset -c 0,1`) for the AFTER runs and all contention runs, and memory use was measured (below) against a 6 GB budget |
| Server | `DEBUG=0` production settings; gunicorn on port 8001; BEFORE: 2 sync workers (the old service file), AFTER: `deployment/gunicorn.conf.py` (2 workers × 4 threads) |
| Data | Synthetic dataset (`manage.py perf_dataset`): 6 people, 408 folders (two with 1,500+ documents), 8,000 documents with versions and 4 details each, 3,000 notifications, 30,000 activity entries, 5,000 sign-ins, 600 jobs. No real data |
| Browser | Chromium (Playwright), fresh profile per flow (cold cache), network emulated as a home LAN/Wi-Fi link (20 ms latency, 40/20 Mbit/s), CPU slowed 2× |
| "Usable" | The screen's own content is shown and nothing on it is loading (`aria-busy`) |
| Contention | Two CPU-bound processes on the same 2 cores: one at the job worker's priority (nice 5, like OCR), one at normal priority (like clamd) |

Note: the BEFORE runs *without* contention used all 4 cores; the AFTER runs used 2. The comparison is therefore
conservative for the AFTER numbers. All contention runs used 2 cores on both sides.

## Before → After → Target {#results}

Median of 5 runs (3 under contention), milliseconds.

| Flow | Before | After | Under contention: before → after | Target | Result |
| --- | ---: | ---: | --- | ---: | --- |
| Sign-in page usable | 513 | 337 | 608 → 484 | ≤ 1,500 | **Pass** |
| Sign-in → dashboard usable | 935 | 831 | 1,134 → 1,055 | ≤ 2,000 | **Pass** |
| Settings initial (General) | 357 | 191 | 484 → 227 | ≤ 1,500 | **Pass** |
| Settings section, previously loaded | 707 | 301 | 919 → 316 | ≤ 500 | **Pass** |
| Settings section, first visit (Backup & Recovery) | 242 | 216 | 301 → 308 | — | Informational |
| Folder browse, large folder (1,500 documents) | 1,093 | 610 | 1,142 → 818 | ≤ 1,000 | **Pass** |
| Folder browse, normal folder | 509 | 495 | 657 → 642 | ≤ 1,000 | **Pass** |
| Document Details open | 438 | 428 | 478 → 492 | ≤ 1,000 | **Pass** |
| Search (8,000 documents) | 866 | 496 | 1,098 → 634 | ≤ 1,000–2,000 | **Pass** |
| Typical API request (server time, in-process) | 8–399 | 7–105 | — | preferably ≤ 500 | **Pass** |

On the BEFORE code, two targets were missed on this machine (cached Settings switch 707 ms, large folder 1,093 ms).
They would be missed by a wider margin on a slower container.

### Transfer and code size

| | Before | After |
| --- | ---: | ---: |
| Sign-in page download | 886 KB (6 requests) | 89 KB |
| Main JavaScript file | 829 KB, sent uncompressed, cached 60 s | 252 KB raw / **72 KB Brotli** / 82 KB gzip, cached as immutable |
| Settings General data | 112 KB | 8 KB |
| Settings code before a section is opened | all sections (128 KB) | shell 5 KB + the section opened |

The sign-in page now makes more requests (21) because the screens likely to be needed next are fetched in the
background once the page is usable. They are not counted in "usable" time and later screens open from cache.

### Server time, database queries (main administrator, synthetic dataset)

| Request | Before | After |
| --- | --- | --- |
| Settings (all values) | 187 ms, 196 queries | 18 ms, 5 queries |
| Notification preferences | 399 ms, 381 queries | 12 ms, 7 queries |
| Folder documents, 100 rows | 183 ms, 108 queries | 44 ms, 7 queries |
| Folder documents, 200 rows | 367 ms, 208 queries | 74 ms, 7 queries |
| Session check (every page load) | 44 ms, 44 queries | 16 ms, 12 queries |
| Dashboard | 121 ms, 59 queries | 93 ms, 32 queries (health summaries computed fresh) |
| Search | 386 ms, 58 queries | 96 ms, 7 queries |
| Sign-in designs | 46 ms, 36 queries | 19 ms, 14 queries |
| Family members | 44 ms, 42 queries | 34 ms, 29 queries (one query per person remains: passkey counts; family scale) |

Slowest remaining query: search snippets (`ts_headline`), about 70 ms on 8,000 documents: part of the unchanged
search design.

### Concurrent family use

Six people browsing at once for 30 s (`scripts/perf_load.py`), server on 2 cores.

| | Requests/s | Median | 95th percentile |
| --- | ---: | ---: | ---: |
| Before | 28.0 | 203 ms | 315 ms |
| After | **42.8** | **125 ms** | 280 ms |
| Before, with background contention | 19.8 | 274 ms | 428 ms |
| After, with background contention, 2 sync workers | 24.5 | 222 ms | 368 ms |
| After, with background contention, 2 × 4 threads (shipped) | **37.2** | **139 ms** | 329 ms |

### Memory and headroom (6 GB budget)

| Component | Measured |
| --- | --- |
| Web worker (gthread, 4 threads) | 126 MB each × 2 (sync: 113 MB) + master 25 MB |
| PostgreSQL | 85 MB database fully cached (100 % buffer hit ratio) with default settings: no change needed |
| Database connections | 8 under load (of 100) |
| Job worker | unchanged: one job at a time, systemd MemoryHigh 3.4 GB / MemoryMax 4 GB (OCR peaks) |

The web service grows by about 26 MB in total. PostgreSQL settings were not changed because nothing measured
pointed to them.

### Adaptive throttling (live check)

Real sampler, all 4 cores at 100 % CPU, threshold temporarily 60 %
([`after/throttle-live.txt`](performance/after/throttle-live.txt)): the first hot sample did not throttle (brief
spikes ignored), the second did ("CPU 100%"). A deferrable job (GeoIP update) stayed queued while other work could
start. After the load stopped, throttling ended after three calm samples. Start and end were recorded as events.

## Bottlenecks found {#bottlenecks}

| # | Bottleneck | Cause | Fix |
| --- | --- | --- | --- |
| 1 | Settings slow, notification preferences slow, session check on every page | Every setting read was its own database query (196 for Settings, 381 for notification preferences) | Settings read once per request (one query), per person once; secrets never kept |
| 2 | Large folders slow | One extra query per document row (current version not joined); every row also fetched the full recognised text and the search index; `DISTINCT` over all those columns | Version joined; large columns deferred; `DISTINCT` only for the tag filter |
| 3 | Documents past 200 unreachable in the folder view | The folder view requested 200 rows and never more | Incremental loading, 100 per page, scroll or **Load more** |
| 4 | Every screen downloaded the whole app | One 829 KB file for every page, sent uncompressed and cached only 60 s | Route and Settings-section code splitting, idle prefetch, precompressed (Brotli/gzip) immutable files |
| 5 | Settings fetched everything for every section, again on every switch | One endpoint returned all settings; sections re-fetched on remount | Section filter, cached section data shown at once and refreshed, cancelled on leave |
| 6 | Slow requests made everyone wait under load | 2 single-threaded web workers: two slow requests blocked the app | 2 workers × 4 threads (measured +48 % throughput under contention) |
| 7 | Dashboard | Four separate document counts, full document rows | One aggregate query, deferred columns (health summaries are not cached: they must never be stale) |
| 8 | Folder tree counts grow with the library | Sequential scan for per-folder counts | Partial index `doc_active_folder_idx` (index-only scan: 9.1 → 1.3 ms at 8,000 documents), built concurrently |

## How to repeat the measurements {#repeat}

```
# a separate, empty database (never production)
createdb -O personaldocs pd_perf
PD_DB_NAME=pd_perf python manage.py migrate
PD_DB_NAME=pd_perf python manage.py perf_dataset --yes
# server-side times and query counts, with the regression budget
PD_DB_NAME=pd_perf python manage.py perf_bench --out perf.json --budget [--compare docs/performance/before/before-api.json]
# a production-like server on that database, then the browser flows and concurrent use
PD_DB_NAME=pd_perf gunicorn personaldocs.wsgi --config ../deployment/gunicorn.conf.py -b 127.0.0.1:8001
BASE=http://localhost:8001 PERF_BIG_FOLDER=<id> PERF_FOLDER=<id> PERF_OUT=pages.json node tests/e2e/perf.mjs
python3 scripts/perf_load.py --base http://localhost:8001 --seconds 30
```

## Regression gate {#gate}

- `tests/test_performance.py` (in the normal test run): query counts that must not grow with the data (documents,
  dashboard, folder tree), pagination returning every document exactly once in every sort order, list rows without
  document text, cache correctness and invalidation, throttling behaviour, Performance pages without private data,
  and `perf_bench --budget` on a small synthetic dataset (40 queries / 500 ms per request).
- Bundle budget: the main JavaScript file must stay under 400 KB (checked when the frontend is built).
- `tests/e2e/corrective.mjs`: Settings loads only the open section, Backup code loads only when opened, compressed
  immutable app files, Performance page restricted to administrators.
