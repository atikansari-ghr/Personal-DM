"""Antivirus scanning with the local ClamAV daemon (clamd) over its Unix socket.

Lifecycle of every stored file (``DocumentVersion.av_status``)::

    upload -> pending -> clean | not_scanned | size_limit | failed | threat -> quarantined [-> released]

* Uploads are never blocked: the file is stored and usable at once, then scanned by a background job.
* Fail-open: if clamd is unreachable the file stays available and is marked *Not scanned*; administrators get a
  critical alert. A file larger than ``antivirus.max_scan_mb`` is *Not scanned — size limit exceeded*, never "clean".
* Archives (ZIP, RAR, ...) are scanned as one file by clamd with its default archive limits. The application does
  not unpack them itself, so "clean" on an archive does not prove every member was inspected.
* A detected threat is moved to ``<data>/quarantine`` (mode 0400) and its preview, download, OCR and local-AI
  processing are blocked. Only the main administrator can release it (warning, confirmation and a reason).
* Only file names, sizes, detection names and versions are logged — never file contents or extracted text.
"""
from __future__ import annotations

import logging
import os
import shutil
import socket
import struct
import subprocess
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import audit, config, jobs

log = logging.getLogger("personaldocs.antivirus")

CHUNK = 64 * 1024
STATUS_LABELS = {
    "pending": "Scan pending", "clean": "Clean", "not_scanned": "Not scanned", "size_limit": "Not scanned — size limit exceeded",
    "failed": "Scan failed", "threat": "Threat detected", "quarantined": "Quarantined", "released": "Released from quarantine",
}


class ScannerUnavailable(Exception):
    pass


class ScanError(Exception):
    pass


# ------------------------------------------------------------------ clamd client

def _connect(timeout: float = 30.0) -> socket.socket:
    path = config.get("antivirus.socket")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(path)
    except (OSError, socket.timeout) as exc:
        sock.close()
        raise ScannerUnavailable(f"ClamAV is not reachable at {path} ({exc.__class__.__name__}).") from exc
    return sock


def _recv_all(sock: socket.socket) -> str:
    data = b""
    while True:
        part = sock.recv(4096)
        if not part:
            break
        data += part
        if data.endswith(b"\0"):
            break
    return data.rstrip(b"\0").decode("utf-8", "replace").strip()


def command(cmd: str, timeout: float = 10.0) -> str:
    sock = _connect(timeout)
    try:
        sock.sendall(f"z{cmd}\0".encode())
        return _recv_all(sock)
    except (OSError, socket.timeout) as exc:
        raise ScannerUnavailable(f"ClamAV did not answer ({exc.__class__.__name__}).") from exc
    finally:
        sock.close()


def ping() -> bool:
    try:
        return command("PING") == "PONG"
    except ScannerUnavailable:
        return False


def _parse_date(text: str):
    try:
        return timezone.make_aware(datetime.strptime(" ".join(text.split()), "%a %b %d %H:%M:%S %Y"), dt_timezone.utc).isoformat()
    except ValueError:
        return None


DB_DIR = Path("/var/lib/clamav")


def _database_header() -> dict:
    """Newest signature database header (daily.cld/.cvd: 'ClamAV-VDB:07 Oct 2026 06-24 +0000:28146:...')."""
    best = {}
    for name in ("daily.cld", "daily.cvd"):
        p = DB_DIR / name
        try:
            head = p.read_bytes()[:512].decode("ascii", "replace")
        except OSError:
            continue
        parts = head.split(":")
        if len(parts) > 3 and parts[0] == "ClamAV-VDB":
            try:
                when = datetime.strptime(parts[1], "%d %b %Y %H-%M %z").astimezone(dt_timezone.utc)
            except ValueError:
                when = None
            if not best or (parts[2].isdigit() and int(parts[2]) > int(best.get("signatures") or 0)):
                best = {"signatures": parts[2], "signatures_date": when.isoformat() if when else None}
    return best


