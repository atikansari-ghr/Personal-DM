"""PDF/A conformance checking for searchable derivatives.

* veraPDF (the PDF Association's reference validator) is used when installed (`PD_VERAPDF_CMD`, default
  `verapdf`). Its verdict is a real conformance validation against the PDF/A-2B profile.
* Otherwise a built-in structural check runs with pypdf: PDF/A identification in XMP metadata, an output
  intent with an ICC profile, no encryption, no JavaScript/launch actions, embedded fonts and a file ID.
  It catches common problems but is NOT a full conformance validation; the result says so.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from django.conf import settings

from . import sandbox

FLAVOUR = "2b"


def verapdf_cmd() -> str | None:
    cmd = getattr(settings, "VERAPDF_CMD", "verapdf")
    found = shutil.which(cmd) or (cmd if Path(cmd).is_file() else None)
    # Only use it when this (service) user can actually run it, e.g. not a root-only /opt/verapdf.
    return found if found and os.access(found, os.X_OK) else None


def validate(path: Path, timeout: int = 300) -> dict:
    cmd = verapdf_cmd()
    if cmd:
        try:
            return _verapdf(cmd, path, timeout)
        except Exception as exc:  # optional validator: any failure falls back to the structural check
            result = _builtin(path)
            result["note"] = f"veraPDF could not run ({exc}); structural check used instead."
            return result
    return _builtin(path)


def _verapdf(cmd: str, path: Path, timeout: int) -> dict:
    # veraPDF is a Java program: it needs more address space than the converters' default limit.
    proc = sandbox.run([cmd, "--flavour", FLAVOUR, "--format", "json", str(path)], timeout=timeout,
                       cwd=Path(settings.TMP_DIR), memory_mb=max(settings.PROCESS_MEMORY_LIMIT_MB, 4096),
                       extra_env={"JAVA_TOOL_OPTIONS": "-Xmx512m"})
    out = proc.stdout.decode(errors="replace")
    start = out.find("{")
    if start < 0:
        raise ValueError("no JSON output")
    data = json.loads(out[start:])
    result = data["report"]["jobs"][0]["validationResult"]
    result = result[0] if isinstance(result, list) else result
    failed = [{"clause": r.get("clause", ""), "test": r.get("testNumber"), "description": (r.get("description") or "")[:200]}
              for r in result.get("details", {}).get("ruleSummaries", []) if r.get("ruleStatus", "FAILED") == "FAILED"]
    return {"validator": "verapdf", "profile": result.get("profileName", "PDF/A-2b"), "compliant": bool(result.get("compliant")),
            "failed_rules": failed[:30], "full_validation": True}


def _builtin(path: Path) -> dict:
    from pypdf import PdfReader
    from pypdf.generic import IndirectObject

    problems: list[str] = []
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001
        return {"validator": "builtin", "compliant": False, "failed_rules": [{"description": f"Unreadable PDF: {exc.__class__.__name__}"}],
                "full_validation": False, "profile": "structural check"}
    if reader.is_encrypted:
        problems.append("File is encrypted.")
    root = reader.trailer["/Root"]
    meta = root.get("/Metadata")
    xmp = b""
    if meta is not None:
        try:
            xmp = meta.get_object().get_data()
        except Exception:  # noqa: BLE001
            xmp = b""
    part = re.search(rb"pdfaid:part(?:>|=\")\s*(\d)", xmp)
    conf = re.search(rb"pdfaid:conformance(?:>|=\")\s*([ABUabu])", xmp)
    if not part or not conf:
        problems.append("No PDF/A identification (pdfaid:part/conformance) in XMP metadata.")
    intents = root.get("/OutputIntents") or []
    if not any(i.get_object().get("/S") == "/GTS_PDFA1" and i.get_object().get("/DestOutputProfile") is not None for i in intents):
        problems.append("No PDF/A output intent with an embedded ICC profile.")
    if "/ID" not in reader.trailer:
        problems.append("Trailer has no file identifier (/ID).")
    names = root.get("/Names")
    if names is not None and "/JavaScript" in names.get_object():
        problems.append("Document contains JavaScript.")
    open_action = root.get("/OpenAction")
    if open_action is not None and isinstance(open_action.get_object(), dict) and open_action.get_object().get("/S") in ("/JavaScript", "/Launch"):
        problems.append("Document has a JavaScript or launch open action.")
    unembedded: set[str] = set()
    for page in reader.pages[:200]:
        res = page.get("/Resources")
        fonts = res.get_object().get("/Font") if res is not None else None
        if not fonts:
            continue
        for _name, ref in fonts.get_object().items():
            font = ref.get_object() if isinstance(ref, IndirectObject) else ref
            targets = [font]
            if font.get("/Subtype") == "/Type0":
                targets = [d.get_object() for d in font.get("/DescendantFonts", [])]
            for f in targets:
                if f.get("/Subtype") == "/Type3":
                    continue
                desc = f.get("/FontDescriptor")
                desc = desc.get_object() if desc is not None else None
                if desc is None or not any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3")):
                    unembedded.add(str(f.get("/BaseFont", "unknown")))
    if unembedded:
        problems.append(f"Fonts not embedded: {', '.join(sorted(unembedded)[:5])}.")
    level = f"PDF/A-{part.group(1).decode()}{conf.group(1).decode().lower()}" if part and conf else "unknown"
    return {"validator": "builtin", "profile": f"structural check (claims {level})", "compliant": not problems,
            "failed_rules": [{"description": p} for p in problems], "full_validation": False}
