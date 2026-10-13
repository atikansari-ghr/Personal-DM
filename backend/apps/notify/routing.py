"""Per-person notification routing (Change Set T): fallback chains, quiet hours and digests.

Order of decisions for one event and one person:
1. Channels come from the existing matrix (``catalog.channels_for``): critical/required channels are locked on.
2. If the person set a **fallback chain** for the event's category (e.g. WhatsApp → Telegram → Email), the chain's
   channels are not sent in parallel: only the first ready channel is queued; the next one is used only when it
   fails (after ``notifications.fallback_after_attempts`` attempts) or is disconnected. A channel the administrator
   requires (critical/locked) is always delivered on its own, independently of the chain.
3. **Urgent** messages (critical severity, events the administrator made critical - the mandatory policy) are
   never held and never put into a digest.
4. **Quiet hours** (person's timezone): other messages to external channels wait until the quiet period ends.
   In-app notifications are silent and always arrive immediately.
5. **Digest** (daily/weekly per category): other messages to external channels are collected and sent as one
   summary per channel at the person's digest time (weekly: Mondays).
"""
from __future__ import annotations

import html
import zoneinfo
from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.core import config

from .event_defs import EVENTS, EXTERNAL, route_of


def user_tz(user) -> zoneinfo.ZoneInfo:
    name = config.get_user(user, "me.timezone") or config.get("general.timezone")
    try:
        return zoneinfo.ZoneInfo(name)
    except Exception:  # noqa: BLE001
        return zoneinfo.ZoneInfo(config.get("general.timezone"))


def conf(user, category: str) -> dict:
    r = (config.get_user(user, "me.notification_routing") or {}).get(category) or {}
    return {"fallback": list(r.get("fallback") or []), "digest": r.get("digest") or "immediate"}


def urgent(message) -> bool:
    from .catalog import is_critical

    ev = EVENTS.get(message.event)
    # critical severity, or an event the administrator made critical (mandatory policy). Informational security
    # notices (new address, new sign-in) follow quiet hours and digests like everything else.
    return message.severity == "critical" or (ev is not None and is_critical(message.event))


def _parse(hhmm: str) -> time:
    h, m = (int(x) for x in hhmm.split(":"))
    return time(h, m)


def quiet_until(user, now=None) -> datetime | None:
    q = config.get_user(user, "me.quiet_hours") or {}
    if not q.get("enabled"):
        return None
    tz = user_tz(user)
    now = (now or timezone.now()).astimezone(tz)
    start, end = _parse(q.get("start", "22:00")), _parse(q.get("end", "07:00"))
    t = now.time()
    if start == end:
        return None
    inside = (start <= t < end) if start < end else (t >= start or t < end)
    if not inside:
        return None
    end_dt = datetime.combine(now.date(), end, tzinfo=tz)
    if end_dt <= now:
        end_dt += timedelta(days=1)
    return end_dt


def plan(user, message, channels: list[str], locked: list[str]) -> list[dict]:
    """[{channel, route, chain, hold, at}] for the external channels (in-app is handled by the caller)."""
    from .catalog import channel_issue

    cat = route_of(message.event)
    c = conf(user, cat)
    is_urgent = urgent(message)
    out = []
    chain = [ch for ch in c["fallback"] if ch in EXTERNAL]
    chosen = [ch for ch in channels if ch in EXTERNAL]
    independent = [ch for ch in chosen if ch not in chain or ch in locked]
    for ch in independent:
        out.append({"channel": ch, "route": "mandatory" if ch in locked else "direct", "chain": []})
    rest = [ch for ch in chain if ch not in locked]
    if rest:
        # first ready channel of the chain; disconnected ones are recorded as skipped with "fallback used"
        for i, ch in enumerate(rest):
            issue = channel_issue(user, ch)
            if issue and i < len(rest) - 1:
                out.append({"channel": ch, "route": "primary" if i == 0 else "fallback", "chain": [], "skip": f"Channel Disconnected: {issue}"})
                continue
            out.append({"channel": ch, "route": "primary" if i == 0 else "fallback", "chain": rest[i + 1:]})
            break
    now = timezone.now()
    q = None if is_urgent else quiet_until(user, now)
    for item in out:
        item["hold"], item["at"] = "", now
        if is_urgent or item.get("skip") or item["route"] == "mandatory":
            continue
        if c["digest"] in ("daily", "weekly"):
            item["hold"] = "digest"
        elif q is not None:
            item["hold"], item["at"] = "quiet_hours", q
    return out


