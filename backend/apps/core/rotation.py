"""Automatic sign-in design rotation (Change Set W).

The main administrator chooses a pool of at least two valid designs, Sequential (pool order, wrapping) or Random
(avoids repeating the current design), and a Daily / Weekly / Monthly time in the installation timezone. A monthly
day 29-31 runs on the last day of shorter months (``ops.schedule``).

* Manual activation never turns rotation off; the next scheduled rotation continues normally.
* An open sign-in page is not refreshed; the new design appears on the next page load.
* After downtime nothing is replayed: Sequential works out which design should be active now (one step per missed
  occurrence, applied once), Random makes one recovery choice. Both are audited with the missed interval.
* Unavailable or deleted pool designs are skipped (audited, main administrators notified). With fewer than two valid
  designs rotation shows "Needs Attention" and does nothing; with none the protected default is used.
* Routine rotations are recorded in the audit log only; only problems notify the main administrators.
"""
from __future__ import annotations

import random
from datetime import datetime

from django.utils import timezone

from . import config, designs

FREQUENCIES = ("daily", "weekly", "monthly")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
RUN = "signin_rotation"


class RotationError(ValueError):
    pass


def settings_() -> dict:
    base = {"enabled": False, "mode": "sequential", "pool": [], "frequency": "weekly", "time": "06:00",
            "weekday": "mon", "month_day": 1}
    return {**base, **(config.get("login.rotation") or {})}


def spec(cfg: dict | None = None) -> dict:
    cfg = cfg or settings_()
    return {"enabled": bool(cfg.get("enabled")), "frequency": cfg["frequency"], "time": cfg["time"],
            "weekday": cfg["weekday"], "month_day": int(cfg.get("month_day") or 1)}


def _now_local() -> datetime:
    from apps.notify.expiry import local_now

    return local_now()


def _run():
    from apps.notify.models import SchedulerRun

    run, _ = SchedulerRun.objects.get_or_create(name=RUN)
    return run


def valid(d) -> bool:
    if d is None:
        return False
    if d.builtin or not d.assets.get("original"):
        return True
    return designs._assets_ok(d)


def pool_designs(cfg: dict | None = None):
    """[(id, design-or-None, valid)] in pool order."""
    from .models import SigninDesign

    cfg = cfg or settings_()
    by_id = {d.pk: d for d in SigninDesign.objects.filter(pk__in=cfg.get("pool") or [])}
    return [(pk, by_id.get(pk), valid(by_id.get(pk))) for pk in cfg.get("pool") or []]


