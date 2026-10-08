"""Security center (Change Set M, AT-149..AT-160): Internet Ready, manual security test, OS updates and reboot,
firewall monitoring, Security Health score, security-record retention/purge, Storage Health, original protection."""
import json
import os
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlsplit

import pytest
import requests
from conftest import client_for, personal_root, run_jobs, upload
from django.conf import settings as dj_settings
from django.urls import get_resolver
from django.utils import timezone

from apps.core import config
from apps.core.models import AuditEvent
from apps.library.models import Document, DocumentVersion
from apps.ops.host_helper import HostHelper
from apps.security import center
from apps.security.models import OsUpdateRun, SecurityTestRun

pytestmark = pytest.mark.django_db

ORIGIN = "https://docs.example.test"
SECURE_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin",
                  "Content-Security-Policy": "default-src 'self'", "Strict-Transport-Security": "max-age=31536000",
                  "Set-Cookie": "pd_csrftoken=x; Secure; SameSite=Lax"}


class FakeWeb:
    """Answers like a correctly published Personal DM behind an HTTPS proxy; records every host contacted."""

    def __init__(self, *, tls_ok=True, redirect=True, hsts=True, leak=None):
        self.hosts, self.tls_ok, self.redirect, self.hsts, self.leak = set(), tls_ok, redirect, hsts, leak or set()

    def __call__(self, method, url, **kw):
        u = urlsplit(url)
        self.hosts.add(u.hostname)
        headers = dict(SECURE_HEADERS)
        if not self.hsts:
            headers.pop("Strict-Transport-Security")
        if u.scheme == "http":
            if self.redirect:
                return SimpleNamespace(status_code=301, headers={"Location": url.replace("http://", "https://")}, text="")
            return SimpleNamespace(status_code=200, headers={}, text="plain")
        if not self.tls_ok:
            raise requests.exceptions.SSLError("certificate verify failed: self-signed certificate")
        path = u.path
        if any(path.startswith(p) for p in self.leak):
            return SimpleNamespace(status_code=200, headers=headers, text="{}")
        if path.startswith("/api/") and path not in ("/api/session", "/api/auth/google/start"):
            return SimpleNamespace(status_code=403, headers=headers, text="{}")
        if path == "/api/auth/google/start":
            return SimpleNamespace(status_code=302, headers={**headers, "Location": "/login?error=google_disabled"}, text="")
        if method == "TRACE":
            return SimpleNamespace(status_code=405, headers=headers, text="")
        if path in ("/.env", "/.git/config", "/admin/") or "settings.py" in path or "passwd" in path:
            return SimpleNamespace(status_code=404, headers=headers, text="Not found")
        return SimpleNamespace(status_code=200, headers=headers, text="{}")


@pytest.fixture
def internet(settings):
    settings.PUBLIC_ORIGIN = ORIGIN
    settings.SESSION_COOKIE_SECURE = settings.CSRF_COOKIE_SECURE = True
    config.set_value("security.deployment", "internet")


def _patch(web):
    return mock.patch.multiple("apps.security.center.requests",
                               get=lambda url, **kw: web("GET", url, **kw), request=lambda m, url, **kw: web(m, url, **kw))


# ---------------------------------------------------------------- AT-149 Internet Ready

def test_at149_internet_ready_requires_valid_https(family, settings, internet):
    with _patch(FakeWeb()):
        res = center.https_checks()
    assert res["internet_ready"] and res["https_ok"]
    assert {c["key"] for c in res["checks"]} == {"https_origin", "tls_valid", "http_redirect", "secure_cookies", "headers", "hsts"}
    with _patch(FakeWeb(tls_ok=False)):
        res = center.https_checks()
    assert not res["internet_ready"] and not {c["key"]: c["ok"] for c in res["checks"]}["tls_valid"]
    with _patch(FakeWeb(redirect=False, hsts=False)):
        res = center.https_checks()
    bad = {c["key"] for c in res["checks"] if not c["ok"]}
    assert bad == {"http_redirect", "hsts"} and not res["internet_ready"]
    settings.PUBLIC_ORIGIN = "http://docs.example.test"
    settings.SESSION_COOKIE_SECURE = settings.CSRF_COOKIE_SECURE = False
    with _patch(FakeWeb()):
        assert not center.https_checks()["internet_ready"]
    # LAN-only HTTP is a distinct state, never "Internet Ready"
    config.set_value("security.deployment", "lan")
    with _patch(FakeWeb()):
        res = center.https_checks()
    assert res["deployment"] == "lan" and res["internet_ready"] is False
    assert client_for(family["dad"]).get("/api/security/https").json()["deployment"] == "lan"
    assert client_for(family["son1"]).get("/api/security/https").status_code == 403


