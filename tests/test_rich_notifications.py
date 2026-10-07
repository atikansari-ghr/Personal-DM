"""Rich notification formatting, icons, templates and actions (Change Set O, AT-176..AT-193, AT-195).

Synthetic people and documents only; the push service, SMTP and Telegram are mocked. AT-194 (cross-device UI) is
covered by tests/e2e/parity.mjs.
"""
import base64
import json
from datetime import date, timedelta
from unittest import mock

import pytest
from conftest import personal_root
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.test import override_settings
from django.utils import timezone

from apps.core import config
from apps.core.models import AuditEvent
from apps.library.models import Document, DocumentType
from apps.library.services import set_field
from apps.notify import catalog, events, expiry, rich, webpush
from apps.notify.models import Notification, NotificationTemplate, OutboxMessage, PushSubscription, TelegramLink

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 3)
EVIL = "<script>alert(1)</script> *bold* _x_ [link](http://evil.example) & <b>"


def _channels(user, *chans):
    config.set_value("smtp.enabled", True)
    config.set_value("smtp.host", "smtp.invalid")
    config.set_value("telegram.enabled", True)
    config.set_value("telegram.bot_token", "123:synthetic")
    TelegramLink.objects.get_or_create(user=user, defaults={"chat_id": "42"})
    user.email = f"{user.username}@example.invalid"
    user.save()
    config.set_user(user, "me.channels", list(chans or ("in_app", "email", "telegram")))


def _passport(owner, days=45, number="X1234567", title="p"):
    ptype = DocumentType.objects.get(name="Passport")
    d = Document.objects.create(folder=personal_root(owner), owner=owner, title=title, doc_type=ptype, state=Document.READY)
    set_field(actor=owner, doc=d, key="document_number", value=number)
    set_field(actor=owner, doc=d, key="full_name", value="Sample Person")
    set_field(actor=owner, doc=d, key="expiry_date", value=(TODAY + timedelta(days=days)).isoformat())
    d.refresh_from_db()
    return d


def _subscribe(user, endpoint="https://fcm.googleapis.com/fcm/send/sample"):
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    PushSubscription.objects.create(user=user, endpoint=endpoint, p256dh=webpush.b64u(pub), auth=webpush.b64u(auth))
    return key, auth


def test_at176_one_event_renders_every_channel(family):
    son = family["son1"]
    _channels(son)
    config.set_user(son, "me.notification_prefs", {"expiry.reminder": ["in_app", "email", "telegram", "push"]})
    _subscribe(son)
    d = _passport(son)
    expiry.run_expiry_scan(TODAY)
    note = Notification.objects.get(user=son, document=d)
    out = {m.channel: m for m in OutboxMessage.objects.filter(user=son, document=d).exclude(channel="in_app")}
    assert set(out) == {"email", "telegram", "push"}
    assert note.event == "expiry.reminder" and note.category == "expiry" and note.severity == "warning" and note.icon == "calendar"
    assert {a["key"] for a in note.data["actions"]} >= {"open_document", "folder", "reminders", "snooze"}
    assert any(x["label"] == "Expiry date" for x in note.data["details"])
    # the same title / severity everywhere, rendered by channel renderers from one structured message
    assert note.title in out["email"].subject and note.title in out["telegram"].payload["text"].replace("&#x27;", "'")
    assert out["push"].payload["title"].endswith("Passport Expiry Alert") and all(m.event == "expiry.reminder" for m in out.values())
    assert {m.severity for m in out.values()} == {"warning"}


