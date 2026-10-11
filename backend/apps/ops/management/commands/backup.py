"""Backups from the console.

    manage.py backup                      Full encrypted recovery point now (default policy), deep-verified
    manage.py backup --incremental        Incremental recovery point (a Full when no chain exists yet)
    manage.py backup --pre-change REASON  Safety backup before a high-risk change; exit code 1 unless verified
    manage.py backup list                 Recovery points with their copies
    manage.py backup health               Backup & Recovery Health (no secrets)
    manage.py backup verify POINT_ID      Deep verification of every copy of a point

Without any Backup & Recovery policy and with a legacy backup folder configured, the previous unencrypted folder
backup (format 1) is made as before, so existing scripts keep working until a policy exists.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.ops import backup as legacy
from apps.ops import bk_engine as E
from apps.ops.models import RecoveryCopy, RecoveryPoint


class Command(BaseCommand):
    help = "Create, list or verify encrypted full-system recovery points."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="run", choices=["run", "list", "health", "verify"])
        parser.add_argument("point", nargs="?")
        parser.add_argument("--incremental", action="store_true")
        parser.add_argument("--pre-change", dest="pre_change", metavar="REASON")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, action, point, incremental, pre_change, json: bool = False, **opts):
        out = self.stdout.write
        if action == "health":
            h = E.health()
            if json:
                out(__import__("json").dumps(h, indent=1, default=str))
                return
            lv = h["latest_verified"]
            out(f"Backup & Recovery: {h['label']}" + (f" · newest verified {lv['kind']} {lv['created_at'][:16]}" if lv else ""))
            out(f"Recovery Readiness: {h['readiness']['label']} · {h['validation']['label']}")
            for w in h["warnings"]:
                out(f"  ! {w}")
            return
        if action == "list":
            for p in RecoveryPoint.objects.filter(deleted_at__isnull=True)[:50]:
                copies = ", ".join(f"{c.destination.name}: {RecoveryCopy.LABELS.get(c.state, c.state)}" for c in p.copies.select_related("destination"))
                out(f"{p.created_at:%Y-%m-%d %H:%M}  {p.kind:<11} {p.status:<9} {p.id}  {copies}")
            for lg in E.legacy_backups():
                out(f"{(lg['created_at'] or '')[:16]}  legacy      folder    {lg['path']} (unencrypted, format 1)")
            return
        if action == "verify":
            p = RecoveryPoint.objects.filter(pk=point).first() if point else None
            if p is None:
                raise CommandError("Give a recovery point id (see: backup list).")
            E.verify_point(p)
            out(f"{p.id}: {p.status}")
            if p.status not in ("verified", "partial"):
                raise CommandError("Verification failed; see Settings → Backup & Recovery for the checks.")
            return
        if not E.configured():
            from apps.core import config

            if config.get("backup.target"):  # legacy installations without a policy yet
                try:
                    r = legacy.run_backup()
                except legacy.BackupError as exc:
                    raise CommandError(str(exc))
                out(self.style.SUCCESS(f"Legacy backup written to {r['path']} ({r['files']} files, verified={r['verified']})"))
                return
            raise CommandError("No backup policy with an enabled destination (Settings → Storage & backup → Backup & Recovery).")
        if pre_change:
            res = E.pre_change_backup(pre_change)
            if not res["ok"]:
                raise CommandError(f"Safety backup failed or not verified: {res['detail']}")
            out(self.style.SUCCESS(f"Safety backup verified: {res['detail']}"))
            return
        try:
            p = E.create_point(E.default_policy(), kind="incremental" if incremental else "full", trigger="manual")
        except E.BackupError as exc:
            raise CommandError(str(exc))
        copies = {c.destination.name: RecoveryCopy.LABELS.get(c.state, c.state) for c in p.copies.select_related("destination")}
        msg = f"{p.kind.title()} recovery point {p.id}: {p.status} · " + ", ".join(f"{k}: {v}" for k, v in copies.items())
        if p.status in ("verified", "partial"):
            out(self.style.SUCCESS(msg))
        else:
            raise CommandError(msg)