# ---------------------------------------------------------------- AT-150..152 security test

def test_at150_manual_baseline_application_and_host_only(family, clients, internet):
    assert not SecurityTestRun.objects.exists()  # never started by install/upgrade/migrations
    upload(clients["son1"], personal_root(family["son1"]), name="a.txt", content=b"synthetic")
    assert clients["son1"].post("/api/security/tests").status_code == 403
    web = FakeWeb()
    with _patch(web):
        r = clients["dad"].post("/api/security/tests")
        assert r.status_code == 202
        assert clients["dad"].post("/api/security/tests").status_code == 409  # one at a time
        run_jobs()
    run = SecurityTestRun.objects.get()
    assert run.status in ("passed", "warning", "failed") and run.finished_at
    cats = {x["category"] for x in run.findings}
    for c in ("HTTPS & TLS", "Framework & configuration", "Authentication & access control", "Web baseline (OWASP-style)",
              "Upload security", "Dependencies", "Secrets & file permissions", "Host"):
        assert c in cats, c
    for x in run.findings:
        assert x["status"] in ("pass", "warn", "fail", "info") and x["severity"] in center.SEVERITIES
        if x["status"] in ("warn", "fail"):
            assert x["remediation"] or x["detail"]
    assert web.hosts == {"docs.example.test"}  # only this deployment's own address, never other LAN devices
    checks = {x["check"]: x for x in run.findings}
    assert checks["Protected pages require sign-in"]["status"] == "pass"
    assert checks["Members cannot open other members' private documents"]["status"] == "pass"
    detail = clients["dad"].get("/api/security/tests").json()
    assert detail["latest"]["id"] == run.id and "does not prove" in detail["note"]


def test_at150_access_control_leak_is_critical(family, clients, internet):
    upload(clients["son1"], personal_root(family["son1"]), name="a.txt", content=b"synthetic")
    with _patch(FakeWeb(leak={"/api/documents"})):
        clients["dad"].post("/api/security/tests")
        run_jobs()
    run = SecurityTestRun.objects.get()
    leak = next(x for x in run.findings if x["check"] == "Protected pages require sign-in")
    assert leak["status"] == "fail" and leak["severity"] == "critical" and run.status == "failed"


def test_at151_critical_high_findings_warn_but_never_block(family, clients, settings, internet):
    settings.DEBUG = True  # simulated Critical finding on an Internet-facing deployment
    with _patch(FakeWeb()):
        clients["dad"].post("/api/security/tests")
        run_jobs()
    run = SecurityTestRun.objects.get()
    debug = next(x for x in run.findings if x["check"] == "Debug mode off")
    assert debug["status"] == "fail" and debug["severity"] == "critical"
    assert run.status == "failed" and run.summary["counts"]["critical"] >= 1
    with _patch(FakeWeb()):
        h = clients["dad"].get("/api/security/health").json()
    assert h["status"] == "At Risk" and any("Critical findings" in f for f in h["forced"])
    # deployment is not technically blocked: the app keeps working
    assert clients["son1"].get("/api/dashboard").status_code == 200
    from apps.notify.models import Notification

    assert Notification.objects.filter(user=family["dad"], kind="security.operations", title__icontains="Critical").exists()


def test_at152_history_comparison_and_one_year_retention(family, clients, internet):
    with _patch(FakeWeb(hsts=False)):
        clients["dad"].post("/api/security/tests")
        run_jobs()
    with _patch(FakeWeb()):
        clients["dad"].post("/api/security/tests")
        run_jobs()
    runs = clients["dad"].get("/api/security/tests").json()["runs"]
    assert len(runs) == 2
    latest = SecurityTestRun.objects.first()
    assert "https-hsts" in latest.summary["resolved"]
    assert next(x for x in latest.findings if x["id"] == "https-hsts")["resolution"] == "resolved"
    old = SecurityTestRun.objects.last()
    SecurityTestRun.objects.filter(pk=old.pk).update(started_at=timezone.now() - timedelta(days=400))
    SecurityTestRun.objects.filter(pk=latest.pk).update(started_at=timezone.now() - timedelta(days=200))
    center.apply_retention()
    assert list(SecurityTestRun.objects.values_list("id", flat=True)) == [latest.id]  # 200 days < 1 year: kept


