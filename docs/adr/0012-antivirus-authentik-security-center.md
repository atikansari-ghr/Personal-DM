# ADR 0012: Antivirus, authentik and the security center

Status: accepted (2026-10-07, change set M)

## Context

- Family members upload files from phones, mail attachments and old folders. The server should notice known malware
  without slowing uploads down or making documents unavailable when the scanner has a problem.
- The server is a small 2 vCPU / 4 GB Debian 13 LXC. Every extra service competes for memory with OCR and LibreOffice.
- Some families already run authentik for other self-hosted services and want one sign-in, but Personal DM must stay
  the authority for who may open which document, and nobody may be locked out when authentik is down.
- The main administrator wants to see in one place whether the installation is safe to publish on the Internet,
  whether security updates are pending and whether a reboot is needed, and sometimes to let another trusted person
  watch this without giving them access to everyone's documents.
- The web application runs as an unprivileged user. Installing packages, inspecting the firewall and rebooting need
  root.

## Decisions

1. **ClamAV over the local Unix socket, asynchronous and fail-open, with quarantine.** Uploads are committed first and
   marked *Scan pending*; a background job streams the file to `clamd` at `/run/clamav/clamd.ctl`. clamd has no TCP
   socket. When clamd is unavailable the file stays usable and is marked *Not scanned*, and administrators get a
   critical alert, instead of refusing uploads. A detection moves the file to `<data>/quarantine` (0400) and blocks
   every way of reading it; only the main administrator can release (with a reason) or delete it. Archives are
   scanned as one file by ClamAV; the app does not unpack them. A size limit (default 50 MB) keeps memory bounded;
   larger files are reported as not scanned, never as clean.
2. **Generic OpenID Connect for authentik, with explicit linking.** The client is standard OIDC (discovery,
   authorization code with PKCE, state, nonce, JWKS-verified ID token), so nothing is specific to one authentik
   version. Existing accounts are linked only by the signed-in person after re-authentication, never by matching an
   email claim, because an identity provider account with the same email is not proof of being the same person.
   Provisioning defaults to existing accounts only. Group mapping may set Member or Administrator only, never the
   main administrator and never document permissions. Local sign-in always remains available.
3. **An Administrator role separate from document access.** `User.is_admin` opens the security center and security
   notifications. Permissions are still decided only by `library/permissions.py`, which does not look at the role.
4. **A root host helper with fixed actions instead of sudo from the app.** The app writes a request file; a systemd
   path unit runs `personaldocs host-apply` as root, which accepts only inspect, check updates, install security
   updates, update signatures and reboot, validates its inputs and writes status and logs back. This is the same pattern
   as the NAS helper and keeps root out of the web process. Updates are never
   installed unattended; each install is preceded by a database and settings backup, and a failed backup blocks
   the install unless the administrator overrides it with an audited reason.
5. **Firewall monitoring only.** The firewall view reports ufw/nftables state and listening services but offers no
   control to change rules: a wrong rule from a web page could lock the administrator out of the server, and the
   firewall is better managed on the host.
6. **A weighted Security Health score with forcing conditions.** Weights: antivirus 20, HTTPS 20, security test 20,
   OS updates 15, firewall 10, reboot 10, authentik 5; Healthy ≥ 90, Attention 70–89, At Risk < 70. Conditions that
   matter on their own (malware in quarantine, failed HTTPS or inactive firewall on an Internet deployment,
   critically stale signatures, unresolved Critical findings) always give At Risk, so a high sum cannot hide them.
   The score is a summary, not a certification.
7. **Warning-only policy for the security test.** The Basic Internet Security Test runs only on request, checks only
   this application and host, and never blocks the site. Critical and High findings are shown as failed, kept in the
   history, lower the score and notify administrators, but the family keeps access to its documents.

## Consequences

- ClamAV needs about 1.2 GB of memory; on smaller machines it is skipped with `--without-antivirus`. A *Clean*
  result means only that ClamAV found nothing with the signatures of that moment.
- Fail-open means a file can be usable before or without a scan; the status badges and alerts make this visible.
- Quarantined files are not in backups, so a released file that was later lost cannot come from a backup.
- authentik adds one more trust relationship; a compromised authentik account can sign in only to an account that its
  owner linked, and two-step verification enabled on that account is still asked.
- The host helper is a root component that must stay small; its action list is fixed in `ops/host_helper.py`.
- The security test is a baseline, not a penetration test; passing it does not prove the absence of vulnerabilities.
- The real authentik server, the Internet Ready path with a real certificate, the host helper on Debian 13 and
  freshclam on Debian 13 were tested only with fakes, mocks or stubs in the build environment.
