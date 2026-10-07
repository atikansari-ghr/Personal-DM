"""Folders, documents, versions, fields, files, permissions, search and dashboard API."""
from __future__ import annotations

import mimetypes
import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Sum
from django.http import FileResponse, Http404, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin
from apps.accounts.models import FamilyGroup, User
from apps.core import audit, config
from apps.notify import events

from . import permissions as P
from . import search as searchlib
from . import services as S
from . import storage
from . import doctypes
from .models import (AccessRule, Correspondent, CustomFieldDef, Document, DocumentField, DocumentType, DocumentVersion, Folder,
                     DocumentHistory, SavedView, Tag)
from .serializers import document_detail, document_row, field_json, folder_json, user_mini, version_json


def _err(msg, status=400, **extra):
    return Response({"error": msg, **extra}, status=status)


def _ctx(request) -> P.AccessContext:
    return P.context_for(request)


def get_doc(request, pk, cap=P.VIEW, include_archived=False) -> Document:
    """Fetch a document or 404. Inaccessible and non-existent ids are indistinguishable."""
    ctx = _ctx(request)
    try:
        doc = Document.objects.select_related("owner", "doc_type", "correspondent", "folder", "current_version").get(pk=pk)
    except (Document.DoesNotExist, ValueError, Exception):
        raise Http404
    if doc.archived_at and not (include_archived and ctx.is_admin):
        raise Http404
    caps = ctx.doc_caps(doc)
    if not caps & P.VIEW:
        raise Http404
    if not caps & cap:
        raise PermissionDenied("You do not have permission for this action.")
    return doc


def get_folder(request, pk, cap=P.VIEW) -> Folder:
    ctx = _ctx(request)
    try:
        folder = Folder.objects.get(pk=pk)
    except Exception:
        raise Http404
    caps = ctx.folder_caps(folder.id)
    if not caps & P.VIEW:
        raise Http404
    if not caps & cap:
        raise PermissionDenied("You do not have permission for this action.")
    return folder


# ------------------------------------------------------------------ folders

@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def folders(request):
    ctx = _ctx(request)
    if request.method == "POST":
        parent = get_folder(request, request.data.get("parent"), P.ORGANIZE)
        try:
            f = S.create_folder(actor=request.user, parent=parent, name=request.data.get("name", ""),
                                emoji=request.data.get("emoji") or None)
        except S.DomainError as exc:
            return _err(str(exc))
        audit.record("folder.create", request=request, target=f)
        ctx._cache.clear()
        ctx.folders[f.id] = P._FolderNode(f.id, f.parent_id, True, False, f.owner_id, f.name)
        return Response(folder_json(ctx, f), status=201)
    include_archived = request.query_params.get("archived") == "1" and ctx.is_admin
    qs = Folder.objects.all() if include_archived else Folder.objects.filter(archived_at__isnull=True)
    qs = qs.select_related("owner")
    visible = ctx.folder_ids_with(P.VIEW) if not ctx.is_admin else set(qs.values_list("id", flat=True))
    by_id = {f.id: f for f in qs}
    # include ancestors as path-only nodes so the tree renders
    needed = set()
    for fid in visible:
        node = by_id.get(fid)
        while node is not None and node.parent_id is not None and node.parent_id not in visible:
            needed.add(node.parent_id)
            node = by_id.get(node.parent_id)
    counts = dict(ctx.documents(P.VIEW).values("folder_id").annotate(n=Count("id")).values_list("folder_id", "n"))
    out = [folder_json(ctx, by_id[i], counts) for i in visible if i in by_id]
    out += [folder_json(ctx, by_id[i], None, path_only=True) for i in needed if i in by_id]
    return Response({"folders": sorted(out, key=lambda f: (f["parent"] or "", f["name"].lower()))})


@api_view(["GET", "PATCH"])
@permission_classes([IsActiveAuthenticated])
def folder_detail(request, pk):
    ctx = _ctx(request)
    folder = get_folder(request, pk)
    if request.method == "GET":
        data = folder_json(ctx, folder)
        data["path"] = [{"id": str(f.id), "name": f.name, "emoji": f.emoji} for f in S.folder_path(folder)
                        if ctx.folder_caps(f.id) & P.VIEW or f.parent_id is None]
        return Response(data)
    caps = ctx.folder_caps(folder.id)
    d = request.data
    try:
        with transaction.atomic():  # a refused move also undoes a rename sent in the same request
            if "name" in d and d["name"] != folder.name:
                if not caps & P.ORGANIZE:
                    raise PermissionDenied("You cannot rename this folder.")
                name = (d["name"] or "").strip()
                if not name or "/" in name or len(name) > 200:
                    return _err("Enter a valid folder name.")
                if Folder.objects.filter(parent=folder.parent, name=name, archived_at__isnull=True).exclude(pk=folder.pk).exists():
                    return _err("A folder with this name already exists here.")
                folder.name = name
                if not folder.emoji_is_custom:
                    folder.emoji = S.default_emoji(name, folder.parent)
            if "emoji" in d:
                if not caps & P.ORGANIZE:
                    raise PermissionDenied("You cannot change this folder's icon.")
                if folder.parent_id is None or folder.kind != Folder.NORMAL:
                    return _err("The icon of a person's or the family's main area cannot be changed.")
                emoji = (d["emoji"] or "").strip()  # "" = reset to the default icon
                if emoji and emoji not in S.APPROVED_ICONS:
                    return _err("Choose an icon from the list.")
                folder.emoji = emoji or S.default_emoji(folder.name, folder.parent)
                folder.emoji_is_custom = bool(emoji)
            if "inherit_permissions" in d:
                if not caps & P.MANAGE:
                    raise PermissionDenied("You cannot change permission inheritance here.")
                folder.inherit_permissions = bool(d["inherit_permissions"])
            if "suggested_type" in d:  # only a suggestion for uploads; documents already here are not changed
                if not caps & P.ORGANIZE:
                    raise PermissionDenied("You cannot change this folder's suggested type.")
                st = d["suggested_type"]
                folder.suggested_type = (DocumentType.objects.filter(pk=st, archived=False).first()
                                         if str(st or "").isdigit() else None)
                if st and folder.suggested_type is None:
                    return _err("Choose an active document type.")
            folder.save()
            if d.get("parent") and str(folder.parent_id) != str(d["parent"]):
                new_parent = get_folder(request, d["parent"])
                S.move_folder(ctx=ctx, actor=request.user, folder=folder, new_parent=new_parent, request=request)
    except S.DomainError as exc:
        return _err(str(exc), 403)
    audit.record("folder.update", request=request, target=folder, fields=list(d.keys()))
    ctx._cache.clear()
    folder.refresh_from_db()
    return Response(folder_json(_rebuild(request), folder))


