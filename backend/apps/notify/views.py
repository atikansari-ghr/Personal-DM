from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin
from apps.core import audit, config, ratelimit

from . import expiry, telegram
from .models import Notification, OutboxMessage, TelegramLink


def _n(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "created_at": n.created_at,
            "read": n.read_at is not None}


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def notifications(request):
    qs = Notification.objects.filter(user=request.user)
    if request.query_params.get("unread"):
        qs = qs.filter(read_at__isnull=True)
    return Response({"notifications": [_n(n) for n in qs[:200]],
                     "unread": Notification.objects.filter(user=request.user, read_at__isnull=True).count()})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def mark_read(request):
    qs = Notification.objects.filter(user=request.user, read_at__isnull=True)
    if request.data.get("ids"):
        qs = qs.filter(id__in=request.data["ids"])
    qs.update(read_at=timezone.now())
    return Response({"status": "ok"})


@api_view(["GET", "PUT"])
@permission_classes([IsActiveAuthenticated])
def my_channels(request):
    user = request.user
    required = config.get("notifications.required_channels")
    if request.method == "PUT":
        wanted = list(request.data.get("channels") or [])
        missing = [c for c in required if c not in wanted]
        if missing:
            return Response({"error": f"Required channels cannot be disabled: {', '.join(missing)}."}, status=400)
        try:
            config.set_user(user, "me.channels", wanted)
        except Exception as exc:  # noqa: BLE001
            return Response({"error": str(exc)}, status=400)
        audit.record("account.channels_update", request=request, channels=wanted)
    active = expiry.channels_for(user)
    out = []
    for ch, label in (("in_app", "In-app"), ("email", "Email"), ("telegram", "Telegram"), ("discord", "Discord"),
                      ("whatsapp", "WhatsApp Personal (experimental)")):
        if ch in ("discord", "whatsapp"):
            from .catalog import channel_configured

            out.append({"channel": ch, "label": label, "available": channel_configured(ch), "enabled": False, "required": False,
                        "issue": expiry.channel_issue(user, ch), "note": "Choose it per category in Notifications → Routing."})
            continue
        out.append({"channel": ch, "label": label, "available": True, "enabled": ch in active,
                    "required": ch in required or ch == "in_app",
                    "issue": expiry.channel_issue(user, ch) if ch in active else None})
    link = TelegramLink.objects.filter(user=user).first()
    return Response({"channels": out, "telegram": {"linked": bool(link), "username": link.username if link else None,
                                                   "bot": config.get("telegram.bot_username")}})


