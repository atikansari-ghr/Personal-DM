"""Login audit, real client IP, local GeoIP, country/IP access policy, recovery and alerts (AT-39..AT-46, AT-49, AT-50)."""
import io
import shutil
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import config
from apps.security import geoip, netutil, policy
from apps.security.models import GeoPolicy, IPRule, LoginEvent, TemporaryCountryAccess
from conftest import PASSWORD, client_for
from mmdb_writer import TEST_NETWORKS, build

pytestmark = pytest.mark.django_db

SA, IN, US, TR = "5.42.0.10", "14.96.0.10", "23.0.0.10", "31.145.0.10"
PROXY = "192.168.1.5"


@pytest.fixture(autouse=True)
def _fresh_policy():
    policy.invalidate()
    yield
    policy.invalidate()


@pytest.fixture
def geodb(settings):
    geoip.geoip_dir().mkdir(parents=True, exist_ok=True)
    build(TEST_NETWORKS, geoip.db_path())
    return geoip.db_path()


def anon(ip, **headers):
    return APIClient(REMOTE_ADDR=ip, **headers)


def login(client, username="dad", password=PASSWORD):
    return client.post("/api/auth/login", {"username": username, "password": password}, format="json")


# ------------------------------------------------------------------ real client IP (AT-39, AT-41)

def test_client_ip_trusted_proxy_rightmost_untrusted(rf, settings):
    settings.TRUSTED_PROXY_IPS = ["192.168.1.0/24", "10.0.0.1"]
    req = rf.get("/", REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=f"6.6.6.6, {SA}")
    assert netutil.client_ip(req) == SA  # the left entry was supplied by the client and is ignored
    req = rf.get("/", REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=f"{SA}, 10.0.0.1")
    assert netutil.client_ip(req) == SA  # chained trusted proxies are skipped
    req = rf.get("/", REMOTE_ADDR=PROXY, HTTP_X_REAL_IP=IN)
    assert netutil.client_ip(req) == IN
    req = rf.get("/", REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=f"{US}, not-an-ip, {SA}")
    assert netutil.client_ip(req) == SA
    req = rf.get("/", REMOTE_ADDR=f"::ffff:{PROXY}", HTTP_X_FORWARDED_FOR=SA)
    assert netutil.client_ip(req) == SA  # IPv4-mapped IPv6 peer


def test_at41_untrusted_client_cannot_spoof_forwarded_headers(rf, settings, family, geodb):
    settings.TRUSTED_PROXY_IPS = [PROXY]
    req = rf.get("/", REMOTE_ADDR=TR, HTTP_X_FORWARDED_FOR=SA, HTTP_X_REAL_IP=SA)
    assert netutil.client_ip(req) == TR
    pol = GeoPolicy.get()
    pol.enabled, pol.mode = True, "allowlist"
    pol.save()
    from apps.security.models import CountryRule

    CountryRule.objects.create(country="SA", kind="allow")
    policy.invalidate()
    r = anon(TR, HTTP_X_FORWARDED_FOR=SA).get("/api/session")
    assert r.status_code == 403  # the forged header does not make Türkiye look like Saudi Arabia


