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


def notify(user, event: str, *, key: str, title, lines=(), facts=(), items=(), items_label: str = "Files",
           more: int = 0, link: str = "", document=None, kind: str | None = None, severity: str = "", icon: str = "",
           summary="", heading="", details=None, actions=None, guidance=None, context=None,
           cooldown_group: str = "") -> dict | None:
    """Send one structured event to one person on the channels the catalogue resolves for them.

    ``cooldown_group`` marks a recurring condition (antivirus down, storage nearly full …): the same group is not
    notified again to the same person within ``notifications.repeat_cooldown_hours``."""
    from . import rich

    if user is None or not user.is_active or not catalog.applies_to(user, event):
        return None
    if not catalog.channels_for(user, event):
        return None
    if cooldown_group and _cooling_down(user, event, cooldown_group):
        return None
    facts = [*facts, ("Date/time", templates.local_stamp())]
    acts = list(actions) if actions is not None else default_actions(event, link=link, context=context or {})
    try:
        msg = rich.from_legacy(event, title=title, lines=lines, facts=facts, items=items, items_label=items_label,
                               more=more, link=link, severity=severity, icon=icon, summary=summary, heading=heading,
                               details=details, actions=acts, guidance=guidance, context=context)
        return dispatch(user, msg, kind=kind or event.split(".")[0], key=key, document=document, group=cooldown_group)
    except Exception:  # noqa: BLE001 - a notification must never break the action that triggered it
        log.exception("notification %s failed", event)
        return None


def _cooling_down(user, event: str, group: str) -> bool:
    from datetime import timedelta

    from apps.core import config

    from .models import Notification

    since = timezone.now() - timedelta(hours=int(config.get("notifications.repeat_cooldown_hours")))
    return Notification.objects.filter(user=user, event=event, data__group=group, created_at__gte=since).exists()


def default_actions(event: str, *, link: str = "", context: dict | None = None) -> list:
    """Event-specific actions. Each is an application page: opening it requires signing in and the normal
    permission checks. Release from quarantine is deliberately absent (only inside the app, main administrator)."""
    from .rich import Action

    ctx = context or {}
    doc, folder = ctx.get("document_id"), ctx.get("folder_id")
    acts: list = []
    if event in ("document.added", "document.changed", "document.shared"):
        if doc:
            acts.append(Action("view_document", "View Document", f"/documents/{doc}", primary=True))
        if folder:
            acts.append(Action("folder", "Go to Folder", f"/folders/{folder}"))
    elif event in ("processing.completed", "processing.failed"):
        if doc:
            acts.append(Action("view_document", "View Document", f"/documents/{doc}", primary=True))
        acts.append(Action("ocr_review", "OCR review", "/ocr-review"))
    elif event in ("security.new_ip", "security.new_country", "account.login", "security.passkey_added",
                   "security.passkey_removed", "security.totp_enabled", "security.totp_disabled", "security.recovery_codes",
                   "security.passwordless", "security.admin_recovery", "security.authentik"):
        acts += [Action("review_activity", "Review Activity", "/settings/account?tab=security", primary=True),
                 Action("sessions", "Manage Sessions", "/settings/account?tab=security"),
                 Action("change_password", "Change Password", "/settings/account?tab=security")]
    elif event in ("security.failed_logins", "security.policy_exception"):
        acts += [Action("review_activity", "Review Activity", "/settings/activity?view=logins", primary=True),
                 Action("access_policy", "Access policy", "/settings/security?view=access")]
    elif event in ("security.policy_change", "security.auth_policy"):
        acts.append(Action("open_security", "Open Security", "/settings/security", primary=True))
    elif event.startswith("antivirus."):
        acts += [Action("security_event", "View Security Event", "/settings/security?view=antivirus", primary=True),
                 Action("security_health", "Security Health", "/settings/security")]
    elif event == "security.operations":
        acts += [Action("system_status", "View System Status", "/settings/security", primary=not link),
                 Action("update_logs", "View Update Details", "/settings/security?view=updates")]
    elif event in ("backup.failed", "integrity.failed"):
        acts.append(Action("storage", "Open Storage & backup", "/settings/storage", primary=True))
    elif event == "import.finished" and link:
        acts.append(Action("report", "View Import Report", link, primary=True))
    if link and not any(a.primary for a in acts):
        acts.insert(0, Action("open", "Open", link, primary=True))
    return acts


def _admins():
    from apps.accounts.models import User

    from django.db.models import Q

    return User.objects.filter(Q(is_main_admin=True) | Q(is_admin=True), is_active=True)


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
               summary="It now appears in Shared with me.", facts=[("Access", ", ".join(caps_names))], link=link,
               context={"folder_id": str(target.id)} if is_folder else {"document_id": str(target.id), "document_name": label})


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
               link=f"/folders/{items[0].folder_id}" if len(folders) == 1 else "/folders",
               context={"count": str(count), **({"document_id": str(items[0].id), "document_name": items[0].title} if count == 1 else {}),
                        **({"folder_id": str(items[0].folder_id)} if len(folders) == 1 else {})})


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
        notify(admin, "backup.failed", kind="backup", key=f"backup_failed:{day}", title="Backup failed", icon="backup",
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
           title=lambda n: f"Processing failed for “{n(doc.title)}”", context={"document_id": str(doc.id), "document_name": doc.title},
           lines=["The original is stored safely. You can retry OCR/preview from the document's menu."],
           link=f"/documents/{doc.id}")


def processing_completed(version) -> None:
    doc = version.document
    if version.created_by is None or _from_import(doc):
        return
    notify(version.created_by, "processing.completed", kind="processing", key=f"processing_done:{version.id}", document=doc,
           title=lambda n: f"“{n(doc.title)}” is processed and searchable", context={"document_id": str(doc.id), "document_name": doc.title},
           facts=[("OCR", "applied" if version.ocr_applied else "not needed"), ("Pages", version.page_count or "")],
           link=f"/documents/{doc.id}")


def documents_changed(*, actor, doc, change: str) -> None:
    """Tell the owner when someone else moved, restored, re-typed or confirmed the details of their document."""
    owner = getattr(doc, "owner", None)
    if owner is None or (actor is not None and actor.pk == owner.pk):
        return
    who = actor.display_name if actor else "An administrator"
    notify(owner, "document.changed", kind="document", key=f"changed:{doc.id}:{change}:{_stamp()}", document=doc,
           title=lambda n: f"{who} {change} your document “{n(doc.title)}”", link=f"/documents/{doc.id}",
           context={"document_id": str(doc.id), "folder_id": str(doc.folder_id), "document_name": doc.title})


def authentik_link_changed(user, *, linked: bool, by_admin: bool = False) -> None:
    what = "linked to" if linked else "unlinked from"
    notify(user, "security.authentik", kind="security", key=f"authentik:{user.pk}:{linked}:{_stamp()}",
           title=f"Your account was {what} authentik", severity="warning",
           summary=("An administrator removed the link. " if by_admin else "")
           + ("You can now sign in with authentik." if linked else "Sign in with your password or passkey."),
           guidance=["If this was not you, change your password and sign out other devices."])
