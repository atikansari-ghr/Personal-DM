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
              "privacy": 409, "disabled": 409, "config": 400, "other": 500, "bad_request": 502, "too_large": 502,
              "server_error": 502, "model_role": 409}


def _ai_error(exc: AIError, **extra):
    return Response({"error": str(exc), "category": exc.category, **exc.detail(), **extra},
                    status=STATUS_FOR.get(exc.category, 500))


def _fail(msg: str, status: int = 400, **extra):
    return Response({"error": msg, **extra}, status=status)


# ------------------------------------------------------------------ profiles (main administrator)

def profile_json(p: AIProfile) -> dict:
    return {"id": p.id, "name": p.name, "enabled": p.enabled, "is_default": p.is_default, "provider": p.provider,
            "base_url": p.base_url, "api_key_configured": bool(p.api_key_enc), "text_model": p.text_model,
            "vision_model": p.vision_model, "embedding_model": p.embedding_model, "timeout_seconds": p.timeout_seconds,
            "max_input_chars": p.max_input_chars, "max_output_tokens": p.max_output_tokens, "privacy": p.privacy,
            "external_acknowledged": p.external_acknowledged, "features": p.features, "updated_at": p.updated_at,
            "capabilities": p.capabilities or {}}


def _apply_profile(p: AIProfile, d: dict, user) -> None:
    before = (p.provider, p.base_url, p.text_model)
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
    # Change Set Y: model roles. The text model writes answers; the embedding model only makes search vectors.
    if p.text_model and p.embedding_model and p.text_model == p.embedding_model:
        raise ValueError("The text model and the embedding model must be different models.")
    if p.text_model and "embed" in p.text_model.lower() and "text_model" in d:
        raise ValueError(f"“{p.text_model}” looks like an embedding model. Choose a chat/text model as the text model.")
    if (p.provider, p.base_url, p.text_model) != before:
        p.capabilities = {}  # a different server or model: find out again what it supports
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


def _step(steps: list, name: str, ok, detail: str = "") -> None:
    steps.append({"step": name, "ok": ok, "detail": detail})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def profile_test(request, pk):
    """Test AI profile / connection: privacy class, reachability, model discovery, and each model in its own role
    (text model answers a tiny prompt; embedding model returns a vector; vision model optional)."""
    p = get_object_or_404(AIProfile, pk=pk)
    out = {"privacy_selected": p.privacy}
    steps: list = []
    started = time.monotonic()
    try:
        out["privacy_actual"] = check_privacy(p)
        _step(steps, "Endpoint and privacy class", True, out["privacy_actual"])
        prov = provider_for(p)
        out["models"] = prov.list_models()
        _step(steps, "Model discovery", True, f"{len(out['models'])} models listed")
        types = prov.model_types()
        missing = [m for m in (p.text_model, p.vision_model, p.embedding_model) if m and out["models"] and m not in out["models"]]
        out["missing_models"] = missing
        role_problem = ""
        if not p.text_model:
            role_problem = "No text model is selected."
        elif p.text_model in missing:
            role_problem = f"The text model “{p.text_model}” is not offered by the server."
        elif types.get(p.text_model) == "embeddings" or p.text_model == p.embedding_model:
            role_problem = f"“{p.text_model}” is an embedding model; choose a chat/text model."
        _step(steps, "Text model", not role_problem, role_problem or p.text_model)
        if p.embedding_model:
            emb_problem = "not offered by the server" if p.embedding_model in missing else (
                "this is a chat model, not an embedding model" if types.get(p.embedding_model) in ("llm", "vlm") else "")
            _step(steps, "Embedding model", not emb_problem, emb_problem or p.embedding_model)
        if p.vision_model:
            _step(steps, "Vision model (optional, not used by Analyze Document)", p.vision_model not in missing,
                  p.vision_model if p.vision_model not in missing else "not offered by the server")
        if not role_problem:
            reply = prov.chat([{"role": "user", "content": "Reply with the single word OK."}], p.text_model)
            out["chat_ok"] = bool(reply.strip())
            _step(steps, "Text model answers", out["chat_ok"], "")
        if p.embedding_model and p.embedding_model not in missing:
            out["embedding_dimensions"] = len(prov.embed(["test"], p.embedding_model)[0])
            _step(steps, "Embedding model returns a vector", True, f"{out['embedding_dimensions']} dimensions")
    except AIError as exc:
        _step(steps, "Failed", False, str(exc))
        audit.record("ai.profile_test", request=request, target=p, outcome="failure", category=exc.category)
        return _ai_error(exc, steps=steps, **out)
    out["latency_ms"] = int((time.monotonic() - started) * 1000)
    out["steps"] = steps
    out["ok"] = all(s["ok"] for s in steps)
    audit.record("ai.profile_test", request=request, target=p)
    return Response(out)


