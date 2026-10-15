"""Full-system encrypted recovery points: creation, replication, deep verification, retention (Change Set T).

A recovery point is an *application-complete recovery package* (not an OS or Proxmox image):

    <destination>/<point id>/g<key generation>/
        header.json        plain: identity, chain, key generation, wrapped data key, file list with cipher checksums
        manifest.enc       inventory of every recovery class, object locations in the chain, counts, compatibility
        database.enc       pg_dump (custom format, no compression) streamed straight into the encryption
        catalog.enc        browsable catalogue for the Recovery Explorer (users, groups, folders, documents, versions,
                           metadata, access rules) - no passwords, sessions or authentication secrets
        settings.enc       global settings and per-person preferences (non-secret values)
        secrets.enc        installation encryption key, Django secret key, WhatsApp linked-device session files
        objects/<version>  original files of document versions (incrementals store only new ones)
        derived/<hash>     previews, searchable PDFs, thumbnails; photos/<hash>, branding/<hash>

Nothing is compressed before encryption. Incrementals reference unchanged objects in earlier points of the same
chain; the database is captured completely in every point, so any point restores to an exact database state.
Points are assembled once in a local staging folder and copied to each destination independently; a failed
destination is retried from staging without re-creating the logical backup.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import shutil
import subprocess
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.core import audit, config

from . import bk_crypto as C
from . import bk_keys
from .bk_destinations import DestError, iter_stream, provider
from .models import BackupDestination, BackupPolicy, RecoveryCopy, RecoveryKey, RecoveryPoint

log = logging.getLogger("personaldocs.backup")
FORMAT = "pdbk-2"
COMPONENTS = ("manifest.enc", "database.enc", "catalog.enc", "settings.enc", "secrets.enc")
LOCK_ID = 0x50444B42  # "PDKB": one backup/rotation at a time across workers
RETRY_HOURS = 24


class BackupError(Exception):
    pass


# ------------------------------------------------------------------ helpers

def staging_root() -> Path:
    return Path(settings.DATA_DIR) / "backup-staging"


def point_dir(point_id, generation: int) -> Path:
    return staging_root() / str(point_id) / f"g{generation}"


def rel(point_id, generation: int, name: str) -> str:
    return f"{point_id}/g{generation}/{name}"


def _hash_name(prefix: str, value: str) -> str:
    return f"{prefix}/{hashlib.sha256(value.encode()).hexdigest()[:40]}"


def schema_state() -> dict:
    with connection.cursor() as cur:
        cur.execute("SELECT app, max(name) FROM django_migrations GROUP BY app")
        return {a: n for a, n in cur.fetchall()}


def _pg_env() -> dict:
    db = settings.DATABASES["default"]
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PGPASSWORD": db.get("PASSWORD") or "", "PGHOST": db.get("HOST") or "",
            "PGPORT": str(db.get("PORT") or "5432"), "PGUSER": db.get("USER") or "", "PGDATABASE": db.get("NAME")}


def _lower_priority():  # pragma: no cover - runs in the child process
    try:
        os.nice(10)
    except OSError:
        pass


class _Lock:
    def __enter__(self):
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
            if not cur.fetchone()[0]:
                raise BackupError("Another backup or key rotation is running. Try again when it has finished.")
        return self

    def __exit__(self, *exc):
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])


def default_policy() -> BackupPolicy | None:
    return BackupPolicy.objects.filter(enabled=True).order_by("id").first() or BackupPolicy.objects.order_by("id").first()


def configured() -> bool:
    return BackupPolicy.objects.filter(enabled=True, destinations__enabled=True).exists()


# ------------------------------------------------------------------ catalogue (Recovery Explorer data)

def _rows(qs, fields):
    return [{f: (str(v) if isinstance(v, uuid.UUID) else v) for f, v in r.items()} for r in qs.values(*fields)]


def build_catalog() -> dict:
    from apps.accounts.models import FamilyGroup, GroupMembership, User
    from apps.library.models import AccessRule, Document, DocumentField, DocumentType, DocumentVersion, Folder, Tag

    docs = list(Document.objects.values("id", "folder_id", "owner_id", "title", "title_is_custom", "doc_type_id", "issue_date",
                                        "expiry_date", "no_expiry", "current_version_id", "inherit_permissions", "archived_at",
                                        "created_at", "updated_at", "ocr_state", "content_text"))
    tag_map: dict[str, list] = {}
    for d_id, t_id in Document.tags.through.objects.values_list("document_id", "tag_id"):
        tag_map.setdefault(str(d_id), []).append(t_id)
    for d in docs:
        d["tags"] = tag_map.get(str(d["id"]), [])
    return {
        "users": _rows(User.objects.all(), ["id", "username", "display_name", "full_name", "role_label", "is_active", "is_main_admin",
                                            "is_admin", "email", "date_joined"]),
        "groups": _rows(FamilyGroup.objects.all(), ["id", "name"]),
        "memberships": _rows(GroupMembership.objects.all(), ["group_id", "user_id"]),
        "folders": _rows(Folder.objects.all(), ["id", "parent_id", "name", "owner_id", "emoji", "kind", "inherit_permissions",
                                               "archived_at", "created_at"]),
        "documents": [{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in d.items()} for d in docs],
        "versions": _rows(DocumentVersion.objects.all(), ["id", "document_id", "number", "original_name", "size", "sha256", "mime",
                                                         "format_class", "comment", "text", "page_count", "ocr_applied", "ocr_quality",
                                                         "ocr_engine", "ocr_model", "ocr_blocks", "ocr_pages", "is_additional",
                                                         "created_at", "av_status", "created_by_id"]),
        "fields": _rows(DocumentField.objects.all(), ["document_id", "key", "label", "value", "status", "source", "confirmed_at"]),
        "rules": _rows(AccessRule.objects.all(), ["folder_id", "document_id", "user_id", "group_id", "caps"]),
        "doc_types": _rows(DocumentType.objects.all(), ["id", "name"]),
        "tags": _rows(Tag.objects.all(), ["id", "name"]),
    }


def _user_settings() -> list:
    from apps.core.models import UserSetting

    return [{"user_id": str(u), "key": k, "value": v} for u, k, v in UserSetting.objects.values_list("user_id", "key", "value")]


def _secret_files() -> dict:
    from apps.core import crypto

    out = {}
    for name, path in (("encryption.key", crypto.key_path()), ("secret_key", Path(settings.CONFIG_DIR) / "secret_key")):
        if path.exists():
            out[name] = base64.b64encode(path.read_bytes()).decode()
    wa = Path(settings.DATA_DIR) / "whatsapp" / "sessions"
    if wa.is_dir():
        for f in sorted(wa.rglob("*")):
            if f.is_file() and f.stat().st_size < 5 * 1024 * 1024:
                out[f"whatsapp/{f.relative_to(wa)}"] = base64.b64encode(f.read_bytes()).decode()
    return out


# ------------------------------------------------------------------ creation

class _Builder:
    def __init__(self, point: RecoveryPoint, dek: bytes):
        self.point = point
        self.dek = dek
        self.dir = point_dir(point.id, point.key_generation)
        self.files: dict[str, dict] = {}
        self.stored: dict[str, str] = {}
        self.warnings: list[str] = []

    def _record(self, name: str, out_path: Path):
        h = hashlib.sha256()
        with open(out_path, "rb") as fh:
            for b in iter_stream(fh):
                h.update(b)
        self.files[name] = {"cipher_sha256": h.hexdigest(), "cipher_size": out_path.stat().st_size}

    def add_file(self, name: str, src: Path, expected_sha: str | None = None) -> str:
        dst = self.dir / name
        _n, sha, _c = C.encrypt_file(src, dst, self.dek, name)
        if expected_sha and sha != expected_sha:
            self.warnings.append(f"{name}: the original on disk does not match its recorded checksum")
        self._record(name, dst)
        self.stored[name] = sha
        return sha

    def add_bytes(self, name: str, data: bytes) -> str:
        dst = self.dir / name
        _n, sha, _c = C.encrypt_bytes_to(data, dst, self.dek, name)
        self._record(name, dst)
        return sha

    def add_command(self, name: str, cmd: list[str]) -> str:
        """Stream a command's output (pg_dump) straight into the encrypted file: no plain-text dump on disk."""
        dst = self.dir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_pg_env(), preexec_fn=_lower_priority)
        try:
            with open(dst, "wb") as out:
                _n, sha, _c = C.encrypt_stream(iter_stream(proc.stdout), out, C.file_key(self.dek, name), name.encode())
            err = proc.stderr.read().decode(errors="replace")
            if proc.wait(timeout=7200) != 0:
                raise BackupError(f"Database dump failed: {err[-300:]}")
        finally:
            if proc.poll() is None:
                proc.kill()
        self._record(name, dst)
        return sha