def _rebuild(request):
    request._pd_access = None
    return _ctx(request)


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def folder_archive(request, pk):
    folder = get_folder(request, pk, P.ARCHIVE)
    if folder.parent_id is None:
        return _err("The library root cannot be archived.")
    try:
        S.archive_folder(actor=request.user, folder=folder, request=request)
    except S.DomainError as exc:
        return _err(str(exc), 403)
    return Response({"status": "archived"})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def folder_apply_template(request, pk):
    folder = get_folder(request, pk, P.ORGANIZE)
    try:
        created = S.apply_template(actor=request.user, root=folder)
    except S.DomainError as exc:
        return _err(str(exc))
    audit.record("folder.apply_template", request=request, target=folder, created=created)
    return Response({"created": created})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def folder_restore(request, pk):
    folder = get_object_or_404(Folder, pk=pk)
    try:
        S.restore_folder(actor=request.user, folder=folder, request=request)
    except S.DomainError as exc:
        return _err(str(exc))
    return Response({"status": "restored"})


def _rules_json(rules):
    return [{"id": r.id, "user": user_mini(r.user) if r.user_id else None,
             "group": {"id": str(r.group_id), "name": r.group.name} if r.group_id else None,
             "caps": P.names(r.caps)} for r in rules.select_related("user", "group")]


def _permissions_view(request, target, is_folder):
    ctx = _ctx(request)
    caps = ctx.folder_caps(target.id) if is_folder else ctx.doc_caps(target)
    if request.method == "PUT":
        if not caps & P.MANAGE:
            raise PermissionDenied("You cannot manage permissions here.")
        user = User.objects.filter(pk=request.data.get("user")).first() if request.data.get("user") else None
        group = FamilyGroup.objects.filter(pk=request.data.get("group")).first() if request.data.get("group") else None
        if (user is None) == (group is None):
            return _err("Choose one person or one group.")
        try:
            new_caps = P.from_names(request.data.get("caps") or [])
            S.grant(ctx=ctx, actor=request.user, target=target, caps=new_caps, user=user, group=group, request=request)
        except (S.DomainError, ValueError) as exc:
            return _err(str(exc), 403)
    rules = AccessRule.objects.filter(**({"folder": target} if is_folder else {"document": target}))
    data = {"my_caps": P.names(caps), "can_manage": bool(caps & P.MANAGE), "inherit_permissions": target.inherit_permissions,
            "cap_labels": P.CAP_LABELS}
    if caps & P.MANAGE:
        data["rules"] = _rules_json(rules)
        who = request.query_params.get("user")
        if who:
            u = get_object_or_404(User, pk=who)
            uctx = P.AccessContext.build(u)
            data["effective_for"] = {
                "user": user_mini(u),
                "caps": P.names(uctx.folder_caps(target.id) if is_folder else uctx.doc_caps(target)),
                "why": uctx.explain_folder(target.id) if is_folder else uctx.explain_document(target),
            }
    data["why"] = ctx.explain_folder(target.id) if is_folder else ctx.explain_document(target)
    return Response(data)


@api_view(["GET", "PUT"])
@permission_classes([IsActiveAuthenticated])
def folder_permissions(request, pk):
    return _permissions_view(request, get_folder(request, pk), True)


# ------------------------------------------------------------------ documents

@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def documents(request):
    ctx = _ctx(request)
    if request.method == "POST":
        return _upload(request, ctx)
    params = {k: request.query_params.get(k) for k in ("folder", "owner", "type", "tag", "correspondent", "state",
                                                     "expiring_days", "expired", "added_after", "sort") if request.query_params.get(k)}
    try:
        limit = min(200, int(request.query_params.get("limit", 50)))
        offset = max(0, int(request.query_params.get("offset", 0)))
    except ValueError:
        limit, offset = 50, 0
    if request.query_params.get("archived") == "1":
        if not ctx.is_admin:
            raise PermissionDenied("Only the main administrator can browse the archive.")
        qs = Document.objects.filter(archived_at__isnull=False).select_related("owner", "doc_type", "current_version")
        total = qs.count()
        return Response({"documents": [document_row(ctx, d) for d in qs.order_by("-archived_at")[offset:offset + limit]], "total": total})
    rows, total, snippets = searchlib.search(ctx, request.query_params.get("q", ""), params, limit, offset)
    return Response({"documents": [document_row(ctx, d, snippets.get(d.id)) for d in rows], "total": total})


