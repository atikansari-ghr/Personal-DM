"""Notification events, their class (critical or optional) and how channels are chosen.

* **Critical** events are chosen by the main administrator (``notifications.critical_events``). People cannot turn
  them off; they always arrive in-app and on every channel in ``notifications.critical_channels``. A required
  channel that cannot deliver (no email address, Telegram not linked, channel not configured) is recorded as
  "skipped" with the reason and shown to the person and the administrator — it is never reported as sent.
* **Optional** events are chosen per person, per channel (``me.notification_prefs``: event -> channels).
  Preferences never remove a critical event or a required channel.
"""
from __future__ import annotations

from apps.core import config

from .event_defs import CHANNELS, DEFAULT_CRITICAL, EVENTS, LABELS, Event  # noqa: F401 - re-exported


def critical_events() -> set[str]:
    return set(config.get("notifications.critical_events") or [])


def is_critical(key: str) -> bool:
    return key in critical_events()


def _legacy(user, key):
    from apps.core.models import UserSetting

    row = UserSetting.objects.filter(user=user, key=key).first()
    return None if row is None else row.value


def default_channels(user, key: str) -> list[str]:
    """What an optional event uses until the person chooses: catalogue default, narrowed by the older
    "my channels" / "other alerts by email/Telegram" preferences when those were set."""
    legacy_channels = _legacy(user, "me.channels")
    if key == "expiry.reminder":
        base = legacy_channels if legacy_channels is not None else config.get("notifications.default_channels")
        return [c for c in CHANNELS if c in set(base) | {"in_app"}]
    base = set(EVENTS[key].default_channels)
    if legacy_channels is not None:
        base &= set(legacy_channels) | {"in_app"}
    if _legacy(user, "me.event_alerts") is False:
        base &= {"in_app"}
    return [c for c in CHANNELS if c in base]


def preferences(user) -> dict[str, list[str]]:
    stored = config.get_user(user, "me.notification_prefs") or {}
    return {k: list(stored[k]) if k in stored else default_channels(user, k) for k in EVENTS}


def locked_channels(key: str) -> list[str]:
    """Channels the person cannot turn off for this event."""
    locked = set()
    if is_critical(key):
        locked |= set(config.get("notifications.critical_channels") or []) | {"in_app"}
    if key == "expiry.reminder":
        locked |= set(config.get("notifications.required_channels") or []) | {"in_app"}
    return [c for c in CHANNELS if c in locked]


def channels_for(user, key: str) -> list[str]:
    chosen = set(preferences(user).get(key, [])) | set(locked_channels(key))
    return [c for c in CHANNELS if c in chosen]


def channel_issue(user, channel: str) -> str | None:
    """Actionable reason a channel cannot deliver to this person, or None when it is ready."""
    if channel == "email":
        if not config.get("smtp.enabled"):
            return "Email is not configured by the administrator."
        if not user.email:
            return "No email address on the profile."
    if channel == "telegram":
        if not config.get("telegram.enabled"):
            return "Telegram is not configured by the administrator."
        if not hasattr(user, "telegram_link"):
            return "Telegram is not linked to the account."
    return None


def applies_to(user, key: str) -> bool:
    return not EVENTS[key].admins_only or user.is_main_admin


def delivery_problems(user) -> list[dict]:
    """Required (critical / required-for-reminders) channels that cannot reach this person."""
    out = {}
    for key in EVENTS:
        if not applies_to(user, key):
            continue
        for ch in locked_channels(key):
            issue = channel_issue(user, ch)
            if issue:
                out.setdefault(ch, {"channel": ch, "issue": issue, "events": []})["events"].append(LABELS[key])
    return list(out.values())


def coerce_prefs(value) -> dict:
    from apps.core.registry import SettingError

    if not isinstance(value, dict):
        raise SettingError("Notification preferences must map events to channels.")
    clean = {}
    for k, chans in value.items():
        if k not in EVENTS:
            raise SettingError(f"Unknown notification event: {k}.")
        if not isinstance(chans, list) or any(c not in CHANNELS for c in chans):
            raise SettingError(f"Channels must be from: {', '.join(CHANNELS)}.")
        clean[k] = [c for c in CHANNELS if c in chans]
    return clean
