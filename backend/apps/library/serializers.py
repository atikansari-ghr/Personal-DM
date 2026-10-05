"""Plain-dict serializers; every function receives the AccessContext to avoid leaking data."""
from __future__ import annotations

from django.utils import timezone

from . import filetypes
from . import permissions as P
from .models import Document, DocumentField, DocumentVersion, Folder
from .services import mask


def user_mini(u) -> dict | None:
    if u is None:
        return None
    from apps.accounts.photos import version

    return {"id": str(u.pk), "display_name": u.display_name, "initials": u.initials, "avatar_color": u.avatar_color,
            "photo_version": version(u)}


def expiry_status(doc: Document) -> dict | None:
    if not doc.expiry_date:
        if getattr(doc, "no_expiry", False):
            return {"days": None, "label": "No expiry", "level": "none"}
        return None
    today = timezone.localdate()
    days = (doc.expiry_date - today).days
    if days < 0:
        label, level = "Expired", "expired"
    elif days <= 90:
        label, level = "Expires soon", "soon"
    else:
        label, level = "Valid", "ok"
    return {"days": days, "label": label, "level": level}


def version_json(v: DocumentVersion) -> dict:
    return {
        "id": str(v.id), "number": v.number, "original_name": v.original_name, "size": v.size, "sha256": v.sha256,
        "mime": v.mime, "format": v.format_class, **filetypes.describe(v), "comment": v.comment, "state": v.state, "error": v.error,
        "ocr_applied": v.ocr_applied, "pdfa": v.pdfa, "page_count": v.page_count,
        "ocr_quality": {k: v.ocr_quality.get(k) for k in ("confidence", "rotation", "skew", "steps", "low_lines", "line_count")}
        if v.ocr_quality else None,
        "pdfa_check": {k: v.pdfa_report.get(k) for k in ("validator", "profile", "compliant", "full_validation", "failed_rules", "note")} if v.pdfa_report else None,
        "has_preview": bool(v.preview_path or v.searchable_path or v.format_class in ("pdf", "image", "text")),
        "has_thumbnail": bool(v.thumbnail_path), "created_at": v.created_at,
        "created_by": v.created_by.display_name if v.created_by_id and v.created_by else None,
    }


def document_row(ctx: P.AccessContext, d: Document, snippet: str | None = None) -> dict:
    v = d.current_version
    row = {
        "id": str(d.id), "title": d.title, "folder": str(d.folder_id), "owner": user_mini(d.owner),
        "type": {"id": d.doc_type_id, "name": d.doc_type.name} if d.doc_type_id else None,
        "state": d.state, "expiry_date": d.expiry_date, "issue_date": d.issue_date, "expiry": expiry_status(d),
        "no_expiry": d.no_expiry,
        "created_at": d.created_at, "archived": d.archived_at is not None,
        "size": v.size if v else None, "format": v.format_class if v else None, **filetypes.describe(v),
        "has_thumbnail": bool(v and v.thumbnail_path), "version_id": str(v.id) if v else None,
        "caps": P.names(ctx.doc_caps(d)),
    }
    if snippet is not None:
        row["snippet"] = snippet
    return row


def field_json(f: DocumentField) -> dict:
    return {
        "key": f.key, "value": mask(f.key, f.value), "sensitive": f.key in DocumentField.SENSITIVE,
        "status": f.status, "source": f.source, "confidence": f.confidence, "flags": f.flags,
        "excerpt": f.source_excerpt, "proposed_value": mask(f.key, f.proposed_value) if f.proposed_value else "",
        "confirmed_at": f.confirmed_at,
    }


def document_detail(ctx: P.AccessContext, d: Document) -> dict:
    caps = ctx.doc_caps(d)
    data = document_row(ctx, d)
    data.update({
        "title_is_custom": d.title_is_custom,
        "correspondent": {"id": d.correspondent_id, "name": d.correspondent.name} if d.correspondent_id else None,
        "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in d.tags.all()],
        "review_flags": d.review_flags,
        "inherit_permissions": d.inherit_permissions,
        "fields": [field_json(f) for f in d.fields.all().order_by("key")],
        "versions": [version_json(v) for v in d.versions.select_related("created_by")],
        "current_version": version_json(d.current_version) if d.current_version else None,
        "path": [{"id": str(f.id), "name": f.name, "emoji": f.emoji} for f in _visible_path(ctx, d.folder)],
        "renews": _link(ctx, d.renews),
        "renewed_by": [_link(ctx, r) for r in d.renewed_by.all() if ctx.can(r, P.VIEW)],
        "source_path": d.source_path if caps & P.EDIT else "",
        "history": [{"at": h.at, "action": h.action, "changes": h.changes,
                     "actor": h.actor.display_name if h.actor_id and h.actor else None}
                    for h in d.history.select_related("actor")[:50]] if caps & P.EDIT else [],
        "archived_at": d.archived_at,
    })
    return data


def _link(ctx, d):
    if d is None or not ctx.can(d, P.VIEW):
        return None
    return {"id": str(d.id), "title": d.title}


def _visible_path(ctx: P.AccessContext, folder: Folder) -> list[Folder]:
    from .services import folder_path

    return [f for f in folder_path(folder) if ctx.folder_caps(f.id) & P.VIEW or f.parent_id is None]


def folder_json(ctx: P.AccessContext, f: Folder, counts: dict | None = None, path_only: bool = False) -> dict:
    caps = ctx.folder_caps(f.id)
    return {
        "id": str(f.id), "parent": str(f.parent_id) if f.parent_id else None, "name": f.name, "emoji": f.emoji,
        "emoji_is_custom": f.emoji_is_custom, "kind": f.kind, "owner": str(f.owner_id) if f.owner_id else None,
        "inherit_permissions": f.inherit_permissions, "caps": [] if path_only else P.names(caps),
        "path_only": path_only, "count": (counts or {}).get(f.id, 0), "archived": f.archived_at is not None,
        # Identity of a member's personal area (name + avatar) for the tree; never used for authorisation.
        "owner_user": user_mini(f.owner) if f.kind == Folder.PERSONAL_ROOT and f.owner_id else None,
    }