def _resolve_owner(request, folder: Folder):
    owner_id = request.data.get("owner")
    if owner_id:
        owner = User.objects.filter(pk=owner_id, is_active=True).first()
        if owner is None:
            raise S.DomainError("Unknown owner.")
        if folder.owner_id and owner.pk != folder.owner_id and not request.user.is_main_admin:
            raise S.DomainError("Documents in a personal folder belong to that person.")
        if not request.user.is_main_admin and owner.pk != request.user.pk and owner.pk != folder.owner_id:
            from apps.accounts.models import GroupMembership
            from apps.accounts.services import delegations_for

            groups = {d.group_id for d in delegations_for(request.user, "documents")}
            if not GroupMembership.objects.filter(user=owner, group_id__in=groups).exists():
                raise S.DomainError("You can only add documents for yourself or for people you manage documents for.")
        return owner
    return folder.owner or request.user


def _upload(request, ctx):
    folder = get_folder(request, request.data.get("folder"), P.UPLOAD)
    files = request.FILES.getlist("files") or request.FILES.getlist("file")
    getlist = getattr(request.data, "getlist", lambda k: [])
    if not files and not getlist("dirs"):
        return _err("Choose at least one file.")
    try:
        owner = _resolve_owner(request, folder)
    except S.DomainError as exc:
        return _err(str(exc))
    doc_type = (DocumentType.objects.filter(pk=request.data.get("doc_type"), archived=False).first()
                if str(request.data.get("doc_type") or "").isdigit() else None)
    # "folder" when the person kept the type the folder suggested, "manual" when they chose it
    type_source = "folder" if request.data.get("type_source") == "folder" else "manual"
    blocked = {e.strip().lower().lstrip(".") for e in (config.get("documents.blocked_extensions") or "").split(",") if e.strip()}
    paths = getlist("paths")  # relative paths of dropped files ("House Documents/Lease/2024.pdf"), parallel to files
    if paths and len(paths) != len(files):
        return _err("Each dropped file needs its relative path.")
    tree = _DropTree(request, ctx, folder)
    for d in getlist("dirs"):  # empty folders that were dropped too
        try:
            tree.folder_for(d, is_dir=True)
        except S.DomainError as exc:
            tree.errors.append({"file": d, "error": str(exc)})
    created, errors = [], tree.errors
    for i, f in enumerate(files):
        label = paths[i] if paths else f.name
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if ext in blocked:
            errors.append({"file": label, "error": "This file type is blocked by the administrator."})
            continue
        try:
            target = tree.folder_for(paths[i]) if paths else folder
            staged = storage.stage_uploaded_file(f)
            doc = S.create_document(actor=request.user, folder=target, owner=owner, staged=staged,
                                    title=request.data.get("title", "") if len(files) == 1 and not paths else "", doc_type=doc_type,
                                    type_source=type_source)
            created.append(doc)
            audit.record("document.upload", request=request, target=doc, subject_user=owner, size=staged.size)
        except (storage.StorageError, S.DomainError) as exc:
            errors.append({"file": label, "error": str(exc)})
    if created:
        events.documents_added(actor=request.user, docs=created, via="upload")  # one summary per owner
    _rebuild(request)
    ctx = _ctx(request)
    ok = created or (tree.created and not errors)
    return Response({"documents": [document_row(ctx, d) for d in created], "errors": errors,
                     "folders_created": len(tree.created)}, status=201 if ok else 400)


