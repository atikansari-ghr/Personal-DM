"""Change Set X: performance optimisation. The change prompt numbered these AT-376…AT-400; here they are
AT-401…AT-425 (prompt AT-n = AT-(n+25)). All data is synthetic.

Query-count tests compare a small and a larger dataset: a count that grows with the data is an N+1 regression.
"""
from __future__ import annotations

import io
import json
import re
import uuid
from pathlib import Path

import pytest
from conftest import personal_root
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core import config

ROOT = Path(__file__).resolve().parent.parent


def _queries(client, url):
    client.get(url)  # warm-up
    with CaptureQueriesContext(connection) as q:
        r = client.get(url)
    assert r.status_code == 200, (url, r.status_code, r.content[:200])
    return len(q.captured_queries), r


def _bulk_docs(folder, owner, n, *, prefix="Perf doc"):
    """n synthetic documents with a current version (no files: list and detail views never read them)."""
    from apps.library.models import Document, DocumentVersion

    docs, versions = [], []
    for i in range(n):
        d = Document(id=uuid.uuid4(), folder=folder, owner=owner, title=f"{prefix} {i}", state=Document.READY,
                     content_text="synthetic renewal statement " * 50)
        v = DocumentVersion(id=uuid.uuid4(), document=d, number=1, original_name=f"f{i}.pdf", storage_path=f"perf/{d.id}.pdf",
                            size=1000 + i, sha256=uuid.uuid4().hex * 2, mime="application/pdf", format_class="pdf", state="ready")
        docs.append(d)
        versions.append(v)
    Document.objects.bulk_create(docs)
    DocumentVersion.objects.bulk_create(versions)
    for d, v in zip(docs, versions):
        d.current_version_id = v.id
    Document.objects.bulk_update(docs, ["current_version"])
    with connection.cursor() as cur:
        cur.execute("UPDATE library_document SET search_vector = to_tsvector('english', title || ' ' || content_text) WHERE id = ANY(%s)",
                    [[d.id for d in docs]])
    return docs


# ------------------------------------------------------------------ AT-401 baseline / AT-423 regression suite
@pytest.mark.django_db(transaction=True)
def test_at401_at423_synthetic_dataset_and_benchmark_budgets(tmp_path):
    """The reproducible benchmark runs on a sanitised synthetic dataset and every request stays within budget."""
    call_command("perf_dataset", "--yes", "--documents", "400", "--folders", "40", "--audit", "300", "--signins", "200",
                 "--notifications", "100", stdout=io.StringIO())
    with pytest.raises(Exception):  # never into a database that already holds data
        call_command("perf_dataset", "--yes", stdout=io.StringIO())
    out = tmp_path / "bench.json"
    call_command("perf_bench", "--runs", "2", "--out", str(out), "--budget", stdout=io.StringIO())
    res = json.loads(out.read_text())
    assert res["dataset"]["documents"] == 400
    for user in ("dad", "son1"):
        rows = res["users"][user]
        assert rows["folder documents, large folder, first page"]["queries"] <= 15
        assert rows["my notification preferences"]["queries"] <= 15
        assert rows["settings (all values)"]["queries"] <= 10


# ------------------------------------------------------------------ AT-402 sign-in
def test_at402_signin_page_data_cached_and_invalidated_without_losing_methods(family, clients):
    from django.test import Client

    from apps.core import designs, perfcache

    anon = Client()
    first = anon.get("/api/branding").json()
    assert anon.get("/api/branding").json() == first
    assert perfcache.stats()["branding"]["hits"] >= 1
    config.set_value("login.title", "Sample family archive")  # any sign-in page change retires the cached copy
    assert anon.get("/api/branding").json()["title"] == "Sample family archive"
    nature = designs.ensure_builtins() or designs.SigninDesign.objects.get(builtin_key="nature") if hasattr(designs, "SigninDesign") else None
    from apps.core.models import SigninDesign

    nature = SigninDesign.objects.get(builtin_key="nature")
    designs.activate(nature, actor=family["dad"])
    assert anon.get("/api/branding").json()["design"] == "nature"
    # password sign-in, passkey options and the session are unaffected
    s = anon.get("/api/session").json()
    assert "passkeys_enabled" in s or "google_enabled" in s
    assert anon.post("/api/auth/passkey/options", {"purpose": "passwordless"}, content_type="application/json").status_code in (200, 400, 403)
    assert anon.post("/api/auth/login", {"username": "dad", "password": "Sample-Passw0rd!"}, content_type="application/json").status_code == 200


