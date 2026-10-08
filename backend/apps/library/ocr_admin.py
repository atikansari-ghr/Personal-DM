"""OCR administration (Change Set Q): Existing OCR Data inventory, bulk actions, orphan analysis/cleanup and the
administrator's Test OCR / Compare Engines.

Nothing here touches original files, document versions, confirmed details or active OCR jobs. Bulk work is queued
(one ``ocr_bulk`` job per batch) and audited; reprocessing is never started for the whole library implicitly.
"""
from __future__ import annotations

import difflib
import shutil
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.db.models.functions import Length
from django.utils import timezone

from apps.core import audit, config, jobs
from apps.core.models import Job

from . import ocr_engines, ocr_runs, storage
from .models import Document, DocumentVersion, OcrRun

BULK_ACTIONS = ("remove", "remove_disable", "disable", "enable", "reprocess", "set_profile")
BATCH = 25


# ------------------------------------------------------------------ inventory

def _filtered(params) -> "QuerySet[Document]":  # noqa: F821
    qs = Document.objects.filter(archived_at__isnull=True)
    if params.get("owner"):
        qs = qs.filter(owner_id=params["owner"])
    if params.get("folder"):
        from .services import _descendant_ids

        from .models import Folder

        f = Folder.objects.filter(pk=params["folder"]).first()
        qs = qs.filter(folder_id__in=_descendant_ids(f)) if f else qs.none()
    if params.get("type"):
        qs = qs.filter(doc_type_id=None) if params["type"] == "none" else qs.filter(doc_type_id=params["type"])
    engine = params.get("engine")
    if engine in ("paddleocr", "tesseract", "unknown"):
        qs = qs.filter(versions__ocr_applied=True, versions__ocr_engine=engine)
    elif engine == "none":
        qs = qs.exclude(versions__ocr_applied=True)
    elif engine == "any":
        qs = qs.filter(versions__ocr_applied=True)
    if params.get("status"):
        qs = qs.filter(ocr_state=params["status"])
    if params.get("disabled") in ("1", "true", True):
        qs = qs.filter(ocr_override="disabled")
    elif params.get("disabled") in ("0", "false", False):
        qs = qs.exclude(ocr_override="disabled")
    if params.get("date_from"):
        qs = qs.filter(versions__ocr_at__date__gte=params["date_from"])
    if params.get("date_to"):
        qs = qs.filter(versions__ocr_at__date__lte=params["date_to"])
    return qs.distinct()


def _searchable_bytes(versions) -> int:
    total = 0
    for rel in versions.exclude(searchable_path="").values_list("searchable_path", flat=True):
        try:
            total += storage.resolve_derivative(rel).stat().st_size
        except (OSError, ValueError):
            pass
    return total


def storage_usage(doc_ids=None) -> dict:
    """Bytes held by OCR-derived data (database text and blocks, searchable copies, semantic chunks)."""
    versions = DocumentVersion.objects.filter(ocr_applied=True)
    if doc_ids is not None:
        versions = versions.filter(document_id__in=doc_ids)
    text = versions.aggregate(n=Sum(Length("text")))["n"] or 0
    blocks = 0
    from django.db import connection

    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            sql = "SELECT COALESCE(SUM(pg_column_size(ocr_blocks)),0) FROM library_documentversion WHERE ocr_applied"
            args = []
            if doc_ids is not None:
                ids = [str(i) for i in doc_ids]
                if not ids:
                    return {"text": 0, "blocks": 0, "searchable": 0, "chunks": 0, "total": 0}
                sql += " AND document_id = ANY(%s::uuid[])"
                args = [ids]
            cur.execute(sql, args)
            blocks = int(cur.fetchone()[0] or 0)
    chunks = 0
    try:
        from apps.ai.models import DocumentChunk

        cq = DocumentChunk.objects.all() if doc_ids is None else DocumentChunk.objects.filter(document_id__in=doc_ids)
        chunks = (cq.aggregate(n=Sum(Length("text")))["n"] or 0) + cq.count() * 4 * 768
    except Exception:  # noqa: BLE001 - optional component
        pass
    searchable = _searchable_bytes(versions)
    return {"text": text, "blocks": blocks, "searchable": searchable, "chunks": chunks,
            "total": text + blocks + searchable + chunks}