class _DropTree:
    """Recreates the folder structure of files dragged from the desktop below the drop target.

    Paths are validated (no "..", absolute paths or control characters); existing sub-folders are reused when the
    person may add documents there, new ones are created only where the person may organise folders.
    """

    def __init__(self, request, ctx, root: Folder):
        self.request, self.ctx, self.root = request, ctx, root
        self.cache: dict[tuple, Folder] = {(): root}
        self.created: list[Folder] = []
        self.errors: list[dict] = []
        self.new_ids: set = set()

    def _caps(self, f: Folder) -> int:
        if f.id in self.new_ids:  # created in this request: inherits the parent's access, which allowed creating it
            return P.VIEW | P.UPLOAD | P.ORGANIZE
        return self.ctx.folder_caps(f.id)

    def folder_for(self, rel: str, is_dir: bool = False) -> Folder:
        from .imports import excluded_reason, normalize_rel

        try:
            rel = normalize_rel(rel)
        except ValueError:
            raise S.DomainError("This path is not allowed (it points outside the folder you dropped on).")
        if not rel:
            raise S.DomainError("Missing file name.")
        why = excluded_reason(rel)
        if why:
            raise S.DomainError(f"Skipped: {why}.")
        parts = rel.split("/") if is_dir else rel.split("/")[:-1]
        node = self.root
        for n in range(1, len(parts) + 1):
            key = tuple(p.lower() for p in parts[:n])
            if key in self.cache:
                node = self.cache[key]
                continue
            name = storage.safe_component(parts[n - 1], 200)
            child = Folder.objects.filter(parent=node, name__iexact=name, archived_at__isnull=True).first()
            if child is None:
                if not self._caps(node) & P.ORGANIZE:
                    raise S.DomainError(f"You cannot create folders in “{node.name}”, so “{name}” was not created.")
                child = S.create_folder(actor=self.request.user, parent=node, name=name)
                self.created.append(child)
                self.new_ids.add(child.id)
                audit.record("folder.create", request=self.request, target=child, via="drop")
            elif not self._caps(child) & P.VIEW:
                raise S.DomainError(f"A folder named “{name}” already exists here and you cannot open it.")
            self.cache[key] = node = child
        if not is_dir and not self._caps(node) & P.UPLOAD:
            raise S.DomainError(f"You cannot add documents to “{node.name}”.")
        return node


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def document_view(request, pk):
    ctx = _ctx(request)
    if request.method == "DELETE":
        if not ctx.is_admin:
            raise PermissionDenied("Only the main administrator can permanently delete documents.")
        doc = get_doc(request, pk, include_archived=True)
        if request.data.get("confirm") != doc.title:
            return _err("Type the document title to confirm permanent deletion.", 400, code="confirm_required")
        gone = events.GoneDocument(doc)
        try:
            S.purge_document(actor=request.user, doc=doc, request=request)
        except S.DomainError as exc:
            return _err(str(exc))
        events.documents_removed(actor=request.user, docs=[gone], permanent=True)
        return Response(status=204)
    doc = get_doc(request, pk, include_archived=True)
    if request.method == "GET":
        audit.record("document.view", request=request, target=doc, subject_user=doc.owner)
        return Response(document_detail(ctx, doc))
    caps = ctx.doc_caps(doc)
    d = request.data
    try:
        if any(k in d for k in ("title", "doc_type", "correspondent", "tags", "renews", "reset_title")):
            if not caps & P.EDIT:
                raise PermissionDenied("You cannot edit this document.")
            changes = {}
            if "title" in d:
                title = (d["title"] or "").strip()[:255]
                if not title:
                    return _err("Title cannot be empty.")
                changes["title"] = [doc.title, title]
                doc.title, doc.title_is_custom = title, True
            if d.get("reset_title"):
                doc.title_is_custom = False
            new_type = _UNSET = object()
            if "doc_type" in d and str(d["doc_type"] or "") != str(doc.doc_type_id or ""):
                new_type = DocumentType.objects.filter(pk=d["doc_type"]).first() if str(d["doc_type"] or "").isdigit() else None
                if d["doc_type"] and new_type is None:
                    return _err("Unknown document type.")
            if "correspondent" in d:
                val = d["correspondent"]
                if isinstance(val, str) and val and not val.isdigit():
                    doc.correspondent, _ = Correspondent.objects.get_or_create(name=val.strip()[:120])
                else:
                    doc.correspondent = Correspondent.objects.filter(pk=val).first() if val else None
            if "renews" in d:
                prev = get_doc(request, d["renews"]) if d["renews"] else None
                if prev and prev.pk == doc.pk:
                    return _err("A document cannot renew itself.")
                doc.renews = prev
                changes["renews"] = str(prev.pk) if prev else None
            doc.save()
            if new_type is not _UNSET:  # same rules as the Set type dialog: values are kept, nothing is moved
                doctypes.change_type(actor=request.user, doc=doc, new_type=new_type, request=request)
                doc.refresh_from_db()
                changes["type"] = new_type.name if new_type else None
            if "tags" in d:
                names = [str(t).strip()[:60] for t in d["tags"] if str(t).strip()]
                tags = [Tag.objects.get_or_create(name=n)[0] for n in names]
                doc.tags.set(tags)
                changes["tags"] = names
            S._history(doc, request.user, "edited", **changes)
            S.refresh_title(doc)
            searchlib.update_search_vector(doc)
        if "folder" in d and str(d["folder"]) != str(doc.folder_id):
            target = get_folder(request, d["folder"])
            S.move_document(ctx=ctx, actor=request.user, doc=doc, folder=target, request=request)
        if "inherit_permissions" in d:
            if not caps & P.MANAGE:
                raise PermissionDenied("You cannot change permission inheritance.")
            doc.inherit_permissions = bool(d["inherit_permissions"])
            doc.save(update_fields=["inherit_permissions"])
    except S.DomainError as exc:
        return _err(str(exc), 403)
    audit.record("document.edit", request=request, target=doc, subject_user=doc.owner, fields=list(d.keys()))
    doc.refresh_from_db()
    return Response(document_detail(_rebuild(request), doc))


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def document_versions(request, pk):
    doc = get_doc(request, pk, P.VERSION)
    f = request.FILES.get("file")
    if not f:
        return _err("Choose a file.")
    try:
        staged = storage.stage_uploaded_file(f)
        v = S.add_version(actor=request.user, doc=doc, staged=staged, comment=(request.data.get("comment") or "")[:255],
                          additional=str(request.data.get("additional") or "").lower() in ("1", "true", "yes"))
    except (storage.StorageError, S.DomainError) as exc:
        return _err(str(exc))
    audit.record("document.version_upload", request=request, target=doc, subject_user=doc.owner, version=v.number)
    return Response(version_json(v), status=201)


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def document_set_version(request, pk, vid):
    doc = get_doc(request, pk, P.VERSION)
    v = get_object_or_404(DocumentVersion, pk=vid, document=doc)
    S.set_current_version(actor=request.user, doc=doc, version=v)
    audit.record("document.version_select", request=request, target=doc, version=v.number)
    return Response(document_detail(_ctx(request), doc))


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def document_renew(request, pk):
    """Upload a renewed credential as a separate, linked record."""
    ctx = _ctx(request)
    old = get_doc(request, pk)
    folder = old.folder
    if not ctx.folder_caps(folder.id) & P.UPLOAD:
        raise PermissionDenied("You need upload permission in this folder.")
    f = request.FILES.get("file")
    if not f:
        return _err("Choose a file.")
    try:
        staged = storage.stage_uploaded_file(f)
        doc = S.create_document(actor=request.user, folder=folder, owner=old.owner, staged=staged, doc_type=old.doc_type, renews=old)
        if old.tags.exists():
            doc.tags.set(old.tags.all())
    except (storage.StorageError, S.DomainError) as exc:
        return _err(str(exc))
    audit.record("document.renewal_upload", request=request, target=doc, subject_user=old.owner, renews=str(old.pk))
    return Response(document_detail(_rebuild(request), doc), status=201)


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def document_fields(request, pk):
    """Edit, confirm, add or remove detail values. One-off details (custom) belong to this document only; values kept
    from a previous type are reviewed with action map / keep / remove."""
    doc = get_doc(request, pk, P.EDIT)
    d = request.data
    try:
        if d.get("confirm_all"):
            S.confirm_all(actor=request.user, doc=doc, allow_incomplete=bool(d.get("allow_incomplete")))
        else:
            key = (d.get("key") or "").strip()
            label = (d.get("label") or "").strip()[:80]
            if not key and label:  # a one-off detail with its own label: "custom:<slug>"
                key = doctypes.custom_key(label)
                if doc.fields.filter(key=key).exists():
                    return _err("This document already has a detail with that name.")
            if not re.fullmatch(r"[a-z0-9_:\-]{1,80}", key):
                return _err("Invalid field name.")
            if d.get("action") in ("map", "keep", "remove"):
                doctypes.resolve_unmapped(actor=request.user, doc=doc, key=key, action=d["action"],
                                          to=(d.get("to") or "").strip())
            elif key.startswith("custom:") and not label and not doc.fields.filter(key=key).exists():
                cdef = CustomFieldDef.objects.filter(key=key[7:]).first()
                if cdef is None:
                    return _err("Unknown custom field.")
                _validate_custom(cdef, d.get("value", ""))
                S.set_field(actor=request.user, doc=doc, key=key, value=str(d.get("value", "")), label=cdef.label,
                            scope=DocumentField.CUSTOM, confirm=bool(d.get("confirm", True)))
            elif d.get("delete"):
                DocumentField.objects.filter(document=doc, key=key).delete()
                S._history(doc, request.user, "field_removed", key=key)
                S.apply_confirmed_fields(doc)
            else:
                existing = doc.fields.filter(key=key).first()
                if key.startswith("custom:") and existing is not None and existing.scope == DocumentField.TYPE:
                    return _err("Invalid field name.")
                cdef = CustomFieldDef.objects.filter(key=key[7:]).first() if key.startswith("custom:") else None
                if cdef is not None:
                    _validate_custom(cdef, d.get("value", ""))
                scope = None
                if existing is None and not key.startswith("custom:") and doc.doc_type_id \
                        and doctypes.template_field_for(doc, key) is None:
                    scope = DocumentField.CUSTOM  # a standard detail outside this type's template: one-off
                S.set_field(actor=request.user, doc=doc, key=key, value=str(d.get("value", "")), label=label,
                            scope=scope, confirm=bool(d.get("confirm", True)))
    except S.DomainError as exc:
        return _err(str(exc))
    audit.record("document.fields", request=request, target=doc, subject_user=doc.owner)
    doc.refresh_from_db()
    if doc.ocr_state == "needs_review" and not doc.fields.filter(status=DocumentField.PROPOSED).exists():
        Document.objects.filter(pk=doc.pk).update(ocr_state="confirmed")  # every suggestion was decided
        doc.ocr_state = "confirmed"
    searchlib.update_search_vector(doc)
    return Response(document_detail(_ctx(request), doc))


