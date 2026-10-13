"""Change Set V - corrective: NAS inside Backup Destinations, durable FIFO backup queue, permission-aware Help and
tooltip registry, English sign-in map with filters, WhatsApp pairing lifecycle (backend parts of AT-356 .. AT-375).
The change prompt numbered these AT-331..AT-350; here they are AT-356..AT-375 (prompt + 25), because AT-331..AT-355
already exist. Synthetic data only. The NAS mount helper is faked (no real SMB/NFS server), WhatsApp uses
tests/fake_whatsapp_bridge.py, and no request reaches a real map provider. A real phone pairing (prompt AT-344 /
AT-369 here) cannot run in CI and is reported Blocked / Not Executed in docs/TEST_REPORT.md."""
import importlib
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.core import config, jobs
from apps.core.models import AppSetting, AuditEvent, Job
from apps.notify.models import OutboxMessage, WhatsAppLink
from apps.ops import bk_engine as E
from apps.ops import nas_migration
from apps.ops.models import BackupDestination, BackupPolicy
from apps.security import mapprov
from apps.security.models import LoginEvent

from conftest import client_for
from fake_whatsapp_bridge import FakeBridge

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1]
SMB_PW = "synthetic-smb-password-DO-NOT-LEAK-91"
TOKEN = "synthetic-bridge-token-0123456789abcdef"


def _old_nas(kind="smb", password=True, **kw):
    """The values an installation had under the removed Settings → Storage & NAS page."""
    vals = {"type": kind, "server": "nas.example.lan", "share": "backups" if kind == "smb" else "/volume1/backups",
            "subfolder": "personaldocs", "username": "backup-user" if kind == "smb" else "", **kw}
    for k, v in vals.items():
        config.set_value(f"nas.{k}", v)
    if password:
        config.set_value("nas.password", SMB_PW)


def _migrate():
    mig = importlib.import_module("apps.ops.migrations.0003_nas_into_destinations")
    mig.forwards(django_apps, None)


def _no_secret_anywhere(*blobs):
    for b in blobs:
        assert SMB_PW not in (b if isinstance(b, str) else json.dumps(b, default=str))


# ------------------------------------------------------------------ AT-356 automatic NAS migration

def test_at356_existing_nas_migrates_into_one_destination_idempotently(family, clients, tmp_path):
    keep = tmp_path / "old-share"
    keep.mkdir()
    (keep / "backup-20261001-023000-personaldocs").mkdir()  # a file on the share must survive untouched
    pol = BackupPolicy.objects.create(name="Default")
    old = BackupDestination.objects.create(name="Existing backup share", kind="nas", config={"path": "/mnt/pdnas/personaldocs"})
    pol.destinations.add(old)
    _old_nas()
    _migrate()
    _migrate()  # idempotent: a rerun neither duplicates nor changes the result
    nas = BackupDestination.objects.filter(kind="nas")
    assert nas.count() == 1
    d = nas.get()
    assert d.pk == old.pk  # the destination the earlier upgrade made from the backup folder is adopted
    assert d.config["managed"] is True and d.config["connection"] == "smb" and d.config["path"] == "/mnt/pdnas/personaldocs"
    assert list(pol.destinations.values_list("pk", flat=True)) == [d.pk]  # policy link retained
    assert d.health != "needs_attention"
    # the old values (and the encrypted password) stay where the mount helper reads them
    assert config.get("nas.server") == "nas.example.lan" and config.is_set("nas.password")
    assert (keep / "backup-20261001-023000-personaldocs").is_dir()
    a = AuditEvent.objects.filter(action="backup.nas_migrated")
    assert a.exists()
    _no_secret_anywhere(list(a.values("context", "outcome")))
    # the standalone page is gone: no Storage tab, the old address redirects to the destinations
    settings_tsx = (ROOT / "frontend/src/pages/Settings.tsx").read_text()
    assert 'Navigate to="/settings/backup?view=destinations"' in settings_tsx and '"storage", "Storage & NAS"' not in settings_tsx
    assert "NasCard" not in (ROOT / "frontend/src/pages/settings/Admin.tsx").read_text()


def test_at356_new_destination_created_when_none_existed(family):
    _old_nas(kind="nfs", password=False)
    res = nas_migration.run(BackupDestination, AppSetting)
    assert res["result"] == "migrated" and res["created"]
    d = BackupDestination.objects.get(kind="nas")
    assert d.name == "NAS backup share" and d.config["connection"] == "nfs"
    assert nas_migration.run(BackupDestination, AppSetting)["created"] is False


