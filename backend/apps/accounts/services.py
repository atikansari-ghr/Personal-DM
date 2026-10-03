"""Account, setup, family-group and delegation operations."""
from __future__ import annotations

import secrets
import string
from datetime import timedelta

import pyotp
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import audit, config, crypto

from .models import (AVATAR_COLORS, DELEGATION_SCOPES, Delegation, FamilyGroup, GroupMembership, RecoveryCode, SetupState,
                     User)


class AccountError(Exception):
    pass


INITIAL_SLOTS = [
    ("dad", "Dad"), ("mom", "Mom"), ("son1", "Son1"), ("daughter", "Daughter"), ("son2", "Son2"), ("son3", "Son3"),
]


def generate_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length - 2)) + secrets.choice("!@#%+=?") + secrets.choice(string.digits)
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw):
            return pw


def check_new_password(password: str, user: User | None = None) -> None:
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        raise AccountError(" ".join(exc.messages))


# ------------------------------------------------------------------ setup

SETUP_TOKEN_HOURS = 24


def new_setup_token() -> str:
    state = SetupState.get()
    if state.completed_at:
        raise AccountError("Setup is already complete.")
    token = crypto.token_urlsafe(24)
    state.token_hash = crypto.hash_token(token)
    state.token_created_at = timezone.now()
    state.save()
    return token


def check_setup_token(token: str) -> bool:
    state = SetupState.get()
    if state.completed_at or not state.token_hash or not token:
        return False
    if state.token_created_at and state.token_created_at < timezone.now() - timedelta(hours=SETUP_TOKEN_HOURS):
        return False
    return secrets.compare_digest(state.token_hash, crypto.hash_token(token))


def create_personal_root(*, actor, user: User, library_root):
    from apps.library import permissions as P
    from apps.library.models import AccessRule, Folder

    existing = Folder.objects.filter(owner=user, kind=Folder.PERSONAL_ROOT).first()
    if existing:
        return existing
    name = user.display_name
    base, n = name, 2
    while Folder.objects.filter(parent=library_root, name=name, archived_at__isnull=True).exists():
        name = f"{base} ({n})"
        n += 1
    folder = Folder.objects.create(parent=library_root, name=name, owner=user, kind=Folder.PERSONAL_ROOT, emoji="👤",
                                   created_by=actor, group=user.reminder_group)
    AccessRule.objects.create(folder=folder, user=user, caps=P.OWNER_DEFAULT, created_by=actor)
    return folder


def library_root(actor=None):
    from apps.library.models import Folder

    root = Folder.objects.filter(parent__isnull=True, kind="library_root").first()
    if root is None:
        root = Folder.objects.create(parent=None, name="Family library", kind="library_root", emoji="📚", created_by=actor)
    return root


@transaction.atomic
def complete_setup(data: dict, request=None) -> dict:
    """Idempotent within its transaction; refuses to run twice once completed."""
    state = SetupState.objects.select_for_update().get_or_create(id=1)[0]
    if state.completed_at:
        raise AccountError("Setup is already complete.")
    group_name = (data.get("group_name") or "My family").strip()[:100]
    tz = data.get("timezone") or "Asia/Riyadh"
    config.set_value("general.timezone", tz)
    if data.get("app_name"):
        config.set_value("general.app_name", data["app_name"])
    members = data.get("members") or []
    slots = {m.get("slot"): m for m in members}
    if "dad" not in slots:
        raise AccountError("The main administrator (Dad) account is required.")
    usernames = [(m.get("username") or "").strip().lower() for m in members]
    if len(set(usernames)) != len(usernames) or any(not u for u in usernames):
        raise AccountError("Every account needs a unique username.")
    group, _ = FamilyGroup.objects.get_or_create(name=group_name)
    root = library_root()
    issued = {}
    created = state.progress.get("users", {})
    order = [s for s, _ in INITIAL_SLOTS]
    for idx, (slot, label) in enumerate(INITIAL_SLOTS):
        m = slots.get(slot)
        if not m:
            continue
        display = (m.get("display_name") or "").strip()
        if not display:
            raise AccountError(f"Enter a name for {label}.")
        username = m["username"].strip().lower()
        user = User.objects.filter(pk=created.get(slot)).first() if created.get(slot) else None
        if user is None:
            if User.objects.filter(username=username).exists():
                raise AccountError(f"Username {username} is already used.")
            user = User(username=username)
        user.display_name = display[:80]
        user.full_name = (m.get("full_name") or "").strip()[:150]
        user.role_label = (m.get("role_label") or label)[:40]
        user.email = (m.get("email") or "").strip()[:254]
        user.sort_order = order.index(slot)
        user.avatar_color = AVATAR_COLORS[idx % len(AVATAR_COLORS)]
        user.reminder_group = group
        if slot == "dad":
            user.is_main_admin = True
        password = m.get("password") or ""
        if m.get("generate_password") or not password:
            if slot == "dad" and not m.get("generate_password"):
                raise AccountError("Set a password for the main administrator.")
            password = generate_password()
            issued[username] = password
        check_new_password(password, user)
        user.set_password(password)
        user.must_change_password = slot != "dad"
        user.password_changed_at = timezone.now()
        user.save()
        created[slot] = str(user.pk)
        GroupMembership.objects.get_or_create(group=group, user=user)
        create_personal_root(actor=None, user=user, library_root=root)
    dad = User.objects.get(pk=created["dad"])
    group.head = dad
    group.save()
    _ensure_shared_folder(root, dad, group, share_view=bool(data.get("share_family_folder_view")))
    state.progress = {"users": created}
    state.completed_at = timezone.now()
    state.token_hash = ""
    state.save()
    audit.record("setup.complete", request=request, actor=dad, members=len(created))
    return {"issued_passwords": issued, "users": created}


