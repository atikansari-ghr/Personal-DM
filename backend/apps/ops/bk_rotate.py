"""Rotate the Backup Recovery Key.

1. A safety checkpoint (recovery point with the current key) is made first.
2. A new key generation is created as *pending*; the old key stays usable.
3. Every retained recovery point is re-encrypted once (decrypted with the old key, encrypted with a new data key
   wrapped by the new key) in the local staging area and copied to each destination that holds it, under
   ``<point>/g<new>/``. Each new copy is deep-verified with the new key before the old generation's files on that
   destination are removed.
4. Destinations that cannot be reached keep the old generation; they are reported by name and the rotation is
   recorded as **Partial**. The old key is kept (state *retiring*) until no retained copy needs it; "Retry rotation"
   migrates the rest later.
5. The new generation becomes active at the commit point (at least one copy migrated, or nothing to migrate). The
   Emergency Recovery Package of the old generation is then shown as Outdated until a new one is exported.
"""
from __future__ import annotations

import json
import secrets
import shutil

from django.utils import timezone

from apps.core import audit

from . import bk_crypto as C
from . import bk_keys
from .bk_destinations import DestError, iter_stream, provider
from .bk_engine import _Lock, open_point, point_dir, pre_change_backup, rel, staging_root, verify_copy
from .models import KeyRotation, RecoveryCopy, RecoveryKey, RecoveryPoint

GOOD = (RecoveryCopy.STORED_VERIFIED, RecoveryCopy.STORED_WARNING)


def _reencrypt(point: RecoveryPoint, src: RecoveryCopy, new_gen: int, new_raw: bytes) -> dict:
    prov = provider(src.destination)
    header, old_dek = open_point(prov, point.id, src.generation, bk_keys.raw_key(src.generation))
    dek = secrets.token_bytes(32)
    out = point_dir(point.id, new_gen)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    files = {}
    for name in sorted(header["files"]):
        dst = out / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        with prov.open(rel(point.id, src.generation, name)) as fh, open(dst, "wb") as w:
            C.encrypt_stream(C.decrypt_stream(fh, C.file_key(old_dek, name), name.encode()), w, C.file_key(dek, name), name.encode())
        import hashlib

        h = hashlib.sha256()
        with open(dst, "rb") as fh:
            for b in iter_stream(fh):
                h.update(b)
        files[name] = {"cipher_sha256": h.hexdigest(), "cipher_size": dst.stat().st_size}
    key = RecoveryKey.objects.get(generation=new_gen)
    header.update(key_generation=new_gen, key_fingerprint=key.fingerprint, dek=C.wrap_dek(new_raw, dek, str(point.id)), files=files,
                  rotated_at=timezone.now().isoformat())
    (out / "header.json").write_text(json.dumps(header, indent=1))
    return header


def migrate(rotation: KeyRotation, new_gen: int, new_raw: bytes) -> list[dict]:
    results = []
    points = RecoveryPoint.objects.filter(deleted_at__isnull=True).order_by("created_at")
    for point in points:
        copies = list(point.copies.exclude(state=RecoveryCopy.DELETED).exclude(generation=new_gen).select_related("destination"))
        if not copies:
            continue
        # any readable copy can be the source - including one already migrated to the new key
        sources = sorted(point.copies.filter(state__in=GOOD).select_related("destination"), key=lambda c: c.generation != new_gen)
        header = None
        for src in sources:
            try:
                header = _reencrypt(point, src, new_gen, new_raw)
                break
            except (DestError, C.DecryptError, OSError) as exc:
                results.append({"point": str(point.id), "destination": src.destination.name, "state": "unreachable", "detail": str(exc)[:200]})
        if header is None:
            for c in copies:
                results.append({"point": str(point.id), "destination": c.destination.name, "state": "unreachable",
                                "detail": "No readable copy of this recovery point; it keeps the previous key."})
            continue
        d = point_dir(point.id, new_gen)
        for c in copies:
            prov = provider(c.destination)
            old_gen = c.generation
            try:
                for name in sorted(header["files"]):
                    prov.put(rel(point.id, new_gen, name), d / name)
                prov.put(rel(point.id, new_gen, "header.json"), d / "header.json")
                c.generation = new_gen
                res = verify_copy(c, key_raw=new_raw)
                if res["status"] == "failed":
                    c.refresh_from_db()
                    RecoveryCopy.objects.filter(pk=c.pk).update(generation=old_gen)
                    prov.delete_prefix(f"{point.id}/g{new_gen}")
                    results.append({"point": str(point.id), "destination": c.destination.name, "state": "verification_failed",
                                    "detail": "The re-encrypted copy failed verification; the previous copy was kept."})
                    continue
                RecoveryCopy.objects.filter(pk=c.pk).update(generation=new_gen, stored_at=timezone.now(), bytes=sum(
                    f["cipher_size"] for f in header["files"].values()))
                prov.delete_prefix(f"{point.id}/g{old_gen}")  # only after the new copy verified
                results.append({"point": str(point.id), "destination": c.destination.name, "state": "migrated", "detail": ""})
            except DestError as exc:
                RecoveryCopy.objects.filter(pk=c.pk).update(generation=old_gen)
                results.append({"point": str(point.id), "destination": c.destination.name, "state": "unreachable", "detail": str(exc)[:200]})
        if not point.copies.exclude(state=RecoveryCopy.DELETED).exclude(generation=new_gen).exists():
            RecoveryPoint.objects.filter(pk=point.pk).update(key_generation=new_gen)
        from .bk_engine import rollup

        rollup(point)
        shutil.rmtree(staging_root() / str(point.id), ignore_errors=True)
    return results


