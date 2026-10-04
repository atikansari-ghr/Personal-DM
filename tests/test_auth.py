"""AT-20, AT-21, AT-22: password reset, TOTP, recovery codes, console recovery, Google linking."""
import time
from datetime import timedelta
from io import StringIO
from unittest import mock

import jwt
import pyotp
import pytest
from conftest import PASSWORD, client_for
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import google
from apps.accounts.models import GoogleIdentity, PasswordResetToken
from apps.core import config, crypto
from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


def _login(username, password=PASSWORD):
    c = APIClient()
    return c, c.post("/api/auth/login", {"username": username, "password": password}, format="json")


def test_password_reset_single_use_and_expiring(family):
    config.set_value("smtp.enabled", True)
    config.set_value("smtp.host", "smtp.invalid")
    son1 = family["son1"]
    son1.email = "son1@example.invalid"
    son1.save()
    sent = {}
    with mock.patch("apps.notify.mailer.send_mail_now", side_effect=lambda to, s, b: sent.update(body=b)):
        r = APIClient().post("/api/auth/password/forgot", {"username": "son1"}, format="json")
        r2 = APIClient().post("/api/auth/password/forgot", {"username": "nobody"}, format="json")
    assert r.json() == r2.json()  # no account enumeration
    token = sent["body"].split("token=")[1].split()[0]
    c = APIClient()
    assert c.post("/api/auth/password/reset", {"token": token, "password": "Brand-New-Sample-1"}, format="json").status_code == 200
    assert c.post("/api/auth/password/reset", {"token": token, "password": "Other-New-Sample-2"}, format="json").status_code == 400
    assert _login("son1", "Brand-New-Sample-1")[1].status_code == 200
    # expired token
    raw = crypto.token_urlsafe(32)
    PasswordResetToken.objects.create(user=son1, token_hash=crypto.hash_token(raw), expires_at=timezone.now() - timedelta(seconds=1))
    assert APIClient().post("/api/auth/password/reset", {"token": raw, "password": "Another-Sample-3"}, format="json").status_code == 400
    assert "token" not in str(list(AuditEvent.objects.values_list("context", flat=True))).lower().replace("auth.reset", "")


def test_password_reset_invalidates_existing_sessions(family):
    son1 = family["son1"]
    c = client_for(son1)
    assert c.get("/api/dashboard").status_code == 200
    from apps.accounts.services import set_password

    set_password(son1, "Reset-By-Admin-77", temporary=True)
    assert c.get("/api/dashboard").status_code in (401, 403)


def test_totp_enrolment_login_and_recovery_codes(family):
    son1 = family["son1"]
    c = client_for(son1)
    secret = c.post("/api/me/totp/setup").json()["secret"]
    assert c.post("/api/me/totp/enable", {"code": "000000"}, format="json").status_code == 400
    codes = c.post("/api/me/totp/enable", {"code": pyotp.TOTP(secret).now()}, format="json").json()["recovery_codes"]
    assert len(codes) == 10
    c2, r = _login("son1")
    assert r.json()["status"] == "totp_required"
    assert c2.get("/api/dashboard").status_code in (401, 403)  # password alone is not enough
    assert c2.post("/api/auth/totp", {"code": "123456"}, format="json").status_code == 400
    assert c2.post("/api/auth/totp", {"code": pyotp.TOTP(secret).now()}, format="json").status_code == 200
    assert c2.get("/api/dashboard").status_code == 200
    # recovery code: one use only
    c3, _ = _login("son1")
    assert c3.post("/api/auth/totp", {"recovery_code": codes[0]}, format="json").status_code == 200
    c4, _ = _login("son1")
    assert c4.post("/api/auth/totp", {"recovery_code": codes[0]}, format="json").status_code == 400
    son1.refresh_from_db()
    assert son1.totp_secret_enc and secret not in son1.totp_secret_enc  # stored encrypted


def test_admin_resets_member_totp_and_temporary_password(family, clients):
    son2 = family["son2"]
    r = clients["dad"].post(f"/api/family/members/{son2.pk}/reset-password", {}, format="json")
    temp = r.json()["temporary_password"]
    c, r = _login("son2", temp)
    assert r.json()["must_change_password"] is True
    assert c.get("/api/dashboard").status_code == 403


def test_console_recovery_is_restricted_and_audited(family):
    with pytest.raises(Exception):
        call_command("recover_admin", "son1", "--generate", stdout=StringIO())  # not an administrator
    dad = family["dad"]
    dad.totp_enabled = True
    dad.save()
    c = client_for(dad)
    out = StringIO()
    call_command("recover_admin", "dad", "--generate", "--reset-totp", stdout=out)
    temp = out.getvalue().split("sign-in): ")[1].strip()
    dad.refresh_from_db()
    assert not dad.totp_enabled and dad.must_change_password
    assert c.get("/api/dashboard").status_code in (401, 403)  # old sessions invalidated
    assert _login("dad", temp)[1].status_code == 200
    ev = AuditEvent.objects.get(action="recovery.console_admin")
    assert temp not in str(ev.context)