def _ensure_shared_folder(root, actor, group, share_view: bool):
    from apps.library import permissions as P
    from apps.library.models import AccessRule, Folder

    shared = Folder.objects.filter(parent=root, kind=Folder.SHARED, name="Shared family").first()
    if shared is None:
        shared = Folder.objects.create(parent=root, name="Shared family", kind=Folder.SHARED, emoji="👪",
                                       created_by=actor, group=group)
    if share_view:
        AccessRule.objects.get_or_create(folder=shared, group=group, defaults={"caps": P.VIEW | P.DOWNLOAD, "created_by": actor})
    return shared


# ------------------------------------------------------------------ TOTP / recovery codes

def totp_begin(user: User) -> dict:
    secret = pyotp.random_base32()
    user.totp_pending_enc = crypto.encrypt(secret)
    user.save(update_fields=["totp_pending_enc"])
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=config.get("general.app_name"))
    return {"secret": secret, "uri": uri, "qr_svg": _qr_svg(uri)}


def _qr_svg(data: str) -> str:
    import io

    import qrcode
    import qrcode.image.svg

    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def _verify_totp(secret: str, code: str) -> bool:
    code = (code or "").replace(" ", "")
    return code.isdigit() and len(code) == 6 and pyotp.TOTP(secret).verify(code, valid_window=1)


def totp_enable(user: User, code: str) -> list[str]:
    if not user.totp_pending_enc:
        raise AccountError("Start authenticator setup first.")
    secret = crypto.decrypt(user.totp_pending_enc)
    if not _verify_totp(secret, code):
        raise AccountError("That code is not valid. Check your device time and try again.")
    user.totp_secret_enc = user.totp_pending_enc
    user.totp_pending_enc = ""
    user.totp_enabled = True
    user.save(update_fields=["totp_secret_enc", "totp_pending_enc", "totp_enabled"])
    return regenerate_recovery_codes(user)


def totp_disable(user: User) -> None:
    user.totp_enabled = False
    user.totp_secret_enc = ""
    user.totp_pending_enc = ""
    user.save(update_fields=["totp_enabled", "totp_secret_enc", "totp_pending_enc"])
    RecoveryCode.objects.filter(user=user).delete()


def regenerate_recovery_codes(user: User) -> list[str]:
    RecoveryCode.objects.filter(user=user).delete()
    codes = ["-".join(secrets.token_hex(2) for _ in range(3)) for _ in range(10)]
    RecoveryCode.objects.bulk_create([RecoveryCode(user=user, code_hash=make_password(c)) for c in codes])
    return codes


def verify_second_factor(user: User, code: str = "", recovery_code: str = "") -> str | None:
    if code and user.totp_enabled and _verify_totp(crypto.decrypt(user.totp_secret_enc), code):
        return "totp"
    if recovery_code:
        rc = recovery_code.strip().lower()
        for row in RecoveryCode.objects.filter(user=user, used_at__isnull=True):
            if check_password(rc, row.code_hash):
                row.used_at = timezone.now()
                row.save(update_fields=["used_at"])
                return "recovery_code"
    return None


# ------------------------------------------------------------------ passwords

def set_password(user: User, password: str, *, temporary: bool) -> None:
    check_new_password(password, user)
    user.set_password(password)
    user.must_change_password = temporary
    user.password_changed_at = timezone.now()
    user.session_epoch += 1
    user.save(update_fields=["password", "must_change_password", "password_changed_at", "session_epoch"])
    user.reset_tokens.filter(used_at__isnull=True).update(used_at=timezone.now())


def active_main_admins():
    return User.objects.filter(is_main_admin=True, is_active=True)


def guard_last_admin(user: User, *, removing_admin: bool = False, deactivating: bool = False) -> None:
    if (removing_admin or deactivating) and user.is_main_admin and active_main_admins().exclude(pk=user.pk).count() == 0:
        raise AccountError("This is the last main administrator; assign another main administrator first.")


# ------------------------------------------------------------------ groups & delegation

def delegations_for(user: User, scope: str):
    return [d for d in Delegation.objects.filter(delegate=user).select_related("group") if scope in d.scopes]


def can_manage_membership(actor: User, group: FamilyGroup) -> bool:
    return actor.is_main_admin or any(d.group_id == group.id for d in delegations_for(actor, "membership"))


def check_membership_escalation(actor: User, group: FamilyGroup) -> None:
    """A delegate adding someone to a group must not hand out access the delegate does not hold."""
    if actor.is_main_admin:
        return
    from apps.library.models import AccessRule
    from apps.library.permissions import AccessContext

    ctx = AccessContext.build(actor)
    for rule in AccessRule.objects.filter(group=group).select_related("document"):
        held = ctx.folder_caps(rule.folder_id) if rule.folder_id else ctx.doc_caps(rule.document)
        if rule.caps & ~held:
            raise AccountError("This group has access you do not hold; only the main administrator can change its members.")


def set_delegation(*, actor: User, delegate: User, group: FamilyGroup, scopes: list[str], request=None):
    if not actor.is_main_admin:
        raise AccountError("Only the main administrator can grant delegation.")
    bad = [s for s in scopes if s not in DELEGATION_SCOPES]
    if bad:
        raise AccountError(f"Unknown scope: {', '.join(bad)}")
    if not scopes:
        Delegation.objects.filter(delegate=delegate, group=group).delete()
        audit.record("delegation.revoke", request=request, actor=actor, target=group, delegate=str(delegate.pk))
        return None
    d, _ = Delegation.objects.update_or_create(delegate=delegate, group=group,
                                               defaults={"scopes": scopes, "granted_by": actor})
    audit.record("delegation.grant", request=request, actor=actor, target=group, delegate=str(delegate.pk), scopes=scopes)
    return d