def _chain_inventory(parent: RecoveryPoint | None) -> dict[str, tuple[str, str]]:
    """name -> (sha, point id) for objects stored earlier in the chain."""
    out: dict[str, tuple[str, str]] = {}
    if parent is None:
        return out
    for p in parent.chain():
        for name, sha in (p.stored or {}).items():
            out[name] = (sha, str(p.id))
    return out


def _incremental_parent(policy: BackupPolicy | None) -> RecoveryPoint | None:
    qs = RecoveryPoint.objects.filter(deleted_at__isnull=True, status__in=[RecoveryPoint.VERIFIED, RecoveryPoint.PARTIAL,
                                                                          RecoveryPoint.WARNING])
    qs = qs.filter(policy=policy) if policy else qs
    last = qs.order_by("-created_at").first()
    if last is None:
        return None
    key = bk_keys.active()
    if key is None or last.key_generation != key.generation:
        return None  # a new key generation starts a new chain
    if any(p.status not in (RecoveryPoint.VERIFIED, RecoveryPoint.PARTIAL, RecoveryPoint.WARNING) or p.deleted_at for p in last.chain()):
        return None
    return last


def create_point(policy: BackupPolicy | None = None, *, kind: str = RecoveryPoint.FULL, trigger: str = "scheduled",
                 actor=None, reason: str = "", request=None, destinations=None, standalone: bool = False,
                 progress=None) -> RecoveryPoint:
    """Build, replicate and deep-verify one recovery point. Never raises for destination failures (they are copy
    states); raises BackupError when the point cannot be built at all.

    ``standalone`` (destination Backup Now): a Full point outside every policy, so it never becomes the base of
    another destination's incremental chain and retention never removes it automatically.
    ``progress(stage)`` reports preparing / backing_up / verifying for the job list."""
    report = progress or (lambda stage: None)
    policy = None if standalone else (policy or default_policy())
    if standalone:
        kind = RecoveryPoint.FULL
    dests = list(destinations if destinations is not None else (policy.destinations.filter(enabled=True) if policy else []))
    if not dests:
        raise BackupError("No backup destination is configured (Settings → Backup & Recovery → Destinations).")
    with _Lock():
        report("preparing")
        key = bk_keys.ensure_active()
        parent = _incremental_parent(policy) if kind == RecoveryPoint.INCREMENTAL else None
        if kind == RecoveryPoint.INCREMENTAL and parent is None:
            kind = RecoveryPoint.FULL  # no usable chain: start one
        point = RecoveryPoint.objects.create(policy=policy, kind=kind, trigger=trigger, reason=reason[:200],
                                             parent=parent, base=(parent.base or parent) if parent else None,
                                             key_generation=key.generation, app_version=settings.APP_VERSION,
                                             schema=schema_state(), created_by=actor)
        try:
            report("backing_up")
            _build(point, key, parent)
        except Exception as exc:
            point.status, point.error, point.finished_at = RecoveryPoint.FAILED, str(exc)[:500], timezone.now()
            point.save(update_fields=["status", "error", "finished_at"])
            shutil.rmtree(staging_root() / str(point.id), ignore_errors=True)
            audit.record("backup.run", request=request, actor=actor, outcome="failure", reason=str(exc)[:200],
                         target_type="recovery_point", target_id=str(point.id))
            _notify("backup.failed", point, detail=str(exc)[:300])
            raise BackupError(str(exc)) from exc
        for dest in dests:
            replicate(point, dest, progress=report)
        rollup(point)
        cleanup_staging(point)
        if policy:
            field = "last_full_at" if kind == RecoveryPoint.FULL else "last_incremental_at"
            BackupPolicy.objects.filter(pk=policy.pk).update(**{field: point.created_at})
    audit.record("backup.run", request=request, actor=actor, outcome="success" if point.status != RecoveryPoint.FAILED else "failure",
                 target_type="recovery_point", target_id=str(point.id), backup_kind=kind, trigger=trigger, status=point.status,
                 copies={c.destination.name: c.state for c in point.copies.select_related("destination")})
    _notify_result(point)
    if policy and trigger == "scheduled":
        try:
            apply_retention(policy)
        except Exception:  # noqa: BLE001 - retention problems are reported, they never fail a backup
            log.exception("retention failed")
    return point