@api_view(["POST", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def telegram_link(request):
    if request.method == "DELETE":
        TelegramLink.objects.filter(user=request.user).delete()
        audit.record("account.telegram_unlink", request=request)
        return Response({"linked": False})
    if not config.get("telegram.enabled"):
        return Response({"error": "Telegram is not configured by the administrator."}, status=400)
    return Response(telegram.new_link_code(request.user))


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def telegram_check(request):
    try:
        telegram.poll_updates()
    except telegram.TelegramError as exc:
        return Response({"error": str(exc)}, status=400)
    return Response({"linked": TelegramLink.objects.filter(user=request.user).exists()})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def test_channel(request):
    channel = request.data.get("channel")
    user = request.user
    try:
        if channel == "email":
            if not user.email:
                return Response({"error": "Add an email address to your profile to receive the test."}, status=400)
            from .mailer import send_mail_now

            send_mail_now(user.email, f"{config.get('general.app_name')}: test email", "This is a test message. Email delivery works.")
        elif channel == "telegram":
            info = telegram.test_connection()
            link = TelegramLink.objects.filter(user=user).first()
            if link:
                telegram.send(link.chat_id, "This is a test message. Telegram delivery works.")
                return Response({"status": "ok", "detail": f"Bot @{info['bot']} reachable; test message sent to your linked chat."})
            return Response({"status": "ok", "detail": f"Bot @{info['bot']} reachable. Link your own Telegram to receive a test message."})
        else:
            return Response({"error": "Unknown channel."}, status=400)
    except Exception as exc:  # noqa: BLE001
        from apps.core.logging import redact

        audit.record("connection.test", request=request, outcome="failure", channel=channel)
        return Response({"error": redact(f"{exc.__class__.__name__}: {exc}")[:300]}, status=400)
    audit.record("connection.test", request=request, channel=channel)
    return Response({"status": "ok", "detail": "Test message sent."})


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def delivery_history(request):
    qs = OutboxMessage.objects.select_related("user").exclude(channel="in_app")[:300]
    return Response({"deliveries": [{"id": m.id, "user": m.user.display_name, "channel": m.channel, "kind": m.kind, "subject": m.subject,
                                     "status": m.status, "attempts": m.attempts, "error": m.last_error, "created_at": m.created_at,
                                     "sent_at": m.sent_at} for m in qs]})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def template_preview(request):
    """Plain-text preview of an expiry reminder with sample data (Settings → Notifications)."""
    from . import rich

    subject, body, _html = rich.render_email(rich.sample("expiry.reminder", request.user.display_name), request.user)
    return Response({"subject": subject, "body": body,
                     "note": "Messages never include document numbers (unless the administrator allows a masked number in email/Telegram), codes, passwords or attachments; long numbers in names are masked and the link requires sign-in and permission."})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def run_reminders_now(request):
    result = expiry.run_expiry_scan()
    result.update(expiry.deliver_outbox())
    audit.record("notifications.run_now", request=request, **{k: v for k, v in result.items() if k != "date"})
    return Response(result)


from . import routing  # noqa: E402
from .event_defs import CHANNEL_LABELS, ROUTE_CATEGORIES, route_of  # noqa: E402


@api_view(["GET", "PUT"])
@permission_classes([IsActiveAuthenticated])
def my_notification_preferences(request):
    """Critical events (locked on) and the optional event x channel matrix for the signed-in person."""
    from . import catalog

    user = request.user
    if request.method == "PUT":
        wanted = request.data.get("preferences") or {}
        if not isinstance(wanted, dict):
            return Response({"error": "Send preferences as {event: [channels]}."}, status=400)
        current = config.get_user(user, "me.notification_prefs") or {}
        merged = {**current}
        for key, chans in wanted.items():
            if key not in catalog.EVENTS or not catalog.applies_to(user, key):
                return Response({"error": f"Unknown notification: {key}."}, status=400)
            locked = set(catalog.locked_channels(key))
            if locked - set(chans or []):
                missing = ", ".join(CHANNEL_LABELS[c] for c in catalog.CHANNELS if c in locked - set(chans or []))
                return Response({"error": f"“{catalog.LABELS[key]}” is required on {missing} by the administrator."}, status=400)
            merged[key] = chans
        try:
            config.set_user(user, "me.notification_prefs", merged)
        except Exception as exc:  # noqa: BLE001 - SettingError
            return Response({"error": str(exc)}, status=400)
        audit.record("account.notification_preferences", request=request, events=sorted(wanted))
    prefs = catalog.preferences(user)
    channels = []
    for ch in catalog.CHANNELS:
        globally = catalog.channel_configured(ch)
        channels.append({"channel": ch, "label": CHANNEL_LABELS[ch], "configured": bool(globally),
                         "issue": catalog.channel_issue(user, ch)})
    events = []
    for key, ev in catalog.EVENTS.items():
        if not catalog.applies_to(user, key):
            continue
        events.append({"key": key, "label": ev.label, "description": ev.description, "group": ev.group,
                       "critical": catalog.is_critical(key), "locked": catalog.locked_channels(key),
                       "channels": catalog.channels_for(user, key), "chosen": prefs.get(key, [])})
    for e in events:
        e["category"] = route_of(e["key"])
    link = TelegramLink.objects.filter(user=user).first()
    return Response({"events": events, "channels": channels, "problems": catalog.delivery_problems(user),
                     "categories": [{"key": k, "label": v, **routing.conf(user, k)} for k, v in ROUTE_CATEGORIES.items()
                                    if any(e["category"] == k for e in events)],
                     "quiet_hours": config.get_user(user, "me.quiet_hours"), "timezone": config.get_user(user, "me.timezone") or "",
                     "installation_timezone": config.get("general.timezone"), "digest_time": config.get_user(user, "me.digest_time"),
                     "telegram": {"linked": bool(link), "username": link.username if link else None,
                                  "bot": config.get("telegram.bot_username")}})


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def delivery_problems(request):
    """People who would miss administrator-required notifications (missing email, Telegram not linked …)."""
    from apps.accounts.models import User

    from . import catalog

    required = set()
    for key in catalog.EVENTS:
        required |= set(catalog.locked_channels(key))
    unconfigured = [{"channel": ch, "issue": catalog.channel_issue(request.user, ch)}
                    for ch in catalog.CHANNELS if ch in required and not catalog.channel_configured(ch)]
    out = []
    for u in User.objects.filter(is_active=True).order_by("display_name"):
        problems = catalog.delivery_problems(u, include_unconfigured=False)
        if problems:
            out.append({"user": u.display_name, "username": u.username, "problems": problems})
    skipped = OutboxMessage.objects.filter(status=OutboxMessage.SKIPPED).exclude(channel="in_app").count()
    return Response({"unconfigured": unconfigured, "people": out, "skipped_messages": skipped})


# ------------------------------------------------------------------ Change Set T: routing, Discord, WhatsApp, delivery status

@api_view(["PUT"])
@permission_classes([IsActiveAuthenticated])
def my_routing(request):
    """Category routing (fallback chain, digest), quiet hours, timezone and digest time; optionally the channels of
    every optional event of one category at once."""
    from . import catalog

    user = request.user
    d = request.data
    try:
        if "routing" in d:
            current = config.get_user(user, "me.notification_routing") or {}
            config.set_user(user, "me.notification_routing", {**current, **(d["routing"] or {})})
        if "quiet_hours" in d:
            config.set_user(user, "me.quiet_hours", d["quiet_hours"])
        if "timezone" in d:
            config.set_user(user, "me.timezone", d["timezone"] or "")
        if "digest_time" in d:
            config.set_user(user, "me.digest_time", d["digest_time"])
        if d.get("category_channels"):
            cat, chans = d["category_channels"].get("category"), list(d["category_channels"].get("channels") or [])
            if cat not in ROUTE_CATEGORIES or any(c not in catalog.CHANNELS for c in chans):
                return Response({"error": "Unknown category or channel."}, status=400)
            prefs = config.get_user(user, "me.notification_prefs") or {}
            for key in catalog.EVENTS:
                if route_of(key) == cat and catalog.applies_to(user, key):
                    prefs[key] = sorted(set(chans) | set(catalog.locked_channels(key)), key=catalog.CHANNELS.index)
            config.set_user(user, "me.notification_prefs", prefs)
    except Exception as exc:  # noqa: BLE001 - SettingError
        return Response({"error": str(exc)}, status=400)
    audit.record("account.notification_routing", request=request, fields=sorted(k for k in d if k != "routing") + sorted((d.get("routing") or {}).keys()))
    return Response({"status": "ok"})


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def my_discord(request):
    from . import discord
    from .models import DiscordWebhook

    user = request.user
    if request.method == "PUT":
        if not config.get("discord.enabled"):
            return Response({"error": "Discord is turned off by the administrator."}, status=400)
        if "url" in request.data:
            try:
                discord.save(user, request.data.get("url"))
            except discord.DiscordError as exc:
                return Response({"error": str(exc)}, status=400)
            audit.record("account.discord_webhook", request=request, change="saved")  # never the address
        if "enabled" in request.data:
            DiscordWebhook.objects.filter(user=user).update(enabled=bool(request.data["enabled"]))
    if request.method == "DELETE":
        DiscordWebhook.objects.filter(user=user).delete()
        audit.record("account.discord_webhook", request=request, change="removed")
    hook = DiscordWebhook.objects.filter(user=user).first()
    from .whatsapp import last_delivery

    return Response({"available": bool(config.get("discord.enabled")),
                     "webhook": {"hint": hook.hint, "enabled": hook.enabled, "status": hook.status, "error": hook.last_error,
                                 "last_tested_at": hook.last_tested_at, "last_delivery_at": last_delivery(user, "discord")} if hook else None})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def my_channel_test(request):
    """Send a TEST message to my own Discord webhook or WhatsApp."""
    ch = request.data.get("channel")
    if ratelimit.too_many(f"chtest:{request.user.pk}", 6, 600):
        return Response({"error": "Too many tests. Wait a few minutes."}, status=429)
    try:
        if ch == "discord":
            from . import discord

            discord.send_test(request.user)
        elif ch == "whatsapp":
            from . import whatsapp

            whatsapp.send_test(request.user)
        else:
            return Response({"error": "Unknown channel."}, status=400)
    except Exception as exc:  # noqa: BLE001
        from apps.core.logging import redact

        return Response({"error": redact(str(exc))[:200]}, status=400)
    audit.record("account.channel_test", request=request, channel=ch)
    return Response({"status": "ok", "detail": "Test message sent."})


@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def my_whatsapp(request):
    """Link my own WhatsApp (QR), see status, reconnect, unlink. Notification-only: nothing here can compose or read
    messages, list contacts or message anyone else."""
    from . import whatsapp

    user = request.user
    try:
        if request.method == "POST":
            action = request.data.get("action", "link")
            if action == "link":
                data = whatsapp.start_link(user)
                audit.record("account.whatsapp", request=request, change="link_started")
                return Response(data)
            if action == "reconnect":
                return Response(whatsapp.reconnect(user))
            return Response({"error": "Unknown action."}, status=400)
        if request.method == "DELETE":
            whatsapp.unlink(user)
            audit.record("account.whatsapp", request=request, change="unlinked")
            return Response({"linked": False, "state": "not_linked"})
        enabled = bool(config.get("whatsapp.enabled"))
        svc = whatsapp.bridge_status() if enabled else {"state": "disabled", "label": "Turned off by the administrator"}
        mine = whatsapp.status(user) if enabled or whatsapp._link(user) else {"linked": False, "state": "not_linked", "label": "Not linked"}
        return Response({"available": enabled, **mine, "last_delivery_at": whatsapp.last_delivery(user, "whatsapp"),
                         "service": {"state": svc.get("state"), "label": svc.get("label")},
                         "experimental": True, "notice": "Experimental, unofficial and self-hosted. Not WhatsApp Business Platform; "
                                                        "not supported or endorsed by WhatsApp or Meta."})
    except whatsapp.WhatsAppError as exc:
        return Response({"error": str(exc)}, status=400)


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def my_deliveries(request):
    """My own delivery state per message and channel (Delivered, Failed, Retrying, Fallback Used, Not Selected,
    Channel Disconnected, Held, Waiting for digest)."""
    from . import catalog

    user = request.user
    rows = []
    for m in OutboxMessage.objects.filter(user=user).exclude(channel="in_app").select_related("fallback_of")[:200]:
        st = routing.state_of(m)
        rows.append({"id": m.id, "channel": m.channel, "channel_label": CHANNEL_LABELS.get(m.channel, m.channel), "subject": m.subject,
                     "event": m.event, "status": st, "status_label": routing.STATUS_LABELS.get(st, st), "route": m.route,
                     "fallback_from": m.fallback_of.channel if m.fallback_of_id else None, "attempts": m.attempts,
                     "error": m.last_error, "created_at": m.created_at, "sent_at": m.sent_at,
                     "next_attempt_at": m.next_attempt_at if m.status == OutboxMessage.PENDING else None})
    not_selected = {}
    for key in catalog.EVENTS:
        if catalog.applies_to(user, key):
            chosen = set(catalog.channels_for(user, key))
            not_selected[key] = [c for c in catalog.CHANNELS if c not in chosen]
    return Response({"deliveries": rows, "not_selected": not_selected, "labels": routing.STATUS_LABELS})


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def admin_connections(request):
    """Provider cards for Settings -> Connections: status of each notification channel, counts only (no addresses,
    webhooks, tokens or session material)."""
    from . import catalog, whatsapp
    from .models import DiscordWebhook, WhatsAppLink

    def card(key, name, purpose, scope, status, label, **extra):
        return {"key": key, "name": name, "purpose": purpose, "scope": scope, "status": status, "label": label, **extra}

    email_on = catalog.channel_configured("email")
    email_set = bool(config.get("smtp.host"))
    tg_on = catalog.channel_configured("telegram")
    tg_set = config.is_set("telegram.bot_token")
    hooks = DiscordWebhook.objects.all()
    links = WhatsAppLink.objects.all()
    svc = whatsapp.service_status()
    wa_state = {"not_installed": "not_installed", "stopped": "degraded", "unavailable": "degraded", "incompatible": "degraded",
                "degraded": "degraded", "healthy": "connected", "ready_disabled": "disabled"}[svc["state"]]
    if not svc["enabled"] and svc["state"] not in ("not_installed",):
        wa_state = "disabled"
    cards = [
        card("in_app", "In-App", "Notification Center inside Personal DM", "system", "connected", "Always on"),
        card("email", "Email (SMTP)", "Messages to each person's email address", "system",
             "configured" if email_on else ("disabled" if email_set else "available_not_configured"),
             "Configured" if email_on else ("Turned off" if email_set else "Not configured")),
        card("telegram", "Telegram", "Messages from your Telegram bot to linked people", "system",
             "configured" if tg_on else ("disabled" if tg_set else "available_not_configured"),
             "Configured" if tg_on else ("Turned off" if tg_set else "Not configured")),
        card("push", "PWA Push", "Notifications on phones and computers where people turned push on", "system",
             "configured" if catalog.channel_configured("push") else "disabled",
             "Configured" if catalog.channel_configured("push") else "Turned off"),
        card("discord", "Discord", "Each person's own official Discord webhook", "personal",
             "configured" if config.get("discord.enabled") else "disabled", "Enabled" if config.get("discord.enabled") else "Disabled by Admin",
             people=hooks.count(), connected=hooks.filter(status="connected").count(), failing=hooks.exclude(status__in=("connected", "untested")).count()),
        card("whatsapp", "WhatsApp Personal", "Each person's own WhatsApp, linked as a device (Experimental · Unofficial · Self-hosted)",
             "personal", wa_state, svc["label"] if svc["enabled"] or svc["state"] == "not_installed" else f"Disabled by Admin · {svc['label']}",
             experimental=True, people=links.count(), connected=links.filter(state="connected").count(),
             reconnect=links.filter(state__in=("reconnect_required", "disconnected", "degraded")).count(), service=svc),
    ]
    return Response({"providers": cards})


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def delivery_health(request):
    """Notification Delivery Health for administrators: counts only - no message bodies, addresses or secrets."""
    from datetime import timedelta

    from django.db.models import Count
    from django.utils import timezone

    from . import whatsapp

    since = timezone.now() - timedelta(days=7)
    counts = {}
    for row in OutboxMessage.objects.filter(created_at__gte=since).exclude(channel="in_app").values("channel", "status").annotate(n=Count("id")):
        counts.setdefault(row["channel"], {})[row["status"]] = row["n"]
    pending_old = OutboxMessage.objects.filter(status=OutboxMessage.PENDING, created_at__lt=timezone.now() - timedelta(hours=6)).exclude(hold="quiet_hours").count()
    from .models import DiscordWebhook, WhatsAppLink

    return Response({"since": since, "channels": [{"channel": ch, "label": CHANNEL_LABELS[ch], "counts": counts.get(ch, {})}
                                                  for ch in CHANNEL_LABELS if ch != "in_app"],
                     "stuck": pending_old, "fallbacks": OutboxMessage.objects.filter(created_at__gte=since, route="fallback").count(),
                     "discord_webhooks": {"total": DiscordWebhook.objects.count(), "broken": DiscordWebhook.objects.exclude(status__in=["connected", "untested"]).count()},
                     "whatsapp": {"bridge": whatsapp.bridge_status(), "links": WhatsAppLink.objects.count(),
                                  "connected": WhatsAppLink.objects.filter(state="connected").count(),
                                  "reconnect_required": WhatsAppLink.objects.filter(state="reconnect_required").count()}})
