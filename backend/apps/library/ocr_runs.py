"""Selective text recognition (OCR) runs (Change Set K).

A logical document can hold several files: replaced versions, and additional sides/copies (an ID card's back). OCR
never processes all of them. A run processes an explicit *source set*: one or more of the document's files and,
for PDFs, all pages or chosen pages/ranges, with chosen languages. The set used by Automatic OCR is the document's
*primary OCR source set* (by default its current file).

States (Document.ocr_state): not_processed, queued, processing, needs_review, confirmed, failed, removed.

Results: each source file keeps its recognised text and confidence; the document's search text is rebuilt from
the native text of its current file plus the recognised text of its source set. Suggested details are proposals;
confirmed values are never overwritten (a different reading is shown next to them instead). Removing OCR data
deletes recognised text, the searchable PDF, confidences and OCR/AI-generated proposals, and keeps the original.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import audit, config, jobs
from apps.core.models import Job

from . import ocr_policy, sandbox, storage
from .models import Document, DocumentField, DocumentVersion

log = logging.getLogger("personaldocs.ocr")

OCRABLE = ("pdf", "image")


class OCRError(Exception):
    """A request that cannot be accepted (message is shown to the person)."""


# ------------------------------------------------------------------ text assembly

def document_text(doc: Document) -> str:
    """Search text: the current file's text plus recognised text of other files in the OCR source set."""
    parts: list[str] = []
    seen = set()
    cur = DocumentVersion.objects.filter(pk=doc.current_version_id).only("id", "text").first()
    if cur is not None:
        parts.append(cur.text or "")
        seen.add(cur.id)
    ids = [s.get("version") for s in (doc.ocr_sources or [])]
    for v in DocumentVersion.objects.filter(document=doc, pk__in=[i for i in ids if i], ocr_applied=True).exclude(pk__in=seen):
        parts.append(v.text or "")
    return "\n\n".join(p for p in parts if p.strip())[:2_000_000]


def _active_job(doc: Document) -> Job | None:
    return (Job.objects.filter(kind="ocr_run", payload__document_id=str(doc.id), status__in=[Job.QUEUED, Job.RUNNING])
            .order_by("created_at").first())


def default_sources(doc: Document) -> list[dict]:
    if doc.ocr_sources:
        return [dict(s) for s in doc.ocr_sources]
    return [{"version": str(doc.current_version_id), "pages": ""}] if doc.current_version_id else []


# ------------------------------------------------------------------ requests

def validate_request(doc: Document, sources: list[dict], languages: list[str]) -> tuple[list[dict], list[str]]:
    if ocr_policy.mode_for(doc) == "disabled":
        raise OCRError("Text recognition is disabled for this document type. An administrator can change this in "
                       "Settings → OCR & processing.")
    if not sources:
        raise OCRError("Choose at least one file to recognise.")
    versions = {str(v.id): v for v in DocumentVersion.objects.filter(document=doc)}
    clean, total_pages = [], 0
    max_mb = int(config.get("processing.ocr_max_file_mb"))
    for s in sources:
        v = versions.get(str(s.get("version") or ""))
        if v is None:
            raise OCRError("That file does not belong to this document.")
        if v.av_blocked:
            raise OCRError(f"“{v.original_name}” is in antivirus quarantine and cannot be recognised.")
        if v.format_class not in OCRABLE:
            raise OCRError(f"“{v.original_name}” is not a scan or image, so it cannot be recognised.")
        if v.size > max_mb * 1024 * 1024:
            raise OCRError(f"“{v.original_name}” is larger than the OCR limit of {max_mb} MB.")
        pages_spec = (s.get("pages") or "").strip()
        if v.format_class == "image":
            pages_spec = ""
            n = 1
        else:
            try:
                n = len(ocr_policy.parse_pages(pages_spec, v.page_count))
            except ValueError as exc:
                raise OCRError(f"“{v.original_name}”: {exc}")
        total_pages += n
        if any(c["version"] == str(v.id) for c in clean):
            raise OCRError("Each file can be chosen only once; use a page range to select several pages.")
        clean.append({"version": str(v.id), "pages": pages_spec})
    if total_pages > int(config.get("processing.max_pages")):
        raise OCRError(f"This request covers {total_pages} pages; the limit is {config.get('processing.max_pages')} per job. "
                       "Choose a page range.")
    offered = set(ocr_policy.configured_languages())
    installed = set(ocr_policy.installed_languages())
    langs = [x for x in dict.fromkeys(languages or ocr_policy.default_languages(doc)) if x]
    for code in langs:
        if code not in offered:
            raise OCRError(f"The language “{code}” is not offered. An administrator can add it in Settings → OCR & processing.")
        if code not in installed:
            raise OCRError(f"The {ocr_policy.LANGUAGE_NAMES.get(code, code)} language pack is not installed on the server. "
                           "Ask the administrator to run `sudo personaldocs repair`.")
    return clean, langs or ["eng"]


