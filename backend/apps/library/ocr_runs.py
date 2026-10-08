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

def validate_request(doc: Document, sources: list[dict], languages: list[str], *, engine: str | None = None,
                     profile: str | None = None) -> tuple[list[dict], list[str], str]:
    """(clean sources, Tesseract languages, profile). Raises OCRError with a message for the person."""
    from apps.core.registry import OCR_PROFILES

    from . import ocr_engines

    if ocr_policy.mode_for(doc) == "disabled":
        if doc.ocr_override == "disabled":
            raise OCRError("OCR is disabled for this document. Choose “Enable OCR for this document” first.")
        raise OCRError("Text recognition is disabled for this document type. An administrator can change this in "
                       "Settings → OCR & processing.")
    if engine not in (None, "", "paddleocr", "tesseract"):
        raise OCRError("Unknown OCR engine.")
    profile = profile or ocr_engines.profile_for(doc)
    if profile not in OCR_PROFILES:
        raise OCRError("Unknown language profile.")
    if profile not in ocr_engines.offered_profiles() and profile != ocr_engines.profile_for(doc):
        raise OCRError(f"The language profile “{OCR_PROFILES[profile]}” is not offered. An administrator can add it in "
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
    langs = [x for x in dict.fromkeys(languages or []) if x]
    if engine == "tesseract" or langs:
        # Tesseract Legacy: explicit languages, or the profile's language packs
        langs = langs or ocr_engines.TESSERACT_LANGS[profile]
        offered = set(ocr_policy.configured_languages()) | set(ocr_engines.TESSERACT_LANGS[profile])
        installed = set(ocr_policy.installed_languages())
        for code in langs:
            if code not in offered:
                raise OCRError(f"The language “{code}” is not offered. An administrator can add it in Settings → OCR & processing.")
            if engine == "tesseract" and code not in installed:
                raise OCRError(f"The {ocr_policy.LANGUAGE_NAMES.get(code, code)} language pack is not installed on the server. "
                               "Ask the administrator to run `sudo personaldocs repair`.")
    return clean, langs or ocr_engines.TESSERACT_LANGS[profile], profile


def request_ocr(*, actor, doc: Document, sources: list[dict] | None = None, languages: list[str] | None = None,
                rotate: int | None = None, set_primary: bool = True, request=None, automatic: bool = False,
                engine: str | None = None, profile: str | None = None, reprocess: bool = False) -> Job:
    """Queue one OCR run. ``engine=None`` uses the configured default (PaddleOCR, with Tesseract fallback if allowed)."""
    from .models import OcrRun

    sources = sources if sources is not None else default_sources(doc)
    if languages and not engine:
        engine = "tesseract"  # explicit Tesseract language packs: a Legacy run (PP-OCRv5 uses profiles)
    clean, langs, profile = validate_request(doc, sources, languages or [], engine=engine, profile=profile)
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
        run = OcrRun.objects.create(document=doc, engine=engine or config.get("processing.ocr_engine"), profile=profile,
                                    languages=langs, sources=clean, reprocess=reprocess,
                                    options={"rotate": rotate, "requested_engine": engine or "", "automatic": automatic},
                                    requested_by=actor if actor and actor.pk else None)
        job = jobs.enqueue("ocr_run", {"document_id": str(doc.id), "sources": clean, "languages": langs, "rotate": rotate,
                                       "requested_by": str(actor.pk) if actor else None, "engine": engine or "",
                                       "profile": profile, "run_id": run.id, "epoch": doc.ocr_epoch, "reprocess": reprocess},
                           max_attempts=int(config.get("processing.ocr_max_attempts")))
        OcrRun.objects.filter(pk=run.pk).update(job_id=job.id)
    audit.record("document.ocr_request", request=request, actor=actor, target=doc, sources=len(clean), profile=profile,
                 engine=engine or "default", automatic=automatic, reprocess=reprocess)
    return job


def auto_ocr(doc: Document, version: DocumentVersion) -> None:
    """After the first processing of an upload: queue OCR only for Automatic types (and never for a document whose OCR
    was disabled), and only for the primary source set."""
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

def _recognise_image_tesseract(path: Path, langs: str, rotate, timeout: int, workdir: Path):
    """(text, quality, reliable_text, staged searchable pdf or None, pdfa_ok)."""
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
    out_pdf = workdir / "searchable.pdf"
    ok_pdfa, _err = _ocr(page, out_pdf, timeout, image=True, workdir=workdir, lang=langs)
    return result.text, result.quality(), result.reliable_text(), (out_pdf if out_pdf.exists() else None), ok_pdfa


def _recognise_pdf_pages(path: Path, pages: list[int], langs: str, rotate, timeout: int, workdir: Path):
    """Selected pages rendered at 300 dpi and recognised one by one with Tesseract (text, quality, reliable)."""
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


def _run_tesseract(v, original: Path, pages_spec: str, langs: list[str], rotate, timeout: int, workdir: Path) -> dict:
    lang = "+".join(langs)
    staged_pdf, pdfa = None, False
    if v.format_class == "image":
        text, quality, reliable, staged_pdf, pdfa = _recognise_image_tesseract(original, lang, rotate, timeout, workdir)
    elif not pages_spec:
        from .processing import _ocr, _pdf_info

        out_pdf = workdir / "searchable.pdf"
        pdfa, err = _ocr(original, out_pdf, timeout, image=False, workdir=workdir, lang=lang)
        if not out_pdf.exists():
            raise sandbox.ToolError(err or "OCR failed")
        staged_pdf = out_pdf
        _p, text, _e = _pdf_info(out_pdf)
        quality, reliable = {"engine": "ocrmypdf", "pages": "all"}, None
    else:
        pages = ocr_policy.parse_pages(pages_spec, v.page_count)
        text, quality, reliable = _recognise_pdf_pages(original, pages, lang, rotate, timeout, workdir)
    from . import ocr_engines

    return {"text": text, "reliable": reliable, "quality": {**quality, "languages": langs}, "staged_pdf": staged_pdf,
            "pdfa": pdfa, "engine": "tesseract", "model": f"Tesseract {lang}" + (" (ocrmypdf)" if quality.get("engine") == "ocrmypdf" else ""),
            "version": ocr_engines.tesseract_version(), "blocks": []}


def _run_paddle(v, original: Path, pages_spec: str, profile: str, timeout: int, workdir: Path) -> dict:
    from . import ocr_engines

    if v.format_class == "image":
        images = [(ocr_engines.prepare_image(original, workdir / "page-1.png"), 1)]
        paged = False
    else:
        pages = ocr_policy.parse_pages(pages_spec, v.page_count)
        images = ocr_engines.render_pdf_pages(original, pages, workdir, timeout)
        paged = True
    res = ocr_engines.paddle_recognise(images, profile, workdir, timeout)
    return {"text": res.text(paged), "reliable": res.reliable_text(), "quality": {**res.quality(), "languages": res.languages},
            "staged_pdf": None, "pdfa": False, "engine": "paddleocr", "model": res.model, "version": res.version,
            "blocks": res.blocks()}


@jobs.handler("ocr_run", heavy=True)
def ocr_run(job):
    """Recognise every source, then replace the OCR-derived data in one transaction. If any source fails, nothing is
    replaced: the previous usable result (and the search index built from it) stays as it was."""
    from . import ocr_engines
    from .models import OcrRun

    doc = Document.objects.select_related("owner", "doc_type").filter(pk=job.payload.get("document_id")).first()
    run = OcrRun.objects.filter(pk=job.payload.get("run_id")).first()
    if doc is None or doc.archived_at:
        if run:
            OcrRun.objects.filter(pk=run.pk).update(status=OcrRun.CANCELLED, finished_at=timezone.now())
        return {"skipped": "document missing or archived"}
    if config.get("processing.ocr_paused"):
        # paused: wait without using an attempt; the same job is picked up again after the delay
        job.attempts = max(0, job.attempts - 1)
        Job.objects.filter(pk=job.pk).update(attempts=job.attempts)
        raise jobs.RetryLater("OCR queue paused", delay_seconds=60)
    if ocr_policy.mode_for(doc) == "disabled" and doc.ocr_override == "disabled":
        Document.objects.filter(pk=doc.pk).update(ocr_state="disabled", ocr_updated_at=timezone.now())
        if run:
            OcrRun.objects.filter(pk=run.pk).update(status=OcrRun.CANCELLED, finished_at=timezone.now(), error="OCR disabled")
        return {"skipped": "OCR disabled for this document"}
    profile = job.payload.get("profile") or ocr_engines.profile_for(doc)
    langs = job.payload.get("languages") or ocr_engines.TESSERACT_LANGS.get(profile, ["eng"])
    rotate = job.payload.get("rotate")
    timeout = int(config.get("processing.timeout_seconds"))
    try:
        engine, note = ocr_engines.resolve_engine(job.payload.get("engine") or None)
    except ocr_engines.EngineError as exc:
        raise jobs.PermanentFailure(str(exc))
    if run:
        OcrRun.objects.filter(pk=run.pk).update(status=OcrRun.RUNNING, engine=engine,
                                                options={**(run.options or {}), "fallback": note} if note else run.options)
    Document.objects.filter(pk=doc.pk).update(ocr_state="processing", ocr_updated_at=timezone.now())
    t0 = timezone.now()
    staged = []  # (version, result) — nothing is written to the document until every source succeeded
    workdirs = []
    try:
        for s in job.payload.get("sources") or []:
            v = DocumentVersion.objects.filter(pk=s.get("version"), document=doc).first()
            if v is None:
                continue
            original = storage.resolve_original(v.storage_path)
            workdir = Path(tempfile.mkdtemp(prefix="ocr-", dir=settings.TMP_DIR))
            workdirs.append(workdir)
            if engine == "paddleocr":
                try:
                    result = _run_paddle(v, original, s.get("pages") or "", profile, timeout, workdir)
                except ocr_engines.EngineError as exc:
                    # a crash, timeout or memory-limit stop repeats on the same input: fail once (the previous result
                    # stays), never re-run a heavy job three times; the owner can re-run with other options
                    raise jobs.PermanentFailure(str(exc))
            else:
                result = _run_tesseract(v, original, s.get("pages") or "", langs, rotate, timeout, workdir)
            staged.append((v, s.get("pages") or "", result))
        _apply_run(doc, staged, profile=profile, run=run, epoch=job.payload.get("epoch"))
    finally:
        for w in workdirs:
            shutil.rmtree(w, ignore_errors=True)
    if run:
        q = [r["quality"] for _v, _p, r in staged]
        scores = [x.get("confidence") for x in q if x.get("confidence") is not None]
        OcrRun.objects.filter(pk=run.pk).update(
            status=OcrRun.DONE, finished_at=timezone.now(), seconds=round((timezone.now() - t0).total_seconds(), 1),
            confidence=round(sum(scores) / len(scores), 1) if scores else None,
            line_count=sum(int(x.get("line_count") or 0) for x in q), low_lines=sum(len(x.get("low_lines") or []) for x in q),
            engine_version=(staged[0][2]["version"] if staged else "")[:80], model=(staged[0][2]["model"] if staged else "")[:200])
    doc.refresh_from_db()
    if ocr_policy.ai_allowed(doc) and staged:
        from apps.ai.jobs import after_processing

        after_processing(doc)
    return {"sources": len(staged), "engine": engine, "profile": profile}


def _apply_run(doc: Document, staged: list, *, profile: str, run=None, epoch=None) -> None:
    """Swap in the new OCR data atomically: version text/blocks/quality, searchable copies, document text, proposals
    and the search index. A searchable copy from an earlier run that this run did not reproduce is deleted, so a stale
    text layer is never served again."""
    from .processing import _apply_to_document

    now = timezone.now()
    moved: list[Path] = []
    with transaction.atomic():
        doc = Document.objects.select_for_update(of=("self",)).select_related("owner", "doc_type").get(pk=doc.pk)
        if epoch is not None and doc.ocr_epoch != epoch:
            raise jobs.PermanentFailure("OCR data of this document was removed while the job was running; result discarded.")
        for v, pages, r in staged:
            out_dir = storage.derivative_dir(v.id)
            searchable, pdfa, report = "", False, {}
            if r["staged_pdf"] is not None:
                target = out_dir / "searchable.pdf"
                shutil.move(str(r["staged_pdf"]), target)
                moved.append(target)
                searchable = storage.derivative_rel(target)
                from .pdfa import validate

                try:
                    report = validate(target, timeout=min(int(config.get("processing.timeout_seconds")), 300))
                except Exception as exc:  # informational only
                    report = {"validator": "none", "compliant": False, "full_validation": False, "note": str(exc)[:300]}
                pdfa = bool(r["pdfa"] and report.get("compliant"))
            elif v.searchable_path:
                try:  # this run produced no searchable copy: the old one would show text that is no longer current
                    storage.resolve_derivative(v.searchable_path).unlink(missing_ok=True)
                except OSError:
                    log.warning("could not delete a superseded searchable copy")
            DocumentVersion.objects.filter(pk=v.pk).update(
                text=r["text"][:2_000_000], ocr_applied=True, ocr_quality=r["quality"], ocr_pages=pages,
                searchable_path=searchable, pdfa=pdfa, pdfa_report=report, ocr_engine=r["engine"], ocr_model=r["model"][:120],
                ocr_profile=profile, ocr_blocks=r["blocks"], ocr_at=now)
        version = staged[0][0] if staged else doc.current_version
        reliable = "\n".join(r["reliable"] if r["reliable"] is not None else r["text"] for _v, _p, r in staged)
        _apply_to_document(doc, version, document_text(doc), "ready", reliable)
        proposed = doc.fields.filter(status=DocumentField.PROPOSED).exists()
        Document.objects.filter(pk=doc.pk).update(ocr_state="needs_review" if proposed else "confirmed", ocr_error="",
                                                  ocr_profile=profile, ocr_updated_at=now)


@jobs.handler("ocr_run:failed")
def ocr_run_failed(job):
    from .models import OcrRun

    doc = Document.objects.filter(pk=job.payload.get("document_id")).first()
    if doc is not None:
        # The previous result (if any) is untouched: show it as still current, with the error.
        has_text = DocumentVersion.objects.filter(document=doc, ocr_applied=True).exists()
        Document.objects.filter(pk=doc.pk).update(
            ocr_state="failed" if not has_text else ("needs_review" if doc.ocr_state == "needs_review" else "confirmed"),
            ocr_error=(job.last_error or "OCR failed")[-500:], ocr_updated_at=timezone.now())
    OcrRun.objects.filter(pk=job.payload.get("run_id")).update(status=OcrRun.FAILED, finished_at=timezone.now(),
                                                              error=(job.last_error or "OCR failed")[-500:])


# ------------------------------------------------------------------ removal, disabling and review

def _cancel_ai(doc: Document) -> int:
    """Queued Local AI work on this document must not recreate suggestions or chunks from removed text."""
    try:
        from apps.ai.models import AIJob
    except Exception:  # noqa: BLE001 - optional component
        return 0
    ids = list(AIJob.objects.filter(document=doc, status=AIJob.QUEUED).values_list("id", flat=True))
    AIJob.objects.filter(pk__in=ids).update(status="cancelled", finished_at=timezone.now())
    Job.objects.filter(kind="ai_task", status=Job.QUEUED, payload__ai_job__in=[str(i) for i in ids]).update(
        status=Job.CANCELLED, finished_at=timezone.now())
    return len(ids)


def _version_dir_searchables(v: DocumentVersion) -> list[Path]:
    d = Path(settings.DERIVATIVES_DIR) / str(v.id)[:2] / str(v.id)
    return list(d.glob("searchable*.pdf")) if d.is_dir() else []


def remove_ocr(*, actor, doc: Document, request=None, disable: bool = False, include_embedded: bool = False,
               bulk: bool = False) -> dict:
    """Remove OCR-derived data; the original file, every version, manual and confirmed details, the document type,
    ownership/permissions and the audit history stay.

    Removed: recognised text and text blocks, geometry, confidences, searchable copies (also stale ones), proposed
    (unconfirmed) details and Local AI suggestions, semantic-search chunks, OCR type suggestions, raw OCR excerpts kept
    next to confirmed details, queued Local AI work and the search-index entries built from all of that.
    ``disable`` also stops OCR for this document until it is enabled again. ``include_embedded`` additionally hides
    the text layer embedded in the file itself (from a scanner or an earlier OCR program)."""
    from apps.ai.models import AISuggestion

    from .processing import _pdf_info
    from .search import update_search_vector

    if _active_job(doc):
        raise OCRError("Text recognition is queued or running; cancel it or wait before removing OCR data.")
    removed_files, bytes_freed, engines = 0, 0, set()
    with transaction.atomic():
        doc = Document.objects.select_for_update(of=("self",)).get(pk=doc.pk)
        hide_embedded = include_embedded or doc.ignore_embedded_text
        for v in DocumentVersion.objects.filter(document=doc):
            if not v.ocr_applied and not (hide_embedded and v.text):
                for p in _version_dir_searchables(v):  # stale copy without an OCR record
                    bytes_freed += p.stat().st_size
                    p.unlink(missing_ok=True)
                    removed_files += 1
                continue
            if v.ocr_applied:
                engines.add(v.ocr_engine or "unknown")
            native = ""
            if v.format_class == "pdf" and not hide_embedded:
                _p, native, _e = _pdf_info(storage.resolve_original(v.storage_path))
            for p in _version_dir_searchables(v):
                try:
                    bytes_freed += p.stat().st_size
                    p.unlink(missing_ok=True)
                    removed_files += 1
                except OSError:
                    log.warning("could not delete a searchable copy")
            bytes_freed += len((v.text or "").encode()) + len(str(v.ocr_blocks or "").encode())
            DocumentVersion.objects.filter(pk=v.pk).update(
                text=native, ocr_applied=False, ocr_quality={}, ocr_pages="", searchable_path="", pdfa=False,
                pdfa_report={}, ocr_engine="", ocr_model="", ocr_profile="", ocr_blocks=[], ocr_at=None)
        fields = DocumentField.objects.filter(document=doc, status=DocumentField.PROPOSED).exclude(source="manual")
        n_fields = fields.count()
        fields.delete()
        # Confirmed details stay (and keep their provenance label); only the raw OCR snippet and pending readings go.
        DocumentField.objects.filter(document=doc, status=DocumentField.CONFIRMED).update(proposed_value="", flags=[])
        DocumentField.objects.filter(document=doc).exclude(source="manual").update(source_excerpt="")
        n_ai = AISuggestion.objects.filter(document=doc, status=AISuggestion.PENDING).delete()[0]
        n_ai_jobs = _cancel_ai(doc)
        try:  # semantic-search chunks are derived from the recognised text too
            from apps.ai.models import DocumentChunk

            n_chunks = DocumentChunk.objects.filter(document=doc).delete()[0]
        except Exception:  # noqa: BLE001 - optional component
            n_chunks = 0
        doc.ignore_embedded_text = hide_embedded
        doc.content_text = document_text(doc)
        doc.type_suggestions = [x for x in doc.type_suggestions or [] if x.get("source") != "ocr"]  # derived from the text
        doc.ocr_state = "disabled" if disable else "removed"
        doc.ocr_error, doc.ocr_updated_at, doc.ocr_sources, doc.ocr_languages, doc.ocr_profile = "", timezone.now(), [], [], ""
        doc.ocr_epoch += 1
        if disable:
            doc.ocr_override = "disabled"
        if doc.state == Document.NEEDS_REVIEW and not doc.fields.filter(status=DocumentField.PROPOSED).exists() and not doc.review_flags:
            doc.state = Document.READY
        doc.save(update_fields=["content_text", "type_suggestions", "ocr_state", "ocr_error", "ocr_updated_at", "state",
                                "ocr_sources", "ocr_languages", "ocr_profile", "ocr_epoch", "ocr_override",
                                "ignore_embedded_text", "updated_at"])
        update_search_vector(doc)
    # the audit entry records what was removed, never the removed text
    audit.record("document.ocr_remove", request=request, actor=actor, target=doc, removal="remove_disable" if disable else "remove",
                 engines=sorted(engines), embedded_text_hidden=include_embedded, proposals_removed=n_fields,
                 ai_suggestions_removed=n_ai, ai_jobs_cancelled=n_ai_jobs, chunks_removed=n_chunks, files_removed=removed_files,
                 bulk=bulk)
    return {"proposals_removed": n_fields, "ai_suggestions_removed": n_ai, "files_removed": removed_files,
            "chunks_removed": n_chunks, "bytes_freed": bytes_freed, "engines": sorted(engines)}


def set_ocr_disabled(*, actor, doc: Document, disabled: bool, remove_existing: bool = False, request=None,
                     bulk: bool = False) -> dict:
    """Disable OCR for one document (persistent override; beats an Automatic type) or enable it again."""
    if disabled and remove_existing:
        return remove_ocr(actor=actor, doc=doc, request=request, disable=True, bulk=bulk)
    if disabled:
        job = _active_job(doc)
        if job is not None and job.status == Job.QUEUED:
            cancel_ocr(actor=actor, doc=doc, request=request)
        elif job is not None:
            raise OCRError("Text recognition is running for this document; wait for it to finish, then disable OCR.")
    has_text = DocumentVersion.objects.filter(document=doc, ocr_applied=True).exists()
    state = "disabled" if disabled else ("confirmed" if has_text else "not_processed")
    Document.objects.filter(pk=doc.pk).update(ocr_override="disabled" if disabled else "", ocr_state=state,
                                              ocr_updated_at=timezone.now())
    audit.record("document.ocr_disable" if disabled else "document.ocr_enable", request=request, actor=actor, target=doc,
                 bulk=bulk, kept_existing=bool(disabled and has_text))
    return {"ocr_override": "disabled" if disabled else "", "kept_existing": bool(disabled and has_text)}


def mark_reviewed(*, actor, doc: Document, request=None) -> None:
    Document.objects.filter(pk=doc.pk).update(ocr_state="confirmed", ocr_updated_at=timezone.now())
    audit.record("document.ocr_reviewed", request=request, actor=actor, target=doc)