def test_at177_html_email_with_plain_text_fallback(family):
    son = family["son1"]
    _channels(son)
    d = _passport(son, days=5)
    expiry.run_expiry_scan(TODAY)
    em = OutboxMessage.objects.get(user=son, document=d, channel="email")
    assert em.severity == "critical" and "Critical" in em.html and "Personal Documents Management System" in em.html
    assert "Expiry date" in em.html and "Open Document" in em.html and "Go to Folder" in em.html
    assert f'href="http://localhost:8000/documents/{d.id}"' in em.html
    assert "<script" not in em.html.lower() and "<img" not in em.html.lower()  # no JavaScript, no images / trackers
    assert em.body.startswith("Notification from ") and "Review: http" in em.body and "Days left: 5 days" in em.body
    with mock.patch("apps.notify.mailer.send_mail_now") as sm:
        expiry.deliver_outbox()
    assert sm.call_args.kwargs["html"] == em.html  # multipart: text + HTML
    # security and system events render the same way
    events.notify(son, "security.new_country", key="t1", title="Sign-in from a new country",
                  facts=[("IP address", "203.0.113.9"), ("Country", "Testland")], link="/settings/account?tab=security")
    events.backup_failed("NAS not mounted")
    sec = OutboxMessage.objects.get(user=son, event="security.new_country", channel="email")
    assert "Review Activity" in sec.html and "203.0.113.9" in sec.html and "Warning" in sec.html
    admin = family["dad"]
    bk = Notification.objects.get(user=admin, event="backup.failed")
    assert bk.severity == "critical" and bk.data["actions"][0]["path"] == "/settings/storage"


def test_at178_telegram_html_escaping_and_buttons(family):
    son = family["son1"]
    _channels(son)
    d = _passport(son, title=EVIL)
    expiry.run_expiry_scan(TODAY)
    tg = OutboxMessage.objects.get(user=son, document=d, channel="telegram")
    assert tg.payload["parse_mode"] == "HTML" and "📅" in tg.payload["text"]
    # http origin: no buttons, links written into the text
    assert "reply_markup" not in tg.payload and "🔗" in tg.payload["text"]
    calls = []
    with mock.patch("apps.notify.telegram._call", side_effect=lambda m, **p: calls.append(p) or {"ok": True, "result": {"message_id": 7}}):
        expiry.deliver_outbox()
    assert calls[0]["parse_mode"] == "HTML" and calls[0]["chat_id"] == "42"
    tg.refresh_from_db()
    assert tg.status == "sent" and tg.provider_ref == "7"
    # https origin: inline URL buttons; user text escaped
    config.set_user(son, "me.notification_prefs", {"document.shared": ["in_app", "email", "telegram"]})
    with override_settings(PUBLIC_ORIGIN="https://docs.example.test"):
        events.notify(son, "document.shared", key="t2", title=lambda n: f"Access to “{n(EVIL)}”", link=f"/documents/{d.id}",
                      context={"document_id": str(d.id)})
    p = OutboxMessage.objects.get(user=son, event="document.shared", channel="telegram").payload
    assert p["reply_markup"]["inline_keyboard"][0][0]["url"] == f"https://docs.example.test/documents/{d.id}"
    assert "<script>" not in p["text"] and "&lt;script&gt;" in p["text"]
    # rejected rich form falls back to plain text, never lost
    from apps.notify import telegram

    sent = []

    def flaky(method, **params):
        if "parse_mode" in params:
            raise telegram.TelegramError("Bad Request: can't parse entities")
        sent.append(params)
        return {"ok": True, "result": {"message_id": 8}}

    with mock.patch("apps.notify.telegram._call", side_effect=flaky):
        telegram.send("42", "plain", {"text": "<b>x", "parse_mode": "HTML"})
    assert sent[0]["text"] == "plain"


