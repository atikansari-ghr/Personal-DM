"""Active Sessions (Change Set AB): who is signed in, from where, and how recently they did something.

* **Active**    — a valid session whose last *activity* (a request the person made, not a background refresh) was
  within ``security.session_active_minutes`` (default 5).
* **Signed In** — a valid session whose last activity is older than that.

Activity comes from the requests people already make: ``sessions.check()`` updates ``last_activity_at`` at most every
``touch_interval()`` (never a per-second heartbeat), and requests the app marks ``X-PD-Background: 1`` (notification
polling, offline sync, progress polling) keep the session alive without counting as activity.

Location and trust reuse the sign-in architecture: Trusted Zone first, then the private-network classification, then
the local GeoIP database, labelled **approximate** (never GPS, never street level). Lookups are memoised per address
for one listing, so a page of sessions costs a fixed number of queries.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.core import audit, config

TRUST_LABELS = {"trusted_zone": "Trusted", "private": "Private network", "public": "Untrusted", "unknown": "Unknown"}
RISK_ORDER = {"": 0, "normal": 0, "low": 1, "warning": 2, "high": 3}


def threshold() -> timedelta:
    return timedelta(minutes=int(config.get("security.session_active_minutes")))


def touch_interval() -> timedelta:
    """How often a session's activity time is written: often enough for the Active threshold, never per request."""
    return min(timedelta(minutes=2), threshold() / 2)


def valid_sessions():
    from apps.accounts.models import UserSession

    since = timezone.now() - timedelta(days=int(config.get("auth.session_days")))
    return UserSession.objects.filter(revoked_at__isnull=True, ended_at__isnull=True, last_seen_at__gte=since,
                                      user__is_active=True)


def visible(viewer):
    """Sessions this person may see: the main administrator all, a scoped administrator their delegated members (and
    themselves), everybody else only their own."""
    from .views_signins import visible_user_ids

    qs = valid_sessions().select_related("user", "recognized_device")
    if not (viewer.is_main_admin or viewer.is_admin):
        return qs.filter(user=viewer)
    ids = visible_user_ids(viewer)
    return qs if ids is None else qs.filter(user_id__in=ids)


def _login_events(session_ids: list[str]) -> dict:
    from .models import LoginEvent

    out = {}
    for ev in (LoginEvent.objects.filter(correlation__in=session_ids, result=LoginEvent.SUCCESS)
               .only("correlation", "risk", "risk_reasons", "network", "zone_name", "location", "method", "browser", "os", "device", "at")
               .order_by("at")):
        out[ev.correlation] = ev  # the sign-in that created the session
    return out


class _Resolver:
    """Location/trust per address, once per listing (no N+1, no remote calls: the GeoIP database is local)."""

    def __init__(self):
        from .models import TrustedZone

        self.memo, self.zones = {}, list(TrustedZone.objects.all().order_by("id"))

    def __call__(self, ip):
        key = str(ip or "")
        if key not in self.memo:
            from . import location

            try:
                r = location.resolve(key or None, zones=self.zones)
            except Exception:  # noqa: BLE001 - a broken GeoIP file must not hide sessions
                r = {"network": "unknown", "location": "Unknown"}
            self.memo[key] = {"network": r.get("network", "unknown"), "zone": r.get("zone_name", ""),
                              "location": r.get("location", "Unknown"), "country": r.get("country", "")}
        return self.memo[key]


def _label_location(loc: dict) -> dict:
    net = loc["network"]
    source = {"trusted_zone": "Trusted Zone", "private": "Private network", "public": "GeoIP (approximate)"}.get(net, "Unknown")
    approx = net == "public" and "approximate" in loc["location"].lower()
    text = loc["location"].replace(" (approximate)", "")
    return {"text": text, "source": source, "approximate": approx, "zone": loc["zone"], "country": loc["country"]}


def row(s, *, viewer, now, active_since, resolve, logins, current: str | None) -> dict:
    from apps.accounts.sessions import describe
    from apps.security.login_audit import parse_user_agent

    last_activity = s.last_activity_at or s.last_seen_at
    state = "active" if last_activity >= active_since else "signed_in"
    loc = resolve(s.ip)
    ev = logins.get(str(s.id))
    browser, system, kind = parse_user_agent(s.user_agent or "")
    dev = s.recognized_device
    device_state = "unknown" if dev is None else "unrecognized" if dev.revoked_at else "recognized"
    risk = (ev.risk if ev and ev.risk else "normal")
    reasons = list(ev.risk_reasons or []) if ev else []
    if ev and ev.network and loc["network"] == "public" and ev.network != "public":
        risk = "warning" if RISK_ORDER[risk] < 2 else risk
        reasons.append("The address changed to a public network after sign-in.")
    if device_state == "unrecognized":
        risk, reasons = "high", [*reasons, "The device was marked Unrecognized."]
    trust = TRUST_LABELS.get(loc["network"], "Unknown")
    untrusted = loc["network"] in ("public", "unknown") or device_state in ("unrecognized",) or RISK_ORDER.get(risk, 0) >= 2
    return {
        "id": str(s.id), "current": str(s.id) == current,
        "user": {"id": s.user_id, "name": s.user.display_name, "username": s.user.username},
        "state": state, "state_label": "Active" if state == "active" else "Signed In",
        "ip": str(s.ip) if s.ip else None,  # complete address for people authorised to see the session (Change Set W)
        "trust": trust, "network": loc["network"], "untrusted": untrusted,
        "location": _label_location(loc),
        "device": {"kind": (ev.device if ev and ev.device else kind) or "desktop", "browser": browser or (ev.browser if ev else ""),
                   "os": system or (ev.os if ev else ""), "label": describe(s.user_agent), "state": device_state,
                   "recognized_id": str(dev.id) if dev else None, "recognized_label": dev.label if dev else ""},
        "login_at": s.created_at, "last_activity_at": last_activity, "last_seen_at": s.last_seen_at,
        "age_seconds": int((now - s.created_at).total_seconds()),
        "idle_seconds": max(0, int((now - last_activity).total_seconds())),
        "method": s.method or (ev.method if ev else ""), "risk": risk, "risk_reasons": reasons[:6],
    }


