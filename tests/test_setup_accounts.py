"""AT-01, AT-20 (part), last-admin protection, forced password change, login hardening."""
import pytest
from conftest import PASSWORD, client_for, setup_payload
from rest_framework.test import APIClient

from apps.accounts import services as S
from apps.accounts.models import FamilyGroup, SetupState, User
from apps.core.models import AuditEvent
from apps.library.models import AccessRule, Folder

pytestmark = pytest.mark.django_db


def test_at01_setup_creates_six_accounts_and_is_not_repeatable():
    token = S.new_setup_token()
    c = APIClient()
    assert c.post("/api/setup/verify", {"token": "wrong"}, format="json").status_code == 400
    assert c.post("/api/setup/verify", {"token": token}, format="json").status_code == 200
    payload = setup_payload(token=token)
    payload["members"][1]["password"] = ""
    payload["members"][1]["generate_password"] = True
    r = c.post("/api/setup/complete", payload, format="json")
    assert r.status_code == 200, r.content
    assert "mom" in r.json()["issued_passwords"]  # generated once for Dad to hand over
    assert User.objects.count() == 6
    dad = User.objects.get(username="dad")
    assert dad.is_main_admin and dad.display_name == "Alex Sample" and dad.role_label == "Dad"
    assert FamilyGroup.objects.get(name="My family").head == dad
    assert not dad.must_change_password
    assert User.objects.get(username="mom").must_change_password  # admin-issued temporary password
    assert Folder.objects.filter(kind=Folder.PERSONAL_ROOT).count() == 6
    assert AccessRule.objects.filter(folder__kind=Folder.PERSONAL_ROOT).count() == 6
    # rerun: refused, nothing duplicated
    r2 = c.post("/api/setup/complete", setup_payload(token=token), format="json")
    assert r2.status_code in (400, 403)
    with pytest.raises(S.AccountError):
        S.complete_setup(setup_payload())
    assert User.objects.count() == 6 and FamilyGroup.objects.count() == 1
    assert SetupState.get().token_hash == ""


def test_setup_requires_valid_token_and_rejects_weak_admin_password():
    S.new_setup_token()
    c = APIClient()
    assert c.post("/api/setup/complete", setup_payload(token="nope"), format="json").status_code == 403
    with pytest.raises(S.AccountError):
        payload = setup_payload()
        payload["members"][0]["password"] = "short"
        S.complete_setup(payload)
    assert User.objects.count() == 0  # atomic: no partial accounts


def test_setup_names_are_not_prefilled_or_guessed():
    with pytest.raises(S.AccountError):
        payload = setup_payload()
        payload["members"][0]["display_name"] = ""
        S.complete_setup(payload)


def test_last_main_admin_cannot_be_demoted_or_disabled(family, clients):
    dad = family["dad"]
    r = clients["dad"].patch(f"/api/family/members/{dad.pk}", {"is_main_admin": False}, format="json")
    assert r.status_code == 400
    r = clients["dad"].patch(f"/api/family/members/{dad.pk}", {"is_active": False}, format="json")
    assert r.status_code == 400
    # renaming Dad keeps the immutable id and admin status
    r = clients["dad"].patch(f"/api/family/members/{dad.pk}", {"display_name": "Alex S."}, format="json")
    assert r.status_code == 200
    dad.refresh_from_db()
    assert dad.is_main_admin and dad.display_name == "Alex S."


def test_forced_password_change_blocks_api_until_changed(family):
    mom = family["mom"]
    mom.must_change_password = True
    mom.save()
    c = client_for(mom)
    r = c.get("/api/dashboard")
    assert r.status_code == 403 and r.json().get("code") == "password_change_required"
    r = c.post("/api/auth/password/change", {"current_password": PASSWORD, "new_password": "Another-Sample-9"}, format="json")
    assert r.status_code == 200, r.content
    assert c.get("/api/dashboard").status_code == 200


def test_login_generic_errors_rate_limit_and_audit(family):
    c = APIClient()
    r = c.post("/api/auth/login", {"username": "dad", "password": "wrong"}, format="json")
    r2 = c.post("/api/auth/login", {"username": "nobody", "password": "wrong"}, format="json")
    assert r.status_code == r2.status_code == 400
    assert r.json()["error"] == r2.json()["error"]
    for _ in range(10):
        c.post("/api/auth/login", {"username": "son1", "password": "wrong"}, format="json")
    r = c.post("/api/auth/login", {"username": "son1", "password": PASSWORD}, format="json")
    assert r.status_code == 429
    ok = APIClient().post("/api/auth/login", {"username": "dad", "password": PASSWORD}, format="json")
    assert ok.status_code == 200
    assert AuditEvent.objects.filter(action="auth.login", outcome="failure").exists()
    assert AuditEvent.objects.filter(action="auth.login", outcome="success").exists()


def test_disabled_user_session_ends(family):
    son2 = family["son2"]
    c = client_for(son2)
    assert c.get("/api/dashboard").status_code == 200
    son2.is_active = False
    son2.save()
    assert c.get("/api/dashboard").status_code in (401, 403)


def test_regular_user_cannot_administer_family(family, clients):
    r = clients["son1"].post("/api/family/members", {"username": "x", "display_name": "X"}, format="json")
    assert r.status_code == 403
    r = clients["son1"].patch(f"/api/family/members/{family['son1'].pk}", {"is_main_admin": True}, format="json")
    assert r.status_code == 403
    r = clients["son1"].post("/api/family/delegations", {"group": "x", "delegate": "y", "scopes": ["documents"]}, format="json")
    assert r.status_code == 403
