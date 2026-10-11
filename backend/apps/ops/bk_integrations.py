"""Post-recovery integration verification.

After a full-system recovery every restored external integration starts **on hold**: its encrypted configuration is
back, but nothing is sent or fetched (outbox deliveries wait, email import and backups to that destination pause)
until a safe connection test passes. A test never sends a message: SMTP opens and authenticates a connection,
Telegram calls getMe, Discord reads the webhook's metadata, storage destinations list/stat, IMAP logs in and out.
Expired or revoked credentials become **Action Required**. In Compromise recovery WhatsApp linked-device sessions are
never reconnected automatically: they need a fresh QR link.
"""
from __future__ import annotations

from django.utils import timezone

from apps.core import config

STATE_KEY = "recovery_integrations"
VERIFIED, PENDING, ACTION, RELINK = "verified", "pending_verification", "action_required", "reconnect_required"
LABELS = {VERIFIED: "Verified", PENDING: "Waiting for verification", ACTION: "Action Required", RELINK: "Reconnect Required",
          "not_configured": "Not configured"}


def _state() -> dict:
    from apps.security.models import HealthState

    return HealthState.get(STATE_KEY)


def _put(data: dict) -> None:
    from apps.security.models import HealthState

    HealthState.objects.update_or_create(key=STATE_KEY, defaults={"data": data})


def hold_active(name: str) -> bool:
    st = _state()
    if not st.get("active"):
        return False
    item = st.get("items", {}).get(name)
    return item is not None and item.get("state") != VERIFIED


def channel_on_hold(channel: str) -> bool:
    return hold_active(f"channel:{channel}")


def inventory() -> dict[str, str]:
    """Integrations present in the (restored) configuration: key -> label. No secret values."""
    from apps.mailimport.models import EmailAccount

    from .models import BackupDestination

    items = {}
    if config.get("smtp.enabled"):
        items["channel:email"] = "Email (SMTP)"
    if config.get("telegram.enabled"):
        items["channel:telegram"] = "Telegram bot"
    if config.get("notifications.push_enabled"):
        items["channel:push"] = "PWA push"
    try:
        from apps.notify.models import DiscordWebhook

        if DiscordWebhook.objects.filter(enabled=True).exists():
            items["channel:discord"] = "Discord webhooks"
    except Exception:  # noqa: BLE001 - before the notification migration
        pass
    if config.get("whatsapp.enabled"):
        items["channel:whatsapp"] = "WhatsApp Personal (experimental)"
    for d in BackupDestination.objects.filter(enabled=True):
        items[f"destination:{d.id}"] = f"Backup destination “{d.name}”"
    if EmailAccount.objects.filter(enabled=True).exists():
        items["mail_import"] = "Email import accounts"
    if config.get("google.enabled"):
        items["google"] = "Google sign-in"
    if config.get("authentik.enabled"):
        items["authentik"] = "authentik sign-in"
    return items


def start_hold(mode: str) -> dict:
    items = {k: {"label": v, "state": PENDING, "detail": "", "at": None} for k, v in inventory().items()}
    data = {"active": True, "mode": mode, "started_at": timezone.now().isoformat(), "items": items}
    _put(data)
    return data


def _test(name: str, mode: str) -> tuple[str, str]:
    if name == "channel:email":
        from apps.notify.mailer import RegistryEmailBackend

        b = RegistryEmailBackend()
        b.open()
        b.close()
        return VERIFIED, "SMTP connection and sign-in succeeded (no email was sent)"
    if name == "channel:telegram":
        from apps.notify import telegram

        telegram.test_connection()
        return VERIFIED, "Bot token accepted (getMe)"
    if name == "channel:push":
        from apps.notify import webpush

        webpush.public_key()
        return VERIFIED, "Push keys restored"
    if name == "channel:discord":
        from apps.notify import discord

        bad = discord.verify_all()
        return (VERIFIED, "Webhooks reachable") if not bad else (ACTION, f"{bad} webhook(s) were deleted or rejected; owners must add them again")
    if name == "channel:whatsapp":
        from apps.notify import whatsapp

        if mode == "compromise":
            n = whatsapp.require_relink_all("Compromise recovery: linked-device sessions are not trusted automatically.")
            return RELINK, f"{n} linked session(s) must be linked again with a QR code"
        res = whatsapp.reconnect_all()
        if res.get("unavailable"):
            return ACTION, "The WhatsApp bridge is not running"
        return (VERIFIED, f"{res.get('connected', 0)} session(s) reconnected") if not res.get("relink") else \
            (RELINK, f"{res['relink']} session(s) were rejected by WhatsApp and must be linked again")
    if name.startswith("destination:"):
        from .bk_destinations import provider
        from .models import BackupDestination

        d = BackupDestination.objects.get(pk=int(name.split(":")[1]))
        res = provider(d).test()
        return VERIFIED, res.get("detail", "Reachable")
    if name == "mail_import":
        from apps.mailimport import imap
        from apps.mailimport.models import EmailAccount

        bad = 0
        for acc in EmailAccount.objects.filter(enabled=True):
            try:
                imap.connect(acc).logout()
            except Exception:  # noqa: BLE001
                bad += 1
        return (VERIFIED, "All accounts signed in") if not bad else (ACTION, f"{bad} account(s) need their password again")
    if name in ("google", "authentik"):
        return VERIFIED, "Configuration restored; sign in once to confirm"
    return ACTION, "Unknown integration"


def verify(names: list[str] | None = None) -> dict:
    st = _state()
    if not st.get("active"):
        return st
    mode = st.get("mode", "normal")
    for name, item in st.get("items", {}).items():
        if names and name not in names:
            continue
        if item.get("state") == VERIFIED:
            continue
        try:
            state, detail = _test(name, mode)
        except Exception as exc:  # noqa: BLE001 - every failure is an actionable state, never a crash
            msg = str(exc)
            state = ACTION
            detail = ("Credentials were rejected (expired or revoked): enter them again." if any(x in msg.lower() for x in ("auth", "401", "403", "token", "password"))
                      else f"Not reachable: {msg[:160]}")
        item.update(state=state, detail=detail, at=timezone.now().isoformat())
    if all(i.get("state") == VERIFIED for i in st.get("items", {}).values()):
        st["active"] = False
        st["completed_at"] = timezone.now().isoformat()
    _put(st)
    return st


def release(name: str) -> dict:
    """The main administrator accepts an integration after fixing it elsewhere (e.g. re-linked WhatsApp)."""
    st = _state()
    if name in st.get("items", {}):
        st["items"][name].update(state=VERIFIED, detail="Accepted by the main administrator", at=timezone.now().isoformat())
        if all(i.get("state") == VERIFIED for i in st["items"].values()):
            st["active"] = False
        _put(st)
    return st


def summary() -> dict:
    st = _state()
    return {"active": bool(st.get("active")), "mode": st.get("mode"), "started_at": st.get("started_at"),
            "items": [{"key": k, **v, "state_label": LABELS.get(v.get("state"), v.get("state"))} for k, v in st.get("items", {}).items()]}