def request_ocr(*, actor, doc: Document, sources: list[dict] | None = None, languages: list[str] | None = None,
                rotate: int | None = None, set_primary: bool = True, request=None, automatic: bool = False) -> Job:
    sources = sources if sources is not None else default_sources(doc)
    clean, langs = validate_request(doc, sources, languages or [])
    if _active_job(doc):
        raise OCRError("Text recognition is already queued or running for this document.")
    waiting = Job.objects.filter(kind="ocr_run", status=Job.QUEUED).count()
    if waiting >= int(config.get("processing.ocr_queue_max")):
        raise OCRError(f"The OCR queue is full ({waiting} waiting). Try again later.")
    with transaction.atomic():
        update = {"ocr_state": "queued", "ocr_error": "", "ocr_languages": langs, "ocr_updated_at": timezone.now()}
        if set_primary:
            update["ocr_sources"] = clean
        Document.objects.filter(pk=doc.pk).update(**update)
        job = jobs.enqueue("ocr_run", {"document_id": str(doc.id), "sources": clean, "languages": langs, "rotate": rotate,
                                       "requested_by": str(actor.pk) if actor else None},
                           max_attempts=int(config.get("processing.ocr_max_attempts")))
    audit.record("document.ocr_request", request=request, actor=actor, target=doc,
                 sources=len(clean), languages=langs, automatic=automatic)
    return job


def auto_ocr(doc: Document, version: DocumentVersion) -> None:
    """After upload processing: queue OCR only for Automatic types, and only for the primary source set."""
    doc = Document.objects.select_related("doc_type").get(pk=doc.pk)
    if ocr_policy.mode_for(doc) != "automatic":
        return
    sources = default_sources(doc)
    if str(version.id) not in {s["version"] for s in sources}:
        return  # another side/copy or an older file: never processed automatically
    try:
        request_ocr(actor=None, doc=doc, sources=sources, automatic=True)
    except OCRError as exc:
        Document.objects.filter(pk=doc.pk).update(ocr_state="failed", ocr_error=str(exc)[:500], ocr_updated_at=timezone.now())


def cancel_ocr(*, actor, doc: Document, request=None) -> bool:
    job = _active_job(doc)
    if job is None or job.status != Job.QUEUED:
        return False
    with transaction.atomic():
        n = Job.objects.filter(pk=job.pk, status=Job.QUEUED).update(status=Job.CANCELLED, finished_at=timezone.now())
        if not n:
            return False
        has_text = DocumentVersion.objects.filter(document=doc, ocr_applied=True).exists()
        Document.objects.filter(pk=doc.pk).update(ocr_state="confirmed" if has_text else "not_processed",
                                                  ocr_updated_at=timezone.now())
    audit.record("document.ocr_cancel", request=request, actor=actor, target=doc)
    return True


# ------------------------------------------------------------------ the job

def _recognise_image(path: Path, langs: str, rotate, timeout: int, workdir: Path, out_dir: Path):
    """(text, quality, reliable_text, searchable_rel, pdfa_ok)."""
    from PIL import Image

    from . import ocr as ocrlib
    from .processing import _ocr

    max_mp = int(config.get("processing.max_image_megapixels"))
    Image.MAX_IMAGE_PIXELS = max_mp * 1_000_000
    opts = ocrlib.Options(rotate=rotate)
    with Image.open(path) as im:
        im.load()
        result = ocrlib.recognise(im, opts, lang=langs, timeout=timeout)
        page = workdir / "ocr-page.png"
        ocrlib.prepared_image(im, result, opts).save(page, "PNG", dpi=(300, 300))
    out_pdf = out_dir / "searchable.pdf"
    ok_pdfa, _err = _ocr(page, out_pdf, timeout, image=True, workdir=workdir, lang=langs)
    searchable = storage.derivative_rel(out_pdf) if out_pdf.exists() else ""
    return result.text, result.quality(), result.reliable_text(), searchable, ok_pdfa