def test_at356_nothing_to_migrate_without_a_managed_nas(family):
    assert nas_migration.run(BackupDestination, AppSetting) == {"result": "nothing"}
    assert not BackupDestination.objects.filter(kind="nas").exists()


# ------------------------------------------------------------------ AT-357 failed migration safety

def test_at357_invalid_old_config_becomes_needs_attention_and_retry_fixes_it(family, clients):
    _old_nas(password=False)  # SMB without a stored password cannot be validated
    _migrate()
    d = BackupDestination.objects.get(kind="nas")
    assert d.health == "needs_attention" and nas_migration.MIGRATION_NOTE in d.health_detail
    assert config.get("nas.server") == "nas.example.lan"  # nothing deleted
    data = clients["dad"].get("/api/backup/overview").json()
    row = next(x for x in data["destinations"] if x["id"] == d.pk)
    assert row["needs_attention"] is True and row["health"] != "healthy"
    # Edit Configuration: entering the password clears Needs Attention; Retry Migration then succeeds
    r = clients["dad"].put(f"/api/backup/destinations/{d.pk}", {"kind": "nas", "config": {"connection": "smb"},
                                                                 "nas": {"server": "nas.example.lan", "share": "backups", "subfolder": "personaldocs",
                                                                         "username": "backup-user"},
                                                                 "secrets": {"password": SMB_PW}}, format="json")
    assert r.status_code == 200, r.content
    _no_secret_anywhere(r.json())
    r = clients["dad"].post(f"/api/backup/destinations/{d.pk}/retry-migration", {}, format="json")
    assert r.status_code == 200 and r.json()["result"] == "migrated"
    assert r.json()["destination"]["health"] != "needs_attention"
    assert BackupDestination.objects.filter(kind="nas").count() == 1
    assert clients["son1"].post(f"/api/backup/destinations/{d.pk}/retry-migration", {}, format="json").status_code == 403


# ------------------------------------------------------------------ AT-358 NAS configuration and secrets

def test_at358_nas_configured_in_destination_and_secret_never_returned(family, clients):
    body = {"name": "Home NAS", "kind": "nas", "config": {"connection": "smb"},
            "nas": {"server": "nas.example.lan", "share": "backups", "subfolder": "pd", "username": "backup-user", "domain": "WORKGROUP"}}
    r = clients["dad"].post("/api/backup/destinations", body, format="json")
    assert r.status_code == 400 and "password" in r.json()["error"].lower()  # SMB needs a password the first time
    r = clients["dad"].post("/api/backup/destinations", {**body, "secrets": {"password": SMB_PW}}, format="json")
    assert r.status_code == 201, r.content
    d = r.json()
    assert d["nas"]["managed"] and d["nas"]["server"] == "nas.example.lan" and d["nas"]["password_set"] is True
    assert d["config"]["path"] == "/mnt/pdnas/pd"
    # unchanged secret is kept when the password field stays empty; a new one replaces it
    r = clients["dad"].put(f"/api/backup/destinations/{d['id']}", {"kind": "nas", "config": {"connection": "smb"},
                                                                    "nas": {**body["nas"], "server": "nas2.example.lan"}}, format="json")
    assert r.status_code == 200 and config.get("nas.password") == SMB_PW and config.get("nas.server") == "nas2.example.lan"
    clients["dad"].put(f"/api/backup/destinations/{d['id']}", {"kind": "nas", "config": {"connection": "smb"}, "nas": body["nas"],
                                                                "secrets": {"password": SMB_PW + "-new"}}, format="json")
    assert config.get("nas.password") == SMB_PW + "-new"
    # nowhere in the API, the overview, or the audit log
    overview = clients["dad"].get("/api/backup/overview").content.decode()
    assert SMB_PW not in overview
    _no_secret_anywhere(list(AuditEvent.objects.values("context", "action", "target_id")))
    # only one Personal-DM-managed share; further shares are "Already mounted"
    r = clients["dad"].post("/api/backup/destinations", {**body, "name": "Second NAS", "secrets": {"password": "x"}}, format="json")
    assert r.status_code == 400 and "Only one NAS share" in r.json()["error"]
    # injection in NAS fields is refused by the same validation as the mount helper
    r = clients["dad"].put(f"/api/backup/destinations/{d['id']}", {"kind": "nas", "config": {"connection": "smb"},
                                                                    "nas": {**body["nas"], "share": "backups,uid=0"}}, format="json")
    assert r.status_code == 400


