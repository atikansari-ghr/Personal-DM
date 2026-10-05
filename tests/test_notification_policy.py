"""Critical vs optional notifications, per-event channel choices, templates and bulk summaries (AT-67..AT-70)."""
from __future__ import annotations

import pytest
from conftest import make_text_pdf, personal_root, run_jobs
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core import config
from apps.library import services as S
from apps.library.models import Document, Folder
from apps.notify.models import Notification, OutboxMessage
from apps.security import alerts

pytestmark = pytest.mark.django_db

SECRETS = ("Sample-Passw0rd!", "123456", "JBSWY3DPEHPK3PXP", "sessionid", "csrftoken")


def _email_ready(user):
    config.set_value("smtp.enabled", True)
    config.set_value("smtp.host", "smtp.invalid")
    user.email = f"{user.username}@example.invalid"
    user.save()


def _prefs(client):
    return {e["key"]: e for e in client.get("/api/me/notification-preferences").json()["events"]}


def test_at67_critical_events_cannot_be_disabled_and_missing_destinations_are_flagged(family, clients):
    son1 = family["son1"]
    config.set_value("smtp.enabled", True)
    config.set_value("smtp.host", "smtp.invalid")  # email works, but son1 has no address
    ev = _prefs(clients["son1"])["security.passkey_added"]
    assert ev["critical"] and set(ev["locked"]) >= {"in_app", "email"}
    r = clients["son1"].put("/api/me/notification-preferences", {"preferences": {"security.passkey_added": ["in_app"]}}, format="json")
    assert r.status_code == 400 and "required" in r.json()["error"]
    # the event is delivered in-app; the required email is recorded as skipped with the reason, never as sent
    alerts.account_security(son1, "New passkey “Laptop” registered", event="passkey_added")
    assert Notification.objects.filter(user=son1, kind="security").count() == 1
    email = OutboxMessage.objects.get(user=son1, channel="email", kind="security")
    assert email.status == "skipped" and "email address" in email.last_error.lower()
    body = clients["son1"].get("/api/me/notification-preferences").json()
    assert any(p["channel"] == "email" for p in body["problems"])
    admin_view = clients["dad"].get("/api/notifications/problems").json()
    assert any(p["username"] == "son1" for p in admin_view["people"])
    assert clients["son1"].get("/api/notifications/problems").status_code == 403
    # administrators decide what is critical; once optional, the person may turn it off
    config.set_value("notifications.critical_events", [k for k in config.get("notifications.critical_events") if k != "security.passkey_added"])
    r = clients["son1"].put("/api/me/notification-preferences", {"preferences": {"security.passkey_added": []}}, format="json")
    assert r.status_code == 200
    alerts.account_security(son1, "New passkey “Phone” registered", event="passkey_added")
    assert Notification.objects.filter(user=son1, kind="security").count() == 1


def test_at67_admin_only_events_are_not_offered_to_members(family, clients):
    keys = set(_prefs(clients["son1"]))
    assert "backup.failed" not in keys and "security.failed_logins" not in keys
    assert {"backup.failed", "security.failed_logins"} <= set(_prefs(clients["dad"]))
    r = clients["son1"].put("/api/me/notification-preferences", {"preferences": {"backup.failed": []}}, format="json")
    assert r.status_code == 400


def test_at68_optional_event_channel_matrix_per_person(family, clients):
    mom, son2 = family["mom"], family["son2"]
    _email_ready(mom)
    _email_ready(son2)
    # mom: email only for "access given"; son2 keeps defaults (in-app + email)
    r = clients["mom"].put("/api/me/notification-preferences", {"preferences": {"document.shared": ["email"]}}, format="json")
    assert r.status_code == 200
    assert _prefs(clients["mom"])["document.shared"]["channels"] == ["email"]
    assert _prefs(clients["son2"])["document.shared"]["channels"] == ["in_app", "email"]
    folder = Folder.objects.create(parent=personal_root(family["son1"]), name="Trip", owner=family["son1"])
    for u in (mom, son2):
        clients["dad"].put(f"/api/folders/{folder.id}/permissions", {"user": str(u.pk), "caps": ["view"]}, format="json")
    assert not Notification.objects.filter(user=mom, kind="access").exists()
    assert OutboxMessage.objects.filter(user=mom, kind="access", channel="email").exists()
    assert Notification.objects.filter(user=son2, kind="access").exists()
    # optional "processing finished" is off by default and can be switched on
    son1 = family["son1"]
    clients["son1"].post("/api/documents", {"folder": str(personal_root(son1).id), "files": [SimpleUploadedFile("a.pdf", make_text_pdf("a"))]}, format="multipart")
    run_jobs()
    assert not Notification.objects.filter(user=son1, kind="processing").exists()
    clients["son1"].put("/api/me/notification-preferences", {"preferences": {"processing.completed": ["in_app"]}}, format="json")
    clients["son1"].post("/api/documents", {"folder": str(personal_root(son1).id), "files": [SimpleUploadedFile("b.pdf", make_text_pdf("b"))]}, format="multipart")
    run_jobs()
    assert Notification.objects.filter(user=son1, kind="processing").count() == 1
    # unknown events / channels are rejected
    assert clients["son1"].put("/api/me/notification-preferences", {"preferences": {"nope": ["in_app"]}}, format="json").status_code == 400
    assert clients["son1"].put("/api/me/notification-preferences", {"preferences": {"document.added": ["sms"]}}, format="json").status_code == 400


