"""Change Set T - recovery workflows (AT-286 .. AT-301, AT-309, AT-310 backend parts). Synthetic data only."""
import json
from pathlib import Path

import pyotp
import pytest

from apps.core import config, crypto
from apps.core.models import AuditEvent
from apps.library.models import Document, DocumentVersion, Folder
from apps.notify.models import Notification
from apps.ops import bk_engine as E
from apps.ops import bk_keys
from apps.ops.models import BackupDestination, EmergencyExport, KeyRotation, RecoveryCopy, RecoveryKey, RecoveryPoint

from conftest import PASSWORD, client_for, personal_root, run_jobs, upload
from fixtures import make_text_pdf
from test_backup_engine import make_policy

pytestmark = pytest.mark.django_db


def stepup(c, **extra):
    return c.post("/api/backup/stepup", {"password": PASSWORD, **extra}, format="json")


@pytest.fixture
def lib(family, clients, tmp_path):
    root = personal_root(family["mom"])
    sub = Folder.objects.create(parent=root, name="Identity", owner=family["mom"])
    nested = Folder.objects.create(parent=sub, name="Passports", owner=family["mom"])
    r = upload(clients["mom"], nested, name="passport-sample.pdf", content=make_text_pdf("Synthetic passport v1"))
    assert r.status_code == 201, r.content
    run_jobs()
    doc = Document.objects.get(title__icontains="passport")
    pol, dests = make_policy(tmp_path, n=2)
    point = E.create_point(pol, kind="full", trigger="manual")
    assert point.status == RecoveryPoint.VERIFIED
    return {"doc": doc, "sub": sub, "nested": nested, "point": point, "policy": pol, "dests": dests}


# ------------------------------------------------------------------ AT-286 key reveal

def test_at286_only_main_admin_with_stepup_reveals_key_and_it_is_never_logged(family, clients, lib):
    assert clients["mom"].post("/api/backup/key/reveal").status_code == 403
    c = clients["dad"]
    assert c.post("/api/backup/key/reveal").json()["code"] == "stepup_required"
    assert stepup(c, password="wrong").status_code == 400
    # with an authenticator app the code is required too
    secret = pyotp.random_base32()
    u = family["dad"]
    u.totp_secret_enc, u.totp_enabled = crypto.encrypt(secret), True
    u.save()
    r = stepup(c)
    assert r.status_code == 400 and r.json()["code"] == "second_factor_required"
    assert stepup(c, code=pyotp.TOTP(secret).now()).status_code == 200
    r = c.post("/api/backup/key/reveal")
    assert r.status_code == 200 and "no-store" in r["Cache-Control"]
    key = r.json()["key"]
    assert key.startswith("PDRK1-") and r.json()["hide_after_seconds"] > 0
    # one reveal per step-up
    assert c.post("/api/backup/key/reveal").json()["code"] == "stepup_required"
    ev = AuditEvent.objects.filter(action="recovery.key_revealed").get()
    assert key not in json.dumps(ev.context, default=str)
    n = Notification.objects.filter(event="recovery.key_revealed", user=u).get()
    assert key not in n.body and key not in json.dumps(n.data)
    assert not Notification.objects.filter(event="recovery.key_revealed").exclude(user=u).exists()


# ------------------------------------------------------------------ AT-287 / AT-288 rotation

def test_at287_rotation_reencrypts_all_reachable_copies_and_requires_new_emergency_package(family, clients, lib):
    from apps.ops import bk_rotate

    EmergencyExport.objects.create(generation=lib["point"].key_generation)
    assert bk_keys.readiness()["state"] == "ready"
    old_gen = bk_keys.active().generation
    old_key = bk_keys.raw_key(old_gen)
    rot = bk_rotate.rotate(family["dad"])
    assert rot.status == KeyRotation.COMPLETE, rot.results
    new = bk_keys.active()
    assert new.generation == old_gen + 1
    # every retained copy (the original point and the safety checkpoint) is on the new generation and verified
    for c in RecoveryCopy.objects.exclude(state=RecoveryCopy.DELETED):
        assert c.generation == new.generation and c.state == RecoveryCopy.STORED_VERIFIED
        root = Path(c.destination.config["path"]) / str(c.point_id)
        assert not (root / f"g{old_gen}").exists() and (root / f"g{new.generation}" / "header.json").exists()
    # the old key no longer opens anything and is destroyed only now
    assert RecoveryKey.objects.get(generation=old_gen).state == RecoveryKey.RETIRED
    from apps.ops import bk_crypto as C
    from apps.ops.bk_destinations import provider

    c = lib["point"].copies.first()
    with pytest.raises(C.DecryptError):
        E.open_point(provider(c.destination), lib["point"].id, new.generation, old_key)
    assert bk_keys.readiness()["state"] == "outdated"
    assert Notification.objects.filter(event="recovery.key_rotated").exists()


