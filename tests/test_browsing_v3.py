"""Folder browsing changes: document/folder actions, folder icons, view preferences, sorting and desktop drops
(AT-85..AT-92). Synthetic data only."""
from __future__ import annotations

import importlib

import pytest
from conftest import make_text_pdf, personal_root, upload
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models import AuditEvent
from apps.library import permissions as P
from apps.library.models import AccessRule, Document, Folder

pytestmark = pytest.mark.django_db


def _folder(client, parent, name, **extra):
    r = client.post("/api/folders", {"parent": str(parent.id), "name": name, **extra}, format="json")
    assert r.status_code == 201, r.content
    return r.json()


# ------------------------------------------------------------------ AT-85/86 document actions

def test_at86_rename_archive_and_permanent_delete_rules(family, clients):
    son1, dad = family["son1"], family["dad"]
    doc_id = upload(clients["son1"], personal_root(son1)).json()["documents"][0]["id"]
    row = clients["son1"].get(f"/api/documents/{doc_id}").json()
    assert {"edit", "organize", "download"} <= set(row["caps"])  # the menu shows these actions
    r = clients["son1"].patch(f"/api/documents/{doc_id}", {"title": "Sample lease 2026"}, format="json")
    assert r.status_code == 200 and Document.objects.get(pk=doc_id).title == "Sample lease 2026"
    # a family member without edit rights cannot rename it, and the menu would not offer it
    mom_view = clients["mom"].get(f"/api/documents/{doc_id}")
    if mom_view.status_code == 200:
        assert "edit" not in mom_view.json()["caps"]
    assert clients["mom"].patch(f"/api/documents/{doc_id}", {"title": "x"}, format="json").status_code in (403, 404)
    # permanent delete: main administrator only, typed confirmation, audited
    assert clients["son1"].delete(f"/api/documents/{doc_id}", {"confirm": "Sample lease 2026"}, format="json").status_code == 403
    archiver = clients["son1"] if "archive" in row["caps"] else clients["dad"]  # Archive is only offered with the right
    if "archive" not in row["caps"]:
        assert clients["son1"].post(f"/api/documents/{doc_id}/archive").status_code in (403, 404)
    assert archiver.post(f"/api/documents/{doc_id}/archive").status_code == 200
    assert AuditEvent.objects.filter(action="document.archive", target_id=doc_id).exists()
    admin = clients["dad"]
    assert admin.delete(f"/api/documents/{doc_id}", {"confirm": "wrong"}, format="json").status_code == 400
    assert admin.delete(f"/api/documents/{doc_id}", {"confirm": "Sample lease 2026"}, format="json").status_code == 204
    assert not Document.objects.filter(pk=doc_id).exists()
    assert AuditEvent.objects.filter(action="document.purge", actor=dad).exists()


# ------------------------------------------------------------------ AT-87/88 folder icons

def test_at87_subfolders_default_to_standard_icon_and_top_level_keeps_suggestions(family, clients):
    c = clients["son1"]
    root = personal_root(family["son1"])
    house = _folder(c, root, "House & Property")
    assert house["emoji"] == "🏠" and not house["emoji_is_custom"]  # semantic top-level folder
    sub = _folder(c, Folder.objects.get(pk=house["id"]), "Passport copies")
    assert sub["emoji"] == "📁" and not sub["emoji_is_custom"]  # deeper folder: standard icon, no name guess
    chosen = _folder(c, Folder.objects.get(pk=house["id"]), "Trips", emoji="🧳")
    assert chosen["emoji"] == "🧳" and chosen["emoji_is_custom"]
    # only approved icons; free-form text/emoji are refused
    assert c.post("/api/folders", {"parent": house["id"], "name": "Bad", "emoji": "<b>"}, format="json").status_code == 400
    assert c.patch(f"/api/folders/{sub['id']}", {"emoji": "🌍"}, format="json").status_code == 400
    # change and reset to default
    assert c.patch(f"/api/folders/{sub['id']}", {"emoji": "🛂"}, format="json").json()["emoji"] == "🛂"
    r = c.patch(f"/api/folders/{sub['id']}", {"emoji": ""}, format="json").json()
    assert r["emoji"] == "📁" and not r["emoji_is_custom"]
    # the area root itself keeps its avatar/identity icon
    assert c.patch(f"/api/folders/{root.id}", {"emoji": "⭐"}, format="json").status_code == 400


def test_at88_icons_survive_moves_and_defaults_follow_level(family, clients):
    c = clients["son1"]
    root = personal_root(family["son1"])
    house = Folder.objects.get(pk=_folder(c, root, "House & Property")["id"])
    travel = _folder(c, house, "Travel")  # deep: standard icon even though the name suggests ✈️
    custom = _folder(c, house, "Keys", emoji="🔑")
    assert travel["emoji"] == "📁"
    # moved to the top level, a default icon becomes the semantic suggestion; a chosen icon is preserved
    assert c.patch(f"/api/folders/{travel['id']}", {"parent": str(root.id)}, format="json").json()["emoji"] == "✈️"
    deeper = Folder.objects.get(pk=travel["id"])
    assert c.patch(f"/api/folders/{custom['id']}", {"parent": str(deeper.id)}, format="json").json()["emoji"] == "🔑"
    assert c.patch(f"/api/folders/{travel['id']}", {"parent": str(house.id)}, format="json").json()["emoji"] == "📁"
    assert c.patch(f"/api/folders/{travel['id']}", {"name": "Holidays"}, format="json").json()["emoji"] == "📁"


