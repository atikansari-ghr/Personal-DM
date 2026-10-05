"""Notifications for events other than expiry reminders.

Every message uses the shared template (``templates.render``): site name, account, what happened, when, and a
review link that requires signing in. Whether a person gets an event, and on which channels, follows
``catalog``: critical events cannot be turned off; optional ones follow each person's choices.
Bulk actions produce one summary (with the first few file names and a report link), never one message per file.
Each event has an idempotency key so retries never notify twice.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from . import catalog, templates
from .expiry import dispatch, local_today

log = logging.getLogger("personaldocs.notify")


def notify(user, event: str, *, key: str, title: str, lines=(), facts=(), items=(), items_label: str = "Files",
           more: int = 0, link: str = "", document=None, kind: str | None = None) -> dict | None:
    """Send one event to one person through the channels the catalogue resolves for them."""
    if user is None or not user.is_active or not catalog.applies_to(user, event):
        return None
    if not catalog.channels_for(user, event):
        return None
    facts = [*facts, ("Date/time", templates.local_stamp())]
    in_app = templates.render(user=user, title=title, lines=lines, facts=facts, items=items, items_label=items_label,
                              more=more, header=False)
    external = templates.render(user=user, title=title, lines=lines, facts=facts, items=items, items_label=items_label,
                                more=more, link=link)
    try:
        return dispatch(user, kind=kind or event.split(".")[0], key=key, subject=templates.text(title, False)[:200], body=in_app,
                        link=link, document=document, external_subject=templates.subject(templates.text(title, True)),
                        external_body=external, event=event)
    except Exception:  # noqa: BLE001 - a notification must never break the action that triggered it
        log.exception("notification %s failed", event)
        return None


def _admins():
    from apps.accounts.models import User

    return User.objects.filter(is_main_admin=True, is_active=True)


def _stamp() -> str:
    return timezone.now().strftime("%Y%m%d%H%M%S%f")


def _folder_path(folder) -> templates.Name:
    from apps.library.services import folder_path

    return templates.Name(" / ".join(f.name for f in folder_path(folder)))


def access_granted(*, actor, target, users, caps_names: list[str]) -> None:
    from apps.library.models import Folder

    if "view" not in caps_names:
        return
    is_folder = isinstance(target, Folder)
    what = "folder" if is_folder else "document"
    label = target.name if is_folder else target.title
    link = f"/folders/{target.id}" if is_folder else f"/documents/{target.id}"
    who = actor.display_name if actor else "An administrator"
    stamp = _stamp()
    for user in users:
        if actor is not None and user.pk == actor.pk:
            continue
        notify(user, "document.shared", kind="access", key=f"access:{target.id}:{user.pk}:{stamp}",
               title=lambda n: f"{who} gave you access to the {what} “{n(label)}”",
               facts=[("Access", ", ".join(caps_names))], link=link)


def documents_added(*, actor, docs: list, via: str = "upload") -> None:
    """One summary per owner and action (an upload of many files is one message)."""
    by_owner: dict = {}
    for d in docs:
        if actor is None or d.owner_id != actor.pk:
            by_owner.setdefault(d.owner, []).append(d)
    stamp = _stamp()
    for owner, items in by_owner.items():
        folders = {d.folder_id: d.folder for d in items}
        where = _folder_path(next(iter(folders.values()))) if len(folders) == 1 else f"{len(folders)} folders"
        count = len(items)
        notify(owner, "document.added", key=f"added:{owner.pk}:{stamp}",
               title=f"{count} document{'s' if count != 1 else ''} added to your account",
               lines=[f"Added by {actor.display_name if actor else 'an import'} ({via})."],
               facts=[("Folder", where)], items=[d.title for d in items],
               link=f"/folders/{items[0].folder_id}" if len(folders) == 1 else "/folders")


class GoneDocument:
    """What is left to say about a document after it was permanently deleted."""

    def __init__(self, doc):
        self.id, self.title, self.owner, self.owner_id = doc.id, doc.title, doc.owner, doc.owner_id


def documents_removed(*, actor, docs: list, permanent: bool) -> None:
    """Tell owners (other than the person acting) that documents were archived (restorable) or permanently deleted.
    One message per owner and action."""
    by_owner: dict = {}
    for d in docs:
        if d.owner is not None and not (actor is not None and d.owner_id == actor.pk):
            by_owner.setdefault(d.owner, []).append(d)
    who = actor.display_name if actor else "an administrator"
    stamp = _stamp()
    for owner, items in by_owner.items():
        n = len(items)
        if permanent:
            title = f"{n} document{'s' if n != 1 else ''} of yours permanently deleted"
            lines = [f"Deleted by {who}. This cannot be undone."]
        else:
            title = f"{n} document{'s' if n != 1 else ''} of yours archived"
            lines = [f"Archived by {who}. Archived documents are hidden, not deleted; the main administrator can restore them."]
        notify(owner, "document.archived", kind="archive", key=f"removed:{owner.pk}:{'purge' if permanent else 'archive'}:{stamp}",
               title=title, lines=lines, items=[d.title for d in items], link="/notifications")


def import_finished(session) -> None:
    from apps.library.models import ImportItem

    items = ImportItem.objects.filter(session=session)
    done_items = list(items.filter(status="done").select_related("document", "document__owner", "document__folder"))
    done, failed = len(done_items), items.filter(status="failed").count()
    title = f"Import finished: {done} imported" + (f", {failed} failed" if failed else "")
    names = [i.relative_path.rsplit("/", 1)[-1] for i in done_items]
    link = f"/imports/{session.id}"
    notify(session.created_by, "import.finished", kind="import", key=f"import:{session.id}:{session.status}:{done}:{failed}",
           title=title, lines=["Open the import to see the per-file report."], items=names, link=link)
    # owners who received documents from someone else's import get one summary each
    docs = [i.document for i in done_items if i.document_id]
    by_owner: dict = {}
    for d in docs:
        if d.owner_id != session.created_by_id:
            by_owner.setdefault(d.owner, []).append(d)
    for owner, owned in by_owner.items():
        folders = {d.folder_id: d.folder for d in owned}
        where = _folder_path(next(iter(folders.values()))) if len(folders) == 1 else f"{len(folders)} folders"
        notify(owner, "document.added", key=f"import-owner:{session.id}:{owner.pk}",
               title=f"{len(owned)} file{'s' if len(owned) != 1 else ''} imported to your account",
               lines=[f"Imported by {session.created_by.display_name}."], facts=[("Folder", where)],
               items=[d.title for d in owned], link=f"/folders/{owned[0].folder_id}" if len(folders) == 1 else "/folders")


def backup_failed(reason: str) -> None:
    day = local_today().isoformat()
    for admin in _admins():
        notify(admin, "backup.failed", kind="backup", key=f"backup_failed:{day}", title="Backup failed",
               lines=[f"Reason: {reason[:300]}", "Check that the NAS is mounted, then run Back up now."],
               link="/settings/storage")


def integrity_problems(count: int) -> None:
    if count <= 0:
        return
    day = local_today().isoformat()
    for admin in _admins():
        notify(admin, "integrity.failed", kind="integrity", key=f"integrity:{day}",
               title=f"Integrity check found {count} problem(s)",
               lines=["Review the report and planned repairs in Settings → Storage & backup."], link="/settings/storage")


def _from_import(doc) -> bool:
    from apps.library.models import ImportItem

    return ImportItem.objects.filter(document=doc).exists()


def processing_failed(version) -> None:
    doc = version.document
    if version.created_by is None or _from_import(doc):
        return  # imports report failures in their own summary
    notify(version.created_by, "processing.failed", kind="processing", key=f"processing_failed:{version.id}", document=doc,
           title=lambda n: f"Processing failed for “{n(doc.title)}”",
           lines=["The original is stored safely. You can retry OCR/preview from the document's menu."],
           link=f"/documents/{doc.id}")


def processing_completed(version) -> None:
    doc = version.document
    if version.created_by is None or _from_import(doc):
        return
    notify(version.created_by, "processing.completed", kind="processing", key=f"processing_done:{version.id}", document=doc,
           title=lambda n: f"“{n(doc.title)}” is processed and searchable",
           facts=[("OCR", "applied" if version.ocr_applied else "not needed"), ("Pages", version.page_count or "")],
           link=f"/documents/{doc.id}")
