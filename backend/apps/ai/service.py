"""Local AI features on top of the deterministic pipeline.

Upload -> validation -> original stored -> native text / Tesseract OCR -> (optional) AI analysis -> AISuggestion rows
-> person reviews and accepts -> normal metadata services apply the change (same permission checks as manual edits).

Retrieval for the assistant and semantic search always starts from AccessContext.documents(VIEW): documents the
signed-in person cannot open are never read, embedded into a prompt, scored or counted, so revoking access
revokes AI retrieval immediately. Prompts and replies are not logged (unless ai.debug_logging, which logs sizes only).
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core import config

from .models import AIJob, AIProfile, AISuggestion, DocumentChunk
from .providers import AIError, parse_json_object, provider_for

log = logging.getLogger("personaldocs.ai")

FEATURES = ("ocr_assist", "smart_organization", "semantic_search", "assistant")
CHUNK_CHARS = 1500
MAX_CHUNKS = 12


# ------------------------------------------------------------------ configuration and authorization

def enabled(feature: str | None = None) -> bool:
    if not config.get("ai.enabled"):
        return False
    return feature is None or bool(config.get(f"ai.{feature}"))


def user_allowed(user) -> bool:
    if not user or not user.is_authenticated or not user.is_active:
        return False
    return user.is_main_admin or config.get("ai.allowed_users") == "everyone"


def profile_for(feature: str) -> AIProfile:
    """The default enabled profile that serves this feature. No silent fallback to other servers."""
    qs = AIProfile.objects.filter(enabled=True)
    profile = qs.filter(is_default=True).first() or (qs.first() if qs.count() == 1 else None)
    if profile is None:
        raise AIError("No default AI profile is configured (Settings → Local AI).", "disabled")
    if profile.features and feature not in profile.features:
        raise AIError(f"The default AI profile is not enabled for {feature.replace('_', ' ')}.", "disabled")
    return profile


def model_for(profile: AIProfile, kind: str) -> str:
    model = {"text": profile.text_model, "vision": profile.vision_model, "embedding": profile.embedding_model}[kind]
    if not model:
        raise AIError(f"The AI profile has no {kind} model selected.", "model_missing")
    return model


def status_for(user) -> dict:
    """What the frontend may offer this person."""
    allowed = user_allowed(user)
    has_profile = AIProfile.objects.filter(enabled=True).exists()
    return {f: bool(allowed and has_profile and enabled(f)) for f in FEATURES} | {"enabled": bool(config.get("ai.enabled")), "allowed": allowed}


# ------------------------------------------------------------------ jobs

def start_job(kind: str, *, document=None, user=None, profile=None, model="") -> AIJob:
    return AIJob.objects.create(kind=kind, document=document, requested_by=user, profile=profile, model=model,
                                status=AIJob.RUNNING, started_at=timezone.now(), attempts=1)


def finish_job(job: AIJob, *, error: AIError | None = None) -> None:
    """Record the outcome truthfully: done, skipped (feature switched off) or failed at the stage it reached."""
    job.finished_at = timezone.now()
    job.next_retry_at = None
    if error is None:
        job.status = AIJob.DONE
        job.stage = "done"
        job.error_category, job.error = "", ""
    else:
        job.status = AIJob.SKIPPED if error.category == "disabled" else AIJob.FAILED
        job.error_category = error.category
        job.error = str(error)[:300]
        job.detail = {**(job.detail or {}), **error.detail()}
        # a person may retry a failed analysis once the cause is fixed (automatic retries are only for transient errors)
        job.retryable = job.status == AIJob.FAILED and job.kind in (AIJob.ANALYZE, AIJob.EMBED)
    job.save()


def _debug(label: str, prompt_chars: int, reply_chars: int) -> None:
    if config.get("ai.debug_logging"):
        log.info("ai %s prompt_chars=%s reply_chars=%s", label, prompt_chars, reply_chars)  # sizes only, never content


# ------------------------------------------------------------------ OCR assist / smart organization

def _vocab(doc) -> dict:
    from apps.library.models import Correspondent, CustomFieldDef, DocumentType, Tag

    return {
        "types": list(DocumentType.objects.values_list("name", flat=True)[:100]),
        "tags": list(Tag.objects.values_list("name", flat=True)[:200]),
        "correspondents": list(Correspondent.objects.values_list("name", flat=True)[:200]),
        "fields": list(CustomFieldDef.objects.values_list("key", flat=True)[:50]),
    }


def _folder_options(user, doc) -> dict[str, str]:
    """Folders the requesting person could move this document into (ORGANIZE), as path -> id."""
    from apps.library import permissions as P
    from apps.library.models import Folder
    from apps.library.services import folder_path

    ctx = P.AccessContext.build(user)
    ids = ctx.folder_ids_with(P.ORGANIZE) if not ctx.is_admin else set(Folder.objects.filter(archived_at=None).values_list("id", flat=True))
    out = {}
    for f in Folder.objects.filter(pk__in=list(ids)[:300], archived_at=None).select_related("parent"):
        out[" / ".join(x.name for x in folder_path(f))] = str(f.id)
    return out


ANALYZE_PROMPT = """You help organise a family's personal documents. Read the OCR text of ONE document and propose metadata.
Reply with a single JSON object only, using these keys (omit a key when unsure):
{keys}
Rules: dates as YYYY-MM-DD; choose document_type, correspondent and folder ONLY from the lists below when one fits;
tags may reuse listed tags or propose at most 3 short new ones; never invent numbers that are not in the text.
Document types: {types}
Existing tags: {tags}
Known issuers: {correspondents}
Folders: {folders}
Current title: {title}
{part}
OCR TEXT:
{text}"""

# Change Set Y: the OCR-first analysis pipeline. Stages are stored on the AIJob so a person can see where it is, or
# where it failed. OCR (Tesseract or PaddleOCR, whichever is configured) always runs first; the AI text model only
# ever receives the recognised TEXT, never the file or a page image.
STAGES = ("queued", "preparing", "ocr_queued", "ocr_running", "validating_ocr", "ai_running", "validating_ai", "saving",
          "done")
STAGE_LABELS = {"queued": "Queued", "preparing": "Preparing document", "ocr_queued": "OCR queued", "ocr_running": "OCR running",
                "validating_ocr": "Checking OCR text", "ai_running": "AI analysis", "validating_ai": "Checking AI answer",
                "saving": "Saving suggestions", "done": "Done"}
MIN_USABLE_CHARS = 12      # letters or digits; below this the AI server is not called
ANALYSIS_PARTS = 3         # a long document is analysed in at most this many parts, in page order
EMPTY_OCR = "OCR completed, but no usable text was detected."

FIELD_SCHEMA = {
    "title": {"type": "string"}, "issue_date": {"type": "string"}, "expiry_date": {"type": "string"},
    "document_number": {"type": "string"}, "summary": {"type": "string"}, "document_type": {"type": "string"},
    "correspondent": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}, "folder": {"type": "string"},
}
OCR_KEYS = ("title", "issue_date", "expiry_date", "document_number", "summary")
ORGANIZE_KEYS = ("document_type", "correspondent", "tags", "folder")


def _date(value) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def set_stage(job: AIJob | None, stage: str, **detail) -> None:
    if job is None:
        return
    job.stage = stage
    if detail:
        job.detail = {**(job.detail or {}), **detail}
    if job.pk:
        AIJob.objects.filter(pk=job.pk).update(stage=job.stage, detail=job.detail)


def usable_chars(text: str) -> int:
    return sum(1 for ch in (text or "") if ch.isalnum())


def ocr_text(doc) -> dict:
    """The document's current recognised/extracted text plus safe facts about where it came from."""
    from apps.library import ocr_runs

    cv = doc.current_version
    text = ocr_runs.document_text(doc) or doc.content_text or ""
    if cv is not None and cv.ocr_applied:
        engine = cv.ocr_engine or "ocr"
    else:
        engine = "text layer" if text.strip() else ""
    return {"text": text, "engine": engine, "pages": getattr(cv, "page_count", None) or None, "chars": usable_chars(text),
            "ocr_applied": bool(cv and cv.ocr_applied)}


