"""Trusted Zones, the sign-in map, recognised devices and Mark Unrecognized (Change Set T).

Visibility: everyone sees their own sign-ins, devices and map. A delegate with the *membership* scope of a family
group sees that group's members. The main administrator sees everyone. Trusted Zones are configured by the main
administrator. Full IP addresses are shown to the person themselves and to authorised administrators.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin
from apps.core import audit, config

from . import location
from .models import LoginEvent, RecognizedDevice, TrustedZone


def _err(msg, status=400, **extra):
    return Response({"error": msg, **extra}, status=status)


def visible_user_ids(user) -> set | None:
    """None = everyone (main administrator)."""
    if user.is_main_admin:
        return None
    from apps.accounts.models import Delegation, GroupMembership

    ids = {user.pk}
    for d in Delegation.objects.filter(delegate=user):
        if "membership" in (d.scopes or []):
            ids |= set(GroupMembership.objects.filter(group=d.group).values_list("user_id", flat=True))
    return ids


def zone_json(z: TrustedZone) -> dict:
    return {"id": z.id, "name": z.name, "cidrs": z.cidrs, "classification": z.classification,
            "classification_label": location.CLASS_LABELS.get(z.classification, z.classification), "description": z.description,
            "pin": {"lat": z.pin_lat, "lon": z.pin_lon, "label": z.pin_label or z.name,
                    "source": "configured Trusted Zone location"} if z.pin_lat is not None else None,
            "updated_at": z.updated_at}


def _clean_zone(d, z: TrustedZone | None = None) -> dict:
    out = {}
    if "name" in d or z is None:
        name = str(d.get("name") or "").strip()[:80]
        if not name:
            raise location.ZoneError("Give the zone a friendly name such as Home or VPN.")
        out["name"] = name
    if "cidrs" in d or z is None:
        out["cidrs"] = location.clean_cidrs(d.get("cidrs"))
    if "classification" in d:
        if d["classification"] not in TrustedZone.CLASSES:
            raise location.ZoneError("Choose Home, VPN, Office, Family or Other.")
        out["classification"] = d["classification"]
    if "description" in d:
        out["description"] = str(d["description"] or "")[:200]
    if "pin" in d:
        pin = d["pin"] or None
        if pin is None:
            out.update(pin_lat=None, pin_lon=None, pin_label="")
        else:
            try:
                lat, lon = float(pin.get("lat")), float(pin.get("lon"))
            except (TypeError, ValueError):
                raise location.ZoneError("Enter the pin as latitude and longitude (decimal degrees).") from None
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise location.ZoneError("Latitude must be −90…90 and longitude −180…180.")
            out.update(pin_lat=round(lat, 5), pin_lon=round(lon, 5), pin_label=str(pin.get("label") or "")[:80])
    return out


@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def zones(request):
    if request.method == "POST":
        try:
            values = _clean_zone(request.data)
        except location.ZoneError as exc:
            return _err(str(exc))
        if TrustedZone.objects.filter(name=values["name"]).exists():
            return _err("A zone with this name exists.")
        z = TrustedZone.objects.create(created_by=request.user, **values)
        audit.record("security.trusted_zone", request=request, change="created", zone=z.name, networks=len(z.cidrs))
        return Response(zone_json(z), status=201)
    return Response({"zones": [zone_json(z) for z in TrustedZone.objects.all()]})


@api_view(["PUT", "DELETE"])
@permission_classes([IsMainAdmin])
def zone_detail(request, pk):
    z = TrustedZone.objects.filter(pk=pk).first()
    if z is None:
        return _err("Not found.", 404)
    if request.method == "DELETE":
        name = z.name
        z.delete()
        audit.record("security.trusted_zone", request=request, change="deleted", zone=name)
        return Response(status=204)
    try:
        values = _clean_zone(request.data, z)
    except location.ZoneError as exc:
        return _err(str(exc))
    if values.get("name") and TrustedZone.objects.filter(name=values["name"]).exclude(pk=z.pk).exists():
        return _err("A zone with this name exists.")
    for k, v in values.items():
        setattr(z, k, v)
    z.save()
    audit.record("security.trusted_zone", request=request, change="changed", zone=z.name, networks=len(z.cidrs))
    return Response(zone_json(z))


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def zone_test(request):
    """Which zone (if any) an address resolves to - without sending it anywhere."""
    r = location.resolve(str(request.data.get("ip", ""))[:64])
    return Response({"network": r["network"], "location": r["location"], "zone": r.get("zone_name"),
                     "coordinates": {"lat": r.get("lat"), "lon": r.get("lon"), "source": r.get("coord_source")} if r.get("lat") is not None else None})


SOURCE_LABELS = {"zone_pin": "Configured Trusted Zone location", "geoip_city": "GeoIP (approximate)",
                 "geoip_country": "GeoIP country (approximate, country level)", "": "No map position"}


def event_json(e: LoginEvent, full_ip: bool) -> dict:
    return {"id": e.id, "at": e.at, "user": e.user.display_name if e.user_id else e.username, "user_id": str(e.user_id) if e.user_id else None,
            "result": e.result, "method": e.method, "ip": e.ip if full_ip else location.privacy_ip(e.ip, e.network),
            "network": e.network, "zone": e.zone_name, "location": e.location or e.country_name, "country": e.country,
            "lat": e.lat, "lon": e.lon, "coord_source": e.coord_source, "coord_label": SOURCE_LABELS.get(e.coord_source, ""),
            "device": " · ".join(x for x in (e.browser, e.os) if x), "recognized_device": str(e.recognized_device_id) if e.recognized_device_id else None,
            "new_device": e.new_device, "risk": e.risk or ("normal" if e.result == "success" else ""), "risk_reasons": e.risk_reasons,
            "flags": e.flags}


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def signin_map(request):
    """Sign-in history and map points within the caller's scope (one-year security retention)."""
    user = request.user
    ids = visible_user_ids(user)
    who = request.query_params.get("user") or str(user.pk)
    if who != "all":
        if ids is not None and who not in {str(i) for i in ids}:
            return _err("Not allowed.", 403)
        qs = LoginEvent.objects.filter(user_id=who)
    else:
        qs = LoginEvent.objects.all() if ids is None else LoginEvent.objects.filter(user_id__in=ids)
    try:
        days = min(max(int(request.query_params.get("days", 90)), 1), 365)
    except ValueError:
        days = 90
    qs = qs.filter(at__gte=timezone.now() - timedelta(days=days)).select_related("user")[:1000]
    events = [event_json(e, full_ip=True) for e in qs]  # own data or authorised administrator: full addresses
    people = []
    if ids is None or len(ids) > 1:
        from apps.accounts.models import User

        pq = User.objects.filter(is_active=True) if ids is None else User.objects.filter(pk__in=ids)
        people = [{"id": str(u.pk), "name": u.display_name} for u in pq.order_by("display_name")]
    return Response({"events": events, "people": people, "zones": [zone_json(z) for z in TrustedZone.objects.all()] if user.is_main_admin else
                     [{"name": z.name, "pin": zone_json(z)["pin"], "classification_label": zone_json(z)["classification_label"]} for z in TrustedZone.objects.exclude(pin_lat=None)],
                     "map": map_config(user), "retention_days": int(config.get("security.login_audit_retention_days") or 365)})


