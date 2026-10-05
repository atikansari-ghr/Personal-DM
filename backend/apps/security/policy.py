"""Geographic / IP access policy evaluation (deterministic precedence, see docs/guides/security-access.md).

Precedence, first match wins:
  0. Emergency switch PD_ACCESS_POLICY_DISABLED=1 (server environment)  -> allow
  1. Health endpoint /api/health (proxy health checks)                   -> allow
  2. Internal addresses (loopback, private LAN, link-local)              -> allow
  3. Explicit blocked IP/CIDR (enabled, not expired)                     -> deny
  4. Trusted IP/CIDR (enabled, not expired)                              -> allow
  5. Geographic policy disabled or mode "off"                            -> allow
  6. Country unknown (no GeoIP data)                                     -> policy.unknown_action
  7. Active temporary country access for the country                     -> allow (flagged as exception)
  8. Block list: country blocked -> deny, else allow
     Allow list: country allowed -> allow, else deny
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from django.utils import timezone

from . import geoip, netutil

CACHE_SECONDS = 15
_cache = {"at": 0.0, "snap": None}


@dataclass
class Snapshot:
    enabled: bool = False
    mode: str = "off"
    unknown_action: str = "allow"
    allowed: frozenset = frozenset()
    blocked: frozenset = frozenset()
    temporary: tuple = ()  # (country, starts_at, ends_at, id)
    trusted: tuple = ()  # (network, id)
    blocked_ips: tuple = ()
    version: int = 0


@dataclass
class Decision:
    allowed: bool
    reason: str
    country: str = ""
    country_name: str = ""
    rule: str = ""
    exception: bool = False
    flags: list = field(default_factory=list)


def _nets(rows):
    out = []
    for r in rows:
        try:
            out.append((netutil.parse_network(r.cidr), r.pk, r.expires_at))
        except ValueError:
            continue
    return tuple(out)


def load_snapshot() -> Snapshot:
    from .models import CountryRule, GeoPolicy, IPRule, TemporaryCountryAccess

    now = timezone.now()
    pol = GeoPolicy.get()
    rules = list(CountryRule.objects.all())
    ips = [r for r in IPRule.objects.filter(enabled=True) if r.live(now)]
    temps = tuple((t.country, t.starts_at, t.ends_at, t.pk) for t in TemporaryCountryAccess.objects.filter(ends_at__gt=now))
    return Snapshot(
        enabled=pol.enabled, mode=pol.mode, unknown_action=pol.unknown_action, version=pol.version,
        allowed=frozenset(r.country for r in rules if r.kind == "allow"),
        blocked=frozenset(r.country for r in rules if r.kind == "block"),
        temporary=temps,
        trusted=_nets([r for r in ips if r.kind == "trusted"]),
        blocked_ips=_nets([r for r in ips if r.kind == "blocked"]),
    )


def snapshot(force: bool = False) -> Snapshot:
    now = time.monotonic()
    if force or _cache["snap"] is None or now - _cache["at"] > CACHE_SECONDS:
        _cache.update(snap=load_snapshot(), at=now)
    return _cache["snap"]


def invalidate() -> None:
    _cache.update(snap=None, at=0.0)


def _match(ip, nets, now):
    for net, pk, expires in nets:
        if (expires is None or expires > now) and ip.version == net.version and ip in net:
            return net, pk
    return None


def evaluate(ip, snap: Snapshot, *, path: str = "", now=None) -> Decision:
    now = now or timezone.now()
    if os.environ.get("PD_ACCESS_POLICY_DISABLED") == "1":
        return Decision(True, "emergency_disabled")
    if path == "/api/health":
        return Decision(True, "health_check")
    if isinstance(ip, str):
        ip = netutil.parse_ip(ip)
    if ip is None:
        return Decision(True, "no_address")
    if netutil.is_internal(ip):
        return Decision(True, "internal")
    hit = _match(ip, snap.blocked_ips, now)
    if hit:
        return Decision(False, "ip_blocked", rule=str(hit[0]))
    hit = _match(ip, snap.trusted, now)
    if hit:
        return Decision(True, "ip_trusted", rule=str(hit[0]))
    if not snap.enabled or snap.mode == "off":
        return Decision(True, "policy_off")
    found = geoip.lookup(ip)
    if not found:
        return Decision(snap.unknown_action == "allow", "country_unknown")
    code, name = found
    for country, start, end, pk in snap.temporary:
        if country == code and start <= now < end:
            return Decision(True, "temporary_access", code, name, rule=f"temporary:{pk}", exception=True, flags=["policy_exception"])
    if snap.mode == "blocklist":
        if code in snap.blocked:
            return Decision(False, "country_blocked", code, name)
        return Decision(True, "country_not_blocked", code, name)
    if code in snap.allowed:
        return Decision(True, "country_allowed", code, name)
    return Decision(False, "country_not_allowed", code, name)


def proposed_snapshot(base: Snapshot, **changes) -> Snapshot:
    data = {**base.__dict__, **changes}
    return Snapshot(**data)
