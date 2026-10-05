<!-- audience: admin -->
# Security & access: login audit, GeoIP, country/IP rules and traffic analytics

## How the layers fit together {#overview}

Every request passes these layers in order. Each one has a single job:

Internet → Nginx Proxy Manager / Pangolin (HTTPS) → **country / IP access policy** → sign-in rate limits → Personal Documents
sign-in (password, passkey, authenticator app, Google) → per-document permissions → audit log.

- The **access policy** decides *whether a network may reach the app at all*. It runs before sign-in and before any document code.
- The **login audit** records *who actually signed in*, recorded by the app itself (not guessed from web logs).
- **Traffic analytics (GoAccess)** only *observes* HTTP traffic. It never blocks anything.
- **Local AI** only ever sees documents that permissions already allow (see [Local AI](local-ai.md#permissions)).

Country filtering is defence in depth. It does not replace strong passwords, two-step verification, rate limits, HTTPS and permissions.

## Real client IP behind NPM or Pangolin {#real-ip}

The reverse proxy connects to the app, so without extra configuration every visitor would appear to come from the proxy's
address. The app therefore reads the visitor's address from `X-Forwarded-For`, **but only when the connection comes from a
trusted proxy** listed in `PD_TRUSTED_PROXY_IPS` (`/etc/personaldocs/personaldocs.env`; addresses or CIDR ranges, comma separated).
Anyone else can send a forged `X-Forwarded-For` header, and it is ignored: the socket address is used instead. The header is read from the
right; the first address that is not itself a trusted proxy is the client.

Settings → Security & access → **Your connection** shows the address the server sees for you, and whether the request came
through a trusted proxy. `sudo personaldocs doctor` warns when all recent sign-ins appear to come from one internal address,
which usually means the proxy is not listed as trusted.

### Nginx Proxy Manager {#npm-real-ip}

NPM sends `X-Forwarded-For` and `X-Real-IP` by default. Put the NPM host's LAN address in the guided installer's "proxy IP"
question, or set it by hand:

```
PD_TRUSTED_PROXY_IPS=127.0.0.1,192.168.1.10
PD_BEHIND_PROXY=1
```

then `sudo systemctl restart personaldocs-web`.

### Pangolin {#pangolin-real-ip}

Pangolin reaches the app through its Newt connector, which forwards `X-Forwarded-For`. Trust the address the requests
arrive from. That is usually the Newt container/host on your LAN, for example `192.168.1.20`; if Newt runs on the same LXC, use `127.0.0.1`.
Check the result in **Your connection** after signing in through the public address.

## Login audit {#login-audit}

**Activity & health → Login audit** lists every sign-in, failed attempt, refusal and sign-out with:

- time, account (or the username typed, for unknown accounts), result and failure reason
  (`bad_credentials`, `bad_code`, `passkey_invalid`, `rate_limited`, `disabled_account`, …)
- method (`password`, `password+totp`, `password+passkey`, `passkey` = passwordless, `google`, `…+recovery_code`)
- real client IP, country from the local GeoIP database, browser, operating system and device class
- the device-session reference (matches **My account → Sessions**)
- flags: **new IP**, **new country** (first time for that account), **temporary access** (allowed only by a travel exception) and
  **auto-blocked**

Filter by person, username, IP (prefix), country code, result, method and dates. The summary shows the last 24 hours and 7 days.
Passwords, codes, recovery codes, tokens, cookies and passkey data are never recorded. Records older than
**Login audit retention** (default 365 days, 0 = forever) are removed by the nightly maintenance.

Countries are approximate: mobile networks, VPNs, iCloud Private Relay and company networks often appear in another country.

## Login protection {#login-protection}

- **Per account / per address:** after *Failed sign-ins before delay* (Authentication, default 8) failures within 15 minutes,
  further attempts are refused for a while.
- **Escalation:** *Failed sign-ins before automatic block* (default 20) failures from one public address within an hour add an
  automatic **blocked IP** rule for *Automatic block duration* (default 60 minutes) and alert administrators. LAN addresses and
  trusted IPs are never blocked automatically. Remove automatic blocks in **Trusted and blocked IPs**, or with
  `sudo personaldocs access-policy clear-automatic`.

## Local GeoIP database {#geoip}

Country lookups use a MaxMind-format database stored on the server (`/var/lib/personaldocs/geoip/country.mmdb`). Visitor
addresses are never sent to a lookup service.

1. Create a free account at maxmind.com and generate a **license key** (GeoLite2).
2. In **Settings → Security & access**, enter the **MaxMind account ID** and **license key** (stored encrypted, never shown again).
3. Click **Update now** in the GeoIP card. With **Update GeoIP weekly** on, it refreshes every Wednesday night.

Alternatively upload a `.mmdb` file (GeoLite2-Country/City or a compatible database) with **Upload .mmdb**.
Every download or upload is opened and test-queried before it replaces the current file, so a failed or corrupt update leaves the
old database and the access policy untouched. The failure is shown in the card, raised as an alert if
*Alert: GeoIP/GoAccess problems* is on, and reported by `personaldocs doctor`.

## Country policy {#country-policy}

**Settings → Security & access → Geographic access control** offers three modes. The active mode is always shown in the
banner at the top of the card.

| Mode | Effect |
|---|---|
| **Off** | No country filtering (IP rules still apply). |
| **Block list** | Every country may reach the app except the ones listed. |
| **Allow list** | Only the listed countries may reach the app; every other country is refused before sign-in. |

*When the country cannot be determined* (no database, or an address missing from it) decides between allow (safer against
lock-outs) and deny (stricter). Refused visitors get a plain "Access not allowed" page; the app's sign-in page and API are never
reached. LAN addresses, trusted IPs and the health-check endpoint are always allowed.

### Example: only Saudi Arabia and India {#example-sa-in}

1. Install the GeoIP database (above) and check **Your connection** shows your country.
2. Enable geographic access control, choose **Allow list**, add *Saudi Arabia* and *India*.
3. Click **Apply policy** and read the confirmation ("ALLOW LIST: only Saudi Arabia, India can reach the app").
4. Before travelling abroad, add **temporary access** for the destination.

Nothing is hard-coded: these countries are only an example.

## Temporary travel access {#temporary}

Allows one country for a time window (start, end, reason), even when the policy blocks it. It ends automatically at the end time; no clean-up is needed.
The list shows **active**, **scheduled** and **expired** rules with who created them. Sign-ins that only succeeded thanks to
temporary access are flagged in the login audit. Creating or ending one can alert administrators.

## Trusted and blocked IP addresses {#ip-rules}

Single IPv4/IPv6 addresses or CIDR ranges (for example `203.0.113.7`, `203.0.113.0/24`, `2001:db8::/48`) with a description or
reason, an enabled switch and an optional expiry. Entries are validated before they are saved; trusted ranges larger than /8 are refused.
Typical uses: trust your office's fixed address so it bypasses the country policy; block an abusive address.

## Rule precedence {#precedence}

The first matching rule wins:

1. Emergency switch `PD_ACCESS_POLICY_DISABLED=1` in the server environment → allow
2. Health endpoint `/api/health` (proxy health checks) → allow
3. Internal addresses (loopback, private LAN, link-local) → allow
4. **Blocked IP** (enabled, not expired) → deny
5. **Trusted IP** (enabled, not expired) → allow
6. Policy disabled or mode Off → allow
7. Country unknown → *unknown location* setting
8. **Temporary country access** active for the country → allow (flagged)
9. Block list: blocked country → deny, otherwise allow. Allow list: allowed country → allow, otherwise deny

So a blocked IP always beats a trusted IP, and trusted IPs and travel exceptions beat the country lists. **Test an address**
(GeoIP card) shows the decision and reason for any address.

## Lock-out protection and recovery {#recovery}

- Before a policy or block is applied, the app checks your current connection; if it would lock you out you must confirm
  explicitly (or add a trusted IP / temporary access first).
- **Undo last change** restores the previous policy.
- With shell access on the server (Proxmox console: `pct enter <id>`):

```
sudo personaldocs access-policy status
sudo personaldocs access-policy off            # disables country filtering, keeps the rules
sudo personaldocs access-policy rollback       # restores the policy before the last change
sudo personaldocs access-policy trust-ip 203.0.113.7 --hours 24
sudo personaldocs access-policy unblock-ip 203.0.113.7
sudo personaldocs access-policy clear-automatic
```

Each command is written to the audit log as a console action and takes effect immediately. As a last resort, add
`PD_ACCESS_POLICY_DISABLED=1` to `/etc/personaldocs/personaldocs.env` and restart `personaldocs-web`. No documents or accounts are touched, and
nothing needs to be reinstalled. There is no way to bypass the policy anonymously from the internet.

## Security alerts {#alerts}

Each alert can be switched on or off in **Settings → Security & access**. Alerts go to the in-app feed and, per person, to email/Telegram:

| Alert | Who | Default |
|---|---|---|
| Repeated failed sign-ins and automatic blocks | administrators | on |
| Sign-in from a new country | the person + administrators | on |
| Sign-in from a new address | the person + administrators | off (noisy on mobile) |
| Sign-in allowed only by temporary access | administrators | on |
| Access policy, IP rule and temporary access changes/expiry | administrators | on |
| GeoIP update or traffic report failures | administrators | on |
| Passkeys, authenticator app, recovery codes, passwordless and admin resets | the person (+ administrators for admin actions) | on |

Alerts are throttled per type and subject (an attack produces one alert, not thousands). They never contain passwords, codes,
tokens or document content.

## Traffic analytics (GoAccess) {#goaccess}

Turn on **Traffic analytics (GoAccess)** in Settings → Security & access. The app writes a privacy-safe access log
(`/var/lib/personaldocs/logs/access.log`, rotated weekly):
- the real client IP
- the path **without query string**, with share-link tokens masked
- status code, size and user agent
- no referrer

Every hour the scheduler turns the log into a report: with [GoAccess](https://goaccess.io/) when it is installed (the installer
installs it when possible), otherwise with an equivalent built-in summary. **Activity & health → Traffic analytics** shows:
- requests, unique visitors and bandwidth
- 401/403/404 counts and bots/scanners
- countries, top IPs, paths, status codes, user agents and requests per day
- requests refused by the access policy

The full GoAccess HTML report can be downloaded by the main administrator; it is never served publicly or as a live dashboard.

## Backups {#backup}

Backups include the login audit, access policy, IP rules and temporary access (database) plus the encrypted MaxMind key
(protected by the backup's encryption key). The GeoIP database file itself is not backed up: after a restore click **Update now** or
upload it again. Until then, *unknown location* applies.