SAMPLE_TEXT = ("SYNTHETIC SAMPLE CERTIFICATE\nIssued by: Sample Licensing Office\nCertificate number: SAMPLE-12345\n"
               "Date of issue: 15 January 2024\nValid until: 14 January 2029\nHolder: Sample Person")


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def profile_test_analysis(request, pk):
    """Test AI analysis: a small synthetic text-only document through exactly the path Analyze Document uses
    (structured output with its one compatibility fallback, parsing and validation). No family data is sent."""
    p = get_object_or_404(AIProfile, pk=pk)
    started = time.monotonic()
    vocab = {"types": ["Certificate", "Passport", "Invoice"], "tags": ["sample"], "correspondents": ["Sample Licensing Office"]}
    try:
        data, info = service.run_analysis(p, SAMPLE_TEXT, keys=list(service.OCR_KEYS) + ["document_type", "correspondent", "tags"],
                                          vocab=vocab, folders={}, title="Test")
    except AIError as exc:
        audit.record("ai.profile_test_analysis", request=request, target=p, outcome="failure", category=exc.category)
        return _ai_error(exc, stage="ai_analysis")
    expected = {"issue_date": "2024-01-15", "expiry_date": "2029-01-14"}
    matched = [k for k, v in expected.items() if data.get(k) == v]
    p.refresh_from_db(fields=["capabilities"])
    audit.record("ai.profile_test_analysis", request=request, target=p)
    return Response({"ok": bool(data), "fields": data, "dates_correct": matched, "latency_ms": int((time.monotonic() - started) * 1000),
                     "structured_output": info.get("structured_output"), "fallback": info.get("fallback", False),
                     "capabilities": p.capabilities or {}})


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def test_ocr_engine(request):
    """Test OCR with one engine on a generated synthetic sample (never a family document)."""
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image, ImageDraw, ImageFont

    from apps.core import config
    from apps.library import ocr_admin

    engine = request.data.get("engine")
    if engine not in ("tesseract", "paddleocr"):
        return _fail("Choose Tesseract or PaddleOCR.")
    expected = "SAMPLE CERTIFICATE 12345"
    img = Image.new("RGB", (1200, 300), "white")
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 64)
    except OSError:
        font = ImageFont.load_default(size=64)
    ImageDraw.Draw(img).text((50, 110), expected, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    upload = SimpleUploadedFile("ocr-sample.png", buf.getvalue(), content_type="image/png")
    try:
        res = ocr_admin.test_ocr(upload=upload, engines=[engine], profile=config.get("processing.ocr_default_profile"),
                                 expected=expected, actor=request.user, request=request)
    except ValueError as exc:
        return _fail(str(exc))
    r = res["results"][0]
    text = r.get("text") or ""
    return Response({"engine": engine, "label": r.get("label"), "ok": bool(r.get("ok")) and service.usable_chars(text) > 0,
                     "text": text[:200], "chars": service.usable_chars(text), "accuracy": r.get("accuracy"),
                     "seconds": r.get("seconds"), "error": r.get("error", ""), "model": r.get("model", "")})


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
        "stage": j.stage, "stage_label": service.STAGE_LABELS.get(j.stage, ""), "detail": safe_detail(j.detail),
        "next_retry_at": j.next_retry_at, "max_attempts": ai_jobs.AI_MAX_ATTEMPTS,
        "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at} for j in qs[:100]]})


SAFE_DETAIL = ("ocr_engine", "ocr_pages", "ocr_chars", "ocr_reused", "ocr_requested", "model", "parts", "total_chars",
               "analyzed_chars", "truncated", "structured_output", "fallback", "rejected_capability", "http_status",
               "server_message", "capability")


def safe_detail(detail) -> dict:
    """Only the known, content-free facts of a job (counts, engine, HTTP status, sanitized server message)."""
    return {k: v for k, v in (detail or {}).items() if k in SAFE_DETAIL}


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def ai_job_retry(request, pk):
    """Retry a failed analysis (or embedding) after the cause was fixed: a new job; the failed one stays as it was."""
    j = get_object_or_404(AIJob, pk=pk)
    if j.status != AIJob.FAILED or j.kind not in (AIJob.ANALYZE, AIJob.EMBED) or j.document_id is None:
        return _fail("Only a failed analysis of a document can be retried.")
    if not service.user_allowed(request.user):
        raise PermissionDenied("AI features are limited to administrators in this installation.")
    doc, _ctx = _doc(request, j.document_id, P.EDIT)
    new = ai_jobs.queue(j.kind, document=doc, user=request.user, requested=True)
    audit.record("ai.job_retry", request=request, target=doc, subject_user=doc.owner, kind=j.kind)
    return Response({"job": str(new.id), "status": new.status}, status=202)


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
    existing = ai_jobs.active_analysis(doc)
    if existing is not None:  # one analysis at a time per document (now marked as asked for by a person)
        ai_jobs.queue(AIJob.ANALYZE, document=doc, user=request.user, requested=True)
        return Response({"job": str(existing.id), "status": existing.status, "stage": existing.stage, "already": True}, status=202)
    job = ai_jobs.queue(AIJob.ANALYZE, document=doc, user=request.user, requested=True)
    audit.record("ai.analyze_requested", request=request, target=doc, subject_user=doc.owner)
    return Response({"job": str(job.id), "status": "queued", "stage": job.stage}, status=202)


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def document_suggestions(request, pk):
    doc, ctx = _doc(request, pk, P.VIEW)
    pending = doc.ai_suggestions.filter(status=AISuggestion.PENDING)
    last = AIJob.objects.filter(document=doc, kind=AIJob.ANALYZE).first()
    return Response({"suggestions": [suggestion_json(s) for s in pending], "can_edit": ctx.can(doc, P.EDIT),
                     "last_job": {"id": str(last.id), "status": last.status, "error": last.error, "error_category": last.error_category,
                                  "stage": last.stage, "stage_label": service.STAGE_LABELS.get(last.stage, ""),
                                  "detail": safe_detail(last.detail), "next_retry_at": last.next_retry_at,
                                  "finished_at": last.finished_at} if last else None})


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