def fallback_after() -> int:
    return int(config.get("notifications.fallback_after_attempts"))


def digest_due(user, last_sent: datetime | None, period: str, now=None) -> bool:
    tz = user_tz(user)
    now = (now or timezone.now()).astimezone(tz)
    at = _parse(config.get_user(user, "me.digest_time") or "08:00")
    if now.time() < at:
        return False
    if period == "weekly" and now.weekday() != 0:
        return False
    if last_sent is None:
        return True
    last_local = last_sent.astimezone(tz)
    return last_local.date() < now.date()


def run_digests(now=None) -> int:
    """Send one summary per person, channel and period. Items stay linked to their digest message."""
    from django.db import transaction

    from apps.accounts.models import User

    from . import templates
    from .models import OutboxMessage, SchedulerRun

    sent = 0
    waiting = OutboxMessage.objects.filter(status=OutboxMessage.DIGEST).values_list("user_id", flat=True).distinct()
    for uid in set(waiting):
        user = User.objects.filter(pk=uid, is_active=True).first()
        if user is None:
            continue
        items = list(OutboxMessage.objects.filter(user=user, status=OutboxMessage.DIGEST).order_by("created_at"))
        for period in ("daily", "weekly"):
            row, _ = SchedulerRun.objects.get_or_create(name=f"digest:{user.pk}:{period}")
            if not digest_due(user, row.last_run_at, period, now):
                continue
            mine = [m for m in items if conf(user, route_of(m.event) if m.event else "system")["digest"] == period]
            by_channel: dict[str, list] = {}
            for m in mine:
                by_channel.setdefault(m.channel, []).append(m)
            for ch, msgs in by_channel.items():
                title = f"Your {period} summary: {len(msgs)} notification{'s' if len(msgs) != 1 else ''}"
                body = templates.render(user=user, title=title, lines=["Open the Notification Center to see each one."],
                                        items=[m.subject for m in msgs], items_label="Notifications", link="/notifications")
                payload = {}
                if ch == "telegram":
                    payload = {"text": f"🗓️ <b>{title}</b>\n" + "\n".join(f"• {html.escape(m.subject)}" for m in msgs[:20]),
                               "parse_mode": "HTML", "disable_web_page_preview": True}
                elif ch == "push":
                    payload = {"title": title, "body": "Open the app to read them.", "url": "/notifications", "severity": "info"}
                with transaction.atomic():
                    dig = OutboxMessage.objects.create(key=f"digest:{user.pk}:{ch}:{period}:{timezone.now():%Y%m%d%H%M}", user=user, channel=ch,
                                                       kind="digest", subject=title[:200], body=body, payload=payload, event="",
                                                       severity="info", route="digest", next_attempt_at=timezone.now())
                    OutboxMessage.objects.filter(pk__in=[m.pk for m in msgs]).update(status=OutboxMessage.DIGESTED, digest=dig)
                sent += 1
            SchedulerRun.objects.filter(pk=row.pk).update(last_run_at=timezone.now())
    return sent


STATUS_LABELS = {"sent": "Delivered", "failed": "Failed", "retrying": "Retrying", "fallback": "Fallback Used", "skipped": "Not delivered",
                 "disconnected": "Channel Disconnected", "queued": "Queued", "held": "Held (quiet hours)", "digest": "Waiting for digest",
                 "digested": "Sent in digest", "not_selected": "Not Selected", "expired": "Expired",
                 "superseded": "Superseded"}


def state_of(m) -> str:
    from .models import OutboxMessage

    if m.status == OutboxMessage.PENDING:
        if m.hold == "quiet_hours" and m.next_attempt_at and m.next_attempt_at > timezone.now():
            return "held"
        return "retrying" if m.attempts else "queued"
    if m.status == OutboxMessage.SKIPPED and (m.last_error or "").startswith(("Channel Disconnected", "Telegram is not linked", "No device",
                                                                               "WhatsApp", "Discord", "No email")):
        return "disconnected"
    return m.status