# ---------------------------------------------------------------- AT-153..155 OS updates, reboot, firewall

APT_SIM = """NOTE: This is only a simulation!
Inst libssl3t64 [3.5.1-1] (3.5.1-1+deb13u1 Debian-Security:13/stable-security [amd64])
Inst openssl [3.5.1-1] (3.5.1-1+deb13u1 Debian-Security:13/stable-security [amd64])
Inst tzdata [2025b-1] (2025c-0+deb13u1 Debian:13.2/stable [all])
Conf libssl3t64 (3.5.1-1+deb13u1 Debian-Security:13/stable-security [amd64])
"""


class FakeRun:
    def __init__(self, outputs):
        self.calls, self.outputs = [], outputs

    def __call__(self, cmd, timeout=600, env=None):
        self.calls.append(cmd)
        for key, out in self.outputs.items():
            if " ".join(cmd).startswith(key):
                return SimpleNamespace(returncode=out[0], stdout=out[1], stderr=out[2] if len(out) > 2 else "")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _helper(tmp_path, outputs, **kw):
    run = FakeRun(outputs)
    return HostHelper(tmp_path, run=run, which=lambda n: f"/usr/bin/{n}", **kw), run


def _request(tmp_path, action):
    d = tmp_path / "host"
    d.mkdir(parents=True, exist_ok=True)
    (d / "request.json").write_text(json.dumps({"id": "req1", "action": action}))


def test_at153_security_updates_listed_and_installed_with_logs(family, clients, tmp_path, settings):
    h, run = _helper(tmp_path, {"apt-get -s": (0, APT_SIM)})
    _request(tmp_path, "check_updates")
    out = h.apply()
    assert out["state"] == "done" and [p["package"] for p in out["pending"]] == ["libssl3t64", "openssl"]  # tzdata is not security
    _request(tmp_path, "install_updates")
    out = h.apply()
    install = [c for c in run.calls if c[:2] == ["apt-get", "install"]][0]
    assert "--only-upgrade" in install and install[-2:] == ["libssl3t64", "openssl"] and "tzdata" not in install
    assert out["installed"] == ["libssl3t64", "openssl"] and (tmp_path / "host" / "logs" / "req1.log").exists()
    # unknown actions are refused by the root helper
    (tmp_path / "host" / "request.json").write_text(json.dumps({"id": "x", "action": "rm -rf /"}))
    assert h.apply()["state"] == "failed"
    # no unattended application-controlled updates: nothing schedules install_updates
    from apps.notify.management.commands import scheduler

    assert "install_updates" not in Path(scheduler.__file__).read_text()
    assert "install_updates" not in Path(center.__file__).read_text().split("def sync_os_runs")[0].split("def pre_update_backup")[0]
    # web side: the page shows pending updates reported by the helper
    hostdir = Path(settings.DATA_DIR) / "host"
    hostdir.mkdir(parents=True, exist_ok=True)
    (hostdir / "helper.json").write_text("{}")
    (hostdir / "check_updates.json").write_text(json.dumps({"id": "c1", "state": "done", "pending": out and [
        {"package": "openssl", "current": "1", "candidate": "2", "origin": "Debian-Security"}], "finished_at": "2026-10-07T00:00:00+00:00"}))
    page = clients["dad"].get("/api/security/os-updates").json()
    assert page["pending"][0]["package"] == "openssl" and "not enabled" in page["unattended"]
    assert clients["son1"].get("/api/security/os-updates").status_code == 403


