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


def _link(user):
    from .models import WhatsAppLink

    return WhatsAppLink.objects.filter(user=user).first()


def start_link(user) -> dict:
    from .models import WhatsAppLink

    if not config.get("whatsapp.enabled"):
        raise WhatsAppError("WhatsApp Personal is turned off by the administrator.")
    link = _link(user)
    if link is None:
        link = WhatsAppLink.objects.create(user=user, session=secrets.token_hex(16))
    _call("POST", "/sessions", json={"session": link.session})
    link.state, link.last_error = WhatsAppLink.PENDING, ""
    link.save(update_fields=["state", "last_error"])
    return status(user)


def qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def status(user) -> dict:
    from .models import WhatsAppLink

    link = _link(user)
    if link is None:
        return {"linked": False, "state": "not_linked", "label": "Not linked"}
    out = {"linked": link.state == WhatsAppLink.CONNECTED, "state": link.state, "number_hint": link.number_hint,
           "linked_at": link.linked_at.isoformat() if link.linked_at else None, "enabled": link.enabled, "error": link.last_error}
    try:
        s = _call("GET", f"/sessions/{link.session}")
    except WhatsAppError as exc:
        out.update(state=link.state if link.state == WhatsAppLink.RELINK else WhatsAppLink.DEGRADED, bridge_error=str(exc))
        out["label"] = LABELS.get(out["state"], out["state"])
        return out
    state = s.get("state", "disconnected")
    if link.state == WhatsAppLink.RELINK and state != WhatsAppLink.CONNECTED:
        state = WhatsAppLink.RELINK
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
        link.last_seen_at = timezone.now()
        changed.append("last_seen_at")
    if changed:
        link.save(update_fields=changed)
    out.update(linked=state == WhatsAppLink.CONNECTED, state=state, number_hint=link.number_hint)
    if state == WhatsAppLink.PENDING and s.get("qr"):
        out["qr_svg"] = qr_svg(s["qr"])  # shown only to the person linking, never stored or logged
    out["label"] = LABELS.get(state, state)
    return out


LABELS = {"connected": "Connected", "disconnected": "Disconnected", "degraded": "Degraded", "reconnect_required": "Reconnect Required",
          "pending": "Waiting for QR scan", "not_linked": "Not linked"}


def send(user, text: str) -> str:
    link = _link(user)
    if link is None or link.state not in ("connected",):
        raise WhatsAppError("WhatsApp is not connected.")
    data = _call("POST", f"/sessions/{link.session}/send", json={"text": text[:3500]})
    return str(data.get("id", ""))


def send_test(user) -> str:
    return send(user, "🧪 Test notification from Personal DM. WhatsApp Personal delivery works (experimental, unofficial).")


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