def _build(point: RecoveryPoint, key: RecoveryKey, parent: RecoveryPoint | None) -> None:
    from apps.accounts.models import User
    from apps.accounts.photos import photo_dir
    from apps.core.branding import branding_dir
    from apps.library.models import DocumentVersion

    raw = bk_keys.raw_key(key.generation)
    dek = secrets.token_bytes(32)
    b = _Builder(point, dek)
    shutil.rmtree(b.dir, ignore_errors=True)
    b.dir.mkdir(parents=True)
    os.chmod(staging_root(), 0o700)
    chain = _chain_inventory(parent)
    inventory: dict[str, dict] = {}

    def ref(name: str, src: Path, expected: str | None, meta: dict):
        prior = chain.get(name)
        if prior and (expected is None or prior[0] == expected):
            inventory[name] = {**meta, "sha256": prior[0], "stored_in": prior[1]}
            return
        if not src.exists():
            b.warnings.append(f"{meta.get('label', name)}: file missing on this server")
            inventory[name] = {**meta, "missing": True}
            return
        sha = b.add_file(name, src, expected)
        inventory[name] = {**meta, "sha256": sha, "stored_in": str(point.id)}

    # 1. database: complete, consistent snapshot (pg_dump uses one transaction)
    b.add_command("database.enc", [settings.PG_DUMP_CMD, "--format=custom", "--compress=0", "--no-owner", "--no-privileges"])
    # 2. documents: every retained version (quarantined malware is never copied into backups)
    excluded = 0
    for v in DocumentVersion.objects.values("id", "storage_path", "sha256", "size", "av_status", "preview_path", "searchable_path",
                                            "thumbnail_path").iterator():
        if v["av_status"] == "quarantined":
            excluded += 1
            continue
        ref(f"objects/{v['id']}", Path(settings.ORIGINALS_DIR) / v["storage_path"], v["sha256"],
            {"type": "original", "version": str(v["id"]), "path": v["storage_path"], "size": v["size"]})
        for drel in (v["preview_path"], v["searchable_path"], v["thumbnail_path"]):
            if drel:
                src = Path(settings.DERIVATIVES_DIR) / drel
                if src.exists():
                    ref(_hash_name("derived", drel), src, None, {"type": "derivative", "path": drel})
    # 3. profile photos and sign-in branding
    for name in User.objects.exclude(photo_name="").values_list("photo_name", flat=True):
        for stem in (name, f"{name}-thumb"):
            src = photo_dir() / f"{stem}.webp"
            if src.exists():
                ref(_hash_name("photos", src.name), src, None, {"type": "photo", "path": src.name})
    from apps.core import designs

    for n in sorted(designs.referenced_files()):  # every saved sign-in design's files + the shared logo (Change Set W)
        if n and "/" not in n and (branding_dir() / n).exists():
            ref(_hash_name("branding", n), branding_dir() / n, None, {"type": "branding", "path": n})
    # 4. catalogue, settings, secrets
    catalog = build_catalog()
    b.add_bytes("catalog.enc", json.dumps(catalog, default=str).encode())
    b.add_bytes("settings.enc", json.dumps({"global": config.snapshot_global(), "users": _user_settings()}, default=str).encode())
    secret_files = _secret_files()
    b.add_bytes("secrets.enc", json.dumps({"files": secret_files}).encode())
    counts = {"users": len(catalog["users"]), "groups": len(catalog["groups"]), "folders": len(catalog["folders"]),
              "documents": len(catalog["documents"]), "versions": len(catalog["versions"]), "rules": len(catalog["rules"]),
              "objects_total": len(inventory), "objects_new": len(b.stored), "quarantined_excluded": excluded,
              "missing": sum(1 for v in inventory.values() if v.get("missing"))}
    chain_ids = [str(p.id) for p in parent.chain()] + [str(point.id)] if parent else [str(point.id)]
    manifest = {"format": FORMAT, "point": str(point.id), "kind": point.kind, "created_at": point.created_at.isoformat(),
                "chain": chain_ids, "app_version": point.app_version, "schema": point.schema,
                "installation": config.get("general.installation_id") or "personaldocs",
                "classes": {"database": "database.enc", "catalog": "catalog.enc", "settings": "settings.enc",
                            "secrets": sorted(secret_files), "documents": counts["versions"],
                            "derivatives": sum(1 for v in inventory.values() if v.get("type") == "derivative"),
                            "photos": sum(1 for v in inventory.values() if v.get("type") == "photo"),
                            "branding": sum(1 for v in inventory.values() if v.get("type") == "branding"),
                            "ocr": sum(1 for v in catalog["versions"] if v.get("text") or v.get("ocr_blocks")),
                            "audit_and_security_state": "database.enc", "trusted_zones": "database.enc",
                            "notification_routing": "database.enc", "backup_policies": "database.enc"},
                "inventory": inventory, "counts": counts, "warnings": b.warnings,
                "compression": "none"}
    b.add_bytes("manifest.enc", json.dumps(manifest, default=str).encode())
    header = {"format": FORMAT, "point": str(point.id), "kind": point.kind, "trigger": point.trigger,
              "created_at": point.created_at.isoformat(), "parent": str(parent.id) if parent else None,
              "base": str((parent.base or parent).id) if parent else None, "chain": chain_ids, "key_generation": key.generation,
              "key_fingerprint": key.fingerprint, "dek": C.wrap_dek(raw, dek, str(point.id)), "app_version": point.app_version,
              "schema": point.schema, "installation": manifest["installation"], "encryption": "AES-256-GCM STREAM, HKDF-SHA256",
              "compression": "none", "files": b.files}
    (b.dir / "header.json").write_text(json.dumps(header, indent=1))
    point.stored = b.stored
    point.counts = counts
    point.size_bytes = sum(f["cipher_size"] for f in b.files.values())
    point.verification = {"build_warnings": b.warnings}
    point.save(update_fields=["stored", "counts", "size_bytes", "verification"])


