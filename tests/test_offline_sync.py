"""Change Set S: offline copies scoped by user + device + folder/document (AT-251..AT-259, server side).

All documents are synthetic. The browser side (Cache Storage, sign-out cleanup, status) is covered by
tests/e2e/offline.mjs."""
import pytest
from conftest import client_for, personal_root, run_jobs, upload
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core import config
from apps.library import permissions as P
from apps.library.models import AccessRule, Document, Folder, OfflineDevice, OfflineSelection
from fixtures import make_text_pdf

pytestmark = pytest.mark.django_db


def _doc(client, folder, name="sample.pdf", text="Sample offline document"):
    r = upload(client, folder, name=name, content=make_text_pdf(text))
    assert r.status_code == 201, r.content
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


def _sub(owner, parent, name):
    return Folder.objects.create(parent=parent, name=name, owner=owner)


def _register(client, label="Test browser"):
    r = client.post("/api/offline/devices", {"label": label, "platform": "Chromium on Linux"}, format="json")
    assert r.status_code == 200, r.content
    return r.json()["device"]["id"]


def _sync(client, device, have=()):
    r = client.post("/api/offline/sync", {"device": device, "have": list(have), "report": {"items": len(have)}}, format="json")
    assert r.status_code == 200, r.content
    return r.json()


@pytest.fixture
def tree(family, clients):
    son = family["son1"]
    root = personal_root(son)
    trip = _sub(son, root, "Trip 2027")
    tickets = _sub(son, trip, "Tickets")
    docs = {"root": _doc(clients["son1"], root, "root.pdf"), "trip": _doc(clients["son1"], trip, "itinerary.pdf"),
            "ticket": _doc(clients["son1"], tickets, "ticket.pdf")}
    run_jobs()
    return {"root": root, "trip": trip, "tickets": tickets, "docs": docs}


def test_at251_offline_state_is_user_and_device_scoped(family, clients, tree):
    c = clients["son1"]
    laptop, phone = _register(c, "Laptop"), _register(c, "Phone")
    assert laptop != phone
    r = c.post("/api/offline/selections", {"device": laptop, "folder": str(tree["trip"].id), "recursive": True}, format="json")
    assert r.status_code == 201, r.content
    assert len(_sync(c, laptop)["items"]) == 2
    assert _sync(c, phone)["items"] == []  # another device of the same person gets nothing
    # another account cannot use (or even see) this device
    other = clients["daughter"]
    assert other.post("/api/offline/selections", {"device": laptop, "folder": str(tree["trip"].id)}, format="json").status_code == 404
    assert _sync(other, laptop)["known_device"] is False
    assert other.get("/api/offline/devices").json()["devices"] == []


def test_at253_recursive_choice_and_estimate(clients, tree):
    c = clients["son1"]
    dev = _register(c)
    est_all = c.get("/api/offline/estimate", {"folder": str(tree["trip"].id), "recursive": "1"}).json()
    est_one = c.get("/api/offline/estimate", {"folder": str(tree["trip"].id), "recursive": "0"}).json()
    assert (est_all["documents"], est_all["subfolders"]) == (2, 1)
    assert (est_one["documents"], est_one["subfolders"]) == (1, 0)
    assert est_all["bytes"] > est_one["bytes"] > 0
    assert est_all["quota_bytes"] == 2048 * 1024 * 1024
    c.post("/api/offline/selections", {"device": dev, "folder": str(tree["trip"].id), "recursive": False}, format="json")
    items = _sync(c, dev)["items"]
    assert [i["name"] for i in items] == ["itinerary.pdf"]
    # switching to "with subfolders" updates the same selection
    c.post("/api/offline/selections", {"device": dev, "folder": str(tree["trip"].id), "recursive": True}, format="json")
    assert OfflineSelection.objects.filter(device_id=dev).count() == 1
    items = _sync(c, dev)["items"]
    assert sorted(i["name"] for i in items) == ["itinerary.pdf", "ticket.pdf"]
    assert {i["path"] for i in items} == {"Trip 2027", "Trip 2027 / Tickets"}  # never the ancestors above the selection
    # a document added later is picked up at the next sync
    _doc(c, tree["tickets"], "hotel.pdf")
    run_jobs()
    assert len(_sync(c, dev)["items"]) == 3


def test_at254_document_add_update_remove(clients, tree):
    c = clients["son1"]
    dev = _register(c)
    doc = tree["docs"]["root"]
    r = c.post("/api/offline/selections", {"device": dev, "document": str(doc.id)}, format="json")
    sel = r.json()["id"]
    first = _sync(c, dev)["items"][0]
    have = [{"document": first["document"], "version": first["version"]}]
    # a new version is listed with its new version id (the device updates or flags "Update available")
    f = SimpleUploadedFile("root-v2.pdf", make_text_pdf("Sample offline document v2"), content_type="application/pdf")
    assert c.post(f"/api/documents/{doc.id}/versions", {"file": f}, format="multipart").status_code in (200, 201)
    run_jobs()
    second = _sync(c, dev, have)["items"][0]
    assert second["version"] != first["version"] and second["version_number"] == 2
    # removing the selection lists the copy for removal
    assert c.delete(f"/api/offline/selections/{sel}").status_code == 204
    out = _sync(c, dev, have)
    assert out["items"] == [] and out["remove"] == [str(doc.id)]


