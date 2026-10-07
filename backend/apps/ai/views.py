"""Local AI API: profiles (admin), status, suggestions, assistant, semantic search, job visibility."""
from __future__ import annotations

import time

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin
from apps.core import audit, crypto
from apps.library import permissions as P
from apps.library.models import Document

from . import jobs as ai_jobs
from . import service
from .models import AIJob, AIProfile, AISuggestion
from .providers import RANK, AIError, check_privacy, classify_endpoint, provider_for

STATUS_FOR = {"unavailable": 503, "timeout": 504, "bad_response": 502, "model_missing": 502, "auth": 502,
              "privacy": 409, "disabled": 409, "config": 400, "other": 500}


def _ai_error(exc: AIError, **extra):
    return Response({"error": str(exc), "category": exc.category, **extra}, status=STATUS_FOR.get(exc.category, 500))


def _fail(msg: str, status: int = 400, **extra):
    return Response({"error": msg, **extra}, status=status)


# ------------------------------------------------------------------ profiles (main administrator)

def profile_json(p: AIProfile) -> dict:
    return {"id": p.id, "name": p.name, "enabled": p.enabled, "is_default": p.is_default, "provider": p.provider,
            "base_url": p.base_url, "api_key_configured": bool(p.api_key_enc), "text_model": p.text_model,
            "vision_model": p.vision_model, "embedding_model": p.embedding_model, "timeout_seconds": p.timeout_seconds,
            "max_input_chars": p.max_input_chars, "max_output_tokens": p.max_output_tokens, "privacy": p.privacy,
            "external_acknowledged": p.external_acknowledged, "features": p.features, "updated_at": p.updated_at}


def _apply_profile(p: AIProfile, d: dict, user) -> None:
    for field, limit in (("name", 80), ("base_url", 300), ("text_model", 200), ("vision_model", 200), ("embedding_model", 200)):
        if field in d:
            setattr(p, field, (d.get(field) or "").strip()[:limit])
    if "provider" in d:
        if d["provider"] not in ("openai", "ollama"):
            raise ValueError("Choose OpenAI-compatible or Ollama.")
        p.provider = d["provider"]
    for field, lo, hi in (("timeout_seconds", 5, 600), ("max_input_chars", 1000, 200000), ("max_output_tokens", 64, 8192)):
        if field in d:
            try:
                value = int(d[field])
            except (TypeError, ValueError):
                raise ValueError(f"{field.replace('_', ' ')} must be a number.")
            if not lo <= value <= hi:
                raise ValueError(f"{field.replace('_', ' ')} must be between {lo} and {hi}.")
            setattr(p, field, value)
    if "privacy" in d:
        if d["privacy"] not in RANK:
            raise ValueError("Choose Local only, Private LAN or External endpoint.")
        p.privacy = d["privacy"]
    if "external_acknowledged" in d:
        p.external_acknowledged = bool(d["external_acknowledged"])
    if p.privacy != "external":
        p.external_acknowledged = False
    if "features" in d:
        feats = [f for f in (d.get("features") or []) if f in service.FEATURES]
        p.features = feats
    if "enabled" in d:
        p.enabled = bool(d["enabled"])
    if "is_default" in d:
        p.is_default = bool(d["is_default"])
    if d.get("api_key"):
        p.api_key_enc = crypto.encrypt(str(d["api_key"])[:500])
    if d.get("clear_api_key"):
        p.api_key_enc = ""
    if not p.name or not p.base_url:
        raise ValueError("Enter a name and the server URL.")
    actual = classify_endpoint(p.base_url)  # raises AIError for malformed URLs / unknown hosts
    if RANK[actual] > RANK[p.privacy]:
        raise ValueError(f"This URL is a {actual.upper()} endpoint. Select '{actual}' as the privacy class"
                         + (" and acknowledge that document text may leave your network." if actual == "external" else "."))
    if p.privacy == "external" and not p.external_acknowledged:
        raise ValueError("Acknowledge that selected document/OCR content may leave your local network.")
    p.updated_by = user


