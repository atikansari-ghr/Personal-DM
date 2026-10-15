"""Sign-in page branding API: public images for the sign-in page; uploads and removal for the main administrator."""
from __future__ import annotations

from django.http import FileResponse, Http404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.auth import IsMainAdmin

from . import audit, branding


def _serve(kind: str):
    """Old addresses (before Change Set W): the active design's wallpaper / the shared logo."""
    from . import designs

    path = None
    if kind == "wallpaper":
        d = designs.active()
        path = designs.asset_path(d, "desktop") if d.assets.get("original") else None
    if path is None and kind == "logo":
        path = branding.path_for(kind)
    if path is None:
        raise Http404
    resp = FileResponse(open(path, "rb"), content_type="image/webp")
    resp["Cache-Control"] = "public, max-age=604800"  # the URL carries a version, so a new upload is fetched at once
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Content-Disposition"] = "inline"
    return resp


LEGACY = "custom-wallpaper-upload"


def _legacy_design(create: bool):
    """The single "Custom wallpaper" of the previous release, now a named design (compatibility for old clients)."""
    from .models import SigninDesign

    d = SigninDesign.objects.filter(migrated_from__in=(LEGACY, "login.wallpaper_file")).order_by("id").first()
    if d is None and create:
        d = SigninDesign.objects.create(name="Custom wallpaper", template="minimal", migrated_from=LEGACY)
    return d


def _change(request, kind: str):
    from . import designs

    if request.method == "DELETE":
        if kind == "wallpaper":
            d = _legacy_design(False)
            if d is not None:
                designs.delete(d, actor=request.user)
            branding.clear(kind, actor=request.user)
        else:
            branding.clear(kind, actor=request.user)
        audit.record(f"settings.login_{kind}_remove", request=request)
        return Response(branding.public())
    f = request.FILES.get("file")
    if f is None:
        return Response({"error": "Choose an image file."}, status=400)
    if f.size > branding.LIMITS[kind][0]:
        return Response({"error": f"The image is larger than {branding.LIMITS[kind][0] // (1024 * 1024)} MB."}, status=400)
    data = f.read()
    try:
        if kind == "wallpaper":
            branding.process(kind, data)
            d = _legacy_design(True)
            designs.set_wallpaper(d, data, actor=request.user)
            if request.data.get("use", "true") != "false":
                designs.activate(d, actor=request.user)
        else:
            branding.save(kind, data, actor=request.user)
    except (branding.BrandingError, designs.DesignError) as exc:
        return Response({"error": str(exc)}, status=400)
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
