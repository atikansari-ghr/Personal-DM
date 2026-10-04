"""Per-device sessions: list, revoke one device, sign out others, password reset ends devices."""
import pytest
from conftest import PASSWORD
from rest_framework.test import APIClient

from apps.accounts.models import UserSession
from apps.accounts.sessions import describe

pytestmark = pytest.mark.django_db

CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
SAFARI_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"


def _device(username, ua, ip):
    c = APIClient(HTTP_USER_AGENT=ua, REMOTE_ADDR=ip)
    assert c.post("/api/auth/login", {"username": username, "password": PASSWORD}, format="json").status_code == 200
    return c


def test_describe_user_agents():
    assert describe(CHROME_WIN) == "Chrome on Windows"
    assert describe(SAFARI_IOS) == "Safari on iOS"
    assert describe("") == "Browser on unknown system"


def test_list_and_revoke_one_device(family):
    laptop = _device("son1", CHROME_WIN, "10.0.0.5")
    phone = _device("son1", SAFARI_IOS, "10.0.0.6")
    _device("son2", CHROME_WIN, "10.0.0.7")  # another person's session is never listed
    listing = laptop.get("/api/me/sessions").json()["sessions"]
    assert {s["device"] for s in listing} == {"Chrome on Windows", "Safari on iOS"}
    assert [s["current"] for s in listing].count(True) == 1
    phone_id = next(s["id"] for s in listing if s["device"] == "Safari on iOS")
    current_id = next(s["id"] for s in listing if s["current"])
    assert laptop.delete(f"/api/me/sessions/{current_id}").status_code == 400  # use Sign out for this one
    assert laptop.delete(f"/api/me/sessions/{phone_id}").status_code == 204
    assert phone.get("/api/dashboard").status_code in (401, 403)  # revoked device is signed out
    assert laptop.get("/api/dashboard").status_code == 200
    assert len(laptop.get("/api/me/sessions").json()["sessions"]) == 1


def test_cannot_revoke_someone_elses_session(family):
    _device("son1", CHROME_WIN, "10.0.0.5")
    other = _device("son2", CHROME_WIN, "10.0.0.7")
    target = UserSession.objects.get(user=family["son1"])
    assert other.delete(f"/api/me/sessions/{target.id}").status_code == 404
    assert UserSession.objects.get(pk=target.pk).revoked_at is None


def test_sign_out_others_logout_and_password_reset(family):
    a = _device("son1", CHROME_WIN, "10.0.0.5")
    b = _device("son1", SAFARI_IOS, "10.0.0.6")
    assert a.post("/api/me/sessions/revoke").json()["revoked"] == 1
    assert b.get("/api/dashboard").status_code in (401, 403)
    assert a.get("/api/dashboard").status_code == 200
    a.post("/api/auth/logout")
    assert UserSession.objects.filter(user=family["son1"], ended_at__isnull=True, revoked_at__isnull=True).count() == 0
    c = _device("son1", CHROME_WIN, "10.0.0.5")
    from apps.accounts.services import set_password

    set_password(family["son1"], "Reset-By-Admin-77", temporary=True)
    assert c.get("/api/dashboard").status_code in (401, 403)
    assert not UserSession.objects.filter(user=family["son1"], revoked_at__isnull=True, ended_at__isnull=True).exists()


def test_changing_own_password_keeps_this_device_and_signs_out_others(family):
    a = _device("son1", CHROME_WIN, "10.0.0.5")
    b = _device("son1", SAFARI_IOS, "10.0.0.6")
    r = a.post("/api/auth/password/change", {"current_password": PASSWORD, "new_password": "Changed-Passw0rd-1"}, format="json")
    assert r.status_code == 200
    assert a.get("/api/dashboard").status_code == 200
    assert b.get("/api/dashboard").status_code in (401, 403)
    assert len(a.get("/api/me/sessions").json()["sessions"]) == 1