def prepare_text(doc, user, job: AIJob | None) -> dict | None:
    """Stage 1 (OCR). Returns the text to analyse, or None when OCR was queued and the job must wait for it.
    Raises AIError for OCR problems: the AI server is never called without usable text."""
    from apps.library import ocr_runs

    info = ocr_text(doc)
    if info["chars"] >= MIN_USABLE_CHARS:
        set_stage(job, "validating_ocr", ocr_engine=info["engine"], ocr_pages=info["pages"], ocr_chars=info["chars"],
                  ocr_reused=True)
        return info
    if ocr_runs._active_job(doc) is not None:  # recognition already queued or running: wait for it
        set_stage(job, "ocr_queued", ocr_requested=True)
        return None
    if job is not None and not (job.detail or {}).get("requested") and not info["ocr_applied"]:
        raise AIError("Skipped: the document has no recognised text yet. Run OCR or choose Analyze Document.", "disabled")
    if info["ocr_applied"] or (job is not None and (job.detail or {}).get("ocr_requested")):
        set_stage(job, "validating_ocr", ocr_engine=info["engine"] or "ocr", ocr_pages=info["pages"], ocr_chars=info["chars"])
        raise AIError(EMPTY_OCR, "ocr_empty")
    try:
        ocr_runs.request_ocr(actor=user if getattr(user, "pk", None) else None, doc=doc, automatic=True)
    except ocr_runs.OCRError as exc:
        raise AIError(f"The document has no usable text and text recognition could not start: {exc}", "ocr_unavailable")
    set_stage(job, "ocr_queued", ocr_requested=True)
    return None


