"""Opt-in plain-HTTP access from the home network (PD_LOCAL_ORIGINS)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from rest_framework.test import APIClient

from conftest import PASSWORD

LAN = "192.168.10.195:8000"


@pytest.fixture
def lan_settings(settings):
    settings.SESSION_COOKIE_SECURE = settings.CSRF_COOKIE_SECURE = True  # as with an https:// public origin
    settings.ALLOWED_HOSTS = ["docs.example.com", "192.168.10.195", "testserver"]
    settings.CSRF_TRUSTED_ORIGINS = ["https://docs.example.com", f"http://{LAN}"]
    settings.LOCAL_HOSTS = {LAN}
    return settings


def _login(host, secure=False):
    c = APIClient(HTTP_HOST=host)
    r = c.post("/api/auth/login", {"username": "dad", "password": PASSWORD}, format="json", secure=secure)
    assert r.status_code == 200, r.content
    return c, r


def test_lan_address_gets_cookies_the_browser_keeps(family, lan_settings):
    c, r = _login(LAN)
    assert r.cookies["pd_session"]["secure"] == ""
    assert "Cross-Origin-Opener-Policy" not in r
    assert c.get("/api/me", HTTP_HOST=LAN).status_code == 200  # the session works on the LAN address


def test_public_https_address_keeps_secure_cookies(family, lan_settings):
    _, r = _login("docs.example.com", secure=True)
    assert r.cookies["pd_session"]["secure"] is True
    assert r["Cross-Origin-Opener-Policy"] == "same-origin"


def test_other_hosts_are_not_relaxed(family, lan_settings):
    lan_settings.ALLOWED_HOSTS.append("192.168.10.196")
    _, r = _login("192.168.10.196:8000")
    assert r.cookies["pd_session"]["secure"] is True


def test_setting_parses_origins_and_ignores_junk():
    backend = Path(__file__).resolve().parents[1] / "backend"
    env = {**os.environ, "PD_TESTING": "1", "PD_ALLOWED_HOSTS": "docs.example.com",
           "PD_PUBLIC_ORIGIN": "https://docs.example.com",
           "PD_LOCAL_ORIGINS": "http://192.168.10.195:8000/, not-a-url, ftp://x"}
    code = ("import json, personaldocs.settings as s; "
            "print(json.dumps([s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS, sorted(s.LOCAL_HOSTS), s.SESSION_COOKIE_SECURE]))")
    out = subprocess.run([sys.executable, "-c", code], cwd=backend, env=env, capture_output=True, text=True, check=True)
    hosts, csrf, local, secure = json.loads(out.stdout.strip().splitlines()[-1])
    assert hosts == ["docs.example.com", "192.168.10.195"]
    assert csrf == ["https://docs.example.com", "http://192.168.10.195:8000"]
    assert local == [LAN] and secure is True
