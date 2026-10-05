# ADR-0007: Pre-authentication access policy in the app, local GeoIP, application login audit

- Status: accepted (change set 2026-10)

## Context
The deployment sits behind Nginx Proxy Manager or Pangolin, which may run on other machines and are configured through their
own UIs. Country/IP restrictions must apply before authentication, keep working across proxy types, and be recoverable without
web access.

## Decision
- Enforce country/IP rules in an `AccessPolicyMiddleware` placed before sessions, CSRF and authentication, instead of generating
  rules for each proxy product. It works the same behind NPM and Pangolin, and denied requests never reach login or document code.
- Determine the client IP only from trusted proxies (addresses/CIDR), reading `X-Forwarded-For` right to left.
- Use a local MaxMind-format database (`maxminddb`) and never an IP lookup API. Updates are validated and swapped atomically;
  failures keep the last database.
- Deterministic precedence: emergency switch → health check → internal → blocked IP → trusted IP → policy off → unknown
  country → temporary access → allow/block list. Lock-out check before saving, rollback snapshot, console command and an
  environment switch for recovery.
- Record authentication in `LoginEvent` (app-level truth). GoAccess consumes a privacy-safe access log written by the app and is
  displayed as a summary to the main administrator only.

## Consequences
Blocked requests still cost one Python request each (cheap, and counted in `BlockedStat`). Proxy-level enforcement (for
example NPM access lists) can be added on top. The policy cache is per process with a 15-second lifetime; the CLI restarts the
web service so changes apply at once.
