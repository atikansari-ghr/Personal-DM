"""Background processing of document versions: native text extraction, previews, thumbnails, field proposals.

Text recognition (OCR) is *not* done here. It is selective (Change Set K): it runs only when a person asks for it
or when the document type's policy is Automatic, and only on the chosen source files/pages (see ocr_runs.py).
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import transaction

from apps.core import config
from apps.core.jobs import PermanentFailure, handler

from . import sandbox, storage
from .extraction import extract
from .models import Document, DocumentField, DocumentVersion

log = logging.getLogger("personaldocs.processing")

MAX_TEXT = 2_000_000


def _pdf_info(path: Path) -> tuple[int, str, bool]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return 0, "", True
        pages = len(reader.pages)
        text_parts = []
        for i, page in enumerate(reader.pages):
            if i >= 500:
                break
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - malformed page
                text_parts.append("")
        return pages, "\n".join(text_parts)[:MAX_TEXT], False
    except Exception as exc:  # noqa: BLE001
        log.warning("pdf parse failed: %s", exc.__class__.__name__)
        return 0, "", False


def _thumbnail_pdf(pdf: Path, out_dir: Path, timeout: int) -> str:
    prefix = out_dir / "thumb"
    proc = sandbox.run([settings.PDFTOPPM_CMD, "-png", "-f", "1", "-l", "1", "-scale-to", "480", "-singlefile", str(pdf), str(prefix)],
                       timeout=min(timeout, 120), cwd=out_dir)
    thumb = out_dir / "thumb.png"
    if proc.returncode == 0 and thumb.exists():
        return storage.derivative_rel(thumb)
    return ""


def _thumbnail_image(img_path: Path, out_dir: Path, max_mp: int) -> str:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = max_mp * 1_000_000
    with Image.open(img_path) as im:
        im.thumbnail((480, 480))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        thumb = out_dir / "thumb.png"
        im.save(thumb, "PNG")
    return storage.derivative_rel(thumb)


def _ocr(src: Path, out_pdf: Path, timeout: int, *, image: bool, workdir: Path, lang: str = "eng") -> tuple[bool, str]:
    cmd = list(settings.OCRMYPDF_CMD) + [
        "--output-type", "pdfa-2", "-l", lang, "--jobs", "1",
        "--skip-text", "--optimize", "0", "--quiet",
    ]
    if image:
        cmd += ["--image-dpi", "300"]
    else:
        cmd += ["--rotate-pages"]  # upside-down / sideways scanned pages (Tesseract orientation model)
    cmd += [str(src), str(out_pdf)]
    proc = sandbox.run(cmd, timeout=timeout, cwd=workdir)
    if proc.returncode in (0, 10) and out_pdf.exists():  # 10 = PDF/A conversion warning but output written
        return proc.returncode == 0, ""
    return False, proc.stderr.decode(errors="replace")[-500:]


def _office_to_pdf(src: Path, workdir: Path, timeout: int) -> Path | None:
    profile = workdir / "lo-profile"
    safe = workdir / ("input" + src.suffix.lower())
    shutil.copyfile(src, safe)
    proc = sandbox.run([settings.SOFFICE_CMD, "--headless", "--norestore", "--nolockcheck", "--nodefault",
                        f"-env:UserInstallation=file://{profile}", "--convert-to", "pdf", "--outdir", str(workdir), str(safe)],
                       timeout=timeout, cwd=workdir, memory_mb=max(settings.PROCESS_MEMORY_LIMIT_MB, 2048))
    out = workdir / "input.pdf"
    return out if proc.returncode == 0 and out.exists() else None


@handler("process_version", heavy=True)
def process_version(job):
    vid = job.payload.get("version_id")
    version = DocumentVersion.objects.select_related("document", "document__owner", "document__doc_type").filter(pk=vid).first()
    if version is None:
        return {"skipped": "version deleted"}
    doc = version.document
    if version.av_blocked:
        return {"skipped": "quarantined"}
    original = storage.resolve_original(version.storage_path)
    if not original.exists():
        raise PermanentFailure("Original file is missing from storage")
    DocumentVersion.objects.filter(pk=vid).update(state="processing", error="")
    if doc.current_version_id == version.id:
        Document.objects.filter(pk=doc.pk).update(state=Document.PROCESSING)

    timeout = int(config.get("processing.timeout_seconds"))
    max_mp = int(config.get("processing.max_image_megapixels"))
    out_dir = storage.derivative_dir(version.id)
    storage.ensure_dirs()
    workdir = Path(tempfile.mkdtemp(prefix="proc-", dir=settings.TMP_DIR))
    fmt = version.format_class
    text, preview, thumb = "", "", ""
    pages, state, error = None, "ready", ""
    needs_ocr = False  # the file has no usable native text (a scan or a photo)
    try:
        if fmt == "pdf":
            pages, text, encrypted = _pdf_info(original)
            if encrypted:
                state, error = "unsupported", "Password-protected PDF: stored safely; preview and OCR are not possible."
            else:
                needs_ocr = len(text.strip()) < max(40, 25 * (pages or 1))
                thumb = _thumbnail_pdf(original, out_dir, timeout)
        elif fmt == "image":
            from PIL import Image

            Image.MAX_IMAGE_PIXELS = max_mp * 1_000_000
            try:
                with Image.open(original) as im:
                    w, h = im.size
                    if w * h > max_mp * 1_000_000:
                        raise Image.DecompressionBombError("too large")
                    im.verify()
                thumb = _thumbnail_image(original, out_dir, max_mp)
                pages, needs_ocr = 1, True
            except (Image.DecompressionBombError, Image.UnidentifiedImageError, OSError) as exc:
                state, error = "unsupported", f"Image could not be processed safely ({exc.__class__.__name__})."
        elif fmt == "text":
            with open(original, "rb") as fh:
                text = fh.read(MAX_TEXT).decode("utf-8", errors="replace")
        elif fmt == "office":
            pdf = _office_to_pdf(original, workdir, timeout)
            if pdf is None:
                state, error = "unsupported", "Local preview conversion failed. The original can still be downloaded."
            else:
                target = out_dir / "preview.pdf"
                shutil.move(str(pdf), target)
                preview = storage.derivative_rel(target)
                pages, text, _e = _pdf_info(target)
                thumb = _thumbnail_pdf(target, out_dir, timeout)
        elif fmt == "dicom":
            state, error = "unsupported", "DICOM files are preserved for download and use in an external viewer."
        else:
            state, error = "unsupported", "No preview is available for this file type. It is stored safely for download."
    except sandbox.ToolError as exc:
        state, error = "failed", str(exc)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    with transaction.atomic():
        # A new upload of the same version (re-processing) keeps earlier OCR results unless OCR is re-run.
        current = DocumentVersion.objects.get(pk=vid)
        keep_ocr = current.ocr_applied
        updates = dict(preview_path=preview, thumbnail_path=thumb, page_count=pages, state=state, error=error[:2000])
        if not keep_ocr:
            updates["text"] = text
        DocumentVersion.objects.filter(pk=vid).update(**updates)
        doc = Document.objects.select_for_update(of=("self",)).select_related("owner", "doc_type").get(pk=doc.pk)
        if doc.current_version_id == version.id and not version.is_additional:
            from .ocr_runs import document_text

            _apply_to_document(doc, version, document_text(doc), state)
    if state in ("ready", "unsupported") and needs_ocr and not keep_ocr:
        from .ocr_runs import auto_ocr

        auto_ocr(doc, version)
    elif state == "ready" and text.strip() and doc.current_version_id == version.id:
        from . import ocr_policy

        if ocr_policy.ai_allowed(doc):  # native text of a type the administrator opened to Local AI
            from apps.ai.jobs import after_processing

            after_processing(doc)
    return {"state": state, "pages": pages, "needs_ocr": needs_ocr}


def _apply_to_document(doc: Document, version: DocumentVersion, text: str, version_state: str,
                       reliable: str | None = None) -> None:
    from .search import update_search_vector

    doc.content_text = text
    owner_names = [n for n in (doc.owner.display_name, doc.owner.full_name) if n]
    template = doc.doc_type.template if doc.doc_type_id else "generic"
    # Low-confidence OCR lines stay searchable but never become suggested details.
    source = reliable if reliable is not None else text
    proposals = extract(source, owner_names=owner_names, template=template) if source else []
    existing = {f.key: f for f in doc.fields.all()}
    for p in proposals:
        f = existing.get(p.key)
        if f and f.status == DocumentField.CONFIRMED:
            if f.value != p.value:
                f.proposed_value = p.value
                f.flags = list(set((f.flags or []) + [f"New scan suggests '{p.value}'."])) if p.key not in DocumentField.SENSITIVE else list(set((f.flags or []) + ["New scan suggests a different value."]))
                f.save(update_fields=["proposed_value", "flags"])
            continue
        DocumentField.objects.update_or_create(
            document=doc, key=p.key,
            defaults={"value": p.value, "status": DocumentField.PROPOSED, "source": p.source, "version": version,
                      "confidence": p.confidence, "flags": p.flags, "source_excerpt": "" if p.key in DocumentField.SENSITIVE else p.excerpt[:300]})
    has_proposed = doc.fields.filter(status=DocumentField.PROPOSED).exists()
    if version_state == "failed":
        doc.state = Document.FAILED
        from apps.notify import events

        transaction.on_commit(lambda: events.processing_failed(version))
    elif version_state == "unsupported":
        doc.state = Document.NEEDS_REVIEW if has_proposed else Document.UNSUPPORTED
    else:
        doc.state = Document.NEEDS_REVIEW if (has_proposed or doc.review_flags) else Document.READY
        if version_state == "ready":
            from apps.notify import events

            transaction.on_commit(lambda: events.processing_completed(version))
    doc.save(update_fields=["content_text", "state", "updated_at"])
    update_search_vector(doc)


@handler("process_version:failed")
def process_version_failed(job):
    vid = job.payload.get("version_id")
    v = DocumentVersion.objects.filter(pk=vid).first()
    if v:
        DocumentVersion.objects.filter(pk=vid).update(state="failed", error=job.last_error[:500])
        Document.objects.filter(pk=v.document_id, current_version_id=vid).update(state=Document.FAILED)
        from apps.notify import events

        events.processing_failed(v)
