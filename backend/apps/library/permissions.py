"""Centralised access control.

Rules (deterministic, default deny):
1. The main administrator has every capability on everything, including archived items.
2. Effective capabilities on a folder = explicit rules on that folder for the user or any of the user's
   family groups, plus delegation-derived grants, plus — only if the folder inherits — the effective
   capabilities of its parent folder.
3. Effective capabilities on a document = explicit document rules, plus (if the document inherits) the
   effective capabilities of its folder.
4. Archived folders/documents are invisible to everyone except the main administrator.
5. Kinship, role labels, folder names, and reminder recipient status never grant access.

Every API endpoint, preview, thumbnail, text, search snippet, count, export and job uses this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q

VIEW = 1
DOWNLOAD = 2
UPLOAD = 4
EDIT = 8
VERSION = 16
ORGANIZE = 32
ARCHIVE = 64
SHARE = 128
MANAGE = 256
ALL = 511

CAP_NAMES = {
    "view": VIEW,
    "download": DOWNLOAD,
    "upload": UPLOAD,
    "edit": EDIT,
    "version": VERSION,
    "organize": ORGANIZE,
    "archive": ARCHIVE,
    "share": SHARE,
    "manage": MANAGE,
}
CAP_LABELS = {
    "view": "View and preview",
    "download": "Download, export and save offline",
    "upload": "Upload new documents",
    "edit": "Edit details and metadata",
    "version": "Upload new file versions",
    "organize": "Create, rename and move folders",
    "archive": "Archive (delete)",
    "share": "Create public share links",
    "manage": "Manage permissions",
}

# Capabilities granted to an owner on their personal root at setup (an explicit, visible rule).
OWNER_DEFAULT = VIEW | DOWNLOAD | UPLOAD | EDIT | VERSION | ORGANIZE | SHARE
# Delegation scopes -> capability on folders owned by members of the delegated group.
DELEGATION_CAPS = {
    "documents": VIEW | DOWNLOAD | UPLOAD | EDIT | VERSION | ORGANIZE,
    "folder_permissions": MANAGE,
}


def names(caps: int) -> list[str]:
    return [n for n, bit in CAP_NAMES.items() if caps & bit]


def from_names(values) -> int:
    caps = 0
    for v in values or []:
        if v not in CAP_NAMES:
            raise ValueError(f"unknown capability {v}")
        caps |= CAP_NAMES[v]
    # view is a prerequisite for every other capability
    if caps and not caps & VIEW:
        caps |= VIEW
    return caps


@dataclass
class _FolderNode:
    id: object
    parent_id: object
    inherit: bool
    archived: bool
    owner_id: object
    name: str


@dataclass
class AccessContext:
    """Per-request snapshot of the folder tree and the user's rules."""

    user: object
    folders: dict = field(default_factory=dict)
    folder_rules: dict = field(default_factory=dict)  # folder_id -> [(caps, source)]
    doc_rules: dict = field(default_factory=dict)  # document_id -> [(caps, source)]
    delegated_owner_caps: dict = field(default_factory=dict)  # owner_id -> [(caps, source)]
    _cache: dict = field(default_factory=dict)

    @property
    def is_admin(self) -> bool:
        return bool(getattr(self.user, "is_main_admin", False))

    @classmethod
    def build(cls, user) -> "AccessContext":
        from apps.accounts.models import Delegation, GroupMembership

        from .models import AccessRule, Folder

        ctx = cls(user=user)
        if not (user and user.is_authenticated and user.is_active):
            return ctx
        for f in Folder.objects.values("id", "parent_id", "inherit_permissions", "archived_at", "owner_id", "name"):
            ctx.folders[f["id"]] = _FolderNode(f["id"], f["parent_id"], f["inherit_permissions"], f["archived_at"] is not None,
                                               f["owner_id"], f["name"])
        if ctx.is_admin:
            return ctx
        group_ids = list(GroupMembership.objects.filter(user=user).values_list("group_id", flat=True))
        rules = AccessRule.objects.filter(Q(user=user) | Q(group_id__in=group_ids)).select_related("group")
        for r in rules:
            source = f"group:{r.group.name}" if r.group_id else "user"
            entry = (r.caps, source, r.id)
            if r.folder_id:
                ctx.folder_rules.setdefault(r.folder_id, []).append(entry)
            else:
                ctx.doc_rules.setdefault(r.document_id, []).append(entry)
        for d in Delegation.objects.filter(delegate=user).select_related("group"):
            caps = 0
            for scope in d.scopes:
                caps |= DELEGATION_CAPS.get(scope, 0)
            if not caps:
                continue
            member_ids = GroupMembership.objects.filter(group=d.group).values_list("user_id", flat=True)
            for mid in member_ids:
                ctx.delegated_owner_caps.setdefault(mid, []).append((caps, f"delegation:{d.group.name}", None))
        return ctx

    # ---- folders
    def folder_caps(self, folder_id) -> int:
        if self.is_admin:
            return ALL
        key = ("f", folder_id)
        if key in self._cache:
            return self._cache[key]
        node = self.folders.get(folder_id)
        if node is None or self._archived_chain(folder_id):
            self._cache[key] = 0
            return 0
        caps = 0
        for c, _s, _id in self.folder_rules.get(folder_id, []):
            caps |= c
        # delegation grants apply to every folder owned by a member of the delegated group
        for c, _s, _id in self.delegated_owner_caps.get(node.owner_id, []) if node.owner_id is not None else []:
            caps |= c
        if node.inherit and node.parent_id is not None:
            caps |= self.folder_caps(node.parent_id)
        self._cache[key] = caps
        return caps

    def _archived_chain(self, folder_id) -> bool:
        seen = 0
        node = self.folders.get(folder_id)
        while node is not None and seen < 256:
            if node.archived:
                return True
            node = self.folders.get(node.parent_id)
            seen += 1
        return False

    def folder_ids_with(self, cap: int) -> set:
        return {fid for fid in self.folders if self.folder_caps(fid) & cap}

    # ---- documents
    def doc_caps(self, doc) -> int:
        if self.is_admin:
            return ALL
        if doc.archived_at is not None:
            return 0
        caps = 0
        for c, _s, _id in self.doc_rules.get(doc.id, []):
            caps |= c
        if doc.inherit_permissions:
            caps |= self.folder_caps(doc.folder_id)
        return caps

    def can(self, doc_or_folder, cap: int) -> bool:
        from .models import Folder

        if isinstance(doc_or_folder, Folder):
            return bool(self.folder_caps(doc_or_folder.id) & cap)
        return bool(self.doc_caps(doc_or_folder) & cap)

    def documents(self, cap: int = VIEW, include_archived: bool = False):
        """QuerySet of documents where the user holds `cap`."""
        from .models import Document

        qs = Document.objects.all()
        if self.is_admin:
            return qs if include_archived else qs.filter(archived_at__isnull=True)
        folder_ids = self.folder_ids_with(cap)
        doc_ids = [did for did, entries in self.doc_rules.items() if any(c & cap for c, _s, _i in entries)]
        return qs.filter(archived_at__isnull=True).filter(
            Q(folder_id__in=folder_ids, inherit_permissions=True) | Q(id__in=doc_ids)
        ).exclude(folder_id__in=[fid for fid in self.folders if self._archived_chain(fid)])

    # ---- explanation
    def explain_folder(self, folder_id) -> list[dict]:
        if self.is_admin:
            return [{"source": "main administrator", "caps": names(ALL), "at": None}]
        out = []
        chain = []
        node = self.folders.get(folder_id)
        while node is not None:
            chain.append(node)
            if not node.inherit:
                break
            node = self.folders.get(node.parent_id)
        for n in chain:
            for c, s, rid in self.folder_rules.get(n.id, []):
                out.append({"source": s, "caps": names(c), "at": n.name, "folder_id": str(n.id), "inherited": n.id != folder_id, "rule_id": rid})
            if n.owner_id in self.delegated_owner_caps:
                for c, s, _ in self.delegated_owner_caps[n.owner_id]:
                    out.append({"source": s, "caps": names(c), "at": n.name, "folder_id": str(n.id), "inherited": n.id != folder_id})
        if chain and not chain[-1].inherit and chain[-1].id != folder_id:
            out.append({"source": "inheritance stops", "caps": [], "at": chain[-1].name, "folder_id": str(chain[-1].id)})
        return out

    def explain_document(self, doc) -> list[dict]:
        if self.is_admin:
            return [{"source": "main administrator", "caps": names(ALL), "at": None}]
        out = [{"source": s, "caps": names(c), "at": "this document", "rule_id": rid}
               for c, s, rid in self.doc_rules.get(doc.id, [])]
        if doc.inherit_permissions:
            out += self.explain_folder(doc.folder_id)
        else:
            out.append({"source": "inheritance disabled on this document", "caps": [], "at": "this document"})
        return out


