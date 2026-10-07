"""Antivirus administration API (Administrators; releasing a file is reserved to the main administrator)."""
from __future__ import annotations

from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsAdministrator, IsMainAdmin
from apps.core import audit, config, jobs
from apps.library.models import Document, DocumentVersion, Folder
from apps.ops import host, schedule

from . import antivirus as av
from .models import AvScanRun, HealthState


def _err(msg, status=400, **extra):
    return Response({"error": msg, **extra}, status=status)


def _file_json(v: DocumentVersion) -> dict:
    return {"version": str(v.id), "document": str(v.document_id), "title": v.document.title, "name": v.original_name,
            "owner": v.document.owner.display_name if v.document.owner_id else "", "status": v.av_status,
            "label": av.STATUS_LABELS.get(v.av_status, v.av_status), "signature": v.av_signature, "detail": v.av_detail,
            "engine": v.av_engine, "scanned_at": v.av_scanned_at, "size": v.size,
            "released_by": v.av_released_by.display_name if v.av_released_by_id else None,
            "released_at": v.av_released_at, "release_reason": v.av_release_reason}


def _run_json(r: AvScanRun | None) -> dict | None:
    if r is None:
        return None
    return {"id": r.id, "kind": r.kind, "scope": r.scope, "status": r.status, "total": r.total, "done": r.done,
            "counts": r.counts, "started_at": r.started_at, "finished_at": r.finished_at,
            "started_by": r.started_by.display_name if r.started_by_id else "Schedule"}


@api_view(["GET"])
@permission_classes([IsAdministrator])
def overview(request):
    h = av.health(refresh=request.query_params.get("refresh") == "1")
    counts = dict(DocumentVersion.objects.values_list("av_status").annotate(n=Count("id")))
    rel = DocumentVersion.objects.select_related("document", "document__owner", "av_released_by")
    quarantine = [_file_json(v) for v in rel.filter(av_status__in=("quarantined", "threat")).order_by("-av_scanned_at")[:200]]
    problems = [_file_json(v) for v in rel.filter(av_status__in=("not_scanned", "size_limit", "failed")).order_by("-created_at")[:100]]
    released = [_file_json(v) for v in rel.filter(av_status="released").order_by("-av_released_at")[:50]]
    runs = AvScanRun.objects.select_related("started_by")[:10]
    nxt = schedule.next_occurrence(timezone.localtime(), kind="antivirus")
    fresh = host.status("freshclam")
    return Response({
        "health": h, "counts": counts, "quarantine": quarantine, "problems": problems, "released": released,
        "runs": [_run_json(r) for r in runs], "active_run": _run_json(AvScanRun.objects.filter(status__in=("running", "paused")).first()),
        "schedule": {"frequency": config.get("antivirus.scan_frequency"), "next": nxt},
        "signatures": {"version": h.get("signatures"), "date": h.get("signatures_date"), "age_days": h.get("signature_age_days"),
                       "stale": h.get("stale"), "updater": "clamav-freshclam (automatic, hourly checks)",
                       "last_manual_update": fresh, "update_available": host.installed()},
        "max_scan_mb": config.get("antivirus.max_scan_mb"), "can_release": bool(request.user.is_main_admin),
        "archive_note": "Archives (ZIP, RAR, …) are scanned as a single file by ClamAV; a clean result does not prove that every file inside was inspected.",
    })


