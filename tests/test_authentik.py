"""authentik external identity provider (Change Set M, AT-146..AT-148) against a local fake OIDC provider."""
from datetime import timedelta

import pytest
from conftest import PASSWORD, client_for
from django.utils import timezone
from fake_oidc import CLIENT_ID, CLIENT_SECRET, FakeOIDC
from rest_framework.test import APIClient

from apps.accounts import authentik
from apps.accounts.models import ExternalIdentity, User
from apps.core import config
from apps.core.models import AuditEvent
from apps.library.models import AccessRule, Document, Folder

pytestmark = pytest.mark.django_db


@pytest.fixture
def idp():
    fake = FakeOIDC()
    authentik._discovery_cache.clear()
    authentik._jwk_clients.clear()
    config.set_value("authentik.enabled", True)
    config.set_value("authentik.issuer", fake.issuer)
    config.set_value("authentik.client_id", CLIENT_ID)
    config.set_value("authentik.client_secret", CLIENT_SECRET)
    yield fake
    fake.server.shutdown()


def _sign_in(c, idp, claims, mode="login", **override):
    r = c.get("/api/auth/authentik/start", {"mode": mode})
    assert r.status_code == 302, r.content
    code, state = idp.authorize(r["Location"], claims, **override)
    return c.get("/api/auth/authentik/callback", {"code": code, "state": state})


def _login_local(username):
    c = APIClient()
    return c, c.post("/api/auth/login", {"username": username, "password": PASSWORD}, format="json")


AK_SON = {"sub": "ak-uuid-son1", "preferred_username": "son1-ak", "name": "Son1 (authentik)", "email": "son1@example.invalid",
          "groups": ["family"]}


def test_at146_authentik_login_button_and_local_fallback(family, idp):
    s = APIClient().get("/api/session").json()["authentik"]
    assert s == {"enabled": True, "label": "Sign in with authentik", "show_logo": True}
    config.set_value("authentik.button_label", "Family SSO")
    config.set_value("authentik.show_logo", False)
    assert APIClient().get("/api/session").json()["authentik"] == {"enabled": True, "label": "Family SSO", "show_logo": False}
    # link first (existing accounts only), then sign in with authentik
    son = client_for(family["son1"])
    r = _sign_in(son, idp, AK_SON, mode="link")
    assert r["Location"] == "/settings/account?tab=security&linked=authentik"
    anon = APIClient()
    r = _sign_in(anon, idp, AK_SON)
    assert r["Location"] == "/" and anon.get("/api/session").json()["user"]["username"] == "son1"
    start = anon.get("/api/auth/authentik/start")
    assert "code_challenge_method=S256" in start["Location"] and "scope=openid+profile+email" in start["Location"]
    # authentik down: the button fails safely and local sign-in still works for everyone
    idp.server.shutdown()
    authentik._discovery_cache.clear()
    assert "authentik_unavailable" in APIClient().get("/api/auth/authentik/start")["Location"]
    for user in ("dad", "son1"):
        assert _login_local(user)[1].status_code == 200
    # tampered or foreign tokens are refused
    config.set_value("authentik.enabled", False)
    assert "authentik_disabled" in APIClient().get("/api/auth/authentik/start")["Location"]


def test_at146_token_checks(family, idp):
    ExternalIdentity.objects.create(user=family["son1"], issuer=idp.issuer.rstrip("/"), subject="ak-uuid-son1")
    assert "authentik_invalid" in _sign_in(APIClient(), idp, AK_SON, aud="other-client")["Location"]
    assert "authentik_invalid" in _sign_in(APIClient(), idp, AK_SON, iss="https://evil.example/")["Location"]
    assert "authentik_invalid" in _sign_in(APIClient(), idp, AK_SON, nonce="replayed")["Location"]
    c = APIClient()
    r = c.get("/api/auth/authentik/start")
    code, _state = idp.authorize(r["Location"], AK_SON)
    assert "authentik_state" in c.get("/api/auth/authentik/callback", {"code": code, "state": "forged"})["Location"]
    # TOTP on the account is still required after authentik
    User.objects.filter(pk=family["son1"].pk).update(totp_enabled=True)
    anon = APIClient()
    assert "step=totp" in _sign_in(anon, idp, AK_SON)["Location"]
    assert anon.get("/api/dashboard").status_code in (401, 403)
    assert AuditEvent.objects.filter(action="auth.authentik", outcome="failure").count() >= 4


