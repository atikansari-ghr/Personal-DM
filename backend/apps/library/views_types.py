"""Document type assignment and administrator-managed type templates (Change Set N).

Assigning a type needs edit permission on the document (the same check as any detail edit). Managing the global
type templates is reserved for the main administrator. Every change is recorded in the document history and audit
log without document contents.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin
from apps.core import audit

from . import doctypes
from . import permissions as P
from . import services as S
from .models import Document, DocumentField, DocumentType, DocumentTypeField
from .serializers import document_detail
from .views import _ctx, _err, _rebuild, get_doc


def _type_or_none(value):
    if value in (None, "", "none"):
        return None
    if not str(value).isdigit():
        raise S.DomainError("Unknown document type.")
    t = DocumentType.objects.filter(pk=value).first()
    if t is None:
        raise S.DomainError("Unknown document type.")
    return t


# ------------------------------------------------------------------ one document

@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def document_type(request, pk):
    """Set / change / clear the type. `preview: true` returns what happens to each value without changing anything.
    `ignore: true` dismisses pending suggestions (all, or the one with `index`)."""
    doc = get_doc(request, pk, P.EDIT)
    d = request.data
    try:
        if d.get("ignore"):
            sug = list(doc.type_suggestions or [])
            idx = d.get("index")
            keep = [s for i, s in enumerate(sug) if idx is not None and str(i) != str(idx)]
            Document.objects.filter(pk=doc.pk).update(type_suggestions=keep)
            S._history(doc, request.user, "type_suggestion_ignored", count=len(sug) - len(keep))
            doc.refresh_from_db()
            return Response(document_detail(_ctx(request), doc))
        new_type = _type_or_none(d.get("type"))
        if d.get("preview"):
            return Response({"plan": doctypes.plan_change(doc, new_type)})
        source = d.get("source") if d.get("source") in ("manual", "folder", "ocr", "ai") else "manual"
        doctypes.change_type(actor=request.user, doc=doc, new_type=new_type, source=source, request=request)
    except S.DomainError as exc:
        return _err(str(exc))
    doc.refresh_from_db()
    return Response(document_detail(_rebuild(request), doc))


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def document_remap_ocr(request, pk):
    """Suggest values for the current type from the text already recognised (no new scan)."""
    doc = get_doc(request, pk, P.EDIT)
    try:
        n = doctypes.remap_ocr(actor=request.user, doc=doc)
    except S.DomainError as exc:
        return _err(str(exc))
    audit.record("document.ocr_remap", request=request, target=doc, subject_user=doc.owner, suggestions=n)
    doc.refresh_from_db()
    if n and doc.ocr_state in ("confirmed", "not_processed"):
        Document.objects.filter(pk=doc.pk).update(ocr_state="needs_review")
        doc.ocr_state = "needs_review"
    return Response({"suggestions": n, "document": document_detail(_ctx(request), doc)})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def bulk_type(request):
    """Apply one type to several documents. Without `overwrite_confirmed`, documents that already have another
    confirmed type are skipped. `preview: true` reports counts first."""
    ctx = _ctx(request)
    d = request.data
    ids = [str(i) for i in (d.get("ids") or [])][:500]
    if not ids:
        return _err("Select at least one document.")
    try:
        new_type = _type_or_none(d.get("type"))
    except S.DomainError as exc:
        return _err(str(exc))
    if new_type is None:
        return _err("Choose a document type.")
    if new_type.archived:
        return _err("This document type is archived. Choose an active type.")
    docs = list(Document.objects.filter(pk__in=ids, archived_at__isnull=True).select_related("doc_type", "owner"))
    allowed = [x for x in docs if ctx.doc_caps(x) & P.EDIT]
    visible = [x for x in docs if ctx.doc_caps(x) & P.VIEW]
    current: dict[str, int] = {}
    for x in allowed:
        k = x.doc_type.name if x.doc_type_id else "Not assigned"
        current[k] = current.get(k, 0) + 1
    confirmed_other = [x for x in allowed if x.type_confirmed and x.doc_type_id and x.doc_type_id != new_type.pk]
    already = [x for x in allowed if x.doc_type_id == new_type.pk]
    summary = {"selected": len(visible), "allowed": len(allowed), "not_allowed": len(visible) - len(allowed),
               "current": current, "confirmed_other": len(confirmed_other), "already": len(already), "type": new_type.name}
    if d.get("preview"):
        return Response(summary)
    overwrite = bool(d.get("overwrite_confirmed"))
    changed = skipped = 0
    unmapped = 0
    for x in allowed:
        if x.doc_type_id == new_type.pk or (x in confirmed_other and not overwrite):
            skipped += 1
            continue
        plan = doctypes.change_type(actor=request.user, doc=x, new_type=new_type, source="manual", request=request)
        unmapped += len(plan["unmapped"])
        changed += 1
    audit.record("document.bulk_type", request=request, type=new_type.name, changed=changed, skipped=skipped)
    return Response({**summary, "changed": changed, "skipped": skipped, "unmapped_values": unmapped})


# ------------------------------------------------------------------ administrator: types and templates

def _types_payload():
    from .ocr_policy import language_status

    return {"types": [doctypes.type_json(t, admin=True) for t in DocumentType.objects.prefetch_related("template_fields")],
            "field_types": list(DocumentTypeField.TYPES), "roles": [r for r in DocumentTypeField.ROLES if r],
            "templates": list(DocumentType.TEMPLATES), "standard_fields": {k: v[0] for k, v in doctypes.STANDARD.items()},
            "languages": language_status(), "report": doctypes.report()}


def _apply_type_settings(t: DocumentType, d) -> None:
    from .ocr_views import _apply_type

    if "name" in d:
        name = (d.get("name") or "").strip()[:80]
        if not name or DocumentType.objects.filter(name__iexact=name).exclude(pk=t.pk).exists():
            raise S.DomainError("Enter a unique name for the document type.")
        t.name = name
    if "emoji" in d:
        t.emoji = (d.get("emoji") or "").strip()[:16]
    if "description" in d:
        t.description = (d.get("description") or "").strip()[:500]
    if "has_expiry" in d:
        t.has_expiry = bool(d["has_expiry"])
    if "sort_order" in d:
        try:
            t.sort_order = int(d["sort_order"])
        except (TypeError, ValueError):
            raise S.DomainError("Order must be a number.") from None
    if "reminder_days" in d:
        raw = d["reminder_days"] if isinstance(d["reminder_days"], list) else str(d["reminder_days"] or "").split(",")
        try:
            days = sorted({int(str(x).strip()) for x in raw if str(x).strip()}, reverse=True)
        except ValueError:
            raise S.DomainError("Reminder days must be whole numbers, e.g. 90, 30, 7.") from None
        if any(x < 0 or x > 3650 for x in days):
            raise S.DomainError("Reminder days must be between 0 and 3650.")
        t.reminder_days = days
    err = _apply_type(t, {k: v for k, v in d.items() if k in ("ocr_mode", "ocr_languages", "ocr_ai_allowed", "archived")})
    if err:
        raise S.DomainError(err)


@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def types_admin(request):
    if request.method == "GET":
        return Response(_types_payload())
    d = request.data
    name = (d.get("name") or "").strip()[:80]
    if not name:
        return _err("Enter a name for the document type.")
    if DocumentType.objects.filter(name__iexact=name).exists():
        return _err("A document type with this name already exists.")
    template = d.get("template") or "generic"
    if template not in DocumentType.TEMPLATES:
        return _err("Unknown starting template.")
    t = DocumentType(name=name, template=template, is_custom=True, emoji="📄", ocr_languages=["eng"])
    try:
        _apply_type_settings(t, {k: v for k, v in d.items() if k != "name"})
        t.save()
        if d.get("copy_from"):
            src = DocumentType.objects.filter(pk=d["copy_from"]).first()
            for f in src.template_fields.all() if src else []:
                DocumentTypeField.objects.create(doc_type=t, **{k: getattr(f, k) for k in (
                    "key", "label", "field_type", "enabled", "required", "order", "help_text", "extract", "searchable",
                    "role", "choices", "validation")})
            doctypes.sync_ocr_fields(t)
        else:
            doctypes.ensure_template(t)
    except S.DomainError as exc:
        return _err(str(exc))
    audit.record("settings.document_type_create", request=request, target_type="document_type", target_id=str(t.pk),
                 name=t.name)
    return Response(doctypes.type_json(t, admin=True), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsMainAdmin])
def type_admin_detail(request, pk):
    t = DocumentType.objects.filter(pk=pk).first()
    if t is None:
        return _err("Unknown document type.", 404)
    if request.method == "DELETE":
        in_use = t.documents.count()
        target = request.data.get("reassign_to") if hasattr(request, "data") else None
        if in_use and not target:
            return _err(f"{in_use} document(s) use this type, so it cannot be deleted. Archive it (documents keep it) "
                        "or move its documents to another type first.", 409, code="in_use", documents=in_use)
        if in_use:
            new_t = DocumentType.objects.filter(pk=target, archived=False).exclude(pk=t.pk).first()
            if new_t is None:
                return _err("Choose an active type to move the documents to.")
            for doc in t.documents.select_related("doc_type", "owner"):
                doctypes.change_type(actor=request.user, doc=doc, new_type=new_t, source="system", request=request)
        audit.record("settings.document_type_delete", request=request, target_type="document_type", target_id=str(t.pk),
                     name=t.name, moved=in_use)
        DocumentType.objects.filter(pk=t.pk).delete()
        return Response(status=204)
    try:
        _apply_type_settings(t, request.data)
        t.save()
    except S.DomainError as exc:
        return _err(str(exc))
    audit.record("settings.document_type_update", request=request, target_type="document_type", target_id=str(t.pk),
                 fields=sorted(request.data.keys()))
    return Response(doctypes.type_json(t, admin=True))


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def type_fields(request, pk):
    """Add a template field, or `reorder` with the list of field ids, or `promote` a document's one-off detail."""
    t = DocumentType.objects.filter(pk=pk).first()
    if t is None:
        return _err("Unknown document type.", 404)
    d = request.data
    try:
        if "reorder" in d:
            ids = [int(x) for x in d["reorder"] if str(x).isdigit()]
            with transaction.atomic():
                for i, fid in enumerate(ids):
                    DocumentTypeField.objects.filter(doc_type=t, pk=fid).update(order=(i + 1) * 10)
            audit.record("settings.document_type_fields_reorder", request=request, target_type="document_type",
                         target_id=str(t.pk))
            return Response(doctypes.type_json(t, admin=True))
        if d.get("promote"):
            doc = get_doc(request, d.get("document"), P.VIEW)
            doctypes.promote(actor=request.user, doc_type=t, doc=doc, key=str(d.get("key") or ""), request=request)
            return Response(doctypes.type_json(t, admin=True), status=201)
        clean = doctypes.validate_template_field(d)
        if t.template_fields.filter(key=clean["key"]).exists():
            return _err("This type already has a field with that key.")
        std = doctypes.STANDARD.get(clean["key"])
        defaults = {"field_type": std[1] if std else "text", "role": std[2] if std else "",
                    "searchable": std[3] if std else True, "choices": list(std[4]) if std else [],
                    "extract": bool(std),
                    "order": (t.template_fields.order_by("-order").values_list("order", flat=True).first() or 0) + 10}
        f = DocumentTypeField.objects.create(doc_type=t, **{**defaults, **clean})
        doctypes.sync_ocr_fields(t)
    except S.DomainError as exc:
        return _err(str(exc))
    audit.record("settings.document_type_field_create", request=request, target_type="document_type",
                 target_id=str(t.pk), key=f.key)
    return Response(doctypes.type_json(t, admin=True), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsMainAdmin])