def split_for_model(text: str, limit: int) -> list[str]:
    """Split long text into parts of at most ``limit`` characters at page or paragraph boundaries, in order."""
    text = text.strip()
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for block in re.split(r"(\f|\n\s*\n)", text):
        if not block or block.isspace() or block == "\f":
            if cur and block:
                cur += "\n\n"
            continue
        while len(block) > limit:  # one very long block: cut at a line or space near the limit
            cut = max(block.rfind("\n", 0, limit), block.rfind(" ", 0, limit))
            cut = cut if cut > limit // 2 else limit
            if cur:
                parts.append(cur.strip())
                cur = ""
            parts.append(block[:cut].strip())
            block = block[cut:]
        if len(cur) + len(block) > limit and cur:
            parts.append(cur.strip())
            cur = ""
        cur += block
    if cur.strip():
        parts.append(cur.strip())
    return [p for p in parts if p]


def _clean(value, limit: int = 300) -> str:
    return "".join(ch for ch in str(value) if ch.isprintable() or ch in " ")[:limit].strip()


def validate_ai_data(data) -> dict:
    """Stage 'validating_ai': keep only the requested keys with the right types; reject an answer with none of them."""
    if not isinstance(data, dict):
        raise AIError("The model's answer is not a JSON object.", "bad_response")
    out = {}
    for key, spec in FIELD_SCHEMA.items():
        if key not in data or data[key] in (None, "", []):
            continue
        val = data[key]
        if spec["type"] == "array":
            if isinstance(val, str):
                val = [x for x in re.split(r"[,;]", val)]
            if not isinstance(val, list):
                continue
            val = [_clean(x, 60) for x in val if isinstance(x, (str, int, float)) and _clean(x, 60)][:8]
            if val:
                out[key] = val
        elif isinstance(val, (str, int, float)) and not isinstance(val, bool):
            v = _clean(val)
            if key in ("issue_date", "expiry_date"):
                v = _date(v) or ""
            if v:
                out[key] = v
    if not out and not any(k in data for k in FIELD_SCHEMA):
        raise AIError("The model's answer did not contain any of the requested fields.", "bad_response")
    return out


def merge_parts(results: list[dict]) -> dict:
    """Combine the answers for the parts of a long document: the first value in page order wins; tags are joined."""
    merged: dict = {}
    for r in results:
        for k, v in r.items():
            if k == "tags":
                merged["tags"] = list(dict.fromkeys((merged.get("tags") or []) + v))[:8]
            elif k not in merged:
                merged[k] = v
    return merged