def test_at39_login_events_record_real_ip_through_proxy(settings, family, geodb):
    settings.TRUSTED_PROXY_IPS = [PROXY]
    assert login(anon(PROXY, HTTP_X_FORWARDED_FOR=SA, HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1")).status_code == 200
    assert login(anon(PROXY, HTTP_X_FORWARDED_FOR=IN), password="wrong").status_code == 400
    ok = LoginEvent.objects.get(result="success")
    bad = LoginEvent.objects.get(result="failure")
    assert (ok.ip, ok.country, ok.method, ok.device, ok.os) == (SA, "SA", "password", "mobile", "iOS")
    assert ok.user.username == "dad" and ok.correlation
    assert (bad.ip, bad.country, bad.username, bad.reason, bad.user) == (IN, "IN", "dad", "bad_credentials", None)


def test_login_audit_flags_totp_logout_and_new_country(settings, family, geodb):
    from apps.accounts import services as S
    import pyotp

    settings.TRUSTED_PROXY_IPS = [PROXY]
    c = anon(PROXY, HTTP_X_FORWARDED_FOR=SA)
    login(c)
    c.post("/api/auth/logout")
    user = family["mom"]
    S.totp_begin(user)
    user.refresh_from_db()
    from apps.core import crypto

    secret = crypto.decrypt(user.totp_pending_enc)
    S.totp_enable(user, pyotp.TOTP(secret).now())
    c2 = anon(PROXY, HTTP_X_FORWARDED_FOR=SA)
    assert login(c2, "mom").json()["status"] == "totp_required"
    assert c2.post("/api/auth/totp", {"code": "000000"}, format="json").status_code == 400
    assert c2.post("/api/auth/totp", {"code": pyotp.TOTP(secret).now()}, format="json").status_code == 200
    c3 = anon(PROXY, HTTP_X_FORWARDED_FOR=IN)
    login(c3)
    results = list(LoginEvent.objects.order_by("at").values_list("username", "result", "method", "totp_used"))
    assert ("dad", "logout", "logout", False) in results
    assert ("mom", "failure", "password+totp", True) in results
    assert ("mom", "success", "password+totp", True) in results
    latest = LoginEvent.objects.filter(username="dad", result="success").order_by("-at").first()
    assert "new_country" in latest.flags and "new_ip" in latest.flags


def test_secrets_never_stored_in_login_audit(family, settings):
    login(anon(SA), password="Very-Secret-Attempt-1!")
    blob = str(list(LoginEvent.objects.values()))
    assert "Very-Secret-Attempt-1!" not in blob


# ------------------------------------------------------------------ admin login audit (AT-46)

def test_at46_admin_filters_login_events_and_users_cannot(settings, clients, family, geodb):
    settings.TRUSTED_PROXY_IPS = [PROXY]
    login(anon(PROXY, HTTP_X_FORWARDED_FOR=SA))
    login(anon(PROXY, HTTP_X_FORWARDED_FOR=IN), "mom")
    login(anon(PROXY, HTTP_X_FORWARDED_FOR=US), "son1", "bad")
    admin = clients["dad"]
    assert clients["son1"].get("/api/admin/security/logins").status_code == 403
    assert anon(SA).get("/api/admin/security/logins").status_code in (401, 403)
    data = admin.get("/api/admin/security/logins").json()
    assert data["total"] == 3 and data["summary"]["success_24h"] == 2 and data["summary"]["failed_24h"] == 1
    assert [e["username"] for e in admin.get("/api/admin/security/logins?country=IN").json()["events"]] == ["mom"]
    assert admin.get("/api/admin/security/logins?result=failure").json()["events"][0]["ip"] == US
    assert admin.get(f"/api/admin/security/logins?ip={SA}").json()["total"] == 1
    assert admin.get(f"/api/admin/security/logins?user={family['mom'].pk}").json()["total"] == 1
    assert admin.get("/api/admin/security/logins?method=password").json()["total"] == 3
    future = (timezone.now() + timedelta(days=1)).date().isoformat()
    assert admin.get(f"/api/admin/security/logins?from={future}").json()["total"] == 0


# ------------------------------------------------------------------ local GeoIP (AT-40, AT-49)

def test_at40_local_geoip_lookup(geodb, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no external lookups"))
    assert geoip.lookup(SA) == ("SA", "Saudi Arabia")
    assert geoip.lookup(IN) == ("IN", "India")
    assert geoip.lookup("192.168.1.10") is None  # private
    assert geoip.lookup("8.8.8.8") is None  # not in the synthetic database
    st = geoip.status()
    assert st["installed"] and st["database_type"] == "GeoLite2-Country" and st["build_date"]


def test_at49_failed_geoip_update_keeps_database_and_policy(geodb, family, clients):
    from apps.security.models import CountryRule

    pol = GeoPolicy.get()
    pol.enabled, pol.mode = True, "allowlist"
    pol.save()
    CountryRule.objects.create(country="SA", kind="allow")
    before = geodb.read_bytes()

    class Resp:
        status_code = 200
        content = b"this is not a tar.gz"

    class Http:
        @staticmethod
        def get(*a, **k):
            return Resp()

    with pytest.raises(geoip.GeoIPError):
        geoip.update_from_maxmind("123", "key", http=Http)
    assert geodb.read_bytes() == before and geoip.lookup(SA) == ("SA", "Saudi Arabia")
    assert geoip.status()["last_error"]
    assert GeoPolicy.get().enabled and CountryRule.objects.filter(country="SA").exists()
    # a corrupt manual upload is rejected as well
    from django.core.files.uploadedfile import SimpleUploadedFile

    r = clients["dad"].post("/api/admin/security/geoip/upload", {"file": SimpleUploadedFile("x.mmdb", b"garbage")}, format="multipart")
    assert r.status_code == 400 and geodb.read_bytes() == before


def test_geoip_update_installs_valid_download(settings, tmp_path):
    import tarfile

    src = tmp_path / "GeoLite2-Country.mmdb"
    build(TEST_NETWORKS, src)
    tgz = tmp_path / "db.tar.gz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(src, arcname="GeoLite2-Country_20261001/GeoLite2-Country.mmdb")

    class Resp:
        status_code = 200
        content = tgz.read_bytes()

    seen = {}

    class Http:
        @staticmethod
        def get(url, auth, timeout):
            seen.update(url=url, auth=auth)
            return Resp()

    geoip.update_from_maxmind("123", "license-abc", http=Http)
    assert "license-abc" not in seen["url"] and seen["auth"] == ("123", "license-abc")
    assert geoip.lookup(TR) == ("TR", "Türkiye") and geoip.status()["last_success"]


# ------------------------------------------------------------------ access policy (AT-42..AT-45)

def _set_policy(admin, **body):
    return admin.put("/api/admin/security/policy", body, format="json")


def test_at42_allow_list_saudi_india(family, clients, geodb):
    admin = clients["dad"]
    r = _set_policy(admin, enabled=True, mode="allowlist", allowed=["SA", "IN"])
    assert r.status_code == 200, r.content  # the admin's own address (test client) is internal -> no lockout
    assert r.json()["allowed"] == ["IN", "SA"]
    assert anon(SA).get("/api/session").status_code == 200
    assert anon(IN).get("/api/session").status_code == 200
    assert anon(US).get("/api/session").status_code == 403
    assert anon(TR).get("/login").status_code == 403
    assert anon("192.168.1.30").get("/api/session").status_code == 200  # LAN always allowed
    assert anon(US).get("/api/health").status_code in (200, 503)  # proxy health checks pass


def test_block_list_and_unknown_locations(family, clients, geodb):
    admin = clients["dad"]
    assert _set_policy(admin, enabled=True, mode="blocklist", blocked=["TR"]).status_code == 200
    assert anon(TR).get("/api/session").status_code == 403
    assert anon(US).get("/api/session").status_code == 200
    assert anon("8.8.8.8").get("/api/session").status_code == 200  # unknown -> allow (default)
    assert _set_policy(admin, enabled=True, mode="blocklist", blocked=["TR"], unknown_action="deny").status_code == 200
    assert anon("8.8.8.8").get("/api/session").status_code == 403


def test_at43_denied_before_authentication(family, clients, geodb, settings):
    _set_policy(clients["dad"], enabled=True, mode="allowlist", allowed=["SA"])
    c = anon(US)
    r = login(c)
    assert r.status_code == 403 and "location" in r.json()["error"]
    assert not LoginEvent.objects.exists()  # authentication code never ran
    blocked = client_for(family["mom"])
    blocked.defaults["REMOTE_ADDR"] = US
    assert blocked.get("/api/documents").status_code == 403  # even with a valid session


def test_at44_ip_rule_precedence(family, clients, geodb):
    admin = clients["dad"]
    _set_policy(admin, enabled=True, mode="allowlist", allowed=["SA"])
    assert admin.post("/api/admin/security/ip-rules", {"cidr": "23.0.0.0/24", "kind": "trusted", "description": "Office"}, format="json").status_code == 201
    assert anon(US).get("/api/session").status_code == 200  # trusted IP beats the country policy
    assert admin.post("/api/admin/security/ip-rules", {"cidr": "23.0.0.10", "kind": "blocked", "description": "Abuse"}, format="json").status_code == 201
    assert anon(US).get("/api/session").status_code == 403  # explicit block beats trust
    assert anon("23.0.0.11").get("/api/session").status_code == 200
    assert admin.post("/api/admin/security/ip-rules", {"cidr": "5.42.0.0/24", "kind": "blocked", "description": "x"}, format="json").status_code == 201
    assert anon(SA).get("/api/session").status_code == 403  # block beats an allowed country
    rule = IPRule.objects.get(cidr="5.42.0.0/24")
    assert admin.patch(f"/api/admin/security/ip-rules/{rule.pk}", {"enabled": False}, format="json").status_code == 200
    assert anon(SA).get("/api/session").status_code == 200
    expired = IPRule.objects.create(cidr="14.96.0.0/24", kind="trusted", expires_at=timezone.now() - timedelta(minutes=1))
    assert not expired.live()
    assert anon(IN).get("/api/session").status_code == 403  # expired trust no longer applies
    assert admin.post("/api/admin/security/ip-rules", {"cidr": "999.1.1.1", "kind": "blocked", "description": "x"}, format="json").status_code == 400
    assert admin.post("/api/admin/security/ip-rules", {"cidr": "2001:db8::/32", "kind": "trusted"}, format="json").status_code == 201


def test_at45_temporary_country_access_window(family, clients, geodb):
    admin = clients["dad"]
    _set_policy(admin, enabled=True, mode="allowlist", allowed=["SA"])
    now = timezone.now()
    r = admin.post("/api/admin/security/temporary", {"country": "TR", "starts_at": (now - timedelta(hours=1)).isoformat(),
                                                    "ends_at": (now + timedelta(hours=1)).isoformat(), "reason": "Family trip"}, format="json")
    assert r.status_code == 201 and r.json()["state"] == "active"
    assert anon(TR).get("/api/session").status_code == 200
    row = TemporaryCountryAccess.objects.get()
    row.ends_at = timezone.now() - timedelta(seconds=1)
    row.save()
    policy.invalidate()
    assert anon(TR).get("/api/session").status_code == 403  # expired by time alone
    states = {t["country"]: t["state"] for t in admin.get("/api/admin/security/policy").json()["temporary"]}
    assert states["TR"] == "expired"
    future = admin.post("/api/admin/security/temporary", {"country": "US", "starts_at": (now + timedelta(days=1)).isoformat(),
                                                         "ends_at": (now + timedelta(days=2)).isoformat(), "reason": "Later trip"}, format="json")
    assert future.json()["state"] == "scheduled" and anon(US).get("/api/session").status_code == 403
    assert admin.post("/api/admin/security/temporary", {"country": "ZZ", "ends_at": (now + timedelta(days=1)).isoformat(), "reason": "x"}, format="json").status_code == 400
    assert admin.post("/api/admin/security/temporary", {"country": "TR", "ends_at": (now - timedelta(days=1)).isoformat(), "reason": "x"}, format="json").status_code == 400


def test_temporary_access_sign_in_is_flagged(family, clients, geodb):
    admin = clients["dad"]
    _set_policy(admin, enabled=True, mode="allowlist", allowed=["SA"])
    now = timezone.now()
    admin.post("/api/admin/security/temporary", {"country": "TR", "starts_at": (now - timedelta(minutes=5)).isoformat(),
                                                "ends_at": (now + timedelta(days=1)).isoformat(), "reason": "Trip"}, format="json")
    assert login(anon(TR), "mom").status_code == 200
    assert "policy_exception" in LoginEvent.objects.get(username="mom").flags


def test_lockout_protection_on_policy_change(family, clients, geodb):
    admin = clients["dad"]
    admin.defaults["REMOTE_ADDR"] = SA  # the admin is connected from Saudi Arabia
    r = _set_policy(admin, enabled=True, mode="allowlist", allowed=["IN"])
    assert r.status_code == 409 and r.json()["code"] == "lockout"
    assert not GeoPolicy.get().enabled  # nothing changed
    r = admin.post("/api/admin/security/ip-rules", {"cidr": "5.42.0.0/24", "kind": "blocked", "description": "x"}, format="json")
    assert r.status_code == 409
    assert _set_policy(admin, enabled=True, mode="allowlist", allowed=["IN", "SA"]).status_code == 200
    assert _set_policy(admin, enabled=True, mode="allowlist", allowed=[]).status_code == 400  # empty allow list refused
    assert _set_policy(admin, enabled=True, mode="allowlist", allowed=["SA"], blocked=["SA"]).status_code == 400
    # rollback restores the previous policy
    assert _set_policy(admin, enabled=True, mode="allowlist", allowed=["SA"]).status_code == 200
    state = admin.post("/api/admin/security/policy/rollback").json()
    assert state["allowed"] == ["IN", "SA"]


def test_policy_test_endpoint_and_permissions(family, clients, geodb):
    admin = clients["dad"]
    _set_policy(admin, enabled=True, mode="allowlist", allowed=["SA"])
    assert admin.post("/api/admin/security/policy/test", {"ip": US}, format="json").json()["reason"] == "country_not_allowed"
    assert admin.post("/api/admin/security/policy/test", {"ip": SA}, format="json").json()["allowed"] is True
    for path in ("/api/admin/security/policy", "/api/admin/security/geoip", "/api/admin/security/traffic"):
        assert clients["mom"].get(path).status_code == 403


# ------------------------------------------------------------------ recovery (AT-50)

def test_at50_console_recovery_from_misconfigured_policy(family, clients, geodb):
    from apps.library.models import Document

    admin = clients["dad"]
    _set_policy(admin, enabled=True, mode="allowlist", allowed=["IN"])
    docs_before = Document.objects.count()
    assert anon(SA).get("/api/session").status_code == 403
    out = io.StringIO()
    call_command("access_policy", "off", stdout=out)
    policy.invalidate()
    assert anon(SA).get("/api/session").status_code == 200
    assert Document.objects.count() == docs_before
    call_command("access_policy", "rollback", stdout=out)
    policy.invalidate()
    assert anon(SA).get("/api/session").status_code == 403
    call_command("access_policy", "trust-ip", SA, "--hours", "2", stdout=out)
    policy.invalidate()
    assert anon(SA).get("/api/session").status_code == 200
    call_command("access_policy", "status", stdout=out)
    assert "ENABLED" in out.getvalue()
    from apps.core.models import AuditEvent

    assert AuditEvent.objects.filter(action__startswith="security.console_").count() >= 3


def test_emergency_environment_switch(family, clients, geodb, monkeypatch):
    _set_policy(clients["dad"], enabled=True, mode="allowlist", allowed=["IN"])
    assert anon(SA).get("/api/session").status_code == 403
    monkeypatch.setenv("PD_ACCESS_POLICY_DISABLED", "1")
    assert anon(SA).get("/api/session").status_code == 200


# ------------------------------------------------------------------ login protection and alerts

def test_failed_login_escalation_blocks_and_alerts(family, settings, geodb):
    from apps.notify.models import Notification

    config.set_value("security.escalation_failures", 5)
    config.set_value("auth.login_rate_limit", 50)
    for i in range(5):
        login(anon(US), f"nobody{i}", "wrong")
    rule = IPRule.objects.get(automatic=True)
    assert rule.cidr == f"{US}/32" and rule.live()
    assert anon(US).get("/api/session").status_code == 403
    assert Notification.objects.filter(user=family["dad"], kind="security", title__icontains="blocked").count() == 1
    for i in range(5):  # LAN addresses are never auto-blocked
        login(anon("192.168.1.40"), f"x{i}", "wrong")
    assert not IPRule.objects.filter(cidr__startswith="192.168.").exists()
    call_command("access_policy", "clear-automatic", stdout=io.StringIO())
    policy.invalidate()
    assert anon(US).get("/api/session").status_code == 200


def test_alerts_are_throttled_and_secret_free(family, settings, geodb):
    from apps.notify.models import Notification, OutboxMessage

    config.set_value("auth.login_rate_limit", 3)
    config.set_value("security.escalation_failures", 0)
    for _ in range(12):
        login(anon(US), "mom", "Wrong-Secret-9!")
    alerts = Notification.objects.filter(user=family["dad"], kind="security", event="security.failed_logins")
    assert alerts.count() == 1 and "failed sign-in" in alerts.first().body
    locked = Notification.objects.filter(event="security.account_locked")  # once per lock window, to mom and the admins
    assert locked.filter(user=family["mom"]).count() == 1 and locked.filter(user=family["dad"]).count() == 1
    blob = str(list(Notification.objects.values())) + str(list(OutboxMessage.objects.values()))
    assert "Wrong-Secret-9!" not in blob


def test_new_country_alert(family, settings, geodb):
    from apps.notify.models import Notification

    login(anon(SA), "son1")
    login(anon(TR), "son1")
    titles = list(Notification.objects.filter(user=family["son1"], kind="security").values_list("title", flat=True))
    assert titles == ["Sign-in from a new country"]


def test_policy_change_alerts_and_audit(family, clients, geodb):
    from apps.core.models import AuditEvent
    from apps.notify.models import Notification

    _set_policy(clients["dad"], enabled=True, mode="blocklist", blocked=["TR"])
    assert AuditEvent.objects.filter(action="security.policy_update").exists()
    assert Notification.objects.filter(user=family["dad"], title="Access policy changed").exists()


def test_login_audit_retention(family):
    from apps.security.jobs import retention

    config.set_value("security.login_audit_retention_days", 30)
    old = LoginEvent.objects.create(result="failure", username="x")
    LoginEvent.objects.filter(pk=old.pk).update(at=timezone.now() - timedelta(days=31))
    LoginEvent.objects.create(result="failure", username="y")
    assert retention() == 1 and LoginEvent.objects.count() == 1


def test_proxy_diagnostics_hint(settings):
    settings.TRUSTED_PROXY_IPS = ["127.0.0.1"]
    hints = netutil.proxy_diagnostics(["192.168.1.5"] * 6)
    assert hints and "PD_TRUSTED_PROXY_IPS" in hints[0]


# ------------------------------------------------------------------ traffic analytics (AT-47, AT-48)

@pytest.fixture
def access_log(settings, tmp_path):
    from apps.security import traffic

    settings.ACCESS_LOG = str(tmp_path / "logs" / "access.log")
    traffic._configured["path"] = None
    yield tmp_path / "logs" / "access.log"
    traffic._configured["path"] = None


def test_access_log_is_privacy_safe(settings, family, access_log):
    settings.TRUSTED_PROXY_IPS = [PROXY]
    c = anon(PROXY, HTTP_X_FORWARDED_FOR=SA, HTTP_USER_AGENT="TestAgent/1.0", HTTP_REFERER="https://x.example/s/secret-ref")
    c.get("/api/session?token=reset-secret-123")
    c.get("/s/share-token-abcdef/file")
    text = access_log.read_text()
    assert f"{SA} - - [" in text and '"GET /api/session HTTP/1.1" 200' in text
    assert "reset-secret-123" not in text and "share-token-abcdef" not in text and "secret-ref" not in text
    assert "/s/[token]/file" in text and "TestAgent/1.0" in text


def test_at47_traffic_analytics_admin_only_and_summaries(settings, family, clients, access_log, geodb):
    from apps.security import traffic

    config.set_value("goaccess.enabled", True)
    for ip, path in ((SA, "/api/session"), (IN, "/login"), (US, "/api/wp-login.php"), (US, "/api/.env")):
        anon(ip, HTTP_USER_AGENT="Mozilla/5.0").get(path)
    anon(TR, HTTP_USER_AGENT="zgrab/0.x").get("/api/admin/security/traffic")
    traffic.build_report()
    summary = traffic.read_summary()
    assert summary["requests"] >= 5 and summary["errors"]["404"] >= 1
    countries = {c["country"] for c in summary["countries"]}
    assert {"Saudi Arabia", "India", "United States"} <= countries
    admin = clients["dad"]
    data = admin.get("/api/admin/security/traffic").json()
    assert data["enabled"] and data["summary"]["requests"] >= 5
    assert clients["mom"].get("/api/admin/security/traffic").status_code == 403
    assert anon(SA).get("/api/admin/security/traffic").status_code in (401, 403)
    assert anon(SA).get("/api/admin/security/traffic/report.html").status_code in (401, 403)


def test_builtin_summary_without_goaccess(settings, family, access_log, monkeypatch):
    from apps.security import traffic

    monkeypatch.setattr(traffic, "goaccess_binary", lambda: None)
    anon(SA, HTTP_USER_AGENT="curl/8.0").get("/api/session")
    traffic.build_report()
    s = traffic.read_summary()
    assert s["source"] == "built-in" and s["requests"] == 1 and s["bots"] == 1


@pytest.mark.skipif(not shutil.which("goaccess"), reason="goaccess not installed")
def test_goaccess_report_parsed(settings, family, access_log, clients):
    from apps.security import traffic

    for ip in (SA, IN, US):
        anon(ip, HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) Chrome/120").get("/api/session")
    anon(US).get("/api/nope")
    traffic.build_report()
    s = traffic.read_summary()
    assert s["source"] == "goaccess" and not s["error"], s.get("error")
    assert s["requests"] == 4 and s["errors"]["404"] == 1 and len(s["top_ips"]) == 3
    r = clients["dad"].get("/api/admin/security/traffic/report.html")
    assert r.status_code == 200 and r["Content-Security-Policy"] == "sandbox" and "attachment" in r["Content-Disposition"]


def test_blocked_requests_are_counted(family, clients, geodb):
    from apps.security import traffic

    _set_policy(clients["dad"], enabled=True, mode="allowlist", allowed=["SA"])
    for _ in range(3):
        anon(US).get("/api/session")
    stats = traffic.blocked_stats()
    assert stats == [{"reason": "country_not_allowed", "country": "US", "requests": 3}]