def test_at147_email_match_never_links_and_links_are_explicit(family, idp):
    dad = family["dad"]
    User.objects.filter(pk=dad.pk).update(email="admin@example.invalid")
    r = _sign_in(APIClient(), idp, {"sub": "attacker", "email": "admin@example.invalid", "preferred_username": "admin"})
    assert "authentik_unlinked" in r["Location"]
    assert not ExternalIdentity.objects.exists()
    # linking needs a recent local verification
    son = client_for(family["son1"])
    s = son.session
    s["reauth_at"] = (timezone.now() - timedelta(hours=2)).isoformat()
    s.save()
    assert "reauth_required" in son.get("/api/auth/authentik/start", {"mode": "link"})["Location"]
    son = client_for(family["son1"])
    _sign_in(son, idp, AK_SON, mode="link")
    assert son.get("/api/me/authentik").json()["linked"] is True
    # the same authentik identity cannot be linked to a second account
    mom = client_for(family["mom"])
    assert "authentik_already_linked" in _sign_in(mom, idp, AK_SON, mode="link")["Location"]
    # the main administrator sees and revokes links; the account and its documents stay
    links = client_for(dad).get("/api/auth/authentik/links").json()["links"]
    assert len(links) == 1 and links[0]["user"]["display_name"] == family["son1"].display_name
    assert son.get("/api/auth/authentik/links").status_code == 403
    docs_before = Document.objects.filter(owner=family["son1"]).count()
    assert client_for(dad).delete(f"/api/auth/authentik/links/{links[0]['id']}").status_code == 204
    assert User.objects.filter(pk=family["son1"].pk, is_active=True).exists()
    assert Document.objects.filter(owner=family["son1"]).count() == docs_before
    assert "authentik_unlinked" in _sign_in(APIClient(), idp, AK_SON)["Location"]
    assert _login_local("son1")[1].status_code == 200


def test_at148_provisioning_and_group_mapping(family, idp):
    assert config.get("authentik.provisioning") == "existing_only"
    new = {"sub": "ak-new", "preferred_username": "Guest.User", "name": "Guest User", "email": "guest@example.invalid",
           "groups": ["pdm-admins"]}
    assert "authentik_unlinked" in _sign_in(APIClient(), idp, new)["Location"]
    config.set_value("authentik.provisioning", "auto")
    anon = APIClient()
    assert _sign_in(anon, idp, new)["Location"] == "/"
    u = User.objects.get(username="guest.user")
    assert u.display_name == "Guest User" and not u.is_main_admin and not u.is_admin and not u.has_usable_password()
    assert Folder.objects.filter(owner=u, kind=Folder.PERSONAL_ROOT).exists()
    assert ExternalIdentity.objects.get(user=u).provisioned
    # group mapping is off by default; then maps only to member/administrator
    assert config.get("authentik.group_mapping_enabled") is False
    from apps.core.registry import SettingError

    with pytest.raises(SettingError):
        config.set_value("authentik.group_mapping", {"pdm-admins": "main_admin"})
    config.set_value("authentik.group_mapping", {"pdm-admins": "administrator", "family": "member"})
    config.set_value("authentik.group_mapping_enabled", True)
    _sign_in(APIClient(), idp, new)
    u.refresh_from_db()
    assert u.is_admin and not u.is_main_admin
    assert AuditEvent.objects.filter(action="family.role_change", context__source="authentik_group_mapping").exists()
    _sign_in(APIClient(), idp, {**new, "groups": ["family"]})
    u.refresh_from_db()
    assert not u.is_admin
    # groups never grant document/folder access
    assert not AccessRule.objects.filter(user=u).exclude(folder__owner=u).exists()
    # the main administrator is never demoted or promoted by mapping
    dad = family["dad"]
    _sign_in(client_for(dad), idp, {"sub": "ak-dad", "preferred_username": "admin", "groups": ["family"]}, mode="link")
    _sign_in(APIClient(), idp, {"sub": "ak-dad", "preferred_username": "admin", "groups": ["family"]})
    dad.refresh_from_db()
    assert dad.is_main_admin
    # automatic provisioning never creates a second main administrator
    assert User.objects.filter(is_main_admin=True).count() == 1


def test_authentik_connection_test(family, idp):
    r = client_for(family["dad"]).post("/api/auth/authentik/test").json()
    checks = {c["name"]: c["ok"] for c in r["checks"]}
    assert checks["Discovery document valid and issuer matches"] and checks["Signing keys (JWKS) reachable from the server"]
    assert r["callback_url"].endswith("/api/auth/authentik/callback")
    assert client_for(family["son1"]).post("/api/auth/authentik/test").status_code == 403
    config.set_value("authentik.issuer", "http://203.0.113.5/application/o/x/")  # plain HTTP outside loopback
    r = client_for(family["dad"]).post("/api/auth/authentik/test").json()
    assert not {c["name"]: c["ok"] for c in r["checks"]}["Discovery document valid and issuer matches"]