def test_at154_backup_first_override_with_reason_and_reboot_safeguards(family, clients, tmp_path, settings):
    hostdir = Path(settings.DATA_DIR) / "host"
    hostdir.mkdir(parents=True)
    (hostdir / "helper.json").write_text("{}")
    admin = clients["dad"]
    assert admin.post("/api/security/os-updates/install", {}, format="json").json()["code"] == "confirm_required"
    with mock.patch("apps.security.center.pre_update_backup", return_value={"ok": False, "detail": "pg_dump: connection refused"}):
        r = admin.post("/api/security/os-updates/install", {"confirm": True}, format="json")
        assert r.status_code == 409 and r.json()["code"] == "backup_failed" and not (hostdir / "request.json").exists()
        r = admin.post("/api/security/os-updates/install", {"confirm": True, "override_backup": True, "override_reason": "short"}, format="json")
        assert r.json()["code"] == "reason_required"
        r = admin.post("/api/security/os-updates/install", {"confirm": True, "override_backup": True,
                                                           "override_reason": "Urgent OpenSSL fix, NAS offline"}, format="json")
    assert r.status_code == 202 and r.json()["backup_override"] and r.json()["backup_status"] == "failed"
    assert json.loads((hostdir / "request.json").read_text())["action"] == "install_updates"
    assert AuditEvent.objects.filter(action="security.update_backup_override").exists()
    # a successful backup is a real database dump + settings snapshot
    with mock.patch("apps.ops.backup._dump_db", side_effect=lambda dest: dest.write_bytes(b"PGDMP")):
        b = center.pre_update_backup()
    assert b["ok"] and (Path(b["detail"]) / "database.pgdump").exists() and (Path(b["detail"]) / "settings.json").exists()
    # reboot: preflight warnings, confirmation, no duplicates
    pre = admin.get("/api/security/reboot").json()
    assert "active_sessions" in pre and isinstance(pre["warnings"], list)
    assert admin.post("/api/security/reboot", {}, format="json").json()["code"] == "confirm_required"
    assert admin.post("/api/security/reboot", {"confirm": True}, format="json").status_code == 202
    assert admin.post("/api/security/reboot", {"confirm": True}, format="json").status_code == 409
    h, run = _helper(tmp_path, {})
    _request(tmp_path, "reboot")
    assert h.apply()["state"] == "rebooting"
    assert ["systemctl", "stop", "personaldocs-worker"] in run.calls and any("reboot" in c for c in run.calls[-1])
    _request(tmp_path, "reboot")
    assert h.apply()["state"] == "ignored"  # the helper refuses a second reboot too
    # without the helper the limitation is reported with the host-side commands
    (hostdir / "helper.json").unlink()
    (hostdir / "reboot.json").unlink()
    OsUpdateRun.objects.all().delete()
    r = admin.post("/api/security/reboot", {"confirm": True}, format="json")
    assert r.status_code == 409 and "sudo reboot" in r.json()["manual_commands"]


UFW = """Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
8000/tcp                   ALLOW IN    192.168.1.0/24
"""
SS = """tcp   LISTEN 0 4096 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=1,fd=3))
tcp   LISTEN 0 4096 0.0.0.0:8000 0.0.0.0:* users:(("gunicorn",pid=2,fd=5))
tcp   LISTEN 0 244 127.0.0.1:5432 0.0.0.0:* users:(("postgres",pid=3,fd=6))
tcp   LISTEN 0 4096 0.0.0.0:3310 0.0.0.0:* users:(("clamd",pid=4,fd=7))
tcp   LISTEN 0 4096 0.0.0.0:6379 0.0.0.0:* users:(("redis-server",pid=5,fd=6))
"""


def test_at155_firewall_is_monitored_never_changed(family, clients, tmp_path):
    h, run = _helper(tmp_path, {"ufw status": (0, UFW), "ss -H": (0, SS), "systemctl is-active": (0, "active\n")})
    _request(tmp_path, "inspect")
    out = h.apply()
    assert out["firewall"]["active"] and out["firewall"]["tool"] == "ufw" and out["firewall"]["rules"] == 2
    assert {s["port"] for s in out["unexpected"]} == {3310, 6379}
    assert [s["port"] for s in out["exposed_local_only"]] == [3310]  # ClamAV must never be reachable over the network
    assert all(c[:2] in (["ufw", "status"], ["ss", "-H"], ["systemctl", "is-active"]) for c in run.calls)  # read-only commands
    # no API can modify firewall rules
    routes = [str(p.pattern) for p in get_resolver().url_patterns[0].url_patterns] if hasattr(get_resolver().url_patterns[0], "url_patterns") \
        else [str(p.pattern) for p in get_resolver().url_patterns]
    flat = " ".join(routes) + " ".join(str(p.pattern) for r in get_resolver().url_patterns for p in getattr(r, "url_patterns", []))
    assert "firewall" in flat and not any(w in flat for w in ("firewall/rules", "firewall/open", "firewall/allow", "ufw"))
    r = clients["dad"].put("/api/security/firewall", {"enable": False}, format="json")
    assert r.status_code == 405
    page = clients["dad"].get("/api/security/firewall").json()
    assert "never opens, closes or changes rules" in page["note"]
    assert clients["son1"].get("/api/security/firewall").status_code == 403


# ---------------------------------------------------------------- AT-156/157 Security Health

def _set_host(settings, **files):
    d = Path(settings.DATA_DIR) / "host"
    d.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (d / f"{name}.json").write_text(json.dumps(data))


