"""Passkeys / WebAuthn (py_webauthn). Standards-based; no custom cryptography.

Relying party ID = host name of PD_PUBLIC_ORIGIN (e.g. docs.example.com); expected origin = PD_PUBLIC_ORIGIN
exactly (HTTPS). Passkeys therefore only work on the public HTTPS address, not on http://<lan-ip>, and changing
the domain later makes existing passkeys unusable (people then sign in with password + TOTP/recovery code
and register new passkeys). Challenges live in the server-side session for 5 minutes.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone
from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, AuthenticatorTransport, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from apps.core import config

from .models import User, WebAuthnCredential

CHALLENGE_TTL = timedelta(minutes=5)


class PasskeyError(ValueError):
    pass


def rp_id() -> str:
    return urlparse(settings.PUBLIC_ORIGIN).hostname or "localhost"


def expected_origins() -> list[str]:
    origins = [settings.PUBLIC_ORIGIN]
    if settings.DEBUG and "http://localhost:8000" not in origins:
        origins.append("http://localhost:8000")
    return origins


def diagnostics() -> list[tuple[str, bool, str]]:
    origin = settings.PUBLIC_ORIGIN
    host = urlparse(origin).hostname or ""
    return [
        ("public origin uses HTTPS", origin.startswith("https://") or host == "localhost", origin),
        ("relying party ID is a host name", bool(host) and not host.replace(".", "").isdigit(), host or "(none)"),
        ("reverse proxy mode enabled", bool(getattr(settings, "SECURE_PROXY_SSL_HEADER", None)), "PD_BEHIND_PROXY=1 lets Django see https behind NPM/Pangolin"),
    ]


def _transports(values) -> list[AuthenticatorTransport]:
    out = []
    for v in values or []:
        try:
            out.append(AuthenticatorTransport(v))
        except ValueError:
            continue
    return out


def active(user):
    return WebAuthnCredential.objects.filter(user=user, revoked_at__isnull=True)


def _store(session, key: str, challenge: bytes, **extra) -> None:
    session[key] = {"challenge": bytes_to_base64url(challenge), "at": timezone.now().isoformat(), **extra}


def _take(session, key: str) -> dict:
    data = session.pop(key, None)
    if not data or timezone.now() - datetime.fromisoformat(data["at"]) > CHALLENGE_TTL:
        raise PasskeyError("The passkey request expired. Please try again.")
    return data


# ------------------------------------------------------------------ registration

def registration_options(session, user: User) -> dict:
    opts = generate_registration_options(
        rp_id=rp_id(), rp_name=config.get("general.app_name"), user_id=user.pk.bytes, user_name=user.username,
        user_display_name=user.display_name or user.username,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id), transports=_transports(c.transports))
                             for c in active(user)],
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.PREFERRED,
                                                               user_verification=UserVerificationRequirement.PREFERRED),
    )
    _store(session, "webauthn_register", opts.challenge, uid=str(user.pk))
    return json.loads(options_to_json(opts))


def register(session, user: User, credential: dict, name: str) -> WebAuthnCredential:
    data = _take(session, "webauthn_register")
    if data.get("uid") != str(user.pk):
        raise PasskeyError("The passkey request belongs to another account.")
    try:
        verified = verify_registration_response(credential=credential, expected_challenge=base64url_to_bytes(data["challenge"]),
                                                expected_rp_id=rp_id(), expected_origin=expected_origins())
    except InvalidRegistrationResponse as exc:
        raise PasskeyError(f"The passkey could not be verified ({exc}).")
    cred_id = bytes_to_base64url(verified.credential_id)
    if WebAuthnCredential.objects.filter(credential_id=cred_id).exists():
        raise PasskeyError("This passkey is already registered.")
    ext = (credential.get("clientExtensionResults") or {}).get("credProps") or {}
    return WebAuthnCredential.objects.create(
        user=user, credential_id=cred_id, public_key=verified.credential_public_key, sign_count=verified.sign_count,
        transports=[t for t in ((credential.get("response") or {}).get("transports") or []) if isinstance(t, str)][:6],
        aaguid=str(verified.aaguid or "")[:40], device_type=str(getattr(verified.credential_device_type, "value", ""))[:20],
        backed_up=bool(verified.credential_backed_up), discoverable=bool(ext.get("rk", False)),
        name=(name or "Passkey").strip()[:80] or "Passkey")


# ------------------------------------------------------------------ authentication

def authentication_options(session, *, user: User | None, purpose: str) -> dict:
    """purpose: '2fa' (after password), 'passwordless' (discoverable credential) or 'reauth'."""
    allow = None
    if user is not None:
        creds = list(active(user))
        if not creds:
            raise PasskeyError("No passkey is registered for this account.")
        allow = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id), transports=_transports(c.transports)) for c in creds]
    uv = UserVerificationRequirement.REQUIRED if purpose == "passwordless" else UserVerificationRequirement.PREFERRED
    opts = generate_authentication_options(rp_id=rp_id(), allow_credentials=allow, user_verification=uv)
    _store(session, f"webauthn_auth_{purpose}", opts.challenge, uid=str(user.pk) if user else "")
    return json.loads(options_to_json(opts))


def authenticate(session, credential: dict, *, purpose: str, user: User | None = None) -> WebAuthnCredential:
    data = _take(session, f"webauthn_auth_{purpose}")
    cred_id = str(credential.get("id") or credential.get("rawId") or "")
    row = WebAuthnCredential.objects.select_related("user").filter(credential_id=cred_id, revoked_at__isnull=True).first()
    if row is None:
        raise PasskeyError("This passkey is not registered (or was removed).")
    if user is not None and row.user_id != user.pk:
        raise PasskeyError("This passkey belongs to another account.")
    if data.get("uid") and data["uid"] != str(row.user_id):
        raise PasskeyError("This passkey belongs to another account.")
    try:
        verified = verify_authentication_response(
            credential=credential, expected_challenge=base64url_to_bytes(data["challenge"]), expected_rp_id=rp_id(),
            expected_origin=expected_origins(), credential_public_key=bytes(row.public_key),
            credential_current_sign_count=row.sign_count, require_user_verification=(purpose == "passwordless"))
    except InvalidAuthenticationResponse as exc:
        raise PasskeyError(f"The passkey could not be verified ({exc}).")
    row.sign_count = verified.new_sign_count
    row.last_used_at = timezone.now()
    row.backed_up = bool(verified.credential_backed_up)
    row.save(update_fields=["sign_count", "last_used_at", "backed_up"])
    return row


# ------------------------------------------------------------------ policy helpers

def has_second_factor(user: User) -> bool:
    return bool(user.totp_enabled) or active(user).exists()


def requires_2fa(user: User) -> bool:
    policy = config.get("auth.require_2fa")
    return policy == "all" or (policy == "admins" and (user.is_main_admin or user.is_admin))


def methods_for(user: User) -> list[str]:
    out = []
    if user.totp_enabled:
        out.append("totp")
    if active(user).exists():
        out.append("passkey")
    if user.recovery_codes.filter(used_at__isnull=True).exists():
        out.append("recovery")
    return out
