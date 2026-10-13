"""WhatsApp Personal - EXPERIMENTAL, UNOFFICIAL, SELF-HOSTED notification bridge.

Not the WhatsApp Business Platform, not supported or endorsed by WhatsApp or Meta. Each person links their *own*
WhatsApp account as a linked device (QR code); Personal DM then sends that person their own notifications as a
message to themselves ("Message yourself" chat).

Isolation and scope (enforced here and in bridge/whatsapp/server.mjs):
* the bridge listens on 127.0.0.1 only and needs a shared token (<config>/whatsapp-bridge.token);
* each person has an opaque random session id; the session credentials are stored encrypted per session by the
  bridge and never pass through Django, the database, logs or backups' plain text;
* the bridge API has no recipient parameter: a session can only message its own account. There is no message
  composer, bulk sending, contact access, auto-reply or chat reading;
* a bridge failure never breaks Personal DM or another channel (short timeouts, bounded retries in the outbox).
"""
from __future__ import annotations

import io
import json
import secrets
from pathlib import Path

import requests
from django.conf import settings
from django.utils import timezone

from apps.core import config

TIMEOUT = 8
PROTOCOL = 1


class WhatsAppError(Exception):
    pass


def token() -> str:
    p = Path(settings.CONFIG_DIR) / "whatsapp-bridge.token"
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def compat() -> dict:
    try:
        return json.loads((Path(settings.REPO_DIR) / "bridge" / "whatsapp" / "compat.json").read_text())
    except (OSError, ValueError):
        return {"protocol": PROTOCOL, "tested_versions": []}


def _base() -> str:
    url = (config.get("whatsapp.bridge_url") or "").rstrip("/")
    if not url.startswith(("http://127.0.0.1:", "http://localhost:", "http://[::1]:")):
        raise WhatsAppError("The bridge address must be a loopback address (127.0.0.1).")
    return url


def _call(method: str, path: str, **kw) -> dict:
    try:
        r = requests.request(method, _base() + path, headers={"Authorization": f"Bearer {token()}"}, timeout=TIMEOUT, **kw)
    except requests.RequestException as exc:
        raise WhatsAppError("The WhatsApp bridge is not running.") from exc
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400:
        raise WhatsAppError(data.get("error") or f"Bridge error (HTTP {r.status_code})")
    return data


def bridge_status() -> dict:
    """Version, protocol compatibility and health. No session material."""
    if not config.get("whatsapp.enabled"):
        return {"enabled": False, "state": "disabled", "label": "Disabled"}
    c = compat()
    try:
        h = _call("GET", "/health")
    except WhatsAppError as exc:
        return {"enabled": True, "state": "unavailable", "label": "Bridge not running", "detail": str(exc), "pinned": c.get("pinned")}
    version = h.get("version", "")
    tested = version in c.get("tested_versions", [])
    protocol_ok = h.get("protocol") == c.get("protocol", PROTOCOL)
    state = "healthy" if (tested and protocol_ok and h.get("ok")) else ("degraded" if protocol_ok else "incompatible")
    return {"enabled": True, "state": state, "label": {"healthy": "Running (tested version)", "degraded": "Degraded",
                                                       "incompatible": "Incompatible bridge version"}[state],
            "version": version, "library": h.get("library"), "tested": tested, "protocol_ok": protocol_ok,
            "pinned": c.get("pinned"), "update_available": bool(c.get("pinned") and version != c.get("pinned")),
            "sessions": h.get("sessions", {}), "detail": h.get("detail", "")}


SERVICE = "personaldocs-whatsapp"
HEALTH_KEY = "whatsapp_bridge"


