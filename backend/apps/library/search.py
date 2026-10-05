"""PostgreSQL full-text search, autocomplete and non-AI 'More like this'.

Every function takes an AccessContext and only ever touches documents the caller can view, so
results, snippets, counts, suggestions and similarity candidates never leak inaccessible data.
"""
from __future__ import annotations

import re

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank, SearchVector
from django.db import connection
from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce

from . import permissions as P
from .models import Document

CONFIG = "english"


def update_search_vector(doc: Document) -> None:
    tags = " ".join(doc.tags.values_list("name", flat=True))
    meta = " ".join(filter(None, [doc.doc_type.name if doc.doc_type_id else "", doc.correspondent.name if doc.correspondent_id else "",
                                  tags, doc.owner.display_name if doc.owner_id else ""]))
    fields = " ".join(f.value for f in doc.fields.exclude(key="document_number") if f.value)
    Document.objects.filter(pk=doc.pk).update(
        search_vector=SearchVector(Value(doc.title), weight="A", config=CONFIG)
        + SearchVector(Value(meta + " " + fields), weight="B", config=CONFIG)
        + SearchVector(Value(doc.content_text[:1_000_000]), weight="C", config=CONFIG)
    )


def _valid(params: dict) -> bool:
    """Malformed filter values (a bad id, a non-number, a bad date) match nothing instead of failing."""
    import uuid
    from datetime import date

    try:
        for k in ("folder", "owner"):
            if params.get(k):
                uuid.UUID(str(params[k]))
        for k in ("type", "tag", "correspondent", "expiring_days"):
            if params.get(k):
                int(params[k])
        if params.get("added_after"):
            date.fromisoformat(str(params["added_after"]))
    except (ValueError, TypeError):
        return False
    return True


def _filters(qs, params: dict):
    if not _valid(params):
        return qs.none()
    if params.get("folder"):
        qs = qs.filter(folder_id=params["folder"])
    if params.get("owner"):
        qs = qs.filter(owner_id=params["owner"])
    if params.get("type"):
        qs = qs.filter(doc_type_id=params["type"])
    if params.get("tag"):
        qs = qs.filter(tags__id=params["tag"])
    if params.get("correspondent"):
        qs = qs.filter(correspondent_id=params["correspondent"])
    if params.get("state"):
        qs = qs.filter(state=params["state"])
    if params.get("expiring_days"):
        from datetime import timedelta

        from django.utils import timezone

        today = timezone.localdate()
        qs = qs.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=int(params["expiring_days"])))
    if params.get("expired"):
        from django.utils import timezone

        qs = qs.filter(expiry_date__lt=timezone.localdate())
    if params.get("added_after"):
        qs = qs.filter(created_at__date__gte=params["added_after"])
    return qs


def search(ctx: P.AccessContext, q: str, params: dict | None = None, limit: int = 50, offset: int = 0):
    params = params or {}
    qs = _filters(ctx.documents(P.VIEW), params).distinct()
    q = (q or "").strip()
    if not q:
        total = qs.count()
        return list(qs.select_related("owner", "doc_type", "folder").order_by("-created_at")[offset:offset + limit]), total, {}
    query = SearchQuery(q, config=CONFIG, search_type="websearch")
    prefix = _prefix_query(q)
    combined = query | prefix if prefix is not None else query
    qs = qs.filter(Q(search_vector=combined) | Q(title__icontains=q))
    total = qs.count()
    rows = list(
        qs.annotate(rank=Coalesce(SearchRank(F("search_vector"), combined), Value(0.0)) + Value(0.0))
        .annotate(snippet=SearchHeadline("content_text", query, config=CONFIG, start_sel="«", stop_sel="»",
                                         max_words=30, min_words=12, max_fragments=2))
        .select_related("owner", "doc_type", "folder")
        .order_by("-rank", "-created_at")[offset:offset + limit]
    )
    snippets = {r.id: (r.snippet or "") for r in rows}
    return rows, total, snippets


