"""AT-02, AT-03, AT-11 (permission side), AT-29 (object access)."""
import pytest
from conftest import client_for, personal_root, run_jobs, upload

from apps.accounts import services as AS
from apps.accounts.models import FamilyGroup, GroupMembership, User
from apps.library import permissions as P
from apps.library.models import AccessRule, Document, Folder

pytestmark = pytest.mark.django_db


def _doc(client, user, name="sample.pdf", **kw):
    r = upload(client, personal_root(user), name=name, **kw)
    assert r.status_code == 201, r.content
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


def _make_relative(dad, username, display, group):
    u = User.objects.create(username=username, display_name=display, reminder_group=group)
    GroupMembership.objects.create(group=group, user=u)
    AS.create_personal_root(actor=dad, user=u, library_root=AS.library_root())
    return u


def test_default_deny_and_owner_access(family, clients):
    doc = _doc(clients["son1"], family["son1"])
    run_jobs()
    assert clients["son1"].get(f"/api/documents/{doc.id}").status_code == 200
    for other in ("mom", "daughter", "son2"):
        assert clients[other].get(f"/api/documents/{doc.id}").status_code == 404
    assert clients["dad"].get(f"/api/documents/{doc.id}").status_code == 200  # main admin


def test_at03_every_route_respects_permissions(family, clients):
    doc = _doc(clients["son1"], family["son1"], content=None)
    run_jobs()
    paths = [f"/api/documents/{doc.id}", f"/api/documents/{doc.id}/file", f"/api/documents/{doc.id}/preview",
             f"/api/documents/{doc.id}/thumbnail", f"/api/documents/{doc.id}/text", f"/api/documents/{doc.id}/similar",
             f"/api/documents/{doc.id}/permissions", f"/api/documents/{doc.id}/shares",
             f"/api/documents/{doc.id}/fields/document_number/reveal"]
    for p in paths:
        assert clients["daughter"].get(p).status_code == 404, p
    # search, counts, autocomplete never reveal it
    r = clients["daughter"].get("/api/documents", {"q": "Sample"})
    assert r.json()["total"] == 0
    assert clients["daughter"].get("/api/search/autocomplete", {"q": "sam"}).json()["suggestions"] == []
    assert clients["daughter"].get("/api/dashboard").json()["stats"]["documents"] == 0
    # export plan only covers accessible documents
    assert clients["daughter"].get("/api/export/plan").json()["files"] == 0


def test_inheritance_document_exception_and_revocation(family, clients):
    son1, mom = family["son1"], family["mom"]
    root = personal_root(son1)
    identity = Folder.objects.create(parent=root, name="Identity", owner=son1)
    passport = Folder.objects.create(parent=identity, name="Passport", owner=son1)
    r = upload(clients["son1"], passport, name="pp.pdf")
    doc = Document.objects.get(pk=r.json()["documents"][0]["id"])
    # grant Mom view on Identity: inherited by Passport and the document
    r = clients["dad"].put(f"/api/folders/{identity.id}/permissions", {"user": str(mom.pk), "caps": ["view"]}, format="json")
    assert r.status_code == 200, r.content
    assert clients["mom"].get(f"/api/documents/{doc.id}").status_code == 200
    assert clients["mom"].get(f"/api/documents/{doc.id}/file", {"download": "1"}).status_code == 403  # view only
    why = clients["mom"].get(f"/api/documents/{doc.id}/permissions").json()["why"]
    assert any(w.get("inherited") for w in why)
    # break inheritance on the document: access disappears
    r = clients["dad"].patch(f"/api/documents/{doc.id}", {"inherit_permissions": False}, format="json")
    assert r.status_code == 200
    assert clients["mom"].get(f"/api/documents/{doc.id}").status_code == 404
    assert clients["son1"].get(f"/api/documents/{doc.id}").status_code == 404  # owner rule was inherited too
    # explicit document-level exception
    clients["dad"].put(f"/api/documents/{doc.id}/permissions", {"user": str(son1.pk), "caps": ["view", "download"]}, format="json")
    assert clients["son1"].get(f"/api/documents/{doc.id}").status_code == 200
    # revoke folder grant: stays revoked for Mom
    clients["dad"].put(f"/api/folders/{identity.id}/permissions", {"user": str(mom.pk), "caps": []}, format="json")
    assert not AccessRule.objects.filter(folder=identity, user=mom).exists()


def test_folder_move_changes_access_and_requires_manage(family, clients):
    son1, son2 = family["son1"], family["son2"]
    shared = Folder.objects.get(name="Shared family")
    sub = Folder.objects.create(parent=personal_root(son1), name="Trip", owner=son1)
    upload(clients["son1"], sub, name="ticket.pdf")
    # son1 lacks MANAGE on his root (owner default) so cannot move a folder with inherited access
    r = clients["son1"].patch(f"/api/folders/{sub.id}", {"parent": str(personal_root(son2).id)}, format="json")
    assert r.status_code in (403, 404)
    AccessRule.objects.create(folder=shared, user=son2, caps=P.VIEW)
    r = clients["dad"].patch(f"/api/folders/{sub.id}", {"parent": str(shared.id)}, format="json")
    assert r.status_code == 200
    ctx = P.AccessContext.build(son2)
    assert ctx.folder_caps(sub.id) & P.VIEW  # inherited from new parent
    assert not P.AccessContext.build(son1).folder_caps(sub.id) & P.VIEW  # left son1's subtree