def test_at288_partial_rotation_names_unreachable_destination(family, clients, lib):
    from apps.ops import bk_rotate

    old_gen = bk_keys.active().generation
    down = lib["dests"][1]
    path = Path(down.config["path"])
    path.rename(path.with_name("offline"))  # destination unavailable during rotation
    rot = bk_rotate.rotate(family["dad"])
    assert rot.status == KeyRotation.PARTIAL
    unreachable = [r for r in rot.results if r["state"] != "migrated"]
    assert unreachable and all(r["destination"] == down.name for r in unreachable)
    assert RecoveryKey.objects.get(generation=old_gen).state == RecoveryKey.RETIRING  # still usable
    assert bk_keys.raw_key(old_gen)
    assert any("Recovery Key rotation is incomplete" in w for w in E.health()["warnings"])
    # the destination returns: retry migrates the rest and only then retires the old key
    path.with_name("offline").rename(path)
    rot2 = bk_rotate.retry(family["dad"])
    assert rot2.status == KeyRotation.COMPLETE, rot2.results
    assert RecoveryKey.objects.get(generation=old_gen).state == RecoveryKey.RETIRED


# ------------------------------------------------------------------ AT-289 / AT-290 emergency package and readiness

def test_at289_at290_emergency_package_and_readiness(family, clients, lib, tmp_path):
    c = clients["dad"]
    assert bk_keys.readiness()["state"] == "not_exported"
    assert c.post("/api/backup/emergency", {"passphrase": "x" * 14, "confirm": "x" * 14}, format="json").json()["code"] == "stepup_required"
    assert stepup(c).status_code == 200
    assert c.post("/api/backup/emergency", {"passphrase": "short", "confirm": "short"}, format="json").status_code == 400
    r = c.post("/api/backup/emergency", {"passphrase": "correct horse battery", "confirm": "correct horse battery"}, format="json")
    assert r.status_code == 200 and r["Content-Disposition"].endswith('.pdrp"')
    pkg = json.loads(r.content)
    key_text = bk_keys.reveal_text(bk_keys.active().generation)
    assert key_text not in r.content.decode()
    assert "Recover Existing Installation" in pkg["instructions"]
    from apps.ops import bk_crypto as C

    assert C.format_key(C.open_emergency(pkg, "correct horse battery")) == key_text
    # never written next to the backups
    for d in lib["dests"]:
        assert not list(Path(d.config["path"]).rglob("*.pdrp"))
    assert bk_keys.readiness()["state"] == "ready"
    # rotation makes it outdated; a new export makes it ready again
    from apps.ops import bk_rotate

    bk_rotate.rotate(family["dad"])
    assert bk_keys.readiness()["state"] == "outdated"
    assert stepup(c).status_code == 200
    c.post("/api/backup/emergency", {"passphrase": "another long phrase", "confirm": "another long phrase"}, format="json")
    assert bk_keys.readiness()["state"] == "ready"
    # the package opens a current recovery point (supported recovery procedure)
    pkg3 = json.loads(r.content) if False else None
    point = RecoveryPoint.objects.filter(deleted_at__isnull=True).order_by("-created_at").first()
    copy = point.copies.first()
    from apps.ops.bk_destinations import provider

    assert stepup(c).status_code == 200
    latest = json.loads(c.post("/api/backup/emergency", {"passphrase": "third long phrase!", "confirm": "third long phrase!"},
                               format="json").content)
    raw = C.open_emergency(latest, "third long phrase!")
    header, dek = E.open_point(provider(copy.destination), point.id, copy.generation, raw)
    assert header["point"] == str(point.id) and len(dek) == 32
    assert pkg3 is None


