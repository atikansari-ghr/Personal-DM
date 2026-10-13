"""Change Set T - Trusted Zones, sign-in map, risk, recognised devices (AT-323 .. AT-331). Synthetic addresses only:
private ranges and the documentation/test networks of tests/mmdb_writer.py."""
import json
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import config
from apps.notify.models import Notification
from apps.security import geoip, location
from apps.security.models import LoginEvent, RecognizedDevice, TrustedZone

from conftest import PASSWORD, client_for
from mmdb_writer import build

pytestmark = pytest.mark.django_db
CITY_A = "5.42.0.7"     # synthetic "Riyadh-like" point
CITY_B = "23.0.0.9"     # synthetic far-away point
COUNTRY_ONLY = "14.96.0.3"


@pytest.fixture
def citydb(settings):
    geoip.geoip_dir().mkdir(parents=True, exist_ok=True)
    build({"5.42.0.0/24": ("SA", "Saudi Arabia", 24.7, 46.7, "Sample City A"),
           "23.0.0.0/24": ("US", "United States", 40.7, -74.0, "Sample City B"),
           "14.96.0.0/24": ("IN", "India")}, geoip.db_path())
    return geoip.db_path()


def login(ip, username="dad", cookie=None, ua="Mozilla/5.0 (X11; Linux x86_64) Chrome/130.0"):
    c = APIClient(REMOTE_ADDR=ip, HTTP_USER_AGENT=ua)
    if cookie:
        c.cookies["pd_device"] = cookie
    r = c.post("/api/auth/login", {"username": username, "password": PASSWORD}, format="json")
    assert r.status_code == 200, r.content
    return c, r.cookies.get("pd_device").value if r.cookies.get("pd_device") else cookie


def signed_in(c) -> bool:
    return c.get("/api/session").json().get("user") is not None


def home(name="Home", cidrs=("192.168.2.0/24",), pin=None):
    return TrustedZone.objects.create(name=name, cidrs=list(cidrs), pin_lat=pin[0] if pin else None, pin_lon=pin[1] if pin else None)


# ------------------------------------------------------------------ AT-323 .. AT-325 Trusted Zones

def test_at323_trusted_zone_replaces_unknown_country(family, citydb):
    home()
    login("192.168.2.10")
    e = LoginEvent.objects.get(result="success")
    assert (e.network, e.zone_name, e.location) == ("trusted_zone", "Home", "Home") and e.country == ""
    assert location.privacy_ip(e.ip, e.network) == "192.168.x.10"
    login("10.20.30.40")  # private, no zone: not "Unknown country"
    e2 = LoginEvent.objects.filter(result="success").order_by("-at").first()
    assert e2.network == "private" and e2.location == "Private network"


def test_at324_multiple_networks_validation_and_longest_prefix(family, clients):
    c = clients["dad"]
    r = c.post("/api/security/zones", {"name": "Home", "cidrs": "192.168.2.0/24\nfd00:1::/64\n10.8.0.0/16", "classification": "home"}, format="json")
    assert r.status_code == 201 and r.json()["cidrs"] == ["192.168.2.0/24", "fd00:1::/64", "10.8.0.0/16"]
    assert c.post("/api/security/zones", {"name": "VPN", "cidrs": ["10.8.5.0/24"], "classification": "vpn"}, format="json").status_code == 201
    for bad in (["192.168.2.300/24"], ["0.0.0.0/0"], []):
        assert c.post("/api/security/zones", {"name": "Bad", "cidrs": bad}, format="json").status_code == 400
    assert c.post("/api/security/zones/test", {"ip": "10.8.5.9"}, format="json").json()["zone"] == "VPN"  # most specific wins
    assert c.post("/api/security/zones/test", {"ip": "10.8.9.9"}, format="json").json()["zone"] == "Home"
    assert c.post("/api/security/zones/test", {"ip": "fd00:1::abcd"}, format="json").json()["zone"] == "Home"
    zid = r.json()["id"]
    assert c.put(f"/api/security/zones/{zid}", {"cidrs": ["192.168.3.0/24"]}, format="json").json()["cidrs"] == ["192.168.3.0/24"]
    assert clients["mom"].get("/api/security/zones").status_code == 403