def version_info() -> dict:
    """``ClamAV 1.4.3/27800/Tue Oct  6 07:34:01 2026`` -> engine, signature version and signature date.

    Debian/Ubuntu ship clamd with EnableVersionCommand off; then the signature version is read from the database
    file header instead (the installer turns the command on)."""
    raw = command("VERSION")
    if raw.startswith("COMMAND UNAVAILABLE"):
        engine = "ClamAV"
        try:
            out = subprocess.run(["clamd", "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
            engine = out.split("/")[0] or engine
        except (OSError, subprocess.SubprocessError):
            pass
        return {"raw": "", "engine": engine, **{"signatures": None, "signatures_date": None}, **_database_header()}
    parts = raw.split("/")
    out = {"raw": raw, "engine": parts[0].strip(), "signatures": None, "signatures_date": None}
    if len(parts) >= 3:
        out["signatures"] = parts[1].strip()
        out["signatures_date"] = _parse_date(parts[2])
    return out


def scan_path(path: Path) -> tuple[str, str]:
    """Stream a file to clamd. Returns ("clean", "") or ("threat", signature). Raises on errors."""
    sock = _connect(timeout=300)
    try:
        sock.sendall(b"zINSTREAM\0")
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(CHUNK)
                if not chunk:
                    break
                sock.sendall(struct.pack("!L", len(chunk)) + chunk)
        sock.sendall(struct.pack("!L", 0))
        reply = _recv_all(sock)
    except (OSError, socket.timeout) as exc:
        # clamd answers "INSTREAM size limit exceeded" and closes while we are still sending: read that answer
        reply = ""
        try:
            reply = _recv_all(sock)
        except OSError:
            pass
        if not reply:
            raise ScannerUnavailable(f"The connection to ClamAV broke during the scan ({exc.__class__.__name__}).") from exc
    finally:
        sock.close()
    if reply.endswith("OK") and "FOUND" not in reply:
        return "clean", ""
    if reply.endswith("FOUND"):
        name = reply.split(":", 1)[-1].rsplit("FOUND", 1)[0].strip()
        return "threat", name[:200] or "unknown threat"
    if "size limit" in reply.lower():
        raise ScanError("size_limit")
    raise ScanError(reply[:200] or "empty reply")


# ------------------------------------------------------------------ health

def health(refresh: bool = False) -> dict:
    """Reachability and signature age, cached in HealthState('antivirus')."""
    from .models import HealthState

    state = HealthState.get("antivirus")
    if not config.get("antivirus.enabled"):
        return {**state, "enabled": False, "status": "disabled"}
    fresh = state.get("checked_at") and timezone.now() - datetime.fromisoformat(state["checked_at"]) < timedelta(minutes=5)
    if refresh or not fresh:
        try:
            info = version_info()
            state = HealthState.put("antivirus", reachable=True, engine=info["engine"], signatures=info["signatures"],
                                    signatures_date=info["signatures_date"], error="", checked_at=timezone.now().isoformat())
        except ScannerUnavailable as exc:
            state = HealthState.put("antivirus", reachable=False, error=str(exc)[:300], checked_at=timezone.now().isoformat())
    age_days = None
    if state.get("signatures_date"):
        age_days = (timezone.now() - datetime.fromisoformat(state["signatures_date"])).total_seconds() / 86400
    stale = age_days is not None and age_days > int(config.get("antivirus.stale_days"))
    critical = age_days is not None and age_days > int(config.get("antivirus.critical_stale_days"))
    status = "unavailable" if not state.get("reachable") else "critical_stale" if critical else "stale" if stale else "ok"
    return {**state, "enabled": True, "status": status, "signature_age_days": round(age_days, 1) if age_days is not None else None,
            "stale": stale, "critically_stale": critical}


def _alert(event: str, key: str, title: str, lines: list[str], link: str = "/settings/security?view=antivirus") -> None:
    from apps.notify import events

    for admin in events._admins():
        events.notify(admin, event, kind=event, key=key, title=title, lines=lines, link=link)


def check_health_and_alert() -> dict:
    """Hourly from the scheduler: alert administrators (once a day per problem) when clamd or signatures are unhealthy."""
    h = health(refresh=True)
    day = timezone.localdate().isoformat()
    if h["status"] == "unavailable":
        _alert("antivirus.unavailable", f"av_down:{day}", "Antivirus (ClamAV) is unavailable",
               ["New files are stored and usable but marked Not scanned until ClamAV is back.",
                "On the server: sudo personaldocs doctor"])
    elif h["status"] in ("stale", "critical_stale"):
        _alert("antivirus.definitions", f"av_stale:{day}", "Antivirus definitions are out of date",
               [f"Signatures are {h['signature_age_days']} days old.", "Use Update now, or check clamav-freshclam on the server."])
    from .models import HealthState

    upd = HealthState.get("freshclam")
    if upd.get("ok") is False and upd.get("finished_at", "")[:10] == day:
        _alert("antivirus.definitions", f"av_update_fail:{day}", "Antivirus signature update failed",
               [f"Error: {str(upd.get('error') or 'unknown')[:200]}"])
    return h


# ------------------------------------------------------------------ scanning

def quarantine_dir() -> Path:
    d = Path(settings.DATA_DIR) / "quarantine"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def on_new_version(version) -> None:
    """Called in the upload transaction: mark the file pending and queue the scan after commit."""
    from apps.library.models import DocumentVersion

    if not config.get("antivirus.enabled"):
        DocumentVersion.objects.filter(pk=version.pk).update(av_status="not_scanned", av_detail="Antivirus scanning is turned off.")
        version.av_status = "not_scanned"
        return
    DocumentVersion.objects.filter(pk=version.pk).update(av_status="pending", av_detail="")
    version.av_status = "pending"
    transaction.on_commit(lambda: jobs.enqueue("av_scan", {"version_id": str(version.id)}, max_attempts=1,
                                               idempotency_key=f"av:{version.id}:upload"))


def scan_version(version, *, actor=None, run=None) -> str:
    """Scan one stored file and record the result. Returns the new status."""
    from apps.library import storage
    from apps.library.models import DocumentVersion

    if version.av_status in ("quarantined", "threat"):
        return version.av_status  # already isolated; release first to re-scan
    if not config.get("antivirus.enabled"):
        _set(version, "not_scanned", detail="Antivirus scanning is turned off.")
        return "not_scanned"
    path = storage.resolve_original(version.storage_path)
    limit = int(config.get("antivirus.max_scan_mb")) * 1024 * 1024
    if not path.exists():
        _set(version, "failed", detail="The stored file is missing.")
        return "failed"
    if path.stat().st_size > limit:
        _set(version, "size_limit", detail=f"Larger than the {config.get('antivirus.max_scan_mb')} MB scan limit.")
        audit.record("antivirus.size_limit", actor=actor, target_type="version", target_id=str(version.id), size=version.size)
        return "size_limit"
    engine = (health().get("engine") or "") + (f"/{health().get('signatures')}" if health().get("signatures") else "")
    try:
        result, name = scan_path(path)
    except ScannerUnavailable as exc:
        _set(version, "not_scanned", detail=str(exc)[:300])
        audit.record("antivirus.unavailable", actor=actor, outcome="failure", target_type="version", target_id=str(version.id))
        _alert("antivirus.unavailable", f"av_down:{timezone.localdate()}", "Antivirus (ClamAV) is unavailable",
               ["Files stay usable but are marked Not scanned. Re-scan them once ClamAV is running again."])
        return "not_scanned"
    except ScanError as exc:
        if str(exc) == "size_limit":
            _set(version, "size_limit", detail="ClamAV's own stream size limit was reached (StreamMaxLength).")
            return "size_limit"
        _set(version, "failed", detail=f"ClamAV error: {str(exc)[:200]}", engine=engine)
        audit.record("antivirus.scan_failed", actor=actor, outcome="failure", target_type="version", target_id=str(version.id))
        _alert("antivirus.unavailable", f"av_fail:{version.id}", "An antivirus scan failed",
               [f"File: {version.original_name}", "The file stays usable and is marked Scan failed."])
        return "failed"
    if result == "clean":
        _set(version, "clean", engine=engine)
        return "clean"
    _set(version, "threat", signature=name, engine=engine, detail="")
    audit.record("antivirus.threat", actor=actor, target_type="version", target_id=str(version.id), signature=name,
                 document=str(version.document_id))
    quarantine(DocumentVersion.objects.get(pk=version.pk))
    return "quarantined"


def _set(version, status: str, *, detail: str = "", signature: str = "", engine: str = "") -> None:
    from apps.library.models import DocumentVersion

    fields = {"av_status": status, "av_detail": detail[:300], "av_scanned_at": timezone.now()}
    if signature or status in ("clean", "threat"):
        fields["av_signature"] = signature
    if engine:
        fields["av_engine"] = engine[:120]
    DocumentVersion.objects.filter(pk=version.pk).update(**fields)
    for k, v in fields.items():
        setattr(version, k, v)


def quarantine(version) -> None:
    """Move the original into the quarantine directory and block every use of it."""
    from apps.library import storage
    from apps.library.models import DocumentVersion

    src = storage.resolve_original(version.storage_path)
    rel = f"{version.id}.quarantine"
    dst = quarantine_dir() / rel
    moved = False
    if src.exists():
        os.chmod(src, 0o600)
        shutil.move(str(src), dst)
        os.chmod(dst, 0o400)
        moved = True
    DocumentVersion.objects.filter(pk=version.pk).update(av_status="quarantined", av_quarantine_path=rel if moved else "")
    version.av_status, version.av_quarantine_path = "quarantined", rel if moved else ""
    audit.record("antivirus.quarantine", target_type="version", target_id=str(version.id), signature=version.av_signature,
                 document=str(version.document_id))
    _alert("antivirus.threat", f"av_threat:{version.id}", "Malware detected — file quarantined",
           [f"File: {version.original_name}", f"Detection: {version.av_signature}",
            "Preview, download, OCR and local AI are blocked for this file. Review it in Settings → Security → Antivirus."])


def release(version, *, actor, reason: str, request=None) -> None:
    """Main administrator only (enforced by the view): move the file back and allow access again."""
    from apps.library import storage
    from apps.library.models import DocumentVersion

    if version.av_status not in ("quarantined", "threat"):
        raise ScanError("This file is not in quarantine.")
    if version.av_quarantine_path:
        src = quarantine_dir() / version.av_quarantine_path
        dst = storage.resolve_original(version.storage_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(src, 0o600)
        shutil.move(str(src), dst)
        os.chmod(dst, 0o440)
    now = timezone.now()
    DocumentVersion.objects.filter(pk=version.pk).update(av_status="released", av_quarantine_path="", av_released_by=actor,
                                                         av_released_at=now, av_release_reason=reason[:500])
    audit.record("antivirus.release", request=request, actor=actor, target_type="version", target_id=str(version.id),
                 signature=version.av_signature, reason_length=len(reason))
    _alert("antivirus.released", f"av_release:{version.id}:{now:%Y%m%d%H%M%S}", "Quarantined file released",
           [f"File: {version.original_name}", f"Detection: {version.av_signature}", f"Released by {actor.display_name}.",
            f"Reason: {reason[:300]}"])


def delete_quarantined_files(versions) -> None:
    """Used by permanent deletion: quarantined copies are removed together with the document."""
    for v in versions:
        if v.av_quarantine_path:
            (Path(settings.DATA_DIR) / "quarantine" / v.av_quarantine_path).unlink(missing_ok=True)


@jobs.handler("av_scan")
def _job_scan(job) -> dict:
    from apps.library.models import DocumentVersion

    payload = job.payload
    v = DocumentVersion.objects.filter(pk=payload["version_id"]).first()
    if v is None:
        return {"skipped": "missing"}
    return {"status": scan_version(v)}


# ------------------------------------------------------------------ library scans

def start_library_scan(*, actor=None, kind: str = "manual", folder=None):
    from apps.library.models import DocumentVersion

    from .models import AvScanRun

    active = AvScanRun.objects.filter(status__in=(AvScanRun.RUNNING, AvScanRun.PAUSED)).first()
    if active:
        raise ScanError("A library scan is already running. Pause, resume or cancel it first.")
    qs = DocumentVersion.objects.all()
    if folder is not None:
        from apps.library.services import _descendant_ids as descendant_folder_ids

        qs = qs.filter(document__folder_id__in=descendant_folder_ids(folder))
    run = AvScanRun.objects.create(kind=kind, scope="folder" if folder else "library", folder_id=folder.id if folder else None,
                                   started_by=actor, total=qs.count())
    audit.record("antivirus.library_scan", actor=actor, target_type="av_scan", target_id=str(run.id), scope=run.scope,
                 total=run.total)
    jobs.enqueue("av_library_scan", {"run_id": run.id}, idempotency_key=f"avrun:{run.id}:0", max_attempts=1)
    return run


BATCH = 25


@jobs.handler("av_library_scan")
def _job_library(job) -> dict:
    from apps.library.models import DocumentVersion

    payload = job.payload
    from .models import AvScanRun

    run = AvScanRun.objects.filter(pk=payload["run_id"]).first()
    if run is None or run.status != AvScanRun.RUNNING:
        return {"stopped": run.status if run else "missing"}
    qs = DocumentVersion.objects.order_by("id")
    if run.folder_id:
        from apps.library.models import Folder
        from apps.library.services import _descendant_ids as descendant_folder_ids

        folder = Folder.objects.filter(pk=run.folder_id).first()
        qs = qs.filter(document__folder_id__in=descendant_folder_ids(folder)) if folder else qs.none()
    if run.cursor:
        qs = qs.filter(id__gt=run.cursor)
    batch = list(qs[:BATCH])
    counts = dict(run.counts or {})
    for v in batch:
        run.refresh_from_db(fields=["status"])
        if run.status != AvScanRun.RUNNING:
            break
        status = scan_version(v, run=run) if v.av_status not in ("quarantined", "threat") else v.av_status
        counts[status] = counts.get(status, 0) + 1
        run.done += 1
        run.cursor = str(v.id)
        AvScanRun.objects.filter(pk=run.pk).update(done=run.done, cursor=run.cursor, counts=counts)
    run.refresh_from_db()
    if run.status == AvScanRun.RUNNING and len(batch) == BATCH:
        jobs.enqueue("av_library_scan", {"run_id": run.id}, idempotency_key=f"avrun:{run.id}:{run.done}", max_attempts=1)
    elif run.status == AvScanRun.RUNNING:
        AvScanRun.objects.filter(pk=run.pk).update(status=AvScanRun.DONE, finished_at=timezone.now(), total=max(run.total, run.done))
        audit.record("antivirus.library_scan_done", target_type="av_scan", target_id=str(run.id), **{f"n_{k}": v for k, v in counts.items()})
    return {"done": run.done, "counts": counts}


def set_run_state(run, action: str, actor=None) -> None:
    from .models import AvScanRun

    if action == "pause" and run.status == AvScanRun.RUNNING:
        run.status = AvScanRun.PAUSED
    elif action == "resume" and run.status == AvScanRun.PAUSED:
        run.status = AvScanRun.RUNNING
        jobs.enqueue("av_library_scan", {"run_id": run.id}, idempotency_key=f"avrun:{run.id}:{run.done}:resume:{timezone.now().timestamp()}",
                     max_attempts=1)
    elif action == "cancel" and run.status in (AvScanRun.RUNNING, AvScanRun.PAUSED):
        run.status = AvScanRun.CANCELLED
        run.finished_at = timezone.now()
    else:
        raise ScanError(f"Cannot {action} a scan that is {run.status}.")
    run.save()
    audit.record(f"antivirus.library_scan_{action}", actor=actor, target_type="av_scan", target_id=str(run.id))


def scheduled_scan_tick(now_local) -> str | None:
    """From the scheduler: start the scheduled re-scan when due (once per occurrence)."""
    from apps.notify.models import SchedulerRun
    from apps.ops import schedule

    if not config.get("antivirus.enabled") or config.get("antivirus.scan_frequency") == "disabled":
        return None
    row, _ = SchedulerRun.objects.get_or_create(name="av_library_scan")
    occ = schedule.due(now_local, row.last_run_at, kind="antivirus")
    if occ is None:
        return None
    SchedulerRun.objects.filter(name="av_library_scan").update(last_local_date=now_local.date(), last_run_at=now_local)
    try:
        run = start_library_scan(kind="scheduled")
    except ScanError:
        return "busy"
    return f"started {run.id}"