def test_at179_notification_center_filters_unread_and_cursor(family, clients):
    son, c = family["son1"], clients["son1"]
    for i in range(35):
        events.notify(son, "document.added", key=f"n{i}", title=f"{i} added", link="/folders")
    events.notify(son, "security.new_country", key="sec", title="New country", link="/settings/account?tab=security")
    r = c.get("/api/notifications?limit=30").json()
    assert len(r["notifications"]) == 30 and r["next"] and r["unread"] == 36
    first = r["notifications"][0]
    assert first["category"] == "security" and first["severity"] == "warning" and first["icon"] == "globe" and first["actions"]
    page2 = c.get(f"/api/notifications?limit=30&before={r['next']}").json()["notifications"]
    assert len(page2) == 6 and not {n["id"] for n in page2} & {n["id"] for n in r["notifications"]}
    assert {n["category"] for n in c.get("/api/notifications?category=security").json()["notifications"]} == {"security"}
    assert len(c.get("/api/notifications?severity=success").json()["notifications"]) == 30  # default page
    c.post("/api/notifications/read", {"ids": [first["id"]]}, format="json")
    assert c.get("/api/notifications?status=unread&limit=100").json()["unread"] == 35
    c.post("/api/notifications/read", {"ids": [first["id"]], "unread": True}, format="json")
    assert c.get("/api/notifications").json()["unread"] == 36
    # only one's own notifications
    assert clients["son2"].get("/api/notifications").json()["notifications"] == []
    assert clients["son2"].post("/api/notifications/read", {"ids": [first["id"]]}, format="json").json()["unread"] == 0
    assert Notification.objects.get(pk=first["id"]).read_at is None


def test_at180_critical_events_stay_in_the_center(family, clients):
    admin = family["dad"]
    events.backup_failed("disk full")
    clients["dad"].post("/api/notifications/read", {}, format="json")  # banners gone, everything read
    r = clients["dad"].get("/api/notifications?severity=critical").json()["notifications"]
    assert r and r[0]["title"] == "Backup failed" and r[0]["read"] is True
    assert Notification.objects.filter(user=admin, event="backup.failed").count() == 1


def test_at181_push_privacy_encryption_and_endpoint_allowlist(family, clients):
    son, c = family["son1"], clients["son1"]
    key, auth = _subscribe(son)
    d = _passport(son, days=30, title="Passport Q9988776 Sample")
    msg = expiry.expiry_message(d, 30, son)
    p = rich.render_push(msg, son)
    assert p["title"].endswith("Passport Expiry Alert") and "30 days" in p["body"]
    assert "X1234567" not in json.dumps(p) and "Sample Person" not in json.dumps(p) and "Q9988776" not in json.dumps(p)
    config.set_user(son, "me.push_preview", "minimal")
    assert "Passport" not in json.dumps(rich.render_push(msg, son))
    config.set_user(son, "me.push_preview", "detailed")
    config.set_value("notifications.include_document_number", True)
    assert "1234567" not in json.dumps(rich.render_push(msg, son))  # never numbers on lock screens
    # encrypted with the subscriber's keys (decryptable only by the browser), VAPID-signed
    captured = {}

    def post(url, data, headers, **kw):
        captured.update(url=url, data=data, headers=headers)
        return mock.Mock(status_code=201, headers={"Location": "https://fcm.googleapis.com/msg/1"})

    with mock.patch("apps.notify.webpush.requests.post", side_effect=post):
        webpush.deliver(son, {"title": "t", "body": "b", "url": "/notifications"})
    import http_ece

    plain = http_ece.decrypt(captured["data"], private_key=key, auth_secret=auth, version="aes128gcm")
    assert json.loads(plain)["title"] == "t"
    assert captured["headers"]["Content-Encoding"] == "aes128gcm" and captured["headers"]["Authorization"].startswith("vapid ")
    # subscriptions only for known push services (no calls to internal addresses)
    good = {"endpoint": "https://updates.push.services.mozilla.com/wpush/v2/x", "keys": {"p256dh": webpush.b64u(b"\x04" + b"1" * 64), "auth": webpush.b64u(b"a" * 16)}}
    assert c.post("/api/notifications/push", good, format="json").status_code == 201
    for bad in ("http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://evil.example/push", "https://user@fcm.googleapis.com/x"):
        assert c.post("/api/notifications/push", {**good, "endpoint": bad}, format="json").status_code == 400
    # a revoked subscription (410) is removed
    with mock.patch("apps.notify.webpush.requests.post", return_value=mock.Mock(status_code=410, headers={})):
        with pytest.raises(webpush.PushError):
            webpush.deliver(son, {"title": "t"})
    assert not PushSubscription.objects.filter(user=son, endpoint__contains="fcm").exists()


