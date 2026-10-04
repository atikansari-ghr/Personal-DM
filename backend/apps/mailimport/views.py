from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin
from apps.core import audit, crypto, jobs
from apps.library import permissions as P
from apps.library.models import Folder

from . import imap
from .models import EmailAccount, EmailRule, ImportedAttachment


def _acc_json(a: EmailAccount, include_rules=True):
    data = {"id": a.id, "label": a.label, "host": a.host, "port": a.port, "security": a.security, "username": a.username,
            "mailbox": a.mailbox, "poll_minutes": a.poll_minutes, "enabled": a.enabled, "disabled_by_admin": a.disabled_by_admin,
            "last_poll_at": a.last_poll_at, "last_error": a.last_error, "password_set": bool(a.password_enc)}
    if include_rules:
        data["rules"] = [{"id": r.id, "name": r.name, "sender_contains": r.sender_contains, "subject_contains": r.subject_contains,
                          "extensions": r.extensions, "max_mb": r.max_mb, "destination": str(r.destination_id),
                          "destination_name": r.destination.name, "enabled": r.enabled} for r in a.rules.select_related("destination")]
        data["history"] = [{"filename": i.filename, "status": i.status, "error": i.error, "at": i.at,
                            "document": str(i.document_id) if i.document_id else None} for i in a.imported.order_by("-at")[:30]]
    return data


def _apply(a: EmailAccount, d: dict):
    for f, typ in (("label", str), ("host", str), ("username", str), ("mailbox", str)):
        if f in d:
            setattr(a, f, str(d[f]).strip()[:200])
    if "port" in d:
        a.port = int(d["port"])
    if "security" in d and d["security"] in ("ssl", "starttls"):
        a.security = d["security"]
    if "poll_minutes" in d:
        a.poll_minutes = max(5, min(1440, int(d["poll_minutes"])))
    if "enabled" in d:
        a.enabled = bool(d["enabled"])
    if d.get("password"):
        a.password_enc = crypto.encrypt(d["password"])


@api_view(["GET", "POST"])
@permission_classes([IsActiveAuthenticated])
def accounts(request):
    if request.method == "POST":
        a = EmailAccount(user=request.user)
        try:
            _apply(a, request.data)
        except (TypeError, ValueError):
            return Response({"error": "Check the port and polling interval."}, status=400)
        if not (a.label and a.host and a.username and a.password_enc):
            return Response({"error": "Label, server, username and password are required."}, status=400)
        a.save()
        audit.record("email_import.account_add", request=request, target=a)
        return Response(_acc_json(a), status=201)
    return Response({"accounts": [_acc_json(a) for a in EmailAccount.objects.filter(user=request.user)]})


@api_view(["PATCH", "DELETE"])
@permission_classes([IsActiveAuthenticated])
def account_detail(request, pk):
    a = get_object_or_404(EmailAccount, pk=pk, user=request.user)
    if request.method == "DELETE":
        a.delete()
        audit.record("email_import.account_delete", request=request, target_type="emailaccount", target_id=str(pk))
        return Response(status=204)
    try:
        _apply(a, request.data)
    except (TypeError, ValueError):
        return Response({"error": "Check the port and polling interval."}, status=400)
    a.save()
    return Response(_acc_json(a))


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def account_test(request, pk):
    a = get_object_or_404(EmailAccount, pk=pk, user=request.user)
    try:
        conn = imap.connect(a)
        boxes = imap.list_mailboxes(conn)
        conn.logout()
    except imap.ImapError as exc:
        return Response({"error": str(exc)}, status=400)
    return Response({"status": "ok", "mailboxes": boxes[:200]})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def account_poll(request, pk):
    a = get_object_or_404(EmailAccount, pk=pk, user=request.user)
    jobs.enqueue("email_poll", {"account_id": a.id})
    return Response({"status": "queued"})


@api_view(["POST"])
@permission_classes([IsActiveAuthenticated])
def rules(request, pk):
    a = get_object_or_404(EmailAccount, pk=pk, user=request.user)
    d = request.data
    dest = Folder.objects.filter(pk=d.get("destination"), archived_at__isnull=True).first()
    if dest is None or not P.AccessContext.build(request.user).folder_caps(dest.id) & P.UPLOAD:
        return Response({"error": "Choose a destination folder where you can upload."}, status=400)
    rid = d.get("id")
    r = get_object_or_404(EmailRule, pk=rid, account=a) if rid else EmailRule(account=a)
    r.name = (d.get("name") or "Rule").strip()[:80]
    r.sender_contains = (d.get("sender_contains") or "").strip()[:200]
    r.subject_contains = (d.get("subject_contains") or "").strip()[:200]
    r.extensions = (d.get("extensions") or "pdf,jpg,jpeg,png").strip()[:200]
    r.max_mb = max(1, min(200, int(d.get("max_mb") or 25)))
    r.destination = dest
    r.enabled = bool(d.get("enabled", True))
    r.save()
    return Response(_acc_json(a))


@api_view(["DELETE"])
@permission_classes([IsActiveAuthenticated])
def rule_delete(request, pk, rid):
    a = get_object_or_404(EmailAccount, pk=pk, user=request.user)
    EmailRule.objects.filter(pk=rid, account=a).delete()
    return Response(_acc_json(a))


@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def admin_connectors(request):
    """Administrators can disable a malfunctioning connector without seeing its credentials."""
    if request.method == "POST":
        a = get_object_or_404(EmailAccount, pk=request.data.get("id"))
        a.disabled_by_admin = bool(request.data.get("disabled"))
        a.save(update_fields=["disabled_by_admin"])
        audit.record("email_import.admin_toggle", request=request, target=a, disabled=a.disabled_by_admin)
    return Response({"accounts": [{"id": a.id, "user": a.user.display_name, "label": a.label, "host": a.host,
                                   "enabled": a.enabled, "disabled_by_admin": a.disabled_by_admin, "last_error": a.last_error,
                                   "last_poll_at": a.last_poll_at} for a in EmailAccount.objects.select_related("user")]})
