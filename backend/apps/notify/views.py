from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin
from apps.core import audit, config

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
    for ch, label in (("in_app", "In-app"), ("email", "Email"), ("telegram", "Telegram"), ("whatsapp", "WhatsApp")):
        if ch == "whatsapp":
            out.append({"channel": ch, "label": label, "available": False, "enabled": False, "required": False,
                        "issue": "Planned for a later release; not available."})
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
    class _T:
        name = "Passport"

    class _O:
        display_name = request.user.display_name

    class _D:
        id = "00000000-0000-0000-0000-000000000000"
        owner = _O()
        doc_type = _T()
        doc_type_id = 1
        expiry_date = expiry.local_today() + timezone.timedelta(days=30)

    subject, body, _ = expiry.expiry_message(_D(), 30, user=request.user)
    from . import templates

    return Response({"subject": templates.subject(subject), "body": body,
                     "note": "Messages never include document numbers, codes, passwords or attachments; long numbers in names are masked and the link requires sign-in and permission."})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def run_reminders_now(request):
    result = expiry.run_expiry_scan()
    result.update(expiry.deliver_outbox())
    audit.record("notifications.run_now", request=request, **{k: v for k, v in result.items() if k != "date"})
    return Response(result)


CHANNEL_LABELS = {"in_app": "In-app", "email": "Email", "telegram": "Telegram"}


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
        globally = ch == "in_app" or (config.get("smtp.enabled") if ch == "email" else config.get("telegram.enabled"))
        channels.append({"channel": ch, "label": CHANNEL_LABELS[ch], "configured": bool(globally),
                         "issue": catalog.channel_issue(user, ch)})
    events = []
    for key, ev in catalog.EVENTS.items():
        if not catalog.applies_to(user, key):
            continue
        events.append({"key": key, "label": ev.label, "description": ev.description, "group": ev.group,
                       "critical": catalog.is_critical(key), "locked": catalog.locked_channels(key),
                       "channels": catalog.channels_for(user, key), "chosen": prefs.get(key, [])})
    link = TelegramLink.objects.filter(user=user).first()
    return Response({"events": events, "channels": channels, "problems": catalog.delivery_problems(user),
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
