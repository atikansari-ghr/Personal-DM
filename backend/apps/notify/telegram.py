"""Telegram Bot API adapter and verified chat linking."""
from __future__ import annotations

import re
import secrets
from datetime import timedelta

import requests
from django.utils import timezone

from apps.core import config, crypto

from .models import SchedulerRun, TelegramLink, TelegramLinkCode

API = "https://api.telegram.org"


class TelegramError(Exception):
    pass


def _token() -> str:
    token = config.get("telegram.bot_token")
    if not config.get("telegram.enabled") or not token:
        raise TelegramError("Telegram is not configured. Configure it in Settings → Connections.")
    return token


def _call(method: str, **params) -> dict:
    token = _token()
    try:
        resp = requests.post(f"{API}/bot{token}/{method}", json=params, timeout=20)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise TelegramError(f"Telegram request failed: {exc.__class__.__name__}") from exc
    if not data.get("ok"):
        raise TelegramError(f"Telegram error: {str(data.get('description', 'unknown'))[:200]}")
    return data


def send(chat_id: str, text: str, payload: dict | None = None) -> str:
    """Plain text, or the rich ``payload`` (HTML parse mode + inline URL buttons). If Telegram rejects the rich form
    (e.g. a button URL it does not accept) the plain text is sent instead, so a notification is never lost."""
    if payload and payload.get("text"):
        try:
            data = _call("sendMessage", chat_id=chat_id, **payload)
            return str(data.get("result", {}).get("message_id", ""))
        except TelegramError:
            pass
    data = _call("sendMessage", chat_id=chat_id, text=text[:4000], disable_web_page_preview=True)
    return str(data.get("result", {}).get("message_id", ""))


def test_connection() -> dict:
    data = _call("getMe")
    return {"bot": data["result"].get("username")}


def new_link_code(user) -> dict:
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    TelegramLinkCode.objects.filter(user=user, used_at__isnull=True).delete()
    TelegramLinkCode.objects.create(user=user, code_hash=crypto.hash_token(code), expires_at=timezone.now() + timedelta(minutes=15))
    bot = config.get("telegram.bot_username")
    return {"code": code, "deep_link": f"https://t.me/{bot}?start={code}" if bot else None, "expires_minutes": 15}


def process_updates(updates: list[dict]) -> int:
    """Link chats that sent `/start CODE`. Only the chat that sends a valid, unexpired code is linked."""
    linked = 0
    for upd in updates:
        msg = upd.get("message") or {}
        text = (msg.get("text") or "").strip()
        m = re.fullmatch(r"/start\s+([A-Z0-9]{8})", text, re.I)
        chat = msg.get("chat") or {}
        if not m or chat.get("type") != "private":
            continue
        row = TelegramLinkCode.objects.filter(code_hash=crypto.hash_token(m.group(1).upper()), used_at__isnull=True,
                                              expires_at__gt=timezone.now()).select_related("user").first()
        if row is None or not row.user.is_active:
            continue
        chat_id = str(chat["id"])
        TelegramLink.objects.filter(chat_id=chat_id).exclude(user=row.user).delete()
        TelegramLink.objects.update_or_create(user=row.user, defaults={"chat_id": chat_id, "username": str(chat.get("username", ""))[:80]})
        row.used_at = timezone.now()
        row.save(update_fields=["used_at"])
        try:
            send(chat_id, f"Linked to {config.get('general.app_name')} for {row.user.display_name}.")
        except TelegramError:
            pass
        linked += 1
    return linked


def poll_updates() -> int:
    state, _ = SchedulerRun.objects.get_or_create(name="telegram_updates")
    offset = state.state.get("offset", 0)
    data = _call("getUpdates", offset=offset, timeout=0, allowed_updates=["message"])
    updates = data.get("result", [])
    if updates:
        state.state = {"offset": max(u["update_id"] for u in updates) + 1}
        state.save()
    return process_updates(updates)
