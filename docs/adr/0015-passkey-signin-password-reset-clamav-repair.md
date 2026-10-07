# ADR 0015: Passkey sign-in on the first screen, administrator password reset, ClamAV repair

Status: accepted (2026-10-07, change set P; the change prompt called it "Change Set O" with AT-176…AT-190, renumbered
to AT-196…AT-210 because those numbers belonged to the rich notifications change set)

## Context

- **Passkeys came only after the password.** Passwordless sign-in was gated by the setting
  `auth.allow_passwordless`, which defaulted to off, plus a per-person opt-in. In practice passkeys were only offered
  as the second step after the password, and the "Sign in with a passkey" button stayed hidden. Families expected to
  tap a passkey on the first screen, as on other sites.
- **Password resets had no safe administrator path.** Members without an email address needed a new password from
  the administrator, and the Administrator role (change set M) had no reset function at all. A reset must not leak the
  new password through email, notifications or logs, and an Administrator must not be able to take over the main
  administrator.
- **Security notifications could be weakened by templates.** The Template Manager (ADR 0014) lets administrators
  rewrite the summary of any event, including the "if this was not you…" guidance of security events.
- **ClamAV showed "Unavailable … /run/clamav/clamd.ctl (FileNotFoundError)" after upgrades** while the page still
  listed an engine version. On Debian 13 (`clamav-daemon` / `clamav-freshclam` 1.4.3+dfsg-1): `clamav-daemon.service`
  is socket-activated (`Requires=clamav-daemon.socket`; the socket unit listens on `/run/clamav/clamd.ctl` with
  `RemoveOnStop=True`); both units carry a `ConditionPathExistsGlob` on the signature files and are silently skipped
  without them; the service has no `Restart=`; and Debian's default `LocalSocket /var/run/clamav/clamd.ctl` is a
  different string from the socket unit's path. The earlier installer kept that line. When the strings differ, clamd
  binds its own socket and deletes it when it stops or restarts. The cached engine version was not proof that
  scanning worked.

## Decisions

1. **One passkey mode for the installation.** `auth.passkey_mode` is `passwordless` (default) or `mfa` and replaces
   `auth.allow_passwordless`. The migration keeps an explicit earlier choice (saved off → mfa, saved on →
   passwordless, never chosen → passwordless) so nobody who deliberately turned passwordless off is switched back,
   and turns passwordless on for accounts that already have a discoverable passkey. The sign-in page shows password,
   "or", **Sign in with Passkey**, then authentik/Google, and offers passkeys through browser autofill (conditional
   mediation). Passwordless always requires user verification, a single-use challenge and the origin/RP ID checks of
   `py_webauthn`. Enrolling a discoverable passkey in passwordless mode turns passwordless on for that person; they can
   turn it off. The main administrator's password, recovery codes and console recovery work in both modes.
2. **Sign-in by username or email.** An email address is accepted when it belongs to exactly one active account, so
   it cannot be ambiguous.
3. **Two reset methods in one module.** `accounts/password_reset.py` is the only implementation, used by the
   administrator dialog and the self-service Forgot password? flow.
   - *Temporary password:* 16 random characters returned once in the API response (`Cache-Control: no-store`) and
     stored only as a hash; never emailed or written to notifications, logs or audit records; the person must change
     it; every session ends (a changed password hash ends Django sessions, so this is not optional); older reset
     tokens are invalidated.
   - *Reset email:* a 32-byte token whose hash is stored, single use, valid `auth.reset_token_minutes`; a newer
     request or any password change invalidates older tokens. The link is sent directly by SMTP and never goes
     through the notification outbox, in-app history, Telegram or push, so it is never stored outside the token
     table's hash. On Internet deployments it is sent only for an https origin.
4. **Main Administrator protection.** `can_reset` refuses an Administrator resetting a main administrator (403 with
   the console hint), anyone resetting their own password through this function, and non-administrators. The
   console recovery `personaldocs recover-admin` stays the last resort.
5. **Mandatory security text outside the template.** Security events carry a `mandatory` tuple in the event
   catalogue. `rich.Message` always includes it, and each renderer shows it in a fixed place (red box and
   `IMPORTANT:` lines in email, bold ⚠️ lines in Telegram, a red note in-app). Templates gain a branding name and a
   footer, validated like the other template fields, but cannot remove or change the mandatory text.
6. **ClamAV: diagnose and repair the real host state, in one standard-library module.** `ops/clamav_check.py` reads
   the systemd units, the effective socket (socket unit `Listen` versus `LocalSocket`), the runtime directory, the
   socket file, access by the `personaldocs` account and a real clean + EICAR scan, and names the likely cause. Its
   repair sets `LocalSocket` to the socket unit's path, removes TCP listeners, installs a restart drop-in and a
   tmpfiles entry for `/run/clamav`, downloads missing signatures, starts socket and daemon in order, waits for
   `PONG` and runs the self-test; it reports success only for Healthy or Degraded. The same code runs from
   `personaldocs antivirus`, install/post-upgrade/repair, `doctor` and the host-helper action `antivirus_repair`, so
   the web app never runs root commands or passes commands from the browser.
7. **Health from operation, not metadata.** The antivirus state is Healthy only when the daemon answers and a small
   INSTREAM scan succeeds; Unavailable and Error give 0 Security Health points and force At Risk. A self-test runs
   daily and after a failure; cached versions are labelled "last seen … not proof that scanning works".

## Consequences

- Passwordless becomes the default for installations that never chose; people with discoverable passkeys can use
  them on the first screen immediately after the upgrade. Installations that turned it off keep Password + Passkey.
- Administrators can help members with forgotten passwords without email, but must pass the temporary password on
  through a safe channel themselves; a lost one cannot be shown again (generate a new one).
- Reset emails depend on SMTP and, on Internet deployments, on an https origin; their delivery to real mail clients
  is not covered by the automated tests.
- Administrators can no longer weaken security guidance through templates; a request to change it needs a code
  change.
- The upgrade changes host configuration outside the application (clamd.conf with a one-time backup, a systemd
  drop-in, a tmpfiles entry). These stay in place on rollback and are compatible with the previous release.
- The repair was verified on a simulated Debian 13 host and against a real clamd in a development container, not
  yet on a real Debian 13 Proxmox LXC or across a real reboot; administrators must check the result on their host.
- Migrations `accounts.0007_passkey_mode` and `notify.0003_template_brand_footer`; rollback to a release without them
  requires restoring the pre-upgrade backup. No new dependencies.