def inventory(params) -> dict:
    base = Document.objects.filter(archived_at__isnull=True)
    ocr_versions = DocumentVersion.objects.filter(ocr_applied=True, document__archived_at__isnull=True)
    by_engine = dict(ocr_versions.values_list("ocr_engine").annotate(n=Count("document", distinct=True)))
    counts = {
        "documents_with_ocr": ocr_versions.values("document").distinct().count(),
        "paddleocr": by_engine.get("paddleocr", 0), "tesseract": by_engine.get("tesseract", 0),
        "unknown": by_engine.get("unknown", 0) + by_engine.get("", 0),
        "indexed": base.filter(versions__ocr_applied=True).exclude(content_text="").distinct().count(),
        "disabled": base.filter(ocr_override="disabled").count(),
        "failed": base.filter(ocr_state="failed").count(),
        "queued": Job.objects.filter(kind="ocr_run", status__in=[Job.QUEUED, Job.RUNNING]).count(),
        "embedded_text_hidden": base.filter(ignore_embedded_text=True).count(),
    }
    qs = _filtered(params).select_related("owner", "doc_type", "folder").order_by("-updated_at")
    page = max(1, int(params.get("page") or 1))
    total = qs.count()
    rows = []
    for d in qs[(page - 1) * 50: page * 50]:
        vs = [v for v in d.versions.all() if v.ocr_applied]
        rows.append({"id": str(d.id), "title": d.title, "owner": d.owner.display_name if d.owner_id else "",
                     "type": d.doc_type.name if d.doc_type_id else "", "folder": d.folder.name if d.folder_id else "",
                     "ocr_state": d.ocr_state, "disabled": d.ocr_override == "disabled",
                     "engines": sorted({v.ocr_engine or "unknown" for v in vs}), "profile": d.ocr_profile,
                     "ocr_at": max((v.ocr_at for v in vs if v.ocr_at), default=None), "text_chars": sum(len(v.text or "") for v in vs),
                     "embedded_text_hidden": d.ignore_embedded_text})
    return {"counts": counts, "storage": storage_usage(), "orphans": orphan_analysis(summary=True), "total": total,
            "page": page, "documents": rows,
            "runs": [run_json(r) for r in OcrRun.objects.select_related("document").filter(status=OcrRun.FAILED)[:20]]}


def run_json(r: OcrRun) -> dict:
    return {"id": r.id, "document": str(r.document_id), "title": r.document.title if r.document_id else "", "engine": r.engine,
            "model": r.model, "profile": r.profile, "status": r.status, "error": r.error, "confidence": r.confidence,
            "created_at": r.created_at, "finished_at": r.finished_at, "seconds": r.seconds,
            "fallback": (r.options or {}).get("fallback", "")}


# ------------------------------------------------------------------ bulk

def bulk_preview(action: str, ids: list[str]) -> dict:
    if action not in BULK_ACTIONS:
        raise ValueError("Unknown action.")
    docs = Document.objects.filter(pk__in=ids, archived_at__isnull=True)
    n = docs.count()
    with_ocr = docs.filter(versions__ocr_applied=True).distinct().count()
    usage = storage_usage([d.pk for d in docs]) if action in ("remove", "remove_disable") else None
    warnings = {
        "remove": "Text that exists only in OCR will no longer find these documents in search. Originals, versions, "
                  "manual and confirmed details stay.",
        "remove_disable": "As Remove, and OCR stays off for these documents (also for Automatic types) until enabled again.",
        "disable": "Automatic OCR will not run for these documents; existing OCR text is kept.",
        "enable": "These documents follow their document type's OCR mode again.",
        "reprocess": "Each document is recognised again with PP-OCRv5. The current OCR result stays until the new one "
                     "succeeds; confirmed details are never overwritten — new readings are shown for review.",
        "set_profile": "Changes the language profile used the next time these documents are recognised.",
    }
    return {"action": action, "affected": n, "with_ocr": with_ocr, "reclaimable_bytes": usage["total"] if usage else 0,
            "warning": warnings[action],
            "kept": ["Original files and every version", "Manual and confirmed details", "Document type, owner and permissions",
                     "Audit history"]}


