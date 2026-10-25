# Troubleshooting

## For everyone {#everyone}

| Problem | What to do |
| --- | --- |
| I cannot sign in | Check the address and your password; after several failed attempts sign-in pauses for a while. Ask the administrator to reset your password or authenticator. See [password reset](password-reset.md) |
| A page looks shifted or old after an update | Reload the page once (or close and reopen the installed app) |
| WhatsApp shows **Linking** for a long time | Keep WhatsApp open on the phone; the card follows the steps by itself. If it says **Pairing failed** or **QR code expired**, generate a new code. See [WhatsApp Personal](whatsapp-personal.md#troubleshooting) |
| WhatsApp or Discord shows **Disabled by Admin** or **Service unavailable** | The administrator has not turned the channel on, or the server part is not running. Your other channels are used meanwhile |
| A notification did not arrive | My account → Notifications → **My delivery status** shows what happened on each channel (Delivered, Failed, Expired, Superseded, Fallback Used). See [notifications](notifications.md#delivery-status) |
| The sign-in map says **Map unavailable** | The list of sign-ins below the map still shows everything. The administrator can choose another map provider |
| A tooltip or Learn more link is missing | Help shows only the guides for features you can use; ask the administrator for anything else |

<!-- audience-section: main_admin -->
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
| Sign-in map tiles say **Access blocked** or the map shows **Map unavailable** | The tile provider refused the tiles (HTTP 401, 403 or 429) or could not be reached. Open Settings → Security → Access policy → **Sign-in map provider** and click **Test Map Provider**: it names the reason. Common fixes: choose MapTiler or Stadia Maps with your own key, allow your site's address for the key, or make sure your proxy does not strip the `Referer` header and allows the tile origin in `img-src` and `connect-src`. Sign-in records and Trusted Zones keep working without the map. See [map provider](security-map.md#map-troubleshooting) |
| Settings → Connections: WhatsApp Personal says **Not installed**, **Service stopped** or **Service unavailable** | Run `sudo personaldocs whatsapp-bridge status`, then `sudo systemctl start personaldocs-whatsapp` or `sudo personaldocs whatsapp-bridge install`. Click **Check again**. Other channels are not affected. See [WhatsApp Personal](whatsapp-personal.md#troubleshooting) |
| WhatsApp Personal or Discord shows **Disabled by Admin** | The main administrator has not turned the channel on in Settings → Connections. Your fallback channels are used meanwhile |
| Folder tree rows look shifted after an upgrade | Reload the page once (or close and reopen the installed app) so the browser loads the new web app |
<!-- /audience-section -->

## Maintenance, upgrades and sessions {#maintenance}

<!-- audience-section: admin -->
| Problem | What to do |
|---|---|
| Update Application, Restart or Repair is unavailable: "host helper is not installed" | On the server: `sudo personaldocs repair`, then `systemctl status personaldocs-host.path`. The same operations work in a terminal meanwhile |
| A job stays **Queued** and then fails with "The host helper did not start the operation" | `personaldocs-host.path` is not running: `sudo systemctl enable --now personaldocs-host.path`; check `journalctl -u personaldocs-host` |
| The page says **Reconnecting…** during an upgrade or restart | Normal: the web service restarts. The job continues on the server; the page reconnects by itself. Closing the browser does not stop or fail the job |
| A job stays **Running** for over an hour, then "stopped reporting progress" | The host restarted during the operation. Run Doctor; read the Full Log; for an upgrade follow [maintenance recovery](#maintenance-recovery) |
| Upgrade failed at **Disk space** | Free space (Settings → Security → Storage, or old files outside Personal DM), then Retry |
| Upgrade failed at **Automatic pre-upgrade backup** or **Backup verification** | Nothing was changed. Fix the backup destination (Settings → Backup & Recovery → Destinations → Test), then Retry |
| Upgrade failed at **Target version validation** or *could not reach the update source* | Check the network and `/etc/personaldocs/github-token`, and that the branch/tag exists |
| Upgrade failed at **Install dependencies** or **Frontend build** | Usually network or memory. Retry; on small hosts use a tagged release with a prebuilt frontend |
| Upgrade failed at **Database migrations** | The database was restored from the snapshot when possible; the result says whether the existing version remains operational. Send the Sanitized Support Report |
| Upgrade failed at **Health checks** | Rolled back automatically when the schema is compatible (the result says *verified healthy*), otherwise *Recovery Required* |
| **Rollback** refused: "migrations unknown to …" | A code-only rollback is not safe after those migrations. Restore the pre-upgrade recovery point instead ([Backup & Recovery](backup-restore.md#pre-upgrade-backup)) |
| Doctor shows **NOT TESTED** for a component | That check could not run (for example a service is down); the detail says why. Run it again after Repair |
| Repair ended **Partially Failed** | The listed checks still fail after the repair. Open Technical Details; some problems need a manual fix (see the plan's "without an automatic repair" list) |
| OCR or AI health shows **Attention** | Settings → OCR & processing / Settings → AI: test the engines and profiles; Doctor lists the failing check |
| A session still shows **Active** long after the person left | Activity counts until the Active threshold passes (default 5 minutes); background refreshes do not count. Check the threshold in Settings → Security → Active Sessions |
| A session shows the wrong place or *Unknown location* | Add the network as a Trusted Zone (Settings → Activity & health → Sign-in map & Trusted Zones); GeoIP is approximate and needs the GeoIP database (Settings → Security → Access policy) |
| A home device shows **Untrusted** | Its address is public and no Trusted Zone covers it, for example behind a reverse proxy that is not trusted (`PD_TRUSTED_PROXIES`) so every session shows the proxy address. Add the zone or fix the proxy setting |
<!-- /audience-section -->

<!-- audience-section: main_admin -->
### Maintenance recovery {#maintenance-recovery}

When a job ends with **Recovery Required**:

1. Open the job and download the **Sanitized Support Report**. Note the failed step and the backup reference
   (a database snapshot under `/var/lib/personaldocs/pre-upgrade/` and, with a backup destination, a verified recovery
   point).
2. On the server, check the state: `sudo personaldocs status` and `sudo personaldocs doctor`.
3. If the schema is still compatible, `sudo personaldocs rollback` returns to the previous release and verifies it.
4. Otherwise restore the database snapshot with the previous release active:
   ```
   sudo systemctl stop personaldocs-web personaldocs-worker personaldocs-scheduler
   sudo -u personaldocs pg_restore --clean --if-exists --no-owner -h /var/run/postgresql -d personaldocs /var/lib/personaldocs/pre-upgrade/db-YYYYMMDD-HHMMSS.pgdump
   sudo personaldocs rollback   # now allowed: the schema matches the previous release again
   ```
   or recover the whole application from the verified pre-upgrade recovery point with `sudo personaldocs recover`
   ([Disaster recovery](disaster-recovery.md)).
5. Run Doctor again and keep the support report with your notes.
<!-- /audience-section -->

## Reporting a bug {#report}

Include the output of `personaldocs doctor` and the app version (Help page). Never send real documents, database dumps or tokens to anyone.
