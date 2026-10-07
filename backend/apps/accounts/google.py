"""Optional Google sign-in for existing accounts (OIDC authorization-code flow with PKCE).

* Never creates accounts; never links by email; binds to (issuer, subject).
* Linking requires a recent local verification of the signed-in account.
* App TOTP is still required after Google sign-in when enabled on the account.
* Requests only `openid email profile` — no Gmail/Drive access.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import jwt
import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core import audit, config

from .auth import IsActiveAuthenticated, IsMainAdmin
from .models import GoogleIdentity, User
from apps.security import login_audit

from .views import _complete_login, recently_verified

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SCOPES = "openid email profile"

_jwk_client = None


class GoogleError(Exception):
    pass


def callback_url() -> str:
    return f"{settings.PUBLIC_ORIGIN}/api/auth/google/callback"


def configured() -> bool:
    return bool(config.get("google.client_id")) and config.is_set("google.client_secret")


def enabled() -> bool:
    return bool(config.get("google.enabled")) and configured()


def jwk_client():
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwk_client


def verify_id_token(id_token: str, *, nonce: str, client_id: str) -> dict:
    try:
        key = jwk_client().get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=client_id, issuer=list(ISSUERS),
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=60)
    except jwt.PyJWTError as exc:
        raise GoogleError(f"id_token rejected: {exc.__class__.__name__}") from exc
    if not nonce or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleError("nonce mismatch")
    if claims.get("azp") and claims["azp"] != client_id:
        raise GoogleError("authorized party mismatch")
    return claims


def exchange_code(code: str, verifier: str) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "code": code,
        "client_id": config.get("google.client_id"),
        "client_secret": config.get("google.client_secret"),
        "redirect_uri": callback_url(),
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }, timeout=15)
    if resp.status_code != 200:
        try:
            err = resp.json().get("error", "token_error")
        except ValueError:
            err = "token_error"
        raise GoogleError(f"token exchange failed: {err}")
    return resp.json()


def _redirect(path: str, **params) -> HttpResponseRedirect:
    q = f"?{urlencode(params)}" if params else ""
    return HttpResponseRedirect(f"{path}{q}")


@api_view(["GET"])
@permission_classes([AllowAny])
def start(request):
    mode = request.query_params.get("mode", "login")
    if mode not in ("login", "link"):
        mode = "login"
    if not enabled():
        return _redirect("/login", error="google_disabled")
    if mode == "link":
        if not (request.user.is_authenticated and request.user.is_active):
            return _redirect("/login", error="sign_in_first")
        if not recently_verified(request):
            return _redirect("/settings/account", tab="linked", error="reauth_required")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    request.session["google_oauth"] = {"state": state, "nonce": nonce, "verifier": verifier, "mode": mode,
                                       "uid": str(request.user.pk) if mode == "link" else None,
                                       "at": timezone.now().isoformat()}
    params = {"client_id": config.get("google.client_id"), "redirect_uri": callback_url(), "response_type": "code",
              "scope": SCOPES, "state": state, "nonce": nonce, "code_challenge": challenge,
              "code_challenge_method": "S256", "prompt": "select_account"}
    return HttpResponseRedirect(f"{AUTH_URL}?{urlencode(params)}")


def handle_callback(request, *, state: str, code: str, error: str = "") -> tuple[str, dict]:
    """Returns (redirect_path, params). Split out for tests."""
    flow = request.session.pop("google_oauth", None)
    if error:
        audit.record("auth.google", request=request, outcome="failure", reason="consent_denied" if error == "access_denied" else "provider_error")
        login_audit.record(request, result="failure", method="google", reason="provider_error")
        return ("/login", {"error": "google_denied"})
    if not flow or not state or not secrets.compare_digest(flow.get("state", ""), state):
        audit.record("auth.google", request=request, outcome="failure", reason="state_mismatch")
        login_audit.record(request, result="failure", method="google", reason="state_mismatch")
        return ("/login", {"error": "google_state"})
    if not enabled():
        return ("/login", {"error": "google_disabled"})
    try:
        tokens = exchange_code(code, flow["verifier"])
        claims = verify_id_token(tokens.get("id_token", ""), nonce=flow["nonce"], client_id=config.get("google.client_id"))
    except GoogleError as exc:
        audit.record("auth.google", request=request, outcome="failure", reason=str(exc)[:120])
        login_audit.record(request, result="failure", method="google", reason="token_invalid")
        return ("/login", {"error": "google_invalid"})
    issuer, subject = "https://accounts.google.com", str(claims["sub"])
    if flow["mode"] == "link":
        user = User.objects.filter(pk=flow.get("uid"), is_active=True).first()
        if user is None or not request.user.is_authenticated or str(request.user.pk) != flow.get("uid"):
            return ("/login", {"error": "sign_in_first"})
        existing = GoogleIdentity.objects.filter(issuer=issuer, subject=subject).first()
        if existing and existing.user_id != user.pk:
            audit.record("auth.google_link", request=request, outcome="denied", reason="identity_linked_elsewhere")
            return ("/settings/account", {"tab": "linked", "error": "google_already_linked"})
        try:
            with transaction.atomic():
                GoogleIdentity.objects.filter(user=user).exclude(issuer=issuer, subject=subject).delete()
                GoogleIdentity.objects.update_or_create(user=user, defaults={"issuer": issuer, "subject": subject,
                                                                             "email": str(claims.get("email", ""))[:254]})
        except IntegrityError:
            return ("/settings/account", {"tab": "linked", "error": "google_already_linked"})
        audit.record("auth.google_link", request=request, actor=user, subject_user=user)
        from apps.notify.events import google_link_changed

        google_link_changed(user, linked=True)
        return ("/settings/account", {"tab": "linked", "linked": "1"})
    ident = GoogleIdentity.objects.select_related("user").filter(issuer=issuer, subject=subject).first()
    if ident is None:
        audit.record("auth.google", request=request, outcome="failure", reason="unlinked_identity")
        login_audit.record(request, result="failure", method="google", reason="unlinked_identity")
        return ("/login", {"error": "google_unlinked"})
    user = ident.user
    if not user.is_active:
        audit.record("auth.google", request=request, outcome="denied", actor=user, reason="disabled_user")
        login_audit.record(request, result="denied", user=user, method="google", reason="disabled_account")
        return ("/login", {"error": "account_disabled"})
    ident.last_login_at = timezone.now()
    ident.save(update_fields=["last_login_at"])
    if user.totp_enabled:
        request.session["pending_2fa"] = {"uid": str(user.pk), "at": timezone.now().isoformat(), "remember": True, "method": "google"}
        return ("/login", {"step": "totp"})
    _complete_login(request, user, "google")
    return ("/", {})


@api_view(["GET"])
@permission_classes([AllowAny])
def callback(request):
    path, params = handle_callback(request, state=request.query_params.get("state", ""), code=request.query_params.get("code", ""),
                                   error=request.query_params.get("error", ""))
    return _redirect(path, **params)


@api_view(["GET", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def my_link(request):
    ident = GoogleIdentity.objects.filter(user=request.user).first()
    if request.method == "DELETE":
        if not recently_verified(request):
            return Response({"error": "Please confirm your password first.", "code": "reauth_required"}, status=403)
        if not request.user.has_usable_password():
            return Response({"error": "Set a local password before disconnecting Google."}, status=400)
        if ident:
            ident.delete()
            audit.record("auth.google_unlink", request=request)
            from apps.notify.events import google_link_changed

            google_link_changed(request.user, linked=False)
        return Response({"linked": False})
    return Response({"enabled": enabled(), "linked": bool(ident), "email": ident.email if ident else None,
                     "linked_at": ident.linked_at if ident else None})


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def diagnostics(request):
    checks = []
    checks.append({"name": "Public origin uses HTTPS", "ok": settings.PUBLIC_ORIGIN.startswith("https://"),
                   "detail": settings.PUBLIC_ORIGIN})
    checks.append({"name": "Client ID entered", "ok": bool(config.get("google.client_id"))})
    checks.append({"name": "Client secret stored", "ok": config.is_set("google.client_secret")})
    checks.append({"name": "Client ID format", "ok": str(config.get("google.client_id")).endswith(".apps.googleusercontent.com")})
    reach = False
    try:
        reach = requests.get(JWKS_URL, timeout=8).status_code == 200
    except requests.RequestException:
        reach = False
    checks.append({"name": "Google signing keys reachable from server", "ok": reach})
    return Response({"callback_url": callback_url(), "enabled": bool(config.get("google.enabled")), "checks": checks,
                     "note": "These checks cannot confirm that the callback URL is registered in Google Cloud Console; complete a test sign-in to verify."})
