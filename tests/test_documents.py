"""AT-06, AT-09, AT-13, AT-18, AT-23 and document detail behaviour."""
import hashlib
from datetime import timedelta

import pytest
from conftest import make_text_pdf, personal_root, run_jobs, upload
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditEvent
from apps.library import storage
from apps.library.models import Document, DocumentType, DocumentVersion, Folder, ShareLink
from apps.library.services import suggest_emoji

pytestmark = pytest.mark.django_db


def _upload_one(client, folder, **kw):
    r = upload(client, folder, **kw)
    assert r.status_code == 201, r.content
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


def test_at06_identical_uploads_stay_separate_and_never_overwrite(family, clients):
    root = personal_root(family["son1"])
    content = make_text_pdf("Identical synthetic content")
    a = _upload_one(clients["son1"], root, name="same.pdf", content=content)
    b = _upload_one(clients["son1"], root, name="same.pdf", content=content)
    assert a.id != b.id
    va, vb = a.current_version, b.current_version
    assert va.sha256 == vb.sha256 and va.storage_path != vb.storage_path
    pa, pb = storage.resolve_original(va.storage_path), storage.resolve_original(vb.storage_path)
    assert pa.exists() and pb.exists() and pa.read_bytes() == pb.read_bytes() == content
    assert oct(pa.stat().st_mode)[-3:] == "440"  # originals are write-once


def test_original_is_byte_identical_and_downloads_are_audited(family, clients):
    content = make_text_pdf("Byte for byte")
    d = _upload_one(clients["son1"], personal_root(family["son1"]), name="x.pdf", content=content)
    run_jobs()
    r = clients["son1"].get(f"/api/documents/{d.id}/file", {"download": "1"})
    body = b"".join(r.streaming_content)
    assert hashlib.sha256(body).hexdigest() == hashlib.sha256(content).hexdigest()
    assert AuditEvent.objects.filter(action="document.download", target_id=str(d.id)).exists()
    # Range request support (streaming / resumable)
    r = clients["son1"].get(f"/api/documents/{d.id}/file", HTTP_RANGE="bytes=0-9")
    assert r.status_code == 206 and b"".join(r.streaming_content) == content[:10]


def test_at09_versions_vs_renewals(family, clients):
    son1 = family["son1"]
    ptype = DocumentType.objects.get(name="Passport")
    d = _upload_one(clients["son1"], personal_root(son1), name="passport-scan.pdf", doc_type=ptype.id)
    run_jobs()
    assert d.title == "Sam Sample Passport (dates needed)"  # no guessed years
    # confirm dates -> generated name uses confirmed years only
    clients["son1"].post(f"/api/documents/{d.id}/fields", {"key": "issue_date", "value": "2016-10-19"}, format="json")
    clients["son1"].post(f"/api/documents/{d.id}/fields", {"key": "expiry_date", "value": "2026-10-18"}, format="json")
    d.refresh_from_db()
    assert d.title == "Sam Sample Passport (2016–2026)"
    # better scan: new immutable version, same record and metadata
    f = SimpleUploadedFile("better.pdf", make_text_pdf("Better scan"))
    r = clients["son1"].post(f"/api/documents/{d.id}/versions", {"file": f, "comment": "clearer scan"}, format="multipart")
    assert r.status_code == 201
    d.refresh_from_db()
    assert d.versions.count() == 2 and d.current_version.number == 2 and d.expiry_date.year == 2026
    v1 = d.versions.get(number=1)
    assert storage.resolve_original(v1.storage_path).exists()  # original kept
    # renewal: separate linked record; old one keeps its history
    f = SimpleUploadedFile("new-passport.pdf", make_text_pdf("Renewed passport"))
    r = clients["son1"].post(f"/api/documents/{d.id}/renew", {"file": f}, format="multipart")
    assert r.status_code == 201, r.content
    new = Document.objects.get(pk=r.json()["id"])
    assert new.id != d.id and new.renews_id == d.id and new.doc_type_id == ptype.id
    clients["son1"].post(f"/api/documents/{new.id}/fields", {"key": "issue_date", "value": "2026-09-01"}, format="json")
    clients["son1"].post(f"/api/documents/{new.id}/fields", {"key": "expiry_date", "value": "2036-08-31"}, format="json")
    new.refresh_from_db()
    d.refresh_from_db()
    assert new.title == "Sam Sample Passport (2026–2036)" and d.title == "Sam Sample Passport (2016–2026)"
    detail = clients["son1"].get(f"/api/documents/{d.id}").json()
    assert detail["renewed_by"][0]["id"] == str(new.id)