def test_at182_event_specific_actions(family):
    acts = lambda e, **k: [a.key for a in events.default_actions(e, **k)]  # noqa: E731
    assert acts("document.added", context={"document_id": "1", "folder_id": "2"}) == ["view_document", "folder"]
    assert acts("security.new_ip") == ["review_activity", "sessions", "change_password"]
    assert acts("antivirus.threat") == ["security_event", "security_health"]
    assert acts("security.operations") == ["system_status", "update_logs"]
    d = _passport(family["son1"])
    m = expiry.expiry_message(d, 45, family["son1"])
    assert [a.key for a in m.actions] == ["open_document", "folder", "reminders", "snooze"]
    # snooze exists only in the app
    _subj, text, html_doc = rich.render_email(m, family["son1"])
    assert "Snooze" not in html_doc and "Snooze" not in text
    assert "Snooze" not in json.dumps(rich.render_telegram(m, family["son1"]))


def test_at183_quarantine_release_never_leaves_the_app(family):
    from apps.security import antivirus

    admin = family["dad"]
    _channels(admin)
    antivirus._alert("antivirus.threat", "t-threat", "Malware detected — file quarantined", ["Eicar-Test-Signature"])
    antivirus._alert("antivirus.released", "t-rel", "Quarantined file released", ["by the main administrator"])
    rows = OutboxMessage.objects.filter(user=admin, event__startswith="antivirus.")
    assert rows.exists()
    for m in rows:
        blob = (m.body + m.html + json.dumps(m.payload)).lower()
        assert "/release" not in blob and "release from quarantine" not in blob
    for n in Notification.objects.filter(user=admin, event__startswith="antivirus."):
        assert all("release" not in a["path"] for a in n.data["actions"])
    assert not rich.safe_path("/api/security/antivirus/1/release") and not rich.safe_path("/settings/security?view=antivirus&release=1")
    assert not rich.safe_path("//evil.example/x") and not rich.safe_path("https://evil.example/")


def test_at184_template_manager(family, clients):
    son, admin = family["son1"], clients["dad"]
    assert clients["son1"].get("/api/notifications/templates").status_code == 403
    lst = admin.get("/api/notifications/templates").json()
    assert {"expiry.reminder", "antivirus.threat"} <= {e["key"] for e in lst["events"]} and "document_type" in lst["placeholders"]
    r = admin.put("/api/notifications/templates/expiry.reminder",
                  {"title": "{document_type} renewal due in {days_remaining} days", "icon": "reminder",
                   "action_labels": {"open_document": "Renew now"}}, format="json")
    assert r.status_code == 200
    _channels(son)
    d = _passport(son, days=30)
    expiry.run_expiry_scan(TODAY)
    n = Notification.objects.get(user=son, document=d)
    assert n.title == "Passport renewal due in 30 days" and n.icon == "bell"
    assert n.data["actions"][0]["label"] == "Renew now"
    em = OutboxMessage.objects.get(user=son, document=d, channel="email")
    assert "Passport renewal due in 30 days" in em.subject and "Renew now" in em.html
    bad = admin.put("/api/notifications/templates/expiry.reminder", {"title": "{password}"}, format="json")
    assert bad.status_code == 400 and "unknown placeholder" in bad.json()["error"]
    assert admin.put("/api/notifications/templates/expiry.reminder", {"title": "{{nested}}"}, format="json").status_code == 400
    assert admin.put("/api/notifications/templates/expiry.reminder", {"icon": "skull"}, format="json").status_code == 400
    assert admin.put("/api/notifications/templates/expiry.reminder", {"action_labels": {"release": "Release"}}, format="json").status_code == 400
    assert admin.delete("/api/notifications/templates/expiry.reminder").json()["reset"] is True
    assert not NotificationTemplate.objects.filter(event="expiry.reminder").exists()
    assert AuditEvent.objects.filter(action="notifications.template_update").exists()


