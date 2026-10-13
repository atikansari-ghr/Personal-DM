"""Change Set T - notification channels and routing (AT-277, AT-312 .. AT-322). Synthetic data; no real Discord or
WhatsApp traffic (Discord HTTP is mocked; WhatsApp uses tests/fake_whatsapp_bridge.py)."""
import json
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from unittest import mock

import pytest
from django.utils import timezone

from apps.core import config
from apps.notify import events, expiry, routing
from apps.notify.models import DiscordWebhook, Notification, OutboxMessage, WhatsAppLink

from fake_whatsapp_bridge import FakeBridge

pytestmark = pytest.mark.django_db
HOOK = "https://discord.com/api/webhooks/123456789012345678/" + "S" * 68
TOKEN = "synthetic-bridge-token-0123456789abcdef"


@pytest.fixture
def bridge(settings):
    Path(settings.CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    (Path(settings.CONFIG_DIR) / "whatsapp-bridge.token").write_text(TOKEN)
    with FakeBridge(TOKEN) as b:
        config.set_value("whatsapp.enabled", True)
        config.set_value("whatsapp.bridge_url", f"http://127.0.0.1:{b.port}")
        yield b


def link(client, user, bridge):
    r = client.post("/api/notifications/whatsapp", {"action": "link"}, format="json")
    assert r.status_code == 200, r.content
    sid = WhatsAppLink.objects.get(user=user).session
    st = client.get("/api/notifications/whatsapp").json()
    assert st["state"] == "pending" and st["qr_svg"].startswith("<?xml") or "<svg" in st["qr_svg"]
    bridge.connect(sid)
    st = client.get("/api/notifications/whatsapp").json()
    assert st["state"] == "connected" and st["number_hint"] == "0042"
    return sid


def notify_security(user, key="k1"):
    return events.notify(user, "security.new_ip", key=key, title="Sign-in from a new address", facts=[("IP address", "203.0.113.7")])


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._b = status, body or {}

    def json(self):
        return self._b


# ------------------------------------------------------------------ AT-277 existing channels keep working

def test_at277_existing_channels_unchanged_and_new_channels_not_enabled_by_migration(family, clients):
    prefs = clients["son1"].get("/api/me/notification-preferences").json()
    for e in prefs["events"]:
        assert "discord" not in e["channels"] and "whatsapp" not in e["channels"]
    assert {c["channel"] for c in prefs["channels"]} >= {"in_app", "email", "telegram", "push", "discord", "whatsapp"}
    assert not config.get("whatsapp.enabled") and not config.get("discord.enabled")
    config.set_value("smtp.enabled", True)
    config.set_value("smtp.host", "smtp.example.com")
    u = family["son1"]
    u.email = "son1@example.com"
    u.save()
    config.set_user(u, "me.notification_prefs", {"security.new_ip": ["in_app", "email"]})
    notify_security(u)
    assert OutboxMessage.objects.get(user=u, channel="email").route == "direct"
    with mock.patch("apps.notify.mailer.send_mail_now") as send:
        expiry.deliver_outbox()
    assert send.called and OutboxMessage.objects.get(user=u, channel="email").status == "sent"


# ------------------------------------------------------------------ AT-317 Discord

def test_at317_discord_webhook_encrypted_masked_tested_routed_removed(family, clients):
    c, u = clients["mom"], family["mom"]
    assert c.put("/api/notifications/discord", {"url": HOOK}, format="json").status_code == 400  # off by default
    config.set_value("discord.enabled", True)
    assert c.put("/api/notifications/discord", {"url": "https://evil.example.com/api/webhooks/1/abc"}, format="json").status_code == 400
    r = c.put("/api/notifications/discord", {"url": HOOK}, format="json")
    assert r.status_code == 200 and r.json()["webhook"]["hint"] == "webhook …5678"
    hook = DiscordWebhook.objects.get(user=u)
    assert HOOK not in hook.url_enc and HOOK not in r.content.decode()
    with mock.patch("apps.notify.discord.requests.post", return_value=_Resp(200, {"id": "1"})) as post:
        assert c.post("/api/notifications/channel-test", {"channel": "discord"}, format="json").status_code == 200
    payload = post.call_args.kwargs["json"]
    assert payload["allowed_mentions"] == {"parse": []} and "Test" in payload["embeds"][0]["title"]
    # category routing: security events to Discord
    c.put("/api/notifications/routing", {"category_channels": {"category": "security", "channels": ["in_app", "discord"]}}, format="json")
    notify_security(u)
    m = OutboxMessage.objects.get(user=u, channel="discord")
    assert m.payload["embeds"][0]["fields"]
    with mock.patch("apps.notify.discord.requests.post", return_value=_Resp(200, {"id": "2"})):
        expiry.deliver_outbox()
    m.refresh_from_db()
    assert m.status == "sent"
    from apps.core.models import AuditEvent

    assert HOOK not in json.dumps([a.context for a in AuditEvent.objects.all()], default=str)
    assert c.delete("/api/notifications/discord").json()["webhook"] is None


# ------------------------------------------------------------------ AT-312 .. AT-316 WhatsApp Personal

def test_at313_per_person_sessions_isolated(family, clients, bridge):
    s_mom = link(clients["mom"], family["mom"], bridge)
    s_son = link(clients["son1"], family["son1"], bridge)
    assert s_mom != s_son
    assert clients["mom"].post("/api/notifications/channel-test", {"channel": "whatsapp"}, format="json").status_code == 200
    assert [s for s, _t in bridge.sent] == [s_mom]
    clients["son1"].delete("/api/notifications/whatsapp")
    assert s_son not in bridge.sessions and s_mom in bridge.sessions
    assert clients["mom"].get("/api/notifications/whatsapp").json()["state"] == "connected"
    # nothing in any response exposes the session id or credentials
    text = clients["mom"].get("/api/notifications/whatsapp").content.decode()
    assert s_mom not in text


def test_at312_bridge_down_never_breaks_other_channels(family, clients, bridge):
    u = family["mom"]
    link(clients["mom"], u, bridge)
    config.set_value("telegram.enabled", True)
    from apps.notify.models import TelegramLink

    TelegramLink.objects.create(user=u, chat_id="1001")
    config.set_user(u, "me.notification_prefs", {"security.new_ip": ["in_app", "telegram", "whatsapp"]})
    bridge.server.shutdown()  # the bridge crashes
    notify_security(u)
    with mock.patch("apps.notify.telegram.send", return_value="t1"):
        expiry.deliver_outbox()
    assert OutboxMessage.objects.get(user=u, channel="telegram").status == "sent"
    wa = OutboxMessage.objects.get(user=u, channel="whatsapp")
    assert wa.status == "pending" and wa.attempts == 1 and "not running" in wa.last_error  # bounded retry, later
    assert Notification.objects.filter(user=u, event="security.new_ip").exists()
    assert clients["mom"].get("/api/notifications/whatsapp").status_code == 200  # the page still works (Degraded)


def test_at314_notification_only_no_composer_contacts_or_recipients(family, clients, bridge):
    import personaldocs.urls as U

    names = " ".join(str(p.pattern) for p in U.api)
    assert "notifications/whatsapp" in names
    for bad in ("whatsapp/send", "whatsapp/contacts", "whatsapp/chats", "whatsapp/broadcast", "whatsapp/messages", "whatsapp/reply"):
        assert bad not in names
    sid = link(clients["mom"], family["mom"], bridge)
    # the API accepts no message text or recipient from the browser
    r = clients["mom"].post("/api/notifications/whatsapp", {"action": "send", "text": "hello", "to": "+10000000000"}, format="json")
    assert r.status_code == 400
    r = clients["mom"].post("/api/notifications/channel-test", {"channel": "whatsapp", "text": "custom", "to": "x"}, format="json")
    assert r.status_code == 200 and "custom" not in bridge.sent[-1][1] and bridge.sent[-1][0] == sid


def test_at315_bridge_version_compatibility(family, clients, bridge):
    from apps.notify import whatsapp

    st = whatsapp.bridge_status()
    assert st["state"] == "healthy" and st["tested"] and st["pinned"] == "1.1.0"
    bridge.version = "9.9.9"
    st = whatsapp.bridge_status()
    assert st["state"] == "degraded" and not st["tested"] and st["update_available"]
    r = clients["dad"].get("/api/notifications/health").json()
    assert r["whatsapp"]["bridge"]["state"] == "degraded"
    assert clients["mom"].get("/api/notifications/health").status_code == 403


def test_at316_restore_reconnect_vs_compromise_relink(family, clients, bridge):
    from apps.notify import whatsapp

    s1 = link(clients["mom"], family["mom"], bridge)
    s2 = link(clients["son1"], family["son1"], bridge)
    bridge.sessions[s2]["revoked"] = True  # WhatsApp rejected this restored session
    res = whatsapp.reconnect_all()
    assert res == {"connected": 1, "relink": 1}
    assert WhatsAppLink.objects.get(session=s1).state == "connected"
    assert WhatsAppLink.objects.get(user=family["son1"]).state == "reconnect_required"
    n = whatsapp.require_relink_all("Compromise recovery")
    assert n == 2 and not WhatsAppLink.objects.filter(state="connected").exists()
    assert s1 not in bridge.sessions  # never reconnected automatically; a fresh QR link is needed
    assert WhatsAppLink.objects.get(user=family["mom"]).session != s1


# ------------------------------------------------------------------ AT-318 routing matrix, AT-319 fallback

def test_at318_category_matrix_sets_only_that_category(family, clients):
    c, u = clients["mom"], family["mom"]
    before = c.get("/api/me/notification-preferences").json()
    docs_before = {e["key"]: e["channels"] for e in before["events"] if e["category"] == "documents"}
    r = c.put("/api/notifications/routing", {"category_channels": {"category": "security", "channels": ["in_app", "email"]}}, format="json")
    assert r.status_code == 200
    after = c.get("/api/me/notification-preferences").json()
    for e in after["events"]:
        if e["category"] == "security":
            assert "email" in e["channels"]
        if e["category"] == "documents":
            assert e["channels"] == docs_before[e["key"]]  # other categories untouched
    assert c.put("/api/notifications/routing", {"routing": {"security": {"fallback": ["in_app"]}}}, format="json").status_code == 400
    assert c.put("/api/notifications/routing", {"routing": {"nope": {}}}, format="json").status_code == 400


def test_at319_fallback_used_once_and_no_duplicate_after_primary_success(family, clients, bridge):
    u = family["mom"]
    link(clients["mom"], u, bridge)
    config.set_value("telegram.enabled", True)
    config.set_value("notifications.fallback_after_attempts", 1)
    from apps.notify.models import TelegramLink

    TelegramLink.objects.create(user=u, chat_id="1002")
    config.set_user(u, "me.notification_prefs", {"security.new_ip": ["in_app"]})
    clients["mom"].put("/api/notifications/routing", {"routing": {"security": {"fallback": ["whatsapp", "telegram", "email"]}}}, format="json")
    # primary works: exactly one external delivery
    notify_security(u, "ok1")
    with mock.patch("apps.notify.telegram.send", return_value="t") as tg:
        expiry.deliver_outbox()
    assert OutboxMessage.objects.filter(key__startswith="ok1", channel="whatsapp", status="sent").count() == 1
    assert not OutboxMessage.objects.filter(key__startswith="ok1", channel="telegram").exists() and not tg.called
    # primary fails: Telegram is used once, recorded as a fallback
    bridge.fail_sends = True
    notify_security(u, "fb1")
    with mock.patch("apps.notify.telegram.send", return_value="t") as tg:
        expiry.deliver_outbox()
        expiry.deliver_outbox()
        expiry.deliver_outbox()
    wa = OutboxMessage.objects.get(key__startswith="fb1", channel="whatsapp")
    tgm = OutboxMessage.objects.get(key__startswith="fb1", channel="telegram")
    assert wa.status == "fallback" and tgm.route == "fallback" and tgm.fallback_of_id == wa.id and tgm.status == "sent"
    assert tg.call_count == 1 and not OutboxMessage.objects.filter(key__startswith="fb1", channel="email").exists()
    rows = clients["mom"].get("/api/notifications/my-deliveries").json()["deliveries"]
    labels = {(r["channel"], r["status_label"]) for r in rows if r["subject"]}
    assert ("whatsapp", "Fallback Used") in labels and ("telegram", "Delivered") in labels


def test_disconnected_primary_falls_back_immediately(family, clients, bridge):
    u = family["mom"]
    config.set_value("telegram.enabled", True)
    from apps.notify.models import TelegramLink

    TelegramLink.objects.create(user=u, chat_id="1003")
    config.set_user(u, "me.notification_routing", {"security": {"fallback": ["whatsapp", "telegram"]}})
    notify_security(u, "dc1")  # WhatsApp never linked
    wa = OutboxMessage.objects.get(key__startswith="dc1", channel="whatsapp")
    tgm = OutboxMessage.objects.get(key__startswith="dc1", channel="telegram")
    assert wa.status == "skipped" and wa.last_error.startswith("Channel Disconnected") and tgm.status == "pending"
    assert routing.state_of(wa) == "disconnected"


# ------------------------------------------------------------------ AT-320 quiet hours, AT-321 digests

def test_at320_quiet_hours_hold_normal_but_not_critical(family, clients):
    u = family["dad"]
    config.set_value("telegram.enabled", True)
    from apps.notify.models import TelegramLink

    TelegramLink.objects.create(user=u, chat_id="1004")
    config.set_user(u, "me.timezone", "Asia/Riyadh")
    config.set_user(u, "me.quiet_hours", {"enabled": True, "start": "22:00", "end": "07:00"})
    config.set_user(u, "me.notification_prefs", {"security.new_ip": ["in_app", "telegram"]})
    night = datetime(2026, 10, 12, 23, 30, tzinfo=routing.user_tz(u))
    with mock.patch("django.utils.timezone.now", return_value=night.astimezone(dt_timezone.utc)):
        notify_security(u, "q1")
        events.backup_event("backup.failed", detail="Synthetic failure", severity="critical", tag="q2")
    normal = OutboxMessage.objects.get(key__startswith="q1", channel="telegram")
    crit = OutboxMessage.objects.get(event="backup.failed", channel="telegram")
    assert normal.hold == "quiet_hours" and normal.next_attempt_at.astimezone(routing.user_tz(u)).hour == 7
    assert crit.hold == "" and crit.next_attempt_at <= night.astimezone(dt_timezone.utc) + timedelta(seconds=1)
    assert routing.state_of(normal) in ("held", "queued")
    assert Notification.objects.filter(user=u, event="security.new_ip").exists()  # in-app is immediate


def test_at321_digests_immediate_daily_weekly_and_critical_stays_immediate(family, clients):
    u = family["dad"]
    config.set_value("telegram.enabled", True)
    from apps.notify.models import TelegramLink

    TelegramLink.objects.create(user=u, chat_id="1005")
    config.set_user(u, "me.notification_prefs", {"security.new_ip": ["in_app", "telegram"], "backup.succeeded": ["in_app", "telegram"]})
    config.set_user(u, "me.notification_routing", {"security": {"digest": "daily"}, "backup": {"digest": "weekly"}})
    config.set_user(u, "me.timezone", "Asia/Riyadh")
    notify_security(u, "d1")
    notify_security(u, "d2")
    events.backup_event("backup.succeeded", detail="ok", tag="w1")
    events.backup_event("backup.failed", detail="Synthetic failure", severity="critical", tag="w2")
    assert OutboxMessage.objects.filter(user=u, channel="telegram", status="digest").count() == 3
    assert OutboxMessage.objects.get(user=u, channel="telegram", event="backup.failed").status == "pending"  # immediate
    tz = routing.user_tz(u)
    tuesday_9 = datetime(2026, 10, 13, 9, 0, tzinfo=tz)  # 13 Oct 2026 is a Tuesday
    assert routing.run_digests(tuesday_9) == 1
    dig = OutboxMessage.objects.get(user=u, kind="digest")
    assert "daily summary: 2 notifications" in dig.subject and dig.route == "digest"
    assert OutboxMessage.objects.filter(digest=dig, status="digested").count() == 2
    assert routing.run_digests(tuesday_9 + timedelta(hours=1)) == 0  # once per day
    monday_9 = datetime(2026, 10, 19, 9, 0, tzinfo=tz)
    assert routing.run_digests(monday_9) == 1
    assert "weekly summary: 1 notification" in OutboxMessage.objects.filter(user=u, kind="digest").order_by("-id").first().subject


# ------------------------------------------------------------------ AT-322 delivery history privacy

def test_at322_people_see_own_deliveries_admin_sees_counts_only(family, clients):
    config.set_value("smtp.enabled", True)
    config.set_value("smtp.host", "smtp.example.com")
    for name in ("mom", "son1"):
        u = family[name]
        u.email = f"{name}@example.com"
        u.save()
        config.set_user(u, "me.notification_prefs", {"security.new_ip": ["in_app", "email"]})
        notify_security(u, f"p-{name}")
    mine = clients["mom"].get("/api/notifications/my-deliveries").json()
    assert {r["channel"] for r in mine["deliveries"]} == {"email"} and len(mine["deliveries"]) == 1
    assert "whatsapp" in mine["not_selected"]["security.new_ip"]
    health = clients["dad"].get("/api/notifications/health")
    text = health.content.decode()
    assert health.status_code == 200 and "Sign-in from a new address" not in text and "mom@example.com" not in text
    assert health.json()["channels"][0]["counts"]
