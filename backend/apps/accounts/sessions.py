"""Per-device session tracking (list and sign out individual devices)."""
from __future__ import annotations

import re
from datetime import timedelta

from django.utils import timezone

from apps.core import audit

from .models import UserSession

TOUCH_EVERY = timedelta(minutes=2)


def describe(user_agent: str) -> str:
    ua = user_agent or ""
    browser = next((name for pat, name in (
        (r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"Firefox/", "Firefox"), (r"Chrome/", "Chrome"),
        (r"Safari/", "Safari")) if re.search(pat, ua)), "Browser")
    system = next((name for pat, name in (
        (r"iPhone|iPad", "iOS"), (r"Android", "Android"), (r"Windows", "Windows"), (r"Mac OS X|Macintosh", "macOS"),
        (r"CrOS", "ChromeOS"), (r"Linux", "Linux")) if re.search(pat, ua)), "unknown system")
    return f"{browser} on {system}"


def start(request, user, method: str) -> UserSession:
    row = UserSession.objects.create(user=user, ip=audit.client_ip(request), method=method[:40],
                                     user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300])
    request.session["device"] = str(row.id)
    return row


def check(request) -> bool:
    """False when this device session was revoked or ended; touches last_seen periodically."""
    device = request.session.get("device")
    if not device:
        return True  # sessions created before device tracking; ended by epoch changes as before
    row = UserSession.objects.filter(pk=device, user=request.user).first()
    if row is None or not row.active:
        return False
    now = timezone.now()
    if now - row.last_seen_at > TOUCH_EVERY:
        UserSession.objects.filter(pk=row.pk).update(last_seen_at=now, ip=audit.client_ip(request))
    return True


def end(request) -> None:
    device = request.session.get("device")
    if device:
        UserSession.objects.filter(pk=device, ended_at__isnull=True).update(ended_at=timezone.now())


def revoke_others(user, keep: str | None) -> int:
    return UserSession.objects.filter(user=user, revoked_at__isnull=True, ended_at__isnull=True).exclude(pk=keep).update(
        revoked_at=timezone.now())


def revoke_all(user) -> int:
    return revoke_others(user, None)


def active_for(user, max_age_days: int):
    since = timezone.now() - timedelta(days=max_age_days)
    return UserSession.objects.filter(user=user, revoked_at__isnull=True, ended_at__isnull=True, last_seen_at__gte=since)
