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
| No OCR text | Image too large or OCR disabled (for the type or for this document); very poor scans may need rescanning |
| OCR engines card says *PaddleOCR: Not installed* or *Self-test failed* | Run `sudo personaldocs ocr status`. Not installed: `sudo personaldocs ocr reinstall` (needs AVX and ~3 GB free disk). Models missing: `sudo personaldocs ocr install-models`. Until then new OCR falls back to Tesseract when fallback is on. See [OCR engines](ocr-engines.md#health). |
| OCR fails with "PaddleOCR stopped without a result (memory limit reached…)" | Large or very detailed pages: raise **PaddleOCR memory limit**, choose fewer pages, or use the Mobile model. The previous OCR result stays. |
| Upgrade says "Some PP-OCRv5 models could not be downloaded" | Run `sudo personaldocs ocr install-models`, then `sudo personaldocs ocr status`. The models need Internet access once (Hugging Face, then Baidu's mirror). If it still fails, the end of `/var/log/personaldocs/install.log` shows where. Until the models are installed, new OCR uses Tesseract. |
| CPU without AVX (Proxmox) | PaddlePaddle needs AVX. Set the VM CPU type to `host` (or check the host CPU), then `sudo personaldocs ocr reinstall`. Tesseract keeps working meanwhile. |
| Removed OCR text still finds the document | The words are in the PDF's own text layer: **Remove OCR data…** with *Also hide the text layer embedded in the file*. See [removing OCR data](ocr-engines.md#remove). |
| Office preview missing | LibreOffice not installed or conversion timed out — the original is still downloadable |
| "Server low on disk space" | Free space or enlarge the LXC disk; uploads stop at 512 MB free |
| Backup "not on a mounted share" | Mount the NAS (`mount -a`) and check the marker file |
| Telegram/email not delivered | Settings → Notifications → Delivery history shows the error; check the person's channel status |
| Google errors | See [Google sign-in troubleshooting](google.md#troubleshooting) |
| Locked out administrator | `sudo personaldocs recover-admin <username> --generate` (add `--reset-2fa` if all passkeys/authenticator devices are lost) |
| "Access not allowed" page (country/IP policy) | From an allowed place: add temporary access or a trusted IP. On the server: `sudo personaldocs access-policy off` — see [recovery](security-access.md#recovery) |
| Everyone in the login audit has the same internal IP | Add the proxy's address to `PD_TRUSTED_PROXY_IPS` — see [real client IP](security-access.md#real-ip) |
| **Sign in with Passkey** greyed out | The page was opened on a plain `http://` address ("Passkeys need the secure HTTPS address of this app"). Open the `https://` address in `PD_PUBLIC_ORIGIN`. See [passkeys](passkeys.md#troubleshooting) |
| Passkey only offered after the password | **Passkey sign-in mode** is *Password + Passkey*, the person turned off passwordless, or the passkey is not discoverable. See [passkeys](passkeys.md#passwordless) |
| "Add a passkey" missing or failing | Passkeys only work on the HTTPS address in `PD_PUBLIC_ORIGIN`, not on `http://<ip>:8000`; check `personaldocs doctor` |
| Lost a passkey | Sign in with another passkey, the authenticator app or a recovery code; or ask the administrator to **Reset 2FA** |
| AI suggestions or Ask AI unavailable | Settings → Local AI → **Test connection**; see [AI troubleshooting](local-ai.md#troubleshooting). Documents keep working without AI |
| GeoIP update failed | The previous database stays in use; check the MaxMind account ID and license key ([GeoIP](security-access.md#geoip)) |
| A family member forgot their password | Settings → Family & access (or Settings → Users) → **Reset password…**: a temporary password shown once, or a reset email. See [password reset](password-reset.md) |
| Password reset email not received | Check spam, the account's email address, SMTP (**Send test email to me**) and the error in the dialog; on an Internet deployment `PD_PUBLIC_ORIGIN` must be `https://`. Links expire after 30 minutes and only the newest link works. See [password reset](password-reset.md#troubleshooting) |
| Temporary password lost before it was passed on | It cannot be shown again. Generate a new one in **Reset password…**; the earlier one stops working |
| **Reset password…** shows **Protected** | An Administrator cannot reset a main administrator's password; another main administrator can, or use `sudo personaldocs recover-admin USERNAME` |
| "Account locked" notice | Too many failed sign-ins for that account; it is paused for a few minutes. If it was not you, change the password and add a passkey or authenticator app |
| Offline files disappeared | Browsers can evict storage; use *Protect storage* or the ZIP export |
| A move is refused | The message says why: no permission at the destination, a folder into its own sub-folder, a same-named folder already there, an archived destination, or the move would give more people access (needs "manage permissions"). Nothing was changed. |
| Drag and drop does nothing on a phone | Use the ⋮ menu → **Move to…**; touch screens do not support dragging files |
| PDF does not display in the viewer | The viewer offers **Download** and, for PDFs, **Use the browser's PDF viewer**. Re-run OCR from the Text (OCR) tab, or re-run the preview from the document menu |
| Push notifications not offered on a device | Push needs the HTTPS address in `PD_PUBLIC_ORIGIN`; on iPhone/iPad the app must be added to the Home Screen first; notifications must be allowed in the browser; only the Apple, Google, Mozilla and Microsoft push services are accepted; **Push notifications (PWA)** must be on in Settings → Notifications. See [push](notifications.md#push) |
| Telegram messages have no buttons | Buttons need an `https://` address; on an `http://` address the links are written into the text instead. See [Telegram](notifications.md#channels) |
| Email shows only plain text | Some mail programs show the plain-text part; it contains the same details and links |
| A recurring alert (antivirus unavailable, storage) was not repeated | It is within the repeat cooldown (`notifications.repeat_cooldown_hours`, default 24). See [noise control](notifications.md#noise) |
| A notification template cannot be saved | Unknown placeholder, other braces, or a placeholder in an action label. See [placeholders](notifications.md#placeholders) |
| Red "Some required notifications cannot reach you" | Add an email address under Profile or link Telegram; the administrator decides which channels are required |
| Weekly/monthly backup did not run | Check *Automatic backups* is on and the NAS is mounted; the Backup status card shows the next run and the last error |
| Antivirus **Unavailable … /run/clamav/clamd.ctl (FileNotFoundError)** / new files *Not scanned* | The socket file the app uses does not exist. Usual causes on Debian 13: `LocalSocket` in `/etc/clamav/clamd.conf` differs from the systemd socket path, clamd was skipped because signatures were missing, or it was killed for lack of memory (about 1.2 GB needed) and not restarted. Run `sudo personaldocs antivirus status` (names the cause), then `sudo personaldocs antivirus repair`, or use **Diagnose / Repair** in Settings → Security → Antivirus. Then re-scan the *Not scanned* files. An engine version still shown on the page is only the last value seen. See [socket missing](antivirus.md#socket-missing) |
| Antivirus **Error** or **Run self-test** fails | clamd answers but cannot scan (or EICAR was not detected). Run **Diagnose / Repair**; check signatures and `journalctl -u clamav-daemon -n 50`. See [status](antivirus.md#status) |
| ClamAV Unavailable; `journalctl -u clamav-daemon` shows `Unknown option EnableVersionCommand` | Debian 13's clamd does not know this option (earlier releases added it) and exits at start. Run `sudo personaldocs antivirus repair`, or by hand: `sudo sed -i '/^EnableVersionCommand/d' /etc/clamav/clamd.conf && sudo systemctl restart clamav-daemon.socket clamav-daemon` |
| ClamAV version or signature date not shown | The app reads them with clamd's VERSION command, or from the signature file header when VERSION is unavailable; check that `/var/lib/clamav/daily.c[vl]d` is readable |
| "Definitions out of date" / critically stale | `systemctl status clamav-freshclam` and `journalctl -u clamav-freshclam`; check outbound internet and DNS from the container, then **Update now**. ClamAV 1.5 also needs the `.cvd.sign` files that freshclam downloads; do not copy only `.cvd` files by hand. See [signatures](antivirus.md#signatures) |
| Type shows **Not assigned** although OCR found details | The document has no type yet: OCR suggests details and possibly a type, but never sets one. Use **Set type** in Details (or accept the suggestion). The main administrator can assign many at once in Settings → Documents & folders → Document types → **Review untyped documents**. See [document types](document-types.md#assign) |
| A value moved to **Previous details — needs review** | The document's new type has no field for it. Choose **Map to a template field**, **Keep as detail** or **Remove**. If it was the expiry date, reminders stop until it is mapped. See [changing a type](document-types.md#change-type) |
| A suggested type was not applied | Suggestions are never applied automatically, and a confirmed type is never replaced ("The confirmed type was kept."). Use **Accept…** or **Change…**. See [suggestions](document-types.md#suggestions) |
| **Delete type** refused | Documents still use the type. Move them to another type first (values are kept or become previous details) or **Archive** the type. See [managing types](document-types.md#manage) |
| Deleting a template field refused | Documents have values in it; turn the field off (*Shown*) instead. See [fields](document-types.md#fields) |
| Bulk **Set type…** skipped documents | They have another confirmed type (tick *Also change documents with a confirmed type*) or you may not edit them. See [bulk](document-types.md#bulk) |
| A file is *Quarantined* | Only the main administrator can **Release…** or **Delete…** it in Settings → Security → Antivirus. See [quarantine](antivirus.md#quarantine) |
| "Host helper not installed" (OS updates, Firewall, Update now) | `sudo personaldocs repair` installs `personaldocs-host.path`; check `systemctl status personaldocs-host.path`. Until then the page shows the commands to run by hand |
| Security updates did not install | Settings → Security → OS updates shows the log of every run; a failed pre-update backup stops the install unless you override it with a reason |
| "Reboot required" stays after rebooting | Reboot from Settings → Security → OS updates or on the host; `personaldocs status` shows whether `/run/reboot-required` is still present |
| Not **Internet Ready** | Settings → Security → Overview lists the failed HTTPS check. Typical causes: `PD_PUBLIC_ORIGIN` not `https://`, no HTTP→HTTPS redirect in the proxy, `X-Forwarded-Proto` not sent, or `PD_HSTS_SECONDS=0`. See [Internet Ready](security-center.md#internet-ready) |
| authentik: "cannot be reached" or **Test connection** fails | Check the issuer address (HTTPS, ending with the application slug and `/`) and that the container can reach it. Local sign-in keeps working |
| authentik: "not linked to a family account" | The person signs in with their password and uses **Link authentik account** in My account → Password & security; accounts are never matched by email. See [linking](authentik.md#linking) |
| authentik: "response could not be verified" | Redirect URI in authentik must be exactly `https://<your address>/api/auth/authentik/callback`; check the client ID and secret and that the provider has a signing key |

## Reporting a bug {#report}

Include the output of `personaldocs doctor` and the app version (Help page). Never send real documents, database dumps or tokens to anyone.
