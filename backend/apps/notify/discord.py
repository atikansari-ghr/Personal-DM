"""Discord delivery through official Discord webhooks (one per person).

* A webhook address contains its secret token; it is stored encrypted and only a non-secret hint is ever shown.
* Only https://discord.com/api/webhooks/<id>/<token> (and the discordapp.com / ptb / canary variants) are accepted,
  so a webhook can never be used to make the server call another address.
* Messages are short embeds rendered from the same structured event as every other channel; no attachments, no
  document text, mentions are disabled (allowed_mentions: none).
* Verification after a recovery reads the webhook's metadata (GET) - it never posts a message.
"""
from __future__ import annotations

import re

import requests
from django.utils import timezone

from apps.core import config, crypto

WEBHOOK = re.compile(r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/(?:v\d+/)?webhooks/(\d{5,25})/([A-Za-z0-9_\-]{30,100})/?$")
SEVERITY_COLOURS = {"critical": 0xB42318, "warning": 0xB54708, "success": 0x1E6B3A, "info": 0x175CD3}


class DiscordError(Exception):
    pass


def validate(url: str) -> str:
    url = (url or "").strip()
    if not WEBHOOK.match(url):
        raise DiscordError("Paste a Discord webhook address (https://discord.com/api/webhooks/…). Create one in Discord: "
                           "Server settings → Integrations → Webhooks → New webhook → Copy webhook URL.")
    return url


def hint(url: str) -> str:
    m = WEBHOOK.match(url)
    return f"webhook …{m.group(1)[-4:]}" if m else "webhook"


def _url(hook) -> str:
    return crypto.decrypt(hook.url_enc)


def save(user, url: str):
    from .models import DiscordWebhook

    url = validate(url)
    hook, _ = DiscordWebhook.objects.update_or_create(user=user, defaults={"url_enc": crypto.encrypt(url), "hint": hint(url),
                                                                              "status": "untested", "last_error": "", "enabled": True})
    return hook


def post(hook, payload: dict) -> str:
    try:
        r = requests.post(_url(hook) + "?wait=true", json={**payload, "allowed_mentions": {"parse": []}}, timeout=20)
    except requests.RequestException as exc:
        raise DiscordError(f"Discord unreachable ({exc.__class__.__name__})") from exc
    if r.status_code in (401, 404):
        hook.status, hook.last_error = "removed_by_discord", "Discord says the webhook no longer exists"
        hook.save(update_fields=["status", "last_error"])
        raise DiscordError("The webhook was deleted in Discord. Add a new one in My account → Notifications.")
    if r.status_code == 429:
        raise DiscordError("Discord rate limit; will retry")
    if r.status_code >= 300:
        raise DiscordError(f"Discord refused the message (HTTP {r.status_code})")
    hook.status, hook.last_error, hook.last_tested_at = "connected", "", timezone.now()
    hook.save(update_fields=["status", "last_error", "last_tested_at"])
    try:
        return str(r.json().get("id", ""))
    except ValueError:
        return ""


def render(msg, user) -> dict:
    """Embed from the structured message (names masked like email/Telegram)."""
    from . import icons, rich, templates

    t = rich.apply_template(msg, "discord", external=True)
    fields = [{"name": d.label[:250], "value": str(v)[:1000], "inline": True} for d, v in rich._details(msg, "telegram")][:8]
    lines = [t["summary"]] if t["summary"] else []
    lines += [f"⚠️ {templates.text(m, True)}" for m in msg.mandatory]
    actions = [a for a in rich._actions(msg, "telegram", t["labels"]) if a.path]
    if actions:
        lines.append(" · ".join(f"[{a.label}]({rich._url(a.path)})" for a in actions[:3]))
    title = ("[TEST] " if msg.test else "") + f"{icons.emoji(t['icon'])} {t['title']}"
    return {"username": config.get("general.app_name")[:80],
            "embeds": [{"title": title[:250], "description": "\n".join(lines)[:3500], "color": SEVERITY_COLOURS.get(t["severity"], 0x175CD3),
                        "fields": fields, "footer": {"text": f"{icons.SEVERITY[t['severity']][1]} · {templates.local_stamp(msg.when)}"}}]}


def send_test(user) -> str:
    hook = getattr(user, "discord_webhook", None)
    if hook is None:
        raise DiscordError("Add your Discord webhook first.")
    return post(hook, {"username": config.get("general.app_name")[:80],
                       "embeds": [{"title": "🧪 Test notification", "color": SEVERITY_COLOURS["info"],
                                   "description": "Discord delivery from Personal DM works. This is a test; no real event happened."}]})


def verify_all() -> int:
    """GET each enabled webhook (metadata only). Returns how many are broken."""
    from .models import DiscordWebhook

    bad = 0
    for hook in DiscordWebhook.objects.filter(enabled=True):
        try:
            r = requests.get(_url(hook), timeout=15)
            ok = r.status_code == 200
        except requests.RequestException:
            ok = False
        if not ok:
            bad += 1
            hook.status, hook.last_error = "failed", "Webhook not reachable after recovery"
            hook.save(update_fields=["status", "last_error"])
    return bad
