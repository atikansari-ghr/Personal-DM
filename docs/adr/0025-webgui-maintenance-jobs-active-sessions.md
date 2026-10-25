# ADR 0025: WebGUI maintenance as durable jobs through the root helper; Active Sessions from bounded activity

Status: accepted (2026-10-25, change set AB. The change prompt numbered its tests AT-456…AT-475; those were taken,
so the tests are AT-481…AT-500, where prompt AT-n = AT-(n+25).)

## Context

- Upgrades, repairs, rollbacks and restarts were command-line only (`sudo personaldocs …`). Main administrators wanted
  them in the browser, with progress, exact errors and logs, without a browser shell and without giving the web
  application root rights.
- An upgrade restarts the web application itself, so anything that lives in the browser or the web process is lost
  half-way.
- Administrators wanted to see who is signed in right now, from where, and to end one session — with sessions that
  are idle distinguished from sessions in use, without a heartbeat and without GPS.

## Decision

1. **One durable job per operation** (`ops.MaintenanceJob`): ordered steps with times and status, sanitized summary,
   technical details, log reference, exit code, versions, backup reference, recovery state, retry parent, failure
   class and verification. A partial unique constraint on `lock_group="system"` allows one Upgrade / Repair /
   Rollback / Restart at a time; the CLI keeps its flock.
2. **Root work through the existing host helper**, extended with five fixed actions that each run one fixed
   `personaldocs` command (`check-updates --json`, `upgrade [--ref REF]`, `restart`, `repair --only ITEM,…`,
   `rollback`). Values are validated (ref pattern, allowlisted items) and passed as separate arguments; nothing reaches
   a shell. Requests are queued per job (`host/queue/`), so a request that arrives while the helper runs a long upgrade
   is not lost. The helper is its own systemd service, so it survives the web restart it causes.
3. **The CLI reports its own steps** (`step` / `meta` functions writing JSON lines to `PD_PROGRESS_FILE`, redacted;
   no-ops in a terminal). `die` and the ERR trap mark the running step failed and record what the failure means:
   *remains_operational* (nothing changed, or the snapshot was restored and the old version verified healthy),
   *rolled_back* (only after health checks passed) or *recovery_required*. Automatic rollback is attempted only when
   `schema_compatible` holds. The app folds this into the job on every poll and once a minute from the scheduler.
4. **Doctor has one implementation**: the management command's checks write to a sink; the CLI prints them, the web
   collects them per component with explicit NOT CONFIGURED / NOT APPLICABLE / NOT TESTED statuses.
5. **Repair is plan-first**: Doctor findings map to allowlisted repair items with problem, proposal, affected
   components, restart, backup and risk; nothing runs until the main administrator confirms with step-up; a backup is
   made first when an item needs one; Doctor runs again afterwards and anything still failing makes the job
   *Partially Failed*.
6. **Server-side sanitization** (`ops/sanitize.py`): every secret value the installation holds plus common secret
   patterns are redacted from summaries, details, logs and reports; an optional anonymized support report also
   replaces addresses, names, hosts, paths and network names on a copy.
7. **Active Sessions** reuse `UserSession`: a new `last_activity_at`, written at most every `min(2 min, threshold/2)`
   and not for requests marked `X-PD-Background: 1`; Active = activity within `security.session_active_minutes`
   (default 5). Location: Trusted Zone → private network → local GeoIP (labelled approximate), zones loaded once per
   listing. Terminate Session sets `revoked_at`, which `sessions.check()` refuses on the next request — distinct from
   Mark Unrecognized.

## Consequences

- The browser never needs to stay open; refresh, sign-out, app and service restarts keep the job and its history.
- Real upgrades are still performed by the same tested CLI code; the web interface adds no second upgrade path.
- Tests drive the real helper with a scripted `personaldocs` that uses the real progress functions; a real upgrade
  on a Debian 13 host remains a manual release check (docs/RELEASE_CHECKLIST.md).
- A rollback after incompatible migrations is refused by design; recovery is restoring the snapshot or the verified
  pre-upgrade recovery point.