# ------------------------------------------------------------------ replication

def _classify(code: str) -> str:
    return {"auth_required": RecoveryCopy.AUTH_REQUIRED, "unavailable": RecoveryCopy.UNAVAILABLE,
            "insufficient_storage": RecoveryCopy.INSUFFICIENT}.get(code, RecoveryCopy.FAILED)


def replicate(point: RecoveryPoint, dest: BackupDestination, progress=None) -> RecoveryCopy:
    copy, _ = RecoveryCopy.objects.get_or_create(point=point, destination=dest, defaults={"generation": point.key_generation})
    if copy.state in (RecoveryCopy.STORED_VERIFIED,):
        return copy
    d = point_dir(point.id, copy.generation)
    if not (d / "header.json").exists():
        copy.state, copy.detail = RecoveryCopy.FAILED, "The local staging copy is gone; the next backup will protect this destination again."
        copy.save(update_fields=["state", "detail"])
        return copy
    header = json.loads((d / "header.json").read_text())
    need = sum(f["cipher_size"] for f in header["files"].values())
    copy.attempts += 1
    copy.state = RecoveryCopy.UPLOADING
    copy.save(update_fields=["attempts", "state"])
    prov = provider(dest)
    try:
        free, total = prov.space()
        _set_health(dest, "healthy", "", free, total)
        if free is not None and free < need + 16 * 1024 * 1024:
            # Never delete other valid backups to make room: alert and let this destination fail.
            raise DestError("insufficient_storage", f"Needs {need // (1024 * 1024)} MiB, only {free // (1024 * 1024)} MiB free.")
        for name in sorted(header["files"]):
            prov.put(rel(point.id, copy.generation, name), d / name)
        prov.put(rel(point.id, copy.generation, "header.json"), d / "header.json")  # header last: a copy is complete
        copy.bytes, copy.stored_at = need, timezone.now()
        copy.save(update_fields=["bytes", "stored_at"])
    except DestError as exc:
        copy.state, copy.detail = _classify(exc.code), str(exc)[:500]
        if copy.attempts < 6 and exc.code != "auth_required":
            copy.state = RecoveryCopy.RETRY_PENDING if exc.code == "unavailable" else copy.state
            copy.next_retry_at = timezone.now() + timedelta(minutes=30 * copy.attempts)
        copy.save(update_fields=["state", "detail", "next_retry_at"])
        _set_health(dest, {"auth_required": "auth_required", "insufficient_storage": "insufficient_storage"}.get(exc.code, "unavailable"),
                    str(exc)[:300])
        _notify("backup.destination", point, detail=f"{dest.name}: {RecoveryCopy.LABELS.get(copy.state, copy.state)} - {exc}",
                severity="critical" if exc.code == "insufficient_storage" else "warning", tag=f"{dest.pk}:{exc.code}")
        return copy
    if progress:
        progress("verifying")
    verify_copy(copy)
    return copy


def capacity(dest) -> dict:
    """Free space against the warning/critical thresholds (defaults 20 % / 10 %, overridable per destination)."""
    from apps.core import config

    cfg = dest.config or {}
    warn = int(cfg.get("warn_pct") or config.get("backup.space_warning_pct") or 20)
    crit = int(cfg.get("crit_pct") or config.get("backup.space_critical_pct") or 10)
    if not dest.total_bytes or dest.free_bytes is None:
        return {"state": "unknown", "warn_pct": warn, "crit_pct": crit, "free_pct": None}
    pct = round(dest.free_bytes * 100 / dest.total_bytes, 1)
    return {"state": "critical" if pct <= crit else "warning" if pct <= warn else "ok", "warn_pct": warn, "crit_pct": crit, "free_pct": pct}


def _set_health(dest, health, detail, free=None, total=None):
    BackupDestination.objects.filter(pk=dest.pk).update(health=health, health_detail=detail[:300], checked_at=timezone.now(),
                                                         **({"free_bytes": free, "total_bytes": total} if free is not None else {}))
    if free is not None and total:
        dest.free_bytes, dest.total_bytes = free, total
        cap = capacity(dest)
        if cap["state"] in ("warning", "critical"):  # one alert per destination, level and day
            _notify("backup.destination", None, detail=f"{dest.name}: only {cap['free_pct']} % free (threshold {cap['warn_pct'] if cap['state'] == 'warning' else cap['crit_pct']} %). "
                                                       "Valid backups are never deleted to make room; retention controls normal cleanup.",
                    severity="critical" if cap["state"] == "critical" else "warning", tag=f"{dest.pk}:space:{cap['state']}:{timezone.now():%Y%m%d}")


