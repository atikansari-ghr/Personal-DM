"""Authentication, setup, profile and family administration API."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core import audit, config, crypto, ratelimit, registry
from apps.security import login_audit

from . import passkeys as PK
from . import photos
from . import services as S
from .auth import IsActiveAuthenticated, IsMainAdmin
from .models import (DELEGATION_SCOPES, Delegation, FamilyGroup, GroupMembership, PasswordResetToken, SetupState, User,
                     WebAuthnCredential)


def reauth_window() -> timedelta:
    return timedelta(minutes=int(config.get("auth.recent_auth_minutes")))


def user_json(u: User, *, full: bool = False) -> dict:
    data = {
        "id": str(u.pk),
        "display_name": u.display_name,
        "role_label": u.role_label,
        "initials": u.initials,
        "avatar_color": u.avatar_color,
        "photo_version": photos.version(u),
        "is_main_admin": u.is_main_admin,
        "is_active": u.is_active,
        "is_head": u.headed_groups.exists(),
    }
    if full:
        data.update({
            "username": u.username,
            "full_name": u.full_name,
            "email": u.email,
            "must_change_password": u.must_change_password,
            "totp_enabled": u.totp_enabled,
            "passkey_count": PK.active(u).count(),
            "passwordless_enabled": u.passwordless_enabled,
            "two_factor_setup_required": PK.requires_2fa(u) and not PK.has_second_factor(u),
            "last_login": u.last_login,
            "reminder_group": str(u.reminder_group_id) if u.reminder_group_id else None,
            "groups": [str(g) for g in u.memberships.values_list("group_id", flat=True)],
            "google_linked": hasattr(u, "google_identity"),
        })
    return data


def _fail(msg: str, status: int = 400, **extra):
    return Response({"error": msg, **extra}, status=status)


def _complete_login(request, user: User, method: str, remember: bool = True):
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.cycle_key()
    request.session["epoch"] = user.session_epoch
    request.session["reauth_at"] = timezone.now().isoformat()
    request.session.set_expiry(int(config.get("auth.session_days")) * 86400 if remember else 0)
    request.session.pop("pending_2fa", None)
    from . import sessions

    sessions.start(request, user, method)
    audit.record("auth.login", request=request, actor=user, method=method, subject_user=user)
    login_audit.record(request, result="success", user=user, method=method)


def recently_verified(request) -> bool:
    at = request.session.get("reauth_at")
    if not at:
        return False
    try:
        from datetime import datetime

        return timezone.now() - datetime.fromisoformat(at) < reauth_window()
    except ValueError:
        return False


# ------------------------------------------------------------------ session / me

@api_view(["GET"])
@permission_classes([AllowAny])
def session_state(request):
    get_token(request)  # ensures the CSRF cookie is set for the SPA
    state = SetupState.get()
    u = request.user
    data = {
        "setup_complete": bool(state.completed_at),
        "app_name": config.get("general.app_name"),
        "version": settings.APP_VERSION,
        "google_enabled": bool(config.get("google.enabled")),
        "pending_2fa": bool(request.session.get("pending_2fa")),
        "pending_methods": (request.session.get("pending_2fa") or {}).get("methods", []),
        "passkeys_enabled": bool(config.get("auth.allow_passkeys")),
        "passwordless_enabled": bool(config.get("auth.allow_passkeys") and config.get("auth.allow_passwordless")),
        "totp_allowed": bool(config.get("auth.allow_totp")),
        "user": None,
    }
    if u.is_authenticated and u.is_active:
        data["user"] = user_json(u, full=True)
        data["preferences"] = {
            "theme": config.get_user(u, "me.theme"),
            "layout": config.get_user(u, "me.layout"),
            "dashboard_widgets": registry.normalize_widgets(config.get_user(u, "me.dashboard_widgets")),
            "doc_view": config.get_user(u, "me.doc_view"),
            "doc_sort": config.get_user(u, "me.doc_sort"),
        }
        data["date_format"] = config.get("general.date_format")
        data["timezone"] = config.get("general.timezone")
        data["delegations"] = [{"group": d.group.name, "group_id": str(d.group_id), "scopes": d.scopes}
                               for d in Delegation.objects.filter(delegate=u).select_related("group")]
    return Response(data)


# ------------------------------------------------------------------ login / logout / 2FA

@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    username = (request.data.get("username") or "").strip().lower()[:150]
    password = request.data.get("password") or ""
    remember = bool(request.data.get("remember", True))
    ip = audit.client_ip(request) or "unknown"
    limit = int(config.get("auth.login_rate_limit"))
    buckets = [f"login:user:{username}", f"login:ip:{ip}"]
    if any(ratelimit.too_many(b, limit if "user" in b else limit * 3, 900) for b in buckets):
        audit.record("auth.login", request=request, outcome="denied", actor_label=username, reason="rate_limited")
        login_audit.record(request, result="denied", username=username, method="password", reason="rate_limited")
        return _fail("Too many attempts. Please wait a few minutes and try again.", 429)
    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        for b in buckets:
            ratelimit.hit(b)
        audit.record("auth.login", request=request, outcome="failure", actor_label=username)
        login_audit.record(request, result="failure", username=username, method="password",
                           reason="disabled_account" if user is not None else "bad_credentials")
        return _fail("Incorrect username or password.", 400)
    ratelimit.clear(buckets[0])
    if PK.has_second_factor(user):
        methods = PK.methods_for(user)
        request.session["pending_2fa"] = {"uid": str(user.pk), "at": timezone.now().isoformat(), "remember": remember,
                                          "method": "password", "methods": methods}
        return Response({"status": "totp_required" if user.totp_enabled else "second_factor_required", "methods": methods})
    _complete_login(request, user, "password", remember)
    return Response({"status": "ok", "must_change_password": user.must_change_password})


@api_view(["POST"])
@permission_classes([AllowAny])
def totp_verify(request):
    pending = request.session.get("pending_2fa")
    if not pending:
        return _fail("Sign in with your password first.", 400)
    from datetime import datetime

    if timezone.now() - datetime.fromisoformat(pending["at"]) > timedelta(minutes=5):
        request.session.pop("pending_2fa", None)
        return _fail("The sign-in attempt expired. Please start again.", 400)
    user = User.objects.filter(pk=pending["uid"], is_active=True).first()
    bucket = f"totp:{pending['uid']}"
    if user is None or ratelimit.too_many(bucket, 6, 900):
        login_audit.record(request, result="denied", user=user, method=f"{pending.get('method', 'password')}+totp", reason="rate_limited")
        return _fail("Too many attempts. Please wait a few minutes and try again.", 429)
    method = S.verify_second_factor(user, request.data.get("code", ""), request.data.get("recovery_code", ""))
    if not method:
        ratelimit.hit(bucket)
        audit.record("auth.totp", request=request, outcome="failure", actor=user)
        login_audit.record(request, result="failure", user=user, method=f"{pending.get('method', 'password')}+totp", reason="bad_code")
        return _fail("That code is not valid.", 400)
    ratelimit.clear(bucket)
    _complete_login(request, user, f"{pending.get('method', 'password')}+{method}", pending.get("remember", True))
    return Response({"status": "ok", "must_change_password": user.must_change_password})


@api_view(["POST"])
@permission_classes([AllowAny])
def logout_view(request):
    if request.user.is_authenticated:
        from . import sessions

        login_audit.record(request, result="logout", user=request.user, method="logout")
        sessions.end(request)
        audit.record("auth.logout", request=request)
    logout(request)
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def change_password(request):
    user = request.user
    if not user.check_password(request.data.get("current_password") or ""):
        audit.record("auth.password_change", request=request, outcome="failure")
        return _fail("Your current password is incorrect.")
    try:
        S.set_password(user, request.data.get("new_password") or "", temporary=False, keep_device=request.session.get("device"))
    except S.AccountError as exc:
        return _fail(str(exc))
    user.refresh_from_db()
    request.session["epoch"] = user.session_epoch
    from django.contrib.auth import update_session_auth_hash

    update_session_auth_hash(request, user)
    audit.record("auth.password_change", request=request)
    return Response({"status": "ok"})


change_password.cls.allow_password_change_pending = True


@api_view(["POST"])
@permission_classes([AllowAny])
def forgot_password(request):
    ident = (request.data.get("username") or "").strip().lower()[:254]
    ip = audit.client_ip(request) or "unknown"
    if not ratelimit.too_many(f"forgot:{ip}", 5, 3600) and ident:
        ratelimit.hit(f"forgot:{ip}")
        user = User.objects.filter(is_active=True).filter(username=ident).first() or \
            User.objects.filter(is_active=True, email__iexact=ident).first()
        if user and user.email and config.get("smtp.enabled"):
            token = crypto.token_urlsafe(32)
            PasswordResetToken.objects.create(user=user, token_hash=crypto.hash_token(token),
                                              expires_at=timezone.now() + timedelta(minutes=int(config.get("auth.reset_token_minutes"))))
            from apps.notify.mailer import send_mail_now

            link = f"{settings.PUBLIC_ORIGIN}/reset-password?token={token}"
            try:
                send_mail_now(user.email, f"{config.get('general.app_name')}: password reset",
                              f"Hello {user.display_name},\n\nUse this link within {config.get('auth.reset_token_minutes')} minutes to set a new password:\n{link}\n\nIf you did not ask for this, ignore this email.")
                audit.record("auth.reset_requested", request=request, actor=None, target=user, subject_user=user)
            except Exception:  # noqa: BLE001
                audit.record("auth.reset_requested", request=request, outcome="failure", target=user, reason="smtp_error")
    # Always the same answer so accounts cannot be enumerated.
    return Response({"status": "ok", "message": "If the account has a registered email address, a reset link has been sent. Otherwise ask your family administrator for help."})


@api_view(["POST"])
@permission_classes([AllowAny])
def reset_password(request):
    token = request.data.get("token") or ""
    row = PasswordResetToken.objects.select_related("user").filter(token_hash=crypto.hash_token(token)).first()
    if row is None or not row.valid() or not row.user.is_active:
        return _fail("This reset link is invalid or has expired.")
    try:
        with transaction.atomic():
            S.set_password(row.user, request.data.get("password") or "", temporary=False)
            row.used_at = timezone.now()
            row.save(update_fields=["used_at"])
    except S.AccountError as exc:
        return _fail(str(exc))
    audit.record("auth.password_reset", request=request, actor=row.user, subject_user=row.user)
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def reauth(request):
    user = request.user
    bucket = f"reauth:{user.pk}"
    if ratelimit.too_many(bucket, 6, 900):
        return _fail("Too many attempts. Please wait a few minutes.", 429)
    ok = False
    if request.data.get("password") and user.check_password(request.data["password"]):
        ok = True
        if user.totp_enabled and not S.verify_second_factor(user, request.data.get("code", ""), request.data.get("recovery_code", "")):
            return _fail("Enter the code from your authenticator app.", 400, code="totp_required")
    if not ok:
        ratelimit.hit(bucket)
        return _fail("Verification failed.")
    request.session["reauth_at"] = timezone.now().isoformat()
    return Response({"status": "ok"})


# ------------------------------------------------------------------ setup wizard

@api_view(["POST"])
@permission_classes([AllowAny])
def setup_verify(request):
    ip = audit.client_ip(request) or "unknown"
    if ratelimit.too_many(f"setup:{ip}", 10, 3600):
        return _fail("Too many attempts.", 429)
    if not S.check_setup_token(request.data.get("token", "")):
        ratelimit.hit(f"setup:{ip}")
        return _fail("The setup code is invalid or expired. Run `personaldocs setup-token` on the server console.")
    return Response({"status": "ok", "slots": [{"slot": s, "role_label": l} for s, l in S.INITIAL_SLOTS],
                     "timezone": config.get("general.timezone")})


@api_view(["POST"])
@permission_classes([AllowAny])
def setup_complete(request):
    if not S.check_setup_token(request.data.get("token", "")):
        return _fail("The setup code is invalid or expired.", 403)
    try:
        result = S.complete_setup(request.data, request=request)
    except (S.AccountError, ValueError) as exc:
        return _fail(str(exc))
    names = {str(u.pk): u.username for u in User.objects.filter(pk__in=result["users"].values())}
    return Response({"status": "ok", "issued_passwords": result["issued_passwords"], "usernames": list(names.values())})


# ------------------------------------------------------------------ my account

@api_view(["GET", "PATCH"])
@permission_classes([IsActiveAuthenticated])
def me(request):
    u = request.user
    if request.method == "PATCH":
        for field, limit in (("display_name", 80), ("full_name", 150), ("email", 254)):
            if field in request.data:
                val = (request.data.get(field) or "").strip()[:limit]
                if field == "display_name" and not val:
                    return _fail("Display name cannot be empty.")
                setattr(u, field, val)
        u.save()
        audit.record("account.profile_update", request=request, fields=[f for f in ("display_name", "full_name", "email") if f in request.data])
    return Response(user_json(u, full=True))


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def totp_setup(request):
    if not config.get("auth.allow_totp"):
        return _fail("Authenticator apps are turned off by the administrator.", 403)
    if not recently_verified(request):
        return _fail("Please confirm your password first.", 403, code="reauth_required")
    return Response(S.totp_begin(request.user))


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def totp_enable(request):
    try:
        codes = S.totp_enable(request.user, request.data.get("code", ""))
    except S.AccountError as exc:
        return _fail(str(exc))
    audit.record("account.totp_enable", request=request)
    from apps.security import alerts

    alerts.account_security(request.user, "Authenticator app turned on", event="totp_enabled")
    return Response({"recovery_codes": codes})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def totp_disable(request):
    if not recently_verified(request):
        return _fail("Please confirm your password first.", 403, code="reauth_required")
    user = request.user
    has_passkey = PK.active(user).exists()
    if PK.requires_2fa(user) and not has_passkey:
        return _fail("Two-step verification is required for your account: add a passkey before turning off the authenticator app.")
    S.totp_disable(user, keep_recovery_codes=has_passkey)
    audit.record("account.totp_disable", request=request)
    from apps.security import alerts

    alerts.account_security(user, "Authenticator app turned off", event="totp_disabled")
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def recovery_codes(request):
    if not PK.has_second_factor(request.user):
        return _fail("Turn on an authenticator app or add a passkey first.")
    if not recently_verified(request):
        return _fail("Please confirm your password first.", 403, code="reauth_required")
    codes = S.regenerate_recovery_codes(request.user)
    audit.record("account.recovery_codes", request=request)
    from apps.security import alerts

    alerts.account_security(request.user, "Recovery codes regenerated", event="recovery_codes")
    return Response({"recovery_codes": codes})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def my_sessions(request):
    from . import sessions

    current = request.session.get("device")
    rows = sessions.active_for(request.user, int(config.get("auth.session_days")))
    return Response({"sessions": [{
        "id": str(r.id), "device": sessions.describe(r.user_agent), "ip": r.ip, "method": r.method,
        "created_at": r.created_at, "last_seen_at": r.last_seen_at, "current": str(r.id) == current,
    } for r in rows], "current_tracked": bool(current)})


@api_view(["DELETE"])
@permission_classes([IsActiveAuthenticated])
def revoke_session(request, pk):
    from .models import UserSession

    row = get_object_or_404(UserSession, pk=pk, user=request.user)
    if str(row.id) == request.session.get("device"):
        return _fail("Use Sign out to end this session.")
    if row.revoked_at is None:
        row.revoked_at = timezone.now()
        row.save(update_fields=["revoked_at"])
        audit.record("account.session_revoke", request=request, target=row)
    return Response(status=204)


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def sign_out_everywhere(request):
    from . import sessions

    u = request.user
    u.session_epoch += 1
    u.save(update_fields=["session_epoch"])
    request.session["epoch"] = u.session_epoch
    n = sessions.revoke_others(u, request.session.get("device"))
    audit.record("account.sign_out_everywhere", request=request, sessions=n)
    return Response({"status": "ok", "revoked": n})


# ------------------------------------------------------------------ family administration

def _visible_member_ids(user: User):
    if user.is_main_admin:
        return None
    group_ids = list(GroupMembership.objects.filter(user=user).values_list("group_id", flat=True))
    ids = set(GroupMembership.objects.filter(group_id__in=group_ids).values_list("user_id", flat=True))
    for d in Delegation.objects.filter(delegate=user):
        ids |= set(GroupMembership.objects.filter(group=d.group).values_list("user_id", flat=True))
    ids.add(user.pk)
    return ids


@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def members(request):
    if request.method == "GET":
        ids = _visible_member_ids(request.user)
        qs = User.objects.all() if ids is None else User.objects.filter(pk__in=ids, is_active=True)
        full = request.user.is_main_admin
        return Response({"members": [user_json(u, full=full or u.pk == request.user.pk) for u in qs]})
    if not request.user.is_main_admin:
        raise PermissionDenied("Only the main administrator can add family members.")
    d = request.data
    username = (d.get("username") or "").strip().lower()
    display = (d.get("display_name") or "").strip()
    if not username or not display:
        return _fail("Name and username are required.")
    if User.objects.filter(username=username).exists():
        return _fail("That username is already used.")
    password = d.get("password") or S.generate_password()
    try:
        with transaction.atomic():
            group = FamilyGroup.objects.filter(pk=d.get("group")).first() if d.get("group") else None
            u = User(username=username, display_name=display[:80], full_name=(d.get("full_name") or "")[:150],
                     role_label=(d.get("role_label") or "")[:40], email=(d.get("email") or "")[:254], reminder_group=group,
                     must_change_password=True, password_changed_at=timezone.now())
            S.check_new_password(password, u)
            u.set_password(password)
            u.save()
            if group:
                GroupMembership.objects.get_or_create(group=group, user=u)
            personal = S.create_personal_root(actor=request.user, user=u, library_root=S.library_root(request.user))
            if d.get("apply_template"):
                from apps.library.services import apply_template

                apply_template(actor=request.user, root=personal)
    except S.AccountError as exc:
        return _fail(str(exc))
    audit.record("family.member_add", request=request, target=u)
    return Response({"member": user_json(u, full=True), "temporary_password": password if not d.get("password") else None}, status=201)


@api_view(["PATCH"])
@permission_classes([IsMainAdmin])
def member_detail(request, pk):
    u = get_object_or_404(User, pk=pk)
    d = request.data
    try:
        if "is_main_admin" in d and not d["is_main_admin"]:
            S.guard_last_admin(u, removing_admin=True)
        if "is_active" in d and not d["is_active"]:
            S.guard_last_admin(u, deactivating=True)
    except S.AccountError as exc:
        return _fail(str(exc))
    for field, limit in (("display_name", 80), ("full_name", 150), ("email", 254), ("role_label", 40)):
        if field in d:
            setattr(u, field, (d.get(field) or "").strip()[:limit])
    if not u.display_name:
        return _fail("Display name cannot be empty.")
    if "username" in d:
        new = (d["username"] or "").strip().lower()
        if not new or User.objects.filter(username=new).exclude(pk=u.pk).exists():
            return _fail("That username is not available.")
        u.username = new
    if "is_main_admin" in d:
        u.is_main_admin = bool(d["is_main_admin"])
    if "is_active" in d:
        u.is_active = bool(d["is_active"])
        if not u.is_active:
            u.session_epoch += 1
    if "reminder_group" in d:
        u.reminder_group = FamilyGroup.objects.filter(pk=d["reminder_group"]).first() if d["reminder_group"] else None
    u.save()
    audit.record("family.member_update", request=request, target=u, fields=list(d.keys()))
    return Response(user_json(u, full=True))


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def member_reset_password(request, pk):
    u = get_object_or_404(User, pk=pk)
    password = request.data.get("password") or S.generate_password()
    try:
        S.set_password(u, password, temporary=True)
    except S.AccountError as exc:
        return _fail(str(exc))
    audit.record("family.password_reset_by_admin", request=request, target=u, subject_user=u)
    return Response({"temporary_password": password if not request.data.get("password") else None})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def member_reset_totp(request, pk):
    u = get_object_or_404(User, pk=pk)
    S.totp_disable(u, keep_recovery_codes=PK.active(u).exists())
    u.session_epoch += 1
    u.save(update_fields=["session_epoch"])
    audit.record("family.totp_reset_by_admin", request=request, target=u, subject_user=u)
    from apps.security import alerts

    alerts.account_security(u, "Authenticator app was reset", actor=request.user)
    return Response({"status": "ok"})


def group_json(g: FamilyGroup) -> dict:
    return {
        "id": str(g.pk),
        "name": g.name,
        "head": str(g.head_id) if g.head_id else None,
        "members": [str(i) for i in g.memberships.values_list("user_id", flat=True)],
        "delegations": [{"delegate": str(d.delegate_id), "scopes": d.scopes} for d in g.delegations.all()],
    }


@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def groups(request):
    if request.method == "GET":
        qs = FamilyGroup.objects.all()
        if not request.user.is_main_admin:
            ids = set(GroupMembership.objects.filter(user=request.user).values_list("group_id", flat=True))
            ids |= set(Delegation.objects.filter(delegate=request.user).values_list("group_id", flat=True))
            qs = qs.filter(pk__in=ids)
        return Response({"groups": [group_json(g) for g in qs], "scopes": DELEGATION_SCOPES})
    if not request.user.is_main_admin:
        raise PermissionDenied("Only the main administrator can create groups.")
    name = (request.data.get("name") or "").strip()[:100]
    if not name or FamilyGroup.objects.filter(name=name).exists():
        return _fail("Enter a unique group name.")
    g = FamilyGroup.objects.create(name=name, head=User.objects.filter(pk=request.data.get("head")).first() if request.data.get("head") else None)
    audit.record("family.group_create", request=request, target=g)
    return Response(group_json(g), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def group_detail(request, pk):
    g = get_object_or_404(FamilyGroup, pk=pk)
    if request.method == "DELETE":
        if not request.user.is_main_admin:
            raise PermissionDenied()
        if g.memberships.exists():
            return _fail("Remove members before deleting the group.")
        g.delete()
        audit.record("family.group_delete", request=request, target_type="familygroup", target_id=str(pk))
        return Response(status=204)
    d = request.data
    if ("name" in d or "head" in d) and not request.user.is_main_admin:
        raise PermissionDenied("Only the main administrator can rename a group or change its head.")
    if "name" in d:
        name = (d["name"] or "").strip()[:100]
        if not name or FamilyGroup.objects.filter(name=name).exclude(pk=g.pk).exists():
            return _fail("Enter a unique group name.")
        g.name = name
    if "head" in d:
        g.head = User.objects.filter(pk=d["head"]).first() if d["head"] else None
    g.save()
    if "add_member" in d or "remove_member" in d:
        if not S.can_manage_membership(request.user, g):
            raise PermissionDenied("You cannot manage this group's members.")
        try:
            S.check_membership_escalation(request.user, g)
        except S.AccountError as exc:
            return _fail(str(exc), 403)
        if d.get("add_member"):
            u = get_object_or_404(User, pk=d["add_member"])
            GroupMembership.objects.get_or_create(group=g, user=u)
            audit.record("family.group_member_add", request=request, target=g, member=str(u.pk))
        if d.get("remove_member"):
            GroupMembership.objects.filter(group=g, user_id=d["remove_member"]).delete()
            audit.record("family.group_member_remove", request=request, target=g, member=str(d["remove_member"]))
    audit.record("family.group_update", request=request, target=g, fields=[k for k in d.keys() if k in ("name", "head")])
    return Response(group_json(g))


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def delegation(request):
    g = get_object_or_404(FamilyGroup, pk=request.data.get("group"))
    u = get_object_or_404(User, pk=request.data.get("delegate"))
    try:
        S.set_delegation(actor=request.user, delegate=u, group=g, scopes=list(request.data.get("scopes") or []), request=request)
    except S.AccountError as exc:
        return _fail(str(exc))
    return Response(group_json(g))


# ------------------------------------------------------------------ profile photos

def _photo_crop(data) -> dict | None:
    if not data.get("crop_size"):
        return None
    return {"x": data.get("crop_x", 0), "y": data.get("crop_y", 0), "size": data.get("crop_size")}


def _photo_change(request, user: User, *, by_admin: bool):
    action = "family.photo" if by_admin else "account.photo"
    if request.method == "DELETE":
        photos.clear(user)
        audit.record(f"{action}_remove", request=request, target=user, subject_user=user)
        return Response(user_json(user, full=True))
    f = request.FILES.get("file")
    if f is None:
        return _fail("Choose an image file.")
    if f.size > photos.MAX_BYTES:
        return _fail("The image is larger than 5 MB.")
    try:
        photos.save(user, f.read(), _photo_crop(request.data))
    except photos.PhotoError as exc:
        return _fail(str(exc))
    audit.record(f"{action}_update", request=request, target=user, subject_user=user)
    return Response(user_json(user, full=True))


@api_view(["POST", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def my_photo(request):
    return _photo_change(request, request.user, by_admin=False)


@api_view(["POST", "DELETE"])
@permission_classes([IsMainAdmin])
def member_photo(request, pk):
    return _photo_change(request, get_object_or_404(User, pk=pk), by_admin=True)


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def user_photo(request, pk):
    """Serve a profile photo to signed-in users who can see that family member."""
    from django.http import FileResponse, Http404

    target = get_object_or_404(User, pk=pk)
    visible = _visible_member_ids(request.user)
    if visible is not None and target.pk not in visible:
        raise Http404  # same answer as "no photo": does not reveal whether a photo exists
    path = photos.path_for(target, thumb=request.query_params.get("size") != "full")
    if path is None:
        raise Http404
    resp = FileResponse(open(path, "rb"), content_type="image/webp")
    resp["Cache-Control"] = "private, max-age=86400"
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Content-Disposition"] = "inline"
    return resp



# ------------------------------------------------------------------ passkeys (WebAuthn)

def _pending_user(request):
    from datetime import datetime

    pending = request.session.get("pending_2fa")
    if not pending:
        return None, None
    if timezone.now() - datetime.fromisoformat(pending["at"]) > timedelta(minutes=5):
        request.session.pop("pending_2fa", None)
        return None, None
    return User.objects.filter(pk=pending["uid"], is_active=True).first(), pending


@api_view(["POST"])
@permission_classes([AllowAny])
def passkey_login_options(request):
    purpose = request.data.get("purpose", "2fa")
    if purpose == "passwordless":
        if not (config.get("auth.allow_passkeys") and config.get("auth.allow_passwordless")):
            return _fail("Passwordless sign-in is not enabled.", 403)
        return Response(PK.authentication_options(request.session, user=None, purpose="passwordless"))
    user, _pending = _pending_user(request)
    if user is None:
        return _fail("Sign in with your password first.", 400)
    try:
        return Response(PK.authentication_options(request.session, user=user, purpose="2fa"))
    except PK.PasskeyError as exc:
        return _fail(str(exc))


@api_view(["POST"])
@permission_classes([AllowAny])
def passkey_login_verify(request):
    purpose = request.data.get("purpose", "2fa")
    credential = request.data.get("credential") or {}
    ip = audit.client_ip(request) or "unknown"
    if ratelimit.too_many(f"passkey:ip:{ip}", int(config.get("auth.login_rate_limit")) * 3, 900):
        login_audit.record(request, result="denied", method="passkey", reason="rate_limited")
        return _fail("Too many attempts. Please wait a few minutes and try again.", 429)
    if purpose == "passwordless":
        if not (config.get("auth.allow_passkeys") and config.get("auth.allow_passwordless")):
            return _fail("Passwordless sign-in is not enabled.", 403)
        try:
            row = PK.authenticate(request.session, credential, purpose="passwordless")
        except PK.PasskeyError as exc:
            ratelimit.hit(f"passkey:ip:{ip}")
            login_audit.record(request, result="failure", method="passkey", reason="passkey_invalid")
            return _fail(str(exc))
        user = row.user
        if not user.is_active or not user.passwordless_enabled:
            login_audit.record(request, result="denied", user=user, method="passkey", reason="passwordless_off")
            return _fail("Passwordless sign-in is not turned on for this account. Sign in with your password.", 403)
        _complete_login(request, user, "passkey", True)
        return Response({"status": "ok", "must_change_password": user.must_change_password})
    user, pending = _pending_user(request)
    if user is None:
        return _fail("Sign in with your password first.", 400)
    try:
        PK.authenticate(request.session, credential, purpose="2fa", user=user)
    except PK.PasskeyError as exc:
        ratelimit.hit(f"passkey:ip:{ip}")
        login_audit.record(request, result="failure", user=user, method=f"{pending.get('method', 'password')}+passkey", reason="passkey_invalid")
        return _fail(str(exc))
    _complete_login(request, user, f"{pending.get('method', 'password')}+passkey", pending.get("remember", True))
    return Response({"status": "ok", "must_change_password": user.must_change_password})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def reauth_passkey(request):
    """Recent authentication with a passkey: step 'options' then 'verify'."""
    if request.data.get("step") == "options":
        try:
            return Response(PK.authentication_options(request.session, user=request.user, purpose="reauth"))
        except PK.PasskeyError as exc:
            return _fail(str(exc))
    try:
        PK.authenticate(request.session, request.data.get("credential") or {}, purpose="reauth", user=request.user)
    except PK.PasskeyError as exc:
        return _fail(str(exc))
    request.session["reauth_at"] = timezone.now().isoformat()
    audit.record("auth.reauth", request=request, method="passkey")
    return Response({"status": "ok"})


reauth_passkey.cls.allow_2fa_setup_pending = True


def passkey_json(c: WebAuthnCredential) -> dict:
    return {"id": c.pk, "name": c.name, "created_at": c.created_at, "last_used_at": c.last_used_at, "transports": c.transports,
            "synced": c.device_type == "multi_device" or c.backed_up, "passwordless_capable": c.discoverable}


@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def my_passkeys(request):
    user = request.user
    if request.method == "GET":
        return Response({"passkeys": [passkey_json(c) for c in PK.active(user)], "rp_id": PK.rp_id(),
                         "allowed": bool(config.get("auth.allow_passkeys")), "passwordless_allowed": bool(config.get("auth.allow_passwordless")),
                         "passwordless_enabled": user.passwordless_enabled})
    if not config.get("auth.allow_passkeys"):
        return _fail("Passkeys are turned off by the administrator.", 403)
    if not recently_verified(request):
        return _fail("Please confirm it's you first.", 403, code="reauth_required")
    if request.data.get("step") == "options":
        return Response(PK.registration_options(request.session, user))
    try:
        row = PK.register(request.session, user, request.data.get("credential") or {}, request.data.get("name") or "")
    except PK.PasskeyError as exc:
        audit.record("account.passkey_register", request=request, outcome="failure")
        return _fail(str(exc))
    codes = None
    if not user.recovery_codes.filter(used_at__isnull=True).exists():
        codes = S.regenerate_recovery_codes(user)
    audit.record("account.passkey_register", request=request, target=row, name=row.name)
    from apps.security import alerts

    alerts.account_security(user, f"New passkey “{row.name}” registered", event="passkey_added")
    return Response({"passkey": passkey_json(row), "recovery_codes": codes}, status=201)


my_passkeys.cls.allow_2fa_setup_pending = True


@api_view(["PATCH", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def my_passkey_detail(request, pk):
    from apps.security import alerts

    user = request.user
    row = get_object_or_404(WebAuthnCredential, pk=pk, user=user, revoked_at__isnull=True)
    if request.method == "PATCH":
        name = (request.data.get("name") or "").strip()[:80]
        if not name:
            return _fail("Enter a name.")
        row.name = name
        row.save(update_fields=["name"])
        audit.record("account.passkey_rename", request=request, target=row, name=name)
        return Response(passkey_json(row))
    if not recently_verified(request):
        return _fail("Please confirm it's you first.", 403, code="reauth_required")
    remaining = PK.active(user).exclude(pk=row.pk).exists() or user.totp_enabled
    if PK.requires_2fa(user) and not remaining:
        return _fail("Two-step verification is required for your account: add another passkey or an authenticator app before removing this one.")
    row.revoked_at = timezone.now()
    row.save(update_fields=["revoked_at"])
    if not PK.active(user).filter(discoverable=True).exists() and user.passwordless_enabled:
        user.passwordless_enabled = False
        user.save(update_fields=["passwordless_enabled"])
    if not remaining:
        from .models import RecoveryCode

        RecoveryCode.objects.filter(user=user).delete()
    audit.record("account.passkey_revoke", request=request, target=row, name=row.name)
    alerts.account_security(user, f"Passkey “{row.name}” removed", event="passkey_removed")
    return Response(status=204)


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def my_passwordless(request):
    from apps.security import alerts

    user = request.user
    enabled = bool(request.data.get("enabled"))
    if not recently_verified(request):
        return _fail("Please confirm it's you first.", 403, code="reauth_required")
    if enabled:
        if not (config.get("auth.allow_passkeys") and config.get("auth.allow_passwordless")):
            return _fail("Passwordless sign-in is not allowed in this installation.", 403)
        if not PK.active(user).filter(discoverable=True).exists():
            return _fail("Register a passkey that supports passwordless sign-in first (most phones and computers do).")
    user.passwordless_enabled = enabled
    user.save(update_fields=["passwordless_enabled"])
    audit.record("account.passwordless", request=request, enabled=enabled)
    alerts.account_security(user, "Passwordless sign-in " + ("turned on" if enabled else "turned off"), event="passwordless")
    return Response({"passwordless_enabled": enabled})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def member_reset_2fa(request, pk):
    """Administrator-assisted recovery: removes authenticator app, passkeys and recovery codes; signs the person out."""
    from apps.security import alerts

    u = get_object_or_404(User, pk=pk)
    S.totp_disable(u)
    n = PK.active(u).update(revoked_at=timezone.now())
    u.passwordless_enabled = False
    u.session_epoch += 1
    u.save(update_fields=["passwordless_enabled", "session_epoch"])
    audit.record("family.two_factor_reset_by_admin", request=request, target=u, subject_user=u, passkeys_revoked=n)
    alerts.account_security(u, "Two-step verification was reset", actor=request.user)
    return Response({"status": "ok", "passkeys_revoked": n})


# Views reachable while a required two-step verification setup is still pending.
for _view in (me, totp_setup, totp_enable, recovery_codes, reauth, change_password, my_sessions):
    _view.cls.allow_2fa_setup_pending = True
