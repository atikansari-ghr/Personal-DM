"""AT-16 and AT-17: reminder schedule, recipients, channels, idempotency, message content."""
from datetime import date, timedelta
from unittest import mock

import pytest
from conftest import client_for, personal_root

from apps.accounts.models import Delegation, FamilyGroup
from apps.core import config
from apps.library.models import Document, DocumentField, DocumentType
from apps.library.services import set_field
from apps.notify import expiry
from apps.notify.models import ExpiryMark, Notification, OutboxMessage

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 3)


def _doc(owner, expiry_on, number="Z7654321"):
    ptype = DocumentType.objects.get(name="Passport")
    d = Document.objects.create(folder=personal_root(owner), owner=owner, title="p", doc_type=ptype, state=Document.READY)
    set_field(actor=owner, doc=d, key="document_number", value=number)
    set_field(actor=owner, doc=d, key="expiry_date", value=expiry_on.isoformat())
    d.refresh_from_db()
    return d


def _sent(doc):
    return sorted(ExpiryMark.objects.filter(document=doc, action="sent").values_list("threshold", flat=True))


def test_thresholds_fire_once_each_and_stop_after_expiry(family):
    son1 = family["son1"]
    d = _doc(son1, TODAY + timedelta(days=90))
    for offset in range(0, 95):
        expiry.run_expiry_scan(TODAY + timedelta(days=offset))
        expiry.run_expiry_scan(TODAY + timedelta(days=offset))  # duplicate run (restart) is harmless
    assert _sent(d) == [0, 7, 30, 60, 90]
    n = Notification.objects.filter(user=son1, document=d)
    assert n.count() == 5
    assert n.filter(title__icontains="expires today").count() == 1


def test_proposed_dates_never_trigger_reminders(family):
    son1 = family["son1"]
    d = Document.objects.create(folder=personal_root(son1), owner=son1, title="p", state=Document.NEEDS_REVIEW)
    DocumentField.objects.create(document=d, key="expiry_date", value=(TODAY + timedelta(days=5)).isoformat(), status="proposed")
    expiry.run_expiry_scan(TODAY)
    assert not Notification.objects.exists()


def test_catch_up_after_missed_runs_and_new_import_sends_one(family):
    d = _doc(family["son1"], TODAY + timedelta(days=20))  # newly imported, already inside 90/60/30
    expiry.run_expiry_scan(TODAY)
    assert _sent(d) == [30]
    assert set(ExpiryMark.objects.filter(document=d, action="skipped").values_list("threshold", flat=True)) == {60, 90}
    assert Notification.objects.filter(document=d, user=family["son1"]).count() == 1


def test_recipients_deduplicated_and_head_reassignment(family):
    dad, mom, son1 = family["dad"], family["mom"], family["son1"]
    d = _doc(dad, TODAY + timedelta(days=7))  # Dad is owner and head: one message
    expiry.run_expiry_scan(TODAY)
    assert Notification.objects.filter(document=d, user=dad).count() == 1
    g = FamilyGroup.objects.get(name="My family")
    g.head = mom
    g.save()
    d2 = _doc(son1, TODAY + timedelta(days=7))
    expiry.run_expiry_scan(TODAY)
    assert set(Notification.objects.filter(document=d2).values_list("user__username", flat=True)) == {"son1", "mom"}
    # delegate with notifications scope receives; disabled accounts never do
    Delegation.objects.create(delegate=family["daughter"], group=g, scopes=["notifications"])
    family["son2"].is_active = False
    family["son2"].save()
    d3 = _doc(family["son3"], TODAY)
    expiry.run_expiry_scan(TODAY)
    assert set(Notification.objects.filter(document=d3).values_list("user__username", flat=True)) == {"son3", "mom", "daughter"}


def test_changed_expiry_restarts_schedule_and_cancels_pending(family):
    son1 = family["son1"]
    config.set_value("smtp.enabled", True)
    config.set_value("smtp.host", "smtp.invalid")
    son1.email = "son1@example.invalid"
    son1.save()
    config.set_user(son1, "me.channels", ["in_app", "email"])
    d = _doc(son1, TODAY + timedelta(days=30))
    expiry.run_expiry_scan(TODAY)
    pending = OutboxMessage.objects.filter(document=d, channel="email", user=son1).get()
    assert pending.status == "pending"
    set_field(actor=son1, doc=d, key="expiry_date", value=(TODAY + timedelta(days=200)).isoformat())
    pending.refresh_from_db()
    assert pending.status == "skipped"
    set_field(actor=son1, doc=d, key="expiry_date", value=(TODAY + timedelta(days=6)).isoformat())
    d.refresh_from_db()
    expiry.run_expiry_scan(TODAY)
    assert ExpiryMark.objects.filter(document=d, expiry_date=d.expiry_date, threshold=7, action="sent").exists()


def test_renewed_and_archived_records_stop_reminders(family):
    son1 = family["son1"]
    old = _doc(son1, TODAY + timedelta(days=10))
    new = _doc(son1, TODAY + timedelta(days=3650))
    new.renews = old
    new.save()
    archived = _doc(son1, TODAY + timedelta(days=5))
    archived.archived_at = __import__("django.utils.timezone", fromlist=["now"]).now()
    archived.save()
    expiry.run_expiry_scan(TODAY)
    assert not _sent(old) and not _sent(archived)