def _systemd_state() -> str:
    """active / inactive / failed / unknown (no systemd here). systemctl is-active needs no privileges."""
    import shutil
    import subprocess

    if not shutil.which("systemctl"):
        return "unknown"
    try:
        out = subprocess.run(["systemctl", "is-active", SERVICE], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out or "unknown"


def service_status() -> dict:
    """Administrator view of the optional bridge, independent of the on/off switch: installed, service, version,
    protocol, compatibility, connectivity and when it was last checked. State only - never session material."""
    import os

    from apps.security.models import HealthState

    prefix = Path(os.environ.get("PD_WHATSAPP_PREFIX", "/opt/personaldocs/whatsapp-bridge"))
    installed = (prefix / "current").exists() if prefix.exists() else None  # None: unknown (not a native install)
    c = compat()
    service = _systemd_state()
    now = timezone.now().isoformat()
    prev = HealthState.get(HEALTH_KEY) or {}
    out = {"enabled": bool(config.get("whatsapp.enabled")), "installed": installed, "service": service, "checked_at": now,
           "pinned": c.get("pinned"), "expected_protocol": c.get("protocol", PROTOCOL), "token_present": bool(token())}
    try:
        h = _call("GET", "/health")
    except WhatsAppError as exc:
        reachable = False
        out.update(reachable=False, detail=str(exc))
    else:
        reachable = True
        version = h.get("version", "")
        out.update(reachable=True, version=version, protocol=h.get("protocol"), library=h.get("library"),
                   tested=version in c.get("tested_versions", []), protocol_ok=h.get("protocol") == c.get("protocol", PROTOCOL),
                   update_available=bool(c.get("pinned") and version and version != c.get("pinned")),
                   sessions=h.get("sessions", {}))
    if not reachable:
        if installed is False:
            state = "not_installed"
        elif service in ("inactive", "failed"):
            state = "stopped"
        else:
            state = "unavailable"
    elif not out.get("protocol_ok"):
        state = "incompatible"
    elif not out.get("tested"):
        state = "degraded"
    else:
        state = "healthy"
    if state == "healthy" and not out["enabled"]:
        state = "ready_disabled"  # installed and running, waiting to be turned on
    out["state"] = state
    out["label"] = {"not_installed": "Not installed", "stopped": "Service stopped", "unavailable": "Service unavailable",
                    "incompatible": "Incompatible bridge version", "degraded": "Degraded (untested version)",
                    "healthy": "Running", "ready_disabled": "Installed and running - turned off"}[state]
    out["last_ok"] = now if reachable and state in ("healthy", "ready_disabled", "degraded") else prev.get("last_ok")
    HealthState.objects.update_or_create(key=HEALTH_KEY, defaults={"data": {k: out.get(k) for k in ("state", "checked_at", "last_ok", "version")}})
    return out


def last_delivery(user, channel: str):
    from .models import OutboxMessage

    m = OutboxMessage.objects.filter(user=user, channel=channel, status=OutboxMessage.SENT).order_by("-sent_at").first()
    return m.sent_at if m else None


def _link(user):
    from .models import WhatsAppLink

    return WhatsAppLink.objects.filter(user=user).first()


LINKS_PER_HOUR = 6  # rate limit for new QR codes per person (the bridge enforces the same)


def start_link(user, *, force: bool = False) -> dict:
    """Start (or continue) linking. A running 5-minute attempt keeps its QR code; ``force`` asks for a new code,
    which the bridge allows only after the attempt expired or definitively failed."""
    from django.core.cache import cache

    from .models import WhatsAppLink

    if not config.get("whatsapp.enabled"):
        raise WhatsAppError("WhatsApp Personal is turned off by the administrator.")
    link = _link(user)
    created = link is None
    if created:
        link = WhatsAppLink.objects.create(user=user, session=secrets.token_hex(16))
    ckey = f"wa-link:{user.pk}"
    now = timezone.now().timestamp()
    recent = [t for t in (cache.get(ckey) or []) if t > now - 3600]
    new_attempt = created or force or link.state != WhatsAppLink.PENDING  # pressing Link again keeps the running attempt
    if new_attempt and len(recent) >= LINKS_PER_HOUR:
        raise WhatsAppError("Too many link attempts in the last hour. Try again later.")
    _call("POST", "/sessions", json={"session": link.session, "force": bool(force)})
    if new_attempt:
        cache.set(ckey, [*recent, now], 3600)
    link.state, link.last_error, link.last_pairing_at, link.verification = WhatsAppLink.PENDING, "", timezone.now(), ""
    link.save(update_fields=["state", "last_error", "last_pairing_at", "verification"])
    from apps.core import audit

    audit.record("whatsapp.link_started", actor=user, outcome="success")  # no QR, session or number
    return status(user)


def qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


# Pairing stages in order (shown live), then the linked states. Labels are the words people see.
STAGES = ["qr_ready", "scanned", "connecting", "authenticating", "saving_session", "sending_verification"]
STAGE_LABELS = {"qr_ready": "QR Ready", "scanned": "Scanned", "connecting": "Connecting", "authenticating": "Authenticating",
                "saving_session": "Saving Session", "sending_verification": "Sending Verification"}
LABELS = {"verified": "Linked & Verified", "verify_pending": "Linked — Verification Pending", "verify_failed": "Linked — Test Failed",
          "disconnected": "Disconnected — reconnecting", "reconnect_required": "Relink Required", "link_expired": "QR code expired",
          "pairing_failed": "Pairing failed", "incompatible": "Compatibility error", "degraded": "Service unavailable",
          "not_linked": "Not linked", "pending": "Linking…"}
FAILURE_HINTS = {401: "WhatsApp rejected the link (logged out on the phone, or the code was used by another device).",
                 403: "WhatsApp refused this account for linked devices.", 408: "The connection timed out.",
                 411: "Multi-device protocol mismatch: the bridge needs a compatible update.", 428: "The connection closed.",
                 500: "The session data was rejected.", 515: "WhatsApp asked for a restart.", "timeout": "The phone did not finish linking in time."}


def status(user) -> dict:
    from .models import WhatsAppLink

    link = _link(user)
    if link is None:
        return {"linked": False, "state": "not_linked", "key": "not_linked", "label": "Not linked", "can_new_qr": True}
    out = {"state": link.state, "number_hint": link.number_hint, "enabled": link.enabled, "error": link.last_error,
           "linked_at": link.linked_at.isoformat() if link.linked_at else None,
           "verified_at": link.verified_at.isoformat() if link.verified_at else None}
    try:
        s = _call("GET", f"/sessions/{link.session}")
    except WhatsAppError as exc:
        st = link.state if link.state == WhatsAppLink.RELINK else WhatsAppLink.DEGRADED
        out.update(state=st, key=st, bridge_error=str(exc), linked=False, label=LABELS.get(st, st), can_new_qr=False)
        return out
    state = s.get("state", "disconnected")
    prev = link.state
    changed = []
    if state != link.state:
        link.state = state
        changed.append("state")
    if state == WhatsAppLink.CONNECTED:
        if not link.linked_at:
            link.linked_at = timezone.now()
            changed.append("linked_at")
        hint_ = (s.get("number_hint") or "")[-4:]
        if hint_ and hint_ != link.number_hint:
            link.number_hint = hint_
            changed.append("number_hint")
        ver = s.get("verification") or "pending"
        if ver != link.verification:
            link.verification = ver
            changed.append("verification")
            if ver == "verified":
                link.verified_at = timezone.now()
                changed.append("verified_at")
        link.last_seen_at = timezone.now()
        changed.append("last_seen_at")
    elif state in ("reconnect_required", "pairing_failed", "link_expired", "not_linked") and link.verification:
        link.verification = ""
        changed.append("verification")
    if state in ("pairing_failed", "reconnect_required", "incompatible"):
        code = s.get("error_code")
        err = FAILURE_HINTS.get(code, f"WhatsApp answered {code}." if code else "")
        if err != link.last_error:
            link.last_error = err[:200]
            changed.append("last_error")
    if changed:
        link.save(update_fields=list(dict.fromkeys(changed)))
    if state == "reconnect_required" and prev != "reconnect_required":
        _tell_relink(link)
    if state == "incompatible":
        alert_incompatible()
    verification = s.get("verification") if state == WhatsAppLink.CONNECTED else None
    key = ({"verified": "verified", "failed": "verify_failed"}.get(verification or "", "verify_pending")
           if state == WhatsAppLink.CONNECTED else state)
    out.update(linked=state == WhatsAppLink.CONNECTED, state=state, key=key, number_hint=link.number_hint,
               stage=s.get("stage"), stages=STAGES, verification=verification, failure_stage=s.get("failure_stage"),
               error=link.last_error, next_retry_in_s=s.get("next_retry_in_s"), link_expires_in_s=s.get("link_expires_in_s"),
               verified_at=link.verified_at.isoformat() if link.verified_at else None)
    if state == WhatsAppLink.PENDING and s.get("stage") == "qr_ready" and s.get("qr"):
        out["qr_svg"] = qr_svg(s["qr"])  # shown only to the person linking, never stored or logged
    out["label"] = STAGE_LABELS.get(s.get("stage") or "", "Linking…") if state == WhatsAppLink.PENDING else LABELS.get(key, state)
    out["can_new_qr"] = state in ("link_expired", "pairing_failed", "reconnect_required", "not_linked", "incompatible")
    return out


def _tell_relink(link) -> None:
    """Tell the person through their other channels (WhatsApp itself cannot deliver now)."""
    from . import events

    events.notify(link.user, "whatsapp.relink_required", key=f"wa-relink:{link.user_id}:{timezone.now():%Y%m%d}",
                  title="Link WhatsApp Personal again", icon="warning", severity="warning",
                  lines=["WhatsApp ended the linked device of Personal DM, so notifications cannot be delivered there.",
                         "Open My account → Notifications → WhatsApp Personal and choose Link again."],
                  link="/settings/account?tab=notifications#whatsapp")


def alert_incompatible() -> None:
    """Tell the main administrators once per day through non-WhatsApp channels (no alert spam)."""
    from apps.accounts.models import User

    from . import events

    for admin in User.objects.filter(is_active=True, is_main_admin=True):
        events.notify(admin, "whatsapp.incompatible", key=f"wa-incompat:{timezone.now():%Y%m%d}", cooldown_group="wa-incompatible",
                      title="WhatsApp Personal bridge needs a compatible update", icon="warning", severity="warning",
                      lines=["WhatsApp delivery is paused; people's fallback channels are used.",
                             "Settings → Connections → WhatsApp Personal → Run Diagnostics, then: sudo personaldocs whatsapp-bridge update"],
                      link="/settings/connections#conn-whatsapp")


def send(user, text: str) -> str:
    link = _link(user)
    if link is None or link.state not in ("connected",):
        raise WhatsAppError("WhatsApp is not connected.")
    data = _call("POST", f"/sessions/{link.session}/send", json={"text": text[:3500]})
    return str(data.get("id", ""))


def send_test(user) -> str:
    """Send Test Notification: a real message to the person's own chat. Success marks the link Verified; a failure
    is recorded but never destroys an otherwise valid session."""
    link = _link(user)
    try:
        ref = send(user, "🧪 Test notification from Personal DM. WhatsApp Personal delivery works (experimental, unofficial).")
    except WhatsAppError:
        if link and link.state == "connected":
            link.verification = "failed"
            link.save(update_fields=["verification"])
        raise
    link.verification, link.verified_at = "verified", timezone.now()
    link.save(update_fields=["verification", "verified_at"])
    return ref


def diagnostics() -> dict:
    """Main-administrator diagnostics from the bridge, with session ids replaced by the person's name. No QR payload,
    credentials, numbers or keys exist in the bridge's answer; this only adds who each session belongs to."""
    from .models import WhatsAppLink

    d = _call("GET", "/diagnostics")
    names = {link.session: link.user.display_name for link in WhatsAppLink.objects.select_related("user")}
    sessions = []
    for s in d.get("sessions", []):
        sid = s.pop("session", "")
        s["person"] = names.get(sid, "Unlinked session")
        sessions.append(s)
    known = {sid[:6]: names[sid] for sid in names}
    events = [{**{k: v for k, v in e.items() if k != "session"}, "person": known.get(e.get("session", ""), "—")} for e in d.get("events", [])]
    d.update(sessions=sessions, events=events)
    c = compat()
    d["tested"] = {"pinned": c.get("pinned"), "library": c.get("library"), "tested_versions": c.get("tested_versions", [])}
    d["compatible"] = d.get("version") in c.get("tested_versions", []) and d.get("protocol") == c.get("protocol", PROTOCOL)
    return d


def restart_bridge() -> None:
    """Ask the bridge to exit cleanly; systemd starts it again (encrypted sessions are kept and resumed)."""
    _call("POST", "/admin/restart")


def unlink(user) -> None:
    link = _link(user)
    if link is None:
        return
    try:
        _call("DELETE", f"/sessions/{link.session}")
    except WhatsAppError:
        pass  # the bridge wipes orphaned sessions on start; the link is removed here regardless
    link.delete()


def reconnect(user) -> dict:
    link = _link(user)
    if link is None:
        raise WhatsAppError("Link WhatsApp first.")
    _call("POST", f"/sessions/{link.session}/reconnect")
    return status(user)


def reconnect_all() -> dict:
    """Normal recovery: try the restored sessions; rejected ones become Reconnect Required."""
    from .models import WhatsAppLink

    try:
        _call("GET", "/health")
    except WhatsAppError:
        return {"unavailable": True}
    connected = relink = 0
    for link in WhatsAppLink.objects.all():
        try:
            s = _call("POST", f"/sessions/{link.session}/reconnect")
            ok = s.get("state") == "connected"
        except WhatsAppError:
            ok = False
        link.state = WhatsAppLink.CONNECTED if ok else WhatsAppLink.RELINK
        link.save(update_fields=["state"])
        connected += ok
        relink += not ok
    return {"connected": connected, "relink": relink}


def require_relink_all(reason: str) -> int:
    """Compromise recovery: restored linked-device sessions are never trusted automatically."""
    from .models import WhatsAppLink

    n = 0
    for link in WhatsAppLink.objects.all():
        try:
            _call("DELETE", f"/sessions/{link.session}")
        except WhatsAppError:
            pass
        link.state, link.last_error, link.session = WhatsAppLink.RELINK, reason[:200], secrets.token_hex(16)
        link.save(update_fields=["state", "last_error", "session"])
        n += 1
    return n


def render(msg) -> str:
    """Plain text with WhatsApp emphasis; same masking as Telegram. Links open the app (sign-in required)."""
    from . import icons, rich, templates

    t = rich.apply_template(msg, "whatsapp", external=True)
    lines = []
    if msg.test:
        lines.append("🧪 *TEST* - sample notification")
    lines.append(f"{icons.emoji(t['icon'])} *{t['title']}*")
    lines.append(f"_{icons.SEVERITY[t['severity']][1]} · {icons.CATEGORY_LABELS.get(msg.category, msg.category)}_")
    if t["summary"]:
        lines += ["", t["summary"]]
    for d, v in rich._details(msg, "telegram"):
        lines.append(f"{d.label}: {v}")
    for m in msg.mandatory:
        lines.append(f"⚠️ {templates.text(m, True)}")
    acts = [a for a in rich._actions(msg, "telegram", t["labels"]) if a.path][:2]
    for a in acts:
        lines.append(f"🔗 {a.label}: {rich._url(a.path)}")
    lines.append(f"⏱️ {templates.local_stamp(msg.when)}")
    return "\n".join(lines)[:3500]
