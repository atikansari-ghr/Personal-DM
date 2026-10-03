"""Originals storage: streaming staging, checksums, safe managed paths, atomic placement.

Originals are written once and never modified (mode 0440). Each version gets its own path that always
includes the version UUID, so name collisions can never overwrite data.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.core import config


class StorageError(Exception):
    pass


@dataclass
class Staged:
    path: Path
    size: int
    sha256: str
    original_name: str


_BAD = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


def safe_component(name: str, limit: int = 80) -> str:
    name = unicodedata.normalize("NFC", name or "")
    name = _BAD.sub("_", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if not name or name in {".", ".."}:
        name = "_"
    if len(name) > limit:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 10:
            name = stem[: limit - len(ext) - 1] + "." + ext
        else:
            name = name[:limit]
    return name


def ensure_dirs() -> None:
    for d in (settings.ORIGINALS_DIR, settings.DERIVATIVES_DIR, settings.STAGING_DIR, settings.TMP_DIR, settings.EXPORT_TMP_DIR):
        Path(d).mkdir(parents=True, exist_ok=True)


def disk_free_bytes(path: Path | None = None) -> int:
    path = Path(path or settings.DATA_DIR)
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free


MIN_FREE_BYTES = 512 * 1024 * 1024


def check_disk_space(incoming: int = 0) -> None:
    free = disk_free_bytes()
    if free - incoming < MIN_FREE_BYTES:
        raise StorageError("The server is low on disk space. Ask the administrator to free space before uploading.")


def stage_stream(chunks, original_name: str, max_bytes: int | None = None) -> Staged:
    """Write an iterable of byte chunks to staging, computing size and SHA-256."""
    ensure_dirs()
    if max_bytes is None:
        max_bytes = int(config.get("documents.max_upload_mb")) * 1024 * 1024
    target = Path(settings.STAGING_DIR) / f"{uuid.uuid4()}.part"
    h = hashlib.sha256()
    size = 0
    try:
        with open(target, "xb") as fh:
            for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise StorageError(f"File exceeds the maximum upload size of {max_bytes // (1024 * 1024)} MB.")
                h.update(chunk)
                fh.write(chunk)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return Staged(target, size, h.hexdigest(), original_name)


def stage_uploaded_file(uploaded) -> Staged:
    check_disk_space(getattr(uploaded, "size", 0) or 0)
    return stage_stream(uploaded.chunks(), uploaded.name)


def stage_local_file(src: Path, original_name: str | None = None) -> Staged:
    """Copy a server-side file into staging (read-only access to the source)."""
    check_disk_space(src.stat().st_size)

    def gen():
        with open(src, "rb") as fh:
            while True:
                b = fh.read(1024 * 1024)
                if not b:
                    return
                yield b

    return stage_stream(gen(), original_name or src.name, max_bytes=1 << 62)


def managed_relpath(*, owner_label: str, type_label: str, title: str, original_name: str, version_id, document_id) -> str:
    template = config.get("documents.filename_template")
    now = timezone.now()
    ext = Path(original_name).suffix.lower()[:12]
    ext = re.sub(r"[^a-z0-9.]", "", ext)
    values = {
        "owner": safe_component(owner_label or "shared", 60),
        "type": safe_component(type_label or "document", 60),
        "title": safe_component(title or "document", 80),
        "year": f"{now.year:04d}",
        "month": f"{now.month:02d}",
        "version_id": str(version_id),
        "document_id": str(document_id),
        "original_name": safe_component(Path(original_name).stem, 80),
    }
    rel = template
    for k, v in values.items():
        rel = rel.replace("{" + k + "}", v)
    parts = [safe_component(p, 120) for p in rel.split("/") if p.strip()]
    rel = "/".join(parts) + ext
    resolve_original(rel)  # validates containment
    return rel


def resolve_original(rel: str) -> Path:
    base = Path(settings.ORIGINALS_DIR).resolve()
    p = (base / rel).resolve()
    if base != p and base not in p.parents:
        raise StorageError("Path escapes the storage folder.")
    return p


def resolve_derivative(rel: str) -> Path:
    base = Path(settings.DERIVATIVES_DIR).resolve()
    p = (base / rel).resolve()
    if base not in p.parents:
        raise StorageError("Path escapes the derivatives folder.")
    return p


def place_original(staged: Staged, rel: str) -> Path:
    final = resolve_original(rel)
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise StorageError("Refusing to overwrite an existing original.")
    os.replace(staged.path, final)  # same filesystem: atomic
    os.chmod(final, 0o440)
    try:
        dfd = os.open(final.parent, os.O_RDONLY)
        os.fsync(dfd)
        os.close(dfd)
    except OSError:  # pragma: no cover - some filesystems do not support dir fsync
        pass
    return final


def remove_file(path: Path) -> None:
    try:
        os.chmod(path, 0o640)
    except OSError:
        pass
    path.unlink(missing_ok=True)


def derivative_dir(version_id) -> Path:
    d = Path(settings.DERIVATIVES_DIR) / str(version_id)[:2] / str(version_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def derivative_rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(Path(settings.DERIVATIVES_DIR).resolve()))


def iter_file(path: Path, start: int = 0, length: int | None = None, chunk: int = 256 * 1024):
    with open(path, "rb") as fh:
        fh.seek(start)
        remaining = length
        while True:
            n = chunk if remaining is None else min(chunk, remaining)
            if n <= 0:
                return
            b = fh.read(n)
            if not b:
                return
            if remaining is not None:
                remaining -= len(b)
            yield b