def test_at185_injection_is_escaped_everywhere(family, clients):
    son = family["son1"]
    _channels(son)
    config.set_user(son, "me.notification_prefs", {"document.shared": ["in_app", "email", "telegram"]})
    clients["dad"].put("/api/notifications/templates/document.shared", {"summary": "<img src=x onerror=alert(1)> {document_name}"},
                       format="json")
    events.notify(son, "document.shared", key="inj", title=lambda n: f"Shared “{n(EVIL)}”", link="/shared",
                  context={"document_name": EVIL}, facts=[("File", EVIL)])
    em = OutboxMessage.objects.get(user=son, event="document.shared", channel="email")
    tg = OutboxMessage.objects.get(user=son, event="document.shared", channel="telegram")
    for blob in (em.html, tg.payload["text"]):
        assert "<script>" not in blob and "<img" not in blob and "onerror=alert(1)>" not in blob
        assert "&lt;script&gt;" in blob and "&lt;img" in blob
    assert "[link](http://evil.example)" in em.html  # Markdown is plain text (HTML parse mode), never a link


def test_at186_preview_and_test_messages(family, clients):
    admin, a = family["dad"], clients["dad"]
    r = a.post("/api/notifications/templates/expiry.reminder/preview", {"draft": {"title": "Draft {document_type}"}}, format="json").json()
    assert r["email"]["subject"].endswith("[TEST] Draft Passport") and "<html" in r["email"]["html"]
    assert r["telegram"]["text"] and r["in_app"]["title"] == "Draft Passport" and r["push"]["title"]
    assert "X1234567" not in json.dumps(r)  # sample number hidden by default
    assert not NotificationTemplate.objects.exists()  # preview stores nothing
    _channels(admin)
    before_audit = set(AuditEvent.objects.values_list("action", flat=True))
    with mock.patch("apps.notify.mailer.send_mail_now") as sm:
        res = a.post("/api/notifications/templates/antivirus.threat/test", {"channels": ["in_app", "email"]}, format="json").json()
    assert res["results"] == {"in_app": "sent", "email": "sent"}
    assert sm.call_args[0][1].startswith("Personal Documents Management System: [TEST]") and "TEST" in sm.call_args.kwargs["html"]
    n = Notification.objects.get(user=admin, is_test=True)
    assert n.kind == "test" and n.event == "antivirus.threat" and n.data["actions"]
    # no fake security event: no antivirus record, no new audit actions besides the test itself
    from apps.library.models import DocumentVersion

    assert not DocumentVersion.objects.filter(av_status="quarantined").exists()
    new = set(AuditEvent.objects.values_list("action", flat=True)) - before_audit
    assert new == {"notifications.test_sent"}
    assert clients["son1"].post("/api/notifications/templates/expiry.reminder/test", {}, format="json").status_code == 403


def test_at187_critical_cannot_be_weakened(family, clients):
    a = clients["dad"]
    r = a.put("/api/notifications/templates/antivirus.threat", {"severity": "info"}, format="json")
    assert r.status_code == 400 and "critical" in r.json()["error"].lower()
    # even a stored lower severity is lifted for critical events
    NotificationTemplate.objects.create(event="antivirus.threat", severity="info")
    assert rich.apply_template(rich.sample("antivirus.threat"), "email", True)["severity"] in ("warning", "critical")
    # people cannot remove required channels (push included)
    r = clients["son1"].put("/api/me/notification-preferences", {"preferences": {"security.new_country": []}}, format="json")
    assert r.status_code == 400
    assert "push" in catalog.CHANNELS


def test_at188_recurring_conditions_obey_the_cooldown(family):
    from apps.security import antivirus

    admin = family["dad"]
    with mock.patch("apps.security.antivirus.health", return_value={"status": "unavailable"}):
        antivirus.check_health_and_alert()
        with mock.patch("django.utils.timezone.localdate", return_value=timezone.localdate() + timedelta(days=1)):
            antivirus.check_health_and_alert()  # next day's hourly check: new key, but inside the cooldown
    assert Notification.objects.filter(user=admin, event="antivirus.unavailable").count() == 1
    config.set_value("notifications.repeat_cooldown_hours", 1)
    Notification.objects.filter(user=admin).update(created_at=timezone.now() - timedelta(hours=2))
    with mock.patch("apps.security.antivirus.health", return_value={"status": "unavailable"}), \
            mock.patch("django.utils.timezone.localdate", return_value=timezone.localdate() + timedelta(days=2)):
        antivirus.check_health_and_alert()
    assert Notification.objects.filter(user=admin, event="antivirus.unavailable").count() == 2
    # a new threat is never held back
    antivirus._alert("antivirus.threat", "th1", "Malware", ["x"])
    antivirus._alert("antivirus.threat", "th2", "Malware", ["y"])
    assert Notification.objects.filter(user=admin, event="antivirus.threat").count() == 2