def test_at02_extended_family_delegation_scope_and_no_escalation(family, clients):
    dad = family["dad"]
    grandparents = FamilyGroup.objects.create(name="Grandparents")
    uncle_family = FamilyGroup.objects.create(name="Uncle's family")
    gp = _make_relative(dad, "grandpa", "Grandpa Sample", grandparents)
    uncle = _make_relative(dad, "uncle", "Uncle Sample", uncle_family)
    cousin = _make_relative(dad, "cousin", "Cousin Sample", uncle_family)
    uncle_family.head = uncle
    uncle_family.save()
    # head of family is not a global administrator and gets no implicit access
    assert not P.AccessContext.build(uncle).folder_caps(personal_root(cousin).id)
    # delegate document management for uncle's family only
    r = clients["dad"].post("/api/family/delegations", {"group": str(uncle_family.pk), "delegate": str(uncle.pk),
                                                        "scopes": ["documents", "membership"]}, format="json")
    assert r.status_code == 200, r.content
    ctx = P.AccessContext.build(uncle)
    assert ctx.folder_caps(personal_root(cousin).id) & P.UPLOAD
    assert not ctx.folder_caps(personal_root(gp).id)  # no cross-group access
    assert not ctx.folder_caps(personal_root(family["son1"]).id)
    uc = client_for(uncle)
    # cannot grant beyond scope (no MANAGE without folder_permissions scope)
    r = uc.put(f"/api/folders/{personal_root(cousin).id}/permissions", {"user": str(gp.pk), "caps": ["view"]}, format="json")
    assert r.status_code == 403
    # with folder_permissions scope: can grant what they hold, never MANAGE itself
    clients["dad"].post("/api/family/delegations", {"group": str(uncle_family.pk), "delegate": str(uncle.pk),
                                                    "scopes": ["documents", "membership", "folder_permissions"]}, format="json")
    uc = client_for(uncle)
    r = uc.put(f"/api/folders/{personal_root(cousin).id}/permissions", {"user": str(gp.pk), "caps": ["view", "manage"]}, format="json")
    assert r.status_code == 403
    r = uc.put(f"/api/folders/{personal_root(cousin).id}/permissions", {"user": str(gp.pk), "caps": ["view", "archive"]}, format="json")
    assert r.status_code == 403  # archive not delegated
    r = uc.put(f"/api/folders/{personal_root(cousin).id}/permissions", {"user": str(gp.pk), "caps": ["view"]}, format="json")
    assert r.status_code == 200
    # delegate cannot create delegations
    r = uc.post("/api/family/delegations", {"group": str(uncle_family.pk), "delegate": str(cousin.pk), "scopes": ["documents"]}, format="json")
    assert r.status_code == 403
    # cannot manage other groups' membership
    r = uc.patch(f"/api/family/groups/{grandparents.pk}", {"add_member": str(cousin.pk)}, format="json")
    assert r.status_code == 403
    # membership escalation: a membership delegate (not a member) cannot add people to a group holding access they lack
    clients["dad"].post("/api/family/delegations", {"group": str(grandparents.pk), "delegate": str(uncle.pk),
                                                    "scopes": ["membership"]}, format="json")
    AccessRule.objects.create(folder=personal_root(family["son1"]), group=grandparents, caps=P.VIEW | P.DOWNLOAD)
    uc = client_for(uncle)
    r = uc.patch(f"/api/family/groups/{grandparents.pk}", {"add_member": str(cousin.pk)}, format="json")
    assert r.status_code == 403
    assert not GroupMembership.objects.filter(group=grandparents, user=cousin).exists()
    AccessRule.objects.filter(group=grandparents).delete()
    r = uc.patch(f"/api/family/groups/{grandparents.pk}", {"add_member": str(cousin.pk)}, format="json")
    assert r.status_code == 200


def test_cross_family_id_guessing_and_stale_permissions(family, clients):
    doc = _doc(clients["son2"], family["son2"])
    mom = family["mom"]
    AccessRule.objects.create(folder=personal_root(family["son2"]), user=mom, caps=P.VIEW)
    mc = client_for(mom)
    assert mc.get(f"/api/documents/{doc.id}").status_code == 200
    AccessRule.objects.filter(user=mom).delete()
    # a fresh request rebuilds the context: stale grant is gone immediately
    assert mc.get(f"/api/documents/{doc.id}").status_code == 404
    assert mc.get("/api/documents/00000000-0000-0000-0000-000000000000").status_code == 404
    assert mc.get("/api/documents/not-a-uuid").status_code == 404


def test_reminder_recipient_status_grants_no_access(family):
    """Dad is head (reminder recipient) for everyone; a non-admin head must not gain access via reminders."""
    from apps.notify.expiry import recipients_for

    g = FamilyGroup.objects.get(name="My family")
    g.head = family["mom"]
    g.save()
    root = personal_root(family["son3"])
    assert not P.AccessContext.build(family["mom"]).folder_caps(root.id)
    d = Document(owner=family["son3"], folder=root, title="x")
    assert family["mom"] in recipients_for(d)
