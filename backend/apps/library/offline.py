"""Offline copies scoped by user + device + folder/document (Change Set S).

The server keeps, per account, the devices (browsers or installed apps) that hold offline copies and what was chosen
on each of them: whole folders (with or without subfolders) or single documents. It never stores anything about
the files' contents here. At every sync the device sends what it holds and receives the authoritative list of what
it may hold *now*, computed with the same permission engine as browsing (download capability). Anything no longer
permitted, removed, archived, quarantined or deselected is listed for removal; newer versions are listed for update.

What the server cannot do: erase files from a device that stays completely offline. Such a device removes them at
its next sync, or locks them after ``offline.max_days_without_sync`` days without one (enforced by the app on the
device; see docs/guides/offline-export.md).
"""
from __future__ import annotations

import hashlib

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin
from apps.core import audit, config

from . import permissions as P
from .models import Document, Folder, OfflineDevice, OfflineSelection

MAX_ITEMS = 5000


def policy() -> dict:
    return {
        "enabled": bool(config.get("offline.enabled")),
        "auto_update": bool(config.get("offline.auto_update")),
        "cache_text": bool(config.get("offline.cache_text")),
        "logout_policy": config.get("offline.logout_policy"),
        "max_days_without_sync": int(config.get("offline.max_days_without_sync")),
        "device_quota_mb": int(config.get("offline.device_quota_mb")),
        "large_download_mb": int(config.get("offline.large_download_mb")),
    }


def allowed_for(user) -> tuple[bool, str]:
    if not config.get("offline.enabled"):
        return False, "Offline copies are turned off by the administrator."
    if not getattr(user, "offline_allowed", True):
        return False, "The administrator has turned off offline copies for your account."
    return True, ""


def _device(request, device_id) -> OfflineDevice:
    return get_object_or_404(OfflineDevice, pk=device_id, user=request.user)


def _subtree(ctx: P.AccessContext, root_id, recursive: bool) -> list:
    if not recursive:
        return [root_id]
    children: dict = {}
    for fid, node in ctx.folders.items():
        children.setdefault(node.parent_id, []).append(fid)
    out, frontier = [root_id], [root_id]
    while frontier and len(out) < 100000:
        nxt = [c for f in frontier for c in children.get(f, [])]
        out += nxt
        frontier = nxt
    return out


def _relpath(ctx: P.AccessContext, root_id, folder_id) -> str:
    """Folder path from the selected folder down (ancestors above it are not revealed)."""
    parts, node = [], ctx.folders.get(folder_id)
    for _ in range(256):
        if node is None:
            break
        parts.append(node.name)
        if node.id == root_id:
            break
        node = ctx.folders.get(node.parent_id)
    return " / ".join(reversed(parts))


def _docs_for_selection(ctx: P.AccessContext, sel: OfflineSelection):
    """Documents of one selection the user may download now (current version present, not quarantined)."""
    qs = ctx.documents(P.DOWNLOAD).select_related("current_version")
    if sel.document_id:
        qs = qs.filter(pk=sel.document_id)
    else:
        if not ctx.folder_caps(sel.folder_id) & P.VIEW:
            # Lost access to the folder itself: documents shared individually inside it are not reached through
            # this selection either (the person would not see the folder to choose it).
            return Document.objects.none()
        qs = qs.filter(folder_id__in=_subtree(ctx, sel.folder_id, sel.recursive))
    return qs.filter(current_version__isnull=False)


def _text_hash(v) -> str | None:
    t = v.text or ""
    return hashlib.sha256(t.encode("utf-8", "replace")).hexdigest()[:20] if t.strip() else None


