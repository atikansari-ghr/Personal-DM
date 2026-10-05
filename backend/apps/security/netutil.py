"""Real client IP behind Nginx Proxy Manager / Pangolin.

Forwarded headers are only believed when the TCP peer is a trusted proxy (PD_TRUSTED_PROXY_IPS: addresses or
CIDR ranges). X-Forwarded-For is read from the right: each hop appends the address it received the request
from, so the rightmost address that is not itself a trusted proxy is the real client. Entries further left
were supplied by the client and can be forged, so they are never used. Without a trusted peer the socket
address is used as is.
"""
from __future__ import annotations

import ipaddress
from functools import lru_cache

from django.conf import settings

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_ip(value: str | None):
    if not value:
        return None
    value = value.strip().strip('"')
    if value.startswith("[") and "]" in value:  # [v6]:port
        value = value[1:value.index("]")]
    elif value.count(":") == 1 and "." in value:  # v4:port
        value = value.split(":")[0]
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip


def parse_network(value: str) -> Network:
    """Validate an address or CIDR ("203.0.113.7", "10.0.0.0/8", "2001:db8::/32")."""
    try:
        return ipaddress.ip_network(value.strip(), strict=False)
    except ValueError as exc:
        raise ValueError(f"'{value}' is not a valid IP address or CIDR range") from exc


@lru_cache(maxsize=8)
def _trusted(spec: tuple[str, ...]) -> tuple[Network, ...]:
    nets = []
    for item in spec:
        try:
            nets.append(parse_network(item))
        except ValueError:
            continue
    return tuple(nets)


def trusted_networks() -> tuple[Network, ...]:
    return _trusted(tuple(getattr(settings, "TRUSTED_PROXY_IPS", ()) or ()))


def in_networks(ip, nets) -> bool:
    return ip is not None and any(ip.version == n.version and ip in n for n in nets)


def is_internal(ip) -> bool:
    """Loopback, private (RFC 1918 / ULA) and link-local: LAN clients, the proxy itself, health checks."""
    return ip is not None and (ip.is_loopback or ip.is_private or ip.is_link_local)


def client_ip_obj(request):
    if request is None:
        return None
    meta = request.META
    peer = parse_ip(meta.get("REMOTE_ADDR"))
    nets = trusted_networks()
    if peer is None or not in_networks(peer, nets):
        return peer
    forwarded = [parse_ip(p) for p in (meta.get("HTTP_X_FORWARDED_FOR") or "").split(",") if p.strip()]
    if not forwarded:
        real = parse_ip(meta.get("HTTP_X_REAL_IP"))
        return real or peer
    if any(f is None for f in forwarded):
        # A malformed entry: trust nothing to its left.
        forwarded = forwarded[len(forwarded) - forwarded[::-1].index(None):]
        if not forwarded:
            return peer
    for hop in reversed(forwarded):
        if not in_networks(hop, nets):
            return hop
    return forwarded[0]


def client_ip(request) -> str | None:
    ip = client_ip_obj(request)
    return str(ip) if ip is not None else None


def proxy_diagnostics(recent_ips: list[str]) -> list[str]:
    """Hints for `doctor` when every visitor seems to come from the proxy/LXC address."""
    hints = []
    nets = trusted_networks()
    distinct = {i for i in recent_ips if i}
    if distinct and len(distinct) == 1:
        only = parse_ip(next(iter(distinct)))
        if only is not None and is_internal(only) and len(recent_ips) >= 5:
            if in_networks(only, nets):
                hints.append(f"All recent sign-ins come from {only}, which is a trusted proxy: the proxy may not send X-Forwarded-For.")
            else:
                hints.append(f"All recent sign-ins come from {only}: add the proxy's address to PD_TRUSTED_PROXY_IPS so real client IPs are used.")
    return hints
