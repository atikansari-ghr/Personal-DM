"""Read/write access to registry-backed settings.

Change Set X: inside a web request, the settings are read once (one query for all global settings, one per person
for personal settings) and kept until the request ends; every request starts from the database again, so a change
is seen by the very next request in every server process. Secret settings are never kept: only whether one is
set. Outside requests (worker, scheduler, commands) every read goes to the database as before.
"""
from __future__ import annotations

import copy
import threading
from typing import Any

from . import crypto
from .models import AppSetting, UserSetting
from .registry import ADMIN, BY_KEY, GLOBAL, MAIN_ADMIN, SELF, USER, SettingError, coerce


_local = threading.local()
_SECRET_SET = object()  # marks "a secret is stored" in the request snapshot (never the secret itself)


def begin_request() -> None:
    _local.scope = {"app": None, "user": {}}
    _stats["requests"] = _stats.get("requests", 0) + 1


def end_request() -> None:
    _local.scope = None


_stats: dict = {"hits": 0, "misses": 0, "requests": 0}  # per process; shown in Admin → Performance


def cache_stats() -> dict:
    return dict(_stats)


def _app_rows() -> dict | None:
    sc = getattr(_local, "scope", None)
    if sc is None:
        return None
    if sc["app"] is None:
        _stats["misses"] += 1
        rows = {}
        for k, v in AppSetting.objects.values_list("key", "value"):
            d = BY_KEY.get(k)
            if d is not None and d.secret:
                rows[k] = _SECRET_SET if (v or {}).get("enc") else None
            else:
                rows[k] = v
        sc["app"] = rows
    else:
        _stats["hits"] += 1
    return sc["app"]


def _user_rows(user) -> dict | None:
    sc = getattr(_local, "scope", None)
    if sc is None or getattr(user, "pk", None) is None:
        return None
    rows = sc["user"].get(user.pk)
    if rows is None:
        _stats["misses"] += 1
        rows = dict(UserSetting.objects.filter(user=user).values_list("key", "value"))
        sc["user"][user.pk] = rows
    else:
        _stats["hits"] += 1
    return rows


def _invalidate(user=None) -> None:
    sc = getattr(_local, "scope", None)
    if sc is not None:
        if user is None:
            sc["app"] = None
        else:
            sc["user"].pop(user.pk, None)


def _copy(v):
    return copy.deepcopy(v) if isinstance(v, (list, dict)) else v


def get(key: str) -> Any:
    defn = BY_KEY[key]
    if not defn.secret:
        rows = _app_rows()
        if rows is not None:
            v = rows.get(key)
            return defn.default if v is None else _copy(v)
    row = AppSetting.objects.filter(key=key).first()
    if row is None or row.value is None:
        return defn.default
    if defn.secret:
        enc = (row.value or {}).get("enc")
        return crypto.decrypt(enc) if enc else ""
    return row.value


def is_set(key: str) -> bool:
    defn = BY_KEY[key]
    rows = _app_rows()
    if rows is not None:
        v = rows.get(key)
        return v is _SECRET_SET if defn.secret else v not in ("", [], None)
    row = AppSetting.objects.filter(key=key).first()
    if not row or row.value is None:
        return False
    if defn.secret:
        return bool((row.value or {}).get("enc"))
    return row.value not in ("", [], None)


def set_value(key: str, value: Any, actor=None) -> Any:
    _invalidate()
    if key.startswith("login.") or key == "general.app_name":
        from . import perfcache

        perfcache.invalidate("branding")  # the public sign-in page payload (Change Set X)
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
    rows = _user_rows(user)
    if rows is not None:
        return defn.default if key not in rows else _copy(rows[key])
    row = UserSetting.objects.filter(user=user, key=key).first()
    return defn.default if row is None else row.value


def set_user(user, key: str, value: Any) -> Any:
    defn = BY_KEY.get(key)
    if defn is None or defn.scope != USER:
        raise SettingError("Unknown setting.")
    value = coerce(defn, value)
    UserSetting.objects.update_or_create(user=user, key=key, defaults={"value": value})
    _invalidate(user)
    return value


def can_edit(user, key: str) -> bool:
    defn = BY_KEY.get(key)
    if not defn:
        return False
    if defn.editable_by == ADMIN:
        return bool(getattr(user, "is_main_admin", False) or getattr(user, "is_admin", False))
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