def configure(data: dict, *, actor=None) -> dict:
    from .models import SigninDesign

    cfg = settings_()
    for k in ("enabled", "mode", "pool", "frequency", "time", "weekday", "month_day"):
        if k in data:
            cfg[k] = data[k]
    cfg["enabled"] = bool(cfg["enabled"])
    if cfg["mode"] not in ("sequential", "random"):
        raise RotationError("Choose Sequential or Random.")
    if cfg["frequency"] not in FREQUENCIES:
        raise RotationError("Choose Daily, Weekly or Monthly.")
    t = str(cfg["time"] or "")
    try:
        h, m = (int(x) for x in t.split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
    except (ValueError, AssertionError):
        raise RotationError("Enter a time as HH:MM.")
    cfg["time"] = f"{h:02d}:{m:02d}"
    if cfg["weekday"] not in WEEKDAYS:
        raise RotationError("Choose a weekday.")
    try:
        cfg["month_day"] = int(cfg["month_day"])
        assert 1 <= cfg["month_day"] <= 31
    except (TypeError, ValueError, AssertionError):
        raise RotationError("Choose a day of the month from 1 to 31.")
    try:
        pool = [int(x) for x in (cfg["pool"] or [])]
    except (TypeError, ValueError):
        raise RotationError("The pool lists designs.")
    pool = list(dict.fromkeys(pool))  # order kept, duplicates removed
    existing = set(SigninDesign.objects.filter(pk__in=pool).values_list("pk", flat=True))
    unknown = [p for p in pool if p not in existing]
    if unknown:
        raise RotationError("The pool contains a design that no longer exists.")
    cfg["pool"] = pool
    if cfg["enabled"] and sum(1 for _pk, _d, ok in pool_designs(cfg) if ok) < 2:
        raise RotationError("Choose at least two valid designs for the rotation pool.")
    config.set_value("login.rotation", cfg, actor=actor)
    run = _run()
    if not cfg["enabled"]:
        run.state = {**(run.state or {}), "attention": ""}
    else:
        run.last_run_at = run.last_run_at or timezone.now()  # first rotation is the next scheduled moment, not now
    run.save()
    from . import audit

    audit.record("settings.signin_rotation", actor=actor, enabled=cfg["enabled"], mode=cfg["mode"],
                 frequency=cfg["frequency"], pool_size=len(pool))
    return status()


def _occurrences_since(last: datetime, now_local: datetime) -> int:
    """How many scheduled moments passed in (last, now] (capped; only used to reconcile Sequential mode)."""
    from apps.ops import schedule

    n, moment = 0, last.astimezone(now_local.tzinfo)
    for _ in range(400):
        nxt = schedule.next_occurrence(moment, spec())
        if nxt is None or nxt > now_local:
            break
        n += 1
        moment = nxt
    return n


def _attention(message: str, *, tag: str) -> None:
    run = _run()
    run.state = {**(run.state or {}), "attention": message}
    run.save(update_fields=["state"])
    designs._alert(message, tag=f"rotation:{tag}")


def rotate(*, steps: int = 1, reason: str = "scheduled", now=None) -> dict:
    """Activate the next design of the pool. Returns what happened (also stored for the status card)."""
    from . import audit

    cfg = settings_()
    entries = pool_designs(cfg)
    skipped = [(pk, d) for pk, d, ok in entries if not ok]
    for pk, d in skipped:
        name = d.name if d else f"#{pk} (deleted)"
        audit.record("settings.signin_rotation_skip", design=name, reason="unavailable" if d else "deleted")
        if d is not None and d.state != d.UNAVAILABLE:
            designs._mark_unavailable(d, "The wallpaper file is missing or damaged.")
    if skipped:
        names = ", ".join((d.name if d else f"#{pk}") for pk, d in skipped)
        _attention(f"Sign-in design rotation skipped unavailable design(s): {names}.", tag="skipped")
    ok = [d for _pk, d, good in entries if good]
    current = designs.active()
    if not ok:
        if not current.builtin or current.builtin_key != designs.DEFAULT_KEY:
            designs._set_active(designs.default_design(), actor=None, reason="rotation: no valid design")
        _attention("Sign-in design rotation has no valid design left; the built-in default is shown. "
                   "Repair the pool in Settings → Overview & sign-in.", tag="empty")
        return {"result": "fallback", "design": designs.DEFAULT_KEY}
    if len(ok) < 2:
        _attention("Sign-in design rotation needs at least two valid designs; it is paused until the pool is repaired.",
                   tag="insufficient")
        return {"result": "needs_attention"}
    if cfg["mode"] == "random":
        choices = [d for d in ok if d.pk != current.pk] or ok
        target = random.choice(choices)
    else:
        ids = [d.pk for d in ok]
        if current.pk in ids:
            target = ok[(ids.index(current.pk) + steps) % len(ok)]
        else:
            pos = int((_run().state or {}).get("position", -1))
            target = ok[(pos + steps) % len(ok)]
    if target.pk != current.pk:
        designs._set_active(target, actor=None, reason=f"rotation ({reason})")  # audited; no notification
    run = _run()
    run.last_run_at = now or timezone.now()
    run.state = {**(run.state or {}), "position": [d.pk for d in ok].index(target.pk), "last_design": target.pk,
                 "last_name": target.name, "last_at": (now or timezone.now()).isoformat(), "attention": "",
                 "last_reason": reason}
    run.save()
    audit.record("settings.signin_rotation_run", design=target.name, mode=cfg["mode"], reason=reason, steps=steps)
    return {"result": "rotated", "design": target.pk}


def tick(now_local: datetime | None = None) -> dict | None:
    """Called by the scheduler every ~30 s. Runs at most one rotation per call, whatever was missed."""
    from apps.ops import schedule

    cfg = settings_()
    if not cfg["enabled"]:
        return None
    now_local = now_local or _now_local()
    run = _run()
    occ = schedule.due(now_local, run.last_run_at, spec(cfg))
    if occ is None:
        return None
    missed = _occurrences_since(run.last_run_at, now_local) if run.last_run_at else 1
    if missed > 1:
        from . import audit

        audit.record("settings.signin_rotation_missed", missed=missed, since=run.last_run_at.isoformat(),
                     mode=cfg["mode"], action="reconciled once" if cfg["mode"] == "sequential" else "one recovery choice")
        steps = missed if cfg["mode"] == "sequential" else 1
        return rotate(steps=steps, reason=f"recovered {missed} missed rotations", now=timezone.now())
    return rotate(steps=1, reason="scheduled", now=timezone.now())


def status() -> dict:
    from apps.ops import schedule

    cfg = settings_()
    entries = pool_designs(cfg)
    n_ok = sum(1 for _pk, _d, ok in entries if ok)
    run = _run()
    st = run.state or {}
    now_local = _now_local()
    nxt = schedule.next_occurrence(now_local, spec(cfg)) if cfg["enabled"] else None
    if not cfg["enabled"]:
        state = "off"
    elif n_ok < 2:
        state = "needs_attention"
    else:
        state = "needs_attention" if st.get("attention") else "on"
    current = designs.active()
    return {**cfg, "timezone": config.get("general.timezone"), "state": state, "attention": st.get("attention", "")
            or ("At least two valid designs are needed." if cfg["enabled"] and n_ok < 2 else ""),
            "current": {"id": current.pk, "name": current.name},
            "last_rotation": {"at": st.get("last_at"), "design": st.get("last_name")} if st.get("last_at") else None,
            "next_rotation": nxt.isoformat() if nxt else None,
            "describe": schedule.describe_spec(spec(cfg)) if cfg["enabled"] else "Off",
            "pool_detail": [{"id": pk, "name": d.name if d else "(deleted)", "valid": ok,
                             "reason": "" if ok else ("deleted" if d is None else d.state_detail or "unavailable")}
                            for pk, d, ok in entries]}


def preview() -> dict:
    """What the rotation will do, without changing the live design or the scheduler position."""
    st = status()
    entries = pool_designs()
    ok = [d for _pk, d, good in entries if good]
    current = designs.active()
    ids = [d.pk for d in ok]
    if st["mode"] == "sequential" and ok:
        i = ids.index(current.pk) if current.pk in ids else int((_run().state or {}).get("position", -1))
        prev_d, next_d = ok[(i - 1) % len(ok)], ok[(i + 1) % len(ok)]
    else:
        prev_d, next_d = None, None
    return {"status": st, "order": [designs.payload(d) | {"valid": True} for d in ok],
            "invalid": [p for p in st["pool_detail"] if not p["valid"]],
            "previous": designs.payload(prev_d) if prev_d else None, "next": designs.payload(next_d) if next_d else None,
            "random_note": "In Random mode the next design is chosen at the scheduled moment; it avoids repeating the "
                           "current design." if st["mode"] == "random" else ""}
