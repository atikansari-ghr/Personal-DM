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

from .models import ExpiryMark, Notification, OutboxMessage

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


def expiry_message(doc, days: int, user=None, header: bool = True) -> tuple[str, str, str]:
    """Only name, document type, expiry date, days remaining and a login-required link (never the number)."""
    from . import templates

    name = doc.owner.display_name
    dtype = doc.doc_type.name if doc.doc_type_id else "document"
    when = doc.expiry_date.strftime("%d %b %Y")
    link = f"/documents/{doc.id}"
    if days == 0:
        subject = f"{name}'s {dtype} expires today"
    else:
        subject = f"{name}'s {dtype} expires in {days} day{'s' if days != 1 else ''}"
    facts = [("Expiry date", when), ("Days left", str(days))]
    if user is None:
        body = f"{subject} ({when}).\nSign in to view: {settings.PUBLIC_ORIGIN}{link}"
    else:
        body = templates.render(user=user, title=f"{subject}.", facts=facts, link=link if header else "", header=header)
    return subject, body, link


def dispatch(user, *, kind: str, key: str, subject: str, body: str, link: str = "", document=None,
             external_subject: str | None = None, external_body: str | None = None, event: str = "expiry.reminder") -> dict:
    """Deliver one notification for ``event`` on the channels it resolves to (critical / required channels plus
    the person's choices). Returns {channel: "queued" | "skipped: <reason>" | "in-app"}."""
    result = {}
    for channel in channels_for(user, event):
        if channel == "in_app":
            _in_app(user, kind, key, subject, body, link, document)
            result[channel] = "in-app"
            continue
        issue = channel_issue(user, channel)
        try:
            with transaction.atomic():  # savepoint: a duplicate key must not poison an enclosing transaction
                OutboxMessage.objects.create(key=f"{key}:{user.pk}:{channel}"[:250], user=user, channel=channel, kind=kind,
                                             subject=(external_subject or subject)[:200], body=external_body or body, document=document,
                                             status=OutboxMessage.SKIPPED if issue else OutboxMessage.PENDING,
                                             last_error=issue or "", next_attempt_at=timezone.now())
        except IntegrityError:
            pass  # already queued by an earlier (possibly interrupted) run
        result[channel] = f"skipped: {issue}" if issue else "queued"
    return result


def _in_app(user, kind, key, subject, body, link, document):
    marker = f"{key}:{user.pk}:in_app"[:250]
    try:
        with transaction.atomic():
            OutboxMessage.objects.create(key=marker, user=user, channel="in_app", kind=kind, subject=subject, body=body,
                                         document=document, status=OutboxMessage.SENT, sent_at=timezone.now())
            Notification.objects.create(user=user, kind=kind, title=subject, body=body, link=link, document=document)
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
        reached = [t for t in thresholds if days <= t]
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
            for user in recipients_for(doc):
                subject, external, link = expiry_message(doc, days, user)
                body = expiry_message(doc, days, user, header=False)[1]
                dispatch(user, kind="expiry", key=key, subject=subject, body=body, link=link, document=doc,
                         external_subject=subject, external_body=external, event="expiry.reminder")
            sent += 1
    return {"date": today.isoformat(), "reminders": sent, "skipped_thresholds": skipped}


def on_expiry_changed(doc, old_expiry) -> None:
    if old_expiry:
        OutboxMessage.objects.filter(document=doc, kind="expiry", status=OutboxMessage.PENDING,
                                     key__contains=f":{old_expiry.isoformat()}:").update(
            status=OutboxMessage.SKIPPED, last_error="Expiry date changed")


MAX_ATTEMPTS = 5


def deliver_outbox(limit: int = 100) -> dict:
    from . import telegram
    from .mailer import send_mail_now

    now = timezone.now()
    done = failed = 0
    for msg in OutboxMessage.objects.filter(status=OutboxMessage.PENDING, next_attempt_at__lte=now).select_related("user")[:limit]:
        # Re-check state at execution time.
        if not msg.user.is_active or (msg.document_id and msg.document and msg.document.archived_at):
            msg.status, msg.last_error = OutboxMessage.SKIPPED, "Recipient disabled or document archived"
            msg.save(update_fields=["status", "last_error"])
            continue
        issue = channel_issue(msg.user, msg.channel)
        if issue:
            msg.status, msg.last_error = OutboxMessage.SKIPPED, issue
            msg.save(update_fields=["status", "last_error"])
            continue
        msg.attempts += 1
        try:
            if msg.channel == "email":
                send_mail_now(msg.user.email, msg.subject, msg.body)
            elif msg.channel == "telegram":
                telegram.send(msg.user.telegram_link.chat_id, msg.body)
            msg.status, msg.sent_at, msg.last_error = OutboxMessage.SENT, timezone.now(), ""
            done += 1
        except Exception as exc:  # noqa: BLE001
            from apps.core.logging import redact

            msg.last_error = redact(f"{exc.__class__.__name__}: {exc}")[:500]
            if msg.attempts >= MAX_ATTEMPTS:
                msg.status = OutboxMessage.FAILED
            else:
                msg.next_attempt_at = timezone.now() + timedelta(minutes=5 * (2 ** (msg.attempts - 1)))
            failed += 1
        msg.save(update_fields=["status", "sent_at", "last_error", "attempts", "next_attempt_at"])
    return {"sent": done, "failed": failed}