@api_view(["POST"])
@permission_classes([IsAdministrator])
def scan(request):
    """Scan one document (all its files), one folder tree, or the entire existing library."""
    if not config.get("antivirus.enabled"):
        return _err("Antivirus scanning is turned off in Settings → Security → Antivirus.")
    d = request.data
    if d.get("document"):
        doc = get_object_or_404(Document, pk=d["document"])
        n = 0
        for v in doc.versions.exclude(av_status__in=("quarantined", "threat")):
            DocumentVersion.objects.filter(pk=v.pk).update(av_status="pending")
            jobs.enqueue("av_scan", {"version_id": str(v.id)}, max_attempts=1,
                         idempotency_key=f"av:{v.id}:manual:{timezone.now().timestamp()}")
            n += 1
        audit.record("antivirus.manual_scan", request=request, target=doc, files=n)
        return Response({"queued": n}, status=202)
    folder = get_object_or_404(Folder, pk=d["folder"]) if d.get("folder") else None
    try:
        run = av.start_library_scan(actor=request.user, folder=folder)
    except av.ScanError as exc:
        return _err(str(exc), 409)
    return Response(_run_json(run), status=202)


@api_view(["POST"])
@permission_classes([IsAdministrator])
def run_action(request, pk):
    run = get_object_or_404(AvScanRun, pk=pk)
    try:
        av.set_run_state(run, str(request.data.get("action", "")), actor=request.user)
    except av.ScanError as exc:
        return _err(str(exc), 409)
    return Response(_run_json(run))


@api_view(["POST"])
@permission_classes([IsAdministrator])
def update_signatures(request):
    try:
        req = host.request("freshclam", actor=request.user, request_obj=request)
    except host.HostError as exc:
        return _err(str(exc), 409)
    return Response({"requested": req["id"]}, status=202)


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def release(request, pk):
    """Release a quarantined file: prominent warning in the UI, explicit confirmation and a mandatory reason."""
    v = get_object_or_404(DocumentVersion.objects.select_related("document"), pk=pk)
    reason = str(request.data.get("reason") or "").strip()
    if request.data.get("confirm") is not True:
        return _err("Confirm that you understand the file was detected as malware.", code="confirm_required")
    if len(reason) < 10:
        return _err("Give a reason of at least 10 characters (it is kept in the audit log).", code="reason_required")
    try:
        av.release(v, actor=request.user, reason=reason, request=request)
    except av.ScanError as exc:
        return _err(str(exc), 409)
    v.refresh_from_db()
    return Response(_file_json(v))


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def delete_quarantined(request, pk):
    """Permanently delete a quarantined file (typed confirmation, audited). The rest of the document is kept."""
    from apps.library import services

    v = get_object_or_404(DocumentVersion.objects.select_related("document"), pk=pk)
    if v.av_status not in ("quarantined", "threat"):
        return _err("Only quarantined files can be deleted here.", 409)
    if request.data.get("confirm_text") != "DELETE":
        return _err("Type DELETE to confirm.", code="confirm_required")
    doc = v.document
    if doc.versions.count() == 1:
        if doc.archived_at is None:
            Document.objects.filter(pk=doc.pk).update(archived_at=timezone.now())
            doc.refresh_from_db()
        services.purge_document(actor=request.user, doc=doc, request=request)
    else:
        av.delete_quarantined_files([v])
        if doc.current_version_id == v.id:
            other = doc.versions.exclude(pk=v.pk).order_by("-number").first()
            Document.objects.filter(pk=doc.pk).update(current_version=other)
        v.delete()
    audit.record("antivirus.quarantine_delete", request=request, target_type="version", target_id=str(pk),
                 signature=v.av_signature)
    return Response(status=204)


@api_view(["GET"])
@permission_classes([IsAdministrator])
def freshclam_status(request):
    st = host.status("freshclam")
    if st.get("state") in ("done", "failed") and st.get("finished_at") != HealthState.get("freshclam").get("finished_at"):
        HealthState.put("freshclam", ok=st.get("ok", st.get("state") == "done"), finished_at=st.get("finished_at"),
                        error=st.get("error", ""))
        if st.get("state") == "failed":
            av._alert("antivirus.definitions", f"av_update_fail:{st.get('id')}", "Antivirus signature update failed",
                      [f"Error: {str(st.get('error') or 'unknown')[:200]}"])
    return Response({**st, "log": host.log_text(st.get("log", ""), 20_000) if st.get("log") else ""})