@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def profiles(request):
    if request.method == "GET":
        return Response({"profiles": [profile_json(p) for p in AIProfile.objects.all()], "features": service.FEATURES})
    p = AIProfile()
    try:
        _apply_profile(p, request.data, request.user)
    except ValueError as exc:
        return _fail(str(exc))
    except AIError as exc:
        return _ai_error(exc)
    if AIProfile.objects.filter(name=p.name).exists():
        return _fail("A profile with this name exists.")
    with transaction.atomic():
        if p.is_default or not AIProfile.objects.exists():
            AIProfile.objects.update(is_default=False)
            p.is_default = True
        p.save()
    audit.record("ai.profile_create", request=request, target=p, privacy=p.privacy, provider=p.provider)
    return Response(profile_json(p), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsMainAdmin])
def profile_detail(request, pk):
    p = get_object_or_404(AIProfile, pk=pk)
    if request.method == "DELETE":
        p.delete()
        audit.record("ai.profile_delete", request=request, target_type="aiprofile", target_id=str(pk))
        return Response(status=204)
    try:
        _apply_profile(p, request.data, request.user)
    except ValueError as exc:
        return _fail(str(exc))
    except AIError as exc:
        return _ai_error(exc)
    with transaction.atomic():
        if p.is_default:
            AIProfile.objects.exclude(pk=p.pk).update(is_default=False)
        p.save()
    audit.record("ai.profile_update", request=request, target=p, fields=[k for k in request.data.keys() if k != "api_key"])
    return Response(profile_json(p))


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def profile_test(request, pk):
    """Validate the endpoint: privacy class, reachability, model discovery and (optionally) a tiny prompt."""
    p = get_object_or_404(AIProfile, pk=pk)
    out = {"privacy_selected": p.privacy}
    started = time.monotonic()
    try:
        out["privacy_actual"] = check_privacy(p)
        prov = provider_for(p)
        out["models"] = prov.list_models()
        missing = [m for m in (p.text_model, p.vision_model, p.embedding_model) if m and out["models"] and m not in out["models"]]
        out["missing_models"] = missing
        if p.text_model and not missing:
            reply = prov.chat([{"role": "user", "content": "Reply with the single word OK."}], p.text_model)
            out["chat_ok"] = bool(reply.strip())
        if p.embedding_model and p.embedding_model not in missing:
            out["embedding_dimensions"] = len(prov.embed(["test"], p.embedding_model)[0])
    except AIError as exc:
        audit.record("ai.profile_test", request=request, target=p, outcome="failure", category=exc.category)
        return _ai_error(exc, **out)
    out["latency_ms"] = int((time.monotonic() - started) * 1000)
    out["ok"] = not out.get("missing_models")
    audit.record("ai.profile_test", request=request, target=p)
    return Response(out)


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def profile_models(request, pk):
    p = get_object_or_404(AIProfile, pk=pk)
    try:
        return Response({"models": provider_for(p).list_models()})
    except AIError as exc:
        return _ai_error(exc)