def retry_pending() -> int:
    n = 0
    for copy in RecoveryCopy.objects.filter(state__in=[RecoveryCopy.RETRY_PENDING, RecoveryCopy.UNAVAILABLE],
                                            next_retry_at__lte=timezone.now(), point__deleted_at__isnull=True).select_related("point", "destination"):
        if (copy.point.created_at < timezone.now() - timedelta(hours=RETRY_HOURS)) or not copy.destination.enabled:
            continue
        replicate(copy.point, copy.destination)
        rollup(copy.point)
        cleanup_staging(copy.point)
        n += 1
    return n


def cleanup_staging(point: RecoveryPoint) -> None:
    """Keep the staging copy while a destination may still be retried; then delete it."""
    pending = point.copies.filter(state__in=[RecoveryCopy.RETRY_PENDING, RecoveryCopy.UNAVAILABLE, RecoveryCopy.UPLOADING]).exists()
    young = point.created_at > timezone.now() - timedelta(hours=RETRY_HOURS)
    if not (pending and young):
        shutil.rmtree(staging_root() / str(point.id), ignore_errors=True)


def rollup(point: RecoveryPoint) -> str:
    states = list(point.copies.exclude(state=RecoveryCopy.DELETED).values_list("state", flat=True))
    good = [s for s in states if s == RecoveryCopy.STORED_VERIFIED]
    warn = [s for s in states if s == RecoveryCopy.STORED_WARNING]
    if good and len(good) == len(states):
        status = RecoveryPoint.VERIFIED
    elif good:
        status = RecoveryPoint.PARTIAL
    elif warn:
        status = RecoveryPoint.WARNING
    else:
        status = RecoveryPoint.FAILED
    point.status, point.finished_at = status, point.finished_at or timezone.now()
    point.save(update_fields=["status", "finished_at"])
    return status


# ------------------------------------------------------------------ deep verification

class _HashReader:
    def __init__(self, fh):
        self.fh, self.h, self.n = fh, hashlib.sha256(), 0

    def read(self, n=-1):
        b = self.fh.read(n)
        self.h.update(b)
        self.n += len(b)
        return b


def open_point(prov, point_id, generation: int, key_raw: bytes) -> tuple[dict, bytes]:
    with prov.open(rel(point_id, generation, "header.json")) as fh:
        header = json.loads(fh.read(4 * 1024 * 1024))
    if header.get("format") != FORMAT:
        raise C.DecryptError("Unsupported package format.")
    return header, C.unwrap_dek(key_raw, header["dek"], str(point_id))


def read_component(prov, point_id, generation: int, dek: bytes, name: str) -> bytes:
    with prov.open(rel(point_id, generation, name)) as fh:
        return C.decrypt_bytes(fh, dek, name)


