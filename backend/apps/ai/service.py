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
    job.finished_at = timezone.now()
    if error is None:
        job.status = AIJob.DONE
    else:
        job.status = AIJob.SKIPPED if error.category == "disabled" else AIJob.FAILED
        job.error_category = error.category
        job.error = str(error)[:300]
        job.retryable = error.category in ("unavailable", "timeout", "bad_response")
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

OCR TEXT:
{text}"""


def _date(value) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def analyze_document(doc, user, *, job: AIJob | None = None) -> list[AISuggestion]:
    """Ask the model for suggestions. Never changes the document; creates pending AISuggestion rows."""
    from apps.library import permissions as P

    ocr = enabled("ocr_assist")
    organize = enabled("smart_organization")
    if not (ocr or organize):
        raise AIError("OCR assist and smart organization are switched off.", "disabled")
    ctx = P.AccessContext.build(user)
    if not ctx.can(doc, P.EDIT):
        raise AIError("You cannot edit this document.", "disabled")
    profile = profile_for("ocr_assist" if ocr else "smart_organization")
    version = doc.current_version
    text = (version.text if version else "") or doc.content_text or ""
    image = None
    if not text.strip() and version and version.preview_path and profile.vision_model:
        from apps.library import storage

        try:
            image = storage.resolve_derivative(version.thumbnail_path or version.preview_path).read_bytes()[:4_000_000]
        except OSError:
            image = None
    if not text.strip() and image is None:
        raise AIError("The document has no OCR text yet and no vision model is configured.", "disabled")
    keys = []
    if ocr:
        keys += ['"title": short descriptive title', '"issue_date"', '"expiry_date"', '"document_number": as printed', '"summary": one sentence']
    if organize:
        keys += ['"document_type"', '"correspondent": issuing organisation', '"tags": [list]', '"folder": one of the folder paths']
    vocab = _vocab(doc)
    folders = _folder_options(user, doc) if organize else {}
    prompt = ANALYZE_PROMPT.format(
        keys="\n".join(keys), types=", ".join(vocab["types"]) or "-", tags=", ".join(vocab["tags"]) or "-",
        correspondents=", ".join(vocab["correspondents"][:80]) or "-", folders="; ".join(list(folders)[:80]) or "-",
        title=doc.title, text=text[: profile.max_input_chars] if text else "(no OCR text: read the attached image)")
    model = model_for(profile, "vision" if image is not None else "text")
    if job:
        job.profile, job.model = profile, model
        job.save(update_fields=["profile", "model"])
    reply = provider_for(profile).chat([{"role": "system", "content": "Return only JSON."},
                                        {"role": "user", "content": prompt}], model, json_mode=True, image=image)
    _debug("analyze", len(prompt), len(reply))
    data = parse_json_object(reply)
    return _store_suggestions(doc, data, vocab, folders, job, ocr=ocr, organize=organize)


def _store_suggestions(doc, data: dict, vocab: dict, folders: dict, job, *, ocr: bool, organize: bool) -> list[AISuggestion]:
    out: list[tuple[str, object, str, str]] = []
    if ocr:
        title = str(data.get("title") or "").strip()[:255]
        if title and title != doc.title:
            out.append(("title", title, title, doc.title))
        for key in ("issue_date", "expiry_date"):
            val = _date(data.get(key))
            current = getattr(doc, key)
            if val and val != (current.isoformat() if current else None):
                out.append((key, val, val, current.isoformat() if current else ""))
        number = re.sub(r"[^A-Za-z0-9\-/ ]", "", str(data.get("document_number") or ""))[:40].strip()
        text = (doc.current_version.text if doc.current_version else "") or ""
        if number and number.replace(" ", "") in text.replace(" ", ""):  # only numbers that really appear in the text
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
        elif f == "doc_type":
            doc.doc_type = DocumentType.objects.filter(name=v).first()
            doc.save()
        elif f == "correspondent":
            doc.correspondent, _ = Correspondent.objects.get_or_create(name=str(v)[:120])
            doc.save()
        elif f == "tags":
            doc.tags.set([Tag.objects.get_or_create(name=str(n)[:60])[0] for n in v])
        elif f == "folder":
            S.move_document(ctx=ctx, actor=user, doc=doc, folder=Folder.objects.get(pk=v))
        elif f in ("issue_date", "expiry_date", "document_number"):
            S.set_field(actor=user, doc=doc, key=f, value=str(v), confirm=True)  # confirmed by the person accepting it
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
