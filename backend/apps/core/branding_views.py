"""Sign-in page branding API: public images for the sign-in page; uploads and removal for the main administrator."""
from __future__ import annotations

from django.http import FileResponse, Http404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.auth import IsMainAdmin

from . import audit, branding


def _serve(kind: str):
    path = branding.path_for(kind)
    if path is None:
        raise Http404
    resp = FileResponse(open(path, "rb"), content_type="image/webp")
    resp["Cache-Control"] = "public, max-age=604800"  # the URL carries a version, so a new upload is fetched at once
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Content-Disposition"] = "inline"
    return resp


def _change(request, kind: str):
    if request.method == "DELETE":
        branding.clear(kind, actor=request.user)
        audit.record(f"settings.login_{kind}_remove", request=request)
        return Response(branding.public())
    f = request.FILES.get("file")
    if f is None:
        return Response({"error": "Choose an image file."}, status=400)
    if f.size > branding.LIMITS[kind][0]:
        return Response({"error": f"The image is larger than {branding.LIMITS[kind][0] // (1024 * 1024)} MB."}, status=400)
    try:
        branding.save(kind, f.read(), actor=request.user)
    except branding.BrandingError as exc:
        return Response({"error": str(exc)}, status=400)
    if kind == "wallpaper" and request.data.get("use", "true") != "false":
        from . import config

        config.set_value("login.design", "custom", actor=request.user)
    audit.record(f"settings.login_{kind}_update", request=request)
    return Response(branding.public())


@api_view(["GET", "POST", "DELETE"])
@permission_classes([AllowAny])
def wallpaper(request):
    if request.method == "GET":
        return _serve("wallpaper")
    if not IsMainAdmin().has_permission(request, None):
        return Response({"error": "Only the main administrator can change the sign-in page."}, status=403)
    return _change(request, "wallpaper")


@api_view(["GET", "POST", "DELETE"])
@permission_classes([AllowAny])
def logo(request):
    if request.method == "GET":
        return _serve("logo")
    if not IsMainAdmin().has_permission(request, None):
        return Response({"error": "Only the main administrator can change the sign-in page."}, status=403)
    return _change(request, "logo")


@api_view(["GET"])
@permission_classes([AllowAny])
def login_branding(request):
    return Response(branding.public())