def test_impossible_dates_are_flagged(family, clients):
    d = _upload_one(clients["son1"], personal_root(family["son1"]))
    run_jobs()
    clients["son1"].post(f"/api/documents/{d.id}/fields", {"key": "issue_date", "value": "2030-01-01"}, format="json")
    clients["son1"].post(f"/api/documents/{d.id}/fields", {"key": "expiry_date", "value": "2020-01-01"}, format="json")
    d.refresh_from_db()
    assert d.review_flags and d.state == Document.NEEDS_REVIEW


def test_document_number_is_masked_and_copy_is_audited(family, clients):
    d = _upload_one(clients["son1"], personal_root(family["son1"]))
    clients["son1"].post(f"/api/documents/{d.id}/fields", {"key": "document_number", "value": "Z1234567"}, format="json")
    detail = clients["son1"].get(f"/api/documents/{d.id}").json()
    num = next(f for f in detail["fields"] if f["key"] == "document_number")
    assert num["value"].endswith("4567") and "Z123" not in num["value"]
    r = clients["son1"].get(f"/api/documents/{d.id}/fields/document_number/reveal")
    assert r.json()["value"] == "Z1234567"
    ev = AuditEvent.objects.get(action="document.field_copy")
    assert "Z1234567" not in str(ev.context)
    hist = detail["history"]
    assert all("Z1234567" not in str(h["changes"]) for h in hist)


def test_at13_emoji_suggestions_overrides_and_rename(family, clients):
    assert suggest_emoji("Travel") == "✈️" and suggest_emoji("Passport") == "🛂" and suggest_emoji("Visa") == "🛃"
    assert suggest_emoji("House Documents") == "🏠" and suggest_emoji("Medical") == "🩺" and suggest_emoji("Misc") == "📁"
    root = personal_root(family["son1"])
    r = clients["son1"].post("/api/folders", {"parent": str(root.id), "name": "Travel"}, format="json")
    fid = r.json()["id"]
    assert r.json()["emoji"] == "✈️"
    r = clients["son1"].patch(f"/api/folders/{fid}", {"emoji": "🌍"}, format="json")
    assert r.json()["emoji"] == "🌍"
    r = clients["son1"].patch(f"/api/folders/{fid}", {"name": "Trips 2026"}, format="json")
    assert r.json()["emoji"] == "🌍"  # custom emoji survives rename
    caps_before = r.json()["caps"]
    r = clients["son1"].patch(f"/api/folders/{fid}", {"emoji": ""}, format="json")
    assert r.json()["emoji"] == "✈️" and r.json()["caps"] == caps_before  # emoji never affects access
    # emoji appears in tree listing
    tree = clients["son1"].get("/api/folders").json()["folders"]
    assert any(f["id"] == fid and f["emoji"] == "✈️" for f in tree)


def test_at23_archive_restore_purge(family, clients):
    d = _upload_one(clients["son1"], personal_root(family["son1"]))
    run_jobs()
    s = clients["son1"].post(f"/api/documents/{d.id}/shares", {"days": 3}, format="json").json()
    # owner lacks archive capability by default -> admin archives
    assert clients["son1"].post(f"/api/documents/{d.id}/archive").status_code == 403
    assert clients["dad"].post(f"/api/documents/{d.id}/archive").status_code == 200
    assert clients["son1"].get(f"/api/documents/{d.id}").status_code == 404
    assert clients["son1"].get("/api/documents").json()["total"] == 0
    assert ShareLink.objects.get(pk=s["id"]).revoked_at is not None
    assert APIClient().get(f"/s/{s['url'].rsplit('/', 1)[1]}").status_code == 404
    assert clients["son1"].get("/api/documents", {"archived": "1"}).status_code == 403
    assert clients["dad"].get("/api/documents", {"archived": "1"}).json()["total"] == 1
    assert clients["son1"].post(f"/api/documents/{d.id}/restore").status_code == 403
    assert clients["dad"].post(f"/api/documents/{d.id}/restore").status_code == 200
    assert clients["son1"].get(f"/api/documents/{d.id}").status_code == 200
    # purge requires archive + typed confirmation; removes files and versions
    clients["dad"].post(f"/api/documents/{d.id}/archive")
    path = storage.resolve_original(d.current_version.storage_path)
    assert clients["dad"].delete(f"/api/documents/{d.id}", {"confirm": "wrong"}, format="json").status_code == 400
    r = clients["dad"].delete(f"/api/documents/{d.id}", {"confirm": d.title}, format="json")
    assert r.status_code == 204
    assert not Document.objects.filter(pk=d.id).exists() and not DocumentVersion.objects.filter(document_id=d.id).exists()
    assert not path.exists()
    assert AuditEvent.objects.filter(action="document.purge", target_id=str(d.id)).exists()