def run_analysis(profile: AIProfile, text: str, *, keys: list[str], vocab: dict, folders: dict, title: str,
                 job: AIJob | None = None) -> tuple[dict, dict]:
    """Stage 2 (AI): send the OCR text (never a file or image) to the profile's TEXT model and return validated data.
    Shared by Analyze Document and Settings → Test AI analysis, so both use the same compatibility path."""
    model = model_for(profile, "text")
    if profile.embedding_model and model == profile.embedding_model:
        raise AIError("The text model is set to the embedding model. Choose a chat/text model in the AI profile.", "model_role")
    parts = split_for_model(text, profile.max_input_chars)
    used = parts[:ANALYSIS_PARTS]
    info = {"parts": len(used), "total_chars": len(text), "analyzed_chars": sum(len(p) for p in used),
            "truncated": len(parts) > len(used)}
    schema = {"type": "object", "properties": {k: FIELD_SCHEMA[k] for k in keys}}
    key_lines = {"title": '"title": short descriptive title', "issue_date": '"issue_date"', "expiry_date": '"expiry_date"',
                 "document_number": '"document_number": as printed', "summary": '"summary": one sentence',
                 "document_type": '"document_type"', "correspondent": '"correspondent": issuing organisation',
                 "tags": '"tags": [list]', "folder": '"folder": one of the folder paths'}
    prov = provider_for(profile)
    results = []
    for i, part in enumerate(used):
        prompt = ANALYZE_PROMPT.format(
            keys="\n".join(key_lines[k] for k in keys), types=", ".join(vocab.get("types") or []) or "-",
            tags=", ".join(vocab.get("tags") or []) or "-", correspondents=", ".join((vocab.get("correspondents") or [])[:80]) or "-",
            folders="; ".join(list(folders)[:80]) or "-", title=title,
            part=f"(Part {i + 1} of {len(used)} of a longer document, in page order.)\n" if len(used) > 1 else "", text=part)
        set_stage(job, "ai_running", model=model, **info)
        reply, how = prov.structured([{"role": "system", "content": "Return only one JSON object."},
                                      {"role": "user", "content": prompt}], model, schema)
        info.update(structured_output=how["structured_output"], fallback=bool(how.get("fallback") or info.get("fallback")))
        if how.get("rejected"):
            info["rejected_capability"] = "response_format"
        _debug("analyze", len(prompt), len(reply))
        set_stage(job, "validating_ai", **info)
        results.append(validate_ai_data(parse_json_object(reply)))
    return merge_parts(results), info


def analyze_document(doc, user, *, job: AIJob | None = None) -> list[AISuggestion] | None:
    """OCR → validate text → AI text model → validate → pending AISuggestion rows. Never changes the document.
    Returns None when OCR had to be queued first (the job resumes when recognition finishes)."""
    from apps.library import permissions as P

    ocr = enabled("ocr_assist")
    organize = enabled("smart_organization")
    if not (ocr or organize):
        raise AIError("OCR assist and smart organization are switched off.", "disabled")
    ctx = P.AccessContext.build(user)
    if not ctx.can(doc, P.EDIT):
        raise AIError("You cannot edit this document.", "disabled")
    profile = profile_for("ocr_assist" if ocr else "smart_organization")
    if job:
        job.profile, job.model = profile, profile.text_model
        job.save(update_fields=["profile", "model"])
    set_stage(job, "preparing")
    info = prepare_text(doc, user, job)
    if info is None:
        return None
    keys = (list(OCR_KEYS) if ocr else []) + (list(ORGANIZE_KEYS) if organize else [])
    vocab = _vocab(doc)
    folders = _folder_options(user, doc) if organize else {}
    data, _how = run_analysis(profile, info["text"], keys=keys, vocab=vocab, folders=folders, title=doc.title, job=job)
    set_stage(job, "saving")
    return _store_suggestions(doc, data, vocab, folders, job, ocr=ocr, organize=organize)


def manual_keys(doc) -> set[str]:
    """Detail keys a person confirmed by hand (entered, or replaced an OCR/AI value)."""
    from apps.library.models import DocumentField

    from django.db.models import Q

    return set(DocumentField.objects.filter(document=doc, status=DocumentField.CONFIRMED)
               .filter(Q(source="manual") | Q(overridden=True)).values_list("key", flat=True))