def _recognise_pdf_pages(path: Path, pages: list[int], langs: str, rotate, timeout: int, workdir: Path):
    """Selected pages rendered at 300 dpi and recognised one by one (text, quality, reliable)."""
    from PIL import Image

    from . import ocr as ocrlib

    texts, reliable, confs, lines, low = [], [], [], 0, []
    for n in pages:
        prefix = workdir / f"p{n}"
        proc = sandbox.run([settings.PDFTOPPM_CMD, "-png", "-r", "300", "-f", str(n), "-l", str(n), "-singlefile",
                            str(path), str(prefix)], timeout=min(timeout, 300), cwd=workdir)
        png = workdir / f"p{n}.png"
        if proc.returncode != 0 or not png.exists():
            raise sandbox.ToolError(f"page {n} could not be rendered")
        with Image.open(png) as im:
            im.load()
            result = ocrlib.recognise(im, ocrlib.Options(rotate=rotate, upscale=False), lang=langs, timeout=timeout)
        texts.append(f"[Page {n}]\n{result.text}")
        reliable.append(result.reliable_text())
        q = result.quality()
        confs.append(result.confidence)
        low += [lines + i for i in q["low_lines"]]
        lines += q["line_count"] + 1
    quality = {"engine": "tesseract", "confidence": round(sum(confs) / len(confs), 1) if confs else 0,
               "pages": pages, "low_lines": low, "line_count": lines}
    return "\n\n".join(texts), quality, "\n".join(reliable)


@jobs.handler("ocr_run", heavy=True)
def ocr_run(job):
    doc = Document.objects.select_related("owner", "doc_type").filter(pk=job.payload.get("document_id")).first()
    if doc is None or doc.archived_at:
        return {"skipped": "document missing or archived"}
    if config.get("processing.ocr_paused"):
        # paused: wait without using an attempt; the same job is picked up again after the delay
        job.attempts = max(0, job.attempts - 1)
        Job.objects.filter(pk=job.pk).update(attempts=job.attempts)
        raise jobs.RetryLater("OCR queue paused", delay_seconds=60)
    langs = "+".join(job.payload.get("languages") or ["eng"])
    rotate = job.payload.get("rotate")
    timeout = int(config.get("processing.timeout_seconds"))
    Document.objects.filter(pk=doc.pk).update(ocr_state="processing", ocr_updated_at=timezone.now())
    results = []
    for s in job.payload.get("sources") or []:
        v = DocumentVersion.objects.filter(pk=s.get("version"), document=doc).first()
        if v is None:
            continue
        original = storage.resolve_original(v.storage_path)
        workdir = Path(tempfile.mkdtemp(prefix="ocr-", dir=settings.TMP_DIR))
        out_dir = storage.derivative_dir(v.id)
        try:
            pdfa, pdfa_report, searchable = False, {}, ""
            if v.format_class == "image":
                text, quality, reliable, searchable, pdfa = _recognise_image(original, langs, rotate, timeout, workdir, out_dir)
            elif not s.get("pages"):
                from .processing import _ocr, _pdf_info

                out_pdf = out_dir / "searchable.pdf"
                pdfa, err = _ocr(original, out_pdf, timeout, image=False, workdir=workdir, lang=langs)
                if not out_pdf.exists():
                    raise sandbox.ToolError(err or "OCR failed")
                searchable = storage.derivative_rel(out_pdf)
                _p, text, _e = _pdf_info(out_pdf)
                quality, reliable = {"engine": "ocrmypdf", "pages": "all"}, None
            else:
                pages = ocr_policy.parse_pages(s["pages"], v.page_count)
                text, quality, reliable = _recognise_pdf_pages(original, pages, langs, rotate, timeout, workdir)
            if searchable:
                from .pdfa import validate

                try:
                    pdfa_report = validate(storage.resolve_derivative(searchable), timeout=min(timeout, 300))
                except Exception as exc:  # informational only
                    pdfa_report = {"validator": "none", "compliant": False, "full_validation": False, "note": str(exc)[:300]}
                pdfa = bool(pdfa and pdfa_report.get("compliant"))
            DocumentVersion.objects.filter(pk=v.pk).update(
                text=text[:2_000_000], ocr_applied=True, ocr_quality={**quality, "languages": job.payload.get("languages")},
                ocr_pages=s.get("pages") or "", searchable_path=searchable or v.searchable_path, pdfa=pdfa, pdfa_report=pdfa_report)
            results.append((v, text, reliable))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    from .processing import _apply_to_document

    with transaction.atomic():
        doc = Document.objects.select_for_update(of=("self",)).select_related("owner", "doc_type").get(pk=doc.pk)
        version = results[0][0] if results else doc.current_version
        reliable = "\n".join(r if r is not None else t for _v, t, r in results)
        _apply_to_document(doc, version, document_text(doc), "ready", reliable)
        proposed = doc.fields.filter(status=DocumentField.PROPOSED).exists()
        Document.objects.filter(pk=doc.pk).update(ocr_state="needs_review" if proposed else "confirmed", ocr_error="",
                                                  ocr_updated_at=timezone.now())
    if ocr_policy.ai_allowed(doc):
        from apps.ai.jobs import after_processing

        after_processing(doc)
    return {"sources": len(results), "languages": langs}


