"""Change Set U - corrective: map provider, sign-in design independence, WhatsApp/Discord wiring (backend parts of
AT-340 .. AT-353). The change prompt numbered these AT-311..AT-330; here they are AT-336..AT-355 (prompt + 25), because
AT-311..AT-335 belong to Change Set T. Synthetic data only; WhatsApp uses tests/fake_whatsapp_bridge.py, Discord HTTP is
mocked, and no request reaches a real map provider."""
import json
from pathlib import Path
from unittest import mock

import pytest

from apps.core import config
from apps.notify.models import DiscordWebhook, WhatsAppLink
from apps.security import mapprov

from fake_whatsapp_bridge import FakeBridge

pytestmark = pytest.mark.django_db
TOKEN = "synthetic-bridge-token-0123456789abcdef"
KEY = "synthetic-map-key-DO-NOT-LEAK-42"
HOOK = "https://discord.com/api/webhooks/123456789012345678/" + "S" * 68


@pytest.fixture
def bridge(settings):
    Path(settings.CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    (Path(settings.CONFIG_DIR) / "whatsapp-bridge.token").write_text(TOKEN)
    with FakeBridge(TOKEN) as b:
        config.set_value("whatsapp.bridge_url", f"http://127.0.0.1:{b.port}")
        yield b


# ------------------------------------------------------------------ AT-340 map provider root cause and presets

def test_at340_provider_presets_referrer_policy_and_legacy_custom_url():
    r = mapprov.resolved()
    assert r["provider"] == "osm" and r["url"] == mapprov.OSM_URL
    cfg = mapprov.public_config()
    # tiles carry only this site's origin as Referer (the observed 403 came from same-origin = no Referer at all)
    assert cfg["referrer_policy"] == "strict-origin-when-cross-origin"
    # a custom tile address set before providers existed is honoured
    config.set_value("security.map_tile_url", "https://tiles.example.org/{z}/{x}/{y}.png")
    assert mapprov.resolved()["provider"] == "custom"
    # keyed providers: the key is inserted into the template, and without a key the map reports why
    config.set_value("security.map_provider", "maptiler")
    assert mapprov.public_config()["enabled"] is False and "key" in mapprov.public_config()["unavailable"]
    config.set_value("security.map_api_key", KEY)
    r = mapprov.resolved()
    assert r["provider"] == "maptiler" and KEY in r["url"] and r["url"].startswith("https://api.maptiler.com/")
    assert mapprov.tile_origin() == "https://api.maptiler.com"


def test_at340_csp_allows_only_the_configured_tile_origin(family, clients):
    from apps.core.middleware import SecurityHeadersMiddleware

    SecurityHeadersMiddleware._tiles["at"] = 0.0
    csp = clients["dad"].get("/api/session")["Content-Security-Policy"]
    assert "img-src 'self' data: blob: https://tile.openstreetmap.org" in csp and "connect-src 'self' https://tile.openstreetmap.org" in csp
    # changing the provider through Settings takes effect at once (no stale minute-long cache)
    r = clients["dad"].put("/api/settings", {"values": {"security.map_provider": "custom",
                                                       "security.map_tile_url": "https://tiles.example.org/{z}/{x}/{y}.png"}}, format="json")
    assert r.status_code == 200, r.content
    assert "https://tiles.example.org" in clients["dad"].get("/api/session")["Content-Security-Policy"]


# ------------------------------------------------------------------ AT-341 failure handling (results the browser reports)

@pytest.mark.parametrize("status,word", [(401, "API key"), (403, "blocked"), (429, "limiting"), (None, "could not be reached")])
def test_at341_provider_failures_are_explained(status, word):
    h = mapprov.record_test(status, "" if status else "TypeError: Failed to fetch")
    assert h["state"] == "failed" and word in h["detail"]


def test_at341_unknown_without_cors_is_not_reported_as_failure():
    assert mapprov.record_test(200)["state"] == "ok"
    h = mapprov.record_test(None, "unknown: no status")
    assert h["state"] == "unknown" and h["last_ok"]  # the last good test is kept


# ------------------------------------------------------------------ AT-342 independence from the map

def test_at342_signin_records_zones_and_risk_work_without_tiles(family, clients):
    from apps.security import location
    from apps.security.models import TrustedZone

    config.set_value("security.map_provider", "maptiler")  # keyed provider without a key: map unavailable
    mapprov.record_test(403)
    TrustedZone.objects.create(name="Home", cidrs=["192.168.2.0/24"], classification="home")
    res = location.resolve("192.168.2.10")
    assert res["zone_name"] == "Home"
    data = clients["dad"].get("/api/security/map", {"days": 30}).json()
    assert data["map"]["enabled"] is False and data["map"]["unavailable"]
    assert "events" in data and isinstance(data["events"], list)


# ------------------------------------------------------------------ AT-343 Test Map Provider: authorised, no secrets

def test_at343_map_test_is_main_admin_only_and_returns_no_key(family, clients):
    config.set_value("security.map_provider", "stadia")
    config.set_value("security.map_api_key", KEY)
    assert clients["mom"].post("/api/security/map/test", {"status": 200}, format="json").status_code == 403
    r = clients["dad"].post("/api/security/map/test", {"status": 403}, format="json")
    assert r.status_code == 200 and r.json()["health"]["state"] == "failed"
    # the browser needs the tile template (with a domain-restricted key) to load tiles; the health record never holds it
    assert KEY not in json.dumps(r.json()["health"])
    settings_text = clients["dad"].get("/api/settings").content.decode()
    assert KEY not in settings_text  # secrets are never returned by the settings API
    from apps.core.models import AuditEvent

    assert AuditEvent.objects.filter(action="security.map_provider_test").exists()


# ------------------------------------------------------------------ AT-345 sign-in design vs app theme

def test_at345_theme_and_signin_design_are_independent(family, clients):
    c = clients["dad"]
    assert c.put("/api/settings", {"values": {"login.design": "travel"}}, format="json").status_code == 200
    assert c.put("/api/settings", {"values": {"me.theme": "dark"}}, format="json").status_code == 200
    assert config.get("login.design") == "travel"
    assert c.put("/api/settings", {"values": {"login.design": "nature"}}, format="json").status_code == 200
    assert config.get_user(family["dad"], "me.theme") == "dark"
    # another person's theme is not touched either
    assert config.get_user(family["mom"], "me.theme") != "dark" or config.get_user(family["mom"], "me.theme") is None


# ------------------------------------------------------------------ AT-348 / AT-349 WhatsApp wiring and running bridge

def test_at349_running_bridge_is_detected_before_and_after_enabling(family, clients, bridge):
    svc = clients["dad"].get("/api/admin/connections").json()["providers"]
    wa = next(p for p in svc if p["key"] == "whatsapp")
    assert wa["service"]["state"] == "ready_disabled" and wa["service"]["version"] == "1.1.0" and wa["service"]["protocol"] == 1
    assert wa["status"] == "disabled" and "Planned" not in json.dumps(svc)
    config.set_value("whatsapp.enabled", True)
    wa = next(p for p in clients["dad"].get("/api/admin/connections").json()["providers"] if p["key"] == "whatsapp")
    assert wa["service"]["state"] == "healthy" and wa["service"]["tested"] and wa["status"] == "connected"
    bridge.protocol = 2
    wa = next(p for p in clients["dad"].get("/api/admin/connections").json()["providers"] if p["key"] == "whatsapp")
    assert wa["service"]["state"] == "incompatible"
    assert clients["mom"].get("/api/admin/connections").status_code == 403


def test_at348_disabled_enable_link_test_route_disable(family, clients, bridge):
    c = clients["dad"]
    st = c.get("/api/notifications/whatsapp").json()
    assert st["available"] is False and st["service"]["state"] == "disabled"
    assert c.put("/api/settings", {"values": {"whatsapp.enabled": True}}, format="json").status_code == 200
    st = c.get("/api/notifications/whatsapp").json()
    assert st["available"] is True and st["service"]["state"] == "healthy"  # no restart needed
    assert c.post("/api/notifications/whatsapp", {"action": "link"}, format="json").status_code == 200
    sid = WhatsAppLink.objects.get(user=family["dad"]).session
    assert "qr_svg" in c.get("/api/notifications/whatsapp").json()
    bridge.connect(sid)
    assert c.get("/api/notifications/whatsapp").json()["state"] == "connected"
    assert c.post("/api/notifications/channel-test", {"channel": "whatsapp"}, format="json").status_code == 200
    assert bridge.sent and bridge.sent[-1][0] == sid
    prefs = c.get("/api/me/notification-preferences").json()
    assert "whatsapp" in {ch["channel"] for ch in prefs["channels"] if ch["configured"]}
    assert c.put("/api/settings", {"values": {"whatsapp.enabled": False}}, format="json").status_code == 200
    st = c.get("/api/notifications/whatsapp").json()
    assert st["available"] is False and st["service"]["state"] == "disabled"


def test_at350_bridge_down_is_degraded_and_other_channels_stay_up(family, clients, bridge):
    config.set_value("whatsapp.enabled", True)
    config.set_value("smtp.enabled", True)
    config.set_value("smtp.host", "smtp.example.com")
    bridge.__exit__(None, None, None)  # stop the bridge
    cards = {p["key"]: p for p in clients["dad"].get("/api/admin/connections").json()["providers"]}
    assert cards["whatsapp"]["status"] == "degraded" and cards["whatsapp"]["service"]["reachable"] is False
    assert cards["email"]["status"] == "configured" and cards["in_app"]["status"] == "connected"
    st = clients["dad"].get("/api/notifications/whatsapp").json()
    assert st["service"]["state"] in ("unavailable", "stopped")  # "stopped" where systemd reports the unit inactive


def test_at351_admin_view_holds_no_session_material_and_people_are_isolated(family, clients, bridge):
    config.set_value("whatsapp.enabled", True)
    clients["dad"].post("/api/notifications/whatsapp", {"action": "link"}, format="json")
    sid = WhatsAppLink.objects.get(user=family["dad"]).session
    text = clients["dad"].get("/api/admin/connections").content.decode()
    assert sid not in text and "qr" not in text.lower().replace("required", "")
    other = clients["mom"].get("/api/notifications/whatsapp").json()
    assert other["state"] == "not_linked" and "qr_svg" not in other
    # Mom cannot unlink or reconnect Dad's session: her requests only ever address her own link
    clients["mom"].delete("/api/notifications/whatsapp")
    assert WhatsAppLink.objects.filter(user=family["dad"]).exists()


# ------------------------------------------------------------------ AT-352 Discord: admin card counts, no webhook

def test_at352_discord_admin_card_and_masked_personal_state(family, clients):
    c = clients["dad"]
    cards = {p["key"]: p for p in c.get("/api/admin/connections").json()["providers"]}
    assert cards["discord"]["status"] == "disabled" and cards["discord"]["label"] == "Disabled by Admin"
    assert c.get("/api/notifications/discord").json()["available"] is False
    config.set_value("discord.enabled", True)
    with mock.patch("apps.notify.discord.requests.get") as g:
        g.return_value = mock.Mock(status_code=200, json=lambda: {"id": "1", "name": "Synthetic hook"})
        assert c.put("/api/notifications/discord", {"url": HOOK}, format="json").status_code == 200
    me = c.get("/api/notifications/discord").json()
    assert HOOK not in json.dumps(me) and me["webhook"]["hint"].endswith(HOOK[-4:]) or "…" in me["webhook"]["hint"]
    cards = {p["key"]: p for p in c.get("/api/admin/connections").json()["providers"]}
    assert cards["discord"]["people"] == 1 and HOOK not in json.dumps(cards)
    assert HOOK not in DiscordWebhook.objects.get().url_enc


# ------------------------------------------------------------------ AT-353 routing shows why a chosen channel cannot deliver

def test_at353_routing_reports_disconnected_personal_channels(family, clients, bridge):
    config.set_value("whatsapp.enabled", True)
    prefs = clients["dad"].get("/api/me/notification-preferences").json()
    wa = next(ch for ch in prefs["channels"] if ch["channel"] == "whatsapp")
    assert wa["configured"] and wa["issue"] == "WhatsApp is not linked."
