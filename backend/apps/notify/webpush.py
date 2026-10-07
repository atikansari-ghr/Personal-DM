"""Web Push for the installed app / browser (RFC 8030 with VAPID, RFC 8292, and aes128gcm encryption, RFC 8291).

* The VAPID key pair is created on first use and stored encrypted in the database (it is part of backups).
* Encryption and signing use maintained libraries (``http_ece``, ``py_vapid``) — no custom cryptography.
* Subscriptions are only accepted for endpoints of known push services (Apple, Google, Mozilla, Microsoft) over HTTPS,
  so a crafted subscription cannot make the server call internal addresses.
* Payloads are short and contain no document numbers or document text (see ``rich.render_push``).
"""
from __future__ import annotations

import base64
import json
import time
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.utils import timezone

from apps.core import config, crypto

PUSH_HOSTS = ("fcm.googleapis.com", "android.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com")
PUSH_SUFFIXES = (".push.services.mozilla.com", ".notify.windows.com", ".push.apple.com")


class PushError(Exception):
    pass


class Gone(PushError):
    """The subscription expired or was revoked by the browser (HTTP 404/410): delete it."""


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def allowed_endpoint(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and not u.username and (host in PUSH_HOSTS or host.endswith(PUSH_SUFFIXES))


def _keys():
    from py_vapid import Vapid02

    from .models import SchedulerRun

    row, _ = SchedulerRun.objects.get_or_create(name="webpush_vapid")
    pem = row.state.get("private")
    if not pem:
        v = Vapid02()
        v.generate_keys()
        pem_bytes = v.private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption())
        row.state = {"private": crypto.encrypt(pem_bytes.decode()), "created_at": timezone.now().isoformat()}
        row.save(update_fields=["state"])
        return v
    return Vapid02.from_pem(crypto.decrypt(pem).encode())


def public_key() -> str:
    v = _keys()
    raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64u(raw)


def _subject() -> str:
    addr = config.get("smtp.from_address")
    if addr and "@" in addr:
        return f"mailto:{addr.split('<')[-1].strip('> ')}"
    return settings.PUBLIC_ORIGIN if settings.PUBLIC_ORIGIN.startswith("https://") else "mailto:admin@localhost"


def send(sub, payload: dict, *, urgency: str = "normal", ttl: int = 86400) -> str:
    """Encrypt and post one message to one subscription. Returns the push service's message reference."""
    import http_ece

    if not allowed_endpoint(sub.endpoint):
        raise PushError("Push endpoint is not a known push service.")
    body = json.dumps(payload, ensure_ascii=False).encode()
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    try:
        data = http_ece.encrypt(body, private_key=ephemeral, dh=b64u_decode(sub.p256dh), auth_secret=b64u_decode(sub.auth),
                                version="aes128gcm")
    except Exception as exc:  # noqa: BLE001 - malformed browser keys
        raise Gone(f"Invalid subscription keys ({exc.__class__.__name__}).") from exc
    origin = "{0.scheme}://{0.netloc}".format(urlparse(sub.endpoint))
    headers = _keys().sign({"sub": _subject(), "aud": origin, "exp": int(time.time()) + 12 * 3600})
    headers.update({"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": str(ttl),
                    "Urgency": urgency if urgency in ("very-low", "low", "normal", "high") else "normal"})
    try:
        resp = requests.post(sub.endpoint, data=data, headers=headers, timeout=15, allow_redirects=False)
    except requests.RequestException as exc:
        raise PushError(f"Push service not reachable ({exc.__class__.__name__}).") from exc
    if resp.status_code in (404, 410):
        raise Gone("The browser removed this push subscription.")
    if resp.status_code >= 400:
        raise PushError(f"Push service answered HTTP {resp.status_code}.")
    return resp.headers.get("Location", "")[-120:]


def deliver(user, payload: dict, severity: str = "info") -> str:
    """Send to every device of the person; expired subscriptions are removed. Raises when none accepted it."""
    from .models import PushSubscription

    subs = list(PushSubscription.objects.filter(user=user))
    if not subs:
        raise PushError("No device is registered for push notifications.")
    ok, errors, ref = 0, [], ""
    for sub in subs:
        try:
            ref = send(sub, payload, urgency="high" if severity == "critical" else "normal") or ref
            ok += 1
            PushSubscription.objects.filter(pk=sub.pk).update(last_used_at=timezone.now(), last_error="")
        except Gone:
            sub.delete()
        except PushError as exc:
            errors.append(str(exc))
            PushSubscription.objects.filter(pk=sub.pk).update(last_error=str(exc)[:300])
    if not ok:
        raise PushError("; ".join(errors) or "No device accepted the notification.")
    return ref or f"{ok} device(s)"
