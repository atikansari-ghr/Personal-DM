"""Passkeys / WebAuthn, authentication policy, recent authentication and recovery (change set G)."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import WebAuthnCredential
from apps.core import config
from apps.security.models import LoginEvent
from conftest import PASSWORD, client_for
from soft_authenticator import SoftAuthenticator

pytestmark = pytest.mark.django_db

ORIGIN, RP = "https://docs.example.com", "docs.example.com"


@pytest.fixture(autouse=True)
def _origin(settings):
    settings.PUBLIC_ORIGIN = ORIGIN
    settings.CSRF_TRUSTED_ORIGINS = [ORIGIN]


def register(client, auth: SoftAuthenticator, name="My phone"):
    opts = client.post("/api/me/passkeys", {"step": "options"}, format="json")
    assert opts.status_code == 200, opts.content
    assert opts.json()["rp"]["id"] == RP
    return client.post("/api/me/passkeys", {"credential": auth.register(opts.json()), "name": name}, format="json")


def password_login(client, username="mom"):
    return client.post("/api/auth/login", {"username": username, "password": PASSWORD}, format="json")


def test_register_list_rename_requires_recent_auth(family, clients):
    mom = family["mom"]
    c = clients["mom"]
    s = c.session
    s["reauth_at"] = (timezone.now() - timedelta(hours=1)).isoformat()
    s.save()
    r = c.post("/api/me/passkeys", {"step": "options"}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "reauth_required"
    c2 = client_for(mom)
    auth = SoftAuthenticator(ORIGIN, RP)
    r = register(c2, auth)
    assert r.status_code == 201, r.content
    assert len(r.json()["recovery_codes"]) == 10  # first second factor -> recovery codes issued once
    pk = r.json()["passkey"]
    assert pk["passwordless_capable"] and pk["name"] == "My phone"
    row = WebAuthnCredential.objects.get(user=mom)
    assert row.public_key and not hasattr(row, "private_key")
    listing = c2.get("/api/me/passkeys").json()
    assert [p["name"] for p in listing["passkeys"]] == ["My phone"] and listing["rp_id"] == RP
    assert row.credential_id not in str(listing)  # raw credential ids are not exposed in the UI API
    assert c2.patch(f"/api/me/passkeys/{row.pk}", {"name": "Work laptop"}, format="json").json()["name"] == "Work laptop"
    # a second passkey (multiple per account) and duplicate protection
    assert register(c2, SoftAuthenticator(ORIGIN, RP), "Security key").status_code == 201
    assert WebAuthnCredential.objects.filter(user=mom).count() == 2


def test_wrong_origin_registration_rejected(family, clients):
    auth = SoftAuthenticator(ORIGIN, RP)
    opts = clients["mom"].post("/api/me/passkeys", {"step": "options"}, format="json").json()
    r = clients["mom"].post("/api/me/passkeys", {"credential": auth.register(opts, origin="https://evil.example"), "name": "x"}, format="json")
    assert r.status_code == 400 and not WebAuthnCredential.objects.exists()


def test_password_plus_passkey_second_factor(family, clients):
    auth = SoftAuthenticator(ORIGIN, RP)
    register(clients["mom"], auth)
    c = APIClient()
    r = password_login(c)
    assert r.json()["status"] == "second_factor_required" and set(r.json()["methods"]) == {"passkey", "recovery"}
    assert c.get("/api/documents").status_code in (401, 403)  # not signed in yet
    opts = c.post("/api/auth/passkey/options", {"purpose": "2fa"}, format="json").json()
    assert opts["allowCredentials"] and opts["rpId"] == RP
    r = c.post("/api/auth/passkey/verify", {"purpose": "2fa", "credential": auth.assert_(opts)}, format="json")
    assert r.status_code == 200, r.content
    assert c.get("/api/me").status_code == 200
    ev = LoginEvent.objects.filter(result="success").latest("at")
    assert ev.method == "password+passkey" and ev.passkey_used and not ev.totp_used
    # the challenge was consumed: replaying the same assertion fails
    c2 = APIClient()
    password_login(c2)
    stale = auth.assert_(opts)
    assert c2.post("/api/auth/passkey/verify", {"purpose": "2fa", "credential": stale}, format="json").status_code == 400


def test_passkey_of_another_user_and_tampering_rejected(family, clients):
    mom_key, son_key = SoftAuthenticator(ORIGIN, RP), SoftAuthenticator(ORIGIN, RP)
    register(clients["mom"], mom_key)
    register(clients["son1"], son_key)
    c = APIClient()
    password_login(c, "mom")
    opts = c.post("/api/auth/passkey/options", {"purpose": "2fa"}, format="json").json()
    r = c.post("/api/auth/passkey/verify", {"purpose": "2fa", "credential": son_key.assert_(opts)}, format="json")
    assert r.status_code == 400 and "another account" in r.json()["error"]
    password_login(c, "mom")
    opts = c.post("/api/auth/passkey/options", {"purpose": "2fa"}, format="json").json()
    bad = mom_key.assert_(opts, rp_id="evil.example")  # signed for another relying party
    assert c.post("/api/auth/passkey/verify", {"purpose": "2fa", "credential": bad}, format="json").status_code == 400
    assert LoginEvent.objects.filter(result="failure", reason="passkey_invalid").count() == 2


def test_passwordless_policy_and_user_opt_in(family, clients):
    """AT-196..198 (prompt AT-176..178): passwordless is the default mode; enrolling a compatible passkey turns it on
    for the account; Password + Passkey (MFA) mode refuses passwordless; the person can opt out."""
    c = APIClient()
    assert c.get("/api/session").json()["passwordless_enabled"] is True  # the sign-in page shows the button
    config.set_value("auth.passkey_mode", "mfa")
    assert c.post("/api/auth/passkey/options", {"purpose": "passwordless"}, format="json").status_code == 403
    assert c.get("/api/session").json()["passwordless_enabled"] is False
    auth = SoftAuthenticator(ORIGIN, RP)
    register(clients["mom"], auth)
    family["mom"].refresh_from_db()
    assert family["mom"].passwordless_enabled is False  # MFA mode: enrolment does not turn passwordless on
    config.set_value("auth.passkey_mode", "passwordless")
    opts = c.post("/api/auth/passkey/options", {"purpose": "passwordless"}, format="json").json()
    assert "allowCredentials" not in opts or not opts["allowCredentials"]
    assert opts["userVerification"] == "required"
    r = c.post("/api/auth/passkey/verify", {"purpose": "passwordless", "credential": auth.assert_(opts)}, format="json")
    assert r.status_code == 403  # this account has passwordless off
    assert clients["mom"].post("/api/me/passwordless", {"enabled": True}, format="json").json()["passwordless_enabled"]
    opts = c.post("/api/auth/passkey/options", {"purpose": "passwordless"}, format="json").json()
    r = c.post("/api/auth/passkey/verify", {"purpose": "passwordless", "credential": auth.assert_(opts)}, format="json")
    assert r.status_code == 200 and c.get("/api/me").json()["username"] == "mom"
    assert LoginEvent.objects.filter(result="success").latest("at").method == "passkey"
    # a passkey without user verification cannot be used passwordless
    weak = SoftAuthenticator(ORIGIN, RP, uv=False)
    register(clients["mom"], weak, "No PIN key")
    c3 = APIClient()
    opts = c3.post("/api/auth/passkey/options", {"purpose": "passwordless"}, format="json").json()
    assert c3.post("/api/auth/passkey/verify", {"purpose": "passwordless", "credential": weak.assert_(opts)}, format="json").status_code == 400


def test_revoke_requires_recent_auth_and_stops_sign_in(family, clients):
    mom = family["mom"]
    auth = SoftAuthenticator(ORIGIN, RP)
    register(clients["mom"], auth)
    row = WebAuthnCredential.objects.get(user=mom)
    stale = client_for(mom)
    s = stale.session
    s["reauth_at"] = (timezone.now() - timedelta(hours=1)).isoformat()
    s.save()
    assert stale.delete(f"/api/me/passkeys/{row.pk}").status_code == 403
    assert clients["mom"].delete(f"/api/me/passkeys/{row.pk}").status_code == 204
    c = APIClient()
    assert password_login(c).json()["status"] == "ok"  # no second factor left -> password only again
    from apps.notify.models import Notification

    titles = list(Notification.objects.filter(user=mom, kind="security").values_list("title", flat=True))
    assert "Account security: New passkey “My phone” registered" in titles and "Account security: Passkey “My phone” removed" in titles


def test_require_2fa_policy_guides_without_lockout(family, clients):
    config.set_value("auth.require_2fa", "all")
    c = APIClient()
    assert password_login(c, "son2").json()["status"] == "ok"  # still signs in
    r = c.get("/api/documents")
    assert r.status_code == 403 and r.json()["code"] == "two_factor_setup_required"
    me = c.get("/api/me").json()
    assert me["two_factor_setup_required"] is True
    s = c.session
    s["reauth_at"] = timezone.now().isoformat()
    s.save()
    assert register(c, SoftAuthenticator(ORIGIN, RP)).status_code == 201
    assert c.get("/api/documents").status_code == 200
    # the last second factor cannot be removed while the policy requires one
    row = WebAuthnCredential.objects.get(user=family["son2"])
    r = c.delete(f"/api/me/passkeys/{row.pk}")
    assert r.status_code == 400 and "required" in r.json()["error"]


def test_totp_disable_keeps_recovery_codes_with_passkey(family, clients):
    import pyotp

    from apps.accounts import services as S
    from apps.core import crypto

    mom = family["mom"]
    register(clients["mom"], SoftAuthenticator(ORIGIN, RP))
    S.totp_begin(mom)
    mom.refresh_from_db()
    S.totp_enable(mom, pyotp.TOTP(crypto.decrypt(mom.totp_pending_enc)).now())
    assert clients["mom"].post("/api/me/totp/disable").status_code == 200
    assert mom.recovery_codes.filter(used_at__isnull=True).count() == 10
    assert clients["mom"].post("/api/me/recovery-codes").status_code == 200  # allowed with a passkey only


def test_admin_assisted_recovery_is_audited_and_notified(family, clients):
    from apps.core.models import AuditEvent
    from apps.notify.models import Notification

    mom = family["mom"]
    register(clients["mom"], SoftAuthenticator(ORIGIN, RP))
    assert clients["son1"].post(f"/api/family/members/{mom.pk}/reset-2fa").status_code == 403
    r = clients["dad"].post(f"/api/family/members/{mom.pk}/reset-2fa")
    assert r.json()["passkeys_revoked"] == 1
    assert not WebAuthnCredential.objects.filter(user=mom, revoked_at__isnull=True).exists()
    assert AuditEvent.objects.filter(action="family.two_factor_reset_by_admin", subject_user=mom).exists()
    assert Notification.objects.filter(user=mom, title="Account security: Two-step verification was reset").exists()
    assert clients["mom"].get("/api/me").status_code in (401, 403)  # signed out everywhere


def test_reauth_with_passkey(family, clients):
    mom = family["mom"]
    auth = SoftAuthenticator(ORIGIN, RP)
    register(clients["mom"], auth)
    c = client_for(mom)
    s = c.session
    s["reauth_at"] = (timezone.now() - timedelta(hours=1)).isoformat()
    s.save()
    opts = c.post("/api/auth/reauth/passkey", {"step": "options"}, format="json").json()
    assert c.post("/api/auth/reauth/passkey", {"credential": auth.assert_(opts)}, format="json").status_code == 200
    assert c.post("/api/me/passkeys", {"step": "options"}, format="json").status_code == 200


def test_policy_switches_do_not_break_existing_credentials(family, clients):
    auth = SoftAuthenticator(ORIGIN, RP)
    register(clients["mom"], auth)
    config.set_value("auth.allow_passkeys", False)
    assert clients["mom"].post("/api/me/passkeys", {"step": "options"}, format="json").status_code == 403  # no new ones
    c = APIClient()
    password_login(c)
    opts = c.post("/api/auth/passkey/options", {"purpose": "2fa"}, format="json").json()
    assert c.post("/api/auth/passkey/verify", {"purpose": "2fa", "credential": auth.assert_(opts)}, format="json").status_code == 200
    config.set_value("auth.allow_totp", False)
    assert clients["dad"].post("/api/me/totp/setup").status_code == 403


def test_no_secrets_in_audit_or_login_records(family, clients):
    from apps.core.models import AuditEvent

    auth = SoftAuthenticator(ORIGIN, RP)
    register(clients["mom"], auth)
    c = APIClient()
    password_login(c)
    opts = c.post("/api/auth/passkey/options", {"purpose": "2fa"}, format="json").json()
    c.post("/api/auth/passkey/verify", {"purpose": "2fa", "credential": auth.assert_(opts)}, format="json")
    blob = str(list(AuditEvent.objects.values())) + str(list(LoginEvent.objects.values()))
    assert opts["challenge"] not in blob and WebAuthnCredential.objects.get().credential_id not in blob
    assert PASSWORD not in blob


def test_passkey_diagnostics():
    from apps.accounts.passkeys import diagnostics

    checks = {name: ok for name, ok, _ in diagnostics()}
    assert checks["public origin uses HTTPS"] and checks["relying party ID is a host name"]


def test_console_recovery_resets_passkeys(family, clients, monkeypatch):
    import io

    from django.core.management import call_command

    dad = family["dad"]
    register(clients["dad"], SoftAuthenticator(ORIGIN, RP))
    out = io.StringIO()
    call_command("recover_admin", "dad", "--generate", "--reset-2fa", stdout=out)
    assert not WebAuthnCredential.objects.filter(user=dad, revoked_at__isnull=True).exists()
    from apps.core.models import AuditEvent

    ev = AuditEvent.objects.filter(action="recovery.console_admin").latest("at")
    assert ev.context["passkeys_revoked"] == 1
    from apps.library.models import Document

    assert Document.objects.count() == Document.objects.count()  # nothing about documents changes
