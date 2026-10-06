"""Selective OCR API: per-document controls, the review queue and the administrator's OCR type policy."""
from __future__ import annotations

from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin
from apps.core import audit, config

from . import ocr_policy, ocr_runs
from . import permissions as P
from .models import Document, DocumentField, DocumentType, DocumentVersion
from .serializers import field_json, ocr_json
from .views import _ctx, _err, get_doc


def _status(doc: Document, caps: int) -> dict:
    versions = list(DocumentVersion.objects.filter(document=doc).order_by("number"))
    texts = [{"version": str(v.id), "number": v.number, "name": v.original_name, "pages": v.ocr_pages,
              "text": v.text if v.ocr_applied else "", "quality": v.ocr_quality or None}
             for v in versions if v.ocr_applied]
    job = ocr_runs._active_job(doc)
    return {
        **ocr_json(doc),
        "can_run": bool(caps & P.EDIT) and ocr_policy.mode_for(doc) != "disabled",
        "can_edit": bool(caps & P.EDIT),
        "job": {"status": job.status, "queued_at": job.created_at} if job else None,
        "paused": bool(config.get("processing.ocr_paused")),
        "files": [{"version": str(v.id), "number": v.number, "name": v.original_name, "format": v.format_class,
                   "page_count": v.page_count, "size": v.size, "current": v.id == doc.current_version_id,
                   "additional": v.is_additional, "ocr_applied": v.ocr_applied, "ocr_pages": v.ocr_pages,
                   "ocrable": v.format_class in ocr_runs.OCRABLE} for v in versions],
        "results": texts,
        "languages_available": [lang for lang in ocr_policy.language_status() if lang["configured"]],
        "fields": [field_json(f) for f in doc.fields.all().order_by("key")],
    }


@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def document_ocr(request, pk):
    """GET status · POST run/re-run on chosen sources · DELETE remove OCR data (original kept)."""
    ctx = _ctx(request)
    if request.method == "GET":
        doc = get_doc(request, pk)
        return Response(_status(doc, ctx.doc_caps(doc)))
    doc = get_doc(request, pk, P.EDIT)
    if request.method == "DELETE":
        if request.data.get("confirm") is not True:
            return _err("Confirm that recognised text and suggestions should be removed (the original file stays).",
                        code="confirm_required")
        try:
            result = ocr_runs.remove_ocr(actor=request.user, doc=doc, request=request)
        except ocr_runs.OCRError as exc:
            return _err(str(exc))
        doc.refresh_from_db()
        return Response({**result, **_status(doc, ctx.doc_caps(doc))})
    d = request.data
    rotate = d.get("rotate")
    if rotate not in (None, "", "auto"):
        try:
            rotate = int(rotate)
        except (TypeError, ValueError):
            rotate = -1
        if rotate not in (0, 90, 180, 270):
            return _err("Rotation must be auto, 0, 90, 180 or 270.")
    else:
        rotate = None
    sources = d.get("sources")
    if sources is not None and not isinstance(sources, list):
        return _err("Sources must be a list of files.")
    try:
        ocr_runs.request_ocr(actor=request.user, doc=doc, sources=sources, languages=d.get("languages") or [],
                             rotate=rotate, set_primary=d.get("set_primary", True) is not False, request=request)
    except ocr_runs.OCRError as exc:
        return _err(str(exc))
    doc.refresh_from_db()
    return Response(_status(doc, ctx.doc_caps(doc)), status=202)


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def document_ocr_cancel(request, pk):
    doc = get_doc(request, pk, P.EDIT)
    if not ocr_runs.cancel_ocr(actor=request.user, doc=doc, request=request):
        return _err("Only queued text recognition can be cancelled; it may already be running or finished.")
    doc.refresh_from_db()
    return Response(_status(doc, _ctx(request).doc_caps(doc)))


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def document_ocr_reviewed(request, pk):
    """Mark the recognised text as reviewed (remaining suggestions can still be confirmed later)."""
    doc = get_doc(request, pk, P.EDIT)
    ocr_runs.mark_reviewed(actor=request.user, doc=doc, request=request)
    doc.refresh_from_db()
    return Response(_status(doc, _ctx(request).doc_caps(doc)))


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def ocr_review_queue(request):
    """Documents waiting for review that the person may edit. Nothing else is listed or counted."""
    ctx = _ctx(request)
    qs = (ctx.documents(P.EDIT).filter(Q(ocr_state="needs_review") | Q(ocr_state="failed"))
          .select_related("owner", "doc_type", "current_version").order_by("-ocr_updated_at")[:200])
    items = []
    for d in qs:
        proposed = list(d.fields.filter(status=DocumentField.PROPOSED).order_by("key"))
        v = d.current_version
        items.append({
            "id": str(d.id), "title": d.title, "owner": {"id": str(d.owner_id), "display_name": d.owner.display_name},
            "type": d.doc_type.name if d.doc_type_id else None, "ocr_state": d.ocr_state, "error": d.ocr_error,
            "updated_at": d.ocr_updated_at, "sources": d.ocr_sources, "languages": d.ocr_languages,
            "confidence": (v.ocr_quality or {}).get("confidence") if v else None,
            "proposed": [field_json(f) for f in proposed],
        })
    return Response({"items": items})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def ocr_languages(request):
    return Response({"languages": ocr_policy.language_status(), "missing": ocr_policy.missing_languages()})


