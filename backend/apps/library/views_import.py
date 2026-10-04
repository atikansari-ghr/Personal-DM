import csv
import io

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated
from apps.core import audit, jobs

from . import imports as I
from . import services as S
from . import storage
from .models import ImportItem, ImportSession


def _err(msg, status=400):
    return Response({"error": msg}, status=status)


def _session(request, pk) -> ImportSession:
    s = get_object_or_404(ImportSession, pk=pk)
    if s.created_by_id != request.user.pk and not request.user.is_main_admin:
        raise PermissionDenied()
    return s


def _json(s: ImportSession) -> dict:
    counts = {k: ImportItem.objects.filter(session=s, status=k).count() for k in ("pending", "done", "failed", "skipped")}
    return {"id": str(s.id), "source_type": s.source_type, "source_root": s.source_root, "status": s.status,
            "scan": {k: v for k, v in s.scan.items() if k != "tree"}, "tree": s.scan.get("tree", [])[:2000],
            "mapping": s.mapping, "counts": counts, "created_at": s.created_at, "finished_at": s.finished_at,
            "preview": I.preview(s) if s.status in ("mapping", "importing", "done", "done_with_errors") and s.mapping else [],
            "capacity_warning": I.capacity_warning(s) if s.scan else None}


@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def import_sessions(request):
    if request.method == "GET":
        qs = ImportSession.objects.all() if request.user.is_main_admin else ImportSession.objects.filter(created_by=request.user)
        return Response({"imports": [{"id": str(s.id), "source_type": s.source_type, "status": s.status, "files": s.scan.get("files", 0),
                                      "created_at": s.created_at} for s in qs.order_by("-created_at")[:50]]})
    source_type = request.data.get("source_type", "browser")
    if source_type == "server":
        if not request.user.is_main_admin:
            raise PermissionDenied("Only the main administrator can import from server folders.")
        try:
            I.validate_server_root(request.data.get("root", ""))
        except S.DomainError as exc:
            return _err(str(exc))
        s = ImportSession.objects.create(created_by=request.user, source_type="server", source_root=request.data["root"])
        try:
            I.scan_server(s)
        except S.DomainError as exc:
            s.status = "failed"
            s.save()
            return _err(str(exc))
    else:
        s = ImportSession.objects.create(created_by=request.user, source_type="browser")
        try:
            I.scan_browser(s, list(request.data.get("entries") or []))
        except (S.DomainError, ValueError) as exc:
            s.delete()
            return _err(str(exc))
    audit.record("import.scan", request=request, target=s, files=s.scan.get("files"))
    return Response(_json(s), status=201)


@api_view(["GET", "PUT"])
@permission_classes([IsActiveAuthenticated])
def import_detail(request, pk):
    s = _session(request, pk)
    if request.method == "PUT":
        if s.status != "mapping":
            return _err("The mapping can only be changed before the import starts.")
        try:
            I.validate_mapping(s, request.data.get("mapping") or {}, request.user)
        except S.DomainError as exc:
            return _err(str(exc))
        audit.record("import.mapping", request=request, target=s)
    return Response(_json(s))


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def import_start(request, pk):
    s = _session(request, pk)
    if s.status not in ("mapping", "importing"):
        return _err("This import cannot be started.")
    if any(m.get("status") != "confirmed" for m in s.mapping.values()) or set(s.mapping) != set(s.scan.get("tops", {})):
        return _err("Confirm every source folder mapping first.")
    for item in ImportItem.objects.filter(session=s, status="pending"):
        if not I.item_allowed(s, item):
            item.status = "skipped"
            item.save(update_fields=["status"])
    s.status = "importing"
    s.save(update_fields=["status"])
    audit.record("import.start", request=request, target=s)
    if s.source_type == "server":
        jobs.enqueue("import_server", {"session_id": str(s.id)}, idempotency_key=f"import:{s.id}:{s.items.filter(status='pending').count()}:{s.items.filter(status='failed').count()}")
    I.finish_if_done(s)
    return Response(_json(s))


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def import_retry(request, pk):
    s = _session(request, pk)
    ImportItem.objects.filter(session=s, status="failed").update(status="pending", error="")
    s.status = "importing"
    s.save(update_fields=["status"])
    if s.source_type == "server":
        jobs.enqueue("import_server", {"session_id": str(s.id)})
    return Response(_json(s))


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def import_upload_item(request, pk):
    """Browser imports: the client uploads each pending item; retries of the same item are idempotent."""
    s = _session(request, pk)
    try:
        rel = I.normalize_rel(request.data.get("path", ""))
    except ValueError:
        return _err("Invalid path.")
    item = ImportItem.objects.filter(session=s, relative_path=rel).first()
    if item is None:
        return _err("This file was not part of the scanned selection.")
    if item.status == "done":
        return Response({"path": rel, "status": "done", "document": str(item.document_id), "duplicate_retry": True})
    if s.status != "importing":
        return _err("Start the import first.")
    if not I.item_allowed(s, item):
        return Response({"path": rel, "status": "skipped"})
    f = request.FILES.get("file")
    if not f:
        return _err("Missing file.")
    try:
        staged = storage.stage_uploaded_file(f)
        item = I.import_item(s, item, staged)
    except (storage.StorageError, S.DomainError) as exc:
        ImportItem.objects.filter(pk=item.pk).update(status="failed", error=str(exc)[:500], attempts=item.attempts + 1)
        I.finish_if_done(s)
        return Response({"path": rel, "status": "failed", "error": str(exc)}, status=200)
    I.finish_if_done(s)
    return Response({"path": rel, "status": item.status, "document": str(item.document_id) if item.document_id else None})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def import_report(request, pk):
    s = _session(request, pk)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["relative_path", "size", "status", "excluded_reason", "error", "document_id"])
    for it in ImportItem.objects.filter(session=s).order_by("relative_path").iterator():
        w.writerow([it.relative_path, it.size, it.status, it.excluded_reason, it.error, it.document_id or ""])
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="import-report-{s.id}.csv"'
    return resp


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def import_pending(request, pk):
    s = _session(request, pk)
    paths = list(ImportItem.objects.filter(session=s, status__in=["pending"]).values_list("relative_path", flat=True)[:5000])
    return Response({"pending": paths})