def _store_suggestions(doc, data: dict, vocab: dict, folders: dict, job, *, ocr: bool, organize: bool) -> list[AISuggestion]:
    out: list[tuple[str, object, str, str]] = []
    if ocr:
        title = str(data.get("title") or "").strip()[:255]
        if title and title != doc.title:
            out.append(("title", title, title, doc.title))
        from apps.library import doctypes

        allowed = doctypes.allowed_extract_keys(doc)  # a typed document only gets its own template's fields
        manual = manual_keys(doc)  # details a person entered or corrected are never proposed for replacement
        for key in ("issue_date", "expiry_date"):
            if (allowed is not None and key not in allowed) or key in manual:
                continue
            val = _date(data.get(key))
            current = getattr(doc, key)
            if val and val != (current.isoformat() if current else None):
                out.append((key, val, val, current.isoformat() if current else ""))
        number = re.sub(r"[^A-Za-z0-9\-/ ]", "", str(data.get("document_number") or ""))[:40].strip()
        text = (doc.current_version.text if doc.current_version else "") or ""
        if number and (allowed is None or "document_number" in allowed) and "document_number" not in manual \
                and number.replace(" ", "") in text.replace(" ", ""):  # only numbers that really appear in the text
            out.append(("document_number", number, number, ""))
        summary = str(data.get("summary") or "").strip()[:300]
        if summary:
            out.append(("summary", summary, summary, ""))
    if organize:
        t = str(data.get("document_type") or "").strip()
        match = next((v for v in vocab["types"] if v.lower() == t.lower()), None)
        if match and (not doc.doc_type or doc.doc_type.name != match):
            out.append(("doc_type", match, match, doc.doc_type.name if doc.doc_type else ""))
        c = str(data.get("correspondent") or "").strip()[:120]
        if c and (not doc.correspondent or doc.correspondent.name.lower() != c.lower()):
            known = next((v for v in vocab["correspondents"] if v.lower() == c.lower()), c)
            out.append(("correspondent", known, known, doc.correspondent.name if doc.correspondent else ""))
        raw = data.get("tags") or []
        if isinstance(raw, str):
            raw = [x for x in re.split(r"[,;]", raw)]
        current_tags = set(doc.tags.values_list("name", flat=True))
        new_names = []
        for name in raw[:8]:
            name = str(name).strip()[:60]
            known = next((v for v in vocab["tags"] if v.lower() == name.lower()), None)
            if name and (known or len([n for n in new_names if n not in vocab["tags"]]) < 3):
                new_names.append(known or name)
        merged = sorted(current_tags | set(new_names))
        if new_names and set(merged) != current_tags:
            out.append(("tags", merged, ", ".join(merged), ", ".join(sorted(current_tags))))
        folder = str(data.get("folder") or "").strip()
        fid = folders.get(folder) or next((v for k, v in folders.items() if k.lower() == folder.lower()), None)
        if fid and fid != str(doc.folder_id):
            out.append(("folder", fid, folder, ""))
    with transaction.atomic():
        AISuggestion.objects.filter(document=doc, status=AISuggestion.PENDING, field__in=[o[0] for o in out]).delete()
        return [AISuggestion.objects.create(document=doc, field=f, value=v, display=str(d)[:300], current=str(c)[:300], job=job)
                for f, v, d, c in out]