def queue_bulk(*, actor, action: str, ids: list[str], profile: str = "", request=None) -> dict:
    preview = bulk_preview(action, ids)
    if action == "set_profile":
        from apps.core.registry import OCR_PROFILES

        if profile not in OCR_PROFILES:
            raise ValueError("Choose a language profile.")
    ids = [str(i) for i in Document.objects.filter(pk__in=ids, archived_at__isnull=True).values_list("id", flat=True)]
    job = jobs.enqueue("ocr_bulk", {"action": action, "ids": ids, "profile": profile, "actor": str(actor.pk),
                                    "done": 0, "skipped": 0, "errors": []}, max_attempts=1)
    audit.record("ocr.bulk_" + action, request=request, actor=actor, documents=len(ids), profile=profile or None,
                 reclaimable_bytes=preview["reclaimable_bytes"])
    return {"queued": len(ids), "job": str(job.id), **preview}


@jobs.handler("ocr_bulk")
def ocr_bulk(job):
    """Works through the selection in batches; re-processing is queued only as fast as the OCR queue accepts it."""
    from apps.accounts.models import User

    p = job.payload
    actor = User.objects.filter(pk=p.get("actor")).first()
    ids = list(p.get("ids") or [])
    done, skipped, errors = int(p.get("done") or 0), int(p.get("skipped") or 0), list(p.get("errors") or [])[:50]
    batch, rest = ids[:BATCH], ids[BATCH:]
    for did in batch:
        doc = Document.objects.select_related("doc_type").filter(pk=did, archived_at__isnull=True).first()
        if doc is None:
            skipped += 1
            continue
        try:
            action = p["action"]
            if action == "remove":
                if DocumentVersion.objects.filter(document=doc, ocr_applied=True).exists():
                    ocr_runs.remove_ocr(actor=actor, doc=doc, bulk=True)
                else:
                    skipped += 1
                    continue
            elif action == "remove_disable":
                ocr_runs.remove_ocr(actor=actor, doc=doc, disable=True, bulk=True)
            elif action in ("disable", "enable"):
                ocr_runs.set_ocr_disabled(actor=actor, doc=doc, disabled=action == "disable", bulk=True)
            elif action == "set_profile":
                Document.objects.filter(pk=doc.pk).update(ocr_profile=p.get("profile") or "")
            elif action == "reprocess":
                waiting = Job.objects.filter(kind="ocr_run", status=Job.QUEUED).count()
                if waiting >= int(config.get("processing.ocr_queue_max")):
                    rest = [did] + [x for x in batch[batch.index(did) + 1:]] + rest
                    break
                if not DocumentVersion.objects.filter(document=doc, ocr_applied=True).exists() and not doc.ocr_sources:
                    skipped += 1
                    continue
                ocr_runs.request_ocr(actor=actor, doc=doc, set_primary=False, engine="paddleocr", reprocess=True,
                                     profile=(doc.ocr_profile or None))
            done += 1
        except Exception as exc:  # noqa: BLE001 - one document must not stop the rest
            errors.append({"document": did, "error": str(exc)[:200]})
    if rest:
        delay = 60 if p["action"] == "reprocess" else 0
        jobs.enqueue("ocr_bulk", {**p, "ids": rest, "done": done, "skipped": skipped, "errors": errors[:50]},
                     max_attempts=1, delay_seconds=delay)
    else:
        audit.record("ocr.bulk_finished", actor=actor, bulk_action=p["action"], done=done, skipped=skipped, errors=len(errors))
        from apps.security.models import HealthState

        HealthState.objects.filter(key="storage").delete()
    return {"done": done, "skipped": skipped, "remaining": len(rest), "errors": len(errors)}


# ------------------------------------------------------------------ orphans

def _referenced_searchables() -> set[str]:
    return set(DocumentVersion.objects.exclude(searchable_path="").values_list("searchable_path", flat=True))


