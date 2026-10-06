"""Overview widgets, Hijri date, holidays, weather and sign-in designs (Change Set K, AT-116..AT-130)."""
import io
import json
import threading
from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import pytest
from conftest import PASSWORD, client_for
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone as dj_tz
from PIL import Image
from rest_framework.test import APIClient

from apps.core import config, overview
from apps.core.models import HolidayOverride, WeatherCache

pytestmark = pytest.mark.django_db


class FakeWeather:
    """Open-Meteo-shaped forecast and geocoding answers on 127.0.0.1; `fail` makes every request answer HTTP 503."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                from urllib.parse import parse_qs, urlparse

                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                fake.calls.append((u.path, q))
                if fake.fail:
                    self.send_response(503)
                    self.end_headers()
                    return
                if u.path == "/search":
                    body = {"results": [{"name": "Riyadh", "country": "Saudi Arabia", "country_code": "SA", "admin1": "Riyadh Region",
                                         "latitude": 24.6877, "longitude": 46.7219, "timezone": "Asia/Riyadh"},
                                        {"name": "Hyderabad", "country": "India", "country_code": "IN", "latitude": 17.38,
                                         "longitude": 78.46, "timezone": "Asia/Kolkata"}]}
                else:
                    days = [(date(2026, 6, 10) + timedelta(days=i)).isoformat() for i in range(5)]
                    body = {"current": {"temperature_2m": 41.3, "weather_code": 0, "relative_humidity_2m": 9, "wind_speed_10m": 14},
                            "daily": {"time": days, "weather_code": [0, 1, 2, 3, 61], "temperature_2m_max": [42, 43, 41, 40, 38],
                                      "temperature_2m_min": [29, 30, 28, 27, 26]}}
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return H


@pytest.fixture
def weather():
    fake = FakeWeather()
    config.set_value("weather.enabled", True)
    config.set_value("weather.base_url", f"{fake.url}/forecast")
    config.set_value("weather.geocoding_url", f"{fake.url}/search")
    yield fake
    fake.server.shutdown()


def _settings(c, **values):
    return c.put("/api/settings", {"values": values}, format="json")


# ---------------------------------------------------------------- widgets (AT-116..AT-119, AT-127)

def test_at116_widgets_have_labels_and_new_accounts_get_suggested_widgets(clients):
    r = clients["mom"].get("/api/session").json()
    assert r["preferences"]["dashboard_widgets"][:5] == ["date", "weather", "summary", "calendar", "holidays"]
    defs = {s["key"]: s for s in clients["mom"].get("/api/settings").json()["settings"]}
    labels = defs["me.dashboard_widgets"]["choice_labels"]
    assert labels["date"].startswith("Today") and labels["calendar"] == "Month calendar with holidays"
    assert all(labels[k] and labels[k] != k for k in defs["me.dashboard_widgets"]["choices"])  # never raw ids
    # disable some widgets: saved per account, other accounts unaffected
    assert _settings(clients["mom"], **{"me.dashboard_widgets": ["calendar", "date"]}).status_code == 200
    assert clients["mom"].get("/api/session").json()["preferences"]["dashboard_widgets"] == ["calendar", "date"]
    assert clients["son1"].get("/api/session").json()["preferences"]["dashboard_widgets"][0] == "date"
    assert _settings(clients["mom"], **{"me.dashboard_widgets": ["calendar", "nope"]}).status_code == 400


def test_at117_order_persists_across_devices(family):
    a, b = client_for(family["mom"]), client_for(family["mom"])  # two sessions = two devices
    order = ["holidays", "date", "recent", "weather"]
    assert _settings(a, **{"me.dashboard_widgets": order}).status_code == 200
    assert b.get("/api/session").json()["preferences"]["dashboard_widgets"] == order


def test_at118_at119_sizes_are_clamped_and_circles_only_for_simple_widgets(clients):
    layout = {"calendar": {"w": 9, "style": "circle"}, "date": {"w": 0, "style": "compact_circle", "settings": {"show_hijri": False}},
              "holidays": {"w": 3, "style": "compact_circle", "settings": {"count": 99, "countries": ["ae", "XX"]}},
              "weather": {"w": 2, "style": "circle"}}
    assert _settings(clients["mom"], **{"me.overview_layout": layout}).status_code == 200
    saved = clients["mom"].get("/api/session").json()["preferences"]["overview_layout"]
    assert saved["calendar"] == {"w": 2, "style": "rect"}  # calendar max is 2 columns; lists never become circles
    assert saved["date"] == {"w": 1, "style": "compact_circle", "settings": {"show_hijri": False}}
    assert saved["holidays"] == {"w": 3, "style": "compact", "settings": {"count": 20, "countries": ["AE"]}}
    assert saved["weather"]["style"] == "circle"
    assert _settings(clients["mom"], **{"me.overview_layout": {"date": {"style": "hexagon"}}}).status_code == 400
    assert _settings(clients["mom"], **{"me.overview_layout": {"unknown": {}}}).status_code == 400
    limits = clients["mom"].get("/api/dashboard").json()["layout_limits"]
    for wid, lim in limits.items():  # a 4-column grid: nothing can be wider than the grid
        assert 1 <= lim["min"] <= lim["default"] <= lim["max"] <= 4, wid
    assert limits["calendar"]["circle"] is False and limits["date"]["circle"] is True


def test_at127_dashboard_carries_every_widgets_data(clients):
    d = clients["mom"].get("/api/dashboard").json()
    for key in ("today", "holidays", "holiday_countries", "shared", "activity", "weather_enabled", "layout_limits"):
        assert key in d
    assert d["weather_enabled"] is False and "shared" in d["stats"]


# ---------------------------------------------------------------- date (AT-120)

def test_at120_gregorian_and_hijri_in_the_configured_timezone(clients):
    config.set_value("general.timezone", "Asia/Riyadh")
    # 21:30 UTC on 9 June 2026 is already 10 June in Riyadh (UTC+3)
    with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 6, 9, 21, 30, tzinfo=dt_tz.utc)):
        t = clients["mom"].get("/api/dashboard").json()["today"]
    assert t["date"] == "2026-06-10" and t["weekday"] == "Wednesday"
    assert t["hijri"]["day"] == 24 and t["hijri"]["month_name"] == "Dhu al-Hijjah" and t["hijri"]["year"] == 1447
    assert t["hijri"]["month_name_ar"] and t["hijri_calendar"] == "Umm al-Qura"
    config.set_value("general.timezone", "UTC")
    with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 6, 9, 21, 30, tzinfo=dt_tz.utc)):
        assert clients["mom"].get("/api/dashboard").json()["today"]["date"] == "2026-06-09"
    config.set_value("overview.hijri_adjust", 1)
    assert overview.hijri_of(date(2026, 6, 10))["day"] == 25
    assert _settings(clients["dad"], **{"overview.hijri_adjust": 5}).status_code == 400


# ---------------------------------------------------------------- calendar + holidays (AT-121..AT-124)

def test_at121_month_calendar_navigation_and_holiday_markers(clients):
    r = clients["mom"].get("/api/overview/calendar?month=2026-03").json()
    assert r["label"] == "March 2026" and len(r["days"]) == 31 and r["first_weekday"] == 6  # 1 March 2026 is a Sunday
    assert "Ramadan" in r["hijri_label"] and "Shawwal" in r["hijri_label"]
    marked = {d["date"]: d["holidays"] for d in r["days"] if d["holidays"]}
    assert any(h["name"] == "Holi" and h["country"] == "IN" for h in marked["2026-03-04"])
    assert any("Eid al-Fitr" in h["name"] and h["country"] == "SA" for hs in marked.values() for h in hs)
    assert clients["mom"].get("/api/overview/calendar?month=2026-13").status_code == 400
    assert clients["mom"].get("/api/overview/calendar?month=2026-04").json()["label"] == "April 2026"
    assert "today" in clients["mom"].get("/api/overview/calendar").json()


def test_at122_saudi_and_indian_holidays_with_source_and_status(clients):
    assert config.get("overview.holiday_countries") == ["SA", "IN"]
    rows = overview.holidays_between(date(2026, 1, 1), date(2026, 12, 31))
    sa = [h for h in rows if h["country"] == "SA"]
    india = [h for h in rows if h["country"] == "IN"]
    assert any(h["name"] == "National Day Holiday" and h["date"] == "2026-09-23" for h in sa)
    assert any(h["name"].startswith("Diwali") for h in india)
    founding = next(h for h in sa if h["name"].startswith("Founding Day"))
    assert founding["status"] == "confirmed" and founding["source"] == "holidays library"
    eid = next(h for h in sa if "Eid al-Fitr" in h["name"])
    assert eid["status"] == "provisional" and eid["calculated"]  # lunar dates wait for the announcement
    assert all(h["flag"] for h in rows)
    with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 3, 1, 9, 0, tzinfo=dt_tz.utc)):
        up = clients["mom"].get("/api/overview/holidays?count=4").json()["holidays"]
    assert len(up) == 4 and up[0]["date"] >= "2026-03-01" and "days_away" in up[0]
    run = next(h for h in up if "Eid al-Fitr Holiday" == h["name"])
    assert run.get("end") and run["end"] > run["date"]  # a multi-day holiday shows once


def test_at123_admin_adds_and_removes_countries_without_code_changes(clients):
    countries = clients["mom"].get("/api/overview/countries").json()
    assert len(countries["countries"]) > 150 and countries["selected"] == ["SA", "IN"]
    assert any(c["code"] == "AE" and c["name"] == "United Arab Emirates" for c in countries["countries"])
    assert _settings(clients["mom"], **{"overview.holiday_countries": ["AE"]}).status_code == 400  # members cannot
    assert _settings(clients["dad"], **{"overview.holiday_countries": ["SA", "IN", "ae"]}).status_code == 200
    assert config.get("overview.holiday_countries") == ["SA", "IN", "AE"]
    rows = overview.holidays_between(date(2026, 12, 1), date(2026, 12, 31))
    assert any(h["country"] == "AE" for h in rows)
    assert _settings(clients["dad"], **{"overview.holiday_countries": ["IN"]}).status_code == 200
    assert {h["country"] for h in overview.holidays_between(date(2026, 1, 1), date(2026, 12, 31))} == {"IN"}
    assert _settings(clients["dad"], **{"overview.holiday_countries": ["ZZ"]}).status_code == 400
    assert config.get("overview.holiday_countries") == ["IN"]  # a bad value never corrupts the saved list


def test_at124_holiday_corrections_override_without_touching_the_country_list(clients):
    admin, mom = clients["dad"], clients["mom"]
    assert mom.post("/api/overview/holiday-overrides", {"country": "SA", "date": "2026-03-20", "name": "x"}, format="json").status_code == 403
    r = admin.post("/api/overview/holiday-overrides", {"country": "SA", "date": "2026-03-20", "name": "Eid al-Fitr (announced)",
                                                        "status": "confirmed", "source": "Official announcement"}, format="json")
    assert r.status_code == 201, r.content
    oid = r.json()["id"]
    day = [h for h in overview.holidays_between(date(2026, 3, 20), date(2026, 3, 20)) if h["country"] == "SA"]
    assert day == [dict(day[0], name="Eid al-Fitr (announced)", status="confirmed", source="Official announcement")]
    assert admin.post("/api/overview/holiday-overrides", {"country": "SA", "date": "2026-03-20", "name": "dup"}, format="json").status_code == 400
    # hide a library holiday
    assert admin.post("/api/overview/holiday-overrides", {"country": "IN", "date": "2026-03-04", "hidden": True}, format="json").status_code == 201
    assert not [h for h in overview.holidays_between(date(2026, 3, 4), date(2026, 3, 4)) if h["country"] == "IN"]
    # add a holiday the library lacks
    assert admin.post("/api/overview/holiday-overrides", {"country": "IN", "date": "2026-07-01", "name": "Family day",
                                                          "status": "provisional"}, format="json").status_code == 201
    assert any(h["name"] == "Family day" and h["status"] == "provisional" for h in overview.holidays_between(date(2026, 7, 1), date(2026, 7, 1)))
    assert admin.post("/api/overview/holiday-overrides", {"country": "XX", "date": "2026-07-01", "name": "n"}, format="json").status_code == 400
    assert admin.patch(f"/api/overview/holiday-overrides/{oid}", {"status": "provisional"}, format="json").json()["status"] == "provisional"
    assert admin.delete(f"/api/overview/holiday-overrides/{oid}").status_code == 204
    assert config.get("overview.holiday_countries") == ["SA", "IN"]
    assert HolidayOverride.objects.count() == 2


# ---------------------------------------------------------------- weather (AT-125, AT-126)

def test_weather_is_off_by_default_and_never_contacts_a_provider(clients):
    assert config.get("weather.enabled") is False
    with mock.patch("requests.get") as get:
        assert clients["mom"].get("/api/overview/weather").json() == {"status": "disabled"}
        assert clients["mom"].get("/api/overview/weather/cities?q=Riyadh").status_code == 409
    get.assert_not_called()


def test_at125_city_choice_and_cached_conditions(clients, weather, family):
    mom = clients["mom"]
    assert mom.get("/api/overview/weather").json()["status"] == "no_city"
    cities = mom.get("/api/overview/weather/cities?q=Riy").json()["cities"]
    assert cities[0]["name"] == "Riyadh" and cities[0]["latitude"] == 24.6877
    r = mom.put("/api/overview/weather", {"city": cities[0]}, format="json").json()
    assert r["status"] == "ok" and r["temperature"] == 41.3 and r["unit"] == "°C" and len(r["days"]) == 5 and not r["stale"]
    assert r["label"] == "Clear sky" and r["days"][4]["icon"] == "rain"
    forecasts = [c for c in weather.calls if c[0] == "/forecast"]
    assert len(forecasts) == 1 and forecasts[0][1]["latitude"] == "24.6877"
    assert "Sample" not in json.dumps(weather.calls)  # only coordinates leave the server, never names
    mom.get("/api/overview/weather")
    mom.get("/api/overview/weather")
    assert len([c for c in weather.calls if c[0] == "/forecast"]) == 1  # served from the cache
    # another city for another member; the first member keeps theirs
    son = clients["son1"]
    assert son.put("/api/overview/weather", {"city": cities[1]}, format="json").json()["city"]["name"] == "Hyderabad"
    assert mom.get("/api/overview/weather").json()["city"]["name"] == "Riyadh"
    assert mom.put("/api/overview/weather", {"city": {"name": "x", "latitude": 200, "longitude": 0}}, format="json").status_code == 400
    # fahrenheit + API key are passed to the provider
    config.set_value("weather.units", "fahrenheit")
    config.set_value("weather.api_key", "test-key-not-real")
    assert mom.get("/api/overview/weather").json()["unit"] == "°F"
    assert weather.calls[-1][1]["temperature_unit"] == "fahrenheit" and weather.calls[-1][1]["apikey"] == "test-key-not-real"
    # administrator connection test
    assert clients["mom"].post("/api/overview/weather/test").status_code == 403
    t = clients["dad"].post("/api/overview/weather/test").json()
    assert t["ok"] and t["city"] == "Riyadh"
    # installation default city for people who chose none
    assert clients["dad"].put("/api/overview/weather/default-city", {"city": cities[1]}, format="json").status_code == 200
    assert clients["daughter"].get("/api/overview/weather").json()["city"]["name"] == "Hyderabad"


def test_at126_provider_failure_shows_stale_or_unavailable_and_overview_still_loads(clients, weather):
    mom = clients["mom"]
    city = mom.get("/api/overview/weather/cities?q=Riyadh").json()["cities"][0]
    mom.put("/api/overview/weather", {"city": city}, format="json")
    WeatherCache.objects.update(fetched_at=dj_tz.now() - timedelta(hours=2))  # older than the cache, younger than a day
    weather.fail = True
    r = mom.get("/api/overview/weather").json()
    assert r["status"] == "ok" and r["stale"] is True and r["temperature"] == 41.3 and "503" in r["error"]
    WeatherCache.objects.all().delete()
    r = mom.get("/api/overview/weather").json()
    assert r["status"] == "unavailable" and r["city"]["name"] == "Riyadh" and "503" in r["error"]
    assert mom.get("/api/dashboard").status_code == 200
    assert mom.get("/api/overview/weather/cities?q=Riyadh").status_code == 502
    assert clients["dad"].post("/api/overview/weather/test").status_code == 502
    config.set_value("weather.base_url", "http://127.0.0.1:9/forecast")  # nothing listens there
    weather.fail = False
    assert mom.get("/api/overview/weather").json()["status"] == "unavailable"


# ---------------------------------------------------------------- sign-in designs (AT-128..AT-130)

def _img(fmt="PNG", size=(1200, 800), exif=False):
    buf = io.BytesIO()
    im = Image.new("RGB", size, (200, 220, 230))
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretCam"  # Make
        im.save(buf, "JPEG", exif=ex.tobytes())
    else:
        im.save(buf, fmt)
    return buf.getvalue()


def _file(data, name="wall.png"):
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


@pytest.fixture
def data_dir(tmp_path, settings):
    settings.DATA_DIR = str(tmp_path)
    return tmp_path


def test_at128_presets_switch_without_changing_sign_in(clients, family):
    anon = APIClient()
    s = anon.get("/api/session").json()["login"]
    assert s["design"] == "minimal" and s["title"] == "Personal Documents Management System" and s["wallpaper"] is None
    for design in ("minimal", "nature", "travel", "family", "neutral"):
        assert _settings(clients["dad"], **{"login.design": design}).status_code == 200
        assert APIClient().get("/api/branding").json()["design"] == design
        c = APIClient()
        r = c.post("/api/auth/login", {"username": "mom", "password": PASSWORD}, format="json")
        assert r.status_code == 200 and c.get("/api/session").json()["user"]["username"] == "mom"
        bad = APIClient().post("/api/auth/login", {"username": "mom", "password": "wrong-password"}, format="json")
        assert bad.status_code in (400, 401)
    assert _settings(clients["mom"], **{"login.design": "travel"}).status_code == 400  # administrators only
    assert _settings(clients["dad"], **{"login.design": "spooky"}).status_code == 400
    assert _settings(clients["dad"], **{"login.title": "Ansari family documents", "login.tagline": ""}).status_code == 200
    b = APIClient().get("/api/branding").json()
    assert b["title"] == "Ansari family documents" and b["tagline"] == ""


def test_at129_custom_wallpaper_upload_configure_remove_and_rejections(clients, data_dir):
    admin = clients["dad"]
    assert clients["mom"].post("/api/branding/wallpaper", {"file": _file(_img())}, format="multipart").status_code == 403
    assert APIClient().post("/api/branding/wallpaper", {"file": _file(_img())}, format="multipart").status_code == 403
    for bad, why in [(b"%PDF-1.4 not an image", "not a supported image"), (_img("GIF"), "Only JPEG"),
                     (_img(size=(300, 200)), "at least 800"), (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "not a supported image")]:
        r = admin.post("/api/branding/wallpaper", {"file": _file(bad)}, format="multipart")
        assert r.status_code == 400 and why in r.json()["error"], r.content
    big = SimpleUploadedFile("big.png", b"0" * (11 * 1024 * 1024))
    assert admin.post("/api/branding/wallpaper", {"file": big}, format="multipart").status_code == 400
    r = admin.post("/api/branding/wallpaper", {"file": _file(_img("JPEG", (3000, 2000), exif=True), "w.jpg")}, format="multipart")
    assert r.status_code == 200, r.content
    b = r.json()
    assert b["design"] == "custom" and b["wallpaper"].startswith("/api/branding/wallpaper?v=")
    stored = list((data_dir / "branding").glob("wallpaper-*.webp"))
    assert len(stored) == 1
    with Image.open(stored[0]) as im:
        assert im.format == "WEBP" and max(im.size) == 2400 and not im.getexif()  # resized, metadata dropped
    assert b"SecretCam" not in stored[0].read_bytes()
    pub = APIClient().get("/api/branding/wallpaper")
    assert pub.status_code == 200 and pub["Content-Type"] == "image/webp" and pub["X-Content-Type-Options"] == "nosniff"
    assert _settings(admin, **{"login.overlay": 30, "login.position": "top"}).status_code == 200
    s = APIClient().get("/api/session").json()["login"]
    assert s["overlay"] == 30 and s["position"] == "top" and s["design"] == "custom"
    assert _settings(admin, **{"login.overlay": 95}).status_code == 400
    # replacing removes the old file
    admin.post("/api/branding/wallpaper", {"file": _file(_img())}, format="multipart")
    assert len(list((data_dir / "branding").glob("wallpaper-*.webp"))) == 1
    # logo keeps transparency, then removal
    logo = io.BytesIO()
    Image.new("RGBA", (300, 120), (0, 0, 0, 0)).save(logo, "PNG")
    assert admin.post("/api/branding/logo", {"file": _file(logo.getvalue(), "logo.png")}, format="multipart").json()["logo"]
    assert admin.delete("/api/branding/logo").json()["logo"] is None
    r = admin.delete("/api/branding/wallpaper").json()
    assert r["design"] == "minimal" and r["wallpaper"] is None and not r["has_wallpaper"]
    assert not list((data_dir / "branding").glob("wallpaper-*.webp"))
    assert APIClient().get("/api/branding/wallpaper").status_code == 404


def test_at130_sign_in_methods_are_offered_identically_with_every_design(clients):
    config.set_value("auth.allow_passkeys", True)
    config.set_value("auth.allow_totp", True)
    seen = set()
    for design in ("minimal", "nature", "travel", "family", "neutral"):
        config.set_value("login.design", design)
        s = APIClient().get("/api/session").json()
        seen.add((s["passkeys_enabled"], s["totp_allowed"], s["google_enabled"], s["passwordless_enabled"]))
    assert len(seen) == 1  # the design never changes which sign-in methods are available
