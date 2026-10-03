"""AT-04, AT-05: browser folder mapping and server/NAS imports."""
import hashlib
import os
from pathlib import Path

import pytest
from conftest import client_for, make_text_pdf, personal_root, run_jobs
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core import config
from apps.library.models import Document, Folder, ImportItem, ImportSession

pytestmark = pytest.mark.django_db

ENTRIES = [
    {"path": "user3/Passport/Old Passports/Old Passport 2016/scan.pdf", "size": 100},
    {"path": "user3/Schools/10STD Reciepts/receipt.pdf", "size": 100},
    {"path": "user3/.sync/Archive/old.pdf", "size": 100},
    {"path": "Travel/Qatar Visa Jan-2025/Visa/visa.pdf", "size": 100},
    {"path": "Sam Sample/Medical/report.pdf", "size": 100},
    {"path": "Mystery/notes.txt", "size": 10},
]


def _scan(client):
    r = client.post("/api/imports", {"source_type": "browser", "entries": ENTRIES}, format="json")
    assert r.status_code == 201, r.content
    return r.json()


def test_at04_browser_mapping_requires_explicit_decisions(family, clients):
    son1 = family["son1"]
    s = _scan(clients["dad"])
    m = s["mapping"]
    assert m["user3"]["status"] == "unresolved"  # "user3" is never guessed to be anyone
    assert m["Sam Sample"]["action"] == "user" and m["Sam Sample"]["status"] == "proposed"
    assert m["Mystery"]["status"] == "unresolved"
    assert ImportItem.objects.get(relative_path__contains=".sync").excluded_reason  # shown, not silently imported
    r = clients["dad"].post(f"/api/imports/{s['id']}/start")
    assert r.status_code == 400  # unresolved folders block the start
    shared = Folder.objects.get(name="Shared family")
    mapping = {
        "user3": {"action": "user", "user": str(son1.pk)},
        "Sam Sample": {"action": "user", "user": str(son1.pk)},  # several source folders -> one account
        "Travel": {"action": "folder", "folder": str(shared.id), "owner": str(family["dad"].pk), "keep_top": True},
        "Mystery": {"action": "skip"},
    }
    r = clients["dad"].put(f"/api/imports/{s['id']}", {"mapping": mapping}, format="json")
    assert r.status_code == 200, r.content
    assert clients["dad"].post(f"/api/imports/{s['id']}/start").status_code == 200
    for e in ENTRIES:
        f = SimpleUploadedFile(e["path"].rsplit("/", 1)[1], make_text_pdf(e["path"]))
        clients["dad"].post(f"/api/imports/{s['id']}/items", {"path": e["path"], "file": f}, format="multipart")
    # retry of the same item does not create an extra copy
    f = SimpleUploadedFile("scan.pdf", make_text_pdf("again"))
    r = clients["dad"].post(f"/api/imports/{s['id']}/items", {"path": ENTRIES[0]["path"], "file": f}, format="multipart")
    assert r.json().get("duplicate_retry") is True, r.json()
    docs = Document.objects.filter(owner=son1)
    assert docs.count() == 3
    scan = docs.get(title="scan")
    chain = []
    node = scan.folder
    while node:
        chain.append(node.name)
        node = node.parent
    assert list(reversed(chain)) == ["Family library", "Sam Sample", "Passport", "Old Passports", "Old Passport 2016"]
    assert scan.source_path.endswith("user3/Passport/Old Passports/Old Passport 2016/scan.pdf")
    assert Document.objects.filter(folder__parent__parent__parent=shared, folder__parent__parent__name="Travel", title="visa").exists()
    assert not Document.objects.filter(title="old").exists() and not Document.objects.filter(title="notes").exists()
    sess = ImportSession.objects.get(pk=s["id"])
    assert sess.status == "done"
    report = clients["dad"].get(f"/api/imports/{s['id']}/report").content.decode()
    assert "Sync tool history folder" in report


