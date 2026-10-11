"""Where a sign-in came from: Trusted Zones first, then local GeoIP for public addresses only (Change Set T).

Resolution order (never sends an address to an outside service):
1. the source address matches a configured **Trusted Zone** -> its friendly name ("Home"); a configured map pin is
   labelled "configured Trusted Zone location", never "GeoIP";
2. another private/local address -> "Private network" (not the misleading "Unknown country");
3. a public address -> the local MaxMind database: City databases give approximate coordinates, Country databases
   only the country (a rough country-level point is shown on the map and labelled as such).

Risk classification is explainable and never blocks a sign-in on GeoIP alone (GeoIP is approximate).
"""
from __future__ import annotations

import ipaddress
import math
from datetime import timedelta

from django.utils import timezone

from . import geoip, netutil

# Rough country-level map points (latitude, longitude) for public addresses when only a Country database is installed.
# Approximate by design; the UI says "approximate, country level".
COUNTRY_POINTS = {
    "AE": (24.0, 54.0), "AF": (33.9, 67.7), "AR": (-34.6, -64.0), "AT": (47.5, 14.6), "AU": (-25.3, 133.8), "BD": (23.7, 90.4),
    "BE": (50.5, 4.5), "BG": (42.7, 25.5), "BH": (26.0, 50.6), "BR": (-14.2, -51.9), "CA": (56.1, -106.3), "CH": (46.8, 8.2),
    "CL": (-35.7, -71.5), "CN": (35.9, 104.2), "CO": (4.6, -74.3), "CZ": (49.8, 15.5), "DE": (51.2, 10.5), "DK": (56.3, 9.5),
    "DZ": (28.0, 1.7), "EG": (26.8, 30.8), "ES": (40.5, -3.7), "ET": (9.1, 40.5), "FI": (61.9, 25.7), "FR": (46.2, 2.2),
    "GB": (54.0, -2.0), "GR": (39.1, 21.8), "HK": (22.3, 114.2), "HU": (47.2, 19.5), "ID": (-0.8, 113.9), "IE": (53.4, -8.2),
    "IL": (31.0, 34.9), "IN": (20.6, 78.9), "IQ": (33.2, 43.7), "IR": (32.4, 53.7), "IT": (41.9, 12.6), "JO": (30.6, 36.2),
    "JP": (36.2, 138.3), "KE": (-0.0, 37.9), "KR": (35.9, 127.8), "KW": (29.3, 47.5), "LB": (33.9, 35.9), "LK": (7.9, 80.8),
    "MA": (31.8, -7.1), "MX": (23.6, -102.6), "MY": (4.2, 101.9), "NG": (9.1, 8.7), "NL": (52.1, 5.3), "NO": (60.5, 8.5),
    "NP": (28.4, 84.1), "NZ": (-40.9, 174.9), "OM": (21.5, 55.9), "PH": (12.9, 121.8), "PK": (30.4, 69.3), "PL": (51.9, 19.1),
    "PT": (39.4, -8.2), "QA": (25.4, 51.2), "RO": (45.9, 25.0), "RS": (44.0, 21.0), "RU": (61.5, 105.3), "SA": (23.9, 45.1),
    "SD": (12.9, 30.2), "SE": (60.1, 18.6), "SG": (1.35, 103.8), "SY": (34.8, 39.0), "TH": (15.9, 100.9), "TN": (33.9, 9.5),
    "TR": (39.0, 35.2), "TW": (23.7, 121.0), "UA": (48.4, 31.2), "US": (39.8, -98.6), "VN": (14.1, 108.3), "YE": (15.6, 48.5),
    "ZA": (-30.6, 22.9),
}
CLASS_LABELS = {"home": "Home", "vpn": "VPN", "office": "Office", "family": "Family", "other": "Trusted network"}


class ZoneError(ValueError):
    pass


def clean_cidrs(values) -> list[str]:
    if isinstance(values, str):
        values = [v for v in values.replace(",", "\n").splitlines()]
    out = []
    for v in values or []:
        v = str(v).strip()
        if not v:
            continue
        try:
            net = ipaddress.ip_network(v, strict=False)
        except ValueError:
            raise ZoneError(f"“{v}” is not an IPv4/IPv6 network. Use CIDR notation such as 192.168.2.0/24 or fd00:1::/64.") from None
        if net.prefixlen == 0:
            raise ZoneError("A Trusted Zone cannot cover every address (/0).")
        out.append(str(net))
    if not out:
        raise ZoneError("Add at least one network (CIDR).")
    if len(out) > 32:
        raise ZoneError("At most 32 networks per zone.")
    return sorted(set(out), key=out.index)


def match_zone(ip):
    """Most specific matching network wins (longest prefix), ties by zone id: deterministic."""
    from .models import TrustedZone

    if isinstance(ip, str):
        ip = netutil.parse_ip(ip)
    if ip is None:
        return None
    best = None
    for z in TrustedZone.objects.all().order_by("id"):
        for c in z.cidrs or []:
            try:
                net = ipaddress.ip_network(c, strict=False)
            except ValueError:
                continue
            if net.version == ip.version and ip in net and (best is None or net.prefixlen > best[0]):
                best = (net.prefixlen, z)
    return best[1] if best else None