def test_at325_configured_pin_is_never_called_geoip(family, clients, citydb):
    z = home(pin=(24.5, 46.5))
    login("192.168.2.11")
    e = LoginEvent.objects.get(result="success")
    assert (e.lat, e.lon, e.coord_source) == (24.5, 46.5, "zone_pin")
    m = clients["dad"].get("/api/security/map").json()
    ev = m["events"][0]
    assert ev["coord_label"] == "Configured Trusted Zone location" and "GeoIP" not in ev["coord_label"]
    assert m["zones"][0]["pin"]["source"] == "configured Trusted Zone location"
    assert z.pk


# ------------------------------------------------------------------ AT-326 GeoIP privacy

def test_at326_public_location_is_local_and_nothing_is_sent_out(family, clients, citydb):
    with mock.patch("requests.sessions.Session.request", side_effect=AssertionError("no outbound request allowed")), \
            mock.patch("urllib.request.urlopen", side_effect=AssertionError("no outbound request allowed")):
        login(CITY_A)
        login(COUNTRY_ONLY)
    a, b = LoginEvent.objects.filter(result="success").order_by("at")
    assert a.coord_source == "geoip_city" and "(approximate)" in a.location and a.lat == pytest.approx(24.7)
    assert b.coord_source == "geoip_country" and b.country == "IN"
    m = clients["dad"].get("/api/security/map").json()["map"]
    assert (m["style_url"] or m["tile_url"]).startswith("https://") and "never" in m["privacy"]
    r = clients["dad"].get("/api/security/map")
    assert "tile.openstreetmap.org" in r["Content-Security-Policy"]


# ------------------------------------------------------------------ AT-327 map authorisation

def test_at327_map_scope_own_delegate_main_admin(family, clients, citydb):
    login(CITY_A, "mom")
    login(CITY_A, "son1")
    mom = clients["mom"].get("/api/security/map").json()
    assert {e["user"] for e in mom["events"]} == {"Maria Sample"} and mom["people"] == []
    assert clients["mom"].get(f"/api/security/map?user={family['son1'].pk}").status_code == 403
    assert clients["mom"].get("/api/security/map?user=all").json()["events"][0]["user"] == "Maria Sample"
    # a delegate with the membership scope of a group sees that group's members
    from apps.accounts.models import Delegation, FamilyGroup, GroupMembership

    g = FamilyGroup.objects.create(name="Synthetic kids")
    GroupMembership.objects.create(group=g, user=family["son1"])
    Delegation.objects.create(delegate=family["mom"], group=g, scopes=["membership"])
    r = clients["mom"].get(f"/api/security/map?user={family['son1'].pk}")
    assert r.status_code == 200 and {e["user"] for e in r.json()["events"]} == {"Sam Sample"}
    admin = clients["dad"].get("/api/security/map?user=all").json()
    assert {"Maria Sample", "Sam Sample"} <= {e["user"] for e in admin["events"]}
    assert clients["son2"].get(f"/api/security/map?user={family['mom'].pk}").status_code == 403


# ------------------------------------------------------------------ AT-328 risk

def test_at328_explainable_risk_and_no_blocking(family, citydb):
    home()
    _, cookie = login("192.168.2.10")  # first sign-in: new device at home
    e1 = LoginEvent.objects.filter(result="success").order_by("-at").first()
    assert e1.risk == "low" and any("New or unrecognised device" in r for r in e1.risk_reasons)
    login("192.168.2.10", cookie=cookie)  # known device at home
    e2 = LoginEvent.objects.filter(result="success").order_by("-at").first()
    assert e2.risk == "normal" and "Recognised device" in e2.risk_reasons
    login("10.20.0.7")  # a new device on a private network that is not a Trusted Zone: low, not warning
    e2b = LoginEvent.objects.filter(result="success").order_by("-at").first()
    assert e2b.risk == "low" and any("private network" in r for r in e2b.risk_reasons)
    login(CITY_A, cookie=cookie)  # known device, public city A (first public sign-in: new country)
    e3 = LoginEvent.objects.filter(result="success").order_by("-at").first()
    assert e3.risk == "warning" and any("GeoIP, approximate" in r for r in e3.risk_reasons)
    login(CITY_A, cookie=cookie)
    assert LoginEvent.objects.filter(result="success").order_by("-at").first().risk == "normal"
    # impossible travel: city B minutes later -> high, still signed in (not blocked)
    c, _ = login(CITY_B, cookie=cookie)
    e5 = LoginEvent.objects.filter(result="success").order_by("-at").first()
    assert e5.risk == "high" and any("Unusual travel" in r for r in e5.risk_reasons)
    assert signed_in(c)
    n = Notification.objects.filter(event="security.risky_signin", user=family["dad"]).first()
    assert n is not None and CITY_B not in n.body  # routine notifications minimise the public address