def _orphan_files() -> list[Path]:
    root = Path(settings.DERIVATIVES_DIR)
    if not root.exists():
        return []
    referenced = _referenced_searchables()
    out = []
    for p in root.glob("*/*/searchable*.pdf"):
        try:
            rel = storage.derivative_rel(p)
        except ValueError:
            continue
        if rel not in referenced:
            out.append(p)
    for p in root.glob("*/*/*.hocr"):
        out.append(p)
    return out


def _active_tmp_owner_ids() -> bool:
    return Job.objects.filter(kind__in=("ocr_run", "process_version"), status=Job.RUNNING).exists()


def _orphan_tmp() -> list[Path]:
    """OCR/processing scratch folders older than two hours (never while an OCR or processing job runs)."""
    tmp = Path(settings.TMP_DIR)
    if not tmp.exists() or _active_tmp_owner_ids():
        return []
    cutoff = time.time() - 2 * 3600
    return [p for p in tmp.iterdir() if p.name.startswith(("ocr-", "paddle-", "proc-", "ocrtest-")) and p.stat().st_mtime < cutoff]


def _size(p: Path) -> int:
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return p.stat().st_size if p.exists() else 0


def orphan_analysis(summary: bool = False) -> dict:
    """Dry run: derived OCR data that no longer belongs to anything. Never originals, versions, confirmed details,
    active OCR jobs or previews."""
    files = _orphan_files()
    tmp = _orphan_tmp()
    stale_blocks = DocumentVersion.objects.filter(ocr_applied=False).exclude(ocr_blocks=[])
    stale_runs = OcrRun.objects.filter(status__in=[OcrRun.QUEUED, OcrRun.RUNNING],
                                       created_at__lt=timezone.now() - timedelta(hours=6))
    active_jobs = {str(j) for j in Job.objects.filter(kind="ocr_run", status__in=[Job.QUEUED, Job.RUNNING]).values_list("id", flat=True)}
    stale_runs = [r for r in stale_runs if str(r.job_id) not in active_jobs]
    chunks = 0
    pending = 0
    try:
        from apps.ai.models import AISuggestion, DocumentChunk

        chunks = DocumentChunk.objects.filter(document__content_text="").count()
        pending = AISuggestion.objects.filter(status=AISuggestion.PENDING, document__content_text="").count()
    except Exception:  # noqa: BLE001
        pass
    items = [
        {"key": "files", "label": "Searchable copies and OCR files no document version refers to", "count": len(files),
         "bytes": sum(_size(p) for p in files)},
        {"key": "tmp", "label": "OCR scratch folders older than two hours", "count": len(tmp), "bytes": sum(_size(p) for p in tmp)},
        {"key": "blocks", "label": "Text blocks left on versions without OCR", "count": stale_blocks.count(), "bytes": 0},
        {"key": "chunks", "label": "Semantic-search chunks of documents without text", "count": chunks, "bytes": 0},
        {"key": "suggestions", "label": "Pending Local AI suggestions of documents without text", "count": pending, "bytes": 0},
        {"key": "runs", "label": "OCR runs stuck in queued/running without a job", "count": len(stale_runs), "bytes": 0},
    ]
    out = {"items": items, "count": sum(i["count"] for i in items), "bytes": sum(i["bytes"] for i in items)}
    if not summary:
        out["never"] = ["Original files and document versions", "Confirmed and manual details", "Active OCR jobs",
                        "Previews and thumbnails"]
    return out


def orphan_cleanup(*, actor, request=None) -> dict:
    before = orphan_analysis()
    for p in _orphan_files():
        p.unlink(missing_ok=True)
    for p in _orphan_tmp():
        shutil.rmtree(p, ignore_errors=True)
    DocumentVersion.objects.filter(ocr_applied=False).exclude(ocr_blocks=[]).update(ocr_blocks=[])
    try:
        from apps.ai.models import AISuggestion, DocumentChunk

        DocumentChunk.objects.filter(document__content_text="").delete()
        AISuggestion.objects.filter(status=AISuggestion.PENDING, document__content_text="").delete()
    except Exception:  # noqa: BLE001
        pass
    active_jobs = {str(j) for j in Job.objects.filter(kind="ocr_run", status__in=[Job.QUEUED, Job.RUNNING]).values_list("id", flat=True)}
    for r in OcrRun.objects.filter(status__in=[OcrRun.QUEUED, OcrRun.RUNNING], created_at__lt=timezone.now() - timedelta(hours=6)):
        if str(r.job_id) not in active_jobs:
            OcrRun.objects.filter(pk=r.pk).update(status=OcrRun.FAILED, error="Abandoned (no job)", finished_at=timezone.now())
    from apps.security.models import HealthState

    HealthState.objects.filter(key="storage").delete()
    audit.record("ocr.orphan_cleanup", request=request, actor=actor, items=before["count"], bytes=before["bytes"])
    return {"removed": before["count"], "bytes": before["bytes"], "after": orphan_analysis(summary=True)}