def _type_json(t: DocumentType) -> dict:
    return {"id": t.id, "name": t.name, "template": t.template, "emoji": t.emoji, "has_expiry": t.has_expiry,
            "ocr_mode": t.ocr_mode, "ocr_languages": t.ocr_languages, "ocr_fields": t.ocr_fields,
            "ocr_ai_allowed": t.ocr_ai_allowed, "is_custom": t.is_custom, "archived": t.archived,
            "documents": t.documents.count()}


@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def ocr_types(request):
    """The administrator's OCR policy per document type; POST adds a custom type."""
    if request.method == "GET":
        return Response({"types": [_type_json(t) for t in DocumentType.objects.all()],
                         "templates": list(DocumentType.TEMPLATES), "fields": list(DocumentField.STANDARD),
                         "template_fields": ocr_policy.TEMPLATE_FIELDS, "languages": ocr_policy.language_status()})
    d = request.data
    name = (d.get("name") or "").strip()[:80]
    if not name:
        return _err("Enter a name for the document type.")
    if DocumentType.objects.filter(name__iexact=name).exists():
        return _err("A document type with this name already exists.")
    template = d.get("template") or "generic"
    if template not in DocumentType.TEMPLATES:
        return _err("Unknown template.")
    t = DocumentType(name=name, template=template, is_custom=True, emoji=(d.get("emoji") or "📄")[:16],
                     has_expiry=bool(d.get("has_expiry")), ocr_fields=ocr_policy.TEMPLATE_FIELDS.get(template, []))
    err = _apply_type(t, d)
    if err:
        return _err(err)
    t.save()
    audit.record("settings.ocr_type_create", request=request, target_type="document_type", target_id=str(t.id), name=name)
    return Response(_type_json(t), status=201)


def _apply_type(t: DocumentType, d) -> str:
    if "ocr_mode" in d:
        if d["ocr_mode"] not in DocumentType.OCR_MODES:
            return "OCR mode must be disabled, manual or automatic."
        t.ocr_mode = d["ocr_mode"]
    if "ocr_languages" in d:
        langs = d["ocr_languages"] if isinstance(d["ocr_languages"], list) else []
        offered = set(ocr_policy.configured_languages())
        if not langs or any(x not in offered for x in langs):
            return "Choose at least one of the offered OCR languages."
        t.ocr_languages = list(dict.fromkeys(langs))
    if "ocr_fields" in d:
        fields = d["ocr_fields"] if isinstance(d["ocr_fields"], list) else []
        if any(f not in DocumentField.STANDARD for f in fields):
            return "Unknown structured field."
        t.ocr_fields = list(dict.fromkeys(fields))
    if "ocr_ai_allowed" in d:
        t.ocr_ai_allowed = bool(d["ocr_ai_allowed"])
    if "archived" in d:
        t.archived = bool(d["archived"])
    if "name" in d and t.is_custom:
        name = (d.get("name") or "").strip()[:80]
        if not name or DocumentType.objects.filter(name__iexact=name).exclude(pk=t.pk).exists():
            return "Enter a unique name."
        t.name = name
    return ""


@api_view(["PATCH", "DELETE"])
@permission_classes([IsMainAdmin])
def ocr_type_detail(request, pk):
    t = DocumentType.objects.filter(pk=pk).first()
    if t is None:
        return _err("Unknown document type.", 404)
    if request.method == "DELETE":
        # types in use are never deleted: archive them (or move their documents to another type first)
        if t.documents.exists() or not t.is_custom:
            return _err("This type is in use or built in, so it cannot be deleted. Archive it instead; documents keep it.",
                        409)
        audit.record("settings.ocr_type_delete", request=request, target_type="document_type", target_id=str(t.id))
        t.delete()
        return Response(status=204)
    err = _apply_type(t, request.data)
    if err:
        return _err(err)
    t.save()
    audit.record("settings.ocr_type_update", request=request, target_type="document_type", target_id=str(t.id),
                 fields=sorted(request.data.keys()))
    return Response(_type_json(t))
