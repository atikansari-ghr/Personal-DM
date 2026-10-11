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


DEVICE_COOKIE = "pd_device"
DEVICE_COOKIE_DAYS = 400


def recognize(request, user):
    """The person's recognised device for this browser (random cookie token; only its hash is stored). A browser
    without a valid cookie becomes a new device. Unrecognised (revoked) devices are never re-used."""
    import hashlib
    import secrets

    from apps.security.login_audit import parse_user_agent
    from apps.security.models import RecognizedDevice

    token = request.COOKIES.get(DEVICE_COOKIE, "") if request is not None else ""
    raw = getattr(request, "_request", request)  # DRF wraps the HttpRequest; the middleware sees the inner one
    now = timezone.now()
    browser, system, kind = parse_user_agent((request.META.get("HTTP_USER_AGENT") or "") if request else "")
    if token:
        h = hashlib.sha256(token.encode()).hexdigest()
        dev = RecognizedDevice.objects.filter(user=user, token_hash=h, revoked_at__isnull=True).first()
        if dev is not None:
            RecognizedDevice.objects.filter(pk=dev.pk).update(last_seen=now, last_ip=audit.client_ip(request))
            raw._pd_device, raw._pd_device_new = dev, False
            return dev
    token = secrets.token_urlsafe(32)
    dev = RecognizedDevice.objects.create(user=user, token_hash=hashlib.sha256(token.encode()).hexdigest(), browser=browser, os=system,
                                          device=kind, label=f"{browser or 'Browser'} on {system or 'unknown system'}"[:80],
                                          last_ip=audit.client_ip(request))
    raw._pd_device, raw._pd_device_new, raw._pd_device_cookie = dev, True, token
    return dev


def start(request, user, method: str) -> UserSession:
    try:
        dev = recognize(request, user)
    except Exception:  # noqa: BLE001 - device recognition must never block a sign-in
        dev = None
    row = UserSession.objects.create(user=user, ip=audit.client_ip(request), method=method[:40],
                                     user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300], recognized_device=dev)
    request.session["device"] = str(row.id)
    return row


def revoke_device(device) -> int:
    """Mark Unrecognized: end every session of that device and drop its recognition."""
    n = UserSession.objects.filter(recognized_device=device, revoked_at__isnull=True, ended_at__isnull=True).update(revoked_at=timezone.now())
    device.status, device.revoked_at = "unrecognized", timezone.now()
    device.save(update_fields=["status", "revoked_at"])
    return n


def check(request) -> bool:
    """False when this device session was revoked or ended; touches last_seen periodically."""
    device = request.session.get("device")
    if not device:
        return True  # sessions created before device tracking; ended by epoch changes as before
    row = UserSession.objects.filter(pk=device, user=request.user).select_related("recognized_device").first()
    if row is None or not row.active:
        return False
    if row.recognized_device is not None and row.recognized_device.revoked_at is not None:
        return False  # the device was marked Unrecognized
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
