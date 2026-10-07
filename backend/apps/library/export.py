"""Streaming ZIP exports of the caller's accessible documents (or one folder subtree).

No temporary copy of the library is built on the server: files are streamed into the ZIP as the
response is sent. Large libraries are split into parts of `part_bytes`. Each part includes a
manifest (paths, sizes, SHA-256) so integrity can be verified after download.
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone as dt_tz

from django.http import Http404, StreamingHttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated
from apps.core import audit

from . import permissions as P
from . import storage
from .models import Document, Folder
from .services import _descendant_ids, folder_path

DEFAULT_PART = 4 * 1024 ** 3


class _Sink:
    def __init__(self):
        self.chunks: list[bytes] = []

    def write(self, b):
        self.chunks.append(bytes(b))
        return len(b)

    def flush(self):
        pass

    def drain(self) -> bytes:
        data = b"".join(self.chunks)
        self.chunks = []
        return data


def _entries(ctx: P.AccessContext, folder_id=None, all_versions: bool = False):
    qs = ctx.documents(P.DOWNLOAD).select_related("folder", "owner", "current_version")
    if folder_id:
        qs = qs.filter(folder_id__in=_descendant_ids(Folder.objects.get(pk=folder_id)))
    paths_cache: dict = {}
    entries, used = [], set()
    for doc in qs.order_by("folder_id", "created_at", "id"):
        if doc.folder_id not in paths_cache:
            chain = [f for f in folder_path(doc.folder) if f.parent_id is not None]  # drop "Family library"
            paths_cache[doc.folder_id] = "/".join(storage.safe_component(f.name, 120) for f in chain)
        versions = list(doc.versions.all()) if all_versions else ([doc.current_version] if doc.current_version else [])
        for v in versions:
            name = storage.safe_component(v.original_name, 150)
            if all_versions and len(versions) > 1:
                stem, dot, ext = name.rpartition(".")
                name = f"{stem or name} (v{v.number}){'.' + ext if dot else ''}"
            arc = f"{paths_cache[doc.folder_id]}/{name}".strip("/")
            base, n = arc, 2
            while arc.lower() in used:
                stem, dot, ext = base.rpartition(".")
                arc = f"{stem} ({n}).{ext}" if dot else f"{base} ({n})"
                n += 1
            used.add(arc.lower())
            entries.append({"arc": arc, "version": v, "doc": doc})
    return entries


def _split(entries, part_bytes: int):
    parts, cur, size = [], [], 0
    for e in entries:
        if cur and size + e["version"].size > part_bytes:
            parts.append(cur)
            cur, size = [], 0
        cur.append(e)
        size += e["version"].size
    if cur or not parts:
        parts.append(cur)
    return parts


def _zip_stream(entries, part_no: int, part_total: int):
    sink = _Sink()
    manifest = {"generated_at": timezone.now().isoformat(), "part": part_no, "parts": part_total, "files": []}
    with zipfile.ZipFile(sink, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for e in entries:
            v = e["version"]
            if v.av_blocked:
                manifest["files"].append({"path": e["arc"], "quarantined": True, "document_id": str(e["doc"].id)})
                continue
            path = storage.resolve_original(v.storage_path)
            if not path.exists():
                manifest["files"].append({"path": e["arc"], "missing": True, "document_id": str(e["doc"].id)})
                continue
            zi = zipfile.ZipInfo(e["arc"], date_time=v.created_at.astimezone(dt_tz.utc).timetuple()[:6])
            zi.compress_type = zipfile.ZIP_STORED
            with zf.open(zi, mode="w", force_zip64=v.size > 2 ** 31) as out:
                for chunk in storage.iter_file(path, chunk=512 * 1024):
                    out.write(chunk)
                    data = sink.drain()
                    if data:
                        yield data
            manifest["files"].append({"path": e["arc"], "size": v.size, "sha256": v.sha256, "document_id": str(e["doc"].id),
                                      "version": v.number, "title": e["doc"].title})
            data = sink.drain()
            if data:
                yield data
        zf.writestr("MANIFEST.json", json.dumps(manifest, indent=1, ensure_ascii=False))
        zf.writestr("SHA256SUMS.txt", "".join(f"{f['sha256']}  {f['path']}\n" for f in manifest["files"] if f.get("sha256")))
    data = sink.drain()
    if data:
        yield data


def _params(request):
    try:
        part_bytes = max(64 * 1024 ** 2, int(request.query_params.get("part_mb", DEFAULT_PART // 1024 ** 2)) * 1024 ** 2)
    except ValueError:
        part_bytes = DEFAULT_PART
    folder = request.query_params.get("folder") or None
    if folder:
        import uuid

        try:
            folder = uuid.UUID(folder)
        except ValueError:
            raise Http404
    return part_bytes, folder, request.query_params.get("all_versions") == "1"


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def export_plan(request):
    ctx = P.context_for(request)
    part_bytes, folder, all_versions = _params(request)
    if folder and not ctx.folder_caps(folder) & P.DOWNLOAD:
        raise Http404
    entries = _entries(ctx, folder, all_versions)
    parts = _split(entries, part_bytes)
    return Response({"files": len(entries), "bytes": sum(e["version"].size for e in entries),
                     "parts": [{"part": i + 1, "files": len(p), "bytes": sum(e["version"].size for e in p)} for i, p in enumerate(parts)]})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def export_download(request):
    ctx = P.context_for(request)
    part_bytes, folder, all_versions = _params(request)
    if folder and not ctx.folder_caps(folder) & P.DOWNLOAD:
        raise Http404
    entries = _entries(ctx, folder, all_versions)
    parts = _split(entries, part_bytes)
    try:
        part = int(request.query_params.get("part", 1))
    except ValueError:
        part = 1
    if part < 1 or part > len(parts):
        raise Http404
    audit.record("export.download", request=request, part=part, parts=len(parts), files=len(parts[part - 1]),
                 folder=str(folder) if folder else None)
    stamp = datetime.now().strftime("%Y%m%d")
    resp = StreamingHttpResponse(_zip_stream(parts[part - 1], part, len(parts)), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="personal-documents-{stamp}-part{part}of{len(parts)}.zip"'
    resp["Cache-Control"] = "no-store, private"
    return resp


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def offline_validate(request):
    """Client sends the version ids it holds offline; server answers which are still permitted."""
    ctx = P.context_for(request)
    ids = list(request.data.get("versions") or [])[:5000]
    from .models import DocumentVersion

    allowed, stale = [], []
    for v in DocumentVersion.objects.filter(pk__in=ids).select_related("document"):
        if ctx.can(v.document, P.DOWNLOAD):
            allowed.append(str(v.id))
            if v.document.current_version_id != v.id:
                stale.append(str(v.id))
    return Response({"allowed": allowed, "stale": stale, "revoked": [i for i in ids if i not in allowed]})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def offline_audit(request):
    action = request.data.get("action")
    if action not in ("save", "remove", "update"):
        return Response({"error": "Unknown action"}, status=400)
    ctx = P.context_for(request)
    for did in list(request.data.get("documents") or [])[:500]:
        doc = Document.objects.filter(pk=did).first()
        if doc and ctx.can(doc, P.DOWNLOAD):
            audit.record(f"offline.{action}", request=request, target=doc, subject_user=doc.owner)
    return Response({"status": "ok"})