# ------------------------------------------------------------------ AT-403 dashboard
def test_at403_dashboard_query_count_does_not_grow_and_data_stays_scoped(family, clients):
    dad, son = family["dad"], family["son1"]
    _bulk_docs(personal_root(dad), dad, 5)
    small, _ = _queries(clients["dad"], "/api/dashboard")
    _bulk_docs(personal_root(dad), dad, 60, prefix="More")
    large, r = _queries(clients["dad"], "/api/dashboard")
    assert large <= small + 2, (small, large)
    assert r.json()["stats"]["documents"] == 65
    _bulk_docs(personal_root(son), son, 3, prefix="Son")
    mine = clients["son1"].get("/api/dashboard").json()
    assert mine["stats"]["documents"] == 3  # a family member counts only what they may open
    assert all(d["title"].startswith("Son") for d in mine["recent"])


# ------------------------------------------------------------------ AT-404 / AT-405 Settings on demand
def test_at404_settings_section_request_returns_only_that_section_and_never_widens(family, clients):
    full = clients["dad"].get("/api/settings").json()["settings"]
    general = clients["dad"].get("/api/settings?section=general").json()["settings"]
    assert general and {s["section"] for s in general} == {"general"}
    assert len(general) < len(full)
    keyed = clients["dad"].get("/api/settings?keys=general.app_name,weather.default_city").json()["settings"]
    assert {s["key"] for s in keyed} == {"general.app_name", "weather.default_city"}
    # a family member cannot see more by asking for an administrator section
    member_all = {s["key"] for s in clients["son1"].get("/api/settings").json()["settings"]}
    member_auth = {s["key"] for s in clients["son1"].get("/api/settings?section=authentication").json()["settings"]}
    assert member_auth <= member_all
    assert not any(k.startswith("auth.") for k in member_auth)


def test_at405_settings_save_is_seen_by_the_next_request_and_brief_responses(family, clients):
    r = clients["dad"].put("/api/settings?brief=1", {"values": {"general.app_name": "Sample Archive"}}, format="json")
    assert r.status_code == 200 and r.json() == {"saved": ["general.app_name"]}
    got = clients["dad"].get("/api/settings?keys=general.app_name").json()["settings"][0]["value"]
    assert got == "Sample Archive"
    r = clients["dad"].put("/api/settings?section=general", {"values": {"general.app_name": "Sample Archive 2"}}, format="json")
    assert {s["section"] for s in r.json()["settings"]} == {"general"}


# ------------------------------------------------------------------ AT-406 ORM / N+1
def test_at406_list_endpoints_do_not_run_a_query_per_row(family, clients):
    dad = family["dad"]
    root = personal_root(dad)
    _bulk_docs(root, dad, 10)
    url = f"/api/documents?folder={root.pk}&limit=100"
    small, _ = _queries(clients["dad"], url)
    _bulk_docs(root, dad, 70, prefix="Bulk")
    large, r = _queries(clients["dad"], url)
    assert large == small, (small, large)
    assert len(r.json()["documents"]) == 80
    for url in ("/api/me/notification-preferences", "/api/family/members", "/api/session", "/api/settings"):
        n, _ = _queries(clients["dad"], url)
        assert n <= 30, (url, n)