def test_at69_templates_are_detailed_but_secret_free_and_names_masked(family, clients):
    son1 = family["son1"]
    _email_ready(son1)
    folder = S.create_folder(actor=son1, parent=personal_root(son1), name="Passport Z9988776")
    files = [SimpleUploadedFile(f"scan{i}.pdf", make_text_pdf(f"s{i}")) for i in range(2)]
    clients["dad"].post("/api/documents", {"folder": str(folder.id), "files": files}, format="multipart")
    note = Notification.objects.get(user=son1, kind="document")
    assert "2 documents added" in note.title and "Passport Z9988776" in note.body  # in the app: full name
    ext = OutboxMessage.objects.get(user=son1, kind="document", channel="email")
    assert ext.body.startswith("Notification from ")
    assert "Account: son1 (Sam Sample)" in ext.body and "Date/time:" in ext.body and "Review: " in ext.body
    assert "1. scan0" in ext.body and "2. scan1" in ext.body
    assert "Z9988776" not in ext.body and "Z99•" in ext.body  # long numbers masked outside the app
    for secret in SECRETS:
        assert secret not in ext.body and secret not in ext.subject
    # names can be left out of external messages entirely
    config.set_value("notifications.include_names", False)
    clients["dad"].post("/api/documents", {"folder": str(folder.id), "files": [SimpleUploadedFile("x.pdf", make_text_pdf("x"))]}, format="multipart")
    latest = OutboxMessage.objects.filter(user=son1, kind="document", channel="email").order_by("-id").first()
    assert "(name hidden)" in latest.body and "x" not in latest.body.split("Files:")[1].split("Review:")[0].replace("(name hidden)", "")
    # the review link needs a signed-in, permitted session
    doc = Document.objects.filter(folder=folder).first()
    assert APIClient().get(f"/api/documents/{doc.id}").status_code in (401, 403)
    assert clients["son2"].get(f"/api/documents/{doc.id}").status_code == 404


def test_at69_login_alert_template_has_ip_country_method_device(family, clients):
    from apps.security.models import LoginEvent

    son1 = family["son1"]
    _email_ready(son1)
    ev = LoginEvent.objects.create(user=son1, username="son1", result=LoginEvent.SUCCESS, method="password+passkey",
                                   ip="5.42.0.7", country="SA", country_name="Saudi Arabia", browser="Firefox", os="Linux",
                                   device="desktop", flags=["new_country"])
    alerts.on_login_event(ev)
    msg = OutboxMessage.objects.get(user=son1, channel="email", kind="security")
    for part in ("IP address: 5.42.0.7", "Country: Saudi Arabia", "Sign-in method: password+passkey", "Device: Firefox · Linux · desktop"):
        assert part in msg.body
    # "every sign-in" information is optional and off by default
    assert not Notification.objects.filter(user=son1, title="New sign-in to your account").exists()


def test_at70_bulk_actions_send_one_summary(family, clients):
    son1, dad = family["son1"], family["dad"]
    _email_ready(son1)
    root = personal_root(son1)
    files = [SimpleUploadedFile(f"f{i}.pdf", make_text_pdf(f"f{i}")) for i in range(14)]
    clients["dad"].post("/api/documents", {"folder": str(root.id), "files": files}, format="multipart")
    assert Notification.objects.filter(user=son1, kind="document").count() == 1
    ext = OutboxMessage.objects.get(user=son1, kind="document", channel="email")
    assert "14 documents added" in ext.subject and "… and 4 more" in ext.body
    # an import of many files: one summary for the importer, one for the owner, no per-file processing messages
    entries = [{"path": f"Old/sub/f{i}.pdf", "size": 10} for i in range(12)]
    s = clients["dad"].post("/api/imports", {"source_type": "browser", "entries": entries}, format="json").json()
    clients["dad"].put(f"/api/imports/{s['id']}", {"mapping": {"Old": {"action": "user", "user": str(son1.pk)}}}, format="json")
    clients["dad"].post(f"/api/imports/{s['id']}/start")
    for e in entries:
        clients["dad"].post(f"/api/imports/{s['id']}/items", {"path": e["path"], "file": SimpleUploadedFile("f.pdf", make_text_pdf(e["path"]))}, format="multipart")
    run_jobs()
    assert Notification.objects.filter(user=dad, kind="import").count() == 1
    assert Notification.objects.filter(user=son1, kind="document").count() == 2  # the upload above + this import
    assert OutboxMessage.objects.filter(user=son1, kind="processing").count() == 0
    # bulk archive by someone else: one message per owner
    ids = [str(d.id) for d in Document.objects.filter(owner=son1)[:5]]
    clients["dad"].post("/api/documents/bulk", {"ids": ids, "action": "archive"}, format="json")
    archived = Notification.objects.filter(user=son1, kind="archive")
    assert archived.count() == 1 and "5 documents of yours archived" in archived.get().title
    assert "restore" in archived.get().body  # archive is clearly not deletion