def rotate(actor=None, request=None) -> KeyRotation:
    old = bk_keys.ensure_active()
    checkpoint = pre_change_backup("Before rotating the Backup Recovery Key", actor=actor, request=request)
    with _Lock():
        new_row, new_raw = bk_keys.new_pending()
        rotation = KeyRotation.objects.create(from_generation=old.generation, to_generation=new_row.generation, started_by=actor,
                                              checkpoint_id=checkpoint.get("point"))
        results = migrate(rotation, new_row.generation, new_raw)
        migrated = [r for r in results if r["state"] == "migrated"]
        failed = [r for r in results if r["state"] != "migrated"]
        if failed and not migrated:
            # nothing could be migrated: keep the current key active, discard the unused new generation
            rotation.status = KeyRotation.FAILED
            new_row.delete()
        else:
            new_row.state, new_row.activated_at = RecoveryKey.ACTIVE, timezone.now()
            new_row.save(update_fields=["state", "activated_at"])
            RecoveryKey.objects.filter(state=RecoveryKey.ACTIVE).exclude(generation=new_row.generation).update(state=RecoveryKey.RETIRING)
            rotation.status = KeyRotation.PARTIAL if failed else KeyRotation.COMPLETE
            bk_keys.retire_unused()
        rotation.results = results
        rotation.finished_at = timezone.now()
        rotation.save()
    audit.record("recovery.key_rotated", request=request, actor=actor, outcome="success" if rotation.status != "failed" else "failure",
                 from_generation=rotation.from_generation, to_generation=rotation.to_generation, status=rotation.status,
                 migrated=len(migrated), incomplete=len(failed))
    from apps.notify import events

    if rotation.status == KeyRotation.COMPLETE:
        detail = (f"Key generation {rotation.to_generation} is active; {len(migrated)} copies re-encrypted and verified. "
                  "Export a new Emergency Recovery Package now.")
    elif rotation.status == KeyRotation.PARTIAL:
        names = sorted({r["destination"] for r in failed})
        detail = (f"Partial: {len(migrated)} copies re-encrypted, {len(failed)} still use the previous key (not reachable: "
                  f"{', '.join(names)}). The previous key stays usable until they are migrated (Retry rotation).")
    else:
        detail = "No copy could be re-encrypted; the current key remains active."
    events.backup_event("recovery.key_rotated", detail=detail, actor=actor, severity="warning" if rotation.status != "complete" else "",
                        tag=str(rotation.id))
    return rotation


def retry(actor=None, request=None) -> KeyRotation | None:
    """Migrate copies still on an older generation to the active key."""
    key = bk_keys.active()
    if key is None:
        return None
    with _Lock():
        rotation = KeyRotation.objects.create(from_generation=0, to_generation=key.generation, started_by=actor)
        results = migrate(rotation, key.generation, bk_keys.raw_key(key.generation))
        failed = [r for r in results if r["state"] != "migrated"]
        rotation.status = KeyRotation.PARTIAL if failed else KeyRotation.COMPLETE
        rotation.results, rotation.finished_at = results, timezone.now()
        rotation.save()
        bk_keys.retire_unused()
    audit.record("recovery.key_rotation_retry", request=request, actor=actor, status=rotation.status)
    return rotation
