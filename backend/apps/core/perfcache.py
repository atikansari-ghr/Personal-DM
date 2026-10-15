"""Small shared cache for derived, non-private summaries (Change Set X).

Only for data that is the same for everyone allowed to see it and that may be a few seconds old: the public
sign-in page design, the administrators' backup and security health summaries. Never for permissions, sessions,
documents, metadata or secrets: those are always read fresh.

The cache is file-based (``<data dir>/cache/shared``), so every web worker, the job worker and the scheduler see the
same entries, and an invalidation in one process takes effect in all of them at once. Each name has a generation
number; ``invalidate(name)`` bumps it, which retires every entry of that name. Entries also expire on their own
(``ttl``) as a safety net. Hits and misses are counted per process for Admin → Performance.
"""
from __future__ import annotations

import time
from typing import Any, Callable

_stats: dict[str, dict] = {}


def _cache():
    from django.core.cache import caches

    return caches["shared"]


def _gen(name: str) -> int:
    try:
        return int(_cache().get(f"gen:{name}") or 0)
    except Exception:  # noqa: BLE001 - an unreadable cache is a miss, never an error
        return 0


def cached(name: str, ttl: int, fn: Callable[[], Any], key: str = "") -> Any:
    st = _stats.setdefault(name, {"hits": 0, "misses": 0, "fill_ms": 0.0})
    full = f"{name}:{_gen(name)}:{key}"
    try:
        hit = _cache().get(full, _MISSING)
    except Exception:  # noqa: BLE001
        hit = _MISSING
    if hit is not _MISSING:
        st["hits"] += 1
        return hit
    st["misses"] += 1
    t = time.perf_counter()
    value = fn()
    st["fill_ms"] += (time.perf_counter() - t) * 1000
    try:
        _cache().set(full, value, ttl)
    except Exception:  # noqa: BLE001 - caching is an optimisation only
        pass
    return value


def invalidate(*names: str) -> None:
    for name in names:
        try:
            c = _cache()
            try:
                c.incr(f"gen:{name}")
            except ValueError:  # not set yet
                c.set(f"gen:{name}", 1, None)
        except Exception:  # noqa: BLE001
            pass


def stats() -> dict:
    return {k: dict(v, hit_rate=round(v["hits"] / max(1, v["hits"] + v["misses"]), 2)) for k, v in _stats.items()}


class _Missing:
    pass


_MISSING = _Missing()
