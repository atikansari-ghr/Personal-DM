"""Background processing of document versions: text extraction, local OCR, previews, thumbnails, field proposals."""
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


def _ocr(src: Path, out_pdf: Path, timeout: int, *, image: bool, workdir: Path) -> tuple[bool, str]:
    cmd = list(settings.OCRMYPDF_CMD) + [
        "--output-type", "pdfa-2", "-l", config.get("processing.ocr_language"), "--jobs", "1",
        "--skip-text", "--optimize", "0", "--quiet",
    ]
    if image:
        cmd += ["--image-dpi", "300"]
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
    original = storage.resolve_original(version.storage_path)
    if not original.exists():
        raise PermanentFailure("Original file is missing from storage")
    DocumentVersion.objects.filter(pk=vid).update(state="processing", error="")
    if doc.current_version_id == version.id:
        Document.objects.filter(pk=doc.pk).update(state=Document.PROCESSING)

    timeout = int(config.get("processing.timeout_seconds"))
    max_pages = int(config.get("processing.max_pages"))
    max_mp = int(config.get("processing.max_image_megapixels"))
    ocr_enabled = bool(config.get("processing.ocr_enabled"))
    out_dir = storage.derivative_dir(version.id)
    storage.ensure_dirs()
    workdir = Path(tempfile.mkdtemp(prefix="proc-", dir=settings.TMP_DIR))
    fmt = version.format_class
    text, preview, searchable, thumb = "", "", "", ""
    pages, ocr_applied, pdfa, state, error = None, False, False, "ready", ""
    try:
        if fmt == "pdf":
            pages, text, encrypted = _pdf_info(original)
            if encrypted:
                state, error = "unsupported", "Password-protected PDF: stored safely; preview and OCR are not possible."
            else:
                needs_ocr = len(text.strip()) < max(40, 25 * (pages or 1))
                if needs_ocr and ocr_enabled and pages and pages <= max_pages:
                    out_pdf = out_dir / "searchable.pdf"
                    ok_pdfa, err = _ocr(original, out_pdf, timeout, image=False, workdir=workdir)
                    if out_pdf.exists():
                        searchable = storage.derivative_rel(out_pdf)
                        ocr_applied, pdfa = True, ok_pdfa
                        _p, text, _e = _pdf_info(out_pdf)
                    else:
                        error = f"OCR failed: {err}" if err else "OCR failed"
                elif needs_ocr and pages and pages > max_pages:
                    error = f"OCR skipped: {pages} pages exceeds the limit of {max_pages}."
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
                if ocr_enabled:
                    src = original
                    if version.mime not in ("image/jpeg", "image/png", "image/tiff"):
                        src = workdir / "convert.png"
                        with Image.open(original) as im:
                            im.convert("RGB").save(src, "PNG")
                    out_pdf = out_dir / "searchable.pdf"
                    ok_pdfa, err = _ocr(src, out_pdf, timeout, image=True, workdir=workdir)
                    if out_pdf.exists():
                        searchable = storage.derivative_rel(out_pdf)
                        ocr_applied, pdfa = True, ok_pdfa
                        pages, text, _e = _pdf_info(out_pdf)
                    else:
                        error = f"OCR failed: {err}" if err else "OCR failed"
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
        DocumentVersion.objects.filter(pk=vid).update(
            text=text, preview_path=preview, searchable_path=searchable, thumbnail_path=thumb, page_count=pages,
            ocr_applied=ocr_applied, pdfa=pdfa, state=state, error=error[:2000])
        doc = Document.objects.select_for_update(of=("self",)).select_related("owner", "doc_type").get(pk=doc.pk)
        if doc.current_version_id == version.id:
            _apply_to_document(doc, version, text, state)
    return {"state": state, "ocr": ocr_applied, "pages": pages}


def _apply_to_document(doc: Document, version: DocumentVersion, text: str, version_state: str) -> None:
    from .search import update_search_vector

    doc.content_text = text
    owner_names = [n for n in (doc.owner.display_name, doc.owner.full_name) if n]
    template = doc.doc_type.template if doc.doc_type_id else "generic"
    proposals = extract(text, owner_names=owner_names, template=template) if text else []
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
    elif version_state == "unsupported":
        doc.state = Document.NEEDS_REVIEW if has_proposed else Document.UNSUPPORTED
    else:
        doc.state = Document.NEEDS_REVIEW if (has_proposed or doc.review_flags) else Document.READY
    doc.save(update_fields=["content_text", "state", "updated_at"])
    update_search_vector(doc)


@handler("process_version:failed")
def process_version_failed(job):
    vid = job.payload.get("version_id")
    v = DocumentVersion.objects.filter(pk=vid).first()
    if v:
        DocumentVersion.objects.filter(pk=vid).update(state="failed", error=job.last_error[:500])
        Document.objects.filter(pk=v.document_id, current_version_id=vid).update(state=Document.FAILED)
