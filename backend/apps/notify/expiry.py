"""Expiry reminder scheduling and multi-channel delivery.

Policies (documented in docs/guides/expiry-rules.md):
* Thresholds come from notifications.expiry_days (default 90/60/30/7/0); expiry dates are date-only.
* "Today" is the date in the installation timezone at the time of the run.
* On each run, for every active (non-archived, non-superseded) document with a *confirmed* expiry date,
  the smallest threshold already reached is sent once; larger reached thresholds that were never sent are
  marked skipped (catch-up after missed runs / new imports never floods users with historic reminders).
* Nothing is sent after the expiry day. Expired records stay labelled until renewed or archived.
* A changed/corrected expiry date starts a new schedule (marks are keyed by expiry date) and pending
  deliveries for the old date are cancelled.
* A record that has been renewed (a newer non-archived record renews it) is superseded: no reminders.
* Recipients are resolved at send time: owner, the head of the owner's reminder group, and delegates of
  that group holding the `notifications` scope. Disabled accounts are skipped; duplicates removed.
* Outbox keys make retries and scheduler restarts idempotent.
"""
from __future__ import annotations

import logging
import zoneinfo
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import config

from .models import ExpiryMark, ExpirySnooze, Notification, OutboxMessage

log = logging.getLogger("personaldocs.notify")


def local_now() -> datetime:
    return timezone.now().astimezone(zoneinfo.ZoneInfo(config.get("general.timezone")))


def local_today() -> date:
    return local_now().date()


def recipients_for(doc) -> list:
    from apps.accounts.models import Delegation

    out = []
    owner = doc.owner
    if config.get("notifications.notify_owner") and owner.is_active:
        out.append(owner)
    group = owner.reminder_group
    if group is not None:
        if config.get("notifications.notify_head") and group.head_id and group.head.is_active:
            out.append(group.head)
        for d in Delegation.objects.filter(group=group).select_related("delegate"):
            if "notifications" in d.scopes and d.delegate.is_active:
                out.append(d.delegate)
    seen, unique = set(), []
    for u in out:
        if u.pk not in seen:
            seen.add(u.pk)
            unique.append(u)
    return unique


def channels_for(user, event: str = "expiry.reminder") -> list[str]:
    from .catalog import channels_for as resolve

    return resolve(user, event)


def channel_issue(user, channel: str) -> str | None:
    from .catalog import channel_issue as issue

    return issue(user, channel)


def expiry_details(doc, days: int):
    """Facts for an expiry message from the document type's template (Change Set N): only confirmed values;
    the document number is marked sensitive (masked, opt-in, never on lock screens)."""
    from apps.library import doctypes
    from apps.library.models import DocumentField
    from apps.library.services import folder_path

    from .rich import Detail
    from .templates import Name

    dtype = doc.doc_type.name if doc.doc_type_id else "Document (type not assigned)"
    confirmed = {f.key: f.value for f in doc.fields.filter(status=DocumentField.CONFIRMED).exclude(scope="unmapped") if f.value}
    labels = {f.key: f.label for f in doctypes.active_fields(doc.doc_type)} if doc.doc_type_id else {}
    number_key = "document_number"
    details = [Detail("Document type", dtype, "document")]
    if confirmed.get("full_name"):
        details.append(Detail(labels.get("full_name", "Full name"), Name(confirmed["full_name"]), "user"))
    else:
        details.append(Detail("Owner", doc.owner.display_name, "user"))
    if confirmed.get(number_key):
        details.append(Detail(labels.get(number_key, "Document number"), confirmed[number_key], "key", sensitive=True))
    details.append(Detail("Expiry date", fmt_date(doc.expiry_date), "calendar", emphasis=True))
    details.append(Detail("Days left", "Expires today" if days == 0 else f"{days} day{'s' if days != 1 else ''}", "time", emphasis=True))
    try:
        details.append(Detail("Location", Name(" > ".join(f.name for f in folder_path(doc.folder) if f.parent_id)), "folder"))
    except Exception:  # noqa: BLE001 - a missing folder never blocks a reminder
        pass
    return dtype, details


def _folder_text(doc) -> str:
    from apps.library.services import folder_path

    try:
        return " > ".join(f.name for f in folder_path(doc.folder) if f.parent_id)
    except Exception:  # noqa: BLE001
        return ""


def fmt_date(d) -> str:
    fmt = config.get("general.date_format") or "d MMM yyyy"
    py = {"d MMM yyyy": "%-d %b %Y", "yyyy-MM-dd": "%Y-%m-%d", "dd/MM/yyyy": "%d/%m/%Y", "MM/dd/yyyy": "%m/%d/%Y"}.get(fmt, "%-d %b %Y")
    return d.strftime(py)