def test_at257_sync_revalidates_access_and_revocation(family, clients, tree):
    owner, guest = clients["son1"], clients["daughter"]
    rule = AccessRule.objects.create(folder=tree["trip"], user=family["daughter"], caps=P.VIEW | P.DOWNLOAD)
    dev = _register(guest)
    assert guest.post("/api/offline/selections", {"device": dev, "folder": str(tree["trip"].id)}, format="json").status_code == 201
    items = _sync(guest, dev)["items"]
    assert len(items) == 2
    have = [{"document": i["document"], "version": i["version"]} for i in items]
    # view without download: may browse, may not keep offline
    rule.caps = P.VIEW
    rule.save()
    out = _sync(client_for(family["daughter"]), dev, have)
    assert out["items"] == [] and sorted(out["remove"]) == sorted(h["document"] for h in have)
    # access fully revoked: the selection no longer reveals the folder name
    rule.delete()
    out = _sync(client_for(family["daughter"]), dev, have)
    assert out["selections"][0]["available"] is False
    assert out["selections"][0]["name"] == "Folder no longer available"
    assert "Trip" not in str(out)
    # documents without download permission cannot be selected at all
    assert guest.post("/api/offline/selections", {"device": dev, "document": str(tree["docs"]["root"].id)}, format="json").status_code == 404


def test_at257_archived_and_quarantined_are_removed(clients, tree):
    c = clients["son1"]
    dev = _register(c)
    c.post("/api/offline/selections", {"device": dev, "folder": str(tree["trip"].id)}, format="json")
    items = _sync(c, dev)["items"]
    have = [{"document": i["document"], "version": i["version"]} for i in items]
    ticket = tree["docs"]["ticket"]
    assert clients["dad"].post(f"/api/documents/{ticket.id}/archive", {}, format="json").status_code in (200, 204)
    v = tree["docs"]["trip"].current_version
    v.av_status = "threat"
    v.save(update_fields=["av_status"])
    out = _sync(c, dev, have)
    assert out["items"] == []
    assert sorted(out["remove"]) == sorted(h["document"] for h in have)


def test_at257_admin_capability_and_global_switch(family, clients, tree):
    c = clients["son1"]
    dev = _register(c)
    c.post("/api/offline/selections", {"device": dev, "folder": str(tree["trip"].id)}, format="json")
    have = [{"document": i["document"], "version": i["version"]} for i in _sync(c, dev)["items"]]
    admin = clients["dad"]
    # only the main administrator manages capability
    assert c.patch(f"/api/admin/offline/users/{family['son1'].id}", {"offline_allowed": False}, format="json").status_code == 403
    assert admin.patch(f"/api/admin/offline/users/{family['son1'].id}", {"offline_allowed": False}, format="json").status_code == 200
    out = _sync(client_for(family["son1"]), dev, have)
    assert out["allowed"] is False and out["wipe"] is True and len(out["remove"]) == 2
    assert client_for(family["son1"]).post("/api/offline/selections", {"device": dev, "document": str(tree["docs"]["root"].id)},
                                           format="json").status_code == 403
    assert client_for(family["son1"]).get("/api/session").json()["offline"]["allowed"] is False
    admin.patch(f"/api/admin/offline/users/{family['son1'].id}", {"offline_allowed": True}, format="json")
    assert len(_sync(client_for(family["son1"]), dev, have)["items"]) == 2
    config.set_value("offline.enabled", False)
    out = _sync(client_for(family["son1"]), dev, have)
    assert out["allowed"] is False and out["wipe"] is True
    overview = admin.get("/api/admin/offline").json()
    son = next(u for u in overview["users"] if u["id"] == str(family["son1"].id))
    assert son["devices"][0]["label"] == "Test browser" and son["devices"][0]["last_sync_at"]


def test_admin_device_wipe_and_forgotten_device(family, clients, tree):
    c = clients["son1"]
    dev = _register(c)
    c.post("/api/offline/selections", {"device": dev, "folder": str(tree["trip"].id)}, format="json")
    have = [{"document": i["document"], "version": i["version"]} for i in _sync(c, dev)["items"]]
    assert clients["dad"].post(f"/api/admin/offline/devices/{dev}/wipe").status_code == 200
    out = _sync(c, dev, have)
    assert out["wipe"] is True and len(out["remove"]) == 2
    assert _sync(c, dev, [])["wipe"] is False  # one-shot
    assert OfflineSelection.objects.filter(device_id=dev).count() == 0
    # forgetting the device: the next sync from it is told to remove everything
    assert c.delete(f"/api/offline/devices/{dev}").status_code == 204
    out = _sync(c, dev, have)
    assert out["known_device"] is False and out["wipe"] is True
    assert not OfflineDevice.objects.filter(pk=dev).exists()


def test_at259_offline_text_policy_and_ocr_removal(family, clients, tree):
    from apps.library.ocr_runs import remove_ocr

    c = clients["son1"]
    dev = _register(c)
    doc = tree["docs"]["root"]
    c.post("/api/offline/selections", {"device": dev, "document": str(doc.id)}, format="json")
    assert _sync(c, dev)["items"][0]["text"] is None  # default: text is not kept offline
    config.set_value("offline.cache_text", True)
    item = _sync(c, dev)["items"][0]
    assert item["text"] and _sync(c, dev)["policy"]["cache_text"] is True
    remove_ocr(actor=family["son1"], doc=Document.objects.get(pk=doc.pk), include_embedded=True)
    assert _sync(c, dev)["items"][0]["text"] is None  # device deletes its offline text at this sync


def test_sync_and_selection_never_audit_titles_or_text(family, clients, tree):
    from apps.core.models import AuditEvent

    c = clients["son1"]
    dev = _register(c)
    c.post("/api/offline/selections", {"device": dev, "folder": str(tree["trip"].id)}, format="json")
    _sync(c, dev)
    for e in AuditEvent.objects.filter(action__startswith="offline."):
        assert "Sample offline document" not in str(e.context)