@jobs.handler("ocr_run:failed")
def ocr_run_failed(job):
    Document.objects.filter(pk=job.payload.get("document_id")).update(
        ocr_state="failed", ocr_error=(job.last_error or "OCR failed")[-500:], ocr_updated_at=timezone.now())


# ------------------------------------------------------------------ removal and review

def remove_ocr(*, actor, doc: Document, request=None) -> dict:
    """Delete recognised text, searchable copies, confidences and OCR/AI proposals. The original stays untouched."""
    from apps.ai.models import AISuggestion

    from .processing import _pdf_info
    from .search import update_search_vector

    if _active_job(doc):
        raise OCRError("Text recognition is queued or running; cancel it or wait before removing OCR data.")
    removed_files = 0
    with transaction.atomic():
        doc = Document.objects.select_for_update(of=("self",)).get(pk=doc.pk)
        for v in DocumentVersion.objects.filter(document=doc, ocr_applied=True):
            native = ""
            if v.format_class == "pdf":
                _p, native, _e = _pdf_info(storage.resolve_original(v.storage_path))
            if v.searchable_path:
                try:
                    storage.resolve_derivative(v.searchable_path).unlink(missing_ok=True)
                    removed_files += 1
                except OSError:
                    log.warning("could not delete a searchable copy")
            DocumentVersion.objects.filter(pk=v.pk).update(text=native, ocr_applied=False, ocr_quality={}, ocr_pages="",
                                                           searchable_path="", pdfa=False, pdfa_report={})
        fields = DocumentField.objects.filter(document=doc, status=DocumentField.PROPOSED).exclude(source="manual")
        n_fields = fields.count()
        fields.delete()
        DocumentField.objects.filter(document=doc, status=DocumentField.CONFIRMED).update(proposed_value="", flags=[])
        n_ai = AISuggestion.objects.filter(document=doc, status=AISuggestion.PENDING).delete()[0]
        try:  # semantic-search chunks are derived from the recognised text too
            from apps.ai.models import DocumentChunk

            DocumentChunk.objects.filter(document=doc).delete()
        except Exception:  # noqa: BLE001 - optional component
            pass
        doc.content_text = document_text(doc)
        doc.ocr_state, doc.ocr_error, doc.ocr_updated_at = "removed", "", timezone.now()
        if doc.state == Document.NEEDS_REVIEW and not doc.fields.filter(status=DocumentField.PROPOSED).exists() and not doc.review_flags:
            doc.state = Document.READY
        doc.save(update_fields=["content_text", "ocr_state", "ocr_error", "ocr_updated_at", "state", "updated_at"])
        update_search_vector(doc)
    # the audit entry records what was removed, never the removed text
    audit.record("document.ocr_remove", request=request, actor=actor, target=doc,
                 proposals_removed=n_fields, ai_suggestions_removed=n_ai, files_removed=removed_files)
    return {"proposals_removed": n_fields, "ai_suggestions_removed": n_ai, "files_removed": removed_files}


def mark_reviewed(*, actor, doc: Document, request=None) -> None:
    Document.objects.filter(pk=doc.pk).update(ocr_state="confirmed", ocr_updated_at=timezone.now())
    audit.record("document.ocr_reviewed", request=request, actor=actor, target=doc)