def test_at189_unicode_rtl_timezone_and_date_format(family):
    son = family["son1"]
    config.set_value("general.timezone", "Asia/Riyadh")
    config.set_value("general.date_format", "dd/MM/yyyy")
    d = _passport(son, days=45, title="جواز السفر")
    m = expiry.expiry_message(d, 45, son)
    exp = (TODAY + timedelta(days=45)).strftime("%d/%m/%Y")
    assert any(x.value == exp for x in m.details)
    _s, text, html_doc = rich.render_email(m, son)
    assert "(Asia/Riyadh)" in html_doc and 'dir="auto"' in html_doc and exp in html_doc
    events.notify(son, "document.shared", key="ar", title=lambda n: f"تمت مشاركة “{n('ملف عائلي')}”", link="/shared")
    n = Notification.objects.get(user=son, event="document.shared")
    assert n.title.startswith("تمت مشاركة") and "ملف عائلي" in n.title


def test_at190_delivery_history_states_and_sanitised_errors(family, clients):
    son = family["son1"]
    _channels(son)
    _passport(son, days=7)
    expiry.run_expiry_scan(TODAY)
    with mock.patch("apps.notify.mailer.send_mail_now", side_effect=OSError("login failed password=hunter2")), \
            mock.patch("apps.notify.telegram._call", return_value={"ok": True, "result": {"message_id": 5}}):
        expiry.deliver_outbox()
    rows = {d["channel"]: d for d in clients["dad"].get("/api/notifications/deliveries").json()["deliveries"]}
    assert rows["email"]["state"] == "retrying" and rows["email"]["next_attempt_at"] and "hunter2" not in rows["email"]["error"]
    assert rows["telegram"]["state"] == "sent" and rows["telegram"]["delivered"] == "accepted by the provider"
    assert rows["email"]["event"] == "expiry.reminder" and rows["email"]["event_label"] == "Expiry reminders"
    assert clients["son1"].get("/api/notifications/deliveries").status_code == 403
    only_failed = clients["dad"].get("/api/notifications/deliveries?status=sent").json()["deliveries"]
    assert {d["channel"] for d in only_failed} == {"telegram"}


def test_at191_document_type_and_metadata(family):
    son = family["son1"]
    d = _passport(son, days=45)
    m = expiry.expiry_message(d, 45, son)
    labels = {x.label: x for x in m.details}
    assert labels["Document type"].value == "Passport" and "Passport number" in labels and labels["Passport number"].sensitive
    _s, text, html_doc = rich.render_email(m, son)
    assert "X1234567" not in html_doc + text and "4567" not in html_doc  # numbers hidden by default
    config.set_value("notifications.include_document_number", True)
    _s, text, html_doc = rich.render_email(m, son)
    assert "••••4567" in html_doc and "X1234567" not in html_doc
    # unconfirmed values are never presented as facts; unassigned type renders gracefully
    u = Document.objects.create(folder=personal_root(son), owner=son, title="u", state=Document.READY)
    set_field(actor=son, doc=u, key="expiry_date", value=(TODAY + timedelta(days=10)).isoformat())
    set_field(actor=son, doc=u, key="full_name", value="Unconfirmed Name", confirm=False)
    u.refresh_from_db()
    mu = expiry.expiry_message(u, 10, son)
    vals = {x.label: str(x.value) for x in mu.details}
    assert vals["Document type"] == "Document (type not assigned)" and "Unconfirmed Name" not in vals.values()
    assert mu.push_title == "Document Expiry Alert"