def _prefix_query(q: str):
    words = [w for w in re.findall(r"[\w]+", q.lower()) if len(w) >= 2][:6]
    if not words:
        return None
    raw = " & ".join(f"{w}:*" for w in words)
    return SearchQuery(raw, config=CONFIG, search_type="raw")


def autocomplete(ctx: P.AccessContext, prefix: str, limit: int = 8) -> list[str]:
    prefix = re.sub(r"[^\w]", "", (prefix or "").lower())[:40]
    if len(prefix) < 2:
        return []
    ids = list(ctx.documents(P.VIEW).values_list("id", flat=True)[:5000])
    if not ids:
        return []
    titles = list(ctx.documents(P.VIEW).filter(title__icontains=prefix).values_list("title", flat=True)[:limit])
    with connection.cursor() as cur:
        cur.execute(
            "SELECT word FROM ts_stat(%s) WHERE word LIKE %s ORDER BY ndoc DESC, nentry DESC LIMIT %s",
            [_vector_sql(ids), prefix + "%", limit],
        )
        words = [r[0] for r in cur.fetchall()]
    seen, out = set(), []
    for s in titles + words:
        if s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:limit]


def _vector_sql(ids) -> str:
    quoted = ",".join("'" + str(i).replace("'", "") + "'" for i in ids)
    return f"SELECT search_vector FROM library_document WHERE id IN ({quoted}) AND search_vector IS NOT NULL"


def more_like_this(ctx: P.AccessContext, doc: Document, limit: int = 8) -> list[tuple[Document, float, list[str]]]:
    """Similarity = shared distinctive terms (ts_rank on an OR query of the source's top lexemes)
    + same type (+0.3) + same correspondent (+0.2) + shared tags (+0.1 each) + same owner (+0.05).
    Deterministic and explainable; not semantic AI search."""
    if not ctx.can(doc, P.VIEW):
        return []
    with connection.cursor() as cur:
        cur.execute(
            "SELECT word FROM ts_stat(%s) WHERE length(word) > 3 ORDER BY nentry DESC LIMIT 25",
            [f"SELECT search_vector FROM library_document WHERE id = '{doc.id}'"],
        )
        terms = [re.sub(r"[^\w]", "", r[0]) for r in cur.fetchall()]
    terms = [t for t in terms if t]
    candidates = ctx.documents(P.VIEW).exclude(pk=doc.pk).select_related("owner", "doc_type")
    scored: dict = {}
    reasons: dict = {}
    if terms:
        tsq = SearchQuery(" | ".join(terms), config=CONFIG, search_type="raw")
        for d in candidates.filter(search_vector=tsq).annotate(rank=SearchRank(F("search_vector"), tsq)).order_by("-rank")[:50]:
            scored[d.id] = (d, float(d.rank) * 10)
            reasons[d.id] = ["shared text"]
    tag_ids = set(doc.tags.values_list("id", flat=True))
    pool = list(candidates.filter(Q(doc_type_id=doc.doc_type_id) | Q(correspondent_id=doc.correspondent_id) | Q(tags__in=tag_ids))
                .distinct()[:100]) if (doc.doc_type_id or doc.correspondent_id or tag_ids) else []
    for d in pool:
        scored.setdefault(d.id, (d, 0.0))
        reasons.setdefault(d.id, [])
    for did, (d, s) in list(scored.items()):
        if doc.doc_type_id and d.doc_type_id == doc.doc_type_id:
            s += 0.3
            reasons[did].append("same type")
        if doc.correspondent_id and d.correspondent_id == doc.correspondent_id:
            s += 0.2
            reasons[did].append("same issuer")
        shared = tag_ids & set(d.tags.values_list("id", flat=True))
        if shared:
            s += 0.1 * len(shared)
            reasons[did].append("shared tags")
        if d.owner_id == doc.owner_id:
            s += 0.05
        scored[did] = (d, s)
    ranked = sorted(scored.values(), key=lambda t: (-t[1], str(t[0].id)))[:limit]
    return [(d, round(s, 3), reasons[d.id]) for d, s in ranked if s > 0]