def test_at156_security_health_widget_score_and_drilldown(family, clients, settings):
    config.set_value("antivirus.enabled", False)
    h = clients["dad"].get("/api/security/health").json()
    assert set(h["components"]) == {"antivirus", "https", "security_test", "os_updates", "firewall", "reboot", "authentik"}
    assert sum(c["max"] for c in h["components"].values()) == 100
    assert 0 <= h["score"] <= 100 and h["band"] in ("Healthy", "Attention", "At Risk")
    assert all(c["link"].startswith("/settings/") for c in h["components"].values())
    # a healthy LAN installation
    _set_host(settings, inspect={"state": "done", "firewall": {"tool": "ufw", "active": True, "rules": 2}, "reboot_required": False},
              check_updates={"state": "done", "pending": []})
    with mock.patch("apps.security.antivirus.health", return_value={"status": "ok", "signatures": "27800", "stale": False}):
        SecurityTestRun.objects.create(status="passed", finished_at=timezone.now(), findings=[])
        h = center.security_health()
    assert h["score"] == 95 and h["band"] == "Healthy" and h["status"] == "Healthy"  # LAN: 15/20 for HTTPS
    # widget only for administrators
    assert "security_health" in clients["dad"].get("/api/dashboard").json()
    assert "security_health" not in clients["son1"].get("/api/dashboard").json()
    assert clients["son1"].get("/api/security/health").status_code == 403


@pytest.mark.parametrize("condition", ["malware", "https", "firewall", "stale", "critical_finding"])
def test_at157_forcing_conditions_set_at_risk(family, clients, settings, condition):
    _set_host(settings, inspect={"state": "done", "firewall": {"tool": "ufw", "active": condition != "firewall"}, "reboot_required": False},
              check_updates={"state": "done", "pending": []})
    av = {"status": "ok", "signatures": "1", "stale": False, "critically_stale": False}
    if condition == "stale":
        av = {"status": "critical_stale", "stale": True, "critically_stale": True, "signature_age_days": 12}
    config.set_value("security.deployment", "internet" if condition in ("https", "firewall") else "lan")
    from apps.security.models import HealthState

    HealthState.put("https", https_ok=condition != "https")
    SecurityTestRun.objects.create(status="failed" if condition == "critical_finding" else "passed", finished_at=timezone.now(),
                                   findings=[{"id": "x", "status": "fail", "severity": "critical", "check": "x"}]
                                   if condition == "critical_finding" else [])
    if condition == "malware":
        doc = Document.objects.create(folder=personal_root(family["son1"]), owner=family["son1"], title="t")
        DocumentVersion.objects.create(document=doc, number=1, original_name="x", storage_path="x/y", size=1, sha256="0",
                                       av_status="quarantined")
    with mock.patch("apps.security.antivirus.health", return_value=av):
        h = center.security_health()
    assert h["status"] == "At Risk" and h["forced"], (condition, h)
    reason = {"malware": "malware", "https": "HTTPS", "firewall": "firewall", "stale": "critically", "critical_finding": "Critical"}[condition]
    assert any(reason in f for f in h["forced"])


# ---------------------------------------------------------------- AT-158 security records

def test_at158_retention_preview_confirm_and_purge_record(family, clients):
    old = timezone.now() - timedelta(days=500)
    for i in range(3):
        e = AuditEvent.objects.create(action="antivirus.scan_failed", target_type="version", target_id=f"v{i}")
        AuditEvent.objects.filter(pk=e.pk).update(at=old)
    keep = AuditEvent.objects.create(action="antivirus.threat", target_type="version", target_id="still-quarantined")
    AuditEvent.objects.filter(pk=keep.pk).update(at=old)
    prior = AuditEvent.objects.create(action="security.log_purge")
    AuditEvent.objects.filter(pk=prior.pk).update(at=old)
    doc = Document.objects.create(folder=personal_root(family["son1"]), owner=family["son1"], title="t")
    v = DocumentVersion.objects.create(document=doc, number=1, original_name="x", storage_path="a/b", size=1, sha256="0", av_status="quarantined")
    AuditEvent.objects.filter(pk=keep.pk).update(target_id=str(v.id))
    admin = clients["dad"]
    assert config.get("security.log_retention_days") == 365
    with pytest.raises(Exception):
        config.set_value("security.log_retention_days", 30)  # never below one year
    pre = admin.get("/api/security/records", {"categories": "antivirus,alerts", "older_than_days": 365}).json()
    av_cat = next(c for c in pre["categories"] if c["key"] == "antivirus")
    assert av_cat["records"] == 3 and av_cat["protected"] == 1 and pre["estimated_bytes"] > 0
    assert next(c for c in pre["categories"] if c["key"] == "alerts")["protected"] == 1  # earlier purge record
    assert admin.post("/api/security/records", {"categories": ["antivirus"], "older_than_days": 365}, format="json").json()["code"] == "confirm_required"
    assert admin.get("/api/security/records", {"older_than_days": 5}).status_code == 400
    r = admin.post("/api/security/records", {"categories": ["antivirus", "alerts"], "older_than_days": 365, "confirm": True}, format="json")
    assert r.json()["removed"]["antivirus"] == 3
    assert AuditEvent.objects.filter(pk=keep.pk).exists() and AuditEvent.objects.filter(pk=prior.pk).exists()
    purge_rec = AuditEvent.objects.filter(action="security.log_purge").order_by("-at").first()
    assert purge_rec.actor_id == family["dad"].pk and purge_rec.context["removed_antivirus"] == 3
    assert clients["son1"].get("/api/security/records").status_code == 403