def _validate_custom(cdef: CustomFieldDef, value):
    from .extraction import parse_date

    value = str(value or "").strip()
    if not value:
        return
    if cdef.type == "number":
        try:
            float(value)
        except ValueError:
            raise S.DomainError(f"{cdef.label} must be a number.")
    elif cdef.type == "date" and parse_date(value) is None:
        raise S.DomainError(f"{cdef.label} must be a date (YYYY-MM-DD).")
    elif cdef.type == "boolean" and value not in ("true", "false"):
        raise S.DomainError(f"{cdef.label} must be yes or no.")
    elif cdef.type == "choice" and value not in cdef.choices:
        raise S.DomainError(f"{cdef.label} must be one of: {', '.join(cdef.choices)}.")


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def field_reveal(request, pk, key):
    """Full value for copy-to-clipboard; audited (value never logged)."""
    doc = get_doc(request, pk)
    f = get_object_or_404(DocumentField, document=doc, key=key)
    audit.record("document.field_copy", request=request, target=doc, subject_user=doc.owner, field=key)
    return Response({"key": key, "value": f.value})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def document_archive(request, pk):
    doc = get_doc(request, pk, P.ARCHIVE)
    S.archive_document(actor=request.user, doc=doc, request=request)
    events.documents_removed(actor=request.user, docs=[doc], permanent=False)
    return Response({"status": "archived"})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def document_restore(request, pk):
    doc = get_doc(request, pk, include_archived=True)
    try:
        S.restore_document(actor=request.user, doc=doc, request=request)
    except S.DomainError as exc:
        return _err(str(exc))
    return Response({"status": "restored"})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def document_reprocess(request, pk):
    from apps.core import jobs

    doc = get_doc(request, pk, P.EDIT)
    if not doc.current_version_id:
        return _err("No file to process.")
    from .models import Document as D

    payload = {"version_id": str(doc.current_version_id)}
    rotate = request.data.get("rotate") if hasattr(request, "data") else None
    if rotate not in (None, "", "auto"):
        try:
            rotate = int(rotate)
        except (TypeError, ValueError):
            return _err("Rotation must be auto, 0, 90, 180 or 270.")
        if rotate not in (0, 90, 180, 270):
            return _err("Rotation must be auto, 0, 90, 180 or 270.")
        payload["rotate"] = rotate  # manual orientation for the OCR re-run (clockwise degrees)
    if "rotate" in payload:  # a rotation only matters for text recognition: re-run OCR on the source set
        from . import ocr_runs

        try:
            ocr_runs.request_ocr(actor=request.user, doc=doc, rotate=payload["rotate"], set_primary=False, request=request)
        except ocr_runs.OCRError as exc:
            return _err(str(exc))
        audit.record("document.reprocess", request=request, target=doc, rotate=payload["rotate"])
        return Response({"status": "queued", "ocr": True})
    D.objects.filter(pk=doc.pk).update(state=D.QUEUED)
    jobs.enqueue("process_version", payload, idempotency_key=f"process:{doc.current_version_id}:{timezone.now().timestamp()}")
    audit.record("document.reprocess", request=request, target=doc, rotate="auto")
    return Response({"status": "queued"})