def accept(suggestion: AISuggestion, *, user, request=None) -> None:
    """Apply one suggestion through the normal services (permission checks identical to manual edits)."""
    from apps.library import permissions as P
    from apps.library import search as searchlib
    from apps.library import services as S
    from apps.library.models import Correspondent, DocumentType, Folder, Tag

    doc = suggestion.document
    ctx = P.AccessContext.build(user)
    if not ctx.can(doc, P.EDIT):
        raise S.DomainError("You cannot edit this document.")
    f, v = suggestion.field, suggestion.value
    with transaction.atomic():
        if f == "title":
            doc.title, doc.title_is_custom = str(v)[:255], True
            doc.save()
        elif f == "doc_type":  # accepted by a person: same safe change as choosing it by hand (values kept)
            from apps.library import doctypes

            doctypes.change_type(actor=user, doc=doc, new_type=DocumentType.objects.filter(name=v, archived=False).first(),
                                 source="ai", request=request)
        elif f == "correspondent":
            doc.correspondent, _ = Correspondent.objects.get_or_create(name=str(v)[:120])
            doc.save()
        elif f == "tags":
            doc.tags.set([Tag.objects.get_or_create(name=str(n)[:60])[0] for n in v])
        elif f == "folder":
            S.move_document(ctx=ctx, actor=user, doc=doc, folder=Folder.objects.get(pk=v))
        elif f in ("issue_date", "expiry_date", "document_number"):
            S.set_field(actor=user, doc=doc, key=f, value=str(v), confirm=True, source="ai")  # confirmed by the person accepting it
        elif f == "summary":
            pass  # informational only
        S._history(doc, user, "ai_suggestion_accepted", field=f)
        if f in ("title", "doc_type", "correspondent", "tags"):
            S.refresh_title(doc)
            searchlib.update_search_vector(doc)
        suggestion.status, suggestion.decided_by, suggestion.decided_at = AISuggestion.ACCEPTED, user, timezone.now()
        suggestion.save()


# ------------------------------------------------------------------ embeddings / semantic search

def chunks_for(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    out, i = [], 0
    while i < len(text) and len(out) < MAX_CHUNKS:
        out.append(text[i:i + CHUNK_CHARS])
        i += CHUNK_CHARS - 200  # small overlap
    return out


def embed_document(doc, *, job: AIJob | None = None) -> int:
    if not enabled("semantic_search"):
        raise AIError("Semantic search is switched off.", "disabled")
    profile = profile_for("semantic_search")
    model = model_for(profile, "embedding")
    version = doc.current_version
    if version is None:
        return 0
    header = f"{doc.title}. {doc.doc_type.name if doc.doc_type else ''}. "
    pieces = chunks_for(header + ((version.text or "") or doc.content_text or ""))
    if job:
        job.profile, job.model = profile, model
        job.save(update_fields=["profile", "model"])
    vectors = provider_for(profile).embed([p[: profile.max_input_chars] for p in pieces], model) if pieces else []
    if len(vectors) != len(pieces):
        raise AIError("The embedding server returned the wrong number of vectors.", "bad_response")
    with transaction.atomic():
        DocumentChunk.objects.filter(document=doc).delete()  # old versions/models are replaced
        DocumentChunk.objects.bulk_create([DocumentChunk(document=doc, version=version, idx=i, text=p, vector=v, model=model)
                                           for i, (p, v) in enumerate(zip(pieces, vectors))])
    return len(pieces)


def _cos(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def semantic_search(ctx, query: str, *, limit: int = 10) -> list[dict]:
    """Rank only documents the person can view. Unauthorised chunks are never loaded."""
    if not enabled("semantic_search"):
        raise AIError("Semantic search is switched off.", "disabled")
    profile = profile_for("semantic_search")
    model = model_for(profile, "embedding")
    allowed_ids = list(ctx.documents().values_list("id", flat=True))
    if not allowed_ids:
        return []
    qvec = provider_for(profile).embed([query[:2000]], model)[0]
    best: dict = {}
    for chunk in DocumentChunk.objects.filter(document_id__in=allowed_ids, model=model).only("document_id", "text", "vector"):
        score = _cos(qvec, chunk.vector)
        if score > best.get(chunk.document_id, (-1, ""))[0]:
            best[chunk.document_id] = (score, chunk.text)
    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])[:limit]
    return [{"document_id": str(did), "score": round(score, 4), "snippet": text[:240]} for did, (score, text) in ranked]


# ------------------------------------------------------------------ document assistant

ASSISTANT_PROMPT = """You are a careful assistant for a family's personal documents. Answer the question using ONLY the
documents listed below (the person is allowed to see exactly these). If the answer is not in them, say you could not find it.
Be brief. Cite documents as [doc:ID] using the ids given. Today's date is {today}.

DOCUMENTS:
{docs}

QUESTION: {question}"""


