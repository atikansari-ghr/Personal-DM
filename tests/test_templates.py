"""Optional folder templates for new members."""
import pytest
from conftest import personal_root, setup_payload

from apps.accounts import services as S
from apps.core import config
from apps.library.models import Folder

pytestmark = pytest.mark.django_db


def _names(root):
    out = set()
    stack = [(root, "")]
    while stack:
        node, prefix = stack.pop()
        for child in Folder.objects.filter(parent=node):
            path = f"{prefix}{child.name}"
            out.add(path)
            stack.append((child, path + "/"))
    return out


def test_template_not_applied_unless_chosen(family):
    assert _names(personal_root(family["son1"])) == set()


def test_setup_can_apply_template_to_everyone(db):
    from django.core.management import call_command
    import io

    call_command("seed_defaults", stdout=io.StringIO())
    S.complete_setup(setup_payload(apply_template=True))
    from apps.accounts.models import User

    names = _names(personal_root(User.objects.get(username="son3")))
    assert {"Identity", "Identity/Passport", "Education", "Medical", "Travel"} <= names
    passport = Folder.objects.get(name="Passport", owner__username="son3")
    assert passport.emoji == "🛂"  # normal emoji suggestions apply


def test_add_member_with_template_and_apply_is_idempotent(family, clients):
    config.set_value("documents.member_template", "Identity/Passport\nSchool/Grades\nIdentity")
    r = clients["dad"].post("/api/family/members", {"username": "grandpa", "display_name": "Grandpa Sample", "apply_template": True}, format="json")
    assert r.status_code == 201, r.content
    root = Folder.objects.get(owner__username="grandpa", kind="personal_root")
    assert _names(root) == {"Identity", "Identity/Passport", "School", "School/Grades"}
    custom = Folder.objects.create(parent=root, name="My own folder", owner=root.owner)
    r = clients["dad"].post(f"/api/folders/{root.id}/apply-template")
    assert r.json()["created"] == 0
    assert Folder.objects.filter(pk=custom.pk).exists()  # nothing removed


def test_apply_template_requires_organise_permission(family, clients):
    root_son2 = personal_root(family["son2"])
    assert clients["son1"].post(f"/api/folders/{root_son2.id}/apply-template").status_code == 404
    r = clients["son1"].post(f"/api/folders/{personal_root(family['son1']).id}/apply-template")
    assert r.status_code == 200 and r.json()["created"] > 0


def test_template_validation(family, clients):
    r = clients["dad"].put("/api/settings", {"values": {"documents.member_template": "a/b/c/d/e/f/g/h/i"}}, format="json")
    assert r.status_code == 400
    r = clients["dad"].put("/api/settings", {"values": {"documents.member_template": "../escape"}}, format="json")
    assert r.status_code == 400
