"""Security alerts through the existing notification system (in-app, email, Telegram).

Each alert type has its own on/off setting (alerts.*). Alerts are throttled per type and subject so an attack
cannot produce thousands of messages, and never contain passwords, codes, tokens or document contents.
Failed-login escalation: many failures from one address within an hour add a temporary automatic block.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.core import config, ratelimit

log = logging.getLogger("personaldocs.security")


def _admins():
    from apps.accounts.models import User

    return User.objects.filter(is_main_admin=True, is_active=True)


def _throttled(bucket: str, window_seconds: int) -> bool:
    if ratelimit.too_many(f"alert:{bucket}", 1, window_seconds):
        return True
    ratelimit.hit(f"alert:{bucket}")
    return False


def _send(users, *, kind: str, key: str, subject: str, body: str, link: str = "/settings/activity?view=logins"):
    from apps.notify.events import _send as send

    app = config.get("general.app_name")
    for u in users:
        send(u, kind=kind, key=f"{key}:{u.pk}", subject=subject, body=body, link=link,
             external_subject=f"{app}: {subject}", external_body=f"{body}\n\nReview: {settings.PUBLIC_ORIGIN}{link}")


def _where(event) -> str:
    place = event.country_name or "unknown location"
    return f"{event.ip or 'unknown address'} ({place})"


def on_login_event(event) -> None:
    from .models import LoginEvent

    stamp = timezone.now().strftime("%Y%m%d%H")
    if event.result in (LoginEvent.FAILURE, LoginEvent.DENIED):
        _check_escalation(event)
        if config.get("alerts.failed_logins") and event.username:
            since = timezone.now() - timedelta(hours=1)
            n = LoginEvent.objects.filter(username=event.username, result=LoginEvent.FAILURE, at__gte=since).count()
            if n >= int(config.get("auth.login_rate_limit")) and not _throttled(f"failed:{event.username}", 3600):
                _send(_admins(), kind="security", key=f"sec:failed:{event.username}:{stamp}",
                      subject="Repeated failed sign-ins",
                      body=f"{n} failed sign-in attempts for the account '{event.username}' in the last hour, latest from {_where(event)}.")
        return
    if event.result != LoginEvent.SUCCESS or event.user is None:
        return
    flags = set(event.flags or [])
    who = event.user.display_name or event.user.username
    if "new_country" in flags and config.get("alerts.new_country") and not _throttled(f"newc:{event.user_id}:{event.country}", 86400):
        _send({event.user, *_admins()}, kind="security", key=f"sec:newc:{event.id}",
              subject="Sign-in from a new country",
              body=f"{who} signed in from {_where(event)} for the first time ({event.method}). If this was not expected, change the password and sign out other devices.")
    elif "new_ip" in flags and config.get("alerts.new_ip") and not _throttled(f"newip:{event.user_id}:{event.ip}", 86400):
        _send({event.user, *_admins()}, kind="security", key=f"sec:newip:{event.id}",
              subject="Sign-in from a new address",
              body=f"{who} signed in from a new address {_where(event)} ({event.method}).")
    if "policy_exception" in flags and config.get("alerts.policy_exception") and not _throttled(f"exc:{event.user_id}", 3600):
        _send(_admins(), kind="security", key=f"sec:exc:{event.id}",
              subject="Sign-in allowed by temporary country access",
              body=f"{who} signed in from {_where(event)}, which is only allowed by a temporary travel exception.")


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
            _send(_admins(), kind="security", key=f"sec:esc:{ip}:{now:%Y%m%d%H}",
                  subject="Address temporarily blocked after failed sign-ins",
                  body=f"{n} failed sign-ins from {_where(event)} within an hour. The address is blocked for {minutes} minutes.",
                  link="/settings/security")


def admin_event(kind_setting: str, subject: str, body: str, key: str, link: str = "/settings/security") -> None:
    """Policy/trusted-IP/temporary-access/health changes, sent to administrators."""
    if not config.get(kind_setting):
        return
    _send(_admins(), kind="security", key=f"sec:{key}", subject=subject, body=body, link=link)


def account_security(user, what: str, *, actor=None) -> None:
    """Passkey/TOTP/recovery-code/passwordless changes on an account (user + administrators for admin actions)."""
    if not config.get("alerts.account_security"):
        return
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    by_admin = actor is not None and actor.pk != user.pk
    body = f"{what} on the account '{user.username}'" + (f" by {actor.display_name}" if by_admin else "") + \
        ". If you did not expect this, contact the family administrator."
    recipients = {user} | (set(_admins()) if by_admin else set())
    _send(recipients, kind="security", key=f"sec:acct:{user.pk}:{stamp}", subject=f"Account security: {what}",
          body=body, link="/settings/account")