def _doc_context(doc, snippet: str) -> str:
    tags = ", ".join(doc.tags.values_list("name", flat=True))
    return (f"[doc:{doc.id}] title: {doc.title}; type: {doc.doc_type.name if doc.doc_type else '-'}; owner: {doc.owner.display_name}; "
            f"issuer: {doc.correspondent.name if doc.correspondent else '-'}; issue date: {doc.issue_date or '-'}; "
            f"expiry date: {doc.expiry_date or '-'}; tags: {tags or '-'}\n  text: {snippet}")


def _expiry_window(question: str) -> int | None:
    q = question.lower()
    if "expir" not in q and "renew" not in q:
        return None
    m = re.search(r"(\d+|one|two|three|six|twelve)\s*(day|week|month|year)", q)
    words = {"one": 1, "two": 2, "three": 3, "six": 6, "twelve": 12}
    if not m:
        return 365
    n = int(m.group(1)) if m.group(1).isdigit() else words[m.group(1)]
    return n * {"day": 1, "week": 7, "month": 31, "year": 366}[m.group(2)]


def retrieve(ctx, question: str, *, document=None, limit: int = 8) -> list:
    """Candidate documents for a question: all from ctx (permission-filtered) via full-text, semantic and date intents."""
    from apps.library import search as searchlib
    from apps.library.models import Document

    visible = ctx.documents()
    if document is not None:
        return [document] if visible.filter(pk=document.pk).exists() else []
    picked: dict = {}
    words = " ".join(re.findall(r"[\w'-]{3,}", question))[:200]
    if words:
        try:
            for d in searchlib.search(ctx, words, {}, limit=limit)[0][:limit]:
                picked.setdefault(d.pk, d)
        except Exception:  # noqa: BLE001 - full-text failures must not break the assistant
            pass
    days = _expiry_window(question)
    if days is not None:
        today = timezone.localdate()
        for d in visible.filter(expiry_date__isnull=False, expiry_date__lte=today + timedelta(days=days)).order_by("expiry_date")[:limit]:
            picked.setdefault(d.pk, d)
    if "missing" in question.lower() and "expir" in question.lower():
        for d in visible.filter(expiry_date__isnull=True, no_expiry=False, doc_type__has_expiry=True)[:limit]:
            picked.setdefault(d.pk, d)
    if enabled("semantic_search") and len(picked) < limit:
        try:
            for hit in semantic_search(ctx, question, limit=limit):
                d = visible.filter(pk=hit["document_id"]).first()
                if d:
                    picked.setdefault(d.pk, d)
        except AIError:
            pass
    if not picked:
        for d in visible.order_by("-created_at")[:3]:
            picked.setdefault(d.pk, d)
    return list(picked.values())[: limit + 4]


def ask(ctx, user, question: str, *, document=None) -> dict:
    question = (question or "").strip()[:1000]
    if not question:
        raise AIError("Ask a question.", "config")
    docs = retrieve(ctx, question, document=document)
    sources = [{"id": str(d.id), "title": d.title} for d in docs]
    if not enabled("assistant"):
        raise AIError("The document assistant is switched off.", "disabled")
    profile = profile_for("assistant")
    model = model_for(profile, "text")
    budget = profile.max_input_chars
    parts = []
    for d in docs:
        text = ((d.current_version.text if d.current_version else "") or d.content_text or "")
        snippet = re.sub(r"\s+", " ", text)[: max(300, budget // max(1, len(docs)))]
        parts.append(_doc_context(d, snippet))
    prompt = ASSISTANT_PROMPT.format(today=timezone.localdate().isoformat(), docs="\n".join(parts) or "(none)", question=question)
    job = start_job(AIJob.ASSISTANT, document=document, user=user, profile=profile, model=model)
    try:
        reply = provider_for(profile).chat([{"role": "user", "content": prompt}], model)
    except AIError as exc:
        finish_job(job, error=exc)
        exc.sources = sources
        raise
    finish_job(job)
    _debug("assistant", len(prompt), len(reply))
    allowed = {s["id"] for s in sources}
    # Drop citations to anything that was not in the permitted context.
    answer = re.sub(r"\[doc:([0-9a-f-]{36})\]", lambda m: m.group(0) if m.group(1) in allowed else "", reply).strip()
    cited = [s for s in sources if f"[doc:{s['id']}]" in answer]
    return {"answer": answer, "sources": cited or sources, "model": model}


def text_fingerprint(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]
