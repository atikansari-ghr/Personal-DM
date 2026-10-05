"""Application-level login audit (who signed in, how, from where).

Only safe metadata is stored: never passwords, one-time codes, recovery codes, tokens or cookies.
"""
from __future__ import annotations

import logging
import re

from . import geoip, netutil

log = logging.getLogger("personaldocs.security")


def parse_user_agent(ua: str) -> tuple[str, str, str]:
    ua = ua or ""
    if re.search(r"bot|crawler|spider|curl|wget|python-requests|httpclient|scanner", ua, re.I):
        device = "bot"
    elif re.search(r"iPad|Tablet|Android(?!.*Mobile)", ua):
        device = "tablet"
    elif re.search(r"Mobi|iPhone|Android", ua):
        device = "mobile"
    else:
        device = "desktop" if ua else ""
    browser = next((n for p, n in ((r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"Firefox/", "Firefox"),
                                   (r"Chrome/", "Chrome"), (r"Safari/", "Safari"), (r"curl/", "curl")) if re.search(p, ua)), "Other" if ua else "")
    system = next((n for p, n in ((r"iPhone|iPad", "iOS"), (r"Android", "Android"), (r"Windows", "Windows"),
                                  (r"Mac OS X|Macintosh", "macOS"), (r"CrOS", "ChromeOS"), (r"Linux", "Linux")) if re.search(p, ua)), "Other" if ua else "")
    return browser, system, device


def record(request, *, result: str, user=None, username: str = "", method: str = "", reason: str = "", flags=None):
    """Create a LoginEvent; never raises (auditing must not break sign-in)."""
    from .models import LoginEvent

    try:
        ip = netutil.client_ip(request)
        geo = geoip.lookup(ip) if ip else None
        browser, system, device = parse_user_agent((request.META.get("HTTP_USER_AGENT") or "") if request else "")
        flags = list(flags or [])
        decision = getattr(request, "access_decision", None)
        if decision is not None and decision.exception and result == LoginEvent.SUCCESS:
            flags.append("policy_exception")
        if user is not None and result == LoginEvent.SUCCESS:
            prior = LoginEvent.objects.filter(user=user, result=LoginEvent.SUCCESS)
            if prior.exists():
                if ip and not prior.filter(ip=ip).exists():
                    flags.append("new_ip")
                if geo and not prior.filter(country=geo[0]).exists():
                    flags.append("new_country")
        session = getattr(request, "session", None)
        event = LoginEvent.objects.create(
            user=user if (user is not None and getattr(user, "pk", None)) else None,
            username=(username or getattr(user, "username", "") or "")[:150],
            result=result, method=(method or "")[:40], reason=(reason or "")[:40], ip=ip,
            country=geo[0] if geo else "", country_name=geo[1][:80] if geo else "",
            browser=browser, os=system, device=device,
            correlation=(session.get("device", "") if session is not None else "")[:64],
            totp_used="totp" in method or "recovery" in method, passkey_used="passkey" in method,
            oidc_used="google" in method, flags=sorted(set(flags)),
        )
    except Exception:  # noqa: BLE001
        log.exception("login audit failed")
        return None
    try:
        from . import alerts

        alerts.on_login_event(event)
    except Exception:  # noqa: BLE001
        log.exception("security alert failed")
    return event
