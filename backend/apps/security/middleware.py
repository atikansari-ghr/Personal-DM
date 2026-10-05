"""Pre-authentication access policy enforcement (country / IP rules).

Runs before sessions, CSRF and authentication, so a denied request never reaches login or document code.
The decision is attached to the request (request.access_decision) for the login audit.
"""
from __future__ import annotations

import logging

from django.db import DatabaseError
from django.db.models import F
from django.http import HttpResponse
from django.utils import timezone

from . import netutil, policy

log = logging.getLogger("personaldocs.security")

DENIED_HTML = (
    "<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
    "<title>Access not allowed</title></head><body style='font-family:system-ui;margin:3rem;max-width:40rem'>"
    "<h1>Access not allowed</h1><p>This service is not available from your network or location.</p>"
    "<p>If you are a member of this family and are travelling, ask the administrator for temporary access.</p>"
    "</body></html>"
)


def _count(decision) -> None:
    from .models import BlockedStat

    try:
        day = timezone.localdate()
        n = BlockedStat.objects.filter(day=day, reason=decision.reason, country=decision.country).update(count=F("count") + 1)
        if not n:
            BlockedStat.objects.get_or_create(day=day, reason=decision.reason, country=decision.country, defaults={"count": 1})
    except DatabaseError:
        pass


class AccessPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            ip = netutil.client_ip_obj(request)
            decision = policy.evaluate(ip, policy.snapshot(), path=request.path)
        except DatabaseError:
            # Database unavailable (e.g. during migrations): the app will fail on its own; do not mask it.
            return self.get_response(request)
        request.access_decision = decision
        if decision.allowed:
            return self.get_response(request)
        _count(decision)
        log.info("access denied ip=%s reason=%s country=%s", ip, decision.reason, decision.country or "-")
        if request.path.startswith("/api/"):
            return HttpResponse('{"error": "Access from your network or location is not allowed."}', status=403,
                                content_type="application/json")
        return HttpResponse(DENIED_HTML, status=403, content_type="text/html; charset=utf-8")