def test_at192_security_events_use_policy_severity_and_admin_visibility(family):
    from apps.security import antivirus, center

    son, admin = family["son1"], family["dad"]
    antivirus._alert("antivirus.threat", "s1", "Malware detected — file quarantined", ["x"])
    assert Notification.objects.get(user=admin, event="antivirus.threat").severity == "critical"
    assert not Notification.objects.filter(user=son, event__startswith="antivirus.").exists()  # administrators only
    with mock.patch("apps.security.center.storage_health", return_value={"status": "critical", "percent": 93, "free": 10 * 1024 ** 3}):
        center.storage_alerts()
    st = Notification.objects.get(user=admin, title__startswith="Storage critical")
    assert st.severity == "critical" and st.icon == "db" and [a["key"] for a in st.data["actions"]] == ["storage", "cleanup"]
    from apps.security.models import OsUpdateRun

    run = OsUpdateRun.objects.create(action="install_updates", status="failed", error="dpkg error", requested_by=admin)
    center._notify_update(run)
    assert Notification.objects.get(user=admin, title="Security update installation failed").severity == "critical"
    events.authentik_link_changed(son, linked=True)
    n = Notification.objects.get(user=son, event="security.authentik")
    assert n.severity == "warning" and catalog.is_critical("security.authentik")


def test_at193_links_never_grant_access(family, clients):
    son, son2 = family["son1"], family["son2"]
    today = timezone.localdate()
    ptype = DocumentType.objects.get(name="Passport")
    d = Document.objects.create(folder=personal_root(son), owner=son, title="p", doc_type=ptype, state=Document.READY)
    set_field(actor=son, doc=d, key="expiry_date", value=(today + timedelta(days=45)).isoformat())
    d.refresh_from_db()
    expiry.run_expiry_scan(today)
    n = Notification.objects.get(user=son, document=d)
    for a in n.data["actions"]:
        assert a["in_app"] or (a["path"].startswith("/") and "token" not in a["path"])
    # the document page behind the link enforces permissions for anyone else
    assert clients["son2"].get(f"/api/documents/{d.id}").status_code == 404
    # someone else's notification cannot be acted on, and snooze re-checks access now
    assert clients["son2"].post(f"/api/notifications/{n.id}/action", {"action": "snooze"}, format="json").status_code == 404
    r = clients["son1"].post(f"/api/notifications/{n.id}/action", {"action": "snooze", "days": 30}, format="json")
    assert r.status_code == 200
    from apps.notify.models import ExpirySnooze

    assert ExpirySnooze.objects.filter(user=son, document=d).exists() and not ExpirySnooze.objects.filter(user=son2).exists()
    # snoozed: the next threshold for this person is skipped, other recipients unaffected
    expiry.run_expiry_scan(today + timedelta(days=16))  # 30-day threshold, inside the 30-day snooze
    assert Notification.objects.filter(user=son, document=d).count() == 1


def test_at195_existing_configuration_survives(family):
    son = family["son1"]
    config.set_value("notifications.critical_channels", ["in_app", "email"])
    config.set_user(son, "me.notification_prefs", {"document.added": ["in_app", "email"]})
    assert catalog.preferences(son)["document.added"] == ["in_app", "email"]  # stored choices still valid
    assert config.get("notifications.critical_channels") == ["in_app", "email"]  # push not forced on anyone
    assert "push" not in catalog.channels_for(son, "security.new_country")
    assert set(catalog.default_channels(son, "expiry.reminder")) <= {"in_app", "email", "telegram"}
    # older in-app rows were classified by the migration; their text and read state are untouched
    import importlib

    from django.apps import apps as django_apps

    old = Notification.objects.create(user=son, kind="backup", title="Backup failed (old)", body="b", category="")
    importlib.import_module("apps.notify.migrations.0002_rich_notifications").classify_existing(django_apps, None)
    old.refresh_from_db()
    assert old.category == "system" and old.severity == "critical" and old.title == "Backup failed (old)" and old.read_at is None
