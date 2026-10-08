"""Integrity checker: missing files, checksum mismatches, broken references, orphans. Read-only by default."""
from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.core import crypto


def check(verify_checksums: bool = True, limit_report: int = 500) -> dict:
    from apps.library.models import Document, DocumentVersion

    problems = []
    referenced = set()
    referenced_deriv = set()
    for v in DocumentVersion.objects.all().iterator():
        referenced.add(v.storage_path)
        p = Path(settings.ORIGINALS_DIR) / v.storage_path
        if v.av_status == "quarantined":  # moved to <data>/quarantine on purpose
            if v.av_quarantine_path and not (Path(settings.DATA_DIR) / "quarantine" / v.av_quarantine_path).exists():
                problems.append({"type": "missing_quarantine", "version": str(v.id), "document": str(v.document_id)})
            continue
        if not p.exists():
            problems.append({"type": "missing_original", "version": str(v.id), "document": str(v.document_id), "path": v.storage_path})
        elif p.stat().st_size != v.size:
            problems.append({"type": "size_mismatch", "version": str(v.id), "document": str(v.document_id)})
        elif verify_checksums and crypto.sha256_file(p) != v.sha256:
            problems.append({"type": "checksum_mismatch", "version": str(v.id), "document": str(v.document_id)})
        for rel in (v.preview_path, v.searchable_path, v.thumbnail_path):
            if rel:
                referenced_deriv.add(str(Path(rel).parent))
                if not (Path(settings.DERIVATIVES_DIR) / rel).exists():
                    problems.append({"type": "missing_derivative", "version": str(v.id), "document": str(v.document_id),
                                     "repair": "reprocess"})
    for d in Document.objects.filter(current_version__isnull=True):
        problems.append({"type": "no_current_version", "document": str(d.id)})
    for d in Document.objects.exclude(current_version__isnull=True).select_related("current_version"):
        if d.current_version.document_id != d.id:
            problems.append({"type": "broken_version_reference", "document": str(d.id)})
    orphans = []
    base = Path(settings.ORIGINALS_DIR)
    if base.exists():
        for f in base.rglob("*"):
            if f.is_file() and str(f.relative_to(base)) not in referenced:
                orphans.append(str(f.relative_to(base)))
    dbase = Path(settings.DERIVATIVES_DIR)
    orphan_derivs = []
    if dbase.exists():
        known = {str(v.id) for v in DocumentVersion.objects.only("id")}
        for shard in dbase.iterdir():
            if shard.is_dir():
                for vdir in shard.iterdir():
                    if vdir.is_dir() and vdir.name not in known:
                        orphan_derivs.append(str(vdir.relative_to(dbase)))
    for o in orphans:
        problems.append({"type": "orphan_original", "path": o, "repair": "quarantine"})
    for o in orphan_derivs:
        problems.append({"type": "orphan_derivative", "path": o, "repair": "remove_derivative"})
    return {"checked_at": timezone.now().isoformat(), "versions": len(referenced), "problems": problems[:limit_report],
            "problem_count": len(problems), "ok": not problems}


def repair(dry_run: bool = True) -> list[str]:
    """Non-destructive repairs: re-queue processing for missing derivatives; quarantine (never delete) orphan originals;
    remove orphan derivative folders (they are regenerable). Missing originals cannot be reconstructed."""
    from apps.core import jobs

    actions = []
    report = check(verify_checksums=False, limit_report=100000)
    qdir = Path(settings.DATA_DIR) / "quarantine" / timezone.now().strftime("%Y%m%d-%H%M%S")
    for p in report["problems"]:
        if p["type"] == "missing_derivative":
            actions.append(f"reprocess version {p['version']}")
            if not dry_run:
                jobs.enqueue("process_version", {"version_id": p["version"], "auto_ocr": False}, idempotency_key=f"repair:{p['version']}:{qdir.name}")
        elif p["type"] == "orphan_original":
            actions.append(f"quarantine {p['path']}")
            if not dry_run:
                dest = qdir / p["path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(Path(settings.ORIGINALS_DIR) / p["path"]), dest)
        elif p["type"] == "orphan_derivative":
            actions.append(f"remove regenerable derivative folder {p['path']}")
            if not dry_run:
                shutil.rmtree(Path(settings.DERIVATIVES_DIR) / p["path"], ignore_errors=True)
        elif p["type"] in ("missing_original", "checksum_mismatch", "size_mismatch"):
            actions.append(f"MANUAL: restore {p.get('path') or p['version']} from a verified backup (cannot be reconstructed)")
    return actions