def context_for(request) -> AccessContext:
    ctx = getattr(request, "_pd_access", None)
    if ctx is None or ctx.user != request.user:
        ctx = AccessContext.build(request.user)
        request._pd_access = ctx
    return ctx


def users_with_view(doc) -> list:
    """All active users who can currently view a document (used to validate reminder recipients)."""
    from apps.accounts.models import User

    result = []
    for u in User.objects.filter(is_active=True):
        if AccessContext.build(u).can(doc, VIEW):
            result.append(u)
    return result


def folder_audience(folder_id) -> dict:
    """Everyone who reaches ``folder_id`` through rules on it or the ancestors it inherits from (the main
    administrator, who sees everything, is left out). Keys are ("user", id), ("group", id) and ("owner", id); the
    owner entry stands for delegations, which follow the folder owner."""
    from .models import AccessRule, Folder

    out: dict = {}
    fields = ("id", "parent_id", "inherit_permissions", "owner_id")
    node = Folder.objects.filter(pk=folder_id).values(*fields).first()
    for _ in range(256):
        if not node:
            break
        for r in AccessRule.objects.filter(folder_id=node["id"]).values("user_id", "group_id", "caps"):
            key = ("user", r["user_id"]) if r["user_id"] else ("group", r["group_id"])
            out[key] = out.get(key, 0) | r["caps"]
        if node["owner_id"]:
            out[("owner", node["owner_id"])] = ALL
        if not node["inherit_permissions"] or not node["parent_id"]:
            break
        node = Folder.objects.filter(pk=node["parent_id"]).values(*fields).first()
    return out


def move_widens_access(source_folder_id, dest_folder_id) -> bool:
    """True when inheriting from ``dest`` would give anyone a capability they do not have through ``source``."""
    if source_folder_id == dest_folder_id:
        return False
    source, dest = folder_audience(source_folder_id), folder_audience(dest_folder_id)
    return any(caps & ~source.get(key, 0) for key, caps in dest.items())
