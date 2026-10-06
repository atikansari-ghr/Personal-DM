"""Family setup model (Change Set L): Main Administrator only by default, optional members (AT-131..AT-135, AT-137)."""
import pytest
from conftest import PASSWORD, client_for, upload
from rest_framework.test import APIClient

from apps.accounts import services as S
from apps.accounts.models import FamilyGroup, User
from apps.library.models import Document, Folder

pytestmark = pytest.mark.django_db

ADMIN = {"display_name": "A. Ansari", "username": "admin", "password": PASSWORD}


def _complete(members=(), **extra):
    token = S.new_setup_token()
    c = APIClient()
    assert c.post("/api/setup/verify", {"token": token}, format="json").status_code == 200
    r = c.post("/api/setup/complete", {"token": token, "admin": ADMIN, "members": list(members), **extra}, format="json")
    assert r.status_code == 200, r.content
    return r.json()


def test_at131_at137_clean_setup_creates_only_the_main_administrator():
    token = S.new_setup_token()
    r = APIClient().post("/api/setup/verify", {"token": token}, format="json").json()
    assert "slots" not in r and "Daughter" in r["relationships"]  # suggestions only, nothing pre-created
    _complete()
    assert User.objects.count() == 1
    admin = User.objects.get()
    assert admin.is_main_admin and admin.display_name == "A. Ansari" and not admin.must_change_password
    assert FamilyGroup.objects.get().head == admin
    assert Folder.objects.filter(kind=Folder.PERSONAL_ROOT).count() == 1
    # no placeholder accounts for the demo/screenshot labels
    assert not User.objects.filter(display_name__in=["Mom", "Son1", "Son2", "Son3", "Daughter"]).exists()
    assert not User.objects.filter(username__in=["dad", "mom", "son1", "son2", "son3", "daughter"]).exists()


def test_at132_optional_members_zero_one_or_many():
    r = _complete(members=[
        {"display_name": "Mom", "username": "mom", "role_label": "Mother", "generate_password": True},
        {"display_name": "Son1", "username": "son1", "role_label": "Son", "password": "Another-Passw0rd!"},
        {"display_name": "", "username": ""},  # an empty row left in the form is ignored, not guessed
    ])
    assert set(r["issued_passwords"]) == {"mom"}
    assert User.objects.count() == 3
    mom = User.objects.get(username="mom")
    assert mom.role_label == "Mother" and mom.must_change_password and not mom.is_main_admin
    assert Folder.objects.filter(kind=Folder.PERSONAL_ROOT).count() == 3


def test_at132_member_rows_are_validated():
    S.new_setup_token()
    with pytest.raises(S.AccountError):
        S.complete_setup({"admin": ADMIN, "members": [{"display_name": "Daughter", "username": "admin"}]})  # duplicate
    with pytest.raises(S.AccountError):
        S.complete_setup({"admin": ADMIN, "members": [{"display_name": "", "username": "kid"}]})  # name required
    with pytest.raises(S.AccountError):
        S.complete_setup({"members": []})  # the administrator is required
    assert User.objects.count() == 0  # atomic


def test_at133_members_can_be_added_later():
    _complete()
    admin = User.objects.get()
    c = client_for(admin)
    r = c.post("/api/family/members", {"display_name": "Daughter", "username": "daughter", "role_label": "Daughter"}, format="json")
    assert r.status_code == 201 and r.json()["temporary_password"]
    assert User.objects.count() == 2
    assert Folder.objects.filter(owner__username="daughter", kind=Folder.PERSONAL_ROOT).exists()


def test_at134_upgrade_keeps_earlier_six_slot_installations(family):
    """Installations created with the earlier fixed-slot wizard keep every account (nothing is cleaned up)."""
    assert User.objects.count() == 6
    assert User.objects.get(username="dad").is_main_admin
    from django.core.management import call_command

    call_command("migrate", verbosity=0)  # running migrations again (as an upgrade does) deletes nothing
    assert User.objects.count() == 6 and Folder.objects.filter(kind=Folder.PERSONAL_ROOT).count() == 6


def test_at135_deactivating_a_member_keeps_their_documents(family, clients):
    son1 = family["son1"]
    root = Folder.objects.get(owner=son1, kind=Folder.PERSONAL_ROOT)
    doc_id = upload(clients["son1"], root).json()["documents"][0]["id"]
    r = clients["dad"].patch(f"/api/family/members/{son1.id}", {"is_active": False}, format="json")
    assert r.status_code == 200
    son1.refresh_from_db()
    assert not son1.is_active
    doc = Document.objects.get(pk=doc_id)
    assert doc.owner_id == son1.id and doc.archived_at is None  # nothing deleted or archived
    assert clients["dad"].get(f"/api/documents/{doc_id}").status_code == 200  # still reachable by the administrator
    assert clients["dad"].delete(f"/api/family/members/{son1.id}").status_code == 405  # no hard delete of accounts
