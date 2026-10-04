"""Application-level backup and restore to a mounted NAS/file share.

Consistency protocol ("immutable files + manifest"):
1. Originals and derivatives are write-once; every file referenced by a DB row exists before the row commits.
2. pg_dump takes a consistent snapshot of the database.
3. Files referenced by that snapshot are copied (hard-linked from the previous backup when the checksum
   is unchanged to save space) and verified against their SHA-256 checksums.
4. A manifest is written last, then the backup directory is atomically renamed from *.partial.
A backup is "verified" only when every referenced original was copied and its checksum re-read OK.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.core import audit, config, crypto

log = logging.getLogger("personaldocs.backup")

MARKER = ".personaldocs-backup-target"


class BackupError(Exception):
    pass


def check_target() -> Path:
    try:
        from . import nas

        nas.sync()
    except Exception:  # noqa: BLE001 - a broken status file must not block backups to a configured folder
        pass
    raw = config.get("backup.target")
    if not raw:
        raise BackupError("No backup destination is configured (Settings → Storage & Backup).")
    target = Path(raw)
    if not target.is_dir():
        raise BackupError(f"Backup destination {target} is not reachable. Is the NAS share mounted?")
    if config.get("backup.require_mount"):
        mount = target.resolve()
        while not os.path.ismount(mount) and mount != mount.parent:
            mount = mount.parent
        if mount == Path("/"):
            raise BackupError(f"{target} is not on a mounted share. Mount the NAS share, or turn off 'Require mounted destination' if the target is intentionally local.")
    if not (target / MARKER).exists():
        raise BackupError(f"The marker file {MARKER} is missing in {target}. This protects against writing into an empty local mount point; create it once after mounting the share.")
    if not os.access(target, os.W_OK):
        raise BackupError(f"The service account cannot write to {target}.")
    return target


def _state_file() -> Path:
    return Path(settings.DATA_DIR) / "backup-status.json"


def last_backup_status() -> dict:
    try:
        return json.loads(_state_file().read_text())
    except (OSError, ValueError):
        return {"last_success": None, "last_attempt": None, "last_error": None}


def _write_status(**updates) -> None:
    status = last_backup_status()
    status.update(updates)
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, default=str, indent=1))
    os.replace(tmp, path)


def _pg_env() -> dict:
    db = settings.DATABASES["default"]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PGPASSWORD": db.get("PASSWORD") or "", "PGHOST": db.get("HOST") or "",
           "PGPORT": str(db.get("PORT") or "5432"), "PGUSER": db.get("USER") or "", "PGDATABASE": db.get("NAME")}
    return env


def _dump_db(dest: Path) -> None:
    proc = subprocess.run([settings.PG_DUMP_CMD, "--format=custom", "--no-owner", "--no-privileges", "-f", str(dest)],
                          env=_pg_env(), capture_output=True, timeout=3600)
    if proc.returncode != 0:
        raise BackupError(f"Database dump failed: {proc.stderr.decode(errors='replace')[-300:]}")


def _previous_backups(target: Path) -> list[Path]:
    found = [p for p in target.iterdir() if p.is_dir() and p.name.startswith("backup-") and not p.name.endswith(".partial")
             and (p / "manifest.json").exists()]

    def created(p: Path) -> str:
        try:
            return json.loads((p / "manifest.json").read_text()).get("created_at", "")
        except (OSError, ValueError):
            return ""

    return sorted(found, key=created, reverse=True)  # newest first, by manifest time (not folder name)


def run_backup(actor=None, request=None) -> dict:
    started = timezone.now()
    _write_status(last_attempt=started.isoformat(), running=True)
    try:
        target = check_target()
        result = _do_backup(target)
        _write_status(last_success=timezone.now().isoformat(), last_error=None, running=False, last_bytes=result["bytes"],
                      last_seconds=result["seconds"], last_path=result["path"], last_verified=result["verified"],
                      destination=str(target))
        audit.record("backup.run", request=request, actor=actor, files=result["files"], verified=result["verified"])
        prune(target)
        return result
    except Exception as exc:
        _write_status(last_error=str(exc)[:500], running=False, last_failure=timezone.now().isoformat())
        audit.record("backup.run", request=request, actor=actor, outcome="failure", reason=str(exc)[:200])
        from apps.notify import events

        events.backup_failed(str(exc))
        raise


def _do_backup(target: Path) -> dict:
    from apps.library.models import DocumentVersion

    t0 = timezone.now()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ident = config.get("general.installation_id") or "personaldocs"
    final = target / f"backup-{stamp}-{ident}"
    n = 2
    while final.exists() or (target / (final.name + ".partial")).exists():
        final = target / f"backup-{stamp}-{n}-{ident}"
        n += 1
    work = target / (final.name + ".partial")
    work.mkdir(parents=True)
    prev = _previous_backups(target)
    prev_dir = prev[0] if prev else None
    _dump_db(work / "database.pgdump")
    # The set of files referenced by the snapshot: taken after the dump, every referenced file already exists.
    files = []
    total = 0
    verified = True
    with connection.cursor() as cur:
        cur.execute("SELECT storage_path, sha256, size, preview_path, searchable_path, thumbnail_path FROM library_documentversion")
        rows = cur.fetchall()
    for rel, sha, size, preview, searchable, thumb in rows:
        src = Path(settings.ORIGINALS_DIR) / rel
        dst = work / "originals" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        linked = False
        if prev_dir is not None:
            old = prev_dir / "originals" / rel
            if old.exists() and old.stat().st_size == size:
                try:
                    os.link(old, dst)
                    linked = True
                except OSError:
                    linked = False
        if not linked:
            if not src.exists():
                files.append({"path": rel, "missing": True})
                verified = False
                continue
            shutil.copyfile(src, dst)
        ok = crypto.sha256_file(dst) == sha
        verified = verified and ok
        files.append({"path": rel, "sha256": sha, "size": size, "ok": ok})
        total += size
        for drel in (preview, searchable, thumb):
            if drel:
                dsrc = Path(settings.DERIVATIVES_DIR) / drel
                if dsrc.exists():
                    ddst = work / "derivatives" / drel
                    ddst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(dsrc, ddst)
    (work / "settings.json").write_text(json.dumps(config.snapshot_global(), indent=1, default=str))
    if config.get("backup.include_keys"):
        key = crypto.key_path()
        if key.exists():
            shutil.copyfile(key, work / "encryption.key")
            os.chmod(work / "encryption.key", 0o600)
    manifest = {"format": 1, "app_version": settings.APP_VERSION, "created_at": timezone.now().isoformat(), "installation": ident,
                "files": files, "file_count": len(files), "bytes": total, "verified": verified,
                "includes_key": (work / "encryption.key").exists()}
    (work / "manifest.json").write_text(json.dumps(manifest, indent=1))
    os.replace(work, final)
    secs = (timezone.now() - t0).total_seconds()
    return {"path": str(final), "files": len(files), "bytes": total, "verified": verified, "seconds": round(secs, 1)}


def prune(target: Path) -> list[str]:
    keep = int(config.get("backup.keep_daily"))
    backups = _previous_backups(target)
    newest_verified = next((b for b in backups if json.loads((b / "manifest.json").read_text()).get("verified")), None)
    removed = []
    for b in backups[keep:]:
        if b == newest_verified:
            continue  # never prune the only/most recent verified backup
        shutil.rmtree(b, ignore_errors=True)
        removed.append(b.name)
    for stale in target.glob("backup-*.partial"):
        shutil.rmtree(stale, ignore_errors=True)
    return removed


def verify_backup(path: Path) -> dict:
    manifest = json.loads((path / "manifest.json").read_text())
    bad = []
    for f in manifest["files"]:
        if f.get("missing"):
            bad.append(f["path"])
            continue
        p = path / "originals" / f["path"]
        if not p.exists() or crypto.sha256_file(p) != f["sha256"]:
            bad.append(f["path"])
    return {"ok": not bad and (path / "database.pgdump").exists(), "bad": bad, "files": len(manifest["files"])}


def restore_backup(path: Path, *, include_key: bool = True) -> dict:
    """Restore into the configured (empty or to-be-replaced) database and data directory. Console only."""
    check = verify_backup(path)
    if not check["ok"]:
        raise BackupError(f"Backup failed verification ({len(check['bad'])} problems); refusing to restore.")
    proc = subprocess.run([settings.PG_RESTORE_CMD, "--clean", "--if-exists", "--no-owner", "--no-privileges", "-d",
                           settings.DATABASES["default"]["NAME"], str(path / "database.pgdump")],
                          env=_pg_env(), capture_output=True, timeout=7200)
    if proc.returncode not in (0, 1):  # 1 = warnings (e.g. objects that did not exist)
        raise BackupError(f"Database restore failed: {proc.stderr.decode(errors='replace')[-400:]}")
    restored = 0
    for sub, dest in (("originals", settings.ORIGINALS_DIR), ("derivatives", settings.DERIVATIVES_DIR)):
        src = path / sub
        if not src.exists():
            continue
        for f in src.rglob("*"):
            if f.is_file():
                out = Path(dest) / f.relative_to(src)
                out.parent.mkdir(parents=True, exist_ok=True)
                if not out.exists():
                    shutil.copyfile(f, out)
                    if sub == "originals":
                        os.chmod(out, 0o440)
                        restored += 1
    key_restored = False
    if include_key and (path / "encryption.key").exists():
        kp = crypto.key_path()
        if kp.exists() and kp.read_bytes() != (path / "encryption.key").read_bytes():
            shutil.copyfile(kp, kp.with_suffix(".key.before-restore"))
        kp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path / "encryption.key", kp)
        os.chmod(kp, 0o600)
        crypto.reset_cache()
        key_restored = True
    audit.record("backup.restore", actor=None, actor_label="console", path=path.name, files=restored)
    return {"files_restored": restored, "key_restored": key_restored}
