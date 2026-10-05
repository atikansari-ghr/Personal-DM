"""File-type identification for icons and labels.

The type shown to people is derived from the *validated* MIME type recorded at upload (content signatures, see
``services.detect_format``) and, for Office/archive containers, from an extension that was checked against the
container format. A renamed file therefore never gets a misleading icon: ``holiday.pdf`` that is really a PNG shows
as PNG, and ``report.docx`` that is not a Word container shows as "Other".
"""
from __future__ import annotations

import zipfile
from pathlib import Path

OOXML = {
    ".docx": ("word/", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xlsx": ("xl/", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".pptx": ("ppt/", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}
ODF = {
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
}
OLE = {".doc": "application/msword", ".xls": "application/vnd.ms-excel", ".ppt": "application/vnd.ms-powerpoint"}
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"
ARCHIVES = (
    (ZIP_MAGIC, "application/zip"),
    (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (b"Rar!\x1a\x07", "application/vnd.rar"),
    (b"\x1f\x8b", "application/gzip"),
)

# kind -> (short text shown on the icon, accessible description)
KINDS = {
    "pdf": ("PDF", "PDF document"),
    "jpeg": ("JPG", "JPEG image"),
    "png": ("PNG", "PNG image"),
    "webp": ("WEBP", "WebP image"),
    "image": ("IMG", "Image"),
    "text": ("TXT", "Text file"),
    "word": ("DOC", "Word document"),
    "excel": ("XLS", "Spreadsheet"),
    "powerpoint": ("PPT", "Presentation"),
    "archive": ("ZIP", "Compressed archive"),
    "dicom": ("DCM", "DICOM medical image"),
    "other": ("FILE", "Other file"),
}

MIME_KIND = {
    "application/pdf": "pdf", "image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp",
    "text/plain": "text", "text/csv": "excel", "application/dicom": "dicom",
    "application/msword": "word", "application/rtf": "word",
    "application/vnd.ms-excel": "excel", "application/vnd.ms-powerpoint": "powerpoint",
    OOXML[".docx"][1]: "word", OOXML[".xlsx"][1]: "excel", OOXML[".pptx"][1]: "powerpoint",
    ODF[".odt"]: "word", ODF[".ods"]: "excel", ODF[".odp"]: "powerpoint",
}
EXT_KIND = {".doc": "word", ".docx": "word", ".odt": "word", ".rtf": "word", ".xls": "excel", ".xlsx": "excel",
            ".ods": "excel", ".csv": "excel", ".ppt": "powerpoint", ".pptx": "powerpoint", ".odp": "powerpoint"}


def office_mime(path: Path, ext: str, head: bytes) -> str:
    """MIME type for an Office upload, or application/octet-stream when the content does not match the extension."""
    if ext in OOXML and head.startswith(ZIP_MAGIC):
        prefix, mime = OOXML[ext]
        try:
            with zipfile.ZipFile(path) as zf:
                if any(n.startswith(prefix) for n in zf.namelist()[:2000]):
                    return mime
        except (zipfile.BadZipFile, OSError, ValueError):
            pass
    elif ext in ODF and head.startswith(ZIP_MAGIC) and ODF[ext].encode() in head[:200]:
        return ODF[ext]
    elif ext in OLE and head.startswith(OLE_MAGIC):
        return OLE[ext]
    elif ext == ".rtf" and head.startswith(b"{\\rtf"):
        return "application/rtf"
    elif ext == ".csv" and b"\x00" not in head:
        return "text/csv"
    return "application/octet-stream"


def archive_mime(head: bytes) -> str | None:
    for magic, mime in ARCHIVES:
        if head.startswith(magic):
            return mime
    return None


def kind_for(mime: str, format_class: str, original_name: str = "") -> str:
    mime = (mime or "").lower()
    if mime in MIME_KIND:
        return MIME_KIND[mime]
    if format_class == "dicom":
        return "dicom"
    if mime in {m for _, m in ARCHIVES}:
        return "archive"
    if format_class == "image" or mime.startswith("image/"):
        return "image"
    if format_class == "text":
        return "text"
    if format_class == "pdf":
        return "pdf"
    if format_class == "office":
        # Uploads before content validation recorded Office files without a specific MIME type.
        return EXT_KIND.get(Path(original_name or "").suffix.lower(), "other")
    return "other"


def describe(version) -> dict:
    if version is None:
        return {"file_kind": "other", "file_label": KINDS["other"][1]}
    kind = kind_for(version.mime, version.format_class, version.original_name)
    return {"file_kind": kind, "file_label": KINDS[kind][1]}
