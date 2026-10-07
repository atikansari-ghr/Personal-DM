"""Notification Center, push devices, template manager, previews / TEST messages and delivery history (Change Set O).

* People only ever read and change their own notifications.
* Templates, previews, TEST messages and delivery history are for the main administrator.
* A TEST message is clearly marked, goes only to the administrator who asked for it and creates no security record,
  document event or audit entry other than "notifications.test_sent".
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin
from apps.core import audit, config

from . import catalog, icons, rich, webpush
from .event_defs import CATEGORIES, EVENTS, SEVERITIES
from .models import ExpirySnooze, Notification, NotificationTemplate, OutboxMessage, PushSubscription


def _err(msg, status=400, **extra):
    return Response({"error": msg, **extra}, status=status)


def notification_json(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "event": n.event, "category": n.category or "system", "severity": n.severity or "info",
            "icon": n.icon or "bell", "title": n.title, "summary": n.summary, "body": n.body, "link": n.link,
            "created_at": n.created_at, "read": n.read_at is not None, "test": n.is_test,
            "details": (n.data or {}).get("details", []), "actions": (n.data or {}).get("actions", []),
            "guidance": (n.data or {}).get("guidance", []), "items": (n.data or {}).get("items", []),
            "items_label": (n.data or {}).get("items_label", "Files"), "more": (n.data or {}).get("more", 0),
            "icon_label": (n.data or {}).get("icon_label", "")}


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def notifications(request):
    """The person's own notifications, newest first, with category / severity / unread filters and a cursor."""
    qs = Notification.objects.filter(user=request.user)
    p = request.query_params
    unread_only = p.get("unread") in ("1", "true") or p.get("status") == "unread"
    if unread_only:
        qs = qs.filter(read_at__isnull=True)
    if p.get("category") in CATEGORIES:
        qs = qs.filter(category=p["category"])
    if p.get("severity") in SEVERITIES:
        qs = qs.filter(severity=p["severity"])
    if str(p.get("before", "")).isdigit():
        qs = qs.filter(id__lt=int(p["before"]))
    try:
        limit = max(1, min(int(p.get("limit", 30)), 100))
    except ValueError:
        limit = 30
    rows = list(qs.order_by("-id")[:limit + 1])
    mine = Notification.objects.filter(user=request.user)
    return Response({"notifications": [notification_json(n) for n in rows[:limit]],
                     "next": rows[limit - 1].id if len(rows) > limit else None,
                     "unread": mine.filter(read_at__isnull=True).count(),
                     "unread_by_severity": dict(mine.filter(read_at__isnull=True).values_list("severity").annotate(n=Count("id")))})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def mark_read(request):
    """Mark the given notifications (or all) read, or unread with ``unread: true``."""
    qs = Notification.objects.filter(user=request.user)
    if request.data.get("ids"):
        qs = qs.filter(id__in=[int(i) for i in request.data["ids"] if str(i).isdigit()])
    if request.data.get("unread"):
        qs.update(read_at=None)
    else:
        qs.filter(read_at__isnull=True).update(read_at=timezone.now())
    return Response({"status": "ok", "unread": Notification.objects.filter(user=request.user, read_at__isnull=True).count()})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def notification_action(request, pk):
    """In-app-only actions. Snooze pauses expiry reminders of that document for this person only, and only when
    the person can still open the document (checked now, not when the notification was created)."""
    from apps.library import permissions as P
    from apps.library.models import Document

    n = Notification.objects.filter(pk=pk, user=request.user).first()
    if n is None:
        return _err("Not found.", 404)
    action = request.data.get("action")
    if action != "snooze" or n.event != "expiry.reminder" or not n.document_id:
        return _err("This action is not available for this notification.")
    doc = Document.objects.filter(pk=n.document_id, archived_at__isnull=True).first()
    if doc is None or not P.AccessContext.build(request.user).can(doc, P.VIEW):
        return _err("Not found.", 404)
    days = 7
    until = timezone.localdate() + timedelta(days=days)
    ExpirySnooze.objects.update_or_create(user=request.user, document=doc, defaults={"until": until})
    Notification.objects.filter(pk=n.pk).update(read_at=timezone.now())
    audit.record("notifications.snooze", request=request, target=doc, days=days)
    return Response({"status": "snoozed", "until": until})