# ---------------------------------------------------------------- AT-159/160 storage

def test_at159_storage_health_categories_thresholds_and_cleanup(family, clients, settings):
    upload(clients["son1"], personal_root(family["son1"]), name="doc.txt", content=b"synthetic document")
    tmp = Path(settings.TMP_DIR) / "old-export.zip"
    tmp.write_bytes(b"x" * 5000)
    os.utime(tmp, (time.time() - 3 * 86400,) * 2)
    orphan = Path(settings.DERIVATIVES_DIR) / "00" / "11111111-2222-3333-4444-555555555555"
    orphan.mkdir(parents=True)
    (orphan / "preview.pdf").write_bytes(b"y" * 3000)
    page = clients["dad"].get("/api/security/storage?refresh=1").json()
    assert page["total"] > 0 and page["used"] > 0 and page["free"] >= 0 and 0 <= page["percent"] <= 100
    keys = {c["key"] for c in page["categories"]}
    assert keys == {"documents", "previews", "ocr", "database", "logs", "quarantine", "backups", "temporary",
                    "ocr_text", "ocr_cache", "ocr_orphans", "ocr_models"}  # OCR categories: Change Set Q
    assert next(c for c in page["categories"] if c["key"] == "documents")["bytes"] >= len(b"synthetic document")
    items = {i["key"]: i for i in page["cleanup"]["items"]}
    assert items["temporary"]["bytes"] >= 5000 and items["orphan_previews"]["count"] == 1
    assert "Original documents" in page["cleanup"]["never"]
    config.set_value("storage.warn_percent", 50)
    config.set_value("storage.critical_percent", 51)
    with mock.patch("apps.security.center.shutil.disk_usage", return_value=SimpleNamespace(total=100, used=95, free=5)):
        assert center.storage_alerts() == "critical"
    from apps.notify.models import Notification

    assert Notification.objects.filter(user=family["dad"], kind="security.operations", title__startswith="Storage critical").exists()
    assert clients["son1"].get("/api/security/storage").status_code == 403


def test_at160_no_cleanup_or_security_workflow_deletes_originals(family, clients, settings):
    r = upload(clients["son1"], personal_root(family["son1"]), name="keep.txt", content=b"original content")
    doc = Document.objects.get(pk=r.json()["documents"][0]["id"])
    original = Path(settings.ORIGINALS_DIR) / doc.current_version.storage_path
    os.utime(original, (time.time() - 1000 * 86400,) * 2)  # even very old originals
    Document.objects.filter(pk=doc.pk).update(created_at=timezone.now() - timedelta(days=2000))
    admin = clients["dad"]
    admin.post("/api/security/storage", {"kinds": list(center.CLEANUP_KINDS), "confirm": True}, format="json")
    admin.post("/api/security/records", {"categories": list(center.PURGE_CATEGORIES), "older_than_days": 30, "confirm": True}, format="json")
    center.apply_retention()
    assert original.read_bytes() == b"original content"
    assert Document.objects.filter(pk=doc.pk).exists() and DocumentVersion.objects.filter(document=doc).count() == 1
    # the same holds for the root helper: none of its actions touches the data directory
    helper_src = Path(__import__("apps.ops.host_helper", fromlist=["x"]).__file__).read_text()
    assert "originals" not in helper_src and "rmtree" not in helper_src