def test_at358_test_connection_reports_categorised_mount_errors(family, clients, tmp_path, settings):
    from apps.ops import nas, nas_helper

    settings.DATA_DIR = tmp_path / "data"
    d = BackupDestination.objects.create(name="Home NAS", kind="nas", config={"managed": True, "connection": "nfs", "path": "/mnt/pdnas/pd"})
    _old_nas(kind="nfs", password=False)
    r = clients["dad"].post(f"/api/backup/destinations/{d.pk}/test", {}, format="json")
    assert r.json()["pending"] is True  # the root helper is asked to mount
    # what the helper reports after a failed mount
    for detail, cat in [("mount error(13): Permission denied", "authentication"), ("mount.nfs: Connection timed out", "reachability"),
                        ("Could not resolve address for nas.example.lan", "dns"), ("mount error(2): No such file or directory", "share"),
                        ("mount: Operation not permitted", "mount_not_allowed")]:
        assert nas_helper.classify(detail) == cat, detail
    st = {"state": "error", "message": "The NAS refused access.", "detail": "mount error(13): Permission denied", "category": "authentication",
          "at": timezone.now().isoformat()}
    (Path(settings.DATA_DIR) / "nas").mkdir(parents=True, exist_ok=True)
    (Path(settings.DATA_DIR) / "nas/status.json").write_text(json.dumps(st))
    r = clients["dad"].post(f"/api/backup/destinations/{d.pk}/test", {"poll": True}, format="json").json()
    assert r["ok"] is False and r["category"] == "authentication" and r["category_label"].startswith("Authentication")
    d.refresh_from_db()
    assert d.health == "auth_required"
    assert nas.read_status()["category"] == "authentication"


# ------------------------------------------------------------------ AT-359 health and capacity

@pytest.mark.parametrize("free,state", [(50, "ok"), (20, "warning"), (15, "warning"), (9, "critical")])
def test_at359_capacity_thresholds(family, free, state):
    d = BackupDestination.objects.create(name=f"Disk {free}", kind="local", config={"path": "/srv/b"}, free_bytes=free, total_bytes=100)
    cap = E.capacity(d)
    assert cap["state"] == state and cap["warn_pct"] == 20 and cap["crit_pct"] == 10


def test_at359_per_destination_override_and_alert_once_a_day(family, clients, tmp_path):
    p = tmp_path / "dest"
    p.mkdir()
    r = clients["dad"].post("/api/backup/destinations", {"name": "USB", "kind": "local", "config": {"path": str(p), "warn_pct": 40, "crit_pct": 25}}, format="json")
    assert r.status_code == 201, r.content
    d = BackupDestination.objects.get(pk=r.json()["id"])
    assert E.capacity(BackupDestination(config=d.config, free_bytes=30, total_bytes=100))["state"] == "warning"
    bad = clients["dad"].put(f"/api/backup/destinations/{d.pk}", {"kind": "local", "config": {"warn_pct": 10, "crit_pct": 20}}, format="json")
    assert bad.status_code == 400 and "lower" in bad.json()["error"]
    before = OutboxMessage.objects.filter(event="backup.destination").count()
    E._set_health(d, "healthy", "ok", 20, 100)
    E._set_health(d, "healthy", "ok", 20, 100)
    sent = OutboxMessage.objects.filter(event="backup.destination").count() - before
    assert sent >= 1
    E._set_health(d, "healthy", "ok", 20, 100)
    assert OutboxMessage.objects.filter(event="backup.destination").count() - before == sent  # no repeat the same day


# ------------------------------------------------------------------ AT-360 Backup Now / AT-361 FIFO queue

def _dest(tmp_path, name="USB disk"):
    p = tmp_path / name.replace(" ", "-")
    p.mkdir()
    return BackupDestination.objects.create(name=name, kind="local", config={"path": str(p)})


