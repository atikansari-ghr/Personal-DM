"""One consistent layout for in-app, email and Telegram messages.

    Notification from <site name>
    Account: <username> (<display name>)

    <what happened>
    Folder: …   Date/time: …   Device: …   IP address: …   Country: …   Sign-in method: …
    Files:
    1. a.pdf
    2. b.pdf
    … and 12 more (see the report)

    Review: https://<site>/<page that requires sign-in>

Never included: passwords, one-time codes, TOTP seeds, recovery codes, passkey material, tokens, API keys,
document numbers, file contents or anything about documents the recipient may not open. Long digit runs in
names (which are often document numbers) are masked, and names can be left out entirely
(``notifications.include_names``). Links only open after signing in, with the normal permission checks.
"""
from __future__ import annotations

import re
import zoneinfo

from django.conf import settings
from django.utils import timezone

from apps.core import config

MAX_ITEMS = 10
_DIGIT_RUN = re.compile(r"\d{6,}")


def mask_numbers(text: str) -> str:
    """'Passport Z9988776' -> 'Passport Z99••••'; dates like '22July2026' stay readable."""
    def repl(m):
        s = m.group(0)
        return s[:2] + "•" * (len(s) - 2)
    return _DIGIT_RUN.sub(repl, text or "")


def name(value: str) -> str:
    """A folder/document/file name as it may appear in an external message."""
    if not config.get("notifications.include_names"):
        return "(name hidden)"
    return mask_numbers(value)


def local_stamp(when=None) -> str:
    tz = config.get("general.timezone")
    dt = (when or timezone.now()).astimezone(zoneinfo.ZoneInfo(tz))
    return f"{dt:%d %b %Y %H:%M} ({tz})"


class Name(str):
    """A folder/document/file name inside a fact: shown as-is in the app, masked (or hidden) in email/Telegram."""


def text(value, external: bool) -> str:
    """Resolve a title/line given as text or as ``lambda name: f"… {name(x)} …"``."""
    if callable(value):
        return value(name if external else (lambda s: s))
    return value


def render(*, user, title, lines=(), facts=(), items=(), items_label: str = "Files", more: int = 0,
           link: str = "", header: bool = True) -> str:
    """``header`` (email/Telegram) adds the site/account lines, the review link and masks names; in-app omits them."""
    external = header
    out: list[str] = []
    if header:
        out += [f"Notification from {config.get('general.app_name')}", f"Account: {user.username} ({user.display_name})", ""]
    out.append(text(title, external))
    out += [text(ln, external) for ln in lines if ln]
    shown = [(k, v) for k, v in facts if v not in (None, "")]
    if shown:
        out.append("")
        out += [f"{k}: {name(v) if external and isinstance(v, Name) else v}" for k, v in shown]
    if items:
        out += ["", f"{items_label}:"]
        out += [f"{i}. {name(n) if external else n}" for i, n in enumerate(items[:MAX_ITEMS], 1)]
        extra = more + max(0, len(items) - MAX_ITEMS)
        if extra:
            out.append(f"… and {extra} more (see the report)")
    if link:
        out += ["", f"Review: {settings.PUBLIC_ORIGIN}{link}"]
    return "\n".join(out)


def subject(title: str) -> str:
    return f"{config.get('general.app_name')}: {title}"[:200]
