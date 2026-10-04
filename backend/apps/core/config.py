"""Read/write access to registry-backed settings."""
from __future__ import annotations

from typing import Any

from . import crypto
from .models import AppSetting, UserSetting
from .registry import BY_KEY, GLOBAL, MAIN_ADMIN, SELF, USER, SettingError, coerce


def get(key: str) -> Any:
    defn = BY_KEY[key]
    row = AppSetting.objects.filter(key=key).first()
    if row is None or row.value is None:
        return defn.default
    if defn.secret:
        enc = (row.value or {}).get("enc")
        return crypto.decrypt(enc) if enc else ""
    return row.value


def is_set(key: str) -> bool:
    defn = BY_KEY[key]
    row = AppSetting.objects.filter(key=key).first()
    if not row or row.value is None:
        return False
    if defn.secret:
        return bool((row.value or {}).get("enc"))
    return row.value not in ("", [], None)


def set_value(key: str, value: Any, actor=None) -> Any:
    defn = BY_KEY.get(key)
    if defn is None or defn.scope != GLOBAL:
        raise SettingError("Unknown setting.")
    if defn.secret:
        # Secrets: empty string keeps the current value; {"clear": true} removes it.
        if isinstance(value, dict) and value.get("clear"):
            AppSetting.objects.update_or_create(key=key, defaults={"value": None, "updated_by": actor})
            return None
        if value in (None, ""):
            return None
        value = coerce(defn, value)
        AppSetting.objects.update_or_create(key=key, defaults={"value": {"enc": crypto.encrypt(value)}, "updated_by": actor})
        return None
    value = coerce(defn, value)
    AppSetting.objects.update_or_create(key=key, defaults={"value": value, "updated_by": actor})
    return value


def get_user(user, key: str) -> Any:
    defn = BY_KEY[key]
    row = UserSetting.objects.filter(user=user, key=key).first()
    return defn.default if row is None else row.value


def set_user(user, key: str, value: Any) -> Any:
    defn = BY_KEY.get(key)
    if defn is None or defn.scope != USER:
        raise SettingError("Unknown setting.")
    value = coerce(defn, value)
    UserSetting.objects.update_or_create(user=user, key=key, defaults={"value": value})
    return value


def can_edit(user, key: str) -> bool:
    defn = BY_KEY.get(key)
    if not defn:
        return False
    if defn.editable_by == MAIN_ADMIN:
        return bool(getattr(user, "is_main_admin", False))
    return defn.editable_by == SELF


def snapshot_global(include_secrets: bool = False) -> dict:
    out = {}
    for key, defn in BY_KEY.items():
        if defn.scope != GLOBAL:
            continue
        if defn.secret:
            out[key] = {"configured": is_set(key)}
            if include_secrets:
                row = AppSetting.objects.filter(key=key).first()
                out[key]["enc"] = (row.value or {}).get("enc") if row and row.value else None
        else:
            out[key] = get(key)
    return out