# ------------------------------------------------------------------ Test OCR / Compare Engines

def _cer_accuracy(expected: str, got: str) -> float:
    """Character accuracy (1 - character error rate) after normalising whitespace; objective, unlike confidences."""
    a = " ".join(expected.split())
    b = " ".join(got.split())
    if not a:
        return 0.0
    if len(a) * len(b) > 25_000_000:  # keep the request fast on very long inputs
        return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() * 100, 1)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(max(0.0, 1 - prev[-1] / len(a)) * 100, 1)


def test_ocr(*, upload, engines: list[str], profile: str, expected: str = "", template: str = "", pages: str = "",
             actor=None, request=None) -> dict:
    """Run a sanitised test file through one or both engines outside the family library. Temporary files are deleted."""
    from .extraction import extract
    from .ocr_policy import parse_pages

    name = Path(getattr(upload, "name", "test")).name.lower()
    workdir = Path(tempfile.mkdtemp(prefix="ocrtest-", dir=settings.TMP_DIR))
    results, images = [], []
    try:
        src = workdir / ("input.pdf" if name.endswith(".pdf") else "input.img")
        with open(src, "wb") as fh:
            for chunk in upload.chunks():
                fh.write(chunk)
        timeout = int(config.get("processing.timeout_seconds"))
        if name.endswith(".pdf"):
            from .processing import _pdf_info

            count, _t, enc = _pdf_info(src)
            if enc:
                raise ValueError("Password-protected PDFs cannot be tested.")
            page_list = parse_pages(pages, count)[:5]
            images = ocr_engines.render_pdf_pages(src, page_list, workdir, timeout)
        else:
            images = [(ocr_engines.prepare_image(src, workdir / "page-1.png"), 1)]
        for engine in engines:
            t0 = time.monotonic()
            entry = {"engine": engine, "label": ocr_engines.ENGINE_LABELS.get(engine, engine)}
            try:
                if engine == "paddleocr":
                    r = ocr_engines.paddle_recognise(images, profile, workdir, timeout)
                else:
                    r = ocr_engines.tesseract_recognise(images, profile, None, timeout)
                text = r.text(len(images) > 1)
                lines = r.lines()
                entry.update(ok=True, model=r.model, version=r.version, profile=r.profile, text=text,
                             lines=lines[:500], line_count=len(lines), low_confidence_lines=sum(1 for x in lines if x["score"] < ocr_engines.LOW_SCORE),
                             mean_score=round(100 * sum(x["score"] for x in lines) / len(lines), 1) if lines else None,
                             has_geometry=engine == "paddleocr", pages=[{"page": p.page, "angle": p.angle} for p in r.pages])
                if expected.strip():
                    entry["accuracy"] = _cer_accuracy(expected, text)
                if template:
                    entry["fields"] = [{"key": p.key, "value": p.value, "confidence": p.confidence}
                                       for p in extract(r.reliable_text(), template=template)]
            except (ocr_engines.EngineError, Exception) as exc:  # noqa: BLE001 - reported per engine
                entry.update(ok=False, error=str(exc)[:300])
            entry["seconds"] = round(time.monotonic() - t0, 2)
            results.append(entry)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    audit.record("ocr.test", request=request, actor=actor, engines=engines, profile=profile, pages=len(images),
                 compared=len(engines) > 1)
    return {"results": results, "profile": profile, "artifacts_removed": not workdir.exists(),
            "note": "Confidence scores of different engines are not comparable. Judge by the expected text (accuracy) or "
                    "by reading the results."}