def geo_detail(ip) -> dict | None:
    """Local GeoIP only. City databases add approximate coordinates."""
    if isinstance(ip, str):
        ip = netutil.parse_ip(ip)
    if ip is None or netutil.is_internal(ip):
        return None
    reader = geoip._open()
    if reader is None:
        return None
    try:
        rec = reader.get(str(ip)) or {}
    except Exception:  # noqa: BLE001
        return None
    country = rec.get("country") or rec.get("registered_country") or {}
    code = (country.get("iso_code") or "").upper()
    if not code:
        return None
    out = {"country": code, "country_name": (country.get("names") or {}).get("en", code)}
    loc = rec.get("location") or {}
    if loc.get("latitude") is not None:
        out.update(lat=float(loc["latitude"]), lon=float(loc["longitude"]), source="geoip_city",
                   accuracy_km=loc.get("accuracy_radius"), city=((rec.get("city") or {}).get("names") or {}).get("en", ""))
    elif code in COUNTRY_POINTS:
        out.update(lat=COUNTRY_POINTS[code][0], lon=COUNTRY_POINTS[code][1], source="geoip_country", accuracy_km=None, city="")
    return out


def resolve(ip_text: str | None) -> dict:
    ip = netutil.parse_ip(ip_text) if ip_text else None
    if ip is None:
        return {"network": "unknown", "location": "Unknown", "country": "", "country_name": ""}
    zone = match_zone(ip)
    if zone is not None:
        out = {"network": "trusted_zone", "zone": zone, "zone_name": zone.name, "location": zone.name, "country": "", "country_name": ""}
        if zone.pin_lat is not None and zone.pin_lon is not None:
            out.update(lat=zone.pin_lat, lon=zone.pin_lon, coord_source="zone_pin")
        return out
    if netutil.is_internal(ip):
        return {"network": "private", "location": "Private network", "country": "", "country_name": ""}
    g = geo_detail(ip)
    if g is None:
        return {"network": "public", "location": "Unknown location (no GeoIP data)", "country": "", "country_name": ""}
    place = ", ".join(x for x in (g.get("city"), g["country_name"]) if x)
    out = {"network": "public", "location": f"{place} (approximate)", "country": g["country"], "country_name": g["country_name"]}
    if "lat" in g:
        out.update(lat=g["lat"], lon=g["lon"], coord_source=g["source"])
    return out


def privacy_ip(ip_text: str | None, network: str) -> str:
    """Routine notifications: private addresses are shortened, public ones replaced by a hint; the full address is
    under View Security Details in the app."""
    ip = netutil.parse_ip(ip_text) if ip_text else None
    if ip is None:
        return "unknown"
    if network in ("trusted_zone", "private"):
        if ip.version == 4:
            parts = str(ip).split(".")
            return f"{parts[0]}.{parts[1]}.x.{parts[3]}"
        return str(ip).split(":")[0] + ":…"
    return "public address (see Security details in the app)"


def _km(a, b) -> float:
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


IMPOSSIBLE_KMH = 900  # faster than an airliner between two sign-ins


def classify(event, *, previous=None) -> tuple[str, list[str]]:
    """normal | low | warning | high, with plain-language reasons. Informational only: nothing is blocked here."""
    from .models import LoginEvent

    reasons = []
    level = 0  # 0 normal, 1 low, 2 warning, 3 high
    known_device = event.recognized_device_id is not None and not event.new_device
    zone = event.network == "trusted_zone"
    if zone:
        reasons.append(f"From the Trusted Zone “{event.zone_name}”")
    elif event.network == "private":
        reasons.append("From a private network that is not a configured Trusted Zone")
        level = max(level, 1)
    if known_device:
        reasons.append("Recognised device")
    else:
        reasons.append("New or unrecognised device")
        level = max(level, 1 if zone else 2)
    flags = set(event.flags or [])
    if "new_country" in flags:
        reasons.append(f"First sign-in from {event.country_name or event.country} (GeoIP, approximate)")
        level = max(level, 2)
    elif "new_ip" in flags and not zone:
        reasons.append("New public address")
        level = max(level, 1)
    if event.passkey_used or event.totp_used or event.oidc_used:
        reasons.append("Signed in with " + ("a passkey" if event.passkey_used else "an authenticator code" if event.totp_used else "single sign-on"))
    elif level >= 2:
        reasons.append("Password only")
    prev = previous
    if prev is None and event.user_id:
        prev = (LoginEvent.objects.filter(user_id=event.user_id, result=LoginEvent.SUCCESS, lat__isnull=False)
                .exclude(pk=event.pk).exclude(coord_source="geoip_country").order_by("-at").first())
    if prev is not None and event.lat is not None and prev.lat is not None and event.coord_source == "geoip_city" \
            and prev.coord_source in ("geoip_city", "zone_pin"):
        hours = max((event.at - prev.at).total_seconds() / 3600, 0.01)
        km = _km((prev.lat, prev.lon), (event.lat, event.lon))
        if km > 500 and km / hours > IMPOSSIBLE_KMH:
            reasons.append(f"Unusual travel: about {int(km)} km from the previous sign-in in {hours:.1f} h (GeoIP is approximate)")
            level = 3
    return ("normal", "low", "warning", "high")[level], reasons


def recent_window():
    return timezone.now() - timedelta(days=365)