def _selection_row(ctx, sel: OfflineSelection) -> dict:
    if sel.folder_id:
        ok = bool(ctx.folder_caps(sel.folder_id) & P.VIEW)
        node = ctx.folders.get(sel.folder_id)
        name = node.name if ok and node else "Folder no longer available"
        return {"id": sel.id, "kind": "folder", "folder": str(sel.folder_id), "recursive": sel.recursive, "name": name,
                "available": ok, "created_at": sel.created_at}
    doc = Document.objects.filter(pk=sel.document_id).first()
    ok = bool(doc and doc.archived_at is None and ctx.doc_caps(doc) & P.DOWNLOAD)
    return {"id": sel.id, "kind": "document", "document": str(sel.document_id), "name": doc.title if ok else "Document no longer available",
            "available": ok, "created_at": sel.created_at}


def _estimate(ctx, *, folder=None, recursive=True, document=None) -> dict:
    if document is not None:
        docs = ctx.documents(P.DOWNLOAD).filter(pk=document.pk, current_version__isnull=False).select_related("current_version")
        subfolders = 0
    else:
        ids = _subtree(ctx, folder.id, recursive)
        docs = ctx.documents(P.DOWNLOAD).filter(folder_id__in=ids, current_version__isnull=False).select_related("current_version")
        subfolders = len([i for i in ids[1:] if ctx.folder_caps(i) & P.VIEW])
    count = blocked = size = 0
    for d in docs:
        if d.current_version.av_blocked:
            blocked += 1
            continue
        count += 1
        size += d.current_version.size or 0
    visible = ctx.documents(P.VIEW).filter(folder_id__in=_subtree(ctx, folder.id, recursive)).count() if folder else count
    return {"documents": count, "subfolders": subfolders, "bytes": size, "blocked": blocked,
            "not_downloadable": max(0, visible - count - blocked)}


# ------------------------------------------------------------------ devices

@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def devices(request):
    """GET: my devices. POST: register this device (or refresh a known one)."""
    if request.method == "GET":
        rows = OfflineDevice.objects.filter(user=request.user)
        return Response({"devices": [_device_row(d) for d in rows], "policy": policy()})
    d = request.data
    label = str(d.get("label") or "This device")[:80]
    platform = str(d.get("platform") or "")[:80]
    existing = OfflineDevice.objects.filter(pk=d.get("device_id"), user=request.user).first() if d.get("device_id") else None
    if existing:
        existing.platform = platform or existing.platform
        existing.installed_app = bool(d.get("installed_app"))
        existing.save(update_fields=["platform", "installed_app"])
        dev = existing
    else:
        dev = OfflineDevice.objects.create(user=request.user, label=label, platform=platform, installed_app=bool(d.get("installed_app")))
        audit.record("offline.device_registered", request=request, target_type="offline_device", target_id=str(dev.id))
    ok, reason = allowed_for(request.user)
    return Response({"device": _device_row(dev), "allowed": ok, "reason": reason, "policy": policy()})


def _device_row(d: OfflineDevice) -> dict:
    return {"id": str(d.id), "label": d.label, "platform": d.platform, "installed_app": d.installed_app,
            "created_at": d.created_at, "last_sync_at": d.last_sync_at, "items": d.reported_items, "bytes": d.reported_bytes,
            "failures": d.reported_failures, "selections": d.selections.count(), "wipe_pending": d.wipe_requested_at is not None}