def map_config(user=None) -> dict:
    from . import mapprov

    return mapprov.public_config(user)


def device_json(d: RecognizedDevice) -> dict:
    from apps.accounts.models import UserSession

    active = UserSession.objects.filter(recognized_device=d, revoked_at__isnull=True, ended_at__isnull=True).count()
    return {"id": str(d.id), "label": d.label, "browser": d.browser, "os": d.os, "device": d.device, "first_seen": d.first_seen,
            "last_seen": d.last_seen, "last_ip": d.last_ip, "status": d.status, "active_sessions": active,
            "revoked_at": d.revoked_at}


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def devices(request):
    ids = visible_user_ids(request.user)
    who = request.query_params.get("user") or str(request.user.pk)
    if ids is not None and who not in {str(i) for i in ids}:
        return _err("Not allowed.", 403)
    current = None
    from apps.accounts.models import UserSession

    row = UserSession.objects.filter(pk=request.session.get("device")).first() if request.session.get("device") else None
    current = str(row.recognized_device_id) if row and row.recognized_device_id else None
    qs = RecognizedDevice.objects.filter(user_id=who)
    return Response({"devices": [{**device_json(d), "current": str(d.id) == current} for d in qs[:100]]})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def device_unrecognize(request, pk):
    """End the device's sessions, drop recognition and trust, audit and notify. Follow-up actions are offered,
    never executed automatically."""
    d = RecognizedDevice.objects.filter(pk=pk).select_related("user").first()
    ids = visible_user_ids(request.user)
    if d is None or (ids is not None and d.user_id not in ids):
        return _err("Not found.", 404)
    if d.revoked_at:
        return _err("This device is already marked Unrecognized.")
    from apps.accounts import sessions

    ended = sessions.revoke_device(d)
    audit.record("security.device_unrecognized", request=request, subject_user=d.user, device=d.label, sessions_ended=ended,
                 by_self=d.user_id == request.user.pk)
    from apps.notify import events

    events.notify(d.user, "security.device_unrecognized", key=f"devunrec:{d.id}", title="A device was marked Unrecognized",
                  summary=f"“{d.label}” is no longer trusted and its {ended} active session(s) were ended.",
                  facts=[("Device", d.label), ("Marked by", request.user.display_name)], link="/settings/account?tab=signins")
    return Response({"device": device_json(d), "sessions_ended": ended,
                     "next_steps": [{"key": "sign_out_others", "label": "Sign out all other sessions", "path": "/settings/account?tab=security#sessions"},
                                    {"key": "change_password", "label": "Change password", "path": "/settings/account?tab=security#password"},
                                    {"key": "passkeys", "label": "Review passkeys", "path": "/settings/account?tab=security#passkeys"},
                                    {"key": "linked", "label": "Review linked sign-in methods", "path": "/settings/account?tab=linked"},
                                    {"key": "activity", "label": "Review recent sign-ins", "path": "/settings/account?tab=signins"}]})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def map_test(request):
    """Record the result of the browser's one-tile test of the configured map provider (main administrator only).
    The browser fetches the tile itself, so the provider sees exactly what the map sends; no secret is returned."""
    from . import mapprov

    if not request.user.is_main_admin:
        return Response({"error": "Only the main administrator can test the map provider."}, status=403)
    data = mapprov.record_test(request.data.get("status"), str(request.data.get("error") or ""), actor=request.user)
    return Response({"health": data, "map": mapprov.public_config(request.user)})
