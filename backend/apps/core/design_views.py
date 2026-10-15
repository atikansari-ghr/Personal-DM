"""Sign-in design administration (main administrator) and the public design images (Change Set W)."""
from __future__ import annotations

from django.http import FileResponse, Http404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.auth import IsMainAdmin

from . import audit, branding, config, designs, rotation
from .models import SigninDesign


def _err(msg, status=400):
    return Response({"error": msg}, status=status)


def _listing():
    designs.ensure_builtins()
    active = designs.active()
    prev = config.get(designs.PREVIOUS)
    rows = [designs.design_json(d, active_id=active.pk, previous_id=prev) for d in SigninDesign.objects.all()]
    rows.sort(key=lambda r: (not r["builtin"], r["builtin_key"] != designs.DEFAULT_KEY, r["name"].lower()))
    return {"designs": rows, "active": active.pk, "previous": prev, "rotation": rotation.status(),
            "limits": {"wallpaper_mb": branding.LIMITS["wallpaper"][0] // (1024 * 1024),
                       "logo_mb": branding.LIMITS["logo"][0] // (1024 * 1024)}}


@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def design_list(request):
    if request.method == "GET":
        return Response(_listing())
    src = None
    if request.data.get("from"):
        src = SigninDesign.objects.filter(pk=request.data["from"]).first()
        if src is None:
            return _err("That design does not exist.", 404)
    try:
        d = designs.create(name=request.data.get("name", ""), template=request.data.get("template") or designs.DEFAULT_KEY,
                           source=src, actor=request.user)
    except designs.DesignError as exc:
        return _err(str(exc))
    audit.record("settings.signin_design_create", request=request, target_type="signin_design", target_id=str(d.pk),
                 design=d.name, source=src.name if src else "")
    return Response(designs.design_json(d, active_id=designs.active().pk), status=201)


def _get(pk):
    d = SigninDesign.objects.filter(pk=pk).first()
    if d is None:
        raise Http404
    return d


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsMainAdmin])
def design_detail(request, pk):
    d = _get(pk)
    if request.method == "GET":
        return Response(designs.design_json(d, active_id=designs.active().pk, previous_id=config.get(designs.PREVIOUS)))
    try:
        if request.method == "DELETE":
            res = designs.delete(d, actor=request.user)
            return Response({**res, **_listing()})
        designs.update(d, request.data, actor=request.user)
    except designs.DesignError as exc:
        return _err(str(exc))
    audit.record("settings.signin_design_update", request=request, target_type="signin_design", target_id=str(d.pk),
                 design=d.name, fields=sorted(k for k in request.data if k != "overrides"))
    return Response(designs.design_json(d, active_id=designs.active().pk))


@api_view(["POST", "DELETE"])
@permission_classes([IsMainAdmin])
def design_file(request, pk, kind):
    d = _get(pk)
    if kind not in ("wallpaper", "logo"):
        raise Http404
    try:
        if request.method == "DELETE":
            designs.remove_wallpaper(d) if kind == "wallpaper" else designs.set_logo(d, None)
        else:
            f = request.FILES.get("file")
            if f is None:
                return _err("Choose an image file.")
            if f.size > branding.LIMITS[kind][0]:
                return _err(f"The image is larger than {branding.LIMITS[kind][0] // (1024 * 1024)} MB.")
            data = f.read()
            designs.set_wallpaper(d, data, actor=request.user) if kind == "wallpaper" else designs.set_logo(d, data)
    except (designs.DesignError, branding.BrandingError) as exc:
        return _err(str(exc))
    audit.record(f"settings.signin_design_{kind}", request=request, target_type="signin_design", target_id=str(d.pk),
                 design=d.name, change="removed" if request.method == "DELETE" else "uploaded")
    d.refresh_from_db()
    return Response(designs.design_json(d, active_id=designs.active().pk))


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def design_activate(request, pk):
    d = _get(pk)
    try:
        designs.activate(d, actor=request.user)
    except designs.DesignError as exc:
        return _err(str(exc))
    return Response(_listing())


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def design_revert(request):
    try:
        designs.revert(actor=request.user)
    except designs.DesignError as exc:
        return _err(str(exc))
    return Response(_listing())


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def design_reset(request):
    designs.activate(designs.default_design(), actor=request.user, reason="reset to default")
    return Response(_listing())


@api_view(["GET", "PUT"])
@permission_classes([IsMainAdmin])
def design_rotation(request):
    if request.method == "PUT":
        try:
            rotation.configure(request.data, actor=request.user)
        except rotation.RotationError as exc:
            return _err(str(exc))
    return Response(rotation.status())


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def design_rotation_preview(request):
    return Response(rotation.preview())


@api_view(["GET"])
@permission_classes([AllowAny])
def design_asset(request, pk, variant):
    """Images of the active design are public (the sign-in page shows them before sign-in). Other designs' images
    are only for the main administrator's previews. Files are addressed by design and variant, never by name."""
    d = SigninDesign.objects.filter(pk=pk).first()
    if d is None:
        raise Http404
    if d.pk != designs.active().pk and not IsMainAdmin().has_permission(request, None):
        raise Http404
    path = designs.asset_path(d, variant)
    if path is None:
        raise Http404
    resp = FileResponse(open(path, "rb"), content_type="image/webp")
    resp["Cache-Control"] = "public, max-age=604800" if d.pk == designs.active().pk else "private, max-age=600"
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Content-Disposition"] = "inline"
    return resp