def test_interval_change_applies_without_resending(family):
    d = _doc(family["son1"], TODAY + timedelta(days=45))
    expiry.run_expiry_scan(TODAY)
    assert _sent(d) == [60]
    config.set_value("notifications.expiry_days", [45, 14, 0])
    expiry.run_expiry_scan(TODAY)
    assert _sent(d) == [45, 60]
    expiry.run_expiry_scan(TODAY)
    assert _sent(d) == [45, 60]


def test_timezone_boundary_uses_installation_timezone(family):
    from datetime import datetime, timezone as tz

    config.set_value("general.timezone", "Asia/Riyadh")  # UTC+3
    with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 2, 22, 30, tzinfo=tz.utc)):
        assert expiry.local_today() == date(2026, 10, 3)
    config.set_value("general.timezone", "America/New_York")
    with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 3, 2, 0, tzinfo=tz.utc)):
        assert expiry.local_today() == date(2026, 10, 2)


def test_at17_required_channels_missing_details_and_content(family, clients):
    son1 = family["son1"]
    config.set_value("notifications.required_channels", ["in_app", "email"])
    r = clients["son1"].put("/api/me/channels", {"channels": ["in_app"]}, format="json")
    assert r.status_code == 400  # cannot disable a required channel
    chans = {c["channel"]: c for c in clients["son1"].get("/api/me/channels").json()["channels"]}
    assert chans["email"]["required"] and chans["email"]["issue"]  # SMTP off / no email: actionable issue shown
    assert chans["whatsapp"]["available"] is False
    d = _doc(son1, TODAY + timedelta(days=7), number="Q9988776")
    expiry.run_expiry_scan(TODAY)
    email_msg = OutboxMessage.objects.get(document=d, user=son1, channel="email")
    assert email_msg.status == "skipped" and email_msg.last_error  # never faked as delivered
    for msg in OutboxMessage.objects.filter(document=d):
        assert "Q9988776" not in msg.body and "8776" not in msg.body
        assert "Sam Sample" in msg.subject and "Passport" in msg.subject and "/documents/" in msg.body


def test_email_and_telegram_delivery_with_retry(family):
    son1 = family["son1"]
    config.set_value("smtp.enabled", True)
    config.set_value("smtp.host", "smtp.invalid")
    config.set_value("telegram.enabled", True)
    config.set_value("telegram.bot_token", "123:synthetic")
    from apps.notify.models import TelegramLink

    TelegramLink.objects.create(user=son1, chat_id="42")
    son1.email = "son1@example.invalid"
    son1.save()
    config.set_user(son1, "me.channels", ["in_app", "email", "telegram"])
    d = _doc(son1, TODAY + timedelta(days=7))
    expiry.run_expiry_scan(TODAY)
    with mock.patch("apps.notify.mailer.send_mail_now", side_effect=OSError("connection refused password=hunter2")), \
            mock.patch("apps.notify.telegram.send") as tg:
        res = expiry.deliver_outbox()
    assert res == {"sent": 1, "failed": 1}
    assert tg.call_args[0][0] == "42" and "Z7654321" not in tg.call_args[0][1]
    em = OutboxMessage.objects.get(document=d, channel="email", user=son1)
    assert em.status == "pending" and em.attempts == 1 and "hunter2" not in em.last_error
    OutboxMessage.objects.filter(pk=em.pk).update(next_attempt_at=__import__("django.utils.timezone", fromlist=["now"]).now())
    with mock.patch("apps.notify.mailer.send_mail_now") as sm:
        expiry.deliver_outbox()
    em.refresh_from_db()
    assert em.status == "sent" and sm.called


def test_telegram_linking_only_links_the_chat_that_sends_the_code(family):
    from apps.notify import telegram
    from apps.notify.models import TelegramLink

    config.set_value("telegram.enabled", True)
    config.set_value("telegram.bot_token", "123:synthetic")
    code = telegram.new_link_code(family["son1"])["code"]
    with mock.patch("apps.notify.telegram.send"):
        n = telegram.process_updates([
            {"update_id": 1, "message": {"text": "/start WRONGCOD", "chat": {"id": 7, "type": "private"}}},
            {"update_id": 2, "message": {"text": f"/start {code}", "chat": {"id": 99, "type": "group"}}},
            {"update_id": 3, "message": {"text": f"/start {code}", "chat": {"id": 55, "type": "private", "username": "sam"}}},
            {"update_id": 4, "message": {"text": f"/start {code}", "chat": {"id": 66, "type": "private"}}},  # reused code
        ])
    assert n == 1
    assert TelegramLink.objects.get(user=family["son1"]).chat_id == "55"
    assert not TelegramLink.objects.filter(chat_id="66").exists()


def test_notification_link_still_requires_permission(family):
    d = _doc(family["son1"], TODAY + timedelta(days=7))
    g = FamilyGroup.objects.get(name="My family")
    g.head = family["mom"]
    g.save()
    expiry.run_expiry_scan(TODAY)
    n = Notification.objects.get(user=family["mom"], document=d)
    assert client_for(family["mom"]).get(f"/api/documents/{d.id}").status_code == 404
    assert n.link == f"/documents/{d.id}"
