"""Recovery Explorer and granular restore (version, document, folder/subtree, user scope).

Authorisation follows today's rules, not the rules inside the backup:
* the main administrator sees and restores everything;
* everyone else (administrators included - the Administrator role never grants document access) sees a document
  of a recovery point when they own it in the backup, or when they currently hold *add versions* on the existing
  document, or *upload* on its existing folder; they restore only into places where they hold those rights now.

Conflict modes (chosen before execution, shown in the Restore Impact Analysis):
* ``keep_new`` (default, safest) - current data stays as it is; restored content is added as new versions marked
  "Restored from backup"; missing items are re-created.
* ``replace`` - the restored version becomes the current version and the document details go back to the backup's
  values. The previous current version stays in the version history (nothing is deleted).
* ``skip`` - existing documents are left untouched; only missing items are re-created.

No restore deletes current data. Deleted data is recoverable only while retained backups contain it.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import audit

from . import bk_crypto as C
from . import bk_keys
from .bk_destinations import DestError, provider
from .bk_validation import best_copy, chain_copies
from .models import RecoveryPoint, RestoreRun

log = logging.getLogger("personaldocs.recovery")
MODES = ("keep_new", "replace", "skip")
_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 300


class RestoreError(Exception):
    pass


# ------------------------------------------------------------------ loading a point

def restorable_points():
    return RecoveryPoint.objects.filter(deleted_at__isnull=True, status__in=[RecoveryPoint.VERIFIED, RecoveryPoint.PARTIAL,
                                                                             RecoveryPoint.WARNING]).order_by("-created_at")


def load(point: RecoveryPoint) -> dict:
    """Catalogue + manifest of a point (decrypted in memory only; kept for a few minutes)."""
    key = str(point.id)
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    copy = best_copy(point)
    if copy is None:
        raise RestoreError("No verified copy of this recovery point is reachable right now.")
    from .bk_engine import open_point, read_component

    prov = provider(copy.destination)
    try:
        _h, dek = open_point(prov, point.id, copy.generation, bk_keys.raw_key(copy.generation))
        data = {"catalog": json.loads(read_component(prov, point.id, copy.generation, dek, "catalog.enc")),
                "manifest": json.loads(read_component(prov, point.id, copy.generation, dek, "manifest.enc")),
                "copy_id": copy.id, "destination_id": copy.destination_id}
    except (DestError, C.DecryptError) as exc:
        raise RestoreError(str(exc)) from exc
    _CACHE.clear() if len(_CACHE) > 4 else None
    _CACHE[key] = (time.monotonic(), data)
    return data


def fetch_object(point: RecoveryPoint, data: dict, name: str, dst: Path) -> str:
    meta = data["manifest"]["inventory"].get(name)
    if not meta or meta.get("missing"):
        raise RestoreError("This file was missing when the backup was made.")
    copies = chain_copies(point, data["destination_id"])
    c = copies.get(meta["stored_in"])
    if c is None:
        raise RestoreError("A recovery point this file depends on is not available on the same destination.")
    from .bk_engine import open_point, rel

    prov = provider(c.destination)
    _h, dek = open_point(prov, c.point_id, c.generation, bk_keys.raw_key(c.generation))
    with prov.open(rel(c.point_id, c.generation, name)) as fh:
        sha = C.decrypt_to(fh, dst, dek, name)
    if sha != meta["sha256"]:
        dst.unlink(missing_ok=True)
        raise RestoreError("The restored file does not match its checksum.")
    return sha


# ------------------------------------------------------------------ authorisation

class Scope:
    def __init__(self, user, data: dict):
        from apps.library import permissions as P

        self.user = user
        self.P = P
        self.ctx = P.AccessContext.build(user)
        self.main = bool(user.is_main_admin)
        cat = data["catalog"]
        self.folders = {f["id"]: f for f in cat["folders"]}
        self.docs = {d["id"]: d for d in cat["documents"]}
        self.versions: dict[str, list] = {}
        for v in cat["versions"]:
            self.versions.setdefault(v["document_id"], []).append(v)
        for vs in self.versions.values():
            vs.sort(key=lambda v: v["number"])
        self.users = {u["id"]: u for u in cat["users"]}
        from apps.library.models import Document, Folder

        self.current_docs = {str(d.id): d for d in Document.objects.filter(id__in=list(self.docs))}
        self.current_folders = {str(f.id): f for f in Folder.objects.filter(id__in=list(self.folders))}

    def can_doc(self, did: str) -> bool:
        if self.main:
            return True
        d = self.docs[did]
        if d["owner_id"] == str(self.user.pk):
            return True
        cur = self.current_docs.get(did)
        if cur is not None:
            return bool(self.ctx.doc_caps(cur) & self.P.VERSION)
        f = self.current_folders.get(d["folder_id"])
        return f is not None and bool(self.ctx.folder_caps(f.id) & self.P.UPLOAD)

    def visible_docs(self) -> list[str]:
        return [d for d in self.docs if self.can_doc(d)]

    def subtree(self, fid: str) -> list[str]:
        out, frontier = [fid], [fid]
        children: dict[str, list] = {}
        for f in self.folders.values():
            children.setdefault(f["parent_id"], []).append(f["id"])
        while frontier:
            nxt = []
            for x in frontier:
                nxt += children.get(x, [])
            out += nxt
            frontier = nxt
        return out

    def path(self, fid: str | None) -> list[str]:
        out = []
        while fid and fid in self.folders and len(out) < 64:
            out.append(self.folders[fid]["name"])
            fid = self.folders[fid]["parent_id"]
        return list(reversed(out))


# ------------------------------------------------------------------ explorer

def explorer(user, point: RecoveryPoint, *, owner: str | None = None, folder: str | None = None, q: str = "") -> dict:
    data = load(point)
    s = Scope(user, data)
    docs = s.visible_docs()
    if q:
        ql = q.lower()
        docs = [d for d in docs if ql in (s.docs[d]["title"] or "").lower()
                or any(ql in (v["original_name"] or "").lower() for v in s.versions.get(d, []))
                or ql in " / ".join(s.path(s.docs[d]["folder_id"])).lower()]
    owners = sorted({s.docs[d]["owner_id"] for d in s.visible_docs()})
    if owner:
        docs = [d for d in docs if s.docs[d]["owner_id"] == owner]
    if folder:
        sub = set(s.subtree(folder))
        docs = [d for d in docs if s.docs[d]["folder_id"] in sub]
    folder_ids = set()
    for d in s.visible_docs() if not owner else [d for d in s.visible_docs() if s.docs[d]["owner_id"] == owner]:
        fid = s.docs[d]["folder_id"]
        while fid and fid in s.folders and fid not in folder_ids:
            folder_ids.add(fid)
            fid = s.folders[fid]["parent_id"]

    def udesc(uid):
        u = s.users.get(uid) or {}
        return {"id": uid, "display_name": u.get("display_name") or u.get("username") or "Unknown",
                "exists": _user_exists(uid), "username": u.get("username") if s.main else None}

    return {
        "point": point_json(point),
        "users": [udesc(u) for u in owners] if (s.main or len(owners) > 1) else [udesc(u) for u in owners],
        "folders": [{"id": f, "name": s.folders[f]["name"], "parent_id": s.folders[f]["parent_id"],
                     "owner_id": s.folders[f]["owner_id"], "exists": f in s.current_folders,
                     "path": s.path(f)} for f in sorted(folder_ids, key=lambda x: s.path(x))],
        "documents": [doc_json(s, d) for d in sorted(docs, key=lambda x: (s.path(s.docs[x]["folder_id"]), s.docs[x]["title"]))[:500]],
        "total": len(docs),
    }


def _user_exists(uid) -> bool:
    from apps.accounts.models import User

    return User.objects.filter(pk=uid).exists()


def doc_json(s: Scope, did: str) -> dict:
    d = s.docs[did]
    cur = s.current_docs.get(did)
    current_shas = set(cur.versions.values_list("sha256", flat=True)) if cur else set()
    return {"id": did, "title": d["title"], "folder_id": d["folder_id"], "folder_path": s.path(d["folder_id"]),
            "owner_id": d["owner_id"], "owner": (s.users.get(d["owner_id"]) or {}).get("display_name", ""),
            "expiry_date": d.get("expiry_date"), "issue_date": d.get("issue_date"), "doc_type_id": d.get("doc_type_id"),
            "archived": bool(d.get("archived_at")), "exists": cur is not None,
            "current_newer": bool(cur and cur.updated_at.isoformat() > str(d.get("updated_at"))),
            "versions": [{"id": v["id"], "number": v["number"], "original_name": v["original_name"], "size": v["size"],
                          "mime": v["mime"], "created_at": v["created_at"], "is_current": v["id"] == d.get("current_version_id"),
                          "in_current": v["sha256"] in current_shas, "ocr": bool(v.get("text")), "comment": v.get("comment", ""),
                          "av_status": v.get("av_status")}
                         for v in s.versions.get(did, [])]}


def point_json(p: RecoveryPoint) -> dict:
    return {"id": str(p.id), "kind": p.kind, "trigger": p.trigger, "status": p.status, "created_at": p.created_at.isoformat(),
            "key_generation": p.key_generation, "size_bytes": p.size_bytes, "counts": p.counts, "parent": str(p.parent_id) if p.parent_id else None,
            "base": str(p.base_id) if p.base_id else None, "app_version": p.app_version}


def compare(user, point: RecoveryPoint, doc_id: str) -> dict:
    """Backup vs current details of one document (version comparison)."""
    data = load(point)
    s = Scope(user, data)
    if doc_id not in s.docs or not s.can_doc(doc_id):
        raise RestoreError("Not found.")
    d = s.docs[doc_id]
    cur = s.current_docs.get(doc_id)
    fields_b = {f["key"]: f["value"] for f in data["catalog"]["fields"] if f["document_id"] == doc_id}
    rows = []
    if cur is not None:
        from apps.library.models import DocumentField

        fields_c = dict(DocumentField.objects.filter(document=cur).values_list("key", "value"))
        for label, b, c in (("Title", d["title"], cur.title), ("Expiry date", d.get("expiry_date"), cur.expiry_date and cur.expiry_date.isoformat()),
                            ("Issue date", d.get("issue_date"), cur.issue_date and cur.issue_date.isoformat()),
                            ("Versions", len(s.versions.get(doc_id, [])), cur.versions.count())):
            rows.append({"label": label, "backup": b, "current": c, "same": str(b or "") == str(c or "")})
        for k in sorted(set(fields_b) | set(fields_c)):
            rows.append({"label": k, "backup": fields_b.get(k), "current": fields_c.get(k), "same": fields_b.get(k) == fields_c.get(k)})
    return {"document": doc_json(s, doc_id), "rows": rows, "current_exists": cur is not None}


# ------------------------------------------------------------------ planning and execution

class Plan:
    """Walks a restore target. With ``execute=False`` it only records the impact analysis."""

    def __init__(self, user, point: RecoveryPoint, *, mode: str, execute: bool, user_option: str = "", transfer_to=None,
                 target_folder=None):
        if mode not in MODES:
            raise RestoreError("Choose Keep current + restore as new version, Replace current version, or Skip existing.")
        self.user, self.point, self.mode, self.execute = user, point, mode, execute
        self.data = load(point)
        self.s = Scope(user, self.data)
        self.user_option, self.transfer_to, self.target_folder = user_option, transfer_to, target_folder
        self.folder_map: dict[str, object] = {}
        self.counts = {"folders_create": 0, "folders_existing": 0, "documents_create": 0, "documents_existing": 0,
                       "versions_restore": 0, "skipped": 0}
        self.conflicts, self.newer, self.perm_diff, self.actions, self.replaces, self.warnings = [], [], [], [], [], []
        self.failed: list[dict] = []
        self.bytes = 0
        self.created: list[dict] = []
        self.work = Path(settings.DATA_DIR) / "backup-staging" / f"restore-{uuid.uuid4().hex[:10]}"

    # ---- folders
    def folder_for(self, fid: str):
        """Existing folder, mapped folder, or (re)create it under its parent."""
        from apps.library.models import Folder

        if fid in self.folder_map:
            return self.folder_map[fid]
        cur = self.s.current_folders.get(fid)
        if cur is not None and cur.archived_at is None and not self.user_option:
            self.folder_map[fid] = cur
            self.counts["folders_existing"] += 1
            return cur
        f = self.s.folders[fid]
        parent = None
        if f["parent_id"] and f["parent_id"] in self.s.folders and f["parent_id"] not in getattr(self, "_roots", set()):
            parent = self.folder_for(f["parent_id"])
        elif self.target_folder is not None:
            parent = self.target_folder
        name = f["name"]
        self.counts["folders_create"] += 1
        self.actions.append(f"Re-create folder “{' / '.join(self.s.path(fid))}”")
        if not self.execute:
            self.folder_map[fid] = ("planned", fid)
            return self.folder_map[fid]
        from apps.library import services

        if isinstance(parent, tuple):
            parent = None
        owner = self._owner(f["owner_id"])
        if parent is None and f.get("kind") == Folder.PERSONAL_ROOT:
            existing_root = Folder.objects.filter(owner=owner, kind=Folder.PERSONAL_ROOT).first()
            if existing_root:
                self.folder_map[fid] = existing_root
                return existing_root
        base = name
        n = 2
        while Folder.objects.filter(parent=parent, name=name, archived_at__isnull=True).exists():
            name = f"{base} (restored{'' if n == 2 else ' ' + str(n - 1)})"
            n += 1
        new = services.create_folder(actor=self.user, parent=parent, name=name, owner=owner,
                                     kind=Folder.NORMAL if parent is not None else (f.get("kind") or Folder.NORMAL))
        self._rules(new, folder_id=fid)
        self.folder_map[fid] = new
        return new

    def _owner(self, uid):
        from apps.accounts.models import User

        if self.transfer_to is not None:
            return self.transfer_to
        if getattr(self, "recreated_user", None) is not None and str(self.recreated_user.pk) == uid:
            return self.recreated_user
        u = User.objects.filter(pk=uid, is_active=True).first()
        return u or self.user

    def _rules(self, obj, *, folder_id=None, document_id=None):
        """Access rules of re-created items, for people and groups that still exist."""
        from apps.accounts.models import FamilyGroup, User
        from apps.library.models import AccessRule

        for r in self.data["catalog"]["rules"]:
            if (folder_id and r["folder_id"] == folder_id) or (document_id and r["document_id"] == document_id):
                u = User.objects.filter(pk=r["user_id"]).first() if r["user_id"] else None
                g = FamilyGroup.objects.filter(pk=r["group_id"]).first() if r["group_id"] else None
                if u is None and g is None:
                    self.warnings.append("An access rule for a person or group that no longer exists was not restored.")
                    continue
                AccessRule.objects.create(folder=obj if folder_id else None, document=obj if document_id else None,
                                          user=u, group=g, caps=r["caps"], created_by=self.user)

    # ---- permission differences for existing items
    def note_perm_diff(self, folder_id: str):
        from apps.library.models import AccessRule

        cur = self.s.current_folders.get(folder_id)
        if cur is None:
            return
        backup = {(r["user_id"], r["group_id"], r["caps"]) for r in self.data["catalog"]["rules"] if r["folder_id"] == folder_id}
        now = {(str(u) if u else None, str(g) if g else None, c) for u, g, c in AccessRule.objects.filter(folder=cur).values_list("user_id", "group_id", "caps")}
        if backup != now:
            self.perm_diff.append({"folder": " / ".join(self.s.path(folder_id)),
                                   "only_in_backup": len(backup - now), "only_now": len(now - backup),
                                   "note": "Current permissions are kept; the backup's rules are not re-applied to existing folders."})

    # ---- documents
    def document(self, did: str, version_ids: list[str] | None = None):
        s = self.s
        if not s.can_doc(did):
            self.warnings.append("A document you are not allowed to restore was left out.")
            return
        d = s.docs[did]
        versions = [v for v in s.versions.get(did, []) if version_ids is None or v["id"] in version_ids]
        versions = [v for v in versions if v.get("av_status") != "quarantined"]
        if not versions:
            return
        cur = s.current_docs.get(did) if not self.user_option else None
        if cur is not None and cur.archived_at is None:
            self.counts["documents_existing"] += 1
            cur_shas = set(cur.versions.values_list("sha256", flat=True))
            if cur.updated_at.isoformat() > str(d.get("updated_at")):
                self.newer.append({"document": d["title"], "current_updated": cur.updated_at.isoformat(), "backup_updated": d.get("updated_at")})
            if self.mode == "skip":
                self.counts["skipped"] += 1
                self.actions.append(f"Skip “{d['title']}” (exists)")
                return
            wanted = [v for v in versions if v["sha256"] not in cur_shas] if self.mode == "keep_new" else versions
            cur_sha = cur.current_version.sha256 if cur.current_version_id else None
            if cur_sha and any(v["sha256"] != cur_sha for v in versions):
                self.conflicts.append({"document": d["title"], "reason": "The current file differs from the backup."})
            if self.mode == "replace":
                target_v = next((v for v in versions if v["id"] == d.get("current_version_id")), versions[-1])
                if target_v["sha256"] != cur_sha:
                    self.replaces.append(d["title"])
                    self.actions.append(f"Make restored version {target_v['number']} the current version of “{d['title']}” "
                                        "(the present version stays in the history)")
                wanted = [target_v] if target_v["sha256"] not in cur_shas else []
                if self.execute:
                    self._run(lambda: self._replace(cur, d, target_v, wanted), d["title"])
                self.counts["versions_restore"] += len(wanted)
                self.bytes += sum(v["size"] for v in wanted)
                return
            if not wanted:
                self.actions.append(f"“{d['title']}”: the selected versions are already present")
                return
            self.actions.append(f"Add {len(wanted)} restored version(s) to “{d['title']}” (current version unchanged)")
            self.counts["versions_restore"] += len(wanted)
            self.bytes += sum(v["size"] for v in wanted)
            if self.execute:
                self._run(lambda: self._add_versions(cur, wanted, keep_current=True), d["title"])
            return
        # missing (deleted, permanently purged) or archived: re-create
        self.counts["documents_create"] += 1
        self.counts["versions_restore"] += len(versions)
        self.bytes += sum(v["size"] for v in versions)
        self.actions.append(f"Re-create “{d['title']}” with {len(versions)} version(s)")
        self.note_perm_diff(d["folder_id"])
        if self.execute:
            self._run(lambda: self._recreate(d, versions), d["title"])

    def _run(self, fn, title):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - one item failing never aborts the others; it is reported
            log.exception("restore item failed")
            self.failed.append({"item": title, "error": str(exc)[:200]})

    def _stage(self, v):
        from apps.library import storage

        self.work.mkdir(parents=True, exist_ok=True)
        tmp = self.work / v["id"]
        fetch_object(self.point, self.data, f"objects/{v['id']}", tmp)
        staged = storage.stage_local_file(tmp, v["original_name"])
        tmp.unlink(missing_ok=True)
        return staged

    def _comment(self, v):
        return f"Restored from backup of {self.point.created_at:%Y-%m-%d %H:%M} UTC (version {v['number']})"[:255]

    def _apply_ocr(self, version, v):
        from apps.library.models import DocumentVersion

        DocumentVersion.objects.filter(pk=version.pk).update(
            text=v.get("text") or "", ocr_quality=v.get("ocr_quality") or {}, ocr_engine=v.get("ocr_engine") or "",
            ocr_model=v.get("ocr_model") or "", ocr_blocks=v.get("ocr_blocks") or [], ocr_pages=v.get("ocr_pages") or "",
            ocr_applied=bool(v.get("ocr_applied")))

    def _add_versions(self, cur, wanted, keep_current: bool):
        from apps.library import services

        prev = cur.current_version
        for v in wanted:
            nv = services.add_version(actor=self.user, doc=cur, staged=self._stage(v), comment=self._comment(v))
            self._apply_ocr(nv, v)
            self.created.append({"document": str(cur.id), "version": str(nv.id)})
        if keep_current and prev is not None:  # the restored versions join the history; the current file stays current
            cur.refresh_from_db()
            services.set_current_version(actor=self.user, doc=cur, version=prev)

    def _replace(self, cur, d, target_v, wanted):
        from apps.library import services
        from apps.library.models import DocumentVersion

        if wanted:
            nv = services.add_version(actor=self.user, doc=cur, staged=self._stage(target_v), comment=self._comment(target_v))
            self._apply_ocr(nv, target_v)
            self.created.append({"document": str(cur.id), "version": str(nv.id)})
        else:
            existing = DocumentVersion.objects.filter(document=cur, sha256=target_v["sha256"]).order_by("-number").first()
            if existing and cur.current_version_id != existing.id:
                services.set_current_version(actor=self.user, doc=cur, version=existing)
        self._metadata(cur, d)

    def _metadata(self, doc, d):
        from apps.library.models import DocumentField, DocumentType

        doc.refresh_from_db()
        doc.title = d["title"]
        doc.title_is_custom = d.get("title_is_custom", False)
        doc.issue_date = d.get("issue_date") or None
        doc.expiry_date = d.get("expiry_date") or None
        doc.no_expiry = bool(d.get("no_expiry"))
        if d.get("doc_type_id") and DocumentType.objects.filter(pk=d["doc_type_id"]).exists():
            doc.doc_type_id = d["doc_type_id"]
        doc.save()
        for f in self.data["catalog"]["fields"]:
            if f["document_id"] == d["id"]:
                DocumentField.objects.update_or_create(document=doc, key=f["key"], defaults={
                    "value": f.get("value") or "", "label": f.get("label") or "", "status": f.get("status") or "confirmed",
                    "source": "manual"})
        from apps.library.models import Tag

        tags = list(Tag.objects.filter(pk__in=d.get("tags") or []))
        if tags:
            doc.tags.add(*tags)

    def _recreate(self, d, versions):
        from apps.library import services
        from apps.library.models import Document

        folder = self.folder_for(d["folder_id"]) if d["folder_id"] in self.s.folders else self.target_folder
        if folder is None or isinstance(folder, tuple):
            raise RestoreError("No folder to restore into.")
        owner = self._owner(d["owner_id"])
        first, rest = versions[0], versions[1:]
        with transaction.atomic():
            doc = services.create_document(actor=self.user, folder=folder, owner=owner, staged=self._stage(first),
                                           title=d["title"], inherit=d.get("inherit_permissions", True))
            self._apply_ocr(doc.current_version, first)
            version_ids = {first["id"]: doc.current_version}
            for v in rest:
                nv = services.add_version(actor=self.user, doc=doc, staged=self._stage(v), comment=v.get("comment") or "",
                                          additional=bool(v.get("is_additional")))
                self._apply_ocr(nv, v)
                version_ids[v["id"]] = nv
            target = version_ids.get(d.get("current_version_id"))
            doc = Document.objects.get(pk=doc.pk)
            if target is not None and doc.current_version_id != target.id:
                services.set_current_version(actor=self.user, doc=doc, version=target)
            self._metadata(doc, d)
            self._rules(doc, document_id=d["id"])
        self.created.append({"document": str(doc.id), "restored_from": d["id"]})

    # ---- targets
    def folder_tree(self, fid: str):
        s = self.s
        if fid not in s.folders:
            raise RestoreError("Folder not found in this recovery point.")
        sub = set(s.subtree(fid))
        for f in sorted(sub, key=lambda x: len(s.path(x))):
            if s.main or any(s.docs[d]["folder_id"] == f and s.can_doc(d) for d in s.docs):
                self.folder_for(f)
        for d in sorted(s.docs, key=lambda x: s.docs[x]["title"]):
            if s.docs[d]["folder_id"] in sub:
                self.document(d)

    def user_scope(self, uid: str):
        s = self.s
        if uid not in s.users:
            raise RestoreError("This person is not in the recovery point.")
        if not s.main and uid != str(self.user.pk):
            raise RestoreError("Only the main administrator can restore another person's data.")
        exists = _user_exists(uid)
        if not exists:
            if not s.main:
                raise RestoreError("Only the main administrator can recover data of a deleted account.")
            if self.user_option not in ("recreate", "transfer", "staging"):
                raise RestoreError("The account no longer exists: choose Re-create account, Restore to another person, "
                                   "or Recovery staging area.")
            self._prepare_orphan(uid)
        elif self.user_option:
            self.user_option = ""
        roots = [f["id"] for f in s.folders.values() if f["owner_id"] == uid and (f["parent_id"] is None or
                                                                                  s.folders.get(f["parent_id"], {}).get("owner_id") != uid)]
        self._roots = set()
        if self.user_option in ("transfer", "staging"):
            self._roots = {s.folders[r]["parent_id"] for r in roots if s.folders[r]["parent_id"]}
        for r in roots:
            self.folder_tree(r)
        for d, doc in s.docs.items():  # documents of this person in other people's folders
            if doc["owner_id"] == uid and not any(doc["folder_id"] in s.subtree(r) for r in roots):
                self.document(d)

    def _prepare_orphan(self, uid: str):
        from apps.accounts.models import User
        from apps.library import services
        from apps.library.models import Folder

        u = self.s.users[uid]
        label = u.get("display_name") or u.get("username")
        stamp = f"{self.point.created_at:%Y-%m-%d}"
        if self.user_option == "recreate":
            if User.objects.filter(username=u["username"]).exists():
                raise RestoreError(f"The username {u['username']} is taken. Choose another option.")
            self.actions.append(f"Re-create the account {u['username']} (new password required; no old sessions, passkeys "
                                "or two-step settings are restored)")
            if self.execute:
                nu = User(id=uid, username=u["username"], display_name=u.get("display_name") or u["username"],
                          full_name=u.get("full_name") or "", role_label=u.get("role_label") or "", email=u.get("email") or "",
                          must_change_password=True, is_active=True)
                nu.set_unusable_password()
                nu.save()
                self.recreated_user = nu
                audit.record("recovery.user_recreated", actor=self.user, subject_user=nu)
            return
        if self.user_option == "transfer":
            if self.transfer_to is None:
                raise RestoreError("Choose the person who receives the recovered data.")
            self.actions.append(f"Restore into “Recovered from {label} ({stamp})” in {self.transfer_to.display_name}'s library")
            if self.execute:
                root = Folder.objects.filter(owner=self.transfer_to, kind=Folder.PERSONAL_ROOT).first()
                self.target_folder = services.create_folder(actor=self.user, parent=root, name=f"Recovered from {label} ({stamp})",
                                                            owner=self.transfer_to)
            return
        # staging: a restricted folder owned by the main administrator
        self.actions.append(f"Restore into the Recovery staging area (main administrator only): “{label} ({stamp})”")
        if self.execute:
            staging = Folder.objects.filter(name="Recovery staging", parent=None, owner=self.user, archived_at__isnull=True).first()
            if staging is None:
                staging = services.create_folder(actor=self.user, parent=None, name="Recovery staging", owner=self.user)
                Folder.objects.filter(pk=staging.pk).update(inherit_permissions=False)
            self.target_folder = services.create_folder(actor=self.user, parent=staging, name=f"{label} ({stamp})"[:200], owner=self.user)
            self.transfer_to = self.user

    def report(self) -> dict:
        from apps.library import storage

        free = storage.disk_free_bytes()
        return {"point": point_json(self.point), "mode": self.mode, "counts": self.counts, "conflicts": self.conflicts[:100],
                "newer_current": self.newer[:100], "permission_differences": self.perm_diff[:50],
                "storage": {"bytes_needed": self.bytes, "free_bytes": free, "ok": free is None or free > self.bytes * 2},
                "actions": self.actions[:300], "replaces_current": self.replaces[:100], "deletes": [],
                "deletion_note": "No current data is deleted by any restore mode.", "warnings": sorted(set(self.warnings))[:20]}


def run(user, point: RecoveryPoint, *, kind: str, target: dict, mode: str = "keep_new", execute: bool = False,
        request=None) -> RestoreRun:
    """Impact analysis (execute=False) or the restore itself. Every restore is audited and notified."""
    from apps.accounts.models import User
    from apps.library.models import Folder

    if kind not in ("version", "document", "folder", "user"):
        raise RestoreError("Unknown restore type.")
    transfer_to = None
    if target.get("transfer_to"):
        transfer_to = User.objects.filter(pk=target["transfer_to"], is_active=True).first()
    tfolder = Folder.objects.filter(pk=target["target_folder"]).first() if target.get("target_folder") else None
    plan = Plan(user, point, mode=mode, execute=execute, user_option=target.get("user_option", ""), transfer_to=transfer_to,
                target_folder=tfolder)
    if kind in ("version", "document"):
        did = target.get("document")
        if did not in plan.s.docs:
            raise RestoreError("Document not found in this recovery point.")
        plan.document(did, [target["version"]] if kind == "version" else None)
    elif kind == "folder":
        plan.folder_tree(target.get("folder", ""))
    else:
        plan.user_scope(target.get("user", ""))
    impact = plan.report()
    rr = RestoreRun.objects.create(kind=kind, mode=mode, point=point, point_label=f"{point.kind} {point.created_at:%Y-%m-%d %H:%M}",
                                   target={k: v for k, v in target.items() if k in ("document", "version", "folder", "user",
                                                                                    "user_option", "transfer_to")},
                                   status="analyzed" if not execute else "running", impact=impact, actor=user,
                                   actor_label=user.username)
    if not execute:
        return rr
    from apps.notify import events

    rr.status = "completed" if not plan.failed else ("partial" if plan.created else "failed")
    rr.result = {"created": plan.created[:500], "failed": plan.failed, "counts": plan.counts}
    rr.finished_at = timezone.now()
    rr.save()
    shutil.rmtree(plan.work, ignore_errors=True)
    audit.record("recovery.restore", request=request, actor=user, outcome="success" if rr.status == "completed" else "failure",
                 target_type="recovery_point", target_id=str(point.id), restore_kind=kind, mode=mode, status=rr.status,
                 restored=len(plan.created), failed=len(plan.failed))
    detail = (f"{kind.title()} restore from the backup of {point.created_at:%Y-%m-%d %H:%M}: {rr.status}. "
              f"{plan.counts['documents_create']} re-created, {plan.counts['versions_restore']} version(s) restored"
              + (f", {len(plan.failed)} failed" if plan.failed else "") + ".")
    recipients = {user.pk: user}
    for admin in User.objects.filter(is_main_admin=True, is_active=True):
        recipients[admin.pk] = admin
    events.backup_event("recovery.restore", point=point, detail=detail, users=recipients.values(), actor=user,
                        severity="success" if rr.status == "completed" else "warning", tag=str(rr.id),
                        title=f"Restore {'completed' if rr.status == 'completed' else rr.status}")
    return rr


def my_recovery(user) -> dict:
    """Limited view for any person: no destinations, credentials, infrastructure or other people."""
    pts = restorable_points()
    latest = pts.first()
    protected = latest is not None
    return {"protected": protected,
            "latest_point": {"id": str(latest.id), "created_at": latest.created_at.isoformat(), "kind": latest.kind} if latest else None,
            "last_successful_backup": latest.created_at.isoformat() if latest else None,
            "points_available": pts.count(),
            "message": ("Your documents are protected by the family's encrypted backups." if protected else
                        "No verified backup exists yet. Ask the family administrator to set up Backup & Recovery.")}