def type_field_detail(request, pk, fid):
    f = DocumentTypeField.objects.filter(doc_type_id=pk, pk=fid).select_related("doc_type").first()
    if f is None:
        return _err("Unknown field.", 404)
    t = f.doc_type
    if request.method == "DELETE":
        used = DocumentField.objects.filter(document__doc_type=t, key=f.key).exclude(value="").count()
        if used:
            return _err(f"{used} document(s) have a value for this field. Turn the field off instead; the values "
                        "are kept.", 409, code="in_use", documents=used)
        audit.record("settings.document_type_field_delete", request=request, target_type="document_type",
                     target_id=str(t.pk), key=f.key)
        f.delete()
        doctypes.sync_ocr_fields(t)
        return Response(doctypes.type_json(t, admin=True))
    try:
        clean = doctypes.validate_template_field(request.data, existing=f)
    except S.DomainError as exc:
        return _err(str(exc))
    for k, v in clean.items():
        setattr(f, k, v)
    f.save()
    doctypes.sync_ocr_fields(t)
    affected = list(Document.objects.filter(doc_type=t, archived_at__isnull=True)
                    .filter(fields__key=f.key).distinct()[:2000]) if {"role", "enabled"} & set(clean) else []
    for doc in affected:  # a changed expiry role re-derives dates and reminders from confirmed values only
        S.apply_confirmed_fields(doc)
    audit.record("settings.document_type_field_update", request=request, target_type="document_type",
                 target_id=str(t.pk), key=f.key, fields=sorted(clean.keys()))
    return Response(doctypes.type_json(t, admin=True))


