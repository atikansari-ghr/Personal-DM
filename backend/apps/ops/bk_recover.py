"""Full-system disaster recovery (``personaldocs recover``), for a clean Debian 13 server or a damaged installation.

Personal DM restores the *application* onto a supported clean environment. Recreating the Proxmox host, the LXC
container or the operating system is outside its responsibility (see docs/guides/disaster-recovery.md).

Flow (each step is recorded in <data>/recovery/state.json, so a failed run can be resumed; while it runs
<data>/recovery-in-progress makes the web application answer 503 - a partly recovered instance is never presented
as healthy):

    1 source    where the encrypted packages are (local/USB folder or downloaded .tar, NAS, S3, Google Drive,
                OneDrive). Bootstrap credentials come from the environment/prompt and are used only to fetch;
                they are never stored. The restored, encrypted integration configuration is used afterwards.
    2 key       the Backup Recovery Key, or an Emergency Recovery Package + passphrase
    3 fetch     the chain (base Full + incrementals) is copied into <data>/recovery/work (still encrypted)
    4 verify    encryption, manifest, checksums, chain and application/schema compatibility
    5 analyze   Restore Impact Analysis (what will be replaced; prerequisites)
    6 database  pg_restore --clean into the configured database, then migrate
    7 files     originals, derivatives, profile photos, branding (checksums verified)
    8 secrets   installation encryption key, Django secret key, WhatsApp linked-device session files
    9 security  Normal: keep sessions. Compromise: end all sessions, revoke device trust, flag WhatsApp for relink,
                require a security review. Passkeys and authenticator apps are kept unless --reset-mfa is given.
   10 integrations  all external integrations on hold until a safe connection test passes
   11 validate  counts against the catalogue, file checksums, application health checks
   12 report    Recovery & Security Report (no secrets), stored and printed
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import urllib.parse
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from . import bk_crypto as C
from .bk_destinations import DestError, LocalProvider, iter_stream, provider

STEPS = ("fetch", "verify", "database", "files", "secrets", "security", "integrations", "validate", "report")


class RecoverError(Exception):
    pass


def recovery_dir() -> Path:
    return Path(settings.DATA_DIR) / "recovery"


def marker() -> Path:
    return Path(settings.DATA_DIR) / "recovery-in-progress"


# ------------------------------------------------------------------ sources (bootstrap credentials never stored)

class _Transient:
    """An unsaved destination description for bootstrap retrieval."""

    def __init__(self, kind, cfg):
        self.kind, self.config, self.secret_enc, self.name, self.id = kind, cfg, "", f"recovery source ({kind})", 0


def source_provider(spec: str, env: dict | None = None):
    env = env if env is not None else os.environ
    if ":" not in spec:
        raise RecoverError("Use local:/path, nas:/mounted/path, s3:https://endpoint/bucket/prefix, gdrive:<folder id> or onedrive:<folder>.")
    kind, rest = spec.split(":", 1)
    if kind in ("local", "usb", "nas", "upload"):
        p = Path(rest)
        if p.is_file() and p.suffix == ".tar":
            out = recovery_dir() / "extracted"
            if not (out / ".complete").exists():
                shutil.rmtree(out, ignore_errors=True)
                out.mkdir(parents=True)
                with tarfile.open(p) as tf:
                    tf.extractall(out, filter="data")  # only regular files inside out/ (path traversal refused)
                (out / ".complete").touch()
            p = out
        return LocalProvider(_Transient("local", {"path": str(p)}))
    if kind == "s3":
        u = urllib.parse.urlsplit(rest)
        parts = u.path.strip("/").split("/", 1)
        cfg = {"endpoint": f"{u.scheme}://{u.netloc}", "bucket": parts[0], "prefix": parts[1] if len(parts) > 1 else "personaldocs",
               "region": env.get("PD_RECOVER_S3_REGION", "us-east-1")}
        return provider(_Transient("s3", cfg), {"access_key": env.get("PD_RECOVER_S3_ACCESS_KEY", ""),
                                                 "secret_key": env.get("PD_RECOVER_S3_SECRET_KEY", "")})
    if kind in ("gdrive", "onedrive"):
        cfg = {"folder_id": rest} if kind == "gdrive" else {"folder": rest}
        return provider(_Transient(kind, cfg), {"access_token": env.get("PD_RECOVER_ACCESS_TOKEN", "")})
    raise RecoverError(f"Unknown source type {kind}.")


def list_points(prov) -> list[dict]:
    out = []
    for pid in prov.list_points():
        for gen in range(1, 1000):
            try:
                with prov.open(f"{pid}/g{gen}/header.json") as fh:
                    h = json.loads(fh.read(4 * 1024 * 1024))
                out.append({"point": pid, "generation": gen, "kind": h["kind"], "created_at": h["created_at"], "chain": h["chain"],
                            "app_version": h.get("app_version"), "installation": h.get("installation"),
                            "key_fingerprint": h.get("key_fingerprint")})
                break
            except DestError:
                if gen > 50:
                    break
                continue
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


def key_from(args_key: str | None = None, emergency_file: str | None = None, passphrase: str | None = None) -> bytes:
    if args_key:
        return C.parse_key(args_key)
    if emergency_file:
        return C.open_emergency(json.loads(Path(emergency_file).read_text()), passphrase or "")
    raise RecoverError("Supply the Backup Recovery Key or an Emergency Recovery Package.")


# ------------------------------------------------------------------ state

def load_state() -> dict:
    try:
        return json.loads((recovery_dir() / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    """Progress only: data keys are never written to disk (a resumed run unwraps them again with the key)."""
    recovery_dir().mkdir(parents=True, exist_ok=True)
    os.chmod(recovery_dir(), 0o700)
    tmp = recovery_dir() / "state.tmp"
    tmp.write_text(json.dumps({k: v for k, v in st.items() if k != "deks"}, indent=1, default=str))
    os.replace(tmp, recovery_dir() / "state.json")


# ------------------------------------------------------------------ fetch / verify / analyze

def fetch(prov, point_id: str, raw_key: bytes, say=print) -> dict:
    """Copy the encrypted chain to the work folder (skipping files already fetched intact) and open every header."""
    pts = {p["point"]: p for p in list_points(prov)}
    if point_id == "latest":
        if not pts:
            raise RecoverError("No recovery points found at the source.")
        point_id = next(iter(pts))
    if point_id not in pts:
        raise RecoverError("That recovery point is not at the source.")
    chain = pts[point_id]["chain"]
    work = recovery_dir() / "work"
    headers, deks = {}, {}
    for pid in chain:
        if pid not in pts:
            raise RecoverError(f"The chain is incomplete: recovery point {pid[:8]} (needed by {point_id[:8]}) is missing at the source.")
        gen = pts[pid]["generation"]
        with prov.open(f"{pid}/g{gen}/header.json") as fh:
            head = fh.read()
        h = json.loads(head)
        deks[pid] = C.unwrap_dek(raw_key, h["dek"], pid)  # wrong key fails here, before anything is changed
        base = work / pid
        base.mkdir(parents=True, exist_ok=True)
        (base / "header.json").write_bytes(head)
        for name, meta in sorted(h["files"].items()):
            dst = base / name
            if dst.exists() and dst.stat().st_size == meta["cipher_size"]:
                continue  # resumable
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".part")
            with prov.open(f"{pid}/g{gen}/{name}") as src, open(tmp, "wb") as out:
                for b in iter_stream(src):
                    out.write(b)
            os.replace(tmp, dst)
        headers[pid] = h
        say(f"  fetched {pts[pid]['kind']} {pid[:8]} ({len(h['files'])} files)")
    return {"point": point_id, "chain": chain, "headers": headers, "deks": {k: v.hex() for k, v in deks.items()}}


def _wopen(pid, name):
    return open(recovery_dir() / "work" / pid / name, "rb")


def _component(pid, dek, name) -> dict:
    with _wopen(pid, name) as fh:
        return json.loads(C.decrypt_bytes(fh, dek, name))


def code_migrations() -> dict[str, set]:
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(None, ignore_no_migrations=True, load=False)
    loader.load_disk()
    out: dict[str, set] = {}
    for app, name in loader.disk_migrations:
        out.setdefault(app, set()).add(name)
    return out


def verify(st: dict, say=print) -> dict:
    """Integrity, chain and compatibility checks on the fetched copy."""
    import hashlib

    point = st["point"]
    deks = {k: bytes.fromhex(v) for k, v in st["deks"].items()}
    problems = []
    for pid in st["chain"]:
        h = st["headers"][pid]
        for name, meta in h["files"].items():
            p = recovery_dir() / "work" / pid / name
            hh = hashlib.sha256()
            with open(p, "rb") as fh:
                for b in iter_stream(fh):
                    hh.update(b)
            if hh.hexdigest() != meta["cipher_sha256"]:
                problems.append(f"{pid[:8]}/{name}: checksum mismatch")
                continue
            try:
                with open(p, "rb") as fh:
                    C.digest_and_verify(fh, deks[pid], name)
            except C.DecryptError as exc:
                problems.append(f"{pid[:8]}/{name}: {exc}")
    manifest = _component(point, deks[point], "manifest.enc")
    catalog = _component(point, deks[point], "catalog.enc")
    for name, meta in manifest["inventory"].items():
        if meta.get("missing"):
            continue
        if meta["stored_in"] not in st["chain"]:
            problems.append(f"{name}: stored in a point outside the chain")
    code = code_migrations()
    newer = [f"{app}: {name}" for app, name in manifest["schema"].items() if app in code and name not in code[app]]
    compat = {"backup_app_version": manifest["app_version"], "this_app_version": settings.APP_VERSION,
              "ok": not newer, "detail": "The backup was made by a newer version of Personal DM; upgrade the code first: " + ", ".join(newer[:5]) if newer
              else "Compatible: database migrations of the backup are known to this version (newer ones are applied after the restore)."}
    say(f"  verification: {'OK' if not problems else f'{len(problems)} problem(s)'}; compatibility: {'OK' if compat['ok'] else 'NOT compatible'}")
    return {"problems": problems, "compatibility": compat, "counts": manifest["counts"], "classes": manifest["classes"],
            "catalog_counts": {k: len(catalog.get(k, [])) for k in ("users", "groups", "folders", "documents", "versions", "rules")}}


def current_state() -> dict:
    from django.db import connection

    try:
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('public.library_document') IS NOT NULL")
            if not cur.fetchone()[0]:
                return {"empty": True}
            cur.execute("SELECT (SELECT count(*) FROM accounts_user), (SELECT count(*) FROM library_document)")
            u, d = cur.fetchone()
            return {"empty": u == 0 and d == 0, "users": u, "documents": d}
    except Exception as exc:  # noqa: BLE001
        return {"empty": True, "error": str(exc)[:100]}


def analyze(st: dict, mode: str) -> dict:
    from apps.library import storage

    v = st.get("verification") or {}
    cur = current_state()
    need = sum(sum(m["cipher_size"] for m in h["files"].values()) for h in st["headers"].values())
    free = storage.disk_free_bytes(Path(settings.DATA_DIR)) if Path(settings.DATA_DIR).exists() else None
    actions = ["Replace the database with the backup's state" + ("" if cur.get("empty") else
               f" (the current {cur.get('users', 0)} accounts and {cur.get('documents', 0)} documents are REPLACED)"),
               "Restore document originals, previews, profile photos and branding (checksums verified)",
               "Restore the installation encryption key and secret key (needed to read restored credentials)",
               "Hold every external integration until a connection test passes"]
    if mode == "compromise":
        actions += ["End every Personal DM session and revoke remembered-device trust; everyone signs in again",
                    "Keep passkeys and authenticator apps (unless --reset-mfa)", "Do not reconnect WhatsApp linked devices; require a new QR link",
                    "Require a security review by the main administrator"]
    return {"point": st["point"], "mode": mode, "chain_length": len(st["chain"]), "counts": v.get("catalog_counts"),
            "compatibility": v.get("compatibility"), "problems": v.get("problems", []), "current": cur,
            "storage": {"needed_bytes": need * 2, "free_bytes": free, "ok": free is None or free > need * 2},
            "secrets": v.get("classes", {}).get("secrets", []),
            "prerequisites": {"pg_restore": shutil.which(settings.PG_RESTORE_CMD) is not None or Path(settings.PG_RESTORE_CMD).exists()},
            "actions": actions, "replaces_current_data": not cur.get("empty")}


# ------------------------------------------------------------------ restore steps

def _pg_env() -> dict:
    db = settings.DATABASES["default"]
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PGPASSWORD": db.get("PASSWORD") or "", "PGHOST": db.get("HOST") or "",
            "PGPORT": str(db.get("PORT") or "5432"), "PGUSER": db.get("USER") or "", "PGDATABASE": db.get("NAME")}


def restore_database(st: dict, say=print) -> None:
    from django.core.management import call_command
    from django.db import connection

    point = st["point"]
    dek = bytes.fromhex(st["deks"][point])
    dump = recovery_dir() / "database.pgdump"
    with _wopen(point, "database.enc") as fh:
        C.decrypt_to(fh, dump, dek, "database.enc")
    os.chmod(dump, 0o600)
    connection.close()
    try:
        proc = subprocess.run([settings.PG_RESTORE_CMD, "--clean", "--if-exists", "--no-owner", "--no-privileges",
                               "-d", settings.DATABASES["default"]["NAME"], str(dump)], env=_pg_env(), capture_output=True, timeout=7200)
        if proc.returncode not in (0, 1):
            raise RecoverError(f"Database restore failed: {proc.stderr.decode(errors='replace')[-400:]}")
    finally:
        dump.unlink(missing_ok=True)
    call_command("migrate", interactive=False, verbosity=0)
    from .models import RecoveryPoint

    RecoveryPoint.objects.filter(status=RecoveryPoint.RUNNING).delete()  # rows of backups in progress at dump time
    say("  database restored and migrated")


def restore_files(st: dict, say=print) -> dict:
    point = st["point"]
    deks = {k: bytes.fromhex(v) for k, v in st["deks"].items()}
    manifest = _component(point, deks[point], "manifest.enc")
    from apps.accounts.photos import photo_dir
    from apps.core.branding import branding_dir

    roots = {"original": Path(settings.ORIGINALS_DIR), "derivative": Path(settings.DERIVATIVES_DIR), "photo": photo_dir(),
             "branding": branding_dir()}
    restored, skipped, bad = 0, 0, []
    for name, meta in manifest["inventory"].items():
        if meta.get("missing"):
            skipped += 1
            continue
        dst = roots[meta["type"]] / meta["path"]
        if not str(dst.resolve()).startswith(str(roots[meta["type"]].resolve())):
            bad.append(name)
            continue
        if dst.exists() and meta["type"] == "original" and C_sha(dst) == meta["sha256"]:
            restored += 1
            continue
        with _wopen(meta["stored_in"], name) as fh:
            sha = C.decrypt_to(fh, dst, deks[meta["stored_in"]], name)
        if sha != meta["sha256"]:
            bad.append(name)
            dst.unlink(missing_ok=True)
            continue
        os.chmod(dst, 0o440 if meta["type"] == "original" else 0o640)
        restored += 1
    say(f"  {restored} files restored, {skipped} were missing at backup time, {len(bad)} failed")
    return {"restored": restored, "missing_at_backup": skipped, "failed": len(bad)}


def C_sha(path: Path) -> str:
    from apps.core import crypto

    return crypto.sha256_file(path)


def restore_secrets(st: dict, say=print) -> list[str]:
    import base64

    from apps.core import crypto

    point = st["point"]
    sec = _component(point, bytes.fromhex(st["deks"][point]), "secrets.enc")
    done = []
    for name, b64 in sec.get("files", {}).items():
        data = base64.b64decode(b64)
        if name == "encryption.key":
            dst = crypto.key_path()
        elif name == "secret_key":
            dst = Path(settings.CONFIG_DIR) / "secret_key"
        elif name.startswith("whatsapp/"):
            dst = Path(settings.DATA_DIR) / "whatsapp" / "sessions" / name.split("/", 1)[1]
        else:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.read_bytes() != data:
            shutil.copyfile(dst, dst.with_name(dst.name + ".before-recovery"))
        tmp = dst.with_name(dst.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dst)
        done.append(name if not name.startswith("whatsapp/") else "whatsapp session")
    crypto.reset_cache()
    say(f"  restored secrets: {', '.join(sorted(set(done)))}")
    return sorted(set(done))


def security_actions(mode: str, reset_mfa: bool = False) -> dict:
    from django.contrib.sessions.models import Session
    from django.db.models import F

    from apps.accounts.models import User, UserSession

    out = {"mode": mode}
    if mode != "compromise":
        out["sessions"] = "kept (normal disaster recovery)"
        return out
    out["sessions_ended"] = UserSession.objects.filter(revoked_at__isnull=True, ended_at__isnull=True).update(revoked_at=timezone.now())
    Session.objects.all().delete()
    User.objects.update(session_epoch=F("session_epoch") + 1)
    try:
        from apps.security.models import RecognizedDevice

        out["devices_untrusted"] = RecognizedDevice.objects.filter(revoked_at__isnull=True).update(
            revoked_at=timezone.now(), status="unrecognized")
    except Exception:  # noqa: BLE001 - before the security migration
        out["devices_untrusted"] = 0
    if reset_mfa:
        from apps.accounts.models import RecoveryCode, WebAuthnCredential

        out["mfa_reset"] = User.objects.filter(totp_enabled=True).update(totp_enabled=False, totp_secret_enc="")
        WebAuthnCredential.objects.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        RecoveryCode.objects.all().delete()
    else:
        out["mfa"] = "passkeys and authenticator apps preserved"
    from apps.security.models import HealthState

    HealthState.put("security_review", required=True, reason="Compromise/Cyberattack recovery", since=timezone.now().isoformat())
    return out


def validate(st: dict) -> list[dict]:
    from apps.accounts.models import User
    from apps.library.models import Document, DocumentVersion, Folder

    v = st.get("verification", {}).get("catalog_counts", {})
    checks = []
    now = {"users": User.objects.count(), "folders": Folder.objects.count(), "documents": Document.objects.count(),
           "versions": DocumentVersion.objects.count()}
    for k, n in now.items():
        checks.append({"check": f"{k.title()} restored", "ok": n == v.get(k), "detail": f"{n} (backup: {v.get(k)})"})
    missing = 0
    for ver in DocumentVersion.objects.exclude(av_status="quarantined").only("storage_path"):
        if not (Path(settings.ORIGINALS_DIR) / ver.storage_path).exists():
            missing += 1
    checks.append({"check": "Every document version has its original file", "ok": missing == 0, "detail": f"{missing} missing"})
    from apps.core import config, crypto

    try:
        crypto.reset_cache()
        for key in ("smtp.password", "telegram.bot_token"):
            if config.is_set(key):
                config.get(key)
        checks.append({"check": "Restored secrets readable with the restored key", "ok": True, "detail": ""})
    except Exception as exc:  # noqa: BLE001
        checks.append({"check": "Restored secrets readable with the restored key", "ok": False, "detail": str(exc)[:120]})
    from django.core.management import call_command

    try:
        call_command("check", verbosity=0)
        checks.append({"check": "Application health checks (manage.py check)", "ok": True, "detail": ""})
    except Exception as exc:  # noqa: BLE001
        checks.append({"check": "Application health checks (manage.py check)", "ok": False, "detail": str(exc)[:200]})
    return checks


SECRET_WORDS = ("password", "token", "secret", "webhook", "PDRK1", "key_enc", "session")


def build_report(st: dict, mode: str, checks: list, integrations: dict, security: dict, files: dict) -> dict:
    v = st.get("verification", {})
    failed = [c for c in checks if not c["ok"]]
    follow = ["Review the Recovery & Security Report and keep the exported copy offline.",
              "Run a Full backup now (Settings → Storage & backup → Backup & Recovery → Back up now).",
              "Export a new Emergency Recovery Package if the key generation changed."]
    for i in integrations.get("items", []):
        if i["state"] != "verified":
            follow.append(f"{i['label']}: {i['state_label']} - {i.get('detail') or 'open Settings to fix it'}")
    if mode == "compromise":
        follow = ["Complete the security review: change the main administrator password, review every account, passkey and "
                  "authenticator app, and the sign-in map.", "Rotate the Backup Recovery Key and export a new Emergency Recovery Package.",
                  "Re-link WhatsApp Personal with a fresh QR code; re-check Discord webhooks and other cloud credentials."] + follow
    report = {"title": "Recovery & Security Report", "generated_at": timezone.now().isoformat(), "mode": mode,
              "restore_point": {"id": st["point"], "kind": st["headers"][st["point"]]["kind"],
                                "created_at": st["headers"][st["point"]]["created_at"], "chain": st["chain"]},
              "integrity": {"problems": v.get("problems", [])[:50], "chain_verified": not v.get("problems")},
              "compatibility": v.get("compatibility"),
              "restored": {**(v.get("catalog_counts") or {}), "files": files},
              "users_and_permissions": {"users": (v.get("catalog_counts") or {}).get("users"), "rules": (v.get("catalog_counts") or {}).get("rules"),
                                        "groups": (v.get("catalog_counts") or {}).get("groups")},
              "database": {"migrated_to_current_schema": True},
              "settings": {"restored": True},
              "integrations": integrations.get("items", []),
              "whatsapp": next((i for i in integrations.get("items", []) if i["key"] == "channel:whatsapp"), None),
              "session_and_device_trust": security,
              "checks": checks, "warnings": [c["check"] + ": " + c["detail"] for c in failed],
              "failed_items": files.get("failed", 0), "status": "completed" if not failed else "completed_with_warnings",
              "follow_up": follow}
    text = json.dumps(report)
    assert "PDRK1-" not in text  # the report never contains the key
    return report


def run(prov, point_id: str, raw_key: bytes, *, mode: str = "normal", reset_mfa: bool = False, say=print, resume: bool = True) -> dict:
    if mode not in ("normal", "compromise"):
        raise RecoverError("Mode must be normal or compromise.")
    st = load_state() if resume else {}
    if st and (st.get("point") not in (point_id, None) and point_id != "latest"):
        st = {}
    marker().parent.mkdir(parents=True, exist_ok=True)
    marker().write_text(json.dumps({"started_at": timezone.now().isoformat(), "mode": mode}))
    done = set(st.get("done", []))
    if st.get("headers") and "deks" not in st:
        st["deks"] = {pid: C.unwrap_dek(raw_key, h["dek"], pid).hex() for pid, h in st["headers"].items()}
    try:
        if "fetch" not in done:
            say("Step 1/9  fetching the encrypted recovery packages")
            st.update(fetch(prov, point_id, raw_key, say))
            st["mode"] = mode
            done.add("fetch")
            st["done"] = sorted(done)
            save_state(st)
        if "verify" not in done:
            say("Step 2/9  verifying integrity, chain and compatibility")
            st["verification"] = verify(st, say)
            if st["verification"]["problems"]:
                raise RecoverError("Verification failed: " + "; ".join(st["verification"]["problems"][:3]))
            if not st["verification"]["compatibility"]["ok"]:
                raise RecoverError(st["verification"]["compatibility"]["detail"])
            done.add("verify")
            st["done"] = sorted(done)
            save_state(st)
        if "database" not in done:
            say("Step 3/9  restoring the database")
            restore_database(st, say)
            done.add("database")
            st["done"] = sorted(done)
            save_state(st)
        if "files" not in done:
            say("Step 4/9  restoring documents and files")
            st["files"] = restore_files(st, say)
            done.add("files")
            st["done"] = sorted(done)
            save_state(st)
        if "secrets" not in done:
            say("Step 5/9  restoring encrypted secrets")
            st["secrets"] = restore_secrets(st, say)
            done.add("secrets")
            st["done"] = sorted(done)
            save_state(st)
        if "security" not in done:
            say(f"Step 6/9  {'compromise recovery: resetting sessions and device trust' if mode == 'compromise' else 'normal recovery: sessions kept'}")
            st["security"] = security_actions(mode, reset_mfa)
            done.add("security")
            st["done"] = sorted(done)
            save_state(st)
        from . import bk_integrations as I

        if "integrations" not in done:
            say("Step 7/9  verifying external integrations before activating them")
            I.start_hold(mode)
            I.verify()
            done.add("integrations")
            st["done"] = sorted(done)
            save_state(st)
        say("Step 8/9  validating the restored installation")
        checks = validate(st)
        say("Step 9/9  writing the Recovery & Security Report")
        report = build_report(st, mode, checks, I.summary(), st.get("security", {}), st.get("files", {}))
        from apps.core import audit

        from .models import RestoreRun

        rr = RestoreRun.objects.create(kind="full", recovery_mode=mode, point_label=f"{report['restore_point']['kind']} {report['restore_point']['created_at'][:16]}",
                                       status="completed" if report["status"] == "completed" else "partial",
                                       impact=analyze(st, mode), result={"summary": f"Full system recovery ({mode}) {report['status'].replace('_', ' ')}",
                                                                        "checks": checks}, report=report, actor_label="console",
                                       finished_at=timezone.now())
        audit.record("recovery.full", actor=None, actor_label="console", mode=mode, point=st["point"], status=rr.status)
        if mode == "compromise":
            audit.record("recovery.compromise_mode", actor=None, actor_label="console", point=st["point"])
        from apps.notify import events

        events.backup_event("recovery.compromise" if mode == "compromise" else "recovery.full",
                            detail=f"Restored recovery point {st['point'][:8]} ({mode} mode). Open the Recovery & Security Report.",
                            tag=str(rr.id))
        report["run"] = str(rr.id)
        (recovery_dir() / f"report-{rr.id}.json").write_text(json.dumps(report, indent=1, default=str))
        shutil.rmtree(recovery_dir() / "work", ignore_errors=True)
        shutil.rmtree(recovery_dir() / "extracted", ignore_errors=True)
        (recovery_dir() / "state.json").unlink(missing_ok=True)
        marker().unlink(missing_ok=True)  # only now does the application open again
        return report
    except Exception:
        st["done"] = sorted(done)
        st["failed_at"] = timezone.now().isoformat()
        save_state(st)
        raise  # the marker stays: the instance is not presented as healthy; re-run to resume
