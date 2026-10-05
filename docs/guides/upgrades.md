<!-- audience: admin -->
# Upgrades, rollback and repair

## Upgrade {#upgrade}

```
sudo personaldocs upgrade              # newest commit of the configured branch
sudo personaldocs upgrade --ref v0.2.0 # a specific tag
```

Steps: take an exclusive lock; check free disk; run a **verified application backup** (aborts if the backup fails — use `--skip-backup` only if you have one); fetch and verify the requested revision; build it in a new release directory; run migration checks; stop the worker and scheduler; apply migrations; switch the `current` symlink; restart; run health checks. The previous and new versions are printed and logged.

If anything fails **before** migrations, the old release keeps running untouched. If health checks fail **after** switching, the previous release is restored automatically when the migrations are backwards-compatible; otherwise you are told to restore the pre-upgrade backup.

## Upgrading from the previous release (profile photos, Local AI, security, passkeys) {#change-set-2026-10}

```
sudo personaldocs upgrade     # backup, new release, migrations, restart, health check
sudo personaldocs repair      # runs the NEW personaldocs command once: GoAccess + access log (safe, keeps all data)
sudo personaldocs doctor
```

The second command is needed only once, when coming from a release older than this change set: the upgrade is run by
the previously installed `personaldocs` command, which does not yet know the new steps. Together they:
- back up first
- apply the new database tables (login audit, access policy, AI, passkeys, profile photos) without touching existing data
- install the new Python libraries in the new release
- install GoAccess when possible (never fatal)
- add the access log and its rotation, and restart the services

Nothing changes for existing users until you switch features on:
- country filtering is off
- Local AI is off
- two-step verification is not required
- existing authenticator apps keep working
- passwordless sign-in is off

Afterwards, optionally:
1. Settings → Security & access: enter MaxMind credentials and **Update now** for GeoIP; review alerts; enable traffic analytics.
2. Settings → Authentication: decide on passkeys / passwordless / required two-step verification.
3. Settings → Local AI: add a profile pointing at your LAN AI server.
4. `sudo personaldocs doctor` to confirm the real client IP, GeoIP, passkey origin and AI checks.

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
