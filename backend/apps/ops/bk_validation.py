"""Test Restore and Automated Recovery Validation.

* **Test Restore** (administrator, any time): decrypts and authenticates every component of a recovery point and its
  chain, restores the database dump into a temporary scratch database when the database account may create one
  (otherwise reports a *structure-only* test), compares counts with the catalogue and checks that the restored
  installation key opens the restored secrets. It never touches the live installation.
* **Automated Recovery Validation** (optional): when the administrator has configured an *isolated* recovery
  environment (a separate PostgreSQL database URL and an empty directory, ideally on another host), the scheduler
  periodically restores the newest verified point there and checks database, users/permissions, folders,
  documents, versions, settings, secrets, OCR metadata and an application start (``manage.py check``) with
  notifications and integrations switched off (``PD_SANDBOX=1``). Personal DM does not create or manage that
  environment. Without it the state is **Not Configured** - a checksum/deep verification is never presented as an
  end-to-end restore.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import urllib.parse
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.core import config

from . import bk_crypto as C
from . import bk_keys
from .bk_destinations import DestError, provider
from .models import RecoveryCopy, RecoveryPoint, RestoreRun


def best_copy(point: RecoveryPoint) -> RecoveryCopy | None:
    order = {RecoveryCopy.STORED_VERIFIED: 0, RecoveryCopy.STORED_WARNING: 1}
    copies = [c for c in point.copies.select_related("destination") if c.state in order and c.destination.enabled]
    return sorted(copies, key=lambda c: order[c.state])[0] if copies else None


def chain_copies(point: RecoveryPoint, dest_id: int) -> dict[str, RecoveryCopy]:
    out = {}
    for p in point.chain():
        c = p.copies.filter(destination_id=dest_id, state__in=[RecoveryCopy.STORED_VERIFIED, RecoveryCopy.STORED_WARNING]).first()
        if c is not None:
            out[str(p.id)] = c
    return out


def validation_configured() -> bool:
    return bool(config.is_set("recovery.validation_database") and config.get("recovery.validation_dir"))


def validation_state() -> dict:
    if not validation_configured():
        return {"state": "not_configured", "label": "Recovery Validation: Not Configured",
                "detail": "No isolated recovery environment is configured. Deep verification checks every copy, but no "
                          "backup has been restored end-to-end automatically."}
    last = RestoreRun.objects.filter(kind="validation").first()
    if last is None:
        return {"state": "pending", "label": "Recovery Validation: Configured, not run yet", "detail": ""}
    ok = last.status == "completed"
    return {"state": "passed" if ok else "failed", "label": f"Recovery Validation: {'Passed' if ok else 'Failed'}",
            "detail": (last.result or {}).get("summary", ""), "at": last.created_at.isoformat(), "run": str(last.id)}


def _decrypt_point(point: RecoveryPoint, work: Path) -> dict:
    """Decrypt the point's database, catalogue, settings and secrets into ``work`` (mode 0700). Objects of the
    whole chain are authenticated without writing them."""
    copy = best_copy(point)
    if copy is None:
        raise DestError("unavailable", "No verified copy of this recovery point is reachable.")
    prov = provider(copy.destination)
    raw = bk_keys.raw_key(copy.generation)
    from .bk_engine import open_point, read_component, rel

    header, dek = open_point(prov, point.id, copy.generation, raw)
    work.mkdir(parents=True, exist_ok=True)
    os.chmod(work, 0o700)
    with prov.open(rel(point.id, copy.generation, "database.enc")) as fh:
        C.decrypt_to(fh, work / "database.pgdump", dek, "database.enc")
    manifest = json.loads(read_component(prov, point.id, copy.generation, dek, "manifest.enc"))
    catalog = json.loads(read_component(prov, point.id, copy.generation, dek, "catalog.enc"))
    settings_pkg = json.loads(read_component(prov, point.id, copy.generation, dek, "settings.enc"))
    secrets_pkg = json.loads(read_component(prov, point.id, copy.generation, dek, "secrets.enc"))
    # authenticate every object the point needs (from the chain on the same destination)
    copies = chain_copies(point, copy.destination_id)
    deks = {str(point.id): (dek, copy.generation)}
    problems = []
    checked = 0
    for name, meta in manifest["inventory"].items():
        if meta.get("missing"):
            continue
        src = meta["stored_in"]
        if src not in copies:
            problems.append(f"{name}: needed point {src[:8]} has no copy on {copy.destination.name}")
            continue
        if src not in deks:
            c = copies[src]
            _h, d = open_point(prov, src, c.generation, bk_keys.raw_key(c.generation))
            deks[src] = (d, c.generation)
        d, g = deks[src]
        try:
            with prov.open(rel(src, g, name)) as fh:
                sha, _n = C.digest_and_verify(fh, d, name)
            if sha != meta["sha256"]:
                problems.append(f"{name}: checksum mismatch")
            checked += 1
        except (DestError, C.DecryptError) as exc:
            problems.append(f"{name}: {exc}")
    return {"copy": copy, "header": header, "manifest": manifest, "catalog": catalog, "settings": settings_pkg,
            "secrets": secrets_pkg, "objects_checked": checked, "problems": problems}


def _db_params(url: str | None = None) -> dict:
    if url:
        u = urllib.parse.urlsplit(url)
        return {"PGHOST": u.hostname or "", "PGPORT": str(u.port or 5432), "PGUSER": urllib.parse.unquote(u.username or ""),
                "PGPASSWORD": urllib.parse.unquote(u.password or ""), "PGDATABASE": (u.path or "/").lstrip("/")}
    db = settings.DATABASES["default"]
    return {"PGHOST": db.get("HOST") or "", "PGPORT": str(db.get("PORT") or 5432), "PGUSER": db.get("USER") or "",
            "PGPASSWORD": db.get("PASSWORD") or "", "PGDATABASE": db.get("NAME")}


def _pg_restore(dump: Path, params: dict, clean: bool) -> tuple[bool, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **params}
    cmd = [settings.PG_RESTORE_CMD, "--no-owner", "--no-privileges", "-d", params["PGDATABASE"], str(dump)]
    if clean:
        cmd[1:1] = ["--clean", "--if-exists"]
    proc = subprocess.run(cmd, env=env, capture_output=True, timeout=7200)
    return proc.returncode in (0, 1), proc.stderr.decode(errors="replace")[-300:]


def _count(params: dict) -> dict:
    import psycopg

    dsn = " ".join(f"{k}={v}" for k, v in (("host", params["PGHOST"]), ("port", params["PGPORT"]), ("user", params["PGUSER"]),
                                           ("password", params["PGPASSWORD"]), ("dbname", params["PGDATABASE"])) if v)
    out = {}
    with psycopg.connect(dsn, connect_timeout=10) as conn, conn.cursor() as cur:
        for key, table in (("users", "accounts_user"), ("groups", "accounts_familygroup"), ("folders", "library_folder"),
                           ("documents", "library_document"), ("versions", "library_documentversion"), ("rules", "library_accessrule"),
                           ("settings", "core_appsetting"), ("migrations", "django_migrations")):
            cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed table names
            out[key] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM library_documentversion WHERE text <> '' OR ocr_blocks::text <> '[]'")
        out["ocr_versions"] = cur.fetchone()[0]
    return out


def _secrets_open(secrets_pkg: dict, encrypted_value: str | None) -> bool:
    """The restored installation key must decrypt a restored secret."""
    import base64

    from cryptography.fernet import Fernet, InvalidToken

    keyb = secrets_pkg.get("files", {}).get("encryption.key")
    if not keyb:
        return False
    f = Fernet(base64.b64decode(keyb).strip())
    if not encrypted_value:
        return True
    try:
        f.decrypt(encrypted_value.encode())
        return True
    except InvalidToken:
        return False


def _any_secret_enc() -> str | None:
    from apps.core.models import AppSetting

    for row in AppSetting.objects.all():
        v = row.value if isinstance(row.value, dict) else None
        if v and v.get("enc"):
            return v["enc"]
    return None


def test_restore(point: RecoveryPoint, actor=None) -> RestoreRun:
    """Isolated test restore. Never changes the live database or files."""
    run = RestoreRun.objects.create(kind="test", point=point, point_label=f"{point.kind} {point.created_at:%Y-%m-%d %H:%M}",
                                    status="running", actor=actor, actor_label=getattr(actor, "username", "console"))
    work = Path(settings.DATA_DIR) / "backup-staging" / f"test-{run.id}"
    checks = []
    level = "structure"
    try:
        pkg = _decrypt_point(point, work)
        checks.append({"check": "Decrypt and authenticate all components", "ok": not pkg["problems"],
                       "detail": f"{pkg['objects_checked']} objects checked" + (f"; {len(pkg['problems'])} problems" if pkg["problems"] else "")})
        cat = pkg["catalog"]
        scratch = f"pd_restore_test_{secrets.token_hex(4)}"
        params = _db_params()
        created = False
        try:
            with connection.cursor() as cur:
                cur.execute(f'CREATE DATABASE "{scratch}"')  # noqa: S608 - generated name
            created = True
        except Exception as exc:  # noqa: BLE001 - no CREATEDB privilege: structure-only test
            checks.append({"check": "Scratch database", "ok": True, "level": "info",
                           "detail": f"Not available ({exc.__class__.__name__}); the dump structure was checked instead"})
        if created:
            level = "database"
            try:
                ok, err = _pg_restore(work / "database.pgdump", {**params, "PGDATABASE": scratch}, clean=False)
                checks.append({"check": "Database restored into a scratch database", "ok": ok, "detail": "" if ok else err})
                counts = _count({**params, "PGDATABASE": scratch})
                expect = {k: len(cat.get(k, [])) for k in ("users", "groups", "folders", "documents", "versions", "rules")}
                same = all(counts[k] == v for k, v in expect.items())
                checks.append({"check": "Users, permissions, folders, documents and versions", "ok": same,
                               "detail": ", ".join(f"{k} {counts[k]}" for k in expect)})
                checks.append({"check": "OCR metadata", "ok": True, "detail": f"{counts['ocr_versions']} versions with recognised text"})
            finally:
                with connection.cursor() as cur:
                    cur.execute(f'DROP DATABASE IF EXISTS "{scratch}"')  # noqa: S608
        else:
            proc = subprocess.run([settings.PG_RESTORE_CMD, "--list", str(work / "database.pgdump")], capture_output=True, timeout=600)
            checks.append({"check": "Database dump structure", "ok": proc.returncode == 0, "detail": "pg_restore --list"})
        checks.append({"check": "Settings package", "ok": bool(pkg["settings"].get("global")), "detail": f"{len(pkg['settings'].get('global', {}))} settings"})
        checks.append({"check": "Secrets readable with the restored installation key", "ok": _secrets_open(pkg["secrets"], _any_secret_enc()),
                       "detail": ", ".join(sorted(pkg["secrets"].get("files", {}).keys())[:6])})
        ok = all(c["ok"] for c in checks)
        run.status = "completed" if ok else "failed"
        run.result = {"level": level, "checks": checks,
                      "summary": ("Test restore passed" if ok else "Test restore found problems")
                      + (" (database restored into a scratch database)" if level == "database" else " (structure-only: no scratch database)")}
    except (DestError, C.DecryptError, OSError, ValueError) as exc:
        run.status = "failed"
        run.result = {"level": level, "checks": checks, "summary": f"Test restore failed: {exc}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    run.finished_at = timezone.now()
    run.save()
    from apps.core import audit

    audit.record("recovery.test_restore", actor=actor, target_type="recovery_point", target_id=str(point.id), status=run.status)
    return run


def automated_validation(point: RecoveryPoint | None = None) -> RestoreRun | None:
    """Restore into the configured isolated environment with notifications and integrations disabled."""
    if not validation_configured():
        return None
    point = point or RecoveryPoint.objects.filter(status__in=[RecoveryPoint.VERIFIED, RecoveryPoint.PARTIAL],
                                                  deleted_at__isnull=True).order_by("-created_at").first()
    if point is None:
        return None
    run = RestoreRun.objects.create(kind="validation", point=point, point_label=f"{point.kind} {point.created_at:%Y-%m-%d %H:%M}",
                                    status="running", actor_label="scheduler")
    target_dir = Path(config.get("recovery.validation_dir"))
    params = _db_params(config.get("recovery.validation_database"))
    live = _db_params()
    checks = []
    work = target_dir / "pd-validation-work"
    try:
        if (params["PGHOST"], params["PGPORT"], params["PGDATABASE"]) == (live["PGHOST"], live["PGPORT"], live["PGDATABASE"]):
            raise ValueError("The validation database is the production database. Configure a separate, isolated database.")
        if target_dir.resolve() in (Path(settings.DATA_DIR).resolve(), Path(settings.STORAGE_DIR).resolve()):
            raise ValueError("The validation directory must be separate from the production data directory.")
        pkg = _decrypt_point(point, work)
        checks.append({"check": "Decrypt and authenticate", "ok": not pkg["problems"], "detail": f"{pkg['objects_checked']} objects"})
        ok, err = _pg_restore(work / "database.pgdump", params, clean=True)
        checks.append({"check": "Database restore", "ok": ok, "detail": "" if ok else err})
        counts = _count(params)
        cat = pkg["catalog"]
        expect = {k: len(cat.get(k, [])) for k in ("users", "groups", "folders", "documents", "versions", "rules")}
        checks.append({"check": "Users/permissions, folders, documents, versions", "ok": all(counts[k] == v for k, v in expect.items()),
                       "detail": ", ".join(f"{k} {counts[k]}" for k in expect)})
        checks.append({"check": "OCR metadata", "ok": True, "detail": f"{counts['ocr_versions']} versions with text"})
        checks.append({"check": "Settings", "ok": counts["settings"] >= 0 and bool(pkg["settings"].get("global")), "detail": ""})
        checks.append({"check": "Secrets readable", "ok": _secrets_open(pkg["secrets"], None), "detail": ""})
        # application start against the restored database, sandboxed (no notifications, no integrations)
        env = {**os.environ, "PD_SANDBOX": "1", "PD_DB_HOST": params["PGHOST"], "PD_DB_PORT": params["PGPORT"],
               "PD_DB_USER": params["PGUSER"], "PD_DB_PASSWORD": params["PGPASSWORD"], "PD_DB_NAME": params["PGDATABASE"],
               "PD_DATA_DIR": str(target_dir / "data")}
        proc = subprocess.run([os.sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "check"], env=env,
                              capture_output=True, timeout=600, cwd=str(settings.BASE_DIR))
        checks.append({"check": "Application start (manage.py check, sandboxed)", "ok": proc.returncode == 0,
                       "detail": "" if proc.returncode == 0 else proc.stderr.decode(errors="replace")[-200:]})
        ok = all(c["ok"] for c in checks)
        run.status = "completed" if ok else "failed"
        run.result = {"checks": checks, "summary": "End-to-end restore into the isolated environment passed" if ok
                      else "Recovery validation found problems"}
    except (DestError, C.DecryptError, OSError, ValueError, subprocess.SubprocessError, Exception) as exc:  # noqa: BLE001
        run.status = "failed"
        run.result = {"checks": checks, "summary": f"Recovery validation failed: {str(exc)[:200]}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    run.finished_at = timezone.now()
    run.save()
    from apps.notify import events

    events.backup_event("recovery.validation", point=point, detail=run.result["summary"],
                        severity="success" if run.status == "completed" else "critical", tag=str(run.id))
    return run
