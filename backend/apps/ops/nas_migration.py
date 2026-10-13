"""Move the old Settings → Storage & NAS connection into a Backup & Recovery destination (Change Set V).

Used by the upgrade migration ``ops.0004_nas_into_destinations`` (with historical models) and by **Retry
Migration** (with the live models). It is idempotent: a rerun finds the destination it created (``config.managed``)
and updates it; it never creates a second one.

What moves: connection type (NFS/SMB), server, share/export, folder, username, domain/workgroup and protocol version.
The SMB password stays where it already is - the encrypted ``nas.password`` setting that the mount helper reads - so
working credentials keep working without being typed again, and no secret is copied, logged or audited. Existing
recovery points, copies, policy links and the files on the share are not touched (only configuration moves).

If the old configuration does not validate, the destination is still created, marked **Needs Attention - Migration
incomplete; existing backup data preserved**, and the old values are kept for Edit / Test Connection / Retry.
"""
from __future__ import annotations

from datetime import datetime, timezone

MOUNT_ROOT = "/mnt/pdnas"
NEEDS_ATTENTION = "needs_attention"
MIGRATION_NOTE = "Migration incomplete; existing backup data preserved"
FIELDS = ("type", "server", "share", "subfolder", "username", "domain", "version")


def old_values(Setting) -> dict:
    """The non-secret NAS values as stored by Settings → Storage & NAS (AppSetting rows)."""
    rows = {r.key: r.value for r in Setting.objects.filter(key__startswith="nas.")}
    vals = {f: rows.get(f"nas.{f}") for f in FIELDS}
    vals["type"] = vals["type"] or "none"
    vals["password_set"] = bool((rows.get("nas.password") or {}).get("enc")) if isinstance(rows.get("nas.password"), dict) else False
    return vals


def run(Dest, Setting, Policy=None, Audit=None, *, now=None) -> dict:
    """Create or update the managed NAS destination. Returns {"result": "migrated"|"needs_attention"|"nothing", ...}."""
    from .nas_helper import NasError, validate

    vals = old_values(Setting)
    if vals["type"] not in ("nfs", "smb") or not (vals.get("server") or vals.get("share")):
        return {"result": "nothing"}  # no app-managed NAS was configured ("Already mounted" was adopted by 0002)
    now = now or datetime.now(timezone.utc)
    subfolder = (vals.get("subfolder") or "personaldocs").strip("/") or "personaldocs"
    path = f"{MOUNT_ROOT}/{subfolder}"
    problem = ""
    try:
        validate({k: vals.get(k) or "" for k in FIELDS})
        if vals["type"] == "smb" and not vals["password_set"]:
            problem = "The SMB password is not stored; enter it in Edit."
    except NasError as exc:
        problem = str(exc)

    dest = next((d for d in Dest.objects.filter(kind="nas") if (d.config or {}).get("managed")), None)
    if dest is None:  # the destination 0002 created from the old backup folder on the mounted share
        dest = next((d for d in Dest.objects.filter(kind="nas") if str((d.config or {}).get("path", "")).startswith(MOUNT_ROOT)), None)
    created = dest is None
    if created:
        name, n = "NAS backup share", 2
        while Dest.objects.filter(name=name).exists():
            name, n = f"NAS backup share {n}", n + 1
        dest = Dest(name=name, kind="nas", enabled=True, config={})
    cfg = dict(dest.config or {})
    cfg.update(managed=True, connection=vals["type"], path=path, require_mount=True, migrated_from="storage_nas",
               migrated_at=now.isoformat())
    dest.config = cfg
    if problem:
        dest.health, dest.health_detail = NEEDS_ATTENTION, f"{MIGRATION_NOTE}: {problem}"[:300]
    elif dest.health == NEEDS_ATTENTION:
        dest.health, dest.health_detail = "unknown", "Migrated from Storage & NAS. Run Test Connection."
    elif created:
        dest.health, dest.health_detail = "unknown", "Migrated from Storage & NAS. Run Test Connection."
    dest.save()
    if Audit is not None:  # no secrets: field names and the outcome only
        try:
            Audit.objects.create(action="backup.nas_migrated", outcome="failure" if problem else "success", actor_label="upgrade",
                                 target_type="backup_destination", target_id=str(dest.pk),
                                 context={"created": created, "connection": vals["type"], "needs_attention": bool(problem)})
        except Exception:  # noqa: BLE001 - auditing never blocks the migration
            pass
    return {"result": NEEDS_ATTENTION if problem else "migrated", "destination": dest.pk, "created": created, "problem": problem}