@api_view(["GET", "PUT"])
@permission_classes([IsActiveAuthenticated])
def document_permissions(request, pk):
    return _permissions_view(request, get_doc(request, pk), False)


# ------------------------------------------------------------------ file delivery

def _stream(request, path, content_type, filename, disposition):
    size = path.stat().st_size
    rng = request.headers.get("Range", "")
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip()) if rng else None
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        else:
            start, end = max(0, size - int(m.group(2))), size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            resp = StreamingHttpResponse([], status=416)
            resp["Content-Range"] = f"bytes */{size}"
            return resp
        resp = StreamingHttpResponse(storage.iter_file(path, start, end - start + 1), status=206, content_type=content_type)
        resp["Content-Range"] = f"bytes {start}-{end}/{size}"
        resp["Content-Length"] = str(end - start + 1)
    else:
        resp = FileResponse(open(path, "rb"), content_type=content_type)
        resp["Content-Length"] = str(size)
    resp["Accept-Ranges"] = "bytes"
    from urllib.parse import quote

    safe = filename.replace('"', "")
    resp["Content-Disposition"] = f"{disposition}; filename=\"{safe.encode('ascii', 'replace').decode()}\"; filename*=UTF-8''{quote(safe)}"
    resp["X-Content-Type-Options"] = "nosniff"
    # Browsers' built-in PDF viewers refuse to run in sandboxed documents, so only non-PDF/image types get `sandbox`.
    viewer_safe = content_type.startswith(("application/pdf", "image/"))
    resp["Content-Security-Policy"] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'" + ("" if viewer_safe else "; sandbox")
    resp["Cache-Control"] = "no-store, private"
    return resp


INLINE_SAFE = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain"}


def _version_for(request, doc, *, allow_blocked: bool = False):
    vid = request.query_params.get("version")
    if vid:
        v = get_object_or_404(DocumentVersion, pk=vid, document=doc)
    elif not doc.current_version:
        raise Http404
    else:
        v = doc.current_version
    if v.av_blocked and not allow_blocked:
        raise QuarantinedFile()
    return v


class QuarantinedFile(Exception):
    pass


def quarantined_response():
    return _err("This file is in antivirus quarantine. Preview, download and processing are blocked until the main "
                "administrator reviews it.", 423, code="quarantined")


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def document_file(request, pk):
    download = request.query_params.get("download") == "1"
    doc = get_doc(request, pk, P.DOWNLOAD if download else P.VIEW)
    try:
        v = _version_for(request, doc)
    except QuarantinedFile:
        return quarantined_response()
    path = storage.resolve_original(v.storage_path)
    if not path.exists():
        return _err("The stored file is missing. Ask the administrator to run the integrity check.", 410)
    ctype = v.mime if v.mime in INLINE_SAFE else "application/octet-stream"
    if v.format_class == "text":
        ctype = "text/plain; charset=utf-8"
    disp = "attachment" if download or ctype == "application/octet-stream" else "inline"
    if download:
        audit.record("document.download", request=request, target=doc, subject_user=doc.owner, version=v.number)
    return _stream(request, path, ctype, v.original_name, disp)


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def document_preview(request, pk):
    doc = get_doc(request, pk)
    try:
        v = _version_for(request, doc)
    except QuarantinedFile:
        return quarantined_response()
    rel = v.searchable_path or v.preview_path
    if rel:
        return _stream(request, storage.resolve_derivative(rel), "application/pdf", f"{doc.title}.pdf", "inline")
    if v.format_class in ("pdf", "image", "text") and v.mime in INLINE_SAFE | {"text/plain"}:
        ctype = "text/plain; charset=utf-8" if v.format_class == "text" else v.mime
        return _stream(request, storage.resolve_original(v.storage_path), ctype, v.original_name, "inline")
    return _err("No preview is available for this file.", 404)


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def document_thumbnail(request, pk):
    doc = get_doc(request, pk)
    try:
        v = _version_for(request, doc)
    except QuarantinedFile:
        raise Http404
    if not v.thumbnail_path:
        raise Http404
    resp = _stream(request, storage.resolve_derivative(v.thumbnail_path), "image/png", "thumb.png", "inline")
    return resp


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def document_text(request, pk):
    doc = get_doc(request, pk)
    v = _version_for(request, doc)
    q = v.ocr_quality or {}
    return Response({"text": v.text, "ocr_applied": v.ocr_applied, "version": v.number,
                     "confidence": q.get("confidence"), "low_lines": q.get("low_lines") or [],
                     "line_count": q.get("line_count")})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def document_similar(request, pk):
    ctx = _ctx(request)
    doc = get_doc(request, pk)
    return Response({"similar": [{**document_row(ctx, d), "score": s, "reasons": r} for d, s, r in searchlib.more_like_this(ctx, doc)]})


