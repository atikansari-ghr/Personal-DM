<!-- audience: admin -->
# Upgrades, rollback and repair

## Upgrade {#upgrade}

```
sudo personaldocs upgrade              # newest commit of the configured branch
sudo personaldocs upgrade --ref v0.2.0 # a specific tag
```

Steps: take an exclusive lock; check free disk; run a **verified application backup** (aborts if the backup fails — use `--skip-backup` only if you have one); fetch and verify the requested revision; build it in a new release directory; run migration checks; stop the worker and scheduler; apply migrations; switch the `current` symlink; restart; run health checks. The previous and new versions are printed and logged.

If anything fails **before** migrations, the old release keeps running untouched. If health checks fail **after** switching, the previous release is restored automatically when the migrations are backwards-compatible; otherwise you are told to restore the pre-upgrade backup.

## Rollback {#rollback}

```
sudo personaldocs rollback
```

Switches back to the previous release only if its code knows every migration applied in the database (same schema). If the newer version changed the schema, running old code is refused — restore the pre-upgrade backup instead (`personaldocs restore /mnt/nas-backup/personaldocs/backup-...`).

## Repair {#repair}

```
sudo personaldocs repair
```

Diagnoses first, then: reinstalls missing packages, fixes ownership and permissions of data and config, recreates missing directories, reinstalls systemd units, applies pending migrations, requeues jobs whose worker died, rebuilds search vectors, restarts services. It **never** recreates the database, regenerates keys, deletes originals or re-runs account setup.

Separate operations:

| Operation | Command | Destructive? |
|---|---|---|
| Safe repair | `personaldocs repair` | No |
| Storage repair | `personaldocs integrity --repair --confirm` | No (orphans are quarantined) |
| Restore from backup | `personaldocs restore PATH --yes` | Replaces the database |
| Permanent deletion | Archive page, one document at a time | Yes |
