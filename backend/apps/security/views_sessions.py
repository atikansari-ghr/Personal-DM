"""Security → Active Sessions (Change Set AB): list, details and Terminate Session.

Administrators see the sessions within their scope (the main administrator: everyone; a scoped administrator: the
members delegated to them), other people only their own (My account → Sessions). Only the main administrator can
terminate someone's session. No cookie, session key or token is ever part of a response.
"""
from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsAdministrator, IsMainAdmin
from apps.accounts.models import UserSession

from . import active_sessions as AS


def _err(msg, status=400, **extra):
    return Response({"error": msg, **extra}, status=status)


@api_view(["GET"])
@permission_classes([IsAdministrator])
def sessions(request):
    q = request.query_params
    filters = {k: q.get(k) for k in ("state", "user", "trust", "risk", "device", "location") if q.get(k)}
    data = AS.listing(request.user, current=request.session.get("device"), filters=filters)
    people = {}
    for r in AS.listing(request.user, current=None)["sessions"] if filters else data["sessions"]:
        people[r["user"]["id"]] = r["user"]["name"]
    return Response({**data, "can_terminate": bool(request.user.is_main_admin),
                     "users": [{"id": k, "name": v} for k, v in sorted(people.items(), key=lambda kv: kv[1])]})


@api_view(["GET"])
@permission_classes([IsAdministrator])
def summary(request):
    return Response(AS.summary(request.user, current=request.session.get("device")))


def _visible_row(request, pk):
    s = AS.visible(request.user).filter(pk=pk).first()
    if s is None:
        return None, None
    data = AS.listing(request.user, current=request.session.get("device"))
    return s, next((r for r in data["sessions"] if r["id"] == str(pk)), None)


@api_view(["GET"])
@permission_classes([IsAdministrator])
def session_detail(request, pk):
    s, row = _visible_row(request, pk)
    if s is None:
        return _err("Not found.", 404)
    return Response({**row, "can_terminate": bool(request.user.is_main_admin) and not row["current"]})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def terminate(request, pk):
    """End one session on the server (not Mark Unrecognized: the device stays recognised)."""
    s = UserSession.objects.filter(pk=pk, revoked_at__isnull=True, ended_at__isnull=True).select_related("user").first()
    if s is None:
        return _err("This session has already ended.", 404)
    if request.data.get("confirm") is not True:
        return _err("Confirm that you want to end this session.", code="confirm_required")
    if str(s.id) == request.session.get("device"):
        return _err("This is your current session. Use Sign out instead.")
    AS.terminate(s, actor=request.user, request=request)
    return Response({"terminated": str(s.id), "user": s.user.display_name})
