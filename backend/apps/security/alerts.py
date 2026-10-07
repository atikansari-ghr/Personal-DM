"""Security alerts through the existing notification system (in-app, email, Telegram).

Each alert type has its own on/off setting (alerts.*). Alerts are throttled per type and subject so an attack
cannot produce thousands of messages, and never contain passwords, codes, tokens or document contents.
Failed-login escalation: many failures from one address within an hour add a temporary automatic block.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from apps.core import config, ratelimit
from apps.core.registry import BY_KEY as BY_KEY_SETTINGS

log = logging.getLogger("personaldocs.security")


def _admins():
    from apps.accounts.models import User

    from django.db.models import Q

    return User.objects.filter(Q(is_main_admin=True) | Q(is_admin=True), is_active=True)


def _throttled(bucket: str, window_seconds: int) -> bool:
    if ratelimit.too_many(f"alert:{bucket}", 1, window_seconds):
        return True
    ratelimit.hit(f"alert:{bucket}")
    return False


def _send(users, *, event: str, key: str, subject: str, body: str = "", facts=(), link: str = "/settings/activity?view=logins"):
    from apps.notify.events import notify

    for u in users:
        notify(u, event, kind="security", key=f"{key}:{u.pk}", title=subject, lines=[body] if body else [], facts=facts, link=link)


def _where(event) -> str:
    place = event.country_name or "unknown location"
    return f"{event.ip or 'unknown address'} ({place})"


def _login_facts(event) -> list:
    device = " · ".join(x for x in (event.browser, event.os, event.device) if x)
    return [("IP address", event.ip or "unknown"), ("Country", event.country_name or event.country or "unknown"),
            ("Sign-in method", event.method), ("Device", device)]


def on_login_event(event) -> None:
    from .models import LoginEvent

    stamp = timezone.now().strftime("%Y%m%d%H")
    if event.result in (LoginEvent.FAILURE, LoginEvent.DENIED):
        _check_escalation(event)
        if config.get("alerts.failed_logins") and event.username:
            since = timezone.now() - timedelta(hours=1)
            n = LoginEvent.objects.filter(username=event.username, result=LoginEvent.FAILURE, at__gte=since).count()
            if n >= int(config.get("auth.login_rate_limit")) and not _throttled(f"failed:{event.username}", 3600):
                _send(_admins(), event="security.failed_logins", key=f"sec:failed:{event.username}:{stamp}",
                      subject="Repeated failed sign-ins",
                      body=f"{n} failed sign-in attempts for the account '{event.username}' in the last hour.",
                      facts=_login_facts(event))
        return
    if event.result != LoginEvent.SUCCESS or event.user is None:
        return
    flags = set(event.flags or [])
    who = event.user.display_name or event.user.username
    if "new_country" in flags and config.get("alerts.new_country") and not _throttled(f"newc:{event.user_id}:{event.country}", 86400):
        _send({event.user, *_admins()}, event="security.new_country", key=f"sec:newc:{event.id}",
              subject="Sign-in from a new country",
              body=f"{who} signed in from {_where(event)} for the first time. If this was not expected, change the password and sign out other devices.",
              facts=_login_facts(event))
    elif "new_ip" in flags and config.get("alerts.new_ip") and not _throttled(f"newip:{event.user_id}:{event.ip}", 86400):
        _send({event.user, *_admins()}, event="security.new_ip", key=f"sec:newip:{event.id}",
              subject="Sign-in from a new address", body=f"{who} signed in from a new address.", facts=_login_facts(event))
    if "policy_exception" in flags and config.get("alerts.policy_exception") and not _throttled(f"exc:{event.user_id}", 3600):
        _send(_admins(), event="security.policy_exception", key=f"sec:exc:{event.id}",
              subject="Sign-in allowed by temporary country access",
              body=f"{who} signed in from a country that is only allowed by a temporary travel exception.", facts=_login_facts(event))
    # optional "every sign-in" information for the person (off by default)
    _send([event.user], event="account.login", key=f"login:{event.id}", subject="New sign-in to your account",
          body="If this was not you, change your password and sign out other devices in My account → Sessions.",
          facts=_login_facts(event), link="/settings/account?tab=security")


def _check_escalation(event) -> None:
    """Many failures from one public address within an hour -> temporary automatic block + alert."""
    from . import netutil, policy
    from .models import IPRule, LoginEvent

    if not event.ip:
        return
    ip = netutil.parse_ip(event.ip)
    if ip is None or netutil.is_internal(ip):
        return
    threshold = int(config.get("security.escalation_failures"))
    if threshold <= 0:
        return
    since = timezone.now() - timedelta(hours=1)
    n = LoginEvent.objects.filter(ip=event.ip, result__in=[LoginEvent.FAILURE, LoginEvent.DENIED], at__gte=since).count()
    if n < threshold:
        return
    now = timezone.now()
    if any(r.live(now) for r in IPRule.objects.filter(cidr=f"{ip}/{ip.max_prefixlen}", kind=IPRule.TRUSTED)):
        return
    minutes = int(config.get("security.escalation_minutes"))
    exists = [r for r in IPRule.objects.filter(cidr=f"{ip}/{ip.max_prefixlen}", kind=IPRule.BLOCKED) if r.live(now)]
    if not exists:
        IPRule.objects.create(cidr=f"{ip}/{ip.max_prefixlen}", kind=IPRule.BLOCKED, automatic=True,
                              description=f"Automatic: {n} failed sign-ins within an hour",
                              expires_at=now + timedelta(minutes=minutes))
        policy.invalidate()
        LoginEvent.objects.filter(pk=event.pk).update(flags=sorted(set(event.flags or []) | {"escalated"}))
        log.warning("temporarily blocked %s after %s failed sign-ins", ip, n)
        if config.get("alerts.failed_logins") and not _throttled(f"esc:{ip}", 3600):
            _send(_admins(), event="security.failed_logins", key=f"sec:esc:{ip}:{now:%Y%m%d%H}",
                  subject="Address temporarily blocked after failed sign-ins",
                  body=f"{n} failed sign-ins within an hour. The address is blocked for {minutes} minutes.",
                  facts=_login_facts(event), link="/settings/security?view=access")


ADMIN_EVENT = {"alerts.policy_changes": "security.policy_change", "alerts.health": "security.health",
               "alerts.auth_policy": "security.auth_policy"}


def admin_event(kind_setting: str, subject: str, body: str, key: str, link: str = "/settings/security?view=access") -> None:
    """Policy/trusted-IP/temporary-access/health changes, sent to administrators."""
    if kind_setting in BY_KEY_SETTINGS and not config.get(kind_setting):
        return
    _send(_admins(), event=ADMIN_EVENT.get(kind_setting, "security.policy_change"), key=f"sec:{key}", subject=subject,
          body=body, link=link)


ACCOUNT_EVENTS = {"passkey_added", "passkey_removed", "totp_enabled", "totp_disabled", "recovery_codes", "passwordless",
                  "admin_recovery"}


def account_security(user, what: str, *, actor=None, event: str = "admin_recovery") -> None:
    """Passkey/TOTP/recovery-code/passwordless changes on an account (user + administrators for admin actions)."""
    if not config.get("alerts.account_security"):
        return
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    by_admin = actor is not None and actor.pk != user.pk
    body = f"{what} on the account '{user.username}'" + (f" by {actor.display_name}" if by_admin else "") + \
        ". If you did not expect this, contact the family administrator."
    recipients = {user} | (set(_admins()) if by_admin else set())
    _send(recipients, event=f"security.{event}" if event in ACCOUNT_EVENTS else "security.admin_recovery",
          key=f"sec:acct:{user.pk}:{stamp}", subject=f"Account security: {what}", body=body, link="/settings/account")


def account_locked(username: str, request=None) -> None:
    """The per-account failed sign-in limit was just reached: tell the person and the administrators (once per
    lock window). Never includes the attempted password."""
    from apps.accounts.models import User

    user = User.objects.filter(username=username, is_active=True).first()
    if user is None or _throttled(f"locked:{user.pk}", 900):
        return
    from apps.core import audit

    ip = audit.client_ip(request) if request is not None else ""
    facts = [("Account", user.username), ("IP address", ip or "unknown")]
    _send({user, *_admins()}, event="security.account_locked", key=f"sec:locked:{user.pk}:{timezone.now():%Y%m%d%H%M}",
          subject="Account locked after repeated failed sign-ins",
          body=f"Sign-in to the account '{user.username}' is paused for 15 minutes after {config.get('auth.login_rate_limit')} failed attempts.",
          facts=facts, link="/settings/account?tab=security")