def verify_copy(copy: RecoveryCopy, key_raw: bytes | None = None) -> dict:
    """Deep verification of one copy, read back from the destination: header, cipher checksums, authenticated
    decryption of every file, manifest schema, database dump structure, settings/secrets readability, inventory
    consistency and chain references. Never stores plain text outside a temporary file for the database check."""
    point = copy.point
    checks: list[dict] = []

    def add(name, ok, detail="", level="error"):
        checks.append({"check": name, "ok": bool(ok), "detail": detail[:300], "level": "ok" if ok else level})

    try:
        prov = provider(copy.destination)
        key_raw = key_raw or bk_keys.raw_key(copy.generation)
        header, dek = open_point(prov, point.id, copy.generation, key_raw)
        add("Header and key", True, f"Key generation {copy.generation}")
        add("Chain identity", header.get("chain", [])[-1:] == [str(point.id)] and header.get("parent") == (str(point.parent_id) if point.parent_id else None),
            "Chain references match the catalogue of recovery points")
        missing = []
        bad = []
        stored = point.stored or {}
        for name, meta in sorted(header["files"].items()):
            try:
                with prov.open(rel(point.id, copy.generation, name)) as fh:
                    hr = _HashReader(fh)
                    sha, _n = C.digest_and_verify(hr, dek, name)
                if hr.h.hexdigest() != meta["cipher_sha256"] or hr.n != meta["cipher_size"]:
                    bad.append(f"{name}: checksum mismatch")
                elif name in stored and stored[name] != sha:
                    bad.append(f"{name}: content differs from what was backed up")
            except DestError as exc:
                missing.append(f"{name}: {exc}")
            except C.DecryptError as exc:
                bad.append(f"{name}: {exc}")
        add("Encrypted files readable and authentic", not bad and not missing,
            f"{len(header['files'])} files checked" if not (bad or missing) else "; ".join((missing + bad)[:5]))
        manifest = json.loads(read_component(prov, point.id, copy.generation, dek, "manifest.enc"))
        required = {"format", "point", "chain", "classes", "inventory", "counts", "schema", "app_version"}
        add("Manifest", required <= set(manifest) and manifest["point"] == str(point.id), "Versioned manifest with every recovery class")
        catalog = json.loads(read_component(prov, point.id, copy.generation, dek, "catalog.enc"))
        originals = [v for v in manifest["inventory"].values() if v.get("type") == "original"]
        consistent = len(originals) + manifest["counts"].get("quarantined_excluded", 0) == len(catalog.get("versions", []))
        add("Document and version inventory", consistent,
            f"{len(catalog.get('documents', []))} documents, {len(catalog.get('versions', []))} versions")
        json.loads(read_component(prov, point.id, copy.generation, dek, "settings.enc"))
        add("Settings package", True, "Readable")
        sec = json.loads(read_component(prov, point.id, copy.generation, dek, "secrets.enc"))
        add("Encrypted secrets package", "encryption.key" in sec.get("files", {}), "Installation key present" if "encryption.key" in sec.get("files", {}) else "Installation key missing")
        # chain references: every object stored in an earlier point must have a usable copy on the same destination
        chain_ok, chain_detail = True, "Full backup"
        if point.parent_id:
            needed = {v["stored_in"] for v in manifest["inventory"].values() if v.get("stored_in") and v["stored_in"] != str(point.id)}
            have = set(RecoveryCopy.objects.filter(destination=copy.destination, point__in=[p.id for p in point.chain()[:-1]],
                                                   state__in=[RecoveryCopy.STORED_VERIFIED, RecoveryCopy.STORED_WARNING])
                       .values_list("point_id", flat=True))
            lost = needed - {str(x) for x in have}
            chain_ok = not lost
            chain_detail = f"Depends on {len(point.chain()) - 1} earlier point(s)" if chain_ok else f"{len(lost)} required earlier point(s) missing on this destination"
        add("Full/incremental chain", chain_ok, chain_detail)
        ok_db, db_detail = _check_dump(prov, point, copy.generation, dek)
        add("Database backup structure", ok_db, db_detail)
        if manifest.get("warnings"):
            add("Backup warnings", False, "; ".join(manifest["warnings"][:3]), level="warning")
    except (DestError, C.DecryptError, ValueError, KeyError) as exc:
        add("Read back", False, str(exc))
    errors = [c for c in checks if not c["ok"] and c["level"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["level"] == "warning"]
    status = "failed" if errors else "warning" if warnings else "verified"
    copy.state = {"verified": RecoveryCopy.STORED_VERIFIED, "warning": RecoveryCopy.STORED_WARNING}.get(status, RecoveryCopy.FAILED)
    copy.detail = "" if status == "verified" else "; ".join(c["detail"] or c["check"] for c in (errors or warnings))[:500]
    copy.verified_at = timezone.now()
    copy.save(update_fields=["state", "detail", "verified_at"])
    ver = dict(point.verification or {})
    ver[str(copy.destination_id)] = {"status": status, "checks": checks, "at": timezone.now().isoformat()}
    point.verification = ver
    point.save(update_fields=["verification"])
    if status != "verified":
        _notify("backup.verification", point, detail=f"{copy.destination.name}: {copy.detail}",
                severity="critical" if status == "failed" else "warning", tag=str(copy.pk))
    return {"status": status, "checks": checks}


def _check_dump(prov, point, generation, dek) -> tuple[bool, str]:
    tmp = staging_root() / f"verify-{point.id}-{secrets.token_hex(4)}.pgdump"
    try:
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with prov.open(rel(point.id, generation, "database.enc")) as fh:
            C.decrypt_to(fh, tmp, dek, "database.enc")
        os.chmod(tmp, 0o600)
        proc = subprocess.run([settings.PG_RESTORE_CMD, "--list", str(tmp)], capture_output=True, timeout=600)
        if proc.returncode != 0:
            return False, "pg_restore cannot read the dump"
        listing = proc.stdout.decode(errors="replace")
        tables = listing.count(" TABLE DATA ")
        ok = tables > 10 and "django_migrations" in listing
        return ok, f"{tables} tables with data" if ok else "The dump is incomplete"
    except (DestError, C.DecryptError, OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)[:200]
    finally:
        tmp.unlink(missing_ok=True)


def verify_point(point: RecoveryPoint) -> RecoveryPoint:
    for copy in point.copies.exclude(state__in=[RecoveryCopy.DELETED, RecoveryCopy.UPLOADING]).select_related("destination", "point"):
        if copy.stored_at:
            verify_copy(copy)
    rollup(point)
    return point


# ------------------------------------------------------------------ retention and deletion

def chains(policy: BackupPolicy | None) -> list[list[RecoveryPoint]]:
    qs = RecoveryPoint.objects.filter(deleted_at__isnull=True).exclude(status=RecoveryPoint.RUNNING)
    qs = qs.filter(policy=policy) if policy else qs
    by_base: dict = {}
    for p in qs.order_by("created_at", "id"):
        base_id = p.base_id or p.id
        by_base.setdefault(base_id, []).append(p)
    # the base (Full) always leads its chain, even when an incremental has the same timestamp; otherwise the chain
    # would not count as usable and retention could plan to delete the newest usable chain
    for c in by_base.values():
        c.sort(key=lambda p: (p.base_id is not None, p.created_at))
    return sorted(by_base.values(), key=lambda c: c[0].created_at, reverse=True)


def dependents(point: RecoveryPoint) -> list[RecoveryPoint]:
    """Points that need this one to restore (later incrementals of the chain)."""
    out, frontier = [], [point]
    while frontier:
        kids = list(RecoveryPoint.objects.filter(parent__in=frontier, deleted_at__isnull=True))
        out += kids
        frontier = kids
    return sorted(out, key=lambda p: p.created_at)


def retention_plan(policy: BackupPolicy, now=None) -> list[list[RecoveryPoint]]:
    """Whole chains that may be deleted: the Full is older than the retention window AND a newer usable chain
    exists. The newest usable chain is never deleted, and a base is never deleted while its incrementals remain
    (chains are removed as a unit)."""
    now = now or timezone.now()
    limit = now - timedelta(weeks=policy.retention_weeks)
    all_chains = chains(policy)
    usable = [c for c in all_chains if c[0].kind == RecoveryPoint.FULL and c[0].status in (RecoveryPoint.VERIFIED, RecoveryPoint.PARTIAL, RecoveryPoint.WARNING)]
    keep_newest = usable[0] if usable else None
    out = []
    for c in all_chains:
        if c is keep_newest:
            continue
        full_failed = c[0].status == RecoveryPoint.FAILED and all(p.status == RecoveryPoint.FAILED for p in c)
        if c[0].created_at < limit or (full_failed and c[0].created_at < now - timedelta(days=7)):
            if keep_newest is None or keep_newest[0].created_at > c[0].created_at or full_failed:
                out.append(c)
    return out


def delete_points(points: list[RecoveryPoint], *, actor=None, reason: str = "retention", request=None) -> dict:
    """Delete copies on every destination; a point is marked deleted only when every copy is gone."""
    done, pending = [], []
    for p in sorted(points, key=lambda x: x.created_at, reverse=True):  # newest first: dependents before their base
        remaining = 0
        for copy in p.copies.exclude(state=RecoveryCopy.DELETED).select_related("destination"):
            try:
                provider(copy.destination).delete_prefix(str(p.id))
                copy.state, copy.detail = RecoveryCopy.DELETED, ""
            except DestError as exc:
                copy.detail = f"Deletion pending: {exc}"[:500]
                remaining += 1
            copy.save(update_fields=["state", "detail"])
        shutil.rmtree(staging_root() / str(p.id), ignore_errors=True)
        if remaining:
            pending.append(str(p.id))
        else:
            p.deleted_at, p.status = timezone.now(), RecoveryPoint.DELETED
            p.save(update_fields=["deleted_at", "status"])
            done.append(str(p.id))
    audit.record("backup.delete" if reason != "retention" else "backup.retention", request=request, actor=actor,
                 deleted=len(done), pending=len(pending), reason=reason)
    bk_keys.retire_unused()
    return {"deleted": done, "pending": pending}


def apply_retention(policy: BackupPolicy) -> dict:
    plan = retention_plan(policy)
    if not plan:
        return {"deleted": [], "pending": []}
    pts = [p for c in plan for p in c]
    try:
        res = delete_points(pts, reason="retention")
        _notify("backup.retention", None, detail=f"{len(res['deleted'])} expired recovery point(s) removed by the retention policy."
                + (f" {len(res['pending'])} could not be removed yet." if res["pending"] else ""),
                severity="warning" if res["pending"] else "success", tag=timezone.now().strftime("%Y%m%d%H"))
        return res
    except Exception as exc:  # noqa: BLE001
        _notify("backup.retention", None, detail=f"Retention cleanup failed: {exc}", severity="warning")
        raise


# ------------------------------------------------------------------ pre-change safety backup

def pre_change_backup(reason: str, actor=None, request=None) -> dict:
    """Preflight backup + deep verification before a high-risk operation. ``ok`` False blocks the operation
    unless the main administrator explicitly overrides (audited by the caller)."""
    if not configured():
        return {"ok": False, "detail": "No backup policy with an enabled destination is configured.", "point": None}
    kind = RecoveryPoint.INCREMENTAL if _incremental_parent(default_policy()) else RecoveryPoint.FULL
    try:
        point = create_point(default_policy(), kind=kind, trigger="pre_change", actor=actor, reason=reason, request=request)
    except BackupError as exc:
        _notify("backup.pre_change_blocked", None, detail=f"{reason}: {exc}", severity="critical")
        return {"ok": False, "detail": str(exc)[:300], "point": None}
    ok = point.status in (RecoveryPoint.VERIFIED, RecoveryPoint.PARTIAL)
    _notify("backup.pre_change" if ok else "backup.pre_change_blocked", point,
            detail=reason if ok else f"{reason}: the safety backup could not be verified; the operation was blocked.",
            severity="success" if ok else "critical")
    return {"ok": ok, "detail": f"Recovery point {point.id} ({point.status})", "point": str(point.id)}


# ------------------------------------------------------------------ health (dashboard, doctor)

def health() -> dict:
    """Backup & Recovery Health from usable verified recovery state - never from "the scheduler is running"."""
    from .bk_validation import validation_state

    now = timezone.now()
    policies = list(BackupPolicy.objects.filter(enabled=True))
    pts = RecoveryPoint.objects.filter(deleted_at__isnull=True)
    latest = pts.exclude(status=RecoveryPoint.RUNNING).order_by("-created_at").first()
    latest_ok = pts.filter(status__in=[RecoveryPoint.VERIFIED, RecoveryPoint.PARTIAL]).order_by("-created_at").first()
    latest_full = pts.filter(kind=RecoveryPoint.FULL, status__in=[RecoveryPoint.VERIFIED, RecoveryPoint.PARTIAL]).order_by("-created_at").first()
    dests = list(BackupDestination.objects.filter(enabled=True))
    warnings: list[str] = []
    readiness = bk_keys.readiness()
    if not policies or not dests:
        state = "critical"
        warnings.append("No backup policy with an enabled destination is configured.")
    elif latest_ok is None:
        state = "critical"
        warnings.append("There is no verified recovery point yet.")
    else:
        state = "healthy"
        max_age = max((p.incremental_hours for p in policies if p.incremental_hours), default=0)
        stale_after = timedelta(hours=max(max_age * 3, 26)) if max_age else timedelta(days=8 if any(p.full_frequency == "weekly" for p in policies) else 2)
        if now - latest_ok.created_at > stale_after * 2:
            state = "critical"
            warnings.append("The newest verified recovery point is too old.")
        elif now - latest_ok.created_at > stale_after:
            state = "attention"
            warnings.append("The newest verified recovery point is older than the schedule expects.")
        if latest and latest.status == RecoveryPoint.FAILED:
            state = "critical" if state == "critical" else "attention"
            warnings.append("The most recent backup failed.")
        if latest_ok.status == RecoveryPoint.PARTIAL:
            state = "attention" if state == "healthy" else state
            warnings.append("Some destinations do not hold a verified copy of the latest recovery point.")
    bad_dests = [d for d in dests if d.health not in ("healthy", "unknown")]
    if bad_dests and state == "healthy":
        state = "attention"
    for d in bad_dests:
        warnings.append(f"{d.name}: {d.health.replace('_', ' ')}" + (" (migration incomplete; existing backup data preserved)" if d.health == "needs_attention" else ""))
    for d in dests:
        cap = capacity(d)
        if cap["state"] == "critical":
            state = "critical"
            warnings.append(f"{d.name}: only {cap['free_pct']} % free space (critical below {cap['crit_pct']} %).")
        elif cap["state"] == "warning":
            state = "attention" if state == "healthy" else state
            warnings.append(f"{d.name}: {cap['free_pct']} % free space (warning below {cap['warn_pct']} %).")
    if readiness["state"] in ("not_exported", "outdated"):
        if state == "healthy":
            state = "attention"
        warnings.append(f"Recovery Readiness: {readiness['label']} - export an Emergency Recovery Package.")
    pending_rot = RecoveryKey.objects.filter(state=RecoveryKey.RETIRING).exists()
    if pending_rot:
        warnings.append("A Recovery Key rotation is incomplete: some copies still use the previous key.")
        state = "attention" if state == "healthy" else state
    return {"state": state, "label": {"healthy": "Healthy", "attention": "Attention", "critical": "Critical"}[state],
            "latest": _point_brief(latest), "latest_verified": _point_brief(latest_ok), "latest_full": _point_brief(latest_full),
            "destinations": [{"id": d.id, "name": d.name, "kind": d.kind, "health": d.health, "detail": d.health_detail,
                              "free_bytes": d.free_bytes, "checked_at": d.checked_at.isoformat() if d.checked_at else None} for d in dests],
            "readiness": readiness, "validation": validation_state(), "warnings": warnings,
            "points": pts.exclude(status=RecoveryPoint.FAILED).count()}


def _point_brief(p: RecoveryPoint | None) -> dict | None:
    if p is None:
        return None
    return {"id": str(p.id), "kind": p.kind, "trigger": p.trigger, "status": p.status, "created_at": p.created_at.isoformat(),
            "size_bytes": p.size_bytes, "key_generation": p.key_generation}


# ------------------------------------------------------------------ notifications

def _notify(event: str, point: RecoveryPoint | None, *, detail: str = "", severity: str = "", tag: str = "") -> None:
    try:
        from apps.notify import events

        events.backup_event(event, point=point, detail=detail, severity=severity, tag=tag)
    except Exception:  # noqa: BLE001 - notifications never break backups
        log.exception("backup notification failed")


def _notify_result(point: RecoveryPoint) -> None:
    labels = {c.destination.name: RecoveryCopy.LABELS.get(c.state, c.state) for c in point.copies.select_related("destination")}
    summary = ", ".join(f"{k}: {v}" for k, v in labels.items())
    if point.status == RecoveryPoint.VERIFIED:
        if point.policy is None or point.policy.notify_success or point.trigger != "scheduled":
            _notify("backup.succeeded", point, detail=summary, severity="success")
    elif point.status in (RecoveryPoint.PARTIAL, RecoveryPoint.WARNING):
        _notify("backup.partial", point, detail=summary, severity="warning")
    else:
        _notify("backup.failed", point, detail=summary or point.error, severity="critical")


# ------------------------------------------------------------------ legacy (format 1) backups

def legacy_backups() -> list[dict]:
    """Unencrypted folder backups made before Change Set T: listed read-only, restorable with
    ``personaldocs restore <folder>``, never deleted automatically."""
    out = []
    roots = {config.get("backup.target")} | {d.config.get("path") for d in BackupDestination.objects.filter(kind__in=["local", "nas"])}
    for raw in sorted(r for r in roots if r):
        root = Path(raw)
        try:
            entries = list(root.iterdir()) if root.is_dir() else []
        except OSError:
            continue
        for p in entries:
            if p.is_dir() and p.name.startswith("backup-") and not p.name.endswith(".partial") and (p / "manifest.json").exists():
                try:
                    m = json.loads((p / "manifest.json").read_text())
                except (OSError, ValueError):
                    continue
                out.append({"path": str(p), "name": p.name, "created_at": m.get("created_at"), "files": m.get("file_count"),
                            "bytes": m.get("bytes"), "verified": m.get("verified"), "format": m.get("format", 1)})
    return sorted(out, key=lambda x: x.get("created_at") or "", reverse=True)


def due_points(now_local) -> list[tuple[BackupPolicy, str, str]]:
    """(policy, kind, slot) that should run now. Full schedules use the same rules as before (daily/weekly/
    monthly at a local time, missed runs catch up once); incrementals run every N hours inside a chain."""
    from . import schedule

    out = []
    for pol in BackupPolicy.objects.filter(enabled=True):
        if not pol.destinations.filter(enabled=True).exists():
            continue
        spec = {"enabled": True, "time": pol.full_time, "frequency": pol.full_frequency, "weekday": pol.full_weekday,
                "month_day": pol.full_month_day}
        from apps.notify.models import SchedulerRun

        row = SchedulerRun.objects.filter(name=f"backup_policy:{pol.id}:full").first()
        occ = schedule.due(now_local, row.last_run_at if row else None, spec)  # last time a Full was scheduled
        if occ is not None:  # failed attempts are de-duplicated per slot by the job idempotency key
            out.append((pol, RecoveryPoint.FULL, occ.isoformat()))
            continue
        if pol.incremental_hours and pol.last_full_at:
            last = max(filter(None, [pol.last_full_at, pol.last_incremental_at]))
            if timezone.now() - last >= timedelta(hours=pol.incremental_hours) - timedelta(minutes=1):
                slot = timezone.now().strftime("%Y%m%d%H")
                out.append((pol, RecoveryPoint.INCREMENTAL, slot))
    return out