def test_regular_user_cannot_map_into_folders_without_upload_rights(family, clients):
    s = _scan(clients["son1"])
    mapping = {k: {"action": "skip"} for k in s["mapping"]}
    mapping["user3"] = {"action": "user", "user": str(family["son2"].pk)}
    r = clients["son1"].put(f"/api/imports/{s['id']}", {"mapping": mapping}, format="json")
    assert r.status_code == 400
    r = clients["son1"].post("/api/imports", {"source_type": "server", "root": "/"}, format="json")
    assert r.status_code == 403


def test_unsafe_paths_rejected(family, clients):
    r = clients["dad"].post("/api/imports", {"source_type": "browser", "entries": [{"path": "../etc/passwd", "size": 1}]}, format="json")
    assert r.status_code == 400


def _tree(tmp_path):
    src = tmp_path / "nas" / "old-documents"
    (src / "user3" / "Passport").mkdir(parents=True)
    (src / "user3" / "Passport" / "p.pdf").write_bytes(make_text_pdf("passport sample"))
    (src / "user3" / "id.pdf").write_bytes(make_text_pdf("id sample"))
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(make_text_pdf("outside the approved root"))
    os.symlink(outside, src / "user3" / "link.pdf")
    return src


def _hashes(root: Path):
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}


def test_at05_server_import_copies_without_touching_source(family, clients, tmp_path):
    src = _tree(tmp_path)
    before = _hashes(src)
    r = clients["dad"].post("/api/imports", {"source_type": "server", "root": str(src)}, format="json")
    assert r.status_code == 400  # not an approved root yet
    config.set_value("documents.import_roots", str(tmp_path / "nas"))
    r = clients["dad"].post("/api/imports", {"source_type": "server", "root": str(tmp_path / "nas" / ".." / "secret.pdf")}, format="json")
    assert r.status_code == 400  # traversal outside approved root
    s = clients["dad"].post("/api/imports", {"source_type": "server", "root": str(src)}, format="json").json()
    link_item = ImportItem.objects.get(session_id=s["id"], relative_path="user3/link.pdf")
    assert link_item.status == "skipped" and "Symbolic link" in link_item.excluded_reason
    clients["dad"].put(f"/api/imports/{s['id']}", {"mapping": {"user3": {"action": "user", "user": str(family["son1"].pk)}}}, format="json")
    clients["dad"].post(f"/api/imports/{s['id']}/start")
    run_jobs()
    assert Document.objects.filter(owner=family["son1"]).count() == 2
    assert not Document.objects.filter(title="link").exists()
    assert _hashes(src) == before  # byte-identical and untouched
    assert (src / "user3" / "id.pdf").exists()


def test_at05_interrupted_server_import_resumes_without_duplicates(family, clients, tmp_path):
    from unittest import mock

    from apps.library import imports as I

    src = _tree(tmp_path)
    config.set_value("documents.import_roots", str(tmp_path / "nas"))
    s = clients["dad"].post("/api/imports", {"source_type": "server", "root": str(src)}, format="json").json()
    clients["dad"].put(f"/api/imports/{s['id']}", {"mapping": {"user3": {"action": "user", "user": str(family["son1"].pk)}}}, format="json")
    clients["dad"].post(f"/api/imports/{s['id']}/start")
    real = I.import_item
    calls = {"n": 0}

    def flaky(session, item, staged):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated interruption")
        return real(session, item, staged)

    with mock.patch.object(I, "import_item", side_effect=flaky):
        run_jobs()
    assert Document.objects.filter(owner=family["son1"]).count() == 1
    assert ImportItem.objects.filter(session_id=s["id"], status="failed").count() == 1
    clients["dad"].post(f"/api/imports/{s['id']}/retry")
    run_jobs()
    assert Document.objects.filter(owner=family["son1"]).count() == 2  # resumed, nothing duplicated
    assert ImportSession.objects.get(pk=s["id"]).status == "done"
