"""Notifications for events other than expiry.

In-app entries may name the folder or document (the recipient can see it). External messages (email/Telegram)
stay minimal and never include document numbers, file names of other people's documents or attachments.
Each event has an idempotency key so retries never notify twice.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.core import config

from .expiry import dispatch, local_today

log = logging.getLogger("personaldocs.notify")


def _send(user, *, kind, key, subject, body, link="", external_subject=None, external_body=None, document=None):
    if not user.is_active:
        return
    try:
        dispatch(user, kind=kind, key=key, subject=subject, body=body, link=link, document=document,
                 external_subject=external_subject, external_body=external_body,
                 external=bool(config.get_user(user, "me.event_alerts")))
    except Exception:  # noqa: BLE001 - a notification must never break the action that triggered it
        log.exception("event notification %s failed", kind)


def _admins():
    from apps.accounts.models import User

    return User.objects.filter(is_main_admin=True, is_active=True)


def access_granted(*, actor, target, users, caps_names: list[str]) -> None:
    from apps.library.models import Folder

    if "view" not in caps_names:
        return
    is_folder = isinstance(target, Folder)
    what = "folder" if is_folder else "document"
    name = target.name if is_folder else target.title
    link = f"/folders/{target.id}" if is_folder else f"/documents/{target.id}"
    who = actor.display_name if actor else "An administrator"
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    for user in users:
        if actor is not None and user.pk == actor.pk:
            continue
        _send(user, kind="access", key=f"access:{target.id}:{user.pk}:{stamp}",
              subject=f"{who} gave you access to the {what} “{name}”",
              body=f"You can now view the {what} “{name}”.", link=link,
              external_subject=f"{config.get('general.app_name')}: you were given access to a {what}",
              external_body=f"{who} gave you access to a {what}. Sign in to view: {settings.PUBLIC_ORIGIN}{link}")


def import_finished(session) -> None:
    from apps.library.models import ImportItem

    done = ImportItem.objects.filter(session=session, status="done").count()
    failed = ImportItem.objects.filter(session=session, status="failed").count()
    subject = f"Import finished: {done} imported" + (f", {failed} failed" if failed else "")
    _send(session.created_by, kind="import", key=f"import:{session.id}:{session.status}:{done}:{failed}",
          subject=subject, body="Open the import to see the per-file report.", link=f"/imports/{session.id}",
          external_body=f"{subject}. Sign in to see the report: {settings.PUBLIC_ORIGIN}/imports/{session.id}")


def backup_failed(reason: str) -> None:
    day = local_today().isoformat()
    for admin in _admins():
        _send(admin, kind="backup", key=f"backup_failed:{day}", subject="Backup failed",
              body=f"The backup did not complete: {reason[:300]}", link="/settings/storage",
              external_body=f"The {config.get('general.app_name')} backup failed. Check Settings → Storage & backup: "
                            f"{settings.PUBLIC_ORIGIN}/settings/storage")


def integrity_problems(count: int) -> None:
    if count <= 0:
        return
    day = local_today().isoformat()
    for admin in _admins():
        _send(admin, kind="integrity", key=f"integrity:{day}", subject=f"Integrity check found {count} problem(s)",
              body="Review the report and planned repairs in Settings → Storage & backup.", link="/settings/storage",
              external_body=f"The storage integrity check found {count} problem(s). Review: {settings.PUBLIC_ORIGIN}/settings/storage")


def processing_failed(version) -> None:
    doc = version.document
    user = version.created_by
    if user is None:
        return
    _send(user, kind="processing", key=f"processing_failed:{version.id}", document=doc,
          subject=f"Processing failed for “{doc.title}”",
          body="The original is stored safely. You can retry OCR/preview from the document's menu.",
          link=f"/documents/{doc.id}", external_subject=f"{config.get('general.app_name')}: a document could not be processed",
          external_body=f"A document you uploaded could not be processed. Sign in to retry: {settings.PUBLIC_ORIGIN}/documents/{doc.id}")
