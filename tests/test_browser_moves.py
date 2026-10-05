"""Folder browser corrections: signed-in identity, validated file types, moving documents and folders (AT-61..AT-62,
AT-72..AT-75). All files are synthetic."""
from __future__ import annotations

import io
import threading
import zipfile

import pytest
from conftest import make_text_pdf, personal_root, upload
from django.db import connection
from PIL import Image

from apps.core.models import AuditEvent
from apps.library import permissions as P
from apps.library import services as S
from apps.library.models import AccessRule, Document, DocumentHistory, Folder


def _image(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 10), (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600
DICOM = b"\x00" * 128 + b"DICM" + b"\x00" * 200

FILES = [
    ("scan.pdf", make_text_pdf("Sample"), "pdf"),
    ("photo.jpg", _image("JPEG"), "jpeg"),
    ("photo.png", _image("PNG"), "png"),
    ("photo.webp", _image("WEBP"), "webp"),
    ("notes.txt", b"plain synthetic text\n", "text"),
    ("letter.docx", _zip({"[Content_Types].xml": b"<x/>", "word/document.xml": b"<w/>"}), "word"),
    ("budget.xlsx", _zip({"[Content_Types].xml": b"<x/>", "xl/workbook.xml": b"<w/>"}), "excel"),
    ("slides.pptx", _zip({"[Content_Types].xml": b"<x/>", "ppt/presentation.xml": b"<p/>"}), "powerpoint"),
    ("old.doc", OLE, "word"),
    ("old.xls", OLE, "excel"),
    ("bundle.zip", _zip({"a.txt": b"a"}), "archive"),
    ("study.dcm", DICOM, "dicom"),
    # Content decides, not the name: a PNG called .pdf is a PNG; a ".docx" that is not a Word container is "other".
    ("renamed.pdf", _image("PNG"), "png"),
    ("fake.docx", b"this is not a word file " * 10, "other"),
    ("mystery.bin", bytes(range(256)) * 4, "other"),
]


def test_at62_file_types_come_from_validated_content(family, clients):
    root = personal_root(family["son1"])
    for name, content, _ in FILES:
        r = upload(clients["son1"], root, name=name, content=content)
        assert r.status_code == 201, (name, r.content)
    rows = clients["son1"].get("/api/documents", {"folder": str(root.id), "limit": 100}).json()["documents"]
    got = {}
    for d in rows:
        detail = clients["son1"].get(f"/api/documents/{d['id']}").json()
        got[detail["current_version"]["original_name"]] = (d["file_kind"], d["file_label"], detail["current_version"]["file_kind"])
    for name, _, kind in FILES:
        assert got[name][0] == kind, (name, got[name])
        assert got[name][2] == kind
        assert got[name][1]  # readable label for screen readers / tooltips


def test_file_kind_for_older_office_rows_without_mime():
    from apps.library.filetypes import kind_for

    assert kind_for("application/octet-stream", "office", "Report.DOCX") == "word"
    assert kind_for("application/octet-stream", "office", "x.ods") == "excel"
    assert kind_for("application/octet-stream", "image", "a.heic") == "image"
    assert kind_for("", "other", "") == "other"


def test_at61_own_area_identity_without_leaking_other_trees(family, clients):
    son1, son2 = family["son1"], family["son2"]
    folders = clients["son1"].get("/api/folders").json()["folders"]
    roots = [f for f in folders if f["kind"] == "personal_root" and not f["path_only"]]
    assert [f["owner"] for f in roots] == [str(son1.pk)]
    mine = roots[0]
    assert mine["owner_user"]["display_name"] == son1.display_name
    assert "photo_version" in mine["owner_user"]
    assert str(personal_root(son2).id) not in {f["id"] for f in folders}
    # the administrator sees every member's area, each with its own identity
    admin = clients["dad"].get("/api/folders").json()["folders"]
    owners = {f["owner_user"]["display_name"] for f in admin if f["kind"] == "personal_root"}
    assert {u.display_name for u in family.values()} <= owners


def _doc(client, folder, name="doc.pdf"):
    r = upload(client, folder, name=name)
    assert r.status_code == 201
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


def test_at72_document_move_with_authorisation_history_and_audit(family, clients):
    son1, son2 = family["son1"], family["son2"]
    root = personal_root(son1)
    travel = S.create_folder(actor=son1, parent=root, name="Travel")
    doc = _doc(clients["son1"], root)
    r = clients["son1"].post("/api/documents/bulk", {"ids": [str(doc.id)], "action": "move", "value": str(travel.id)}, format="json")
    assert r.json()["succeeded"] == 1
    doc.refresh_from_db()
    assert doc.folder_id == travel.id
    assert DocumentHistory.objects.filter(document=doc, action="moved").exists()
    assert AuditEvent.objects.filter(action="document.move", target_id=str(doc.id)).exists()
    # moving to where it already is changes nothing and records nothing new
    n = DocumentHistory.objects.filter(document=doc, action="moved").count()
    clients["son1"].post("/api/documents/bulk", {"ids": [str(doc.id)], "action": "move", "value": str(travel.id)}, format="json")
    assert DocumentHistory.objects.filter(document=doc, action="moved").count() == n
    # someone else's area: refused, nothing changes, the other area is not revealed
    r = clients["son1"].post("/api/documents/bulk", {"ids": [str(doc.id)], "action": "move", "value": str(personal_root(son2).id)}, format="json")
    assert r.json()["failed"] == 1 and r.json()["results"][0]["error"]
    doc.refresh_from_db()
    assert doc.folder_id == travel.id
    # a person who can only view cannot move it
    AccessRule.objects.create(folder=travel, user=son2, caps=P.VIEW)
    r = clients["son2"].post("/api/documents/bulk", {"ids": [str(doc.id)], "action": "move", "value": str(personal_root(son2).id)}, format="json")
    assert r.json()["failed"] == 1
    doc.refresh_from_db()
    assert doc.folder_id == travel.id


def test_at74_document_never_moved_into_archived_folder(family, clients):
    son1 = family["son1"]
    root = personal_root(son1)
    old = S.create_folder(actor=son1, parent=root, name="Old")
    doc = _doc(clients["son1"], root)
    S.archive_folder(actor=family["dad"], folder=old)
    r = clients["dad"].post("/api/documents/bulk", {"ids": [str(doc.id)], "action": "move", "value": str(old.id)}, format="json")
    assert r.json()["failed"] == 1 and "archived" in r.json()["results"][0]["error"].lower()
    doc.refresh_from_db()
    assert doc.folder_id == root.id


def test_at73_folder_move_keeps_hierarchy_and_rejects_bad_targets(family, clients):
    son1 = family["son1"]
    dad = clients["dad"]
    root = personal_root(son1)
    edu = S.create_folder(actor=son1, parent=root, name="Education")
    school = S.create_folder(actor=son1, parent=edu, name="School")
    grade = S.create_folder(actor=son1, parent=school, name="Grade 10")
    doc = _doc(clients["son1"], grade, "certificate.pdf")
    archive = S.create_folder(actor=son1, parent=root, name="Archive box")

    r = dad.patch(f"/api/folders/{school.id}", {"parent": str(archive.id)}, format="json")
    assert r.status_code == 200 and r.json()["parent"] == str(archive.id)
    grade.refresh_from_db()
    doc.refresh_from_db()
    assert grade.parent_id == school.id and doc.folder_id == grade.id  # the subtree travels intact
    assert AuditEvent.objects.filter(action="folder.move", target_id=str(school.id)).exists()

    # into itself / its own descendant
    for target in (school, grade):
        r = dad.patch(f"/api/folders/{school.id}", {"parent": str(target.id)}, format="json")
        assert r.status_code == 403 and "itself" in r.json()["error"]
    # name conflict at the destination
    S.create_folder(actor=son1, parent=edu, name="School")
    r = dad.patch(f"/api/folders/{school.id}", {"parent": str(edu.id)}, format="json")
    assert r.status_code == 403 and "already has a folder" in r.json()["error"]
    # a refused move inside the same request also undoes the rename (atomic)
    r = dad.patch(f"/api/folders/{school.id}", {"name": "Renamed", "parent": str(grade.id)}, format="json")
    assert r.status_code == 403
    school.refresh_from_db()
    assert school.name == "School" and school.parent_id == archive.id
    # top-level folders stay where they are
    r = dad.patch(f"/api/folders/{root.id}", {"parent": str(edu.id)}, format="json")
    assert r.status_code == 403
    assert Folder.objects.get(pk=root.id).parent_id == root.parent_id


def test_at73_member_without_rights_cannot_move_folders(family, clients):
    son1 = family["son1"]
    edu = S.create_folder(actor=son1, parent=personal_root(son1), name="Education")
    r = clients["son2"].patch(f"/api/folders/{edu.id}", {"parent": str(personal_root(family["son2"]).id)}, format="json")
    assert r.status_code == 404  # not even visible
    edu.refresh_from_db()
    assert edu.parent_id == personal_root(son1).id


@pytest.mark.django_db(transaction=True)
def test_at74_concurrent_opposite_moves_cannot_create_a_cycle(family):
    if connection.vendor != "postgresql":
        pytest.skip("advisory locks need PostgreSQL")
    dad, son1 = family["dad"], family["son1"]
    root = personal_root(son1)
    a = S.create_folder(actor=son1, parent=root, name="A")
    b = S.create_folder(actor=son1, parent=root, name="B")
    barrier = threading.Barrier(2)
    outcome: dict[str, str] = {}

    def move(name, folder, target):
        from django.db import connections

        try:
            ctx = P.AccessContext.build(dad)
            barrier.wait()
            S.move_folder(ctx=ctx, actor=dad, folder=folder, new_parent=target)
            outcome[name] = "moved"
        except S.DomainError as exc:
            outcome[name] = str(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=move, args=("a", a, b)), threading.Thread(target=move, args=("b", b, a))]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert sorted(v == "moved" for v in outcome.values()) == [False, True], outcome
    a.refresh_from_db()
    b.refresh_from_db()
    # exactly one is inside the other, and the pair is still attached to the member's area
    assert (a.parent_id == b.id) != (b.parent_id == a.id)
    assert root.id in (a.parent_id, b.parent_id)


def test_at74_member_move_that_would_widen_access_is_refused(family, clients):
    son1 = family["son1"]
    shared = Folder.objects.get(name="Shared family")
    AccessRule.objects.create(folder=shared, user=son1, caps=P.VIEW | P.UPLOAD | P.ORGANIZE)
    AccessRule.objects.create(folder=shared, user=family["son2"], caps=P.VIEW)  # someone else can see "Shared family"
    doc = _doc(clients["son1"], personal_root(son1), "private.pdf")
    r = clients["son1"].post("/api/documents/bulk", {"ids": [str(doc.id)], "action": "move", "value": str(shared.id)}, format="json")
    assert r.json()["failed"] == 1 and "other people access" in r.json()["results"][0]["error"]
    doc.refresh_from_db()
    assert doc.folder_id == personal_root(son1).id
    # the main administrator may do it deliberately
    r = clients["dad"].post("/api/documents/bulk", {"ids": [str(doc.id)], "action": "move", "value": str(shared.id)}, format="json")
    assert r.json()["succeeded"] == 1