def test_at88_upgrade_migration_resets_only_automatic_deep_icons(family):
    root = personal_root(family["son1"])
    top = Folder.objects.create(parent=root, name="Medical", owner=family["son1"], emoji="🩺")
    auto = Folder.objects.create(parent=top, name="Passport scans", owner=family["son1"], emoji="🛂")
    chosen = Folder.objects.create(parent=top, name="Dentist", owner=family["son1"], emoji="⭐", emoji_is_custom=True)
    mig = importlib.import_module("apps.library.migrations.0005_subfolder_default_icon")
    from django.apps import apps as django_apps

    mig.forwards(django_apps, None)
    for f in (top, auto, chosen):
        f.refresh_from_db()
    assert (top.emoji, auto.emoji, chosen.emoji) == ("🩺", "📁", "⭐")


# ------------------------------------------------------------------ AT-89 views and sorting

def test_at89_view_and_sort_preferences_sync_and_sorting(family, clients):
    c = clients["son1"]
    assert c.get("/api/session").json()["preferences"]["doc_view"] == "list"
    assert c.put("/api/settings", {"values": {"me.doc_view": "details", "me.doc_sort": "name"}}, format="json").status_code == 200
    # another device (new session for the same account) sees the same view
    from conftest import client_for

    prefs = client_for(family["son1"]).get("/api/session").json()["preferences"]
    assert prefs["doc_view"] == "details" and prefs["doc_sort"] == "name"
    assert c.put("/api/settings", {"values": {"me.doc_view": "carousel"}}, format="json").status_code == 400
    root = personal_root(family["son1"])
    for title, size in (("Bravo", 1), ("alpha", 3), ("Charlie", 2)):
        upload(c, root, name=f"{title}.pdf", content=make_text_pdf("x" * 200 * size), title=title)
    names = lambda sort: [d["title"] for d in c.get("/api/documents", {"folder": str(root.id), "sort": sort}).json()["documents"]]  # noqa: E731
    assert names("name") == ["alpha", "Bravo", "Charlie"]
    assert names("-name") == ["Charlie", "Bravo", "alpha"]
    assert names("-added")[0] == "Charlie"
    assert names("nonsense") == names("-added")  # unknown sort keys fall back safely


# ------------------------------------------------------------------ AT-90/91 files and folders from the desktop

def _drop(client, folder, items, dirs=()):
    files = [SimpleUploadedFile(p.rsplit("/", 1)[-1], make_text_pdf(p)) for p in items]
    return client.post("/api/documents", {"folder": str(folder.id), "files": files, "paths": list(items), "dirs": list(dirs)},
                       format="multipart")


def test_at91_dropped_folder_hierarchy_is_recreated_below_target(family, clients):
    c = clients["son1"]
    root = personal_root(family["son1"])
    target = Folder.objects.get(pk=_folder(c, root, "House & Property")["id"])
    r = _drop(c, target, ["House Documents/Lease/lease-2025.pdf", "House Documents/Lease/lease-2026.pdf",
                          "House Documents/Utilities/Water/bill.pdf", "House Documents/readme.pdf"],
              dirs=["House Documents/Insurance"])
    assert r.status_code == 201, r.content
    body = r.json()
    assert len(body["documents"]) == 4 and body["errors"] == [] and body["folders_created"] == 5
    house = Folder.objects.get(parent=target, name="House Documents")
    lease = Folder.objects.get(parent=house, name="Lease")
    water = Folder.objects.get(parent__parent=house, name="Water")
    assert Folder.objects.filter(parent=house, name="Insurance").exists()  # empty folder kept too
    assert Document.objects.filter(folder=lease).count() == 2 and Document.objects.filter(folder=water).count() == 1
    assert Document.objects.filter(folder=house).count() == 1
    assert {f.emoji for f in (house, lease, water)} == {"📁"}  # dropped sub-folders use the standard icon
    assert all(d.owner == family["son1"] for d in Document.objects.filter(folder__in=[house, lease, water]))
    # dropping again reuses the existing folders instead of duplicating them
    r = _drop(c, target, ["House Documents/Lease/lease-2027.pdf"])
    assert r.json()["folders_created"] == 0 and Folder.objects.filter(parent=target, name="House Documents").count() == 1


def test_at90_unsafe_paths_and_missing_rights_are_reported_not_discarded(family, clients):
    c = clients["son1"]
    root = personal_root(family["son1"])
    r = _drop(c, root, ["../escape.pdf", "ok/../../x.pdf", "/abs/y.pdf", "Fine/.DS_Store", "Fine/good.pdf"])
    body = r.json()
    assert r.status_code == 201 and len(body["documents"]) == 1
    failed = {e["file"]: e["error"] for e in body["errors"]}
    assert set(failed) == {"../escape.pdf", "ok/../../x.pdf", "/abs/y.pdf", "Fine/.DS_Store"}
    assert all(failed.values())
    assert not Folder.objects.filter(name__in=["..", "abs", "escape.pdf"]).exists()
    # someone who may add documents but not organise folders gets plain files in, folders refused with a reason
    son2_root = personal_root(family["son2"])
    AccessRule.objects.create(folder=son2_root, user=family["son1"], caps=P.VIEW | P.UPLOAD)
    from conftest import client_for

    r = _drop(client_for(family["son1"]), son2_root, ["single.pdf", "New Folder/inner.pdf"])
    body = r.json()
    assert len(body["documents"]) == 1 and body["errors"][0]["file"] == "New Folder/inner.pdf"
    assert "cannot create folders" in body["errors"][0]["error"]
    assert not Folder.objects.filter(parent=son2_root, name="New Folder").exists()
    # paths must match the files one to one
    f = SimpleUploadedFile("a.pdf", make_text_pdf("a"))
    assert c.post("/api/documents", {"folder": str(root.id), "files": [f], "paths": ["a.pdf", "b.pdf"]}, format="multipart").status_code == 400