@api_view(["PATCH", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def device_detail(request, pk):
    dev = _device(request, pk)
    if request.method == "DELETE":
        # Forget the device: its selections go; the device itself removes its copies when it next syncs (unknown id).
        dev.delete()
        audit.record("offline.device_removed", request=request, target_type="offline_device", target_id=str(pk))
        return Response(status=204)
    report = request.data.get("report")
    if isinstance(report, dict):  # counts after a sync finished (no titles or content)
        dev.reported_items = max(0, int(report.get("items") or 0))
        dev.reported_bytes = max(0, int(report.get("bytes") or 0))
        dev.reported_failures = max(0, int(report.get("failures") or 0))
        dev.save(update_fields=["reported_items", "reported_bytes", "reported_failures"])
        return Response(_device_row(dev))
    label = str(request.data.get("label") or "").strip()[:80]
    if not label:
        return Response({"error": "Enter a name for this device."}, status=400)
    dev.label = label
    dev.save(update_fields=["label"])
    return Response(_device_row(dev))


# ------------------------------------------------------------------ selections

@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def estimate(request):
    """Count and size of what a folder (with or without subfolders) or document would put on this device."""
    ctx = P.context_for(request)
    q = request.query_params
    if q.get("document"):
        doc = Document.objects.filter(pk=q["document"]).first()
        if not doc or not ctx.doc_caps(doc) & P.VIEW:
            return Response({"error": "Not found"}, status=404)
        if not ctx.doc_caps(doc) & P.DOWNLOAD:
            return Response({"error": "You do not have download permission for this document."}, status=403)
        out = _estimate(ctx, document=doc)
    else:
        folder = Folder.objects.filter(pk=q.get("folder")).first() if q.get("folder") else None
        if not folder or not ctx.folder_caps(folder.id) & P.VIEW:
            return Response({"error": "Not found"}, status=404)
        out = _estimate(ctx, folder=folder, recursive=q.get("recursive", "1") not in ("0", "false"))
    pol = policy()
    out.update(quota_bytes=pol["device_quota_mb"] * 1024 * 1024, large_bytes=pol["large_download_mb"] * 1024 * 1024)
    return Response(out)


@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def selections(request):
    ctx = P.context_for(request)
    if request.method == "GET":
        dev = _device(request, request.query_params.get("device"))
        return Response({"selections": [_selection_row(ctx, s) for s in dev.selections.all().order_by("created_at")]})
    d = request.data
    dev = _device(request, d.get("device"))
    ok, reason = allowed_for(request.user)
    if not ok:
        return Response({"error": reason}, status=403)
    if d.get("document"):
        doc = Document.objects.filter(pk=d["document"]).first()
        if not doc or not ctx.doc_caps(doc) & P.VIEW:
            return Response({"error": "Not found"}, status=404)
        if not ctx.doc_caps(doc) & P.DOWNLOAD:
            return Response({"error": "You do not have download permission for this document."}, status=403)
        sel, _ = OfflineSelection.objects.get_or_create(device=dev, document=doc)
        target = doc
    elif d.get("folder"):
        folder = Folder.objects.filter(pk=d["folder"]).first()
        if not folder or not ctx.folder_caps(folder.id) & P.VIEW:
            return Response({"error": "Not found"}, status=404)
        try:
            sel, created = OfflineSelection.objects.get_or_create(device=dev, folder=folder, defaults={"recursive": bool(d.get("recursive", True))})
        except IntegrityError:
            return Response({"error": "Already selected"}, status=409)
        if not created and sel.recursive != bool(d.get("recursive", True)):
            sel.recursive = bool(d.get("recursive", True))
            sel.save(update_fields=["recursive"])
        target = folder
    else:
        return Response({"error": "Choose a folder or a document."}, status=400)
    audit.record("offline.select", request=request, target=target, device=str(dev.id),
                 recursive=sel.recursive if sel.folder_id else None)
    return Response(_selection_row(ctx, sel), status=201)


@api_view(["DELETE"])
@permission_classes([IsActiveAuthenticated])
def selection_detail(request, pk):
    sel = get_object_or_404(OfflineSelection, pk=pk, device__user=request.user)
    audit.record("offline.unselect", request=request, target_type="folder" if sel.folder_id else "document",
                 target_id=str(sel.folder_id or sel.document_id), device=str(sel.device_id))
    sel.delete()
    return Response(status=204)


# ------------------------------------------------------------------ sync

@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def sync(request):
    """The device reports what it holds; the server answers with what it may hold now.

    Request: {device, have: [{document, version, text}], report: {items, bytes, failures}}
    Response: {known_device, allowed, reason, wipe, policy, selections, items, remove, server_time}
    """
    d = request.data
    have = {str(h.get("document")): h for h in (d.get("have") or [])[:MAX_ITEMS] if isinstance(h, dict)}
    dev = OfflineDevice.objects.filter(pk=d.get("device"), user=request.user).first() if d.get("device") else None
    now = timezone.now()
    if dev is None:
        # Unknown or forgotten device: everything it holds for this account is removed.
        return Response({"known_device": False, "allowed": False, "reason": "This device is no longer registered for offline copies.",
                         "wipe": True, "policy": policy(), "selections": [], "items": [], "remove": list(have), "server_time": now})
    ok, reason = allowed_for(request.user)
    wipe = dev.wipe_requested_at is not None
    report = d.get("report") or {}
    dev.last_sync_at = now
    dev.reported_items = max(0, int(report.get("items") or 0))
    dev.reported_bytes = max(0, int(report.get("bytes") or 0))
    dev.reported_failures = max(0, int(report.get("failures") or 0))
    if wipe:
        dev.wipe_requested_at = None
        audit.record("offline.device_wiped", request=request, target_type="offline_device", target_id=str(dev.id))
    dev.save(update_fields=["last_sync_at", "reported_items", "reported_bytes", "reported_failures", "wipe_requested_at"])
    pol = policy()
    if not ok or wipe:
        return Response({"known_device": True, "allowed": ok, "reason": reason or "The administrator removed offline copies from this device.",
                         "wipe": True, "policy": pol, "selections": [], "items": [], "remove": list(have), "server_time": now})
    ctx = P.context_for(request)
    sels = list(dev.selections.all().order_by("created_at"))
    items: dict = {}
    for sel in sels:
        root = sel.folder_id
        for doc in _docs_for_selection(ctx, sel)[:MAX_ITEMS]:
            v = doc.current_version
            if v.av_blocked:
                continue
            key = str(doc.id)
            if key in items:
                items[key]["selections"].append(sel.id)
                continue
            if len(items) >= MAX_ITEMS:
                break
            items[key] = {"document": key, "version": str(v.id), "version_number": v.number, "title": doc.title,
                          "name": v.original_name, "mime": v.mime, "size": v.size or 0, "folder": str(doc.folder_id),
                          "path": _relpath(ctx, root, doc.folder_id) if root else "", "selections": [sel.id],
                          "text": _text_hash(v) if pol["cache_text"] else None}
    remove = [k for k in have if k not in items]
    return Response({"known_device": True, "allowed": True, "reason": "", "wipe": False, "policy": pol,
                     "selections": [_selection_row(ctx, s) for s in sels], "items": list(items.values()), "remove": remove,
                     "server_time": now})


# ------------------------------------------------------------------ administrator

@api_view(["GET"])
@permission_classes([IsMainAdmin])
def admin_overview(request):
    from apps.accounts.models import User

    users = []
    for u in User.objects.filter(is_active=True).order_by("sort_order", "display_name"):
        devs = list(OfflineDevice.objects.filter(user=u))
        users.append({"id": str(u.id), "display_name": u.display_name, "offline_allowed": u.offline_allowed,
                      "devices": [_device_row(x) for x in devs]})
    return Response({"policy": policy(), "users": users})


@api_view(["PATCH"])
@permission_classes([IsMainAdmin])
def admin_user(request, pk):
    from apps.accounts.models import User

    u = get_object_or_404(User, pk=pk)
    allowed = bool(request.data.get("offline_allowed"))
    if u.offline_allowed != allowed:
        u.offline_allowed = allowed
        u.save(update_fields=["offline_allowed"])
        audit.record("offline.capability_changed", request=request, target=u, subject_user=u, allowed=allowed)
    return Response({"id": str(u.id), "offline_allowed": u.offline_allowed})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def admin_device_wipe(request, pk):
    dev = get_object_or_404(OfflineDevice, pk=pk)
    dev.wipe_requested_at = timezone.now()
    dev.save(update_fields=["wipe_requested_at"])
    dev.selections.all().delete()
    audit.record("offline.device_wipe_requested", request=request, target_type="offline_device", target_id=str(dev.id),
                 subject_user=dev.user)
    return Response({"status": "requested", "device": _device_row(dev)})