# ------------------------------------------------------------------ push devices

@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def push(request):
    """GET: public key and this person's devices. POST: register a browser subscription. DELETE: remove one."""
    if request.method == "GET":
        enabled = bool(config.get("notifications.push_enabled"))
        return Response({"enabled": enabled, "key": webpush.public_key() if enabled else None,
                         "preview": config.get_user(request.user, "me.push_preview") or "standard",
                         "devices": [{"id": s.id, "label": s.label, "created_at": s.created_at, "last_used_at": s.last_used_at,
                                      "error": s.last_error} for s in request.user.push_subscriptions.order_by("-created_at")]})
    if request.method == "DELETE":
        q = Q(pk=request.data.get("id")) if str(request.data.get("id", "")).isdigit() else Q(endpoint=request.data.get("endpoint", ""))
        n = PushSubscription.objects.filter(q, user=request.user).delete()[0]
        audit.record("notifications.push_unsubscribe", request=request, removed=n)
        return Response({"removed": n})
    if not config.get("notifications.push_enabled"):
        return _err("Push notifications are turned off by the administrator.")
    d = request.data
    endpoint = str(d.get("endpoint") or "")
    keys = d.get("keys") or {}
    if not webpush.allowed_endpoint(endpoint):
        return _err("This browser's push service is not supported (only Apple, Google, Mozilla and Microsoft push services).")
    p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
    try:
        if len(webpush.b64u_decode(p256dh)) != 65 or len(webpush.b64u_decode(auth)) != 16:
            raise ValueError
    except ValueError:
        return _err("Invalid push subscription keys.")
    PushSubscription.objects.filter(endpoint=endpoint).exclude(user=request.user).delete()
    PushSubscription.objects.update_or_create(endpoint=endpoint, defaults={
        "user": request.user, "p256dh": p256dh, "auth": auth, "label": str(d.get("label") or "")[:120], "last_error": ""})
    audit.record("notifications.push_subscribe", request=request)
    return Response({"status": "subscribed"}, status=201)


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def push_test(request):
    """A clearly marked TEST push to the person's own devices."""
    payload = {"title": "TEST · Personal Documents", "body": "Push notifications work on this device.", "url": "/notifications",
               "tag": "test", "severity": "info", "test": True}
    try:
        ref = webpush.deliver(request.user, payload)
    except webpush.PushError as exc:
        return _err(str(exc))
    audit.record("notifications.test_sent", request=request, channel="push")
    return Response({"status": "sent", "detail": ref})


# ------------------------------------------------------------------ template manager (main administrator)

def _template_json(t: NotificationTemplate | None) -> dict | None:
    if t is None:
        return None
    return {"channel": t.channel, "title": t.title, "heading": t.heading, "summary": t.summary, "icon": t.icon,
            "severity": t.severity, "action_labels": t.action_labels, "updated_at": t.updated_at,
            "updated_by": t.updated_by.display_name if t.updated_by_id and t.updated_by else None}


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def templates_list(request):
    overrides: dict = {}
    for t in NotificationTemplate.objects.select_related("updated_by"):
        overrides.setdefault(t.event, []).append(_template_json(t))
    events = []
    for key, ev in EVENTS.items():
        s = rich.sample(key)
        events.append({"key": key, "label": ev.label, "description": ev.description, "category": ev.category,
                       "severity": ev.severity, "icon": ev.icon, "critical": catalog.is_critical(key),
                       "always_critical": ev.always_critical, "admins_only": ev.admins_only,
                       "locked_channels": catalog.locked_channels(key),
                       "actions": [{"key": a.key, "label": a.label, "in_app_only": a.in_app_only} for a in s.actions],
                       "overrides": overrides.get(key, [])})
    return Response({"events": events, "placeholders": rich.PLACEHOLDERS,
                     "icons": [{"key": k, "emoji": v[0], "svg": v[1], "label": v[2]} for k, v in icons.ICONS.items()],
                     "severities": [{"key": k, "label": v[1]} for k, v in icons.SEVERITY.items()],
                     "categories": icons.CATEGORY_LABELS, "channels": list(catalog.CHANNELS)})