# ------------------------------------------------------------------ bulk

@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def documents_bulk(request):
    ctx = _ctx(request)
    action = request.data.get("action")
    value = request.data.get("value")
    ids = list(request.data.get("ids") or [])[:500]
    results, archived = [], []
    for did in ids:
        try:
            doc = Document.objects.select_related("folder", "owner").get(pk=did, archived_at__isnull=True)
        except Exception:
            results.append({"id": did, "ok": False, "error": "Not found"})
            continue
        caps = ctx.doc_caps(doc)
        if not caps & P.VIEW:
            results.append({"id": did, "ok": False, "error": "Not found"})
            continue
        try:
            if action in ("tag_add", "tag_remove", "set_type"):
                if not caps & P.EDIT:
                    raise S.DomainError("No edit permission")
                if action == "set_type":  # same rules as one document: values kept, confirmed types protected
                    new_type = DocumentType.objects.filter(pk=value).first() if str(value or "").isdigit() else None
                    if value and new_type is None:
                        raise S.DomainError("Unknown document type.")
                    if (doc.type_confirmed and doc.doc_type_id and doc.doc_type_id != getattr(new_type, "pk", None)
                            and not request.data.get("overwrite_confirmed")):
                        raise S.DomainError("Already has a confirmed type (not changed)")
                    if doc.doc_type_id != getattr(new_type, "pk", None):
                        doctypes.change_type(actor=request.user, doc=doc, new_type=new_type, request=request)
                else:
                    tag, _ = Tag.objects.get_or_create(name=str(value).strip()[:60])
                    (doc.tags.add if action == "tag_add" else doc.tags.remove)(tag)
                searchlib.update_search_vector(doc)
            elif action == "move":
                S.move_document(ctx=ctx, actor=request.user, doc=doc, folder=get_folder(request, value), request=request)
            elif action == "archive":
                if not caps & P.ARCHIVE:
                    raise S.DomainError("No archive permission")
                S.archive_document(actor=request.user, doc=doc, request=request)
                archived.append(doc)
            else:
                raise S.DomainError("Unknown action")
            results.append({"id": did, "ok": True})
        except (S.DomainError, PermissionDenied, Http404) as exc:
            results.append({"id": did, "ok": False, "error": str(exc) or "Not permitted"})
    audit.record("document.bulk", request=request, bulk_action=action, count=len(ids), failed=sum(1 for r in results if not r["ok"]))
    if archived:
        events.documents_removed(actor=request.user, docs=archived, permanent=False)  # one summary per owner
    return Response({"results": results, "succeeded": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])})


# ------------------------------------------------------------------ search / saved views

@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def autocomplete(request):
    return Response({"suggestions": searchlib.autocomplete(_ctx(request), request.query_params.get("q", ""))})


def _view_json(v):
    return {"id": v.id, "name": v.name, "query": v.query, "show_on_dashboard": v.show_on_dashboard, "show_in_sidebar": v.show_in_sidebar}


@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def saved_views(request):
    if request.method == "POST":
        name = (request.data.get("name") or "").strip()[:80]
        if not name:
            return _err("Name the view.")
        query = {k: v for k, v in (request.data.get("query") or {}).items() if k in
                 ("q", "folder", "owner", "type", "tag", "correspondent", "state", "expiring_days", "expired")}
        v = SavedView.objects.create(user=request.user, name=name, query=query,
                                     show_on_dashboard=bool(request.data.get("show_on_dashboard")),
                                     show_in_sidebar=bool(request.data.get("show_in_sidebar")))
        return Response(_view_json(v), status=201)
    ctx = _ctx(request)
    out = []
    for v in SavedView.objects.filter(user=request.user):
        data = _view_json(v)
        # Counts are computed with the caller's *current* permissions.
        _rows, total, _ = searchlib.search(ctx, v.query.get("q", ""), v.query, limit=1)
        data["count"] = total
        out.append(data)
    return Response({"views": out})