# ------------------------------------------------------------------ AT-294 explorer authorisation

def test_at294_explorer_shows_only_what_each_person_may_recover(family, clients, lib):
    pid = lib["point"].id
    admin = clients["dad"].get(f"/api/recovery/points/{pid}").json()
    assert any(d["title"].lower().startswith("passport") for d in admin["documents"])
    mom = clients["mom"].get(f"/api/recovery/points/{pid}").json()
    assert [d["id"] for d in mom["documents"]] == [str(lib["doc"].id)]
    son = clients["son1"].get(f"/api/recovery/points/{pid}").json()
    assert son["documents"] == []  # no access to mom's documents now
    # an Administrator (security role) gets no document access either
    u = family["son2"]
    u.is_admin = True
    u.save()
    assert client_for(u).get(f"/api/recovery/points/{pid}").json()["documents"] == []
    # the points list hides admin details from members
    assert clients["son1"].get("/api/recovery/points").json()["points"][0]["status"] is None
    assert clients["son1"].get("/api/backup/overview").status_code == 403
    # search
    assert clients["mom"].get(f"/api/recovery/points/{pid}?q=passports").json()["total"] == 1


# ------------------------------------------------------------------ AT-295 / AT-296 version restore and conflicts

def _add_version(clients, doc, text):
    f = __import__("django.core.files.uploadedfile", fromlist=["SimpleUploadedFile"]).SimpleUploadedFile(
        "passport-sample.pdf", make_text_pdf(text), content_type="application/pdf")
    r = clients["mom"].post(f"/api/documents/{doc.id}/versions", {"file": f}, format="multipart")
    assert r.status_code in (200, 201), r.content
    run_jobs()


