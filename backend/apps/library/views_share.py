"""External share links: high-entropy, expiring, optional password, revocable, pinned to a version."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated
from apps.core import audit, config, crypto, ratelimit

from . import permissions as P
from . import storage
from .models import ShareLink
from .views import _ctx, _err, _stream, get_doc

MAX_DAYS = 90


def _share_json(s: ShareLink, token: str | None = None) -> dict:
    now = timezone.now()
    status = "revoked" if s.revoked_at else ("expired" if s.expires_at <= now else "active")
    data = {"id": str(s.id), "version": s.version.number, "expires_at": s.expires_at, "status": status,
            "has_password": bool(s.password_hash), "allow_download": s.allow_download, "hint": s.token_hint,
            "created_at": s.created_at, "access_count": s.access_count, "created_by": s.created_by.display_name}
    if token:
        from django.conf import settings

        data["url"] = f"{settings.PUBLIC_ORIGIN}/s/{token}"
    return data


@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def document_shares(request, pk):
    doc = get_doc(request, pk, P.SHARE)
    if request.method == "POST":
        try:
            days = int(request.data.get("days", 7))
        except (TypeError, ValueError):
            days = 7
        if days < 1 or days > MAX_DAYS:
            return _err(f"Links can last between 1 and {MAX_DAYS} days.")
        if not doc.current_version:
            return _err("Nothing to share yet.")
        password = request.data.get("password") or ""
        if password and len(password) < 6:
            return _err("Share passwords need at least 6 characters.")
        token = crypto.token_urlsafe(32)
        s = ShareLink.objects.create(document=doc, version=doc.current_version, token_hash=crypto.hash_token(token),
                                     token_hint=token[:4], password_hash=make_password(password) if password else "",
                                     allow_download=bool(request.data.get("allow_download", True)),
                                     expires_at=timezone.now() + timedelta(days=days), created_by=request.user)
        audit.record("share.create", request=request, target=doc, subject_user=doc.owner, days=days, password=None,
                     protected=bool(password))
        return Response(_share_json(s, token), status=201)
    return Response({"shares": [_share_json(s) for s in doc.share_links.select_related("version", "created_by").order_by("-created_at")]})


@api_view(["DELETE"])
@permission_classes([IsActiveAuthenticated])
def share_revoke(request, sid):
    s = get_object_or_404(ShareLink.objects.select_related("document"), pk=sid)
    get_doc(request, s.document_id, P.SHARE)
    if s.revoked_at is None:
        s.revoked_at = timezone.now()
        s.save(update_fields=["revoked_at"])
        audit.record("share.revoke", request=request, target=s.document)
    return Response(_share_json(s))


# ------------------------------------------------------------------ public side (no login)

def _lookup(token: str) -> ShareLink | None:
    if not token or len(token) > 100:
        return None
    s = ShareLink.objects.select_related("document", "document__owner", "version", "created_by").filter(
        token_hash=crypto.hash_token(token)).first()
    if s is None:
        return None
    doc = s.document
    now = timezone.now()
    if s.revoked_at or s.expires_at <= now or doc.archived_at or not doc.owner.is_active:
        return None
    # The creator must still hold share permission on the document.
    if not s.created_by.is_active or not P.AccessContext.build(s.created_by).can(doc, P.SHARE):
        return None
    return s


def _session_key(s):
    return f"share_ok:{s.id}"


@csrf_protect
@require_http_methods(["GET", "POST"])
def public_share(request, token):
    s = _lookup(token)
    ip = audit.client_ip(request) or "unknown"
    if s is None:
        audit.record("share.access", request=request, outcome="failure", actor_label="public", reason="invalid_or_expired")
        return HttpResponse(render_to_string("share_unavailable.html", {"app": config.get("general.app_name")}), status=404)
    error = ""
    if s.password_hash and not request.session.get(_session_key(s)):
        if request.method == "POST":
            bucket = f"sharepw:{s.id}:{ip}"
            if ratelimit.too_many(bucket, 5, 900) or ratelimit.too_many(f"sharepw:{s.id}", 30, 3600):
                error = "Too many attempts. Try again later."
                audit.record("share.password", request=request, outcome="denied", target=s.document, actor_label="public")
            elif check_password(request.POST.get("password", ""), s.password_hash):
                request.session[_session_key(s)] = True
                ratelimit.clear(bucket)
            else:
                ratelimit.hit(bucket)
                ratelimit.hit(f"sharepw:{s.id}")
                error = "Incorrect password."
                audit.record("share.password", request=request, outcome="failure", target=s.document, actor_label="public")
        if not request.session.get(_session_key(s)):
            return HttpResponse(render_to_string("share_password.html", {"error": error, "app": config.get("general.app_name"),
                                                                         "csrf": _csrf(request)}, request=request))
    ShareLink.objects.filter(pk=s.pk).update(access_count=s.access_count + 1, last_access_at=timezone.now())
    audit.record("share.access", request=request, target=s.document, actor_label="public", subject_user=s.document.owner)
    v = s.version
    return HttpResponse(render_to_string("share_view.html", {
        "app": config.get("general.app_name"), "title": s.document.title, "token": token, "name": v.original_name,
        "size": v.size, "expires": s.expires_at, "allow_download": s.allow_download,
        "previewable": bool(v.searchable_path or v.preview_path or v.mime in ("application/pdf", "image/png", "image/jpeg")),
    }))


def _csrf(request):
    from django.middleware.csrf import get_token

    return get_token(request)


@require_http_methods(["GET"])
def public_share_file(request, token):
    s = _lookup(token)
    if s is None or (s.password_hash and not request.session.get(_session_key(s))):
        raise Http404
    v = s.version
    if v.av_blocked:
        raise Http404  # quarantined files are never served through share links
    download = request.GET.get("download") == "1"
    if download and not s.allow_download:
        raise Http404
    if not download and (v.searchable_path or v.preview_path):
        path, ctype, name = storage.resolve_derivative(v.searchable_path or v.preview_path), "application/pdf", f"{s.document.title}.pdf"
    else:
        path = storage.resolve_original(v.storage_path)
        ctype = v.mime if v.mime in ("application/pdf", "image/png", "image/jpeg") and not download else "application/octet-stream"
        name = v.original_name
    if download:
        audit.record("share.download", request=request, target=s.document, actor_label="public", subject_user=s.document.owner)
    return _stream(request, path, ctype, name, "attachment" if download else "inline")