@api_view(["PATCH", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def saved_view_detail(request, pk):
    v = get_object_or_404(SavedView, pk=pk, user=request.user)
    if request.method == "DELETE":
        v.delete()
        return Response(status=204)
    for k in ("name", "show_on_dashboard", "show_in_sidebar"):
        if k in request.data:
            setattr(v, k, request.data[k])
    v.save()
    return Response(_view_json(v))


# ------------------------------------------------------------------ metadata

@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def metadata(request):
    if request.method == "POST":
        if not request.user.is_main_admin:
            raise PermissionDenied("Only the main administrator can manage types and fields.")
        kind = request.data.get("kind")
        name = (request.data.get("name") or "").strip()
        if not name:
            return _err("Enter a name.")
        if kind == "type":
            t, created = DocumentType.objects.get_or_create(name=name[:80], defaults={
                "template": request.data.get("template") if request.data.get("template") in DocumentType.TEMPLATES else "generic",
                "has_expiry": bool(request.data.get("has_expiry")), "is_custom": True})
            if created:
                doctypes.ensure_template(t)
        elif kind == "tag":
            Tag.objects.get_or_create(name=name[:60])
        elif kind == "correspondent":
            Correspondent.objects.get_or_create(name=name[:120])
        elif kind == "field":
            from django.utils.text import slugify

            ftype = request.data.get("type") if request.data.get("type") in CustomFieldDef.TYPES else "text"
            CustomFieldDef.objects.get_or_create(key=slugify(name)[:60] or "field", defaults={
                "label": name[:80], "type": ftype, "choices": list(request.data.get("choices") or [])})
        else:
            return _err("Unknown kind.")
    return Response({
        "types": [{"id": t.id, "name": t.name, "template": t.template, "has_expiry": t.has_expiry, "emoji": t.emoji,
                   "archived": t.archived, "description": t.description} for t in DocumentType.objects.all()],
        "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in Tag.objects.all()],
        "correspondents": [{"id": c.id, "name": c.name} for c in Correspondent.objects.all()],
        "fields": [{"key": f.key, "label": f.label, "type": f.type, "choices": f.choices} for f in CustomFieldDef.objects.all()],
        "templates": DocumentType.TEMPLATES,
        "standard_fields": DocumentField.STANDARD,
    })


@api_view(["DELETE"])
@permission_classes([IsMainAdmin])
def metadata_delete(request, kind, pk):
    model = {"type": DocumentType, "tag": Tag, "correspondent": Correspondent}.get(kind)
    if model is None:
        if kind == "field":
            CustomFieldDef.objects.filter(key=pk).delete()
            return Response(status=204)
        raise Http404
    if model is DocumentType and Document.objects.filter(doc_type_id=pk).exists():
        # never untype documents by deleting their type: archive it or move the documents first (Settings)
        return _err("This document type is in use. Archive it or move its documents to another type first.", 409,
                    code="in_use")
    model.objects.filter(pk=pk).delete()
    return Response(status=204)


# ------------------------------------------------------------------ dashboard

@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def dashboard(request):
    ctx = _ctx(request)
    from apps.accounts.views import _visible_member_ids, user_json

    docs = ctx.documents(P.VIEW)
    today = timezone.localdate()
    expiring = docs.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=90))
    member_ids = _visible_member_ids(request.user)
    members = User.objects.filter(is_active=True) if member_ids is None else User.objects.filter(pk__in=member_ids, is_active=True)
    storage_bytes = DocumentVersion.objects.filter(document__in=docs).aggregate(s=Sum("size"))["s"] or 0
    review = [d for d in docs.filter(state=Document.NEEDS_REVIEW).select_related("owner", "doc_type", "current_version")[:20]
              if ctx.doc_caps(d) & P.EDIT][:8]
    data = {
        "stats": {
            "documents": docs.count(),
            "members": members.count(),
            "expiring_90": expiring.count(),
            "expired": docs.filter(expiry_date__lt=today).count(),
            "storage_bytes": storage_bytes,
            "needs_review": len(review),
        },
        "members": [user_json(u) for u in members],
        "recent": [document_row(ctx, d) for d in docs.select_related("owner", "doc_type", "current_version").order_by("-created_at")[:6]],
        "expiring": [document_row(ctx, d) for d in expiring.select_related("owner", "doc_type", "current_version").order_by("expiry_date")[:6]],
        "review": [document_row(ctx, d) for d in review],
        "saved_views": [],
    }
    from apps.core import config as cfg
    from apps.core import overview

    shared = docs.exclude(owner=request.user)
    data["stats"]["shared"] = shared.count()
    data["shared"] = [document_row(ctx, d) for d in shared.select_related("owner", "doc_type", "current_version").order_by("-created_at")[:6]]
    labels = {"created": "added", "edited": "edited", "moved": "moved", "archived": "archived", "restored": "restored",
              "version_added": "uploaded a new version of", "file_added": "added a file to", "current_version": "changed the current version of",
              "field_confirmed": "confirmed details of", "field_removed": "removed a detail from", "ai_suggestion_accepted": "accepted a suggestion for"}
    data["activity"] = [{"at": h.at, "action": h.action, "verb": labels.get(h.action, h.action.replace("_", " ")),
                         "actor": h.actor.display_name if h.actor_id else "System",
                         "document": {"id": str(h.document_id), "title": h.document.title}}
                        for h in DocumentHistory.objects.filter(document__in=docs).select_related("actor", "document").order_by("-at")[:8]]
    data["today"] = overview.today_info()
    data["holidays"] = overview.upcoming_holidays(limit=6)
    data["holiday_countries"] = [{"code": c, "name": overview.country_names()[c], "flag": overview.flag(c)} for c in overview.configured_countries()]
    data["weather_enabled"] = bool(cfg.get("weather.enabled"))
    data["layout_limits"] = overview.layout_limits()
    if request.user.is_main_admin or request.user.is_admin:  # Security Health is for administrators only
        from apps.security import center

        try:
            data["security_health"] = center.security_health()
        except Exception:  # noqa: BLE001 - the Overview must load even if a health source fails
            data["security_health"] = None
    for v in SavedView.objects.filter(user=request.user, show_on_dashboard=True):
        _rows, total, _ = searchlib.search(ctx, v.query.get("q", ""), v.query, limit=1)
        data["saved_views"].append({**_view_json(v), "count": total})
    if ctx.is_admin:
        from apps.ops.backup import last_backup_status

        data["admin"] = {"backup": last_backup_status(), "disk_free_bytes": storage.disk_free_bytes(),
                         "failed_jobs": __import__("apps.core.models", fromlist=["Job"]).Job.objects.filter(status="failed").count()}
    return Response(data)