def test_at295_version_restore_keeps_current_by_default(family, clients, lib):
    doc = lib["doc"]
    v1 = doc.current_version
    _add_version(clients, doc, "Synthetic passport v2")
    doc.refresh_from_db()
    v2 = doc.current_version
    assert v2.id != v1.id
    # v1 deleted from the current library? simulate an accidental loss of v1's file content change
    body = {"point": str(lib["point"].id), "kind": "version", "target": {"document": str(doc.id), "version": str(v1.id)},
            "mode": "keep_new"}
    preview = clients["mom"].post("/api/recovery/restore", body, format="json").json()
    assert preview["status"] == "analyzed" and preview["impact"]["deletes"] == []
    assert any("already present" in a for a in preview["impact"]["actions"])  # v1 still in the history: nothing to add
    DocumentVersion.objects.filter(pk=v1.pk).update(sha256="0" * 64)  # the history copy differs now (controlled conflict)
    r = clients["mom"].post("/api/recovery/restore", {**body, "execute": True}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "completed", r.json()
    doc.refresh_from_db()
    assert doc.current_version_id == v2.id  # current data not overwritten
    restored = doc.versions.order_by("-number").first()
    assert "Restored from backup" in restored.comment
    assert AuditEvent.objects.filter(action="recovery.restore").exists()
    assert Notification.objects.filter(event="recovery.restore", user=family["mom"]).exists()


def test_at296_conflict_modes_replace_and_skip(family, clients, lib):
    doc = lib["doc"]
    v1 = doc.current_version
    _add_version(clients, doc, "Synthetic passport v2")
    doc.refresh_from_db()
    v2 = doc.current_version
    base = {"point": str(lib["point"].id), "kind": "document", "target": {"document": str(doc.id)}}
    skip = clients["mom"].post("/api/recovery/restore", {**base, "mode": "skip"}, format="json").json()
    assert skip["impact"]["counts"]["skipped"] == 1 and skip["impact"]["newer_current"]
    clients["mom"].post("/api/recovery/restore", {**base, "mode": "skip", "execute": True}, format="json")
    doc.refresh_from_db()
    assert doc.current_version_id == v2.id and doc.versions.count() == 2
    rep = clients["mom"].post("/api/recovery/restore", {**base, "mode": "replace"}, format="json").json()
    assert rep["impact"]["replaces_current"] and rep["impact"]["conflicts"]
    r = clients["mom"].post("/api/recovery/restore", {**base, "mode": "replace", "execute": True}, format="json").json()
    assert r["status"] == "completed", r
    doc.refresh_from_db()
    assert doc.current_version.sha256 == v1.sha256 and doc.versions.filter(pk=v2.pk).exists()  # v2 kept in history
    assert clients["mom"].post("/api/recovery/restore", {**base, "mode": "bogus"}, format="json").status_code == 400


# ------------------------------------------------------------------ AT-297 folder and user restore, AT-299 impact

def test_at297_at299_nested_folder_restore_recreates_hierarchy_with_impact(family, clients, lib):
    from apps.library import services

    doc = lib["doc"]
    sha = doc.current_version.sha256
    services.archive_document(actor=family["mom"], doc=doc)
    services.purge_document(actor=family["mom"], doc=Document.objects.get(pk=doc.pk))
    Folder.objects.filter(pk=lib["nested"].pk).delete()
    Folder.objects.filter(pk=lib["sub"].pk).delete()
    body = {"point": str(lib["point"].id), "kind": "folder", "target": {"folder": str(lib["sub"].id)}, "mode": "keep_new"}
    imp = clients["mom"].post("/api/recovery/restore", body, format="json").json()["impact"]
    assert imp["counts"]["documents_create"] == 1 and imp["counts"]["folders_create"] == 2
    assert imp["storage"]["bytes_needed"] > 0 and "No current data is deleted" in imp["deletion_note"]
    r = clients["mom"].post("/api/recovery/restore", {**body, "execute": True}, format="json").json()
    assert r["status"] == "completed", r
    new_doc = Document.objects.get(title__icontains="passport")
    assert new_doc.folder.name == "Passports" and new_doc.folder.parent.name == "Identity"
    assert new_doc.folder.parent.parent.kind == Folder.PERSONAL_ROOT and new_doc.owner == family["mom"]
    assert new_doc.versions.count() == 1 and new_doc.current_version.sha256 == sha


def test_at297_user_scope_restore(family, clients, lib):
    r = clients["mom"].post("/api/recovery/restore", {"point": str(lib["point"].id), "kind": "user",
                                                      "target": {"user": str(family["mom"].pk)}}, format="json").json()
    assert r["status"] == "analyzed"
    # a member cannot restore someone else's scope
    assert clients["son1"].post("/api/recovery/restore", {"point": str(lib["point"].id), "kind": "user",
                                                          "target": {"user": str(family["mom"].pk)}}, format="json").status_code == 400


def _delete_user(user):
    from apps.library.models import AccessRule

    for d in Document.objects.filter(owner=user):
        DocumentVersion.objects.filter(document=d).delete()
    Document.objects.filter(owner=user).delete()
    AccessRule.objects.filter(user=user).delete()
    for f in sorted(Folder.objects.filter(owner=user), key=lambda f: -len(str(f.parent_id or ""))):
        pass
    while Folder.objects.filter(owner=user).exists():
        Folder.objects.filter(owner=user, children__isnull=True).delete()
    user.delete()


@pytest.mark.parametrize("option", ["recreate", "transfer", "staging"])
def test_at298_deleted_user_recovery_options(family, clients, lib, option):
    mom_id = str(family["mom"].pk)
    _delete_user(family["mom"])
    body = {"point": str(lib["point"].id), "kind": "user", "target": {"user": mom_id}}
    r = clients["dad"].post("/api/recovery/restore", body, format="json")
    assert r.status_code == 400 and "no longer exists" in r.json()["error"]
    target = {"user": mom_id, "user_option": option}
    if option == "transfer":
        target["transfer_to"] = str(family["daughter"].pk)
    r = clients["dad"].post("/api/recovery/restore", {**body, "target": target, "execute": True}, format="json").json()
    assert r["status"] == "completed", r
    doc = Document.objects.get(title__icontains="passport")
    from apps.accounts.models import User, UserSession

    if option == "recreate":
        u = User.objects.get(pk=mom_id)
        assert doc.owner == u and not u.has_usable_password() and u.must_change_password
        assert not UserSession.objects.filter(user=u).exists()  # no old sessions come back
        assert not u.totp_enabled
    elif option == "transfer":
        names, f = [], doc.folder
        while f is not None:
            names.append(f.name)
            f = f.parent
        assert doc.owner == family["daughter"] and any(n.startswith("Recovered from Maria Sample") for n in names)
        assert personal_root(family["daughter"]).name in names
    else:
        top = doc.folder
        while top.parent is not None:
            top = top.parent
        assert top.name == "Recovery staging" and doc.owner == family["dad"]


# ------------------------------------------------------------------ AT-300 protected deletion, AT-301 download

def test_at300_protected_deletion(family, clients, lib):
    pol = lib["policy"]
    inc = E.create_point(pol, kind="incremental", trigger="manual")
    pid = lib["point"].id
    assert clients["mom"].post(f"/api/backup/points/{pid}/delete").status_code == 403
    u = family["son2"]
    u.is_admin = True
    u.save()
    assert client_for(u).post(f"/api/backup/points/{pid}/delete").status_code == 403
    c = clients["dad"]
    prev = c.get(f"/api/backup/points/{pid}/delete").json()
    assert [d["id"] for d in prev["dependents"]] == [str(inc.id)] and prev["coverage"]["warning"]
    r = c.post(f"/api/backup/points/{pid}/delete", {}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "dependents"
    r = c.post(f"/api/backup/points/{pid}/delete", {"include_dependents": True}, format="json")
    assert r.json()["code"] == "stepup_required"
    assert stepup(c).status_code == 200
    r = c.post(f"/api/backup/points/{pid}/delete", {"include_dependents": True}, format="json")
    assert r.status_code == 200 and set(r.json()["deleted"]) == {str(pid), str(inc.id)}
    for d in lib["dests"]:
        assert not (Path(d.config["path"]) / str(pid)).exists()
    assert AuditEvent.objects.filter(action="backup.delete").exists()
    assert Notification.objects.filter(event="backup.deleted").exists()


def test_at301_secure_encrypted_download(family, clients, lib):
    pid = lib["point"].id
    inc = E.create_point(lib["policy"], kind="incremental", trigger="manual")
    assert clients["mom"].get(f"/api/backup/points/{pid}/download").status_code == 403
    c = clients["dad"]
    assert c.get(f"/api/backup/points/{inc.id}/download").json()["code"] == "stepup_required"
    assert stepup(c).status_code == 200
    r = c.get(f"/api/backup/points/{inc.id}/download")
    assert r.status_code == 200 and r["Content-Type"] == "application/x-tar"
    body = b"".join(r.streaming_content)
    import io
    import tarfile

    names = tarfile.open(fileobj=io.BytesIO(body)).getnames()
    # the incremental's base is included: a complete recoverable set
    assert any(n.startswith(str(pid)) for n in names) and any(n.startswith(str(inc.id)) for n in names)
    assert b"Synthetic passport" not in body and b"%PDF" not in body
    assert AuditEvent.objects.filter(action="backup.download").exists()
    assert Notification.objects.filter(event="backup.downloaded").exists()
    # guessing another URL does not bypass authorisation
    assert clients["son1"].get(f"/api/backup/points/{inc.id}/download?destination=1").status_code == 403


def test_my_recovery_privacy(family, clients, lib):
    r = clients["son1"].get("/api/recovery/mine").json()
    assert r["protected"] is True
    text = json.dumps(r)
    for d in lib["dests"]:
        assert d.config["path"] not in text and d.name not in text


def test_admin_overview_never_returns_destination_secrets(family, clients, lib):
    c = clients["dad"]
    r = c.post("/api/backup/destinations", {"name": "Object storage", "kind": "s3",
                                            "config": {"endpoint": "https://s3.example.com", "bucket": "pd", "region": "eu-1"},
                                            "secrets": {"access_key": "AKIASYNTHETIC", "secret_key": "synthetic-secret-123"}}, format="json")
    assert r.status_code == 201, r.content
    text = c.get("/api/backup/overview").content.decode()
    assert "synthetic-secret-123" not in text and "AKIASYNTHETIC" not in text and '"secret_key"' in text
    d = BackupDestination.objects.get(name="Object storage")
    assert "synthetic-secret-123" not in d.secret_enc