@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def type_review(request):
    """Untyped documents with a folder or OCR suggestion, for an explicit review (never a silent mass change)."""
    if request.method == "GET":
        rows = []
        qs = (Document.objects.filter(archived_at__isnull=True, doc_type__isnull=True)
              .select_related("folder", "owner").order_by("-created_at")[:2000])
        for doc in qs:
            sugg = doctypes.suggestions_json(doc)
            hint = doctypes.folder_suggestion(doc.folder)
            if hint is not None and not any(s["type"] == hint.id and s["source"] == "folder" for s in sugg):
                sugg.append({"index": None, "type": hint.id, "name": hint.name, "source": "folder",
                             "source_label": "Folder suggestion", "reason": f"Folder '{doc.folder.name}' suggests it.",
                             "confidence": None})
            if not sugg:
                continue
            if len({s["type"] for s in sugg}) > 1:
                for s in sugg:
                    s["conflict"] = True
            rows.append({"id": str(doc.id), "title": doc.title, "owner": doc.owner.display_name,
                         "folder": doc.folder.name, "suggestions": sugg})
            if len(rows) >= 300:
                break
        return Response({"items": rows, "report": doctypes.report()})
    applied = 0
    for item in (request.data.get("items") or [])[:300]:
        doc = Document.objects.filter(pk=item.get("id"), archived_at__isnull=True).select_related("owner", "doc_type").first()
        t = DocumentType.objects.filter(pk=item.get("type"), archived=False).first() if str(item.get("type") or "").isdigit() else None
        if doc is None or t is None or doc.type_confirmed:
            continue
        source = item.get("source") if item.get("source") in ("folder", "ocr", "ai") else "manual"
        doctypes.change_type(actor=request.user, doc=doc, new_type=t, source=source, request=request)
        applied += 1
    audit.record("document.type_review", request=request, applied=applied)
    return Response({"applied": applied, "report": doctypes.report()})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def types_list(request):
    """Active types for selectors (any signed-in person)."""
    types = DocumentType.objects.filter(archived=False)
    return Response({"types": [doctypes.type_json(t) for t in types]})
