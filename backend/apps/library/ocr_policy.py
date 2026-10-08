"""Selective OCR policy: which documents are recognised, with which languages and limits (Change Set K).

OCR is opt-in. Each document type is Disabled, Manual or Automatic; documents without a type follow
``processing.ocr_untyped_mode``. Automatic OCR processes only the document's primary OCR source set, never every
file or historical version. Fresh installations default to Manual.
"""
from __future__ import annotations

import functools
import re
import subprocess

from django.conf import settings

from apps.core import config
from apps.core.registry import _OCR_LANGS

# Structured fields offered for review per template (they must exist in the extraction rules / DocumentField keys).
TEMPLATE_FIELDS = {
    "passport": ["document_number", "full_name", "nationality", "date_of_birth", "issue_date", "expiry_date"],
    "visa": ["document_number", "full_name", "issue_date", "expiry_date"],
    "iqama": ["document_number", "full_name", "nationality", "issue_date", "expiry_date", "no_expiry"],
    "national_id": ["document_number", "full_name", "date_of_birth", "issue_date", "expiry_date", "no_expiry"],
    "driving_license": ["document_number", "full_name", "issue_date", "expiry_date"],
    "employee_id": ["document_number", "full_name", "issuer", "expiry_date", "no_expiry"],
    "insurance": ["document_number", "issuer", "issue_date", "expiry_date"],
    "certificate": ["full_name", "issuer", "issue_date"],
    "generic": [],
}

LANGUAGE_NAMES = _OCR_LANGS
LANG_RX = re.compile(r"^[a-z]{3}(_[a-z]{3,4})?$")


@functools.lru_cache(maxsize=1)
def _installed_cached() -> tuple[str, ...]:
    try:
        out = subprocess.run([settings.TESSERACT_CMD, "--list-langs"], capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return ()
    lines = out.stdout.decode(errors="replace").splitlines()[1:]
    return tuple(sorted(x.strip() for x in lines if LANG_RX.match(x.strip()) and x.strip() != "osd"))


def installed_languages() -> list[str]:
    return list(_installed_cached())


def refresh_languages() -> None:
    _installed_cached.cache_clear()


def configured_languages() -> list[str]:
    """Languages the administrator offers (Settings -> OCR & processing)."""
    langs = config.get("processing.ocr_languages") or ["eng"]
    return [x for x in langs if LANG_RX.match(x)]


def language_status() -> list[dict]:
    installed = set(installed_languages())
    codes = sorted(set(configured_languages()) | installed, key=lambda c: (c not in configured_languages(), c))
    return [{"code": c, "name": LANGUAGE_NAMES.get(c, c), "configured": c in configured_languages(), "installed": c in installed}
            for c in codes]


def missing_languages() -> list[str]:
    installed = set(installed_languages())
    return [c for c in configured_languages() if c not in installed]


def mode_for(doc) -> str:
    """Effective OCR mode: global switch, then the document's own override (Disable OCR for this document beats an
    Automatic type), then the document type, then the setting for documents without a type."""
    if not config.get("processing.ocr_enabled"):
        return "disabled"
    if getattr(doc, "ocr_override", "") == "disabled":
        return "disabled"
    if doc.doc_type_id and doc.doc_type:
        return doc.doc_type.ocr_mode
    return config.get("processing.ocr_untyped_mode")


def default_languages(doc) -> list[str]:
    if doc.doc_type_id and doc.doc_type and doc.doc_type.ocr_languages:
        return list(doc.doc_type.ocr_languages)
    return configured_languages()[:1] or ["eng"]


def ai_allowed(doc) -> bool:
    """Local AI may only read recognised text of types the administrator explicitly allowed."""
    if doc.doc_type_id and doc.doc_type:
        return bool(doc.doc_type.ocr_ai_allowed)
    return bool(config.get("processing.ocr_untyped_ai_allowed"))


def parse_pages(spec: str, page_count: int | None) -> list[int]:
    """'1-3, 5' -> [1, 2, 3, 5]; '' -> all pages. Raises ValueError for anything outside 1..page_count."""
    spec = (spec or "").strip()
    if not spec:
        return list(range(1, (page_count or 1) + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d{1,5})(?:\s*-\s*(\d{1,5}))?", part)
        if not m:
            raise ValueError(f"'{part}' is not a page or page range (examples: 2, 1-3, 1-2, 5).")
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if a < 1 or b < a:
            raise ValueError(f"'{part}' is not a valid range.")
        if page_count and b > page_count:
            raise ValueError(f"Page {b} does not exist (this file has {page_count} page{'s' if page_count != 1 else ''}).")
        pages.update(range(a, b + 1))
    return sorted(pages)