def test_at360_backup_now_needs_confirmation_and_targets_one_destination(family, clients, tmp_path):
    d1, d2 = _dest(tmp_path, "Disk one"), _dest(tmp_path, "Disk two")
    pol = BackupPolicy.objects.create(name="Default")
    pol.destinations.set([d1, d2])
    url = f"/api/backup/destinations/{d2.pk}/backup-now"
    assert clients["son1"].post(url, {"confirm": True}, format="json").status_code == 403
    r = clients["dad"].post(url, {}, format="json")
    assert r.status_code == 400 and r.json().get("code") == "confirm"
    r = clients["dad"].post(url, {"confirm": True}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["position"] == 0
    assert clients["dad"].post(url, {"confirm": True}, format="json").status_code == 409  # duplicate prevented
    q = clients["dad"].get("/api/backup/jobs").json()
    assert q["fifo"] is True and q["cancellable"] is False
    assert q["jobs"][0]["state"] == "Queued" and q["jobs"][0]["destinations"] == ["Disk two"] and q["jobs"][0]["cancellable"] is False
    jobs.run_pending(max_jobs=5)
    q = clients["dad"].get("/api/backup/jobs").json()
    assert q["jobs"][0]["state"] == "Completed", q["jobs"][0]
    from apps.ops.models import RecoveryPoint

    point = RecoveryPoint.objects.get()
    assert point.kind == "full" and point.policy_id is None
    assert list(point.copies.values_list("destination__name", flat=True)) == ["Disk two"]  # this destination only
    assert point.status == RecoveryPoint.VERIFIED


def test_at361_one_job_at_a_time_strictly_fifo(family, clients, tmp_path):
    d = _dest(tmp_path)
    pol = BackupPolicy.objects.create(name="Default")
    pol.destinations.set([d])
    scheduled = jobs.enqueue("backup_point", {"policy": pol.id, "kind": "full", "trigger": "scheduled"}, max_attempts=1)
    r = clients["dad"].post(f"/api/backup/destinations/{d.pk}/backup-now", {"confirm": True}, format="json")
    assert r.json()["position"] == 1  # the manual backup waits behind the scheduled one
    manual = Job.objects.get(pk=r.json()["job"])
    # a lower priority value must not let it jump the queue either
    Job.objects.filter(pk=manual.pk).update(priority=-100)
    first = jobs.claim("w1", heavy_limit=4)
    assert first.pk == scheduled.pk
    assert jobs.claim("w2", heavy_limit=4) is None  # nothing else serial starts while one runs
    other = jobs.enqueue("thumbnail_noop_for_test", {}, max_attempts=1)  # unrelated, non-backup work is not blocked
    got = jobs.claim("w3", heavy_limit=4)
    assert got is not None and got.pk == other.pk
    Job.objects.filter(pk=first.pk).update(status=Job.DONE, finished_at=timezone.now())
    assert jobs.claim("w4", heavy_limit=4).pk == manual.pk


def test_at361_waiting_retry_does_not_block_the_queue(family):
    later = jobs.enqueue("backup_verify", {"point": "x"}, max_attempts=1)
    Job.objects.filter(pk=later.pk).update(run_after=timezone.now() + timedelta(hours=1))
    now_job = jobs.enqueue("backup_verify", {"point": "y"}, max_attempts=1)
    assert jobs.claim("w", heavy_limit=4).pk == now_job.pk


# ------------------------------------------------------------------ AT-362/363 tooltip registry

def _registry():
    text = (ROOT / "frontend/src/components/helpRegistry.ts").read_text()
    return dict(re.findall(r'"([a-z]+\.[a-z_.]+)": \{ text: .*?link: "([^"]+)"', text))


def test_at363_every_tooltip_id_used_exists_and_every_link_resolves():
    reg = _registry()
    used = set()
    for f in (ROOT / "frontend/src").rglob("*.tsx"):
        used |= set(re.findall(r'<HelpTip id="([^"]+)"', f.read_text()))
    assert used, "no registry tooltips in use"
    missing = used - set(reg)
    assert not missing, f"HelpTip ids missing from helpRegistry.ts: {missing}"
    for key, link in reg.items():
        m = re.fullmatch(r"/help/([a-z0-9-]+)#([a-z0-9-]+)", link)
        assert m, (key, link)
        guide = (ROOT / "docs/guides" / f"{m.group(1)}.md").read_text()
        assert "{#" + m.group(2) + "}" in guide or f'id="{m.group(2)}"' in guide, f"{key}: no heading #{m.group(2)} in {m.group(1)}.md"


def test_at362_tooltip_is_portalled_and_flips():
    ui = (ROOT / "frontend/src/components/ui.tsx").read_text()
    css = (ROOT / "frontend/src/styles.css").read_text()
    assert "createPortal" in ui and "document.body" in ui
    assert re.search(r"\.tip-pop\s*\{[^}]*position:\s*fixed", css)
    assert 'role="tooltip"' in ui and "aria-describedby" in ui and "Escape" in ui


# ------------------------------------------------------------------ AT-364/365 Help authorization

ADMIN_ONLY = ("backup-restore", "disaster-recovery", "installation", "upgrades", "security-access", "antivirus", "settings")


def test_at364_normal_user_sees_only_user_guides(family, clients):
    c = clients["son1"]
    slugs = {g["slug"] for g in c.get("/api/help").json()["guides"]}
    assert "getting-started" in slugs and "whatsapp-personal" in slugs and "security-map" in slugs
    assert not slugs & set(ADMIN_ONLY)
    for slug in ADMIN_ONLY:
        assert c.get(f"/api/help/{slug}").status_code == 404  # same answer as a guide that does not exist
    for term in ("NAS", "recovery key", "ClamAV", "pg_dump", "whatsapp-bridge update"):
        res = c.get("/api/help", {"q": term}).json()["guides"]
        assert not {g["slug"] for g in res} & set(ADMIN_ONLY), term
        for g in res:
            assert "personaldocs whatsapp-bridge update" not in (g.get("excerpt") or "")
    md = c.get("/api/help/whatsapp-personal").json()["markdown"]
    assert "whatsapp-bridge update" not in md and "Run Diagnostics" not in md  # admin sections removed
    assert "Link your WhatsApp" in md
    md = c.get("/api/help/security-map").json()["markdown"]
    assert "Map provider and tiles" not in md and "Filters" in md
    # links to guides this person may not open become plain text; no server-console procedure is shown
    leaks = []
    for g in c.get("/api/help").json()["guides"]:
        md = c.get(f"/api/help/{g['slug']}").json()["markdown"]
        leaks += [f"{g['slug']}: {line.strip()[:90]}" for line in md.splitlines() if "sudo " in line]
        for slug in ADMIN_ONLY:
            assert f"]({slug}.md" not in md and f"](../guides/{slug}.md" not in md and f"](/help/{slug}" not in md, (g["slug"], slug)
    assert not leaks, "administrator console commands visible to a normal user:\n" + "\n".join(leaks)


def test_at365_scoped_admin_main_admin_and_live_permission_changes(family, clients):
    from apps.accounts.models import Delegation, FamilyGroup

    mom = family["mom"]
    mom.is_admin = True
    mom.save(update_fields=["is_admin"])
    c = client_for(mom)
    slugs = {g["slug"] for g in c.get("/api/help").json()["guides"]}
    assert {"antivirus", "security-center"} <= slugs  # Administrator: security and operations guides
    assert "backup-restore" not in slugs and c.get("/api/help/disaster-recovery").status_code == 404
    main = {g["slug"] for g in clients["dad"].get("/api/help").json()["guides"]}
    assert set(ADMIN_ONLY) <= main  # main administrator sees everything
    assert "whatsapp-bridge update" in clients["dad"].get("/api/help/whatsapp-personal").json()["markdown"]
    # permission change applies at once (no cached visibility)
    mom.is_admin = False
    mom.save(update_fields=["is_admin"])
    assert c.get("/api/help/antivirus").status_code == 404
    # delegates of a family group see the family-administration guide
    son = family["son1"]
    assert client_for(son).get("/api/help/extended-family").status_code == 404
    Delegation.objects.create(delegate=son, group=FamilyGroup.objects.first(), scopes=["membership"], granted_by=family["dad"])
    assert client_for(son).get("/api/help/extended-family").status_code == 200


def test_at365_every_guide_declares_a_valid_audience():
    from apps.core.help_access import AUDIENCES

    for p in (ROOT / "docs/guides").glob("*.md"):
        text = re.sub(r"`[^`\n]*`", "", p.read_text())  # markers quoted as code are documentation, not markers
        m = re.search(r"<!-- audience: ([a-z_]+) -->", text)
        if m:
            assert m.group(1) in AUDIENCES, p.name
        opens = len(re.findall(r"<!-- audience-section: [a-z_]+ -->", text))
        assert opens == text.count("<!-- /audience-section -->"), f"{p.name}: unbalanced audience sections"


# ------------------------------------------------------------------ AT-366 English sign-in map

def test_at366_default_provider_has_english_vector_labels():
    r = mapprov.resolved()
    assert r["provider"] == "openfreemap" and r["kind"] == "vector" and r["english"] is True
    cfg = mapprov.public_config()
    assert cfg["style_url"].startswith("https://tiles.openfreemap.org/") and cfg["english_labels"] is True
    assert cfg["fallback_tile_url"] == mapprov.OSM_URL and "OpenStreetMap" in cfg["fallback_attribution"]
    assert "https://tiles.openfreemap.org" in mapprov.tile_origin()
    # the label expression prefers the English name, then the Latin transliteration, then the local name
    tsx = (ROOT / "frontend/src/components/SigninMap.tsx").read_text()
    assert '["get", "name:en"], ["get", "name_en"], ["get", "name:latin"], ["get", "name"]' in tsx
    assert "language" not in (ROOT / "frontend/src/pages/settings/Signins.tsx").read_text().lower()  # no language selector


def test_at366_explicit_osm_choice_is_upgraded_but_custom_kept(family):
    mig = importlib.import_module("apps.security.migrations.0005_map_english_labels")
    config.set_value("security.map_provider", "osm")
    mig.forwards(django_apps, None)
    assert config.get("security.map_provider") == "openfreemap"
    config.set_value("security.map_provider", "custom")
    mig.forwards(django_apps, None)
    assert config.get("security.map_provider") == "custom"


def test_at366_csp_allows_openfreemap_and_raster_fallback(family, clients):
    from apps.core.middleware import SecurityHeadersMiddleware

    SecurityHeadersMiddleware._tiles["at"] = 0.0
    csp = clients["dad"].get("/api/session")["Content-Security-Policy"]
    assert "connect-src 'self' https://tiles.openfreemap.org https://tile.openstreetmap.org" in csp
    assert "script-src 'self';" in csp  # the CSP build of the map library needs no blob: workers or eval


# ------------------------------------------------------------------ AT-367/368 map details, filters, authorization

def _events(family):
    now = timezone.now()
    mk = lambda user, days, **kw: LoginEvent.objects.create(user=family[user], result="success", at=now - timedelta(days=days), **kw)
    return [mk("dad", 1, ip="198.51.100.7", lat=24.7, lon=46.7, location="Riyadh, Saudi Arabia", network="public", risk="normal"),
            mk("dad", 3, ip="198.51.100.7", lat=24.7, lon=46.7, location="Riyadh, Saudi Arabia", network="public", risk="warning"),
            mk("dad", 20, ip="203.0.113.9", lat=51.5, lon=-0.1, location="London, United Kingdom", network="public", risk="high"),
            mk("dad", 200, ip="192.0.2.44", network="unknown", risk="low"),
            mk("son1", 2, ip="203.0.113.50", lat=40.7, lon=-74.0, location="New York, United States", network="public", risk="normal")]


def test_at368_default_last_7_days_and_filters(family, clients):
    _events(family)
    c = clients["dad"]
    data = c.get("/api/security/map").json()
    assert data["filters"]["period"] == "7" and len(data["events"]) == 2
    e = data["events"][0]
    for k in ("user", "ip", "location", "network", "device", "risk", "at", "browser", "os", "device_type"):
        assert k in e, k
    assert len(c.get("/api/security/map", {"period": "30"}).json()["events"]) == 3
    assert len(c.get("/api/security/map", {"period": "365"}).json()["events"]) == 4  # one-year retention window
    assert [x["risk"] for x in c.get("/api/security/map", {"period": "30", "risk": "high"}).json()["events"]] == ["high"]
    d0 = (timezone.localdate() - timedelta(days=25)).isoformat()
    d1 = (timezone.localdate() - timedelta(days=10)).isoformat()
    assert len(c.get("/api/security/map", {"period": "custom", "from": d0, "to": d1}).json()["events"]) == 1
    assert c.get("/api/security/map", {"period": "custom", "from": d1, "to": d0}).status_code == 400
    assert c.get("/api/security/map", {"period": "365", "trust": "trusted"}).json()["events"] == []
    # records without coordinates are still listed (the list shows "Location unavailable")
    rows = c.get("/api/security/map", {"period": "365"}).json()["events"]
    assert any(r["lat"] is None for r in rows)
    everyone = c.get("/api/security/map", {"user": "all"}).json()["events"]
    assert {r["user"] for r in everyone} == {"Alex Sample", "Sam Sample"}


def test_at367_query_tampering_cannot_reveal_other_people(family, clients):
    _events(family)
    c = clients["son1"]
    assert c.get("/api/security/map", {"user": str(family["dad"].pk)}).status_code == 403
    rows = c.get("/api/security/map", {"user": "all", "period": "365"}).json()["events"]
    assert {r["user"] for r in rows} == {"Sam Sample"}
    assert c.get("/api/security/map").json()["zones_for_filter"] == []


# ------------------------------------------------------------------ AT-370..373 WhatsApp lifecycle (fake bridge)

@pytest.fixture
def bridge(settings):
    Path(settings.CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    (Path(settings.CONFIG_DIR) / "whatsapp-bridge.token").write_text(TOKEN)
    with FakeBridge(TOKEN) as b:
        config.set_value("whatsapp.bridge_url", f"http://127.0.0.1:{b.port}")
        config.set_value("whatsapp.enabled", True)
        yield b


def test_at370_qr_lifecycle_no_churn_and_replacement_rules(family, clients, bridge):
    c = clients["son1"]
    r = c.post("/api/notifications/whatsapp", {"action": "link"}, format="json").json()
    assert r["state"] == "pending" and r["stage"] == "qr_ready" and r["link_expires_in_s"] >= 280
    assert "<svg" in r["qr_svg"] and "FAKE-QR" not in json.dumps(r)  # only the rendered picture
    assert r["can_new_qr"] is False
    # pressing Link again keeps the running attempt (no churn); asking for a new code inside the window is refused
    c.post("/api/notifications/whatsapp", {"action": "link"}, format="json")
    assert bridge.links == 1
    r = c.post("/api/notifications/whatsapp", {"action": "link", "new_qr": True}, format="json")
    assert r.status_code == 400 and "still valid" in r.json()["error"]
    sid = WhatsAppLink.objects.get(user=family["son1"]).session
    # while connecting no QR is shown
    bridge.sessions[sid].update(stage="connecting")
    r = c.get("/api/notifications/whatsapp").json()
    assert r["label"] == "Connecting" and "qr_svg" not in r
    # a definitive failure allows a new code at once, with the step and reason
    bridge.sessions[sid].update(state="pairing_failed", stage=None, error_code="timeout", failure_stage="authenticating")
    r = c.get("/api/notifications/whatsapp").json()
    assert r["can_new_qr"] is True and r["failure_stage"] == "authenticating" and "in time" in r["error"]
    assert c.post("/api/notifications/whatsapp", {"action": "link", "new_qr": True}, format="json").status_code == 200
    assert bridge.links == 2
    # nothing QR-like reaches the audit log
    _qr_free(AuditEvent.objects.values("context", "action"))


def _qr_free(rows):
    blob = json.dumps(list(rows), default=str)
    assert "FAKE-QR" not in blob and "<svg" not in blob


def test_at370_link_attempts_are_rate_limited(family, clients, bridge):
    from apps.notify import whatsapp

    u = family["son2"]
    for i in range(whatsapp.LINKS_PER_HOUR):
        whatsapp.start_link(u, force=True) if i else whatsapp.start_link(u)
        bridge.sessions[WhatsAppLink.objects.get(user=u).session].update(state="link_expired", stage=None)
        whatsapp.status(u)
    with pytest.raises(whatsapp.WhatsAppError, match="Too many"):
        whatsapp.start_link(u, force=True)


def test_at371_sessions_are_isolated_per_person(family, clients, bridge):
    for name in ("son1", "daughter"):
        clients[name].post("/api/notifications/whatsapp", {"action": "link"}, format="json")
    s1 = WhatsAppLink.objects.get(user=family["son1"]).session
    s2 = WhatsAppLink.objects.get(user=family["daughter"]).session
    assert s1 != s2
    bridge.connect(s1, hint="1111")
    assert clients["son1"].get("/api/notifications/whatsapp").json()["key"] == "verified"
    assert clients["daughter"].get("/api/notifications/whatsapp").json()["state"] == "pending"
    clients["daughter"].delete("/api/notifications/whatsapp")
    assert s1 in bridge.sessions and s2 not in bridge.sessions  # unlinking one person never touches another


def test_at372_verification_relink_and_stale_queue(family, clients, bridge):
    c = clients["son1"]
    c.post("/api/notifications/whatsapp", {"action": "link"}, format="json")
    link = WhatsAppLink.objects.get(user=family["son1"])
    bridge.connect(link.session, verification="pending")
    r = c.get("/api/notifications/whatsapp").json()
    assert r["key"] == "verify_pending" and r["label"] == "Linked — Verification Pending"
    bridge.sessions[link.session]["verification"] = "verified"
    r = c.get("/api/notifications/whatsapp").json()
    assert r["key"] == "verified" and r["label"] == "Linked & Verified" and r["verified_at"]
    # WhatsApp revokes the linked device: Relink Required, and the person is told through another channel
    bridge.sessions[link.session].update(state="reconnect_required", error_code=401)
    r = c.get("/api/notifications/whatsapp").json()
    assert r["label"] == "Relink Required" and r["can_new_qr"] and "rejected" in r["error"]
    told = OutboxMessage.objects.filter(user=family["son1"], event="whatsapp.relink_required")
    assert told.exists() and not told.filter(channel="whatsapp").exists()
    c.get("/api/notifications/whatsapp")
    assert told.count() == told.count()  # not repeated on every poll


def test_at372_stale_messages_expire_or_are_superseded(family):
    from apps.notify import expiry

    u = family["son1"]
    old = timezone.now() - timedelta(hours=30)
    mk = lambda key, event, severity, at=old, **kw: OutboxMessage.objects.create(key=key, user=u, channel="whatsapp", kind="event", subject="s",
                                                                                 body="b", event=event, severity=severity, **kw)
    a = mk("a", "backup.completed", "success")
    b = mk("b", "backup.completed", "success")
    sec = mk("c", "security.signin_new_device", "warning")
    crit = mk("d", "backup.failed", "critical")
    info = mk("e", "documents.shared", "info")
    OutboxMessage.objects.filter(pk__in=[a.pk, b.pk, sec.pk, crit.pk, info.pk]).update(created_at=old)
    OutboxMessage.objects.filter(pk=b.pk).update(created_at=old + timedelta(minutes=5))
    for m in (a, b, sec, crit, info):
        m.refresh_from_db()
    assert expiry.staleness(a) == OutboxMessage.SUPERSEDED  # a newer backup status replaced it
    assert expiry.staleness(sec) is None and expiry.staleness(crit) is None  # security / critical are never dropped
    assert expiry.staleness(info) == OutboxMessage.EXPIRED
    assert expiry.deliver_one(info) in ("skipped", "expired")
    info.refresh_from_db()
    assert info.status == OutboxMessage.EXPIRED and info.last_error


def test_at373_diagnostics_are_main_admin_only_and_redacted(family, clients, bridge):
    clients["son1"].post("/api/notifications/whatsapp", {"action": "link"}, format="json")
    assert clients["son1"].get("/api/admin/whatsapp").status_code == 403
    r = clients["dad"].get("/api/admin/whatsapp")
    assert r.status_code == 200
    d = r.json()["diagnostics"]
    assert d["dns"]["ok"] and d["clock"]["ok"] and d["storage"]["ok"]
    assert d["sessions"][0]["person"] == "Sam Sample" and "session" not in d["sessions"][0]
    blob = r.content.decode()
    session = WhatsAppLink.objects.get(user=family["son1"]).session
    assert session not in blob and TOKEN not in blob and "FAKE-QR" not in blob
    assert d["tested"]["pinned"] == "1.1.0" and d["compatible"] is True
    r = clients["dad"].post("/api/admin/whatsapp", {"action": "restart"}, format="json")
    assert r.status_code == 200 and bridge.restarts == 1
    assert AuditEvent.objects.filter(action="whatsapp.bridge_restart").exists()


def test_at373_incompatible_bridge_alerts_main_admin_outside_whatsapp(family, clients, bridge):
    bridge.version = "0.9.0"
    clients["dad"].get("/api/admin/whatsapp")
    clients["dad"].get("/api/admin/whatsapp")
    msgs = OutboxMessage.objects.filter(user=family["dad"], event="whatsapp.incompatible")
    assert msgs.exists() and not msgs.filter(channel="whatsapp").exists()
    assert msgs.values("channel").distinct().count() == msgs.count()  # once per channel, not per poll


def test_at373_bridge_pins_a_tested_library_version():
    pkg = json.loads((ROOT / "bridge/whatsapp/package.json").read_text())
    compat = json.loads((ROOT / "bridge/whatsapp/compat.json").read_text())
    lib = pkg["dependencies"]["@whiskeysockets/baileys"]
    assert re.fullmatch(r"\d+\.\d+\.\d+(-[a-z0-9.]+)?", lib)  # exact pin, never "latest" or a range
    assert compat["library"].endswith("@" + lib) and pkg["version"] == compat["pinned"] and compat["pinned"] in compat["tested_versions"]
    src = (ROOT / "bridge/whatsapp/session.mjs").read_text() + (ROOT / "bridge/whatsapp/server.mjs").read_text()
    assert "fetchLatestWaWebVersion" not in src  # no spoofed user agent / unpinned protocol version
    assert "515" in src  # the restart WhatsApp requests after the scan is handled


# ------------------------------------------------------------------ AT-374 documentation

def test_at374_obsolete_storage_and_nas_instructions_removed():
    hits = []
    for p in list((ROOT / "docs").rglob("*.md")) + [ROOT / "README.md"]:
        if p.name in ("CHANGELOG.md", "TRACEABILITY.md", "IMPLEMENTATION_STATUS.md", "TEST_REPORT.md"):
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if re.search(r"Settings → Storage & NAS|Storage & backup → NAS|in \*\*Storage & NAS\*\*", line) and "no longer exists" not in line \
                    and "Upgrading from Storage & NAS" not in line and "old **Settings → Storage & NAS**" not in line:
                hits.append(f"{p.relative_to(ROOT)}:{i}")
    assert not hits, hits
