"""Standards-based IMAP polling. Messages are read with BODY.PEEK (never marked read, moved or deleted)."""
from __future__ import annotations

import email
import imaplib
import logging
import re
import ssl
from email.header import decode_header, make_header
from email.utils import parseaddr

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import crypto, jobs
from apps.library import permissions as P
from apps.library import services as S
from apps.library import storage

from .models import EmailAccount, EmailRule, ImportedAttachment

log = logging.getLogger("personaldocs.mailimport")


class ImapError(Exception):
    pass


def connect(acc: EmailAccount, password: str | None = None) -> imaplib.IMAP4:
    password = password if password is not None else crypto.decrypt(acc.password_enc)
    ctx = ssl.create_default_context()
    try:
        if acc.security == "ssl":
            conn = imaplib.IMAP4_SSL(acc.host, acc.port, ssl_context=ctx, timeout=30)
        else:
            conn = imaplib.IMAP4(acc.host, acc.port, timeout=30)
            conn.starttls(ssl_context=ctx)
        conn.login(acc.username, password)
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
        raise ImapError(f"Could not sign in to {acc.host}: {exc.__class__.__name__}") from exc
    return conn


def list_mailboxes(conn) -> list[str]:
    typ, data = conn.list()
    out = []
    for line in data or []:
        m = re.search(rb'"([^"]+)"\s*$|\s(\S+)$', line or b"")
        if m:
            out.append((m.group(1) or m.group(2)).decode(errors="replace").strip('"'))
    return out


def _decode(value) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:  # noqa: BLE001
        return value or ""


def rule_matches(rule: EmailRule, sender: str, subject: str) -> bool:
    if rule.sender_contains and rule.sender_contains.lower() not in sender.lower():
        return False
    if rule.subject_contains and rule.subject_contains.lower() not in subject.lower():
        return False
    return True


def poll_account(acc: EmailAccount, conn=None) -> dict:
    """Import matching attachments. Idempotent per (account, UIDVALIDITY, UID, part)."""
    if not acc.enabled or acc.disabled_by_admin or not acc.user.is_active:
        return {"skipped": True}
    own = conn is None
    conn = conn or connect(acc)
    imported = failed = 0
    try:
        typ, _ = conn.select(f'"{acc.mailbox}"', readonly=True)
        if typ != "OK":
            raise ImapError(f"Mailbox {acc.mailbox} not found")
        uv = (conn.untagged_responses.get("UIDVALIDITY") or [b"0"])[0]
        uidvalidity = uv.decode() if isinstance(uv, bytes) else str(uv)
        if uidvalidity != acc.uidvalidity:
            acc.uidvalidity, acc.last_uid = uidvalidity, 0  # server reset UIDs: identities are keyed by uidvalidity
        typ, data = conn.uid("search", None, f"UID {acc.last_uid + 1}:*")
        uids = [int(u) for u in (data[0] or b"").split() if int(u) > acc.last_uid]
        rules = [r for r in acc.rules.filter(enabled=True).select_related("destination")]
        ctx = P.AccessContext.build(acc.user)
        for uid in sorted(uids)[:500]:
            typ, msg_data = conn.uid("fetch", str(uid), "(BODY.PEEK[])")
            raw = next((p[1] for p in msg_data if isinstance(p, tuple)), None)
            if raw is None:
                continue
            msg = email.message_from_bytes(raw)
            sender = parseaddr(_decode(msg.get("From")))[1]
            subject = _decode(msg.get("Subject"))
            rule = next((r for r in rules if rule_matches(r, sender, subject)), None)
            if rule is not None:
                for idx, part in enumerate(msg.walk()):
                    filename = part.get_filename()
                    if not filename or part.get_content_maintype() == "multipart":
                        continue
                    filename = _decode(filename)
                    if ImportedAttachment.objects.filter(account=acc, uidvalidity=uidvalidity, uid=uid, part_index=idx, status="done").exists():
                        continue
                    ok, err = _import_part(acc, rule, ctx, part, filename, uidvalidity, uid, idx)
                    imported += ok
                    failed += 0 if ok else (1 if err else 0)
            if not ImportedAttachment.objects.filter(account=acc, uidvalidity=uidvalidity, uid=uid, status="failed").exists():
                acc.last_uid = max(acc.last_uid, uid)
        acc.last_error = ""
    except ImapError as exc:
        acc.last_error = str(exc)[:500]
        raise
    finally:
        acc.last_poll_at = timezone.now()
        acc.save(update_fields=["uidvalidity", "last_uid", "last_error", "last_poll_at"])
        if own:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
    return {"imported": imported, "failed": failed}


def _import_part(acc, rule, ctx, part, filename, uidvalidity, uid, idx) -> tuple[int, str]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = {e.strip().lower().lstrip(".") for e in rule.extensions.split(",") if e.strip()}
    payload = part.get_payload(decode=True) or b""
    if allowed and ext not in allowed:
        return 0, ""
    if len(payload) > rule.max_mb * 1024 * 1024:
        _record(acc, uidvalidity, uid, idx, filename, "", "skipped", "Attachment larger than rule limit", rule)
        return 0, ""
    # Permission re-checked on every poll.
    if not ctx.folder_caps(rule.destination_id) & P.UPLOAD or rule.destination.archived_at:
        _record(acc, uidvalidity, uid, idx, filename, "", "failed", "No upload permission for destination folder", rule)
        return 0, "perm"
    try:
        staged = storage.stage_stream([payload], filename)
        with transaction.atomic():
            owner = rule.destination.owner or acc.user
            doc = S.create_document(actor=acc.user, folder=rule.destination, owner=owner, staged=staged,
                                    source_path=f"email:{acc.label}/{acc.mailbox}#{uid}")
            ImportedAttachment.objects.update_or_create(
                account=acc, uidvalidity=uidvalidity, uid=uid, part_index=idx,
                defaults={"filename": filename[:255], "sha256": staged.sha256, "status": "done", "error": "", "document": doc, "rule": rule})
        return 1, ""
    except (storage.StorageError, S.DomainError, IntegrityError) as exc:
        _record(acc, uidvalidity, uid, idx, filename, "", "failed", str(exc)[:300], rule)
        return 0, "error"


def _record(acc, uidvalidity, uid, idx, filename, sha, status, error, rule):
    ImportedAttachment.objects.update_or_create(account=acc, uidvalidity=uidvalidity, uid=uid, part_index=idx,
                                                defaults={"filename": filename[:255], "sha256": sha, "status": status,
                                                          "error": error, "rule": rule})


@jobs.handler("email_poll")
def email_poll_job(job):
    acc = EmailAccount.objects.select_related("user").filter(pk=job.payload["account_id"]).first()
    if acc is None:
        return {"skipped": True}
    try:
        return poll_account(acc)
    except ImapError as exc:
        raise jobs.PermanentFailure(str(exc))


def due_accounts():
    now = timezone.now()
    for acc in EmailAccount.objects.filter(enabled=True, disabled_by_admin=False, user__is_active=True):
        if acc.last_poll_at is None or (now - acc.last_poll_at).total_seconds() >= acc.poll_minutes * 60:
            yield acc
