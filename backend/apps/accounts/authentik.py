"""Optional sign-in with authentik (standard OpenID Connect authorization-code flow with PKCE, state and nonce).

* Personal Documents stays the authority for documents and folders: authentik only proves who someone is.
* Local sign-in is always available; authentik being down never locks anyone out.
* Accounts are linked only by the signed-in person (Profile → Security → Link authentik account) — never because an
  email address matches. With provisioning set to *automatic*, an unknown authentik user gets a new **member**
  account; the main administrator is never created or assigned automatically.
* Optional group-to-role mapping can set the Member/Administrator role. Groups never grant document or folder access.
* Secrets (client secret, tokens) are never logged; only issuer/subject/username are stored on the link.
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from urllib.parse import urlencode, urlparse

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
from apps.security import login_audit

from . import passkeys as PK
from . import services as S
from .auth import IsActiveAuthenticated, IsMainAdmin
from .models import ExternalIdentity, User
from .views import _complete_login, recently_verified, user_json

PROVIDER = "authentik"
_discovery_cache: dict = {}
_jwk_clients: dict = {}


class OIDCError(Exception):
    pass


def callback_url() -> str:
    return f"{settings.PUBLIC_ORIGIN}/api/auth/authentik/callback"


def _issuer() -> str:
    return (config.get("authentik.issuer") or "").strip()


def configured() -> bool:
    return bool(_issuer() and config.get("authentik.client_id") and config.is_set("authentik.client_secret"))


def enabled() -> bool:
    return bool(config.get("authentik.enabled")) and configured()


def _allowed_url(url: str) -> bool:
    """HTTPS everywhere; plain HTTP only for loopback (development and tests)."""
    u = urlparse(url or "")
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1"))


def _norm(url: str) -> str:
    return (url or "").rstrip("/")


def discovery(force: bool = False) -> dict:
    issuer = _issuer()
    if not issuer or not _allowed_url(issuer):
        raise OIDCError("The issuer URL must use HTTPS.")
    cached = _discovery_cache.get(issuer)
    if cached and not force and time.time() - cached[0] < 3600:
        return cached[1]
    url = _norm(issuer) + "/.well-known/openid-configuration"
    try:
        resp = requests.get(url, timeout=10)
    except requests.RequestException as exc:
        raise OIDCError(f"authentik is not reachable ({exc.__class__.__name__}).") from exc
    if resp.status_code != 200:
        raise OIDCError(f"The discovery document answered HTTP {resp.status_code}.")
    try:
        meta = resp.json()
    except ValueError as exc:
        raise OIDCError("The discovery document is not valid JSON.") from exc
    if _norm(meta.get("issuer")) != _norm(issuer):
        raise OIDCError("The discovery document belongs to a different issuer. Copy the issuer URL from authentik exactly.")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not _allowed_url(meta.get(key, "")):
            raise OIDCError(f"The provider's {key.replace('_', ' ')} is missing or not HTTPS.")
    if "S256" not in (meta.get("code_challenge_methods_supported") or ["S256"]):
        raise OIDCError("The provider does not support PKCE (S256).")
    _discovery_cache[issuer] = (time.time(), meta)
    return meta


def _jwk_client(uri: str):
    if uri not in _jwk_clients:
        _jwk_clients[uri] = jwt.PyJWKClient(uri, cache_keys=True, lifespan=3600)
    return _jwk_clients[uri]


def verify_id_token(id_token: str, *, nonce: str, meta: dict) -> dict:
    client_id = config.get("authentik.client_id")
    try:
        key = _jwk_client(meta["jwks_uri"]).get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(id_token, key, algorithms=["RS256", "ES256", "RS384", "RS512", "ES384"], audience=client_id,
                            issuer=meta["issuer"], options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=60)
    except (jwt.PyJWTError, KeyError) as exc:
        raise OIDCError(f"id_token rejected: {exc.__class__.__name__}") from exc
    if not nonce or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OIDCError("nonce mismatch")
    if claims.get("azp") and claims["azp"] != client_id:
        raise OIDCError("authorized party mismatch")
    return claims


def exchange_code(code: str, verifier: str, meta: dict) -> dict:
    try:
        resp = requests.post(meta["token_endpoint"], data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": callback_url(), "code_verifier": verifier,
        }, auth=(config.get("authentik.client_id"), config.get("authentik.client_secret")), timeout=15)
    except requests.RequestException as exc:
        raise OIDCError(f"token request failed ({exc.__class__.__name__})") from exc
    if resp.status_code != 200:
        try:
            err = resp.json().get("error", "token_error")
        except ValueError:
            err = "token_error"
        raise OIDCError(f"token exchange failed: {str(err)[:60]}")
    return resp.json()


def _redirect(path: str, **params) -> HttpResponseRedirect:
    return HttpResponseRedirect(f"{path}{'?' + urlencode(params) if params else ''}")


def _scopes() -> str:
    scopes = [s for s in re.split(r"[\s,]+", config.get("authentik.scopes") or "") if re.fullmatch(r"[A-Za-z0-9:._-]{1,60}", s)]
    return " ".join(dict.fromkeys(["openid", *scopes]))


@api_view(["GET"])
@permission_classes([AllowAny])
def start(request):
    mode = request.query_params.get("mode", "login")
    mode = mode if mode in ("login", "link") else "login"
    if not enabled():
        return _redirect("/login", error="authentik_disabled")
    if mode == "link":
        if not (request.user.is_authenticated and request.user.is_active):
            return _redirect("/login", error="sign_in_first")
        if not recently_verified(request):
            return _redirect("/settings/account", tab="security", error="reauth_required")
    try:
        meta = discovery()
    except OIDCError:
        audit.record("auth.authentik", request=request, outcome="failure", reason="discovery_failed")
        return _redirect("/login", error="authentik_unavailable")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    request.session["authentik_oidc"] = {"state": state, "nonce": nonce, "verifier": verifier, "mode": mode,
                                         "uid": str(request.user.pk) if mode == "link" else None, "at": timezone.now().isoformat()}
    params = {"client_id": config.get("authentik.client_id"), "redirect_uri": callback_url(), "response_type": "code",
              "scope": _scopes(), "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
    return HttpResponseRedirect(f"{meta['authorization_endpoint']}?{urlencode(params)}")


def _claim(claims: dict, key_setting: str, default: str = "") -> str:
    return str(claims.get(config.get(key_setting) or "", default) or default)


def _groups(claims: dict) -> list[str]:
    g = claims.get(config.get("authentik.groups_claim") or "groups") or []
    return [str(x)[:120] for x in g if isinstance(x, (str, int))][:100] if isinstance(g, list) else []


def apply_group_mapping(user: User, groups: list[str], request=None) -> str | None:
    """Set the Member/Administrator role from mapped groups. Never touches the main administrator flag."""
    if not config.get("authentik.group_mapping_enabled") or user.is_main_admin:
        return None
    mapping = config.get("authentik.group_mapping") or {}
    roles = {mapping[g] for g in groups if g in mapping}
    if not roles:
        return None  # no mapped group: keep the role the administrator set
    want_admin = "administrator" in roles
    if user.is_admin != want_admin:
        user.is_admin = want_admin
        user.save(update_fields=["is_admin"])
        audit.record("family.role_change", request=request, actor=None, target=user, subject_user=user,
                     role="administrator" if want_admin else "member", source="authentik_group_mapping")
    return "administrator" if want_admin else "member"


def _provision(claims: dict, request=None) -> User:
    base = re.sub(r"[^a-z0-9._-]", "", _claim(claims, "authentik.username_claim").lower())[:40] or "user"
    username, n = base, 1
    while User.objects.filter(username=username).exists():
        n += 1
        username = f"{base}{n}"
    display = _claim(claims, "authentik.name_claim")[:80] or username
    with transaction.atomic():
        u = User(username=username, display_name=display, email=_claim(claims, "authentik.email_claim")[:254],
                 role_label="", is_main_admin=False, must_change_password=False)
        u.set_unusable_password()  # signs in through authentik; the administrator can set a local password later
        u.save()
        S.create_personal_root(actor=None, user=u, library_root=S.library_root(None))
    audit.record("family.member_add", request=request, actor=None, target=u, source="authentik_provisioning")
    return u


def handle_callback(request, *, state: str, code: str, error: str = "") -> tuple[str, dict]:
    flow = request.session.pop("authentik_oidc", None)
    if error:
        audit.record("auth.authentik", request=request, outcome="failure", reason="provider_error")
        login_audit.record(request, result="failure", method=PROVIDER, reason="provider_error")
        return ("/login", {"error": "authentik_denied"})
    if not flow or not state or not secrets.compare_digest(flow.get("state", ""), state):
        audit.record("auth.authentik", request=request, outcome="failure", reason="state_mismatch")
        login_audit.record(request, result="failure", method=PROVIDER, reason="state_mismatch")
        return ("/login", {"error": "authentik_state"})
    if not enabled():
        return ("/login", {"error": "authentik_disabled"})
    try:
        meta = discovery()
        tokens = exchange_code(code, flow["verifier"], meta)
        claims = verify_id_token(tokens.get("id_token", ""), nonce=flow["nonce"], meta=meta)
    except OIDCError as exc:
        audit.record("auth.authentik", request=request, outcome="failure", reason=str(exc)[:120])
        login_audit.record(request, result="failure", method=PROVIDER, reason="token_invalid")
        return ("/login", {"error": "authentik_invalid"})
    issuer, subject = _norm(meta["issuer"]), str(claims["sub"])
    groups = _groups(claims)
    if flow["mode"] == "link":
        user = User.objects.filter(pk=flow.get("uid"), is_active=True).first()
        if user is None or not request.user.is_authenticated or str(request.user.pk) != flow.get("uid"):
            return ("/login", {"error": "sign_in_first"})
        existing = ExternalIdentity.objects.filter(issuer=issuer, subject=subject).first()
        if existing and existing.user_id != user.pk:
            audit.record("auth.authentik_link", request=request, outcome="denied", reason="identity_linked_elsewhere")
            return ("/settings/account", {"tab": "security", "error": "authentik_already_linked"})
        try:
            with transaction.atomic():
                ExternalIdentity.objects.filter(provider=PROVIDER, user=user).exclude(issuer=issuer, subject=subject).delete()
                ExternalIdentity.objects.update_or_create(provider=PROVIDER, user=user, defaults={
                    "issuer": issuer, "subject": subject, "email": _claim(claims, "authentik.email_claim")[:254],
                    "username": _claim(claims, "authentik.username_claim")[:150], "groups": groups})
        except IntegrityError:
            return ("/settings/account", {"tab": "security", "error": "authentik_already_linked"})
        audit.record("auth.authentik_link", request=request, actor=user, subject_user=user)
        return ("/settings/account", {"tab": "security", "linked": "authentik"})
    ident = ExternalIdentity.objects.select_related("user").filter(issuer=issuer, subject=subject).first()
    if ident is None:
        if config.get("authentik.provisioning") != "auto":
            audit.record("auth.authentik", request=request, outcome="failure", reason="unlinked_identity")
            login_audit.record(request, result="failure", method=PROVIDER, reason="unlinked_identity")
            return ("/login", {"error": "authentik_unlinked"})
        user = _provision(claims, request)
        ident = ExternalIdentity.objects.create(provider=PROVIDER, user=user, issuer=issuer, subject=subject, provisioned=True,
                                                email=_claim(claims, "authentik.email_claim")[:254],
                                                username=_claim(claims, "authentik.username_claim")[:150], groups=groups)
    user = ident.user
    if not user.is_active:
        audit.record("auth.authentik", request=request, outcome="denied", actor=user, reason="disabled_user")
        login_audit.record(request, result="denied", user=user, method=PROVIDER, reason="disabled_account")
        return ("/login", {"error": "account_disabled"})
    ExternalIdentity.objects.filter(pk=ident.pk).update(last_login_at=timezone.now(), groups=groups)
    apply_group_mapping(user, groups, request)
    if PK.has_second_factor(user):
        # Same second step as a password sign-in: authenticator app, passkey or recovery code.
        request.session["pending_2fa"] = {"uid": str(user.pk), "at": timezone.now().isoformat(), "remember": True,
                                          "method": PROVIDER, "methods": PK.methods_for(user)}
        return ("/login", {"step": "totp"})
    _complete_login(request, user, PROVIDER)
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
    ident = ExternalIdentity.objects.filter(provider=PROVIDER, user=request.user).first()
    if request.method == "DELETE":
        if not recently_verified(request):
            return Response({"error": "Please confirm your password first.", "code": "reauth_required"}, status=403)
        if ident:
            ident.delete()
            audit.record("auth.authentik_unlink", request=request, subject_user=request.user)
        return Response({"linked": False})
    return Response({"enabled": enabled(), "label": config.get("authentik.button_label"), "linked": bool(ident),
                     "username": ident.username if ident else None, "email": ident.email if ident else None,
                     "linked_at": ident.linked_at if ident else None, "last_login_at": ident.last_login_at if ident else None,
                     "has_password": request.user.has_usable_password()})


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def links(request):
    rows = ExternalIdentity.objects.filter(provider=PROVIDER).select_related("user").order_by("user__display_name")
    return Response({"links": [{"id": i.id, "user": user_json(i.user), "username": i.username, "email": i.email,
                                "groups": i.groups, "provisioned": i.provisioned, "linked_at": i.linked_at,
                                "last_login_at": i.last_login_at} for i in rows]})


@api_view(["DELETE"])
@permission_classes([IsMainAdmin])
def link_detail(request, pk):
    """Revoke a link. The local account and its documents are kept."""
    ident = ExternalIdentity.objects.filter(pk=pk, provider=PROVIDER).select_related("user").first()
    if ident is None:
        return Response({"error": "Unknown link."}, status=404)
    user = ident.user
    ident.delete()
    user.session_epoch += 1  # sessions opened through authentik end; local sign-in still works
    user.save(update_fields=["session_epoch"])
    audit.record("auth.authentik_unlink", request=request, target=user, subject_user=user, by="main_admin")
    return Response(status=204)


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def test_connection(request):
    checks = [{"name": "Public origin uses HTTPS", "ok": settings.PUBLIC_ORIGIN.startswith("https://"), "detail": settings.PUBLIC_ORIGIN},
              {"name": "Issuer URL entered", "ok": bool(_issuer()), "detail": _issuer()},
              {"name": "Client ID entered", "ok": bool(config.get("authentik.client_id"))},
              {"name": "Client secret stored", "ok": config.is_set("authentik.client_secret")}]
    meta = None
    try:
        meta = discovery(force=True)
        checks.append({"name": "Discovery document valid and issuer matches", "ok": True, "detail": meta["issuer"]})
    except OIDCError as exc:
        checks.append({"name": "Discovery document valid and issuer matches", "ok": False, "detail": str(exc)})
    if meta:
        try:
            ok = requests.get(meta["jwks_uri"], timeout=8).status_code == 200
        except requests.RequestException:
            ok = False
        checks.append({"name": "Signing keys (JWKS) reachable from the server", "ok": ok})
        checks.append({"name": "PKCE (S256) supported", "ok": "S256" in (meta.get("code_challenge_methods_supported") or ["S256"])})
    audit.record("auth.authentik_test", request=request, outcome="success" if all(c["ok"] for c in checks[1:]) else "failure")
    return Response({"callback_url": callback_url(), "checks": checks,
                     "note": "Add the callback URL as a Redirect URI of the authentik provider, then complete a test sign-in."})