class _Draft:
    """An unsaved override for previews (same fields as NotificationTemplate)."""

    def __init__(self, data):
        self.title, self.heading, self.summary = data["title"], data["heading"], data["summary"]
        self.icon, self.severity, self.action_labels = data["icon"], data["severity"], data["action_labels"]


def _clean_template(event: str, d) -> dict:
    out = {"channel": d.get("channel") or ""}
    if out["channel"] not in ("", *catalog.CHANNELS):
        raise rich.TemplateError("Unknown channel.")
    out["title"] = rich.check_template_text(d.get("title", ""), field_name="Title / subject", limit=200)
    out["heading"] = rich.check_template_text(d.get("heading", ""), field_name="Heading", limit=200)
    out["summary"] = rich.check_template_text(d.get("summary", ""), field_name="Summary", limit=500)
    icon = d.get("icon") or ""
    if icon and icon not in icons.ICONS:
        raise rich.TemplateError("Choose an icon from the list.")
    out["icon"] = icon
    sev = d.get("severity") or ""
    if sev and sev not in icons.SEVERITY:
        raise rich.TemplateError("Unknown severity.")
    if sev and catalog.is_critical(event) and rich.SEVERITY_RANK[sev] < 1:
        raise rich.TemplateError("A critical notification cannot be shown as Information or Success.")
    out["severity"] = sev
    labels = d.get("action_labels") or {}
    if not isinstance(labels, dict):
        raise rich.TemplateError("Action labels must map an action to a label.")
    allowed = {a.key for a in rich.sample(event).actions} | {"open"}
    clean_labels = {}
    for k, v in labels.items():
        if k not in allowed:
            raise rich.TemplateError(f"Unknown action: {k}.")
        v = rich.check_template_text(v, field_name="Action label", limit=40)
        if v and rich._PH.search(v):
            raise rich.TemplateError("Action labels cannot contain placeholders.")
        if v:
            clean_labels[k] = v
    out["action_labels"] = clean_labels
    return out