@api_view(["GET"])
@permission_classes([IsMainAdmin])
def ai_jobs_api(request):
    qs = AIJob.objects.select_related("requested_by", "profile")
    if request.query_params.get("status"):
        qs = qs.filter(status=request.query_params["status"])
    counts = {s: AIJob.objects.filter(status=s).count() for s in (AIJob.QUEUED, AIJob.RUNNING, AIJob.FAILED)}
    return Response({"counts": counts, "jobs": [{
        "id": str(j.id), "kind": j.kind, "document": str(j.document_id) if j.document_id else None,
        "requested_by": j.requested_by.display_name if j.requested_by_id and j.requested_by else None,
        "profile": j.profile.name if j.profile_id and j.profile else None, "model": j.model, "status": j.status,
        "error_category": j.error_category, "error": j.error, "attempts": j.attempts, "retryable": j.retryable,
        "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at} for j in qs[:100]]})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def reindex(request):
    if not service.enabled("semantic_search"):
        return _fail("Turn on semantic search first.", 409)
    from apps.library import ocr_policy

    n = 0
    for doc in Document.objects.filter(archived_at__isnull=True).exclude(content_text="").select_related("doc_type")[:5000]:
        if not ocr_policy.ai_allowed(doc):  # only types the administrator opened to Local AI
            continue
        ai_jobs.queue(AIJob.EMBED, document=doc, user=request.user)
        n += 1
    audit.record("ai.reindex", request=request, documents=n)
    return Response({"queued": n})


# ------------------------------------------------------------------ status, suggestions, assistant, semantic search

@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def ai_status(request):
    return Response(service.status_for(request.user))


def _require_ai(request, feature: str):
    if not service.user_allowed(request.user):
        raise PermissionDenied("AI features are limited to administrators in this installation.")
    if not service.enabled(feature):
        raise PermissionDenied(f"The AI feature '{feature.replace('_', ' ')}' is switched off.")


def _doc(request, pk, cap) -> tuple[Document, P.AccessContext]:
    from apps.library.views import get_doc

    doc = get_doc(request, pk, include_archived=False)  # 404 when not visible: no existence leak
    ctx = P.context_for(request)
    if not ctx.can(doc, cap):
        raise PermissionDenied("You cannot edit this document.")
    return doc, ctx


def suggestion_json(s: AISuggestion) -> dict:
    return {"id": s.id, "field": s.field, "value": s.value, "display": s.display, "current": s.current, "status": s.status,
            "created_at": s.created_at}


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def document_analyze(request, pk):
    if not service.user_allowed(request.user) or not (service.enabled("ocr_assist") or service.enabled("smart_organization")):
        raise PermissionDenied("AI document analysis is not available.")
    doc, _ctx = _doc(request, pk, P.EDIT)
    from apps.library import ocr_policy

    if not ocr_policy.ai_allowed(doc):
        raise PermissionDenied("Local AI is not allowed for this document type (Settings → OCR & processing).")
    if doc.current_version_id and doc.current_version.av_blocked:
        raise PermissionDenied("This file is in antivirus quarantine; Local AI cannot read it.")
    job = ai_jobs.queue(AIJob.ANALYZE, document=doc, user=request.user)
    audit.record("ai.analyze_requested", request=request, target=doc, subject_user=doc.owner)
    return Response({"job": str(job.id), "status": "queued"}, status=202)


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def document_suggestions(request, pk):
    doc, ctx = _doc(request, pk, P.VIEW)
    pending = doc.ai_suggestions.filter(status=AISuggestion.PENDING)
    last = AIJob.objects.filter(document=doc, kind=AIJob.ANALYZE).first()
    return Response({"suggestions": [suggestion_json(s) for s in pending], "can_edit": ctx.can(doc, P.EDIT),
                     "last_job": {"status": last.status, "error": last.error, "finished_at": last.finished_at} if last else None})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def suggestion_decide(request, pk, sid):
    from apps.library import services as S

    doc, _ctx = _doc(request, pk, P.EDIT)
    action = request.data.get("action")
    rows = list(doc.ai_suggestions.filter(status=AISuggestion.PENDING)) if sid == 0 else [get_object_or_404(AISuggestion, pk=sid, document=doc, status=AISuggestion.PENDING)]
    if action not in ("accept", "dismiss"):
        return _fail("Choose accept or dismiss.")
    done = []
    for s in rows:
        try:
            if action == "accept":
                service.accept(s, user=request.user, request=request)
            else:
                s.status = AISuggestion.DISMISSED
                s.decided_by = request.user
                from django.utils import timezone

                s.decided_at = timezone.now()
                s.save()
            done.append(s.field)
        except (S.DomainError, Exception) as exc:  # noqa: BLE001 - report which suggestion failed
            return _fail(f"Could not apply the {s.field.replace('_', ' ')} suggestion: {exc}", 400, applied=done)
    audit.record(f"ai.suggestion_{action}", request=request, target=doc, subject_user=doc.owner, fields=done)
    return Response({"applied": done})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def assistant(request):
    _require_ai(request, "assistant")
    ctx = P.context_for(request)
    doc = None
    if request.data.get("document"):
        doc, ctx = _doc(request, request.data["document"], P.VIEW)
    try:
        result = service.ask(ctx, request.user, request.data.get("question", ""), document=doc)
    except AIError as exc:
        return _ai_error(exc, sources=getattr(exc, "sources", []))
    audit.record("ai.assistant", request=request, sources=len(result["sources"]))  # never the question or answer
    return Response(result)


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def semantic(request):
    _require_ai(request, "semantic_search")
    q = (request.query_params.get("q") or "").strip()
    if not q:
        return Response({"results": []})
    ctx = P.context_for(request)
    try:
        hits = service.semantic_search(ctx, q)
    except AIError as exc:
        return _ai_error(exc)
    docs = {str(d.id): d for d in ctx.documents().filter(pk__in=[h["document_id"] for h in hits]).select_related("owner", "doc_type")}
    from apps.library.serializers import document_row

    return Response({"results": [{**document_row(ctx, docs[h["document_id"]]), "score": h["score"], "snippet": h["snippet"]}
                                 for h in hits if h["document_id"] in docs]})