def test_at18_share_links(family, clients):
    d = _upload_one(clients["son1"], personal_root(family["son1"]), content=make_text_pdf("Shared synthetic"))
    run_jobs()
    r = clients["son1"].post(f"/api/documents/{d.id}/shares", {"days": 2, "password": "open-sesame"}, format="json")
    assert r.status_code == 201
    share = r.json()
    token = share["url"].rsplit("/", 1)[1]
    assert len(token) >= 40
    link = ShareLink.objects.get(pk=share["id"])
    assert token not in link.token_hash and link.password_hash.startswith(("md5$", "argon2", "pbkdf2"))
    pub = APIClient(enforce_csrf_checks=False)
    assert b"Password required" in pub.get(f"/s/{token}").content
    assert pub.get(f"/s/{token}/file").status_code == 404  # file needs the password first
    for _ in range(5):
        pub.post(f"/s/{token}", {"password": "nope"})
    r = pub.post(f"/s/{token}", {"password": "open-sesame"})
    assert b"Too many attempts" in r.content  # rate limited even with the right password
    pub2 = APIClient(REMOTE_ADDR="10.0.0.2")  # a different visitor is not blocked by the first one's attempts
    r = pub2.post(f"/s/{token}", {"password": "open-sesame"})
    assert b">Download</a>" in r.content
    assert pub2.get(f"/s/{token}/file", {"download": "1"}).status_code == 200
    # the link gives access only to this document version — not other docs or the API
    assert pub2.get(f"/api/documents/{d.id}").status_code in (401, 403)
    # new version does not change what the link serves (pinned)
    f = SimpleUploadedFile("v2.pdf", make_text_pdf("Second version"))
    clients["son1"].post(f"/api/documents/{d.id}/versions", {"file": f}, format="multipart")
    link.refresh_from_db()
    assert link.version.number == 1
    # revoke
    assert clients["son1"].delete(f"/api/shares/{share['id']}").status_code == 200
    assert pub2.get(f"/s/{token}").status_code == 404
    # expiry
    r = clients["son1"].post(f"/api/documents/{d.id}/shares", {"days": 1}, format="json").json()
    ShareLink.objects.filter(pk=r["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert APIClient().get(f"/s/{r['url'].rsplit('/', 1)[1]}").status_code == 404
    # creator losing share permission disables their links
    r = clients["son1"].post(f"/api/documents/{d.id}/shares", {"days": 1}, format="json").json()
    from apps.library.models import AccessRule

    AccessRule.objects.filter(user=family["son1"]).update(caps=1)
    assert APIClient().get(f"/s/{r['url'].rsplit('/', 1)[1]}").status_code == 404
    assert "open-sesame" not in str(list(AuditEvent.objects.values_list("context", flat=True)))


def test_bulk_edit_reports_partial_failures(family, clients):
    mine = _upload_one(clients["son1"], personal_root(family["son1"]))
    other = _upload_one(clients["son2"], personal_root(family["son2"]))
    r = clients["son1"].post("/api/documents/bulk", {"ids": [str(mine.id), str(other.id)], "action": "tag_add", "value": "trip"}, format="json")
    assert r.json()["succeeded"] == 1 and r.json()["failed"] == 1
    assert mine.tags.filter(name="trip").exists() and not other.tags.exists()


def test_uploaded_executable_is_stored_but_never_processed(family, clients):
    d = _upload_one(clients["son1"], personal_root(family["son1"]), name="tool.exe", content=b"MZ\x90\x00fake-binary")
    run_jobs()
    d.refresh_from_db()
    assert d.current_version.format_class == "other" and d.state == Document.UNSUPPORTED
    r = clients["son1"].get(f"/api/documents/{d.id}/file")
    assert r["Content-Type"] == "application/octet-stream" and r["Content-Disposition"].startswith("attachment")


def test_upload_requires_folder_upload_permission(family, clients):
    shared = Folder.objects.get(name="Shared family")
    r = upload(clients["son1"], shared)
    assert r.status_code == 404  # not even visible
