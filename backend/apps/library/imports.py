"""Folder-to-account import wizard (browser folder uploads and approved server/NAS paths).

Server imports COPY files into managed storage; sources are opened read-only and never modified.
Ownership is never guessed: proposals must be confirmed, and unmatched folders must be resolved.
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path, PurePosixPath

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core import audit, config, jobs

from . import permissions as P
from . import services as S
from . import storage
from .models import Folder, ImportItem, ImportSession

EXCLUDE_NAMES = {".sync": "Sync tool history folder", ".git": "Version control data", "__MACOSX": "macOS archive metadata",
                 ".DS_Store": "macOS metadata", "Thumbs.db": "Windows thumbnail cache", "desktop.ini": "Windows folder settings",
                 "@eaDir": "NAS index folder", "#recycle": "NAS recycle bin", ".Trash": "Trash folder"}
ROOT_FILES = "(files in the top folder)"
MAX_ITEMS = 200_000


def normalize_rel(path: str) -> str:
    path = unicodedata.normalize("NFC", (path or "").replace("\\", "/"))
    parts = [p for p in PurePosixPath(path).parts if p not in ("", ".", "/")]
    if any(p == ".." for p in parts) or path.startswith("/"):
        raise ValueError("Unsafe path")
    if any(re.search(r"[\x00-\x1f]", p) for p in parts):
        raise ValueError("Unsafe characters in path")
    return "/".join(parts)


def excluded_reason(rel: str) -> str:
    for part in rel.split("/"):
        if part in EXCLUDE_NAMES:
            return EXCLUDE_NAMES[part]
        if part.startswith(".") and part not in (".",):
            return "Hidden file or folder"
    return ""


def top_level(rel: str) -> str:
    return rel.split("/", 1)[0] if "/" in rel else ROOT_FILES


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def propose_mapping(tops: list[str]) -> dict:
    """Suggestions only — status 'proposed' until the user confirms each mapping."""
    users = list(User.objects.filter(is_active=True))
    out = {}
    for top in tops:
        if top in EXCLUDE_NAMES or top.startswith("."):
            out[top] = {"action": "skip", "status": "proposed", "reason": EXCLUDE_NAMES.get(top, "Hidden folder")}
            continue
        n = _norm(top)
        match = None
        for u in users:
            aliases = {_norm(u.display_name), _norm(u.full_name), _norm(u.username)}
            aliases.discard("")
            if n in aliases:
                match = (u, "name matches")
                break
        if match:
            out[top] = {"action": "user", "user": str(match[0].pk), "status": "proposed", "reason": match[1]}
        else:
            out[top] = {"action": None, "status": "unresolved", "reason": "No matching account — choose an owner, a shared folder, or skip."}
    return out


def scan_browser(session: ImportSession, entries: list[dict]) -> dict:
    if len(entries) > MAX_ITEMS:
        raise S.DomainError(f"Too many files in one import (limit {MAX_ITEMS}).")
    items, tops, total, excluded = [], {}, 0, 0
    for e in entries:
        rel = normalize_rel(e.get("path", ""))
        size = int(e.get("size") or 0)
        reason = excluded_reason(rel)
        items.append(ImportItem(session=session, relative_path=rel, size=size, status="skipped" if reason else "pending",
                                excluded_reason=reason))
        t = top_level(rel)
        info = tops.setdefault(t, {"files": 0, "bytes": 0, "excluded": 0})
        info["files"] += 1
        info["bytes"] += size
        if reason:
            info["excluded"] += 1
            excluded += 1
        total += size
    with transaction.atomic():
        ImportItem.objects.filter(session=session).delete()
        ImportItem.objects.bulk_create(items, batch_size=2000)
        session.scan = {"files": len(items), "bytes": total, "excluded": excluded, "tops": tops,
                        "tree": _tree([i.relative_path for i in items])}
        session.mapping = propose_mapping(list(tops.keys()))
        session.status = "mapping"
        session.save()
    return session.scan


def approved_roots() -> list[Path]:
    raw = config.get("documents.import_roots") or ""
    return [Path(line.strip()).resolve() for line in raw.splitlines() if line.strip().startswith("/")]


def validate_server_root(root: str) -> Path:
    p = Path(root).resolve()
    roots = approved_roots()
    if not any(p == r or r in p.parents for r in roots):
        raise S.DomainError("This path is not inside an approved import folder (Settings → Documents & Folders).")
    if not p.is_dir():
        raise S.DomainError("The folder does not exist or is not readable.")
    return p


def scan_server(session: ImportSession) -> dict:
    root = validate_server_root(session.source_root)
    entries = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            full = Path(dirpath) / name
            rel = str(full.relative_to(root)).replace(os.sep, "/")
            try:
                st = full.lstat()
            except OSError:
                continue
            if full.is_symlink():
                target = full.resolve()
                if not (target == root or root in target.parents):
                    entries.append({"path": rel, "size": 0, "symlink_outside": True})
                    continue
                st = target.stat()
            entries.append({"path": rel, "size": st.st_size})
            if len(entries) > MAX_ITEMS:
                raise S.DomainError(f"Too many files (limit {MAX_ITEMS}).")
    scan = scan_browser(session, entries)
    bad = [e["path"] for e in entries if e.get("symlink_outside")]
    if bad:
        ImportItem.objects.filter(session=session, relative_path__in=bad).update(status="skipped",
                                                                                  excluded_reason="Symbolic link outside the approved folder")
    return scan


def _tree(paths: list[str], limit: int = 4000) -> list:
    """Compact folder tree (folders only) for the preview."""
    folders = set()
    for p in paths:
        parts = p.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            folders.add("/".join(parts[:i]))
    return sorted(folders)[:limit]


def validate_mapping(session: ImportSession, mapping: dict, actor) -> dict:
    ctx = P.AccessContext.build(actor)
    tops = set(session.scan.get("tops", {}).keys())
    clean = {}
    for top in tops:
        m = mapping.get(top) or {}
        action = m.get("action")
        if action == "user":
            u = User.objects.filter(pk=m.get("user"), is_active=True).first()
            if u is None:
                raise S.DomainError(f"Choose a valid owner for '{top}'.")
            root = Folder.objects.filter(owner=u, kind=Folder.PERSONAL_ROOT, archived_at__isnull=True).first()
            if root is None:
                raise S.DomainError(f"{u.display_name} has no personal folder.")
            dest = root
            if m.get("folder") and str(m["folder"]) != str(root.pk):
                dest = Folder.objects.filter(pk=m["folder"], archived_at__isnull=True).first()
                # the chosen sub-folder must really be inside this person's area (not just any folder)
                if dest is None or root not in S.folder_path(dest) or not ctx.folder_caps(dest.id) & P.VIEW:
                    raise S.DomainError(f"The sub-folder chosen for '{top}' is not inside {u.display_name}'s folder.")
            if not ctx.folder_caps(dest.id) & P.UPLOAD:
                raise S.DomainError(f"You cannot upload into the folder chosen for '{top}'.")
            clean[top] = {"action": "user", "user": str(u.pk), "folder": str(dest.pk) if dest.pk != root.pk else None,
                          "keep_top": bool(m.get("keep_top", False)) and top != ROOT_FILES, "status": "confirmed"}
        elif action == "folder":
            f = Folder.objects.filter(pk=m.get("folder"), archived_at__isnull=True).first()
            if f is None or not ctx.folder_caps(f.id) & P.UPLOAD:
                raise S.DomainError(f"You cannot upload into the folder chosen for '{top}'.")
            owner = User.objects.filter(pk=m.get("owner"), is_active=True).first() if m.get("owner") else f.owner
            if owner is None:
                raise S.DomainError(f"Choose who owns the documents in '{top}' (documents always belong to an account).")
            clean[top] = {"action": "folder", "folder": str(f.pk), "owner": str(owner.pk),
                          "keep_top": bool(m.get("keep_top", True)) and top != ROOT_FILES, "status": "confirmed"}
        elif action == "skip":
            clean[top] = {"action": "skip", "status": "confirmed"}
        else:
            raise S.DomainError(f"Decide what to do with '{top}' before importing.")
        for k in ("include_excluded",):
            if m.get(k):
                clean[top][k] = True
    session.mapping = clean
    session.save(update_fields=["mapping"])
    return clean


def _base_folder(m: dict) -> Folder | None:
    if m.get("action") == "user":
        if m.get("folder"):
            return Folder.objects.filter(pk=m["folder"]).first()
        return Folder.objects.filter(owner_id=m["user"], kind=Folder.PERSONAL_ROOT, archived_at__isnull=True).first()
    if m.get("action") == "folder":
        return Folder.objects.filter(pk=m["folder"]).first()
    return None


def _sub_parts(m: dict, rel: str) -> list[str]:
    """Folders below the destination for one source file: the selected destination replaces only the import root,
    every nested source folder is kept (the top folder itself too when ``keep_top`` is set)."""
    top = top_level(rel)
    sub = rel.split("/")[1:-1] if top != ROOT_FILES else []
    if m.get("keep_top") and top != ROOT_FILES:
        sub = [top] + sub
    return [storage.safe_component(p, 200) for p in sub]


def preview(session: ImportSession) -> list[dict]:
    out = []
    for top, m in session.mapping.items():
        info = session.scan.get("tops", {}).get(top, {})
        base = _base_folder(m)
        dest = None
        if base is not None:
            dest = " / ".join(x.name for x in S.folder_path(base))
            if m.get("keep_top") and top != ROOT_FILES:
                dest += f" / {storage.safe_component(top, 200)}"
        out.append({"source": top, "action": m.get("action"), "destination": dest, "files": info.get("files", 0),
                    "bytes": info.get("bytes", 0), "excluded": info.get("excluded", 0), "status": m.get("status")})
    return out


def preview_tree(session: ImportSession, limit: int = 3000) -> list[dict]:
    """The exact folders the import will use, with file counts and whether each already exists (files are then
    added next to what is there — nothing is overwritten) or will be created."""
    counts: dict[tuple, int] = {}
    bases: dict[str, Folder | None] = {}
    for rel, excluded in ImportItem.objects.filter(session=session).exclude(status="done").values_list("relative_path", "excluded_reason").iterator():
        top = top_level(rel)
        m = session.mapping.get(top) or {}
        if m.get("action") in (None, "skip") or (excluded and not m.get("include_excluded")):
            continue
        if top not in bases:
            bases[top] = _base_folder(m)
        base = bases[top]
        if base is None:
            continue
        key = (str(base.pk), *_sub_parts(m, rel))
        counts[key] = counts.get(key, 0) + 1
    # every intermediate folder appears too, even when it holds no files directly
    keys = set(counts)
    for k in list(counts):
        for i in range(1, len(k)):
            keys.add(k[:i])
    names = {str(b.pk): " / ".join(x.name for x in S.folder_path(b)) for b in bases.values() if b is not None}
    exists: dict[tuple, str | None] = {}

    def existing_id(key: tuple) -> str | None:
        if key in exists:
            return exists[key]
        if len(key) == 1:
            exists[key] = key[0]
        else:
            parent = existing_id(key[:-1])
            child = Folder.objects.filter(parent_id=parent, name=key[-1], archived_at__isnull=True).values_list("id", flat=True).first() if parent else None
            exists[key] = str(child) if child else None
        return exists[key]

    rows = []
    for key in sorted(keys, key=lambda k: (names.get(k[0], ""), [p.lower() for p in k[1:]]))[:limit]:
        rows.append({"path": " / ".join([names.get(key[0], "?"), *key[1:]]), "depth": len(key) - 1, "files": counts.get(key, 0),
                     "exists": existing_id(key) is not None})
    return rows


def capacity_warning(session: ImportSession) -> str | None:
    need = int(session.scan.get("bytes", 0) * 1.3)  # originals + derivatives estimate
    free = storage.disk_free_bytes()
    if need > free - storage.MIN_FREE_BYTES:
        return f"About {need // (1024 ** 2)} MB may be needed (originals and previews) but only {free // (1024 ** 2)} MB is free."
    return None


def destination_for(session: ImportSession, rel: str):
    """Return (folder, owner) for an item, creating sub-folders that mirror the source path below the destination."""
    m = session.mapping.get(top_level(rel)) or {}
    if m.get("action") == "user":
        owner = User.objects.get(pk=m["user"])
    elif m.get("action") == "folder":
        owner = User.objects.get(pk=m["owner"])
    else:
        return None, None
    base = _base_folder(m)
    if base is None or base.archived_at:
        raise S.DomainError("The destination folder no longer exists.")
    folder = S.get_or_create_folder_path(actor=session.created_by, root=base, parts=_sub_parts(m, rel),
                                         source_prefix=session.source_root or "")
    return folder, owner


def item_allowed(session: ImportSession, item: ImportItem) -> bool:
    if item.status == "done":
        return False
    m = session.mapping.get(top_level(item.relative_path)) or {}
    if m.get("action") in (None, "skip"):
        return False
    if item.excluded_reason and not m.get("include_excluded"):
        return False
    if item.excluded_reason.startswith("Symbolic link"):
        return False
    return True


def import_item(session: ImportSession, item: ImportItem, staged: storage.Staged) -> ImportItem:
    """Idempotent: a retried item that already produced a document returns it without a new copy."""
    with transaction.atomic():
        locked = ImportItem.objects.select_for_update().get(pk=item.pk)
        if locked.status == "done" and locked.document_id:
            staged.path.unlink(missing_ok=True)
            return locked
        folder, owner = destination_for(session, locked.relative_path)
        if folder is None:
            staged.path.unlink(missing_ok=True)
            locked.status = "skipped"
            locked.save(update_fields=["status"])
            return locked
        # Permission re-checked at execution time (the mapping may be stale).
        ctx = P.AccessContext.build(session.created_by)
        if not session.created_by.is_active or not ctx.folder_caps(folder.id) & P.UPLOAD:
            staged.path.unlink(missing_ok=True)
            raise S.DomainError("Upload permission for the destination has been removed.")
        source = f"{session.source_root.rstrip('/')}/{locked.relative_path}" if session.source_root else locked.relative_path
        doc = S.create_document(actor=session.created_by, folder=folder, owner=owner, staged=staged, source_path=source[:2000])
        locked.status, locked.document, locked.error = "done", doc, ""
        locked.attempts += 1
        locked.save(update_fields=["status", "document", "error", "attempts"])
        return locked


def finish_if_done(session: ImportSession) -> None:
    if not ImportItem.objects.filter(session=session, status="pending").exists() and session.status == "importing":
        failed = ImportItem.objects.filter(session=session, status="failed").count()
        session.status = "done" if failed == 0 else "done_with_errors"
        session.finished_at = timezone.now()
        session.save(update_fields=["status", "finished_at"])
        audit.record("import.finish", actor=session.created_by, target=session, failed=failed)
        from apps.notify import events

        events.import_finished(session)


@jobs.handler("import_server")
def import_server_job(job):
    session = ImportSession.objects.select_related("created_by").filter(pk=job.payload["session_id"]).first()
    if session is None or session.status not in ("importing",):
        return {"skipped": True}
    if not session.created_by.is_main_admin:
        raise jobs.PermanentFailure("Server imports require the main administrator.")
    root = validate_server_root(session.source_root)
    done = failed = 0
    for item in ImportItem.objects.filter(session=session, status__in=["pending", "failed"]).order_by("id"):
        if not item_allowed(session, item):
            continue
        src = (root / item.relative_path)
        try:
            resolved = src.resolve()
            if not (resolved == root or root in resolved.parents):
                raise S.DomainError("Path escapes the approved folder")
            staged = storage.stage_local_file(resolved, original_name=src.name)
            import_item(session, item, staged)
            done += 1
        except Exception as exc:  # noqa: BLE001 - per-item result
            ImportItem.objects.filter(pk=item.pk).update(status="failed", error=str(exc)[:500], attempts=item.attempts + 1)
            failed += 1
    finish_if_done(session)
    return {"imported": done, "failed": failed}