def listing(viewer, *, current: str | None = None, filters: dict | None = None, limit: int = 500) -> dict:
    now = timezone.now()
    active_since = now - threshold()
    sessions = list(visible(viewer).order_by("-last_activity_at", "-last_seen_at")[:limit])
    logins = _login_events([str(s.id) for s in sessions])
    resolve = _Resolver()
    rows = [row(s, viewer=viewer, now=now, active_since=active_since, resolve=resolve, logins=logins, current=current)
            for s in sessions]
    counts = {"active": sum(r["state"] == "active" for r in rows), "signed_in": len(rows),
              "idle": sum(r["state"] == "signed_in" for r in rows), "untrusted": sum(r["untrusted"] for r in rows),
              "high_risk": sum(r["risk"] == "high" for r in rows)}
    f = filters or {}
    if f.get("state") in ("active", "signed_in"):
        rows = [r for r in rows if r["state"] == f["state"]]
    if f.get("user"):
        rows = [r for r in rows if str(r["user"]["id"]) == str(f["user"])]
    if f.get("trust") in ("trusted", "untrusted"):
        rows = [r for r in rows if (not r["untrusted"]) == (f["trust"] == "trusted")]
    if f.get("risk") in ("normal", "low", "warning", "high"):
        rows = [r for r in rows if r["risk"] == f["risk"]]
    if f.get("device") in ("desktop", "mobile", "tablet"):
        rows = [r for r in rows if r["device"]["kind"] == f["device"]]
    if f.get("location"):
        needle = str(f["location"]).lower()
        rows = [r for r in rows if needle in (r["location"]["text"] + " " + r["location"]["zone"]).lower()]
    return {"counts": counts, "sessions": rows, "threshold_minutes": int(config.get("security.session_active_minutes")),
            "generated_at": now}


def summary(viewer, *, current: str | None = None, rows: int = 8) -> dict:
    """The Overview tile: counts plus the most recent sessions (people with the latest activity first)."""
    data = listing(viewer, current=current, limit=200)
    return {"counts": data["counts"], "threshold_minutes": data["threshold_minutes"],
            "sessions": [{k: r[k] for k in ("id", "user", "state", "state_label", "trust", "untrusted", "location", "device",
                                            "last_activity_at", "idle_seconds", "risk", "current")}
                         for r in data["sessions"][:rows]], "link": "/settings/security/sessions"}


def terminate(session, *, actor, request=None) -> None:
    """End one session on the server: it is refused on its next request (sessions.check), whatever its cookie.
    Different from Mark Unrecognized, which ends every session of a device and drops the device's recognition."""
    from apps.notify import events

    from .location import privacy_ip

    session.revoked_at = timezone.now()
    session.save(update_fields=["revoked_at"])
    audit.record("security.session_terminated", request=request, actor=actor, subject_user=session.user,
                 target_type="user_session", target_id=str(session.id), ip=privacy_ip(str(session.ip) if session.ip else None))
    from apps.accounts.sessions import describe

    events.notify(session.user, "security.session_terminated", key=f"session-terminated:{session.id}",
                  title="One of your sessions was ended",
                  summary=f"{actor.display_name} ended your session on {describe(session.user_agent)}. That device must sign in again.",
                  facts=[("Device", describe(session.user_agent)), ("Ended by", actor.display_name)],
                  link="/settings/account?tab=security#sessions")


def notify_high_risk(session_row: dict) -> None:
    """Tell the main administrators once per session when a high-risk session is active (existing policy: alerts are
    for administrators, deduplicated by key)."""
    from apps.accounts.models import User
    from apps.notify import events

    for admin in User.objects.filter(is_main_admin=True, is_active=True):
        events.notify(admin, "security.session_high_risk", key=f"session-risk:{session_row['id']}",
                      title=f"High-risk session: {session_row['user']['name']}",
                      summary="; ".join(session_row["risk_reasons"][:2]) or "A session from an untrusted location is active.",
                      facts=[("Location", session_row["location"]["text"]), ("Trust", session_row["trust"])],
                      link=f"/settings/security/sessions?session={session_row['id']}")


def scan_high_risk() -> int:
    """Scheduler: one notification per high-risk session that is still valid (keys deduplicate repeats)."""
    from apps.accounts.models import User

    admin = User.objects.filter(is_main_admin=True, is_active=True).first()
    if admin is None:
        return 0
    rows = [r for r in listing(admin, limit=500)["sessions"] if r["risk"] == "high"]
    for r in rows:
        notify_high_risk(r)
    return len(rows)