# ------------------------------------------------------------------ AT-407 indexes
def test_at407_partial_folder_index_is_valid_and_used(family):
    with connection.cursor() as cur:
        cur.execute("SELECT i.indisvalid, pg_get_indexdef(i.indexrelid) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                    "WHERE c.relname = 'doc_active_folder_idx'")
        valid, definition = cur.fetchone()
    assert valid and "WHERE (archived_at IS NULL)" in definition
    from apps.library.migrations import __path__ as mig  # noqa: F401
    src = (ROOT / "backend/apps/library/migrations/0012_doc_active_folder_idx.py").read_text()
    assert "CONCURRENTLY IF NOT EXISTS" in src and "DROP INDEX CONCURRENTLY IF EXISTS" in src and "atomic = False" in src


# ------------------------------------------------------------------ AT-408 cache correctness
def test_at408_settings_snapshot_is_per_request_per_person_and_never_holds_secrets(family, clients):
    from apps.core import perfcache

    config.set_value("smtp.password", "s3cret-sample-value")
    config.begin_request()
    try:
        assert config.is_set("smtp.password")
        rows = config._app_rows()
        assert "s3cret-sample-value" not in json.dumps({k: v for k, v in rows.items() if isinstance(v, (str, int, list, dict, bool))})
        assert config.get("smtp.password") == "s3cret-sample-value"  # secrets are always read from the database
        config.set_user(family["dad"], "me.theme", "blue")
        config.set_user(family["mom"], "me.theme", "glass_dark")
        assert config.get_user(family["dad"], "me.theme") == "blue"
        assert config.get_user(family["mom"], "me.theme") == "glass_dark"  # no cross-user reuse
        config.set_value("general.app_name", "Changed within the request")
        assert config.get("general.app_name") == "Changed within the request"
    finally:
        config.end_request()
    # the shared cache: hits, misses and explicit invalidation
    calls = []
    assert perfcache.cached("unit", 60, lambda: calls.append(1) or "v") == "v"
    assert perfcache.cached("unit", 60, lambda: calls.append(1) or "w") == "v"
    perfcache.invalidate("unit")
    assert perfcache.cached("unit", 60, lambda: calls.append(1) or "w") == "w"
    assert len(calls) == 2 and perfcache.stats()["unit"]["hits"] == 1


# ------------------------------------------------------------------ AT-409 / AT-410 frontend (static checks; the browser suites run the screens)
def test_at409_screens_and_settings_sections_load_on_demand():
    app = (ROOT / "frontend/src/App.tsx").read_text()
    settings = (ROOT / "frontend/src/pages/Settings.tsx").read_text()
    assert "lazyPage(load.folders)" in app and "prefetchWhenIdle" in app
    assert 'import { ChangePassword, ForcedTwoFactor, ForgotPassword, Login, ResetPassword } from "./pages/Auth"' in app  # auth stays eager
    for section in ("./settings/Backup", "./settings/SecurityCenter", "./settings/Account", "./settings/Performance"):
        assert f'import("{section}")' in settings
    assert "import BackupPanel from" not in settings
    dist = ROOT / "frontend/dist/static/app"
    if dist.exists():  # bundle budget (when the frontend is built)
        main = [p for p in dist.glob("main-*.js")]
        assert main and max(p.stat().st_size for p in main) < 400_000, "main bundle over 400 KB"


def test_at410_api_client_dedupes_cancels_and_clears_cached_sections_on_write():
    api = (ROOT / "frontend/src/api.ts").read_text()
    assert "inflight" in api and "signal: opts.signal" in api and "recent.clear()" in api
    folders = (ROOT / "frontend/src/pages/Folders.tsx").read_text()
    assert "docsCtl.current?.abort()" in folders and "IntersectionObserver" in folders


# ------------------------------------------------------------------ AT-411 / AT-412 / AT-413 browsing
@pytest.mark.parametrize("sort", ["-added", "name", "-size", "expiry", "type"])
def test_at411_pagination_returns_every_document_exactly_once_in_server_order(family, clients, sort):
    dad = family["dad"]
    root = personal_root(dad)
    docs = _bulk_docs(root, dad, 230)
    seen = []
    for offset in range(0, 300, 100):
        r = clients["dad"].get(f"/api/documents?folder={root.pk}&limit=100&offset={offset}&sort={sort}").json()
        assert r["total"] == 230
        seen += [d["id"] for d in r["documents"]]
    assert len(seen) == 230 and set(seen) == {str(d.id) for d in docs}
    # another person sees no rows and no count of this folder
    r = clients["son1"].get(f"/api/documents?folder={root.pk}&limit=100")
    assert r.status_code in (403, 404) or r.json()["total"] == 0


def test_at412_list_rows_carry_no_document_text_or_binary_and_files_load_only_on_request(family, clients):
    dad = family["dad"]
    root = personal_root(dad)
    _bulk_docs(root, dad, 3)
    with CaptureQueriesContext(connection) as q:
        r = clients["dad"].get(f"/api/documents?folder={root.pk}")
    body = r.content.decode()
    assert "synthetic renewal statement" not in body
    listing = [x["sql"] for x in q.captured_queries if 'FROM "library_document"' in x["sql"] and "LIMIT" in x["sql"]]
    assert listing and all('"library_document"."content_text"' not in s for s in listing)
    row = r.json()["documents"][0]
    assert "has_thumbnail" in row and "content_text" not in row
    assert clients["dad"].get(f"/api/documents/{row['id']}/thumbnail")["Cache-Control"].startswith("no-store")


def test_at413_folder_tree_query_count_does_not_grow_with_folders(family, clients):
    from apps.library import services as S

    dad = family["dad"]
    small, _ = _queries(clients["dad"], "/api/folders")
    parent = personal_root(dad)
    for i in range(60):
        parent = S.create_folder(actor=dad, parent=parent if i % 10 else personal_root(dad), name=f"Level {i}")
    large, r = _queries(clients["dad"], "/api/folders")
    assert large <= small + 1, (small, large)
    assert len([f for f in r.json()["folders"] if f["name"].startswith("Level")]) == 60
    assert not any(f["name"].startswith("Level") for f in clients["son1"].get("/api/folders").json()["folders"])


# ------------------------------------------------------------------ AT-414 / AT-415 background priority and throttling
def _sample(**kw):
    return {"cpu_percent": 20.0, "mem_available_percent": 60.0, "swap_used_percent": None, "psi_io": 0.0, **kw}


def test_at414_throttled_worker_starts_urgent_work_and_postpones_others_for_a_bounded_time(family):
    from datetime import timedelta

    from django.utils import timezone

    from apps.core import jobs, throttle
    from apps.core.models import Job

    for _ in range(2):
        throttle.evaluate(_sample(cpu_percent=99.0))
    throttle._cache["at"] = 0
    assert throttle.active()
    ocr = jobs.enqueue("geoip_update", {})
    urgent = jobs.enqueue("security_test", {}, priority=200)
    picked = jobs.claim("test-worker")
    assert picked is not None and picked.pk == urgent.pk  # urgent work is not held back
    assert Job.objects.get(pk=ocr.pk).status == Job.QUEUED
    assert jobs.claim("test-worker") is None  # the deferrable job waits while throttled
    Job.objects.filter(pk=ocr.pk).update(run_after=timezone.now() - timedelta(minutes=16))  # longest postponement reached
    assert jobs.claim("test-worker").pk == ocr.pk


def test_at415_throttling_needs_sustained_load_is_logged_visible_and_recovers(family, clients):
    from apps.core import throttle
    from apps.core.models import PerfEvent

    assert not throttle.evaluate(_sample(cpu_percent=99.0))["active"]  # one spike: no throttling
    assert not throttle.evaluate(_sample())["active"]
    throttle.evaluate(_sample(mem_available_percent=4.0))
    st = throttle.evaluate(_sample(mem_available_percent=4.0, swap_used_percent=80.0))
    assert st["active"] and "memory available 4%" in st["reason"]
    assert PerfEvent.objects.filter(kind="throttle_start").exists()
    perf = clients["dad"].get("/api/admin/performance").json()
    assert perf["throttle"]["active"] and any("throttled" in w for w in perf["warnings"])
    throttle.evaluate(_sample())
    throttle.evaluate(_sample())
    assert throttle.evaluate(_sample())["active"] is False
    assert PerfEvent.objects.filter(kind="throttle_end").exists()
    config.set_value("performance.throttle_enabled", False)
    for _ in range(3):
        assert not throttle.evaluate(_sample(cpu_percent=100.0))["active"]


# ------------------------------------------------------------------ AT-416 / AT-417 Admin Performance and report
def test_at416_admin_performance_is_restricted_useful_and_free_of_private_data(family, clients):
    from apps.notify.management.commands.scheduler import tick

    dad = family["dad"]
    _bulk_docs(personal_root(dad), dad, 2, prefix="Passport 7HX2Q9")
    config.set_value("smtp.password", "s3cret-sample-value")
    clients["dad"].get(f"/api/documents?folder={personal_root(dad).pk}&q=7HX2Q9")
    tick()
    r = clients["dad"].get("/api/admin/performance?hours=1")
    assert r.status_code == 200
    data = r.json()
    names = [x["name"] for x in data["requests"]["by_route"]]
    assert "GET api/documents" in names and all("7HX2Q9" not in n for n in names)
    assert data["system"].get("jobs_queued") is not None and "settings_snapshot" in data["cache"]
    text = json.dumps(data)
    for secret in ("s3cret-sample-value", "7HX2Q9", "Sample-Passw0rd!", str(personal_root(dad).pk)):
        assert secret not in text
    assert clients["son1"].get("/api/admin/performance").status_code == 403


def test_at417_diagnostic_report_main_admin_only_without_secrets(family, clients):
    from apps.core.models import AuditEvent

    config.set_value("smtp.password", "s3cret-sample-value")
    r = clients["dad"].get("/api/admin/performance/report")
    assert r.status_code == 200 and "attachment" in r["Content-Disposition"]
    body = r.content.decode()
    report = json.loads(body)
    assert report["environment"]["postgresql"] and "processing.heavy_concurrency" in report["environment"]["settings"]
    assert "s3cret-sample-value" not in body and "smtp.password" not in body
    assert AuditEvent.objects.filter(action="performance.report").exists()
    family["mom"].is_admin = True
    family["mom"].save()
    assert clients["mom"].get("/api/admin/performance").status_code == 200  # Administrator role: dashboard
    assert clients["mom"].get("/api/admin/performance/report").status_code == 403  # report: main administrator only


# ------------------------------------------------------------------ AT-418 / AT-419 runtime and static files
def test_at418_runtime_configuration_threads_with_safe_defaults(monkeypatch):
    import runpy

    unit = (ROOT / "deployment/systemd/personaldocs-web.service").read_text()
    assert "--config /opt/personaldocs/current/deployment/gunicorn.conf.py" in unit
    monkeypatch.delenv("PD_WEB_THREADS", raising=False)
    monkeypatch.delenv("PD_WEB_WORKERS", raising=False)
    conf = runpy.run_path(str(ROOT / "deployment/gunicorn.conf.py"))
    assert conf["workers"] == 2 and conf["threads"] == 4 and conf["worker_class"] == "gthread"
    monkeypatch.setenv("PD_WEB_THREADS", "1")
    assert runpy.run_path(str(ROOT / "deployment/gunicorn.conf.py"))["worker_class"] == "sync"
    assert "PD_WEB_THREADS=4" in (ROOT / "deployment/personaldocs.env.example").read_text()
    script = (ROOT / "scripts/personaldocs").read_text()
    assert "env_set PD_WEB_THREADS 4" in script


def test_at419_hashed_assets_immutable_index_revalidated_and_precompressed(family, clients):
    from django.conf import settings

    test = settings.WHITENOISE_IMMUTABLE_FILE_TEST
    assert test("", "/static/app/main-BXZMeMm8.js") and test("", "/static/app/pdfjs-6.4.299/cmaps/x.bcmap")
    assert not test("", "/index.html") and not test("", "/sw.js") and not test("", "/static/app/icon.svg")
    assert "precompress()" in (ROOT / "frontend/vite.config.ts").read_text()
    dist = Path(settings.FRONTEND_DIST)
    if (dist / "index.html").exists():
        r = clients["dad"].get("/folders")
        assert r["Cache-Control"] == "no-cache"


# ------------------------------------------------------------------ AT-420 freshness
def test_at420_permission_and_settings_changes_apply_immediately(family, clients):
    from apps.core import perfcache
    from apps.library import permissions as P
    from apps.library.models import AccessRule

    dad, son = family["dad"], family["son1"]
    docs = _bulk_docs(personal_root(dad), dad, 1, prefix="Shared now")
    rule = AccessRule.objects.create(document=docs[0], user=son, caps=P.VIEW)
    assert clients["son1"].get(f"/api/documents/{docs[0].pk}").status_code == 200
    rule.delete()  # access removed: the very next request is refused
    assert clients["son1"].get(f"/api/documents/{docs[0].pk}").status_code in (403, 404)
    config.set_value("general.app_name", "Fresh name")
    assert clients["dad"].get("/api/session").json()["app_name"] == "Fresh name"
    # health summaries (backup, security) are computed fresh for every request, never cached
    clients["dad"].get("/api/dashboard")
    clients["dad"].get("/api/dashboard")
    assert "health" not in perfcache.stats()


# ------------------------------------------------------------------ AT-421 search architecture unchanged
def test_at421_search_architecture_and_results_unchanged(family, clients):
    dad = family["dad"]
    _bulk_docs(personal_root(dad), dad, 5, prefix="Insurance policy")
    _bulk_docs(personal_root(dad), dad, 5, prefix="Bank letter")
    r = clients["dad"].get("/api/documents?q=insurance").json()
    assert r["total"] == 5 and all("Insurance" in d["title"] for d in r["documents"])
    assert all("snippet" in d for d in r["documents"])
    src = (ROOT / "backend/apps/library/search.py").read_text()
    assert "SearchQuery(q, config=CONFIG, search_type=\"websearch\")" in src and "search_vector" in src
    reqs = (ROOT / "backend/requirements.txt").read_text().lower()
    assert "elasticsearch" not in reqs and "opensearch" not in reqs


# ------------------------------------------------------------------ AT-422 post-upgrade maintenance
def test_at422_post_upgrade_maintenance_is_safe_and_repeatable(family):
    from apps.library.models import Document

    _bulk_docs(personal_root(family["dad"]), family["dad"], 3)
    before = Document.objects.count()
    for _ in range(2):
        out = io.StringIO()
        try:
            call_command("perf_maintenance", stdout=out)
        except SystemExit as exc:  # only when the frontend is not built in this environment
            assert "not built" in out.getvalue() or "compressed" in out.getvalue(), out.getvalue()
        assert "statistics refreshed" in out.getvalue() and "all indexes valid" in out.getvalue()
    assert Document.objects.count() == before
    script = (ROOT / "scripts/personaldocs").read_text()
    assert re.search(r"manage perf_maintenance", script)
