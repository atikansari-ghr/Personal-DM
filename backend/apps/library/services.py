"""Domain operations for folders, documents and versions."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.core import audit, config, jobs

from . import filetypes
from . import permissions as P
from . import storage
from .models import AccessRule, Document, DocumentField, DocumentHistory, DocumentVersion, Folder, ShareLink

log = logging.getLogger("personaldocs.library")


class DomainError(Exception):
    pass


EMOJI_RULES = [
    (("passport",), "🛂"),
    (("visa", "re-entry", "reentry", "exit re"), "🛃"),
    (("travel", "trip", "ticket", "flight", "umrah", "umra"), "✈️"),
    (("house", "home", "property", "deed", "rent", "agreement", "tax"), "🏠"),
    (("school", "college", "degree", "education", "university", "sem", "memo", "std", "kg"), "🎓"),
    (("medical", "health", "xray", "x-ray", "dicom", "vaccin", "eye", "report", "hospital"), "🩺"),
    (("bank", "finance", "loan", "kyc", "zakat", "pay", "statement", "wallet"), "🏦"),
    (("insurance", "insurence", "policy"), "🛡️"),
    (("car", "vehicle", "activa", "bike", "license", "licence", "driving", "istemara", "instemara"), "🚗"),
    (("certificate", "cerificate", "award", "appreciation", "apreciation", "itil", "mcse"), "📜"),
    (("aadhaar", "aadhar", "pan card", "voter", "iqama", "id", "identity"), "🪪"),
    (("bill", "purchase", "receipt", "reciept"), "🧾"),
    (("photo",), "🖼️"),
    (("form",), "📝"),
    (("family", "shared"), "👪"),
]


def suggest_emoji(name: str) -> str:
    low = (name or "").lower()
    for keys, emoji in EMOJI_RULES:
        for k in keys:
            if k == "id":
                if low == "id" or low.endswith(" id") or " id " in low:
                    return emoji
            elif k in low:
                return emoji
    return "📁"


def folder_path(folder: Folder) -> list[Folder]:
    chain = []
    seen = set()
    node = folder
    while node is not None and node.id not in seen:
        chain.append(node)
        seen.add(node.id)
        node = node.parent
    return list(reversed(chain))


MAX_DEPTH = 32


def create_folder(*, actor, parent: Folder | None, name: str, owner=None, kind: str = Folder.NORMAL,
                  emoji: str | None = None, source_path: str = "", group=None) -> Folder:
    name = (name or "").strip()
    if not name or len(name) > 200 or "/" in name or "\\" in name or name in {".", ".."}:
        raise DomainError("Folder names must be 1–200 characters and cannot contain slashes.")
    if parent is not None and len(folder_path(parent)) >= MAX_DEPTH:
        raise DomainError(f"Folders can be nested at most {MAX_DEPTH} levels deep.")
    if Folder.objects.filter(parent=parent, name=name, archived_at__isnull=True).exists():
        raise DomainError("A folder with this name already exists here.")
    if owner is None and parent is not None:
        owner = parent.owner
    if group is None and parent is not None:
        group = parent.group
    custom = emoji is not None and emoji != ""
    if not custom:
        emoji = suggest_emoji(name) if config.get("documents.emoji_suggestions") else "📁"
    folder = Folder.objects.create(parent=parent, name=name, owner=owner, kind=kind, emoji=emoji,
                                   emoji_is_custom=custom, source_path=source_path, created_by=actor, group=group)
    return folder


def get_or_create_folder_path(*, actor, root: Folder, parts: list[str], source_prefix: str = "") -> Folder:
    node = root
    for i, part in enumerate(parts):
        part = storage.safe_component(part, 200)
        child = Folder.objects.filter(parent=node, name=part, archived_at__isnull=True).first()
        if child is None:
            child = create_folder(actor=actor, parent=node, name=part,
                                  source_path="/".join([source_prefix] + parts[: i + 1]).strip("/"))
        node = child
    return node


# ---------------------------------------------------------------- format detection

OFFICE_EXT = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf", ".csv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".heic"}
TEXT_EXT = {".txt", ".md", ".log", ".json", ".xml"}
EXEC_EXT = {".exe", ".bat", ".cmd", ".com", ".msi", ".sh", ".ps1", ".vbs", ".js", ".jar", ".app", ".dll", ".scr"}


def detect_format(path: Path, original_name: str) -> tuple[str, str]:
    ext = Path(original_name).suffix.lower()
    with open(path, "rb") as fh:
        head = fh.read(2048)
    if head.startswith(b"%PDF"):
        return "pdf", "application/pdf"
    if len(head) >= 132 and head[128:132] == b"DICM" or ext == ".dcm" or Path(original_name).name.upper() == "DICOMDIR":
        return "dicom", "application/dicom"
    if head.startswith(b"\x89PNG"):
        return "image", "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image", "image/tiff"
    if head.startswith(b"GIF8"):
        return "image", "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", "image/webp"
    if head.startswith(b"BM") and ext == ".bmp":
        return "image", "image/bmp"
    if ext in OFFICE_EXT:
        mime = filetypes.office_mime(path, ext, head)
        # Content that does not match its Office extension is stored as-is but never handed to the converter.
        return ("office", mime) if mime != "application/octet-stream" else ("other", mime)
    archive = filetypes.archive_mime(head)
    if archive:
        return "other", archive
    if ext in EXEC_EXT or head.startswith(b"MZ") or head.startswith(b"\x7fELF") or head.startswith(b"#!"):
        return "other", "application/octet-stream"
    if ext in TEXT_EXT or (ext == "" and _looks_text(head)):
        if _looks_text(head):
            return "text", "text/plain"
    if ext in IMAGE_EXT:
        return "image", "application/octet-stream"
    return "other", "application/octet-stream"


def _looks_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


# ---------------------------------------------------------------- naming

def generated_title(doc: Document) -> str:
    owner = doc.owner.display_name if doc.owner_id else "Shared"
    if doc.doc_type_id:
        base = f"{owner} {doc.doc_type.name}"
        if doc.issue_date and doc.expiry_date:
            return f"{base} ({doc.issue_date.year}–{doc.expiry_date.year})"
        if doc.expiry_date:
            return f"{base} (expires {doc.expiry_date.year})"
        if doc.doc_type.has_expiry:
            return f"{base} (dates needed)"
        return base
    return doc.title


def refresh_title(doc: Document) -> None:
    if not doc.title_is_custom:
        new = generated_title(doc)
        if new and new != doc.title:
            doc.title = new
            doc.save(update_fields=["title", "updated_at"])


def _history(doc, actor, action, **changes):
    DocumentHistory.objects.create(document=doc, actor=actor, action=action, changes=changes)


# ---------------------------------------------------------------- documents and versions

def _commit_version(*, actor, doc: Document, staged: storage.Staged, number: int, comment: str = "") -> DocumentVersion:
    vid = uuid.uuid4()
    rel = storage.managed_relpath(
        owner_label=doc.owner.display_name if doc.owner_id else "shared",
        type_label=doc.doc_type.name if doc.doc_type_id else "document",
        title=doc.title, original_name=staged.original_name, version_id=vid, document_id=doc.id)
    fmt, mime = detect_format(staged.path, staged.original_name)
    final = storage.place_original(staged, rel)
    try:
        version = DocumentVersion.objects.create(
            id=vid, document=doc, number=number, original_name=staged.original_name[:255], storage_path=rel,
            size=staged.size, sha256=staged.sha256, mime=mime, format_class=fmt, comment=comment, created_by=actor)
    except Exception:
        storage.remove_file(final)
        raise
    return version


def create_document(*, actor, folder: Folder, owner, staged: storage.Staged, title: str = "", doc_type=None,
                    renews: Document | None = None, source_path: str = "", inherit: bool = True) -> Document:
    if owner is None:
        raise DomainError("Every document needs an owner account.")
    final_path = None
    try:
        with transaction.atomic():
            doc = Document.objects.create(
                folder=folder, owner=owner, group=folder.group, title=(title or Path(staged.original_name).stem)[:255],
                title_is_custom=bool(title), doc_type=doc_type, renews=renews, source_path=source_path,
                created_by=actor, inherit_permissions=inherit, state=Document.QUEUED)
            version = _commit_version(actor=actor, doc=doc, staged=staged, number=1)
            final_path = storage.resolve_original(version.storage_path)
            doc.current_version = version
            doc.save(update_fields=["current_version"])
            if doc_type is not None and not title:
                refresh_title(doc)
            _history(doc, actor, "created", version=1, renews=str(renews.id) if renews else None)
            transaction.on_commit(lambda: jobs.enqueue("process_version", {"version_id": str(version.id)},
                                                       idempotency_key=f"process:{version.id}"))
    except Exception:
        # The transaction rolled back, so a placed original has no database row: remove it.
        if final_path is not None and final_path.exists():
            storage.remove_file(final_path)
        Path(staged.path).unlink(missing_ok=True)
        raise
    return doc


def add_version(*, actor, doc: Document, staged: storage.Staged, comment: str = "") -> DocumentVersion:
    """A better scan / edited copy of the same document. Renewals must use create_document(renews=...)."""
    final_path = None
    try:
        with transaction.atomic():
            locked = Document.objects.select_for_update().get(pk=doc.pk)
            number = (locked.versions.order_by("-number").values_list("number", flat=True).first() or 0) + 1
            version = _commit_version(actor=actor, doc=locked, staged=staged, number=number, comment=comment)
            final_path = storage.resolve_original(version.storage_path)
            locked.current_version = version
            locked.state = Document.QUEUED
            locked.save(update_fields=["current_version", "state", "updated_at"])
            _history(locked, actor, "version_added", version=number)
            transaction.on_commit(lambda: jobs.enqueue("process_version", {"version_id": str(version.id)},
                                                       idempotency_key=f"process:{version.id}"))
    except Exception:
        if final_path is not None and final_path.exists():
            storage.remove_file(final_path)
        Path(staged.path).unlink(missing_ok=True)
        raise
    return version


def set_current_version(*, actor, doc: Document, version: DocumentVersion) -> None:
    if version.document_id != doc.id:
        raise DomainError("Version does not belong to this document.")
    doc.current_version = version
    doc.content_text = version.text
    doc.save(update_fields=["current_version", "content_text", "updated_at"])
    from .search import update_search_vector

    update_search_vector(doc)
    _history(doc, actor, "current_version", version=version.number)


# ---------------------------------------------------------------- fields

DATE_FIELDS = {"issue_date", "expiry_date", "date_of_birth"}


def mask(key: str, value: str) -> str:
    if key in DocumentField.SENSITIVE and value:
        return "•" * max(0, len(value) - 4) + value[-4:]
    return value


def set_field(*, actor, doc: Document, key: str, value: str, confirm: bool = True) -> DocumentField:
    from .extraction import parse_date

    key = key.strip()[:80]
    value = (value or "").strip()
    if key in DATE_FIELDS and value:
        parsed = parse_date(value)
        if parsed is None:
            raise DomainError("Enter dates as YYYY-MM-DD.")
        value = parsed.isoformat()
    field, _ = DocumentField.objects.get_or_create(document=doc, key=key)
    old = field.value
    field.value = value
    field.source = "manual" if field.status == DocumentField.CONFIRMED or field.source == "manual" or not confirm else field.source
    if confirm:
        field.status = DocumentField.CONFIRMED
        field.confirmed_by = actor
        field.confirmed_at = timezone.now()
        field.flags = []
    field.save()
    _history(doc, actor, "field_confirmed" if confirm else "field_set", key=key,
             old=mask(key, old), new=mask(key, value))
    apply_confirmed_fields(doc)
    return field


def confirm_all(*, actor, doc: Document) -> None:
    for f in doc.fields.filter(status=DocumentField.PROPOSED):
        f.status = DocumentField.CONFIRMED
        f.confirmed_by = actor
        f.confirmed_at = timezone.now()
        f.flags = []
        f.save()
        _history(doc, actor, "field_confirmed", key=f.key, new=mask(f.key, f.value))
    apply_confirmed_fields(doc)


def apply_confirmed_fields(doc: Document) -> None:
    """Only confirmed values drive dates, generated names and reminders."""
    from datetime import date

    vals = {f.key: f.value for f in doc.fields.filter(status=DocumentField.CONFIRMED)}

    def d(k):
        try:
            return date.fromisoformat(vals[k]) if vals.get(k) else None
        except ValueError:
            return None

    old_expiry = doc.expiry_date
    doc.issue_date = d("issue_date")
    doc.expiry_date = d("expiry_date")
    pending = doc.fields.filter(status=DocumentField.PROPOSED).exists()
    flags = []
    if doc.issue_date and doc.expiry_date and doc.issue_date >= doc.expiry_date:
        flags.append("Issue date is not before expiry date.")
    doc.review_flags = flags
    if doc.state in (Document.NEEDS_REVIEW, Document.READY):
        doc.state = Document.NEEDS_REVIEW if (pending or flags) else Document.READY
    doc.save(update_fields=["issue_date", "expiry_date", "review_flags", "state", "updated_at"])
    refresh_title(doc)
    if old_expiry != doc.expiry_date:
        from apps.notify.expiry import on_expiry_changed

        on_expiry_changed(doc, old_expiry)


# ---------------------------------------------------------------- archive / restore / purge

def archive_document(*, actor, doc: Document, request=None) -> None:
    with transaction.atomic():
        doc.archived_at = timezone.now()
        doc.archived_by = actor
        doc.save(update_fields=["archived_at", "archived_by", "updated_at"])
        ShareLink.objects.filter(document=doc, revoked_at__isnull=True).update(revoked_at=timezone.now())
        _history(doc, actor, "archived")
    audit.record("document.archive", request=request, actor=actor, target=doc, subject_user=doc.owner)


def restore_document(*, actor, doc: Document, request=None) -> None:
    if Folder.objects.filter(pk=doc.folder_id, archived_at__isnull=False).exists():
        raise DomainError("Restore the containing folder first.")
    doc.archived_at = None
    doc.archived_by = None
    doc.save(update_fields=["archived_at", "archived_by", "updated_at"])
    _history(doc, actor, "restored")
    audit.record("document.restore", request=request, actor=actor, target=doc, subject_user=doc.owner)


def purge_document(*, actor, doc: Document, request=None) -> None:
    """Permanently delete an archived document, its versions, derivatives and search data."""
    if doc.archived_at is None:
        raise DomainError("Only archived documents can be permanently deleted.")
    files = []
    for v in doc.versions.all():
        files.append(storage.resolve_original(v.storage_path))
        files.append(storage.derivative_dir(v.id))
    doc_id, owner, title_len = doc.id, doc.owner, len(doc.title)
    with transaction.atomic():
        Document.objects.filter(renews=doc).update(renews=None)
        doc.delete()
        audit.record("document.purge", request=request, actor=actor, target_type="document", target_id=str(doc_id),
                     subject_user=owner, title_length=title_len)

        def _cleanup():
            import shutil

            for f in files:
                if f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
                else:
                    storage.remove_file(f)

        transaction.on_commit(_cleanup)


def archive_folder(*, actor, folder: Folder, request=None) -> None:
    if folder.kind == Folder.PERSONAL_ROOT and not actor.is_main_admin:
        raise DomainError("Only the main administrator can archive a person's root folder.")
    folder.archived_at = timezone.now()
    folder.archived_by = actor
    folder.save(update_fields=["archived_at", "archived_by"])
    # Public links inside an archived folder stop working immediately.
    ids = _descendant_ids(folder)
    ShareLink.objects.filter(document__folder_id__in=ids, revoked_at__isnull=True).update(revoked_at=timezone.now())
    audit.record("folder.archive", request=request, actor=actor, target=folder)


def restore_folder(*, actor, folder: Folder, request=None) -> None:
    if Folder.objects.filter(parent=folder.parent, name=folder.name, archived_at__isnull=True).exclude(pk=folder.pk).exists():
        raise DomainError("An active folder with the same name exists; rename it first.")
    folder.archived_at = None
    folder.archived_by = None
    folder.save(update_fields=["archived_at", "archived_by"])
    audit.record("folder.restore", request=request, actor=actor, target=folder)


def _descendant_ids(folder: Folder) -> list:
    ids = [folder.id]
    frontier = [folder.id]
    while frontier:
        nxt = list(Folder.objects.filter(parent_id__in=frontier).values_list("id", flat=True))
        ids += nxt
        frontier = nxt
    return ids


def _lock_tree() -> None:
    """Serialise folder moves: two concurrent moves (A into B, B into A) could otherwise each pass the cycle check
    and leave a detached loop of folders. Transaction-scoped, released on commit/rollback."""
    from django.db import connection

    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", [0x50444D56])  # "PDMV"


def move_folder(*, ctx: P.AccessContext, actor, folder: Folder, new_parent: Folder, request=None) -> bool:
    """Move a folder (with everything inside) under ``new_parent``. Atomic; returns False when nothing changed."""
    with transaction.atomic():
        _lock_tree()
        folder = Folder.objects.select_for_update().get(pk=folder.pk)
        new_parent = Folder.objects.select_for_update().get(pk=new_parent.pk)
        if folder.parent_id is None:
            raise DomainError("Top-level folders cannot be moved.")
        if folder.archived_at or new_parent.archived_at:
            raise DomainError("Archived folders cannot be moved or used as a destination.")
        if folder.parent_id == new_parent.id:
            return False
        if new_parent.id in _descendant_ids(folder):
            raise DomainError("A folder cannot be moved into itself or one of its subfolders.")
        if not ctx.is_admin:
            need = P.ORGANIZE
            if not (ctx.folder_caps(folder.id) & need and ctx.folder_caps(new_parent.id) & need):
                raise DomainError("You need organise permission on both locations.")
            # A move that would let more people in needs permission-management rights (prevents escalation);
            # moving within an area with the same (or narrower) access does not.
            if (folder.inherit_permissions and not ctx.folder_caps(folder.id) & P.MANAGE
                    and P.move_widens_access(folder.parent_id, new_parent.id)):
                raise DomainError("Moving this folder there would give other people access to it. "
                                  "Ask someone who can manage permissions here (or the main administrator).")
        if Folder.objects.filter(parent=new_parent, name=folder.name, archived_at__isnull=True).exclude(pk=folder.pk).exists():
            raise DomainError(f"“{new_parent.name}” already has a folder called “{folder.name}”. Rename one of them first.")
        old_parent = folder.parent_id
        folder.parent = new_parent
        folder.save(update_fields=["parent"])
        audit.record("folder.move", request=request, actor=actor, target=folder,
                     source=str(old_parent), destination=str(new_parent.id))
    return True


def move_document(*, ctx: P.AccessContext, actor, doc: Document, folder: Folder, request=None) -> bool:
    """Move a document to ``folder``. Atomic; returns False when it is already there."""
    with transaction.atomic():
        doc = Document.objects.select_for_update().get(pk=doc.pk)
        folder = Folder.objects.get(pk=folder.pk)
        if doc.archived_at:
            raise DomainError("Archived documents cannot be moved.")
        if folder.archived_at:
            raise DomainError("Documents cannot be moved into an archived folder.")
        if doc.folder_id == folder.id:
            return False
        if not ctx.is_admin:
            if not (ctx.doc_caps(doc) & P.ORGANIZE and ctx.folder_caps(folder.id) & P.UPLOAD):
                raise DomainError("You need organise permission here and upload permission at the destination.")
            if (doc.inherit_permissions and not ctx.doc_caps(doc) & P.MANAGE
                    and P.move_widens_access(doc.folder_id, folder.id)):
                raise DomainError("Moving this document there would give other people access to it. "
                                  "Ask someone who can manage permissions here (or the main administrator).")
        source = doc.folder_id
        doc.folder = folder
        doc.save(update_fields=["folder", "updated_at"])
        _history(doc, actor, "moved", folder=str(folder.id), source=str(source))
        audit.record("document.move", request=request, actor=actor, target=doc, source=str(source), destination=str(folder.id))
    return True


# ---------------------------------------------------------------- permissions administration

def grant(*, ctx: P.AccessContext, actor, target, caps: int, user=None, group=None, request=None) -> AccessRule | None:
    from .models import Folder as F

    is_folder = isinstance(target, F)
    held = ctx.folder_caps(target.id) if is_folder else ctx.doc_caps(target)
    if not ctx.is_admin:
        if not held & P.MANAGE:
            raise DomainError("You cannot manage permissions here.")
        if caps & ~held:
            raise DomainError("You cannot grant capabilities you do not hold yourself.")
        if caps & P.MANAGE:
            raise DomainError("Only the main administrator can grant permission management.")
    filters = {"folder": target} if is_folder else {"document": target}
    filters.update({"user": user} if user is not None else {"group": group})
    if caps == 0:
        AccessRule.objects.filter(**filters).delete()
        audit.record("permission.revoke", request=request, actor=actor, target=target,
                     subject=str(getattr(user or group, "pk", "")))
        return None
    previous = AccessRule.objects.filter(**filters).values_list("caps", flat=True).first() or 0
    rule, _ = AccessRule.objects.update_or_create(**filters, defaults={"caps": caps, "created_by": actor})
    audit.record("permission.grant", request=request, actor=actor, target=target, caps=P.names(caps),
                 subject=str(getattr(user or group, "pk", "")))
    if caps & P.VIEW and not previous & P.VIEW:
        from apps.notify import events

        recipients = [user] if user is not None else [m.user for m in group.memberships.select_related("user")]
        transaction.on_commit(lambda: events.access_granted(actor=actor, target=target, users=recipients, caps_names=P.names(caps)))
    return rule


def apply_template(*, actor, root: Folder, template: str | None = None) -> int:
    """Create template folders under `root` (idempotent; existing folders are reused, nothing is removed)."""
    from apps.core.registry import template_lines

    if template is None:
        template = config.get("documents.member_template")
    before = Folder.objects.count()
    for parts in template_lines(template):
        get_or_create_folder_path(actor=actor, root=root, parts=parts)
    return Folder.objects.count() - before
