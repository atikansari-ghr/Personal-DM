# Troubleshooting

## First checks {#first}

- `sudo personaldocs status` and `sudo personaldocs doctor` (safe, read-only, redacted).
- Settings → Activity & health: services, tools, disk, failed jobs.
- `sudo personaldocs logs worker` for processing errors.
- The app does not open in the browser: `sudo personaldocs check-access` checks each link from the container to your domain (services, listening port, firewall rule, allowed host name, public DNS record, HTTPS through the proxy) and prints the fix for the first broken one.

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
| Locked out administrator | `sudo personaldocs recover-admin dad --generate` |
| A family member forgot their password | Settings → Family & access → Reset password |
| Offline files disappeared | Browsers can evict storage; use *Protect storage* or the ZIP export |

## Reporting a bug {#report}

Include the output of `personaldocs doctor` and the app version (Help page). Never send real documents, database dumps or tokens to anyone.
