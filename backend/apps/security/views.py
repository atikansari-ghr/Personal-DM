"""Administrator API: login audit, access policy (country / IP), GeoIP and traffic analytics.

Every endpoint is restricted to the main administrator server-side.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.accounts.auth import IsMainAdmin
from apps.core import audit, config, jobs

from . import alerts, geoip, netutil, policy, traffic
from .countries import COUNTRIES, normalize
from .models import CountryRule, GeoPolicy, IPRule, LoginEvent, TemporaryCountryAccess


def _fail(msg: str, status: int = 400, **extra):
    return Response({"error": msg, **extra}, status=status)


def _dt(value):
    if not value:
        return None
    parsed = parse_datetime(value) if "T" in value else None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


# ------------------------------------------------------------------ login audit

def _event_json(e: LoginEvent) -> dict:
    return {"id": e.id, "at": e.at, "user": e.user.display_name if e.user_id and e.user else None,
            "user_id": str(e.user_id) if e.user_id else None, "username": e.username, "result": e.result,
            "method": e.method, "reason": e.reason, "ip": e.ip, "country": e.country, "country_name": e.country_name,
            "browser": e.browser, "os": e.os, "device": e.device, "totp": e.totp_used, "passkey": e.passkey_used,
            "oidc": e.oidc_used, "flags": e.flags, "session": e.correlation[:8] if e.correlation else ""}


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def logins(request):
    p = request.query_params
    qs = LoginEvent.objects.select_related("user")
    if p.get("user"):
        qs = qs.filter(user_id=p["user"])
    if p.get("username"):
        qs = qs.filter(username__icontains=p["username"][:150])
    if p.get("ip"):
        qs = qs.filter(ip__startswith=p["ip"][:64]) if not p["ip"].endswith("*") else qs.filter(ip__startswith=p["ip"][:-1])
    if p.get("country"):
        qs = qs.filter(country=p["country"].upper()[:2])
    if p.get("result"):
        qs = qs.filter(result=p["result"])
    if p.get("method"):
        qs = qs.filter(method__icontains=p["method"][:40])
    if p.get("flag"):
        qs = qs.filter(flags__contains=[p["flag"]])
    if _dt(p.get("from")):
        qs = qs.filter(at__gte=_dt(p.get("from")))
    if _dt(p.get("to")):
        qs = qs.filter(at__lte=_dt(p.get("to")))
    try:
        offset = max(0, int(p.get("offset", 0)))
    except ValueError:
        offset = 0
    now = timezone.now()
    day, week = now - timedelta(days=1), now - timedelta(days=7)
    recent = LoginEvent.objects.filter(at__gte=week)
    summary = {
        "success_24h": LoginEvent.objects.filter(at__gte=day, result="success").count(),
        "failed_24h": LoginEvent.objects.filter(at__gte=day, result__in=["failure", "denied"]).count(),
        "success_7d": recent.filter(result="success").count(),
        "failed_7d": recent.filter(result__in=["failure", "denied"]).count(),
        "new_ip_7d": recent.filter(flags__contains=["new_ip"]).count(),
        "new_country_7d": recent.filter(flags__contains=["new_country"]).count(),
        "countries": list(recent.exclude(country="").values("country", "country_name").annotate(
            success=Count("id", filter=Q(result="success")), failed=Count("id", filter=Q(result__in=["failure", "denied"])))
            .order_by("-success")[:10]),
        "methods": list(recent.filter(result="success").values("method").annotate(n=Count("id")).order_by("-n")[:10]),
        "top_failed_ips": list(recent.filter(result__in=["failure", "denied"]).exclude(ip=None).values("ip", "country")
                               .annotate(n=Count("id")).order_by("-n")[:5]),
    }
    return Response({"total": qs.count(), "events": [_event_json(e) for e in qs[offset:offset + 100]], "summary": summary,
                     "retention_days": config.get("security.login_audit_retention_days")})


# ------------------------------------------------------------------ access policy

def _rule_json(r: IPRule) -> dict:
    return {"id": r.id, "cidr": r.cidr, "kind": r.kind, "description": r.description, "enabled": r.enabled,
            "expires_at": r.expires_at, "created_at": r.created_at, "automatic": r.automatic, "live": r.live(),
            "created_by": r.created_by.display_name if r.created_by_id and r.created_by else ("automatic" if r.automatic else None)}


def _temp_json(t: TemporaryCountryAccess) -> dict:
    now = timezone.now()
    state = "active" if t.active(now) else ("scheduled" if t.starts_at > now else "expired")
    return {"id": t.id, "country": t.country, "country_name": COUNTRIES.get(t.country, t.country), "starts_at": t.starts_at,
            "ends_at": t.ends_at, "reason": t.reason, "state": state, "created_at": t.created_at,
            "created_by": t.created_by.display_name if t.created_by_id and t.created_by else None}


def _proxy_status(request) -> dict:
    peer = netutil.parse_ip(request.META.get("REMOTE_ADDR"))
    nets = netutil.trusted_networks()
    return {"trusted_proxies": [str(n) for n in nets], "peer": str(peer) if peer else None,
            "via_trusted_proxy": netutil.in_networks(peer, nets),
            "forwarded_header": bool(request.META.get("HTTP_X_FORWARDED_FOR")),
            "client_ip": netutil.client_ip(request)}


def _policy_state(request) -> dict:
    pol = GeoPolicy.get()
    snap = policy.snapshot(force=True)
    ip = netutil.client_ip_obj(request)
    decision = policy.evaluate(ip, snap)
    return {
        "policy": {"enabled": pol.enabled, "mode": pol.mode, "unknown_action": pol.unknown_action,
                   "updated_at": pol.updated_at, "updated_by": pol.updated_by.display_name if pol.updated_by_id and pol.updated_by else None,
                   "can_rollback": bool(pol.previous)},
        "allowed": sorted(snap.allowed), "blocked": sorted(snap.blocked),
        "temporary": [_temp_json(t) for t in TemporaryCountryAccess.objects.select_related("created_by")[:100]],
        "ip_rules": [_rule_json(r) for r in IPRule.objects.select_related("created_by")],
        "countries": COUNTRIES,
        "you": {"ip": str(ip) if ip else None, "allowed": decision.allowed, "reason": decision.reason,
                "country": decision.country, "country_name": decision.country_name},
        "proxy": _proxy_status(request),
        "geoip": geoip.status(),
        "emergency_disabled": os.environ.get("PD_ACCESS_POLICY_DISABLED") == "1",
    }


def _summary(pol: GeoPolicy, allowed, blocked) -> str:
    if not pol.enabled or pol.mode == "off":
        return "Geographic access control is off."
    if pol.mode == "allowlist":
        return f"Allow list: only {', '.join(sorted(allowed)) or 'no countries'} (plus trusted IPs and temporary access)."
    return f"Block list: everything except {', '.join(sorted(blocked)) or 'no countries'}."


@api_view(["GET", "PUT"])
@permission_classes([IsMainAdmin])
def access_policy(request):
    if request.method == "GET":
        return Response(_policy_state(request))
    d = request.data
    mode = d.get("mode", "off")
    if mode not in ("off", "blocklist", "allowlist"):
        return _fail("Choose a policy mode: off, block list or allow list.")
    unknown = d.get("unknown_action", "allow")
    if unknown not in ("allow", "deny"):
        return _fail("Choose allow or deny for unknown locations.")
    try:
        allowed = sorted({normalize(c) for c in d.get("allowed") or []})
        blocked = sorted({normalize(c) for c in d.get("blocked") or []})
    except ValueError as exc:
        return _fail(str(exc))
    enabled = bool(d.get("enabled")) and mode != "off"
    if enabled and mode == "allowlist" and not allowed:
        return _fail("An allow list needs at least one allowed country, otherwise everyone outside your LAN is blocked.")
    if set(allowed) & set(blocked):
        return _fail(f"A country cannot be both allowed and blocked: {', '.join(sorted(set(allowed) & set(blocked)))}.")
    base = policy.snapshot(force=True)
    proposed = policy.proposed_snapshot(base, enabled=enabled, mode=mode, unknown_action=unknown,
                                        allowed=frozenset(allowed), blocked=frozenset(blocked))
    ip = netutil.client_ip_obj(request)
    verdict = policy.evaluate(ip, proposed)
    if not verdict.allowed and not d.get("confirm_lockout"):
        return _fail(f"This policy would block your current connection ({ip}, {verdict.country_name or 'unknown location'}). "
                     "Add a trusted IP or temporary access first, or confirm if you will reconnect from an allowed location.",
                     409, code="lockout", reason=verdict.reason)
    with transaction.atomic():
        pol = GeoPolicy.objects.select_for_update().get_or_create(id=1)[0]
        pol.previous = {"enabled": pol.enabled, "mode": pol.mode, "unknown_action": pol.unknown_action,
                        "allowed": sorted(base.allowed), "blocked": sorted(base.blocked)}
        pol.enabled, pol.mode, pol.unknown_action, pol.updated_by = enabled, mode, unknown, request.user
        pol.version += 1
        pol.save()
        CountryRule.objects.exclude(kind="allow", country__in=allowed).filter(kind="allow").delete()
        CountryRule.objects.exclude(kind="block", country__in=blocked).filter(kind="block").delete()
        for c in allowed:
            CountryRule.objects.get_or_create(country=c, kind="allow", defaults={"created_by": request.user})
        for c in blocked:
            CountryRule.objects.get_or_create(country=c, kind="block", defaults={"created_by": request.user})
    policy.invalidate()
    text = _summary(pol, allowed, blocked)
    audit.record("security.policy_update", request=request, enabled=enabled, mode=mode, unknown_action=unknown,
                 allowed=allowed, blocked=blocked, lockout_confirmed=bool(d.get("confirm_lockout")))
    alerts.admin_event("alerts.policy_changes", "Access policy changed", f"{request.user.display_name} changed the access policy. {text}",
                       key=f"policy:{pol.version}")
    return Response(_policy_state(request))


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def access_policy_rollback(request):
    pol = GeoPolicy.get()
    prev = pol.previous or {}
    if not prev:
        return _fail("There is no earlier policy to restore.")
    with transaction.atomic():
        pol.enabled, pol.mode, pol.unknown_action = prev.get("enabled", False), prev.get("mode", "off"), prev.get("unknown_action", "allow")
        pol.previous, pol.updated_by = {}, request.user
        pol.version += 1
        pol.save()
        CountryRule.objects.all().delete()
        for c in prev.get("allowed", []):
            CountryRule.objects.create(country=c, kind="allow", created_by=request.user)
        for c in prev.get("blocked", []):
            CountryRule.objects.create(country=c, kind="block", created_by=request.user)
    policy.invalidate()
    audit.record("security.policy_rollback", request=request)
    alerts.admin_event("alerts.policy_changes", "Access policy restored", f"{request.user.display_name} restored the previous access policy.",
                       key=f"policy:{pol.version}")
    return Response(_policy_state(request))


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def access_policy_test(request):
    ip = netutil.parse_ip(str(request.data.get("ip") or ""))
    if ip is None:
        return _fail("Enter a valid IPv4 or IPv6 address.")
    decision = policy.evaluate(ip, policy.snapshot(force=True))
    return Response({"ip": str(ip), "allowed": decision.allowed, "reason": decision.reason, "country": decision.country,
                     "country_name": decision.country_name, "rule": decision.rule})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def temporary_access(request):
    d = request.data
    try:
        country = normalize(d.get("country", ""))
    except ValueError as exc:
        return _fail(str(exc))
    starts, ends = _dt(d.get("starts_at")) or timezone.now(), _dt(d.get("ends_at"))
    reason = (d.get("reason") or "").strip()[:200]
    if ends is None or ends <= starts:
        return _fail("The end must be after the start.")
    if ends - starts > timedelta(days=366):
        return _fail("Temporary access can last at most one year.")
    if not reason:
        return _fail("Enter a reason, e.g. 'Family trip to Türkiye'.")
    row = TemporaryCountryAccess.objects.create(country=country, starts_at=starts, ends_at=ends, reason=reason, created_by=request.user)
    policy.invalidate()
    audit.record("security.temporary_access_create", request=request, target=row, country=country,
                 starts_at=starts.isoformat(), ends_at=ends.isoformat())
    alerts.admin_event("alerts.policy_changes", "Temporary country access created",
                       f"{request.user.display_name} allowed {COUNTRIES[country]} from {timezone.localtime(starts):%Y-%m-%d %H:%M} "
                       f"to {timezone.localtime(ends):%Y-%m-%d %H:%M} ({reason}).", key=f"temp:{row.pk}")
    return Response(_temp_json(row), status=201)


@api_view(["DELETE"])
@permission_classes([IsMainAdmin])
def temporary_access_detail(request, pk):
    row = get_object_or_404(TemporaryCountryAccess, pk=pk)
    row.delete()
    policy.invalidate()
    audit.record("security.temporary_access_delete", request=request, target_type="temporarycountryaccess", target_id=str(pk),
                 country=row.country)
    alerts.admin_event("alerts.policy_changes", "Temporary country access removed",
                       f"{request.user.display_name} removed temporary access for {row.country} ({row.reason}).", key=f"temp_del:{pk}")
    return Response(status=204)


def _lockout_by_block(request, cidr_net) -> bool:
    ip = netutil.client_ip_obj(request)
    return ip is not None and ip.version == cidr_net.version and ip in cidr_net


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def ip_rules(request):
    d = request.data
    kind = d.get("kind")
    if kind not in ("trusted", "blocked"):
        return _fail("Choose trusted or blocked.")
    try:
        net = netutil.parse_network(str(d.get("cidr") or ""))
    except ValueError as exc:
        return _fail(str(exc))
    if net.num_addresses > 2 ** 24 and net.version == 4 and kind == "trusted":
        return _fail("Trusted ranges larger than /8 are not allowed.")
    expires = _dt(d.get("expires_at")) if d.get("expires_at") else None
    if expires is not None and expires <= timezone.now():
        return _fail("The expiry must be in the future.")
    description = (d.get("description") or "").strip()[:200]
    if kind == "blocked" and not description:
        return _fail("Enter a reason for the block.")
    if kind == "blocked" and _lockout_by_block(request, net) and not d.get("confirm_lockout"):
        return _fail(f"{net} includes your current address; you would lose access.", 409, code="lockout")
    row = IPRule.objects.create(cidr=str(net), kind=kind, description=description, expires_at=expires, created_by=request.user)
    policy.invalidate()
    audit.record("security.ip_rule_create", request=request, target=row, cidr=str(net), kind=kind)
    alerts.admin_event("alerts.policy_changes", f"{'Trusted' if kind == 'trusted' else 'Blocked'} IP added",
                       f"{request.user.display_name} added {kind} {net}" + (f" ({description})" if description else "") + ".",
                       key=f"iprule:{row.pk}")
    return Response(_rule_json(row), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsMainAdmin])
def ip_rule_detail(request, pk):
    row = get_object_or_404(IPRule, pk=pk)
    if request.method == "DELETE":
        row.delete()
        policy.invalidate()
        audit.record("security.ip_rule_delete", request=request, target_type="iprule", target_id=str(pk), cidr=row.cidr, kind=row.kind)
        alerts.admin_event("alerts.policy_changes", "IP rule removed", f"{request.user.display_name} removed {row.kind} {row.cidr}.",
                           key=f"iprule_del:{pk}")
        return Response(status=204)
    d = request.data
    if "enabled" in d:
        if row.kind == "blocked" and d["enabled"] and _lockout_by_block(request, netutil.parse_network(row.cidr)) and not d.get("confirm_lockout"):
            return _fail(f"{row.cidr} includes your current address; you would lose access.", 409, code="lockout")
        row.enabled = bool(d["enabled"])
    if "description" in d:
        row.description = (d.get("description") or "").strip()[:200]
    if "expires_at" in d:
        row.expires_at = _dt(d["expires_at"]) if d["expires_at"] else None
    row.save()
    policy.invalidate()
    audit.record("security.ip_rule_update", request=request, target=row, fields=list(d.keys()))
    alerts.admin_event("alerts.policy_changes", "IP rule changed", f"{request.user.display_name} changed {row.kind} {row.cidr}.",
                       key=f"iprule_upd:{pk}:{timezone.now():%Y%m%d%H%M%S}")
    return Response(_rule_json(row))


# ------------------------------------------------------------------ GeoIP

@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def geoip_api(request):
    if request.method == "POST":
        action = request.data.get("action")
        if action == "update":
            if not config.is_set("geoip.license_key") or not config.get("geoip.account_id"):
                return _fail("Enter the MaxMind account ID and license key first.")
            job = jobs.enqueue("geoip_update", {}, max_attempts=1, idempotency_key=f"geoip:manual:{timezone.now():%Y%m%d%H%M}")
            audit.record("security.geoip_update_requested", request=request)
            return Response({"status": "queued", "job": str(job.id) if job else None, "geoip": geoip.status()})
        if action == "lookup":
            ip = netutil.parse_ip(str(request.data.get("ip") or ""))
            if ip is None:
                return _fail("Enter a valid IP address.")
            found = geoip.lookup(ip)
            return Response({"ip": str(ip), "country": found[0] if found else None, "country_name": found[1] if found else None,
                             "internal": netutil.is_internal(ip)})
        return _fail("Unknown action.")
    return Response(geoip.status())


@api_view(["POST"])
@permission_classes([IsMainAdmin])
@parser_classes([MultiPartParser])
def geoip_upload(request):
    f = request.FILES.get("file")
    if f is None or f.size > 200 * 1024 * 1024:
        return _fail("Choose a .mmdb database file (at most 200 MB).")
    with tempfile.NamedTemporaryFile(suffix=".mmdb", delete=False) as fh:
        for chunk in f.chunks():
            fh.write(chunk)
        tmp = Path(fh.name)
    try:
        result = geoip.install_file(tmp)
    except geoip.GeoIPError as exc:
        return _fail(str(exc))
    finally:
        tmp.unlink(missing_ok=True)
    policy.invalidate()
    audit.record("security.geoip_upload", request=request, database_type=result["database_type"])
    return Response(geoip.status())


# ------------------------------------------------------------------ traffic analytics

@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def traffic_api(request):
    if request.method == "POST":
        job = jobs.enqueue("goaccess_report", {}, max_attempts=1, idempotency_key=f"goaccess:manual:{timezone.now():%Y%m%d%H%M}")
        return Response({"status": "queued", "job": str(job.id) if job else None})
    return Response({"enabled": bool(config.get("goaccess.enabled")), "status": traffic.status(),
                     "summary": traffic.read_summary(), "blocked": traffic.blocked_stats()})


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def traffic_html(request):
    path = traffic.report_dir() / "report.html"
    if not path.exists():
        raise Http404
    audit.record("security.traffic_report_download", request=request)
    resp = FileResponse(open(path, "rb"), content_type="text/html", as_attachment=True, filename="goaccess-report.html")
    resp["Content-Security-Policy"] = "sandbox"
    return resp