def expiry_message(doc, days: int, user=None):
    """The structured expiry reminder: type, confirmed holder name, expiry date from the expiry-role field, days left,
    folder; actions Open document / Go to folder / Expiring documents / Snooze (in the app)."""
    from .rich import Action, Message

    dtype, details = expiry_details(doc, days)
    owner = doc.owner.display_name
    short = dtype if doc.doc_type_id else "document"
    mine = user is not None and user.pk == doc.owner_id
    whose = "Your" if mine else f"{owner}'s"
    if days == 0:
        heading, summary, severity = f"{whose} {short} expires today", "Renew it as soon as possible.", "critical"
    else:
        heading = f"{whose} {short} is expiring soon"
        summary = f"The document will expire in {days} day{'s' if days != 1 else ''} ({fmt_date(doc.expiry_date)})."
        severity = "critical" if days <= 7 else "warning" if days <= 60 else "info"
    # subject keeps the earlier wording (owner and type), used by filters people may have set up
    title = f"{owner}'s {short} expires today" if days == 0 else f"{owner}'s {short} expires in {days} day{'s' if days != 1 else ''}"
    actions = [Action("open_document", "Open Document", f"/documents/{doc.id}", primary=True),
               Action("folder", "Go to Folder", f"/folders/{doc.folder_id}"),
               Action("reminders", "View Expiry Reminders", "/search?expiring_days=90"),
               Action("snooze", "Snooze 7 days", "", in_app_only=True)]
    return Message(event="expiry.reminder", title=title, heading=heading, summary=summary, severity=severity,
                   push_title=f"{short[:1].upper()}{short[1:]} Expiry Alert",
                   icon="calendar", details=details, actions=actions, link=f"/documents/{doc.id}",
                   guidance=["Renew the document before the expiry date.", "Upload the renewed document with Add renewed document."],
                   context={"document_name": doc.title, "document_type": short, "owner_name": owner,
                            "expiry_date": fmt_date(doc.expiry_date), "days_remaining": str(days),
                            "folder_path": _folder_text(doc),
                            "document_id": str(doc.id), "tag": str(doc.id)})


def dispatch(user, message, *, kind: str, key: str, document=None, group: str = "") -> dict:
    """Deliver one structured message for ``message.event`` on the channels it resolves to (critical / required
    channels plus the person's choices). Every channel is rendered from the same message.
    Returns {channel: "in-app" | "queued" | "skipped: <reason>"}."""
    from . import rich, templates

    if message.secret_link:  # a token link must never reach the outbox, in-app history or chat channels
        raise ValueError("messages with a secret link are sent directly (send_direct_email), not dispatched")
    event = message.event
    result = {}
    for channel in channels_for(user, event):
        if channel == "in_app":
            card = rich.render_in_app(message)
            body = templates.render(user=user, title=card["title"], lines=[x for x in (card["summary"],) if x] + card["guidance"],
                                    facts=[(d["label"], d["value"]) for d in card["details"]], items=message.items,
                                    items_label=message.items_label, more=message.more, header=False)
            _in_app(user, kind, key, card, body, message, document, group)
            result[channel] = "in-app"
            continue
        issue = channel_issue(user, channel)
        html_part, payload = "", {}
        if channel == "email":
            subject, body, html_part = rich.render_email(message, user)
        elif channel == "telegram":
            subject, body, _h = rich.render_email(message, user)
            payload = rich.render_telegram(message, user)
        else:  # push
            payload = rich.render_push(message, user)
            subject, body = payload["title"], payload["body"]
        try:
            with transaction.atomic():  # savepoint: a duplicate key must not poison an enclosing transaction
                OutboxMessage.objects.create(key=f"{key}:{user.pk}:{channel}"[:250], user=user, channel=channel, kind=kind,
                                             subject=subject[:200], body=body, html=html_part, payload=payload,
                                             event=event, severity=message.severity, document=document,
                                             is_test=message.test,
                                             status=OutboxMessage.SKIPPED if issue else OutboxMessage.PENDING,
                                             last_error=issue or "", next_attempt_at=timezone.now())
        except IntegrityError:
            pass  # already queued by an earlier (possibly interrupted) run
        result[channel] = f"skipped: {issue}" if issue else "queued"
    return result


def _in_app(user, kind, key, card, body, message, document, group=""):
    marker = f"{key}:{user.pk}:in_app"[:250]
    data = {k: card[k] for k in ("details", "actions", "guidance", "items", "items_label", "more", "heading", "icon_label")}
    if group:
        data["group"] = group
    try:
        with transaction.atomic():
            OutboxMessage.objects.create(key=marker, user=user, channel="in_app", kind=kind, subject=card["title"], body=body,
                                         event=message.event, severity=card["severity"], document=document,
                                         is_test=message.test, status=OutboxMessage.SENT, sent_at=timezone.now())
            Notification.objects.create(user=user, kind=kind, title=card["title"], body=body, link=message.link,
                                        document=document, event=message.event, category=card["category"],
                                        severity=card["severity"], icon=card["icon"], summary=card["summary"][:500],
                                        data=data, is_test=message.test)
    except IntegrityError:
        pass


