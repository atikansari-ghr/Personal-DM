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
        "ocr_applied": v.ocr_applied, "ocr_pages": v.ocr_pages, "is_additional": v.is_additional, "pdfa": v.pdfa,
        "page_count": v.page_count,
        "ocr_quality": {k: v.ocr_quality.get(k) for k in ("confidence", "rotation", "skew", "steps", "low_lines", "line_count", "languages", "pages", "engine")}
        if v.ocr_quality else None,
        "pdfa_check": {k: v.pdfa_report.get(k) for k in ("validator", "profile", "compliant", "full_validation", "failed_rules", "note")} if v.pdfa_report else None,
        "has_preview": bool(v.preview_path or v.searchable_path or v.format_class in ("pdf", "image", "text")),
        "has_thumbnail": bool(v.thumbnail_path), "created_at": v.created_at,
        "created_by": v.created_by.display_name if v.created_by_id and v.created_by else None,
        "antivirus": {"status": v.av_status, "signature": v.av_signature, "engine": v.av_engine, "detail": v.av_detail,
                      "scanned_at": v.av_scanned_at, "blocked": v.av_blocked,
                      "released_at": v.av_released_at if v.av_status == "released" else None},
    }


def document_row(ctx: P.AccessContext, d: Document, snippet: str | None = None) -> dict:
    v = d.current_version
    row = {
        "id": str(d.id), "title": d.title, "folder": str(d.folder_id), "owner": user_mini(d.owner),
        "type": {"id": d.doc_type_id, "name": d.doc_type.name, "emoji": d.doc_type.emoji,
                 "confirmed": d.type_confirmed} if d.doc_type_id else None,
        "type_suggested": bool(d.type_suggestions) and not d.type_confirmed,
        "state": d.state, "expiry_date": d.expiry_date, "issue_date": d.issue_date, "expiry": expiry_status(d),
        "no_expiry": d.no_expiry, "ocr_state": d.ocr_state, "av_status": v.av_status if v else None,
        "created_at": d.created_at, "archived": d.archived_at is not None,
        "size": v.size if v else None, "format": v.format_class if v else None, **filetypes.describe(v),
        "has_thumbnail": bool(v and v.thumbnail_path), "version_id": str(v.id) if v else None,
        "caps": P.names(ctx.doc_caps(d)),
    }
    if snippet is not None:
        row["snippet"] = snippet
    return row


def field_json(f: DocumentField, labels: dict | None = None) -> dict:
    from .doctypes import SOURCE_LABELS, standard_label

    labels = labels or {}
    return {
        "key": f.key, "value": mask(f.key, f.value), "sensitive": f.key in DocumentField.SENSITIVE,
        "label": labels.get(f.key) or f.label or standard_label(f.key.removeprefix("custom:")),
        "status": f.status, "source": f.source, "source_label": SOURCE_LABELS.get(f.source, f.source),
        "scope": f.scope, "overridden": f.overridden, "previous_type": f.previous_type,
        "confidence": f.confidence, "flags": f.flags,
        "excerpt": f.source_excerpt, "proposed_value": mask(f.key, f.proposed_value) if f.proposed_value else "",
        "confirmed_at": f.confirmed_at, "updated_at": f.updated_at,
        "confirmed_by": f.confirmed_by.display_name if f.confirmed_by_id and f.confirmed_by else None,
    }


def _classification(ctx: P.AccessContext, d: Document) -> dict:
    """Type, its template, values grouped by template / additional / previous, and the Details status."""
    from . import doctypes
    from .models import CustomFieldDef

    template = doctypes.active_fields(d.doc_type) if d.doc_type_id else []
    labels = {f.key: f.label for f in template}
    labels.update({f"custom:{c.key}": c.label for c in CustomFieldDef.objects.all()})
    fields = list(d.fields.select_related("confirmed_by").order_by("key"))
    tkeys = {f.key for f in template}
    out_fields = []
    for f in fields:
        j = field_json(f, labels)
        if f.scope == DocumentField.UNMAPPED:
            j["group"] = "unmapped"
        elif f.scope == DocumentField.TYPE and (f.key in tkeys or not template):
            j["group"] = "template"
        else:
            j["group"] = "additional"
        out_fields.append(j)
    order = {f.key: f.order for f in template}
    out_fields.sort(key=lambda j: (order.get(j["key"], 10_000), j["label"].lower()))
    is_admin = bool(getattr(ctx.user, "is_main_admin", False))
    return {
        "fields": out_fields,
        "template": [{"key": f.key, "label": f.label, "field_type": f.field_type, "required": f.required,
                      "help_text": f.help_text, "choices": f.choices, "role": f.role,
                      "sensitive": f.key in DocumentField.SENSITIVE} for f in template],
        "type_info": {"source": d.type_source, "source_label": doctypes.SOURCE_LABELS.get(d.type_source, ""),
                      "confirmed": d.type_confirmed, "suggestions": doctypes.suggestions_json(d)},
        "details_status": doctypes.details_status(d),
        "can_manage_types": is_admin,
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
        **_classification(ctx, d),
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
        "ocr": ocr_json(d),
    })
    return data


def ocr_json(d: Document) -> dict:
    from . import ocr_policy

    return {"state": d.ocr_state, "mode": ocr_policy.mode_for(d), "sources": d.ocr_sources or [],
            "languages": d.ocr_languages or [], "default_languages": ocr_policy.default_languages(d),
            "error": d.ocr_error, "updated_at": d.ocr_updated_at, "ai_allowed": ocr_policy.ai_allowed(d)}


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
        "suggested_type": ({"id": f.suggested_type_id, "name": f.suggested_type.name}
                           if f.suggested_type_id and not path_only else None),
    }