# ------------------------------------------------------------------ AT-329 devices, AT-330 Mark Unrecognized

def test_at329_at330_devices_and_mark_unrecognized(family, citydb):
    c1, cookie1 = login("192.168.2.10", "mom")
    c2, cookie2 = login("192.168.2.20", "mom", ua="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1")
    devs = c1.get("/api/security/devices").json()["devices"]
    assert len(devs) == 2 and sum(d["current"] for d in devs) == 1
    phone = next(d for d in devs if d["os"] == "iOS")
    assert client_for(family["son1"]).post(f"/api/security/devices/{phone['id']}/unrecognize").status_code == 404
    r = c1.post(f"/api/security/devices/{phone['id']}/unrecognize")
    assert r.status_code == 200 and r.json()["sessions_ended"] == 1
    keys = {s["key"] for s in r.json()["next_steps"]}
    assert keys == {"sign_out_others", "change_password", "passkeys", "linked", "activity"}  # offered, not executed
    assert not signed_in(c2)  # the phone's session ended
    assert signed_in(c1)  # this device and the password are untouched
    d = RecognizedDevice.objects.get(pk=phone["id"])
    assert d.status == "unrecognized" and d.revoked_at
    from apps.core.models import AuditEvent

    assert AuditEvent.objects.filter(action="security.device_unrecognized").exists()
    assert Notification.objects.filter(event="security.device_unrecognized", user=family["mom"]).exists()
    # the unrecognised cookie is never trusted again: next sign-in is a new device
    login("192.168.2.20", "mom", cookie=cookie2)
    assert RecognizedDevice.objects.filter(user=family["mom"], revoked_at__isnull=True).count() == 2


# ------------------------------------------------------------------ AT-331 retention

def test_at331_one_year_retention_keeps_current_security_state(family, citydb):
    from apps.security import jobs

    c, cookie = login("192.168.2.10")
    old = LoginEvent.objects.create(user=family["dad"], result="success", ip="192.168.2.10", network="trusted_zone")
    LoginEvent.objects.filter(pk=old.pk).update(at=timezone.now() - timedelta(days=400))
    stale = RecognizedDevice.objects.create(user=family["dad"], token_hash="0" * 64, label="Old browser")
    RecognizedDevice.objects.filter(pk=stale.pk).update(last_seen=timezone.now() - timedelta(days=400))
    assert int(config.get("security.login_audit_retention_days")) == 365
    jobs.retention()
    assert not LoginEvent.objects.filter(pk=old.pk).exists() and not RecognizedDevice.objects.filter(pk=stale.pk).exists()
    assert LoginEvent.objects.filter(result="success").exists()
    assert RecognizedDevice.objects.filter(user=family["dad"]).count() == 1
    assert signed_in(c)


def test_zone_secrets_and_ip_privacy_in_notifications(family, citydb):
    from apps.security.alerts import _login_facts

    home()
    login("192.168.2.10")
    e = LoginEvent.objects.get(result="success")
    facts = dict(_login_facts(e))
    assert facts["Network"] == "Home — Trusted Zone" and facts["IP address"] == "192.168.x.10" and facts["Location"] == "Home"
    login(CITY_A)
    e2 = LoginEvent.objects.filter(result="success").order_by("-at").first()
    assert CITY_A not in json.dumps(_login_facts(e2))
