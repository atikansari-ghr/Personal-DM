# Troubleshooting

## First checks {#first}

- `sudo personaldocs status` and `sudo personaldocs doctor` (safe, read-only, redacted).
- Settings → Activity & health: services, tools, disk, failed jobs.
- `sudo personaldocs logs worker` for processing errors.
- The app does not open in the browser: `sudo personaldocs check-access` checks each link from the container to your domain (services, listening port, firewall rule, allowed host name, public DNS record, HTTPS through the proxy) and prints the fix for the first broken one. Opening `http://<container-ip>:8000` directly shows "Bad Request (400)": the app only answers to its domain name, so test with `curl -H "Host: <domain>" http://<container-ip>:8000/api/health`.

## Common problems {#common}

| Problem | What to do |
|---|---|
| Browser says the site can't be reached | DNS record or router port forwarding (80/443 to the proxy) is missing, or the proxy host is not set up. Run `sudo personaldocs check-access`. |
| Proxy shows 502/504 | The proxy cannot reach `http://<container-ip>:8000`: wrong target, firewall rule allowing a different IP, or the app is stopped. Run `sudo personaldocs check-access`. |
| "Forbidden (CSRF)" or sign-in loops | `PD_PUBLIC_ORIGIN` must match the address in the browser exactly (https, no trailing slash); `PD_BEHIND_PROXY=1` behind NPM/Pangolin |
| Uploads fail at a certain size | Raise the proxy's body size limit and the app's Maximum upload size |
| Document stuck in *Processing* | Check the worker is running; failed jobs can be retried in OCR & processing |
| No OCR text | Image too large or OCR disabled; very poor scans may need rescanning |
| Office preview missing | LibreOffice not installed or conversion timed out — the original is still downloadable |
| "Server low on disk space" | Free space or enlarge the LXC disk; uploads stop at 512 MB free |
| Backup "not on a mounted share" | Mount the NAS (`mount -a`) and check the marker file |
| Telegram/email not delivered | Settings → Notifications → Delivery history shows the error; check the person's channel status |
| Google errors | See [Google sign-in troubleshooting](google.md#troubleshooting) |
| Locked out administrator | `sudo personaldocs recover-admin dad --generate` (add `--reset-2fa` if all passkeys/authenticator devices are lost) |
| "Access not allowed" page (country/IP policy) | From an allowed place: add temporary access or a trusted IP. On the server: `sudo personaldocs access-policy off` — see [recovery](security-access.md#recovery) |
| Everyone in the login audit has the same internal IP | Add the proxy's address to `PD_TRUSTED_PROXY_IPS` — see [real client IP](security-access.md#real-ip) |
| "Add a passkey" missing or failing | Passkeys only work on the HTTPS address in `PD_PUBLIC_ORIGIN`, not on `http://<ip>:8000`; check `personaldocs doctor` |
| Lost a passkey | Sign in with another passkey, the authenticator app or a recovery code; or ask the administrator to **Reset 2FA** |
| AI suggestions or Ask AI unavailable | Settings → Local AI → **Test connection**; see [AI troubleshooting](local-ai.md#troubleshooting). Documents keep working without AI |
| GeoIP update failed | The previous database stays in use; check the MaxMind account ID and license key ([GeoIP](security-access.md#geoip)) |
| A family member forgot their password | Settings → Family & access → Reset password |
| Offline files disappeared | Browsers can evict storage; use *Protect storage* or the ZIP export |
| A move is refused | The message says why: no permission at the destination, a folder into its own sub-folder, a same-named folder already there, an archived destination, or the move would give more people access (needs "manage permissions"). Nothing was changed. |
| Drag and drop does nothing on a phone | Use the ⋮ menu → **Move to…**; touch screens do not support dragging files |
| PDF does not display in the viewer | The viewer offers **Download** and, for PDFs, **Use the browser's PDF viewer**. Re-run OCR / preview from the document menu |
| Red "Some required notifications cannot reach you" | Add an email address under Profile or link Telegram; the administrator decides which channels are required |
| Weekly/monthly backup did not run | Check *Automatic backups* is on and the NAS is mounted; the Backup status card shows the next run and the last error |

## Reporting a bug {#report}

Include the output of `personaldocs doctor` and the app version (Help page). Never send real documents, database dumps or tokens to anyone.
