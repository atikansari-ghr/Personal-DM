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

    subject, body, _ = expiry.expiry_message(_D(), 30)
    return Response({"subject": subject, "body": body,
                     "note": "Messages never include document numbers or attachments; the link requires sign-in and permission."})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def run_reminders_now(request):
    result = expiry.run_expiry_scan()
    result.update(expiry.deliver_outbox())
    audit.record("notifications.run_now", request=request, **{k: v for k, v in result.items() if k != "date"})
    return Response(result)