def run_expiry_scan(today: date | None = None) -> dict:
    from apps.library.models import Document

    today = today or local_today()
    thresholds = sorted(config.get("notifications.expiry_days"))
    sent = skipped = 0
    docs = (Document.objects.filter(archived_at__isnull=True, expiry_date__isnull=False, expiry_date__gte=today,
                                    owner__is_active=True)
            .select_related("owner", "owner__reminder_group", "owner__reminder_group__head", "doc_type"))
    for doc in docs.iterator():
        if doc.renewed_by.filter(archived_at__isnull=True).exists():
            continue
        days = (doc.expiry_date - today).days
        own = doc.doc_type.reminder_days if doc.doc_type_id and doc.doc_type.reminder_days else None
        reached = [t for t in (sorted(own) if own else thresholds) if days <= t]  # a type may set its own days
        if not reached:
            continue
        target = min(reached)
        marks = set(ExpiryMark.objects.filter(document=doc, expiry_date=doc.expiry_date).values_list("threshold", flat=True))
        if target in marks:
            continue
        with transaction.atomic():
            for t in reached:
                if t != target and t not in marks:
                    ExpiryMark.objects.get_or_create(document=doc, expiry_date=doc.expiry_date, threshold=t, defaults={"action": "skipped"})
                    skipped += 1
            _m, created = ExpiryMark.objects.get_or_create(document=doc, expiry_date=doc.expiry_date, threshold=target,
                                                           defaults={"action": "sent"})
            if not created:
                continue
            key = f"expiry:{doc.id}:{doc.expiry_date.isoformat()}:{target}"
            snoozed = set(ExpirySnooze.objects.filter(document=doc, until__gte=today).values_list("user_id", flat=True))
            for user in recipients_for(doc):
                if user.pk in snoozed:
                    continue  # the person paused reminders for this document (in-app Snooze)
                dispatch(user, expiry_message(doc, days, user), kind="expiry", key=key, document=doc)
            sent += 1
    return {"date": today.isoformat(), "reminders": sent, "skipped_thresholds": skipped}


def on_expiry_changed(doc, old_expiry) -> None:
    if old_expiry:
        OutboxMessage.objects.filter(document=doc, kind="expiry", status=OutboxMessage.PENDING,
                                     key__contains=f":{old_expiry.isoformat()}:").update(
            status=OutboxMessage.SKIPPED, last_error="Expiry date changed")


MAX_ATTEMPTS = 5


def deliver_outbox(limit: int = 100) -> dict:
    now = timezone.now()
    done = failed = 0
    for msg in OutboxMessage.objects.filter(status=OutboxMessage.PENDING, next_attempt_at__lte=now).select_related("user")[:limit]:
        outcome = deliver_one(msg)
        done += outcome == "sent"
        failed += outcome == "failed"
    return {"sent": done, "failed": failed}


def deliver_one(msg) -> str:
    """Send one queued message now. Returns "sent", "skipped" or "failed" (failures retry with back-off)."""
    from . import mailer, telegram

    # Re-check state at execution time.
    if not msg.user.is_active or (msg.document_id and msg.document and msg.document.archived_at):
        msg.status, msg.last_error = OutboxMessage.SKIPPED, "Recipient disabled or document archived"
        msg.save(update_fields=["status", "last_error"])
        return "skipped"
    issue = channel_issue(msg.user, msg.channel)
    if issue:
        msg.status, msg.last_error = OutboxMessage.SKIPPED, issue
        msg.save(update_fields=["status", "last_error"])
        return "skipped"
    msg.attempts += 1
    outcome = "sent"
    try:
        ref = ""
        if msg.channel == "email":
            if msg.html:
                mailer.send_mail_now(msg.user.email, msg.subject, msg.body, html=msg.html)
            else:
                mailer.send_mail_now(msg.user.email, msg.subject, msg.body)
        elif msg.channel == "telegram":
            ref = telegram.send(msg.user.telegram_link.chat_id, msg.body, msg.payload or None)
        elif msg.channel == "push":
            from . import webpush

            ref = webpush.deliver(msg.user, msg.payload or {"title": msg.subject, "body": msg.body, "url": "/notifications"},
                                  severity=msg.severity)
        msg.status, msg.sent_at, msg.last_error = OutboxMessage.SENT, timezone.now(), ""
        msg.provider_ref = str(ref or "")[:120]
    except Exception as exc:  # noqa: BLE001
        from apps.core.logging import redact

        msg.last_error = redact(f"{exc.__class__.__name__}: {exc}")[:500]
        if msg.attempts >= MAX_ATTEMPTS:
            msg.status = OutboxMessage.FAILED
        else:
            msg.next_attempt_at = timezone.now() + timedelta(minutes=5 * (2 ** (msg.attempts - 1)))
        outcome = "failed"
    msg.save(update_fields=["status", "sent_at", "last_error", "attempts", "next_attempt_at", "provider_ref"])
    return outcome