# ------------------------------------------------------------------ Google (protocol tests with a local key pair)

CLIENT_ID = "synthetic-client.apps.googleusercontent.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeJwk:
    def get_signing_key_from_jwt(self, token):
        return mock.Mock(key=KEY.public_key())


def _id_token(**over):
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "g-sub-1", "email": "sam@example.invalid",
              "iat": now, "exp": now + 300, "nonce": "N"}
    claims.update(over)
    return jwt.encode(claims, KEY, algorithm="RS256")


@pytest.fixture
def google_on(monkeypatch):
    config.set_value("google.client_id", CLIENT_ID)
    config.set_value("google.client_secret", "synthetic-secret")
    config.set_value("google.enabled", True)
    monkeypatch.setattr(google, "jwk_client", lambda: _FakeJwk())


def _callback(client, token, mode="login", uid=None, state="S", nonce="N"):
    s = client.session
    s["google_oauth"] = {"state": "S", "nonce": nonce, "verifier": "v", "mode": mode, "uid": uid, "at": timezone.now().isoformat()}
    s.save()
    with mock.patch.object(google, "exchange_code", return_value={"id_token": token}):
        return client.get("/api/auth/google/callback", {"state": state, "code": "c"})


def test_at21_google_link_login_unlink(family, google_on):
    son1 = family["son1"]
    c = client_for(son1)
    r = c.get("/api/auth/google/start", {"mode": "link"})
    assert r.status_code == 302 and "code_challenge_method=S256" in r["Location"] and "scope=openid+email+profile" in r["Location"]
    r = _callback(c, _id_token(), mode="link", uid=str(son1.pk))
    assert "linked=1" in r["Location"]
    assert GoogleIdentity.objects.get(user=son1).subject == "g-sub-1"
    anon = APIClient()
    r = _callback(anon, _id_token())
    assert r["Location"] == "/"
    assert anon.get("/api/dashboard").status_code == 200
    # unlink requires recent verification and keeps local login
    s = c.session
    s["reauth_at"] = (timezone.now() - timedelta(hours=1)).isoformat()
    s.save()
    assert c.delete("/api/me/google").status_code == 403
    c.post("/api/auth/reauth", {"password": PASSWORD}, format="json")
    assert c.delete("/api/me/google").json()["linked"] is False
    assert _login("son1")[1].status_code == 200


def test_at21_unknown_google_identity_cannot_register(family, google_on):
    from apps.accounts.models import User

    r = _callback(APIClient(), _id_token(sub="stranger", email="dad@example.invalid"))
    assert "google_unlinked" in r["Location"]
    assert User.objects.count() == 6


def test_at22_google_failures_are_safe(family, google_on):
    son1, son2 = family["son1"], family["son2"]
    GoogleIdentity.objects.create(user=son1, issuer="https://accounts.google.com", subject="g-sub-1")
    assert "google_invalid" in _callback(APIClient(), _id_token(iss="https://evil.example"))["Location"]
    assert "google_invalid" in _callback(APIClient(), _id_token(aud="other-client"))["Location"]
    assert "google_invalid" in _callback(APIClient(), _id_token(nonce="other"))["Location"]
    assert "google_invalid" in _callback(APIClient(), _id_token(exp=int(time.time()) - 3600))["Location"]
    assert "google_state" in _callback(APIClient(), _id_token(), state="tampered")["Location"]
    # duplicate identity cannot be linked to a second account
    c2 = client_for(son2)
    r = _callback(c2, _id_token(), mode="link", uid=str(son2.pk))
    assert "google_already_linked" in r["Location"]
    # disabled user
    son1.is_active = False
    son1.save()
    assert "account_disabled" in _callback(APIClient(), _id_token())["Location"]
    son1.is_active = True
    son1.save()
    # app TOTP still required after Google sign-in
    son1.totp_enabled = True
    son1.save()
    anon = APIClient()
    r = _callback(anon, _id_token())
    assert "step=totp" in r["Location"] and anon.get("/api/dashboard").status_code in (401, 403)
    # disabled provider blocks new sign-ins
    config.set_value("google.enabled", False)
    assert "google_disabled" in _callback(APIClient(), _id_token())["Location"]
    assert "google_disabled" in APIClient().get("/api/auth/google/start")["Location"]


def test_google_link_requires_recent_verification(family, google_on):
    c = client_for(family["son1"])
    s = c.session
    s["reauth_at"] = (timezone.now() - timedelta(hours=2)).isoformat()
    s.save()
    r = c.get("/api/auth/google/start", {"mode": "link"})
    assert "reauth_required" in r["Location"]