@api_view(["PUT", "DELETE"])
@permission_classes([IsMainAdmin])
def template_detail(request, event):
    if event not in EVENTS:
        return _err("Unknown notification.", 404)
    channel = (request.data.get("channel") if request.method == "PUT" else request.query_params.get("channel")) or ""
    if request.method == "DELETE":
        n = NotificationTemplate.objects.filter(event=event, channel=channel).delete()[0]
        audit.record("notifications.template_reset", request=request, target_type="notification_template", target_id=event,
                     channel=channel or "all")
        return Response({"reset": bool(n)})
    try:
        clean = _clean_template(event, request.data)
    except rich.TemplateError as exc:
        return _err(str(exc))
    if not any(clean[k] for k in ("title", "heading", "summary", "icon", "severity")) and not clean["action_labels"]:
        NotificationTemplate.objects.filter(event=event, channel=clean["channel"]).delete()
        return Response({"reset": True})
    NotificationTemplate.objects.update_or_create(event=event, channel=clean["channel"], defaults={
        **{k: v for k, v in clean.items() if k != "channel"}, "updated_by": request.user})
    audit.record("notifications.template_update", request=request, target_type="notification_template", target_id=event,
                 channel=clean["channel"] or "all", fields=sorted(k for k, v in clean.items() if v and k != "channel"))
    return Response({"saved": True})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def template_preview(request, event):
    """Render the sample message for every channel (with an unsaved draft when given). Nothing is sent or stored."""
    if event not in EVENTS:
        return _err("Unknown notification.", 404)
    msg = rich.sample(event, request.user.display_name)
    if request.data.get("draft"):
        try:
            msg.draft = _Draft(_clean_template(event, request.data["draft"]))
        except rich.TemplateError as exc:
            return _err(str(exc))
    subject, text, html_doc = rich.render_email(msg, request.user)
    tg = rich.render_telegram(msg, request.user)
    return Response({"email": {"subject": subject, "text": text, "html": html_doc}, "telegram": tg,
                     "in_app": rich.render_in_app(msg), "push": rich.render_push(msg, request.user),
                     "note": "Sample data, marked TEST. Document numbers are hidden unless allowed in Notifications settings, "
                             "and never shown in push."})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def template_test(request, event):
    """Send the sample message, marked TEST, to the administrator's own channels now."""
    from .expiry import _in_app, deliver_one
    from . import templates

    if event not in EVENTS:
        return _err("Unknown notification.", 404)
    wanted = [c for c in request.data.get("channels") or ["in_app"] if c in catalog.CHANNELS]
    msg = rich.sample(event, request.user.display_name)
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    results = {}
    for channel in wanted:
        key = f"test:{event}:{stamp}:{request.user.pk}:{channel}"
        if channel == "in_app":
            card = rich.render_in_app(msg)
            _in_app(request.user, "test", f"test:{event}:{stamp}", card,
                    templates.render(user=request.user, title=card["title"], lines=[card["summary"]], header=False), msg, None)
            results[channel] = "sent"
            continue
        issue = catalog.channel_issue(request.user, channel)
        if issue:
            results[channel] = f"skipped: {issue}"
            continue
        html_part, payload = "", {}
        if channel == "email":
            subject, body, html_part = rich.render_email(msg, request.user)
        elif channel == "telegram":
            subject, body, _h = rich.render_email(msg, request.user)
            payload = rich.render_telegram(msg, request.user)
        else:
            payload = rich.render_push(msg, request.user)
            subject, body = payload["title"], payload["body"]
        out = OutboxMessage.objects.create(key=key[:250], user=request.user, channel=channel, kind="test", event=event,
                                           severity=msg.severity, subject=subject[:200], body=body, html=html_part,
                                           payload=payload, is_test=True, next_attempt_at=timezone.now())
        outcome = deliver_one(out)
        out.refresh_from_db()
        results[channel] = outcome if outcome != "failed" else f"failed: {out.last_error}"
    audit.record("notifications.test_sent", request=request, event=event, channels=wanted)
    return Response({"results": results})


# ------------------------------------------------------------------ delivery history (main administrator)

@api_view(["GET"])
@permission_classes([IsMainAdmin])
def delivery_history(request):
    qs = OutboxMessage.objects.select_related("user").exclude(channel="in_app")
    p = request.query_params
    if p.get("channel") in catalog.CHANNELS:
        qs = qs.filter(channel=p["channel"])
    if p.get("status") in ("pending", "sent", "failed", "skipped"):
        qs = qs.filter(status=p["status"])
    if p.get("event") in EVENTS:
        qs = qs.filter(event=p["event"])
    now = timezone.now()

    def state(m):
        if m.status == OutboxMessage.PENDING:
            return "retrying" if m.attempts else "queued"
        return m.status

    return Response({"deliveries": [{
        "id": m.id, "user": m.user.display_name, "channel": m.channel, "kind": m.kind, "event": m.event,
        "event_label": EVENTS[m.event].label if m.event in EVENTS else m.kind, "severity": m.severity, "subject": m.subject,
        "status": m.status, "state": state(m), "attempts": m.attempts, "error": m.last_error, "created_at": m.created_at,
        "sent_at": m.sent_at, "next_attempt_at": m.next_attempt_at if m.status == OutboxMessage.PENDING else None,
        "delivered": "accepted by the provider" if m.status == OutboxMessage.SENT and m.provider_ref else
                     ("not reported by the provider" if m.status == OutboxMessage.SENT else None),
        "test": m.is_test, "overdue": bool(m.status == OutboxMessage.PENDING and m.next_attempt_at and m.next_attempt_at < now - timedelta(hours=1)),
    } for m in qs[:300]]})
