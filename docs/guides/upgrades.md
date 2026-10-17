<!-- audience: main_admin -->
# Upgrades, rollback and repair

## Upgrade {#upgrade}

```
sudo personaldocs upgrade              # newest commit of the configured branch
sudo personaldocs upgrade --ref v0.2.0 # a specific tag
# or with the one-line installer (also runs the health check afterwards):
bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
```

Steps: take an exclusive lock; check free disk; run a **verified application backup** (aborts if the backup fails — use `--skip-backup` only if you have one); fetch and verify the requested revision; build it in a new release directory; run migration checks; stop the worker and scheduler; apply migrations; switch the `current` symlink; restart; run health checks. The previous and new versions are printed and logged.

If anything fails **before** migrations, the old release keeps running untouched. If health checks fail **after** switching, the previous release is restored automatically when the migrations are backwards-compatible; otherwise you are told to restore the pre-upgrade backup.

## Upgrading to Change Set Z (AI Document Intelligence and the OCR engine order) {#change-set-z}

```
sudo personaldocs upgrade     # safety backup, migrations core.0008 and ai.0003, light-ocr install, restart
sudo personaldocs doctor
```

(The change prompt numbered its tests AT-416..AT-435, which Change Sets X and Y already use. Here they are
**AT-441..AT-460**: prompt AT-n = AT-(n+25).)

### What the upgrade does

- **light-ocr is installed** (non-fatal): the pinned `@arcships/light-ocr` 0.5.9 package (PP-OCRv6 Small on ONNX
  Runtime, CPU, about 130 MB) goes to `/opt/personaldocs/light-ocr` with `npm ci` from a lockfile, and a real
  recognition self-test runs. It needs Node.js 20+ (installed from Debian if missing). If it cannot be installed,
  OCR simply uses the next engine. `--without-light-ocr` skips it.
- **Migration `core.0008`** turns the old *Default OCR engine* / *Fall back to Tesseract* settings into the new
  **OCR engine order** and **OCR mode**, keeping what you had: PaddleOCR with fallback → *PaddleOCR → Tesseract*
  (Auto); PaddleOCR without fallback → *PaddleOCR* (Primary only); Tesseract → *Tesseract*. light-ocr is **not** added
  to an upgraded installation automatically. New installations start with *light-ocr → Tesseract → PaddleOCR*.
- The same migration turns *Analyse new uploads automatically* into the **AI mode**: AI off → *AI on Demand* (still
  off); AI on with automatic analysis → *OCR + AI* (new uploads only); AI on without it → *AI on Demand*. **No
  existing document is queued or sent to AI by the upgrade.**
- **Migration `ai.0003`** marks every profile **Local** or **Cloud** (an *External endpoint* profile becomes Cloud) and
  adds the Cloud send controls: an external profile you had already acknowledged keeps sending OCR text and metadata
  as before; **original images and files are off**. It also adds the provenance fields of AI jobs and the AI outputs
  (summaries, OCR checks, expiry analysis, answers). Suggestions and OCR results stay as they are.
- New in Settings → AI: the AI mode, Smart Auto conditions, cloud providers (OpenAI, Anthropic, Gemini, OpenRouter),
  *Allow automatic AI with a Cloud profile* (off) and *Let people choose the AI profile per action* (off).

### After the upgrade (main administrator)

1. **Settings → OCR & processing → OCR engines**: the card lists the engine order with *Available* / *Unavailable* and
   the reason. Press **Self-test light-ocr**. If it passes and you want it, tick *light-ocr* in **OCR engine order**,
   move it to the top and **Save settings** (or leave your order as it is).
2. **Settings → AI**: check the **AI mode** (AI on Demand is recommended). For each profile press **Test Profile**;
   *Last test* shows the checks that ran. For a Cloud profile, review *Data this Cloud profile may receive*.
3. Open a document → **AI Actions**: run *Summarize* or *Verify OCR*, then open **AI History** to see the profile,
   Local/Cloud, the data sent and the status.
4. `sudo personaldocs doctor` shows *OCR engine order*, *light-ocr installed / self-test*, *AI mode*, *AI default
   profile* and its provider/model/capabilities, never a key.

### Rollback

```
sudo personaldocs manage migrate ai 0002
sudo personaldocs manage migrate core 0007
sudo personaldocs rollback
```

`core 0007` restores *Default OCR engine*, *Fall back to Tesseract* and *Analyse new uploads automatically* from the
new settings. `ai 0002` removes the Local/Cloud fields, the send controls, the job provenance and the AI outputs
(summaries, OCR checks, answers). Documents, OCR results and suggestions are kept. `/opt/personaldocs/light-ocr` can be
removed with `sudo rm -rf /opt/personaldocs/light-ocr`.

## Upgrading to Change Set Y (Analyze Document: OCR → AI pipeline) {#change-set-y}

```
sudo personaldocs upgrade     # safety backup, migration ai.0002, restart
sudo personaldocs doctor
```

(The change prompt numbered its tests AT-401..AT-415 and called itself "Change Set X", which is taken. Here it is
**Change Set Y, AT-426..AT-440**: prompt AT-n = AT-(n+25).)

### What the upgrade does

- **Migration `ai.0002`** adds the stage and safe details to AI jobs and a small "what this server supports" record
  to AI profiles. Analyze Document jobs that failed before keep their *failed* state and can now be retried. Nothing
  else changes: AI profiles (including LM Studio profiles), suggestions and OCR results stay as they are. You do
  **not** need to recreate an AI profile.
- **Analyze Document** now asks the AI server for JSON in a way LM Studio accepts (this was the cause of
  *The AI server returned HTTP 400*). OCR always runs first with the engine chosen in Settings → OCR & processing;
  only the recognised text goes to the profile's text model.

### After the upgrade (main administrator)

1. **Settings → Local AI → your profile → Test connection**: every step shows ✓, including *Text model* and
   *Embedding model*.
2. **Test AI analysis**: ✓ with the fields read back from the synthetic sample.
3. **Test OCR — Tesseract** and **Test OCR — PaddleOCR** (for the engines you use): ✓ with a character count.
4. Open a document and choose **Analyse again**: the panel shows the stages and ends with suggestions. In
   **AI jobs**, press **Retry** on earlier failed analyses you still want.

### Rollback

```
sudo personaldocs manage migrate ai 0001
sudo personaldocs rollback
```

Only the stage details of AI jobs and the remembered server capabilities are removed.

## Upgrading to Change Set X (performance) {#change-set-x}

```
sudo personaldocs upgrade     # safety backup, migrations core.0007 and library.0012, then performance maintenance
sudo personaldocs doctor
```

(The change prompt numbered its tests AT-376..AT-400. Here they are **AT-401..AT-425**: prompt AT-n = AT-(n+25).)

### What the upgrade does

- **Migrations.** `core.0007` adds the performance measurement tables. `library.0012` adds one partial index on
  documents, built **concurrently** so reading and writing documents are never blocked while it is created; on a
  family library this takes seconds. No data is changed.
- **Web service.** The service now reads `deployment/gunicorn.conf.py`: 2 processes with 4 threads each. The upgrade
  adds `PD_WEB_THREADS=4` to `/etc/personaldocs/personaldocs.env` if it is missing (existing values are kept).
- **Performance maintenance** (also `sudo personaldocs post-upgrade`): database statistics, index validity, shared
  cache, temporary files, a check of the compressed app files, removal of old measurements. Its result is printed.
- Nothing else changes: users, documents, permissions, search, OCR, notifications, backups and settings stay as they
  are. Search and OCR work exactly as before.

### After the upgrade (main administrator)

1. Sign in, open a large folder and Settings: both should feel quicker.
2. **Settings → Performance**: *Background processing normal*, no warnings; the worker and scheduler report.
3. Optional: **Download Diagnostic Report** and keep it as your own baseline.
4. Behind a reverse proxy that compresses responses itself, nothing needs to change: the app already sends
   compressed files (`Content-Encoding: br` or `gzip`) and the proxy passes them through.

### Rollback

```
sudo personaldocs manage migrate library 0011   # drops the new index
sudo personaldocs manage migrate core 0006      # drops the measurement tables
sudo personaldocs rollback
```

Only the performance measurements are lost. `PD_WEB_THREADS` stays in the environment file and is ignored by the
previous release, whose service file starts 2 single-threaded processes as before.

## Upgrading to Change Set W (named sign-in designs and rotation, complete details and IPs, Notification Detail Level) {#change-set-w}

```
sudo personaldocs upgrade     # safety backup first, then migrations core.0004 – core.0006
sudo personaldocs doctor
```

(The change prompt numbered its tests AT-351..AT-375. Here they are **AT-376..AT-400**: prompt AT-n = AT-(n+25).)

### What the upgrade does

- **Sign-in designs.** `core.0005` adds the design table; `core.0006` creates the five protected built-in designs.
  If you had uploaded a wallpaper, it becomes a custom design named **Custom wallpaper**, with your overlay and image
  position as its focal point. Whatever was active stays active, so the sign-in page looks the same. Nothing has to
  be uploaded again, and running the migration twice creates nothing new. The Desktop, Tablet and Phone versions and
  the colours are made the first time the design is shown.
- **Notification Detail Level.** `core.0004` sets the new setting to **Full Details**, or **Minimal Details** if you
  had turned off *Include names*. The two old switches are no longer shown.
- **Complete values.** Document numbers, identifiers and IP addresses are shown in full to the people allowed to see
  them. Nothing about who may see a document changes.
- Users, documents, permissions, backups, routing and other settings are unchanged.

### After the upgrade (main administrator)

1. Open the sign-in page in a private window: it looks as before.
2. **Settings → Overview & sign-in → Sign-in page design**: your designs are listed, the active one marked **In use**.
   To make the panel match your wallpaper, select the design, click **Edit**, choose **Auto — Match wallpaper** and
   **Save design**.
3. Optional: set up **Automatic Design Rotation** with at least two designs and click **Preview Rotation**.
4. **Settings → Notifications → Notification Detail Level**: check Full or Minimal. Each person can override it in
   **My account → Notifications**.
5. `sudo personaldocs doctor` reports no errors.

### Rollback

`personaldocs rollback` refuses while the database contains migrations the previous release does not know, so
reverse this release's migrations first, then switch back:

```
sudo personaldocs manage migrate core 0003   # removes the design table and the detail-level marker (data kept elsewhere)
sudo personaldocs rollback
```

The previous settings (`login.design`, `login.wallpaper_file`, overlay and position) are kept in step with the active
design, so the previous release shows the same sign-in page. Designs and rotation settings are kept for a later upgrade; the
old release ignores them. Notification masking returns to the old behaviour.

## Upgrading to Change Set V (NAS in Backup Destinations, English sign-in map, tooltips, Help permissions, WhatsApp pairing) {#change-set-v}

```
sudo personaldocs upgrade                    # safety backup first, then migrations (NAS → destination, map provider)
sudo personaldocs whatsapp-bridge update     # only if you use WhatsApp Personal: bridge 1.1.0 (pinned, tested)
sudo personaldocs doctor
```

(The change prompt numbered its tests AT-331..AT-350. Here they are **AT-356..AT-375**: prompt AT-n = AT-(n+25).)

### What the upgrade does

- **Storage & NAS → Backup Destinations.** The migration `ops.0003_nas_into_destinations` moves the NAS connection
  (type, server, share, folder, username, domain, protocol version) into a NAS destination. It adopts the destination
  that already pointed at `/mnt/pdnas`, or creates **NAS backup share**. The SMB password stays encrypted where it
  was. Recovery points, copies, policies and the files on the share are not touched. Running it again creates nothing
  new. A configuration that does not validate becomes **Needs Attention — Migration incomplete; existing backup data
  preserved** instead of being dropped.
- **Backup queue.** Backups, verifications, test restores, key rotation and recovery validation now run one at a
  time, first in, first out. Each destination has **Backup Now**.
- **Sign-in map.** The default provider becomes **OpenFreeMap** (English labels, no key). An explicit *OpenStreetMap*
  choice is switched to OpenFreeMap (migration `security.0005_map_english_labels`); MapTiler, Stadia and custom
  servers are kept.
- **Help** shows each person only the guides and sections for the features they may use (enforced by the server).
- **WhatsApp.** New fields record verification (migration `notify.0005_whatsapp_verification`). Existing links are
  kept, but the Personal DM upgrade does **not** replace the bridge: run `sudo personaldocs whatsapp-bridge update`.
- Users, documents, permissions, settings, backups, Trusted Zones and notification routing are otherwise unchanged.

### After the upgrade (main administrator)

1. **Backup & Recovery → Destinations.** Find the NAS card (the old Settings → Storage & NAS address redirects
   here).
   - Click **Test Connection**. **Healthy** with the free space means the share is mounted and writable.
   - If it says **Needs Attention**, click **Edit Configuration**, check the fields (enter the SMB password if it was
     never stored), **Save**, **Test Connection**, then **Retry Migration**.
   - Optional: set **Space warning below / Space critical below** (defaults 20 % and 10 %).
2. **Sign-in map.** Open **My account → Sign-in security**: place names are in English. If your reverse proxy sets
   its own Content-Security-Policy, add `https://tiles.openfreemap.org` to `connect-src` and `img-src` (and keep
   `https://tile.openstreetmap.org` for browsers without WebGL).
3. **WhatsApp Personal** (only if you use it):
   - `sudo personaldocs whatsapp-bridge update` installs bridge **1.1.0** with the maintained protocol library
     (Baileys 7.0.0-rc14). It archives the encrypted sessions first, self-tests, and rolls back by itself on failure.
     The command prints the diagnostics at the end.
   - **Settings → Connections → WhatsApp Personal → Run Diagnostics**: DNS, network, system time and storage should
     all say OK.
   - People whose phone stayed on *Connecting* click **Generate new QR code** (or **Link WhatsApp**) and scan again.
     The card should end on **Linked & Verified**.
4. **Help.** Sign in as a family member and open Help: administrator guides are not listed.

### Behind a reverse proxy

Allow `https://tiles.openfreemap.org` in `connect-src` and `img-src` if the proxy sets its own CSP. Nothing else
changes.

### Rollback

`sudo personaldocs rollback` switches back to the previous release (the upgrade's safety backup is verified first).
The migrations only add data: the old `nas.*` settings are still there, so the previous release's Storage & NAS page
works again unchanged, and the extra destination fields are ignored. To go back to bridge 1.0.0:
`sudo personaldocs whatsapp-bridge rollback` (people then link again). To restore the old map labels, choose
**OpenStreetMap standard** in Settings → Security → Access policy.

## Upgrading to Change Set U (folder tree, sign-in map provider, sign-in designs, WhatsApp and Discord) {#change-set-u}

```
sudo personaldocs upgrade
# or: bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
sudo personaldocs doctor        # the map check now names the provider and warns when the last map test failed
```

(The change prompt numbered its tests AT-311..AT-330. Here they are **AT-336..AT-355**: prompt AT-n = AT-(n+25).)

### What the upgrade does

- **No database migrations.** Two settings are added: **Map provider** and **Map provider API key**.
- Users, documents, permissions, settings, backups, Trusted Zones and notification channels are not changed.
- A custom tile address you set earlier is detected and keeps being used (provider *Custom*).
- Discord and WhatsApp stay off until you turn them on. Saved webhooks and WhatsApp links are kept.
- The folder tree and the sign-in design thumbnails are fixed by the new web app. There is nothing to do.

### After the upgrade (main administrator)

1. **Sign-in map.** Open **Settings → Security → Access policy → Sign-in map provider**.
   - Keep **OpenStreetMap** for an occasional look at a small family map, or choose **MapTiler** or **Stadia Maps**
     and paste your own API key (restrict the key to your site's address in the provider's dashboard), or **Custom**.
   - Click **Save settings**, then **Test Map Provider**. **Working** means the tiles load.
   - If it says **Failed**, the message names the reason (HTTP 401, 403 or 429, or network) and what to change.
2. **WhatsApp Personal** (only if you installed the bridge). Open **Settings → Connections → WhatsApp Personal**.
   - The **Bridge service** table should say *Installed and running – turned off*, version 1.0.0, protocol 1,
     *Compatible (tested version)*.
   - Turn **WhatsApp Personal** on and click **Save settings**. The status changes to **Running** (no restart).
   - Each person links their phone under **My account → Notifications → WhatsApp Personal → Link WhatsApp**.
3. **Discord** (optional). Turn **Discord webhooks** on in **Settings → Connections**. Each person adds their own
   webhook under **My account → Notifications**.
4. **Sign-in design.** Open **Settings → Overview & sign-in**. Check the **Live sign-in preview**. Choosing a design
   now previews it; click **Save design** to publish it.

### Behind a reverse proxy

If your proxy sets its own Content-Security-Policy, allow the tile origin in **both** `img-src` and `connect-src`
(for example `https://tile.openstreetmap.org`, `https://api.maptiler.com` or `https://tiles.stadiamaps.com`). Do not
strip the `Referer` header from the browser's tile requests: OpenStreetMap blocks requests without it.

### Rollback

`sudo personaldocs rollback` switches back to the previous release. The two new settings are then ignored.

## Upgrading to Change Set T (encrypted recovery, notification routing, sign-in map) {#change-set-t}

```
sudo personaldocs upgrade
# or: bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
sudo personaldocs doctor        # includes the new recovery, destination, readiness, Discord, WhatsApp and map checks
sudo personaldocs backup health
```

(The change prompt numbered its tests AT-251..AT-310. Here they are **AT-276..AT-335**: prompt AT-n = AT-(n+25).)

### What the upgrade does

1. The usual verified pre-upgrade backup runs first, with the previous release's backup code.
2. It applies these migrations. All are additive; nothing is deleted:
   - `ops.0001_initial`: recovery points, copies, destinations, policies, key generations and restore runs.
   - `ops.0002_migrate_backup_settings`: turns your existing backup folder (`backup.target`) into the destination
     **Existing backup share**, and your schedule into the policy **Default**. Incrementals are **off**, so nothing
     runs more often than before.
   - `notify.0004_routing_discord_whatsapp`.
   - `security.0004_…`: Trusted Zones, recognised devices, sign-in location and risk.
   - `accounts.0009_usersession_recognized_device`.
3. It rebuilds the web app. Leaflet (the map library) is bundled, so nothing is loaded from a CDN.

Existing email, Telegram, in-app and push notifications keep their settings. Discord and WhatsApp are **not** turned on
for anyone.

### After the upgrade (main administrator)

1. Open **Settings → Backup & Recovery → Overview**. Folder backups made by earlier releases are listed under *Legacy
   folder backups* and can still be verified and restored.
2. In **Policies & schedule**, edit *Default*:
   - Set **Incremental every** to `4` hours (recommended).
   - Check the Full backup day and time, and **Keep Full backups** (4 weeks recommended).
3. In **Destinations**, click **Test** on *Existing backup share*. Add a second destination if you can, for example a
   USB disk, S3 or a cloud drive.
4. Click **Back up now**. The first encrypted backup creates the **Backup Recovery Key**.
5. In **Recovery Key**:
   - Click **Show** and store the key in your password manager.
   - Click **Export Emergency Recovery Package** and keep the `.pdrp` file offline, together with its passphrase.

   *Recovery Readiness* then shows **Ready**.
6. Optional, under **Settings → Activity & health → Sign-in map & Trusted Zones**: add a **Trusted Zone** for your home
   network (and VLANs, VPN), with a map pin.
7. Optional, under **Settings → Connections**:
   - turn **Discord** on, so that people can add their own webhooks;
   - install the experimental WhatsApp bridge with `sudo personaldocs whatsapp-bridge install` (it needs Node.js 20 or
     newer), then turn **WhatsApp Personal** on.
8. Each person can then choose channels per category, quiet hours and digests under **My account → Notifications**.

### Behind a reverse proxy

The sign-in map loads picture tiles from `https://tile.openstreetmap.org` by default. The app adds that origin to its
own `img-src` Content-Security-Policy automatically. If your proxy sets its own CSP header, add the tile origin there
too, or choose another provider in **Settings → Security → Access policy → Sign-in map provider** (see [Change Set U](#change-set-u)). To show only the list, turn **Sign-in
map** off.

### Rollback

`sudo personaldocs rollback` switches back to the previous release. The new tables stay, unused. Encrypted recovery
points made by this release can only be read by this release or newer. Keep the pre-upgrade folder backup until you
have a verified encrypted recovery point and an exported Emergency Recovery Package.

## Upgrading to Change Set Q (PaddleOCR PP-OCRv5 and the complete OCR lifecycle) {#change-set-q}

```
sudo personaldocs upgrade
# or: bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
sudo personaldocs ocr status   # PaddleOCR versions, models, AVX and a real PP-OCRv5 inference self-test
sudo personaldocs doctor       # includes the OCR checks (engine, models, self-test, Tesseract, queue, storage, orphans)
```

(The change prompt called this "Change Set P" with tests AT-191..AT-210. Those numbers were already in use, so here it
is **Change Set Q** with tests **AT-211..AT-230**: prompt AT-n = AT-(n+20).)

**Before you start:** PaddlePaddle needs a CPU with **AVX** (`grep -c avx /proc/cpuinfo` must print more than 0;
on Proxmox use CPU type `host` for VMs) and about **3 GB free disk** for the first installation. On a 6 GB / 4 vCPU
container the defaults are sized to fit. Without AVX, with too little disk, or with `--without-paddleocr`, the
upgrade still completes and OCR keeps using Tesseract.

What the upgrade does (the post-upgrade step runs it for you, after the verified backup):

1. Applies the migration **`library.0010_ocr_engines_lifecycle`**:
   - adds the engine, model, profile and text-position fields, the per-document OCR switch and the OCR run history;
   - labels existing results **Tesseract (Legacy)** (or *Unknown* when that cannot be determined);
   - maps each document type's Tesseract languages to a language profile (Arabic → Arabic + English, Hindi → Hindi +
     English, …).

   **No OCR job is queued and no document is re-processed.**
2. Installs `apt` libraries `libgomp1`, `libgl1`, `libglib2.0-0` and builds the isolated PaddleOCR environment
   **`/opt/personaldocs/paddle-venv`** (PaddlePaddle 3.2.2, PaddleOCR 3.7.0, PaddleX 3.7.2; about 1.3 GB, several
   minutes). It is built next to the old one and swapped in only when complete.
3. Downloads the **PP-OCRv5 models** of the offered language profiles into **`/var/lib/personaldocs/paddle`**
   (about 60 MB; from Hugging Face, retried from Baidu's mirror). This needs Internet access once.
4. Runs the **self-test**: real PP-OCRv5 inference on a generated image. Only a passing self-test makes the engine
   *Healthy*.
5. Sets `PD_PADDLE_PYTHON` / `PD_PADDLE_HOME` in `/etc/personaldocs/personaldocs.env` and installs the worker unit
   with `MemoryHigh=3400M`, `MemoryMax=4000M` and `CPUWeight=50`.

After the upgrade:

- **New** OCR runs use PaddleOCR (PP-OCRv5); results show their engine.
- Existing OCR text stays as it was, labelled Tesseract (Legacy).
- To upgrade old results deliberately, use **Settings → OCR & processing → Existing OCR data**: filter *Tesseract*,
  select documents (or all matching), then **Re-process with PP-OCRv5**, preview and confirm. Each document keeps its
  old text until the new result succeeds, and confirmed details are never overwritten.
- Check **Settings → OCR & processing → OCR engines**. It should say *Healthy*; otherwise run
  `sudo personaldocs ocr status` and see [troubleshooting](troubleshooting.md).
- If unwanted OCR text came back after removal in earlier releases, remove it again with **Remove OCR data…**. Tick
  *Also hide the text layer embedded in the file* if the words are in the PDF itself. Optionally disable OCR for that
  document.
- Offer Telugu + English or Tamil + English under **Offered language profiles**, then run
  `sudo personaldocs ocr install-models`.

Rollback: `sudo personaldocs rollback` switches back to the previous release; the PaddleOCR environment and models stay
on disk unused. The new columns are only used by this release. If the previous release refuses to start, restore
the pre-upgrade database snapshot as described in [Rollback](#rollback). To remove PaddleOCR completely:
`sudo rm -rf /opt/personaldocs/paddle-venv /var/lib/personaldocs/paddle`, then remove PaddleOCR from the **OCR engine
order** (since Change Set Z; earlier releases: set **Default OCR engine** to Tesseract (Legacy)).

## Upgrading to Change Set P (passkey sign-in, password reset, ClamAV repair) {#change-set-p}

> **ClamAV fix (2026-10-08).** If the Antivirus page shows *Unavailable* and `journalctl -u clamav-daemon` says `Unknown option EnableVersionCommand`: an earlier release added that option, which Debian 13's clamd does not know, so clamd stops at start. Upgrade again (or run `sudo personaldocs antivirus repair`) — the repair now removes it. Quick manual fix: `sudo sed -i '/^EnableVersionCommand/d' /etc/clamav/clamd.conf && sudo systemctl restart clamav-daemon.socket clamav-daemon`. The `clamd.conf.personaldocs-backup` file may also contain the line; remove it there too before restoring that backup.

```
sudo personaldocs upgrade
# or: bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
sudo personaldocs antivirus status   # every ClamAV check and the likely cause of any problem
sudo personaldocs doctor             # starts with the same ClamAV diagnosis, then the app checks
```

(The change prompt for this release called it "Change Set O" with tests AT-176..AT-190. Those numbers were already
used by the rich notifications release, so in this repository it is **Change Set P** with tests **AT-196..AT-210**:
prompt AT-176 is AT-196, AT-177 is AT-197, and so on up to AT-190, which is AT-210.)

No new system packages and no new Python packages. This release adds **two database migrations**, applied
automatically after the verified backup:

- `accounts.0007_passkey_mode`: replaces the on/off setting `auth.allow_passwordless` with **Passkey sign-in mode**
  (`auth.passkey_mode`). An explicit earlier choice is kept: saved *off* becomes **Password + Passkey**, saved *on*
  becomes **Passwordless**, never chosen becomes **Passwordless** (the new default). In passwordless mode it also turns
  passwordless sign-in on for accounts that already have a discoverable passkey. See
  [passkeys after upgrading](passkeys.md#upgrade).
- `notify.0003_template_brand_footer`: **Branding name** and **Footer / help text** for notification templates.

**The ClamAV repair runs automatically.** The post-upgrade step (which `personaldocs upgrade` and the one-line
upgrade run for you) now runs the [antivirus repair](antivirus.md#repair) instead of assuming that installed packages
mean antivirus works. It:

- rewrites `LocalSocket` in `/etc/clamav/clamd.conf` to the systemd socket path `/run/clamav/clamd.ctl` (the original
  is backed up once as `/etc/clamav/clamd.conf.personaldocs-backup`) and removes any TCP listener;
- installs the restart drop-in `/etc/systemd/system/clamav-daemon.service.d/50-personaldocs.conf` and the tmpfiles
  entry `/etc/tmpfiles.d/personaldocs-clamav.conf`;
- downloads missing signatures, starts the socket and the daemon in the right order, and runs a clean + EICAR
  self-test.

This can take **a few minutes** (up to 4 minutes of waiting) while clamd loads its signatures. It fixes the
"Unavailable … `/run/clamav/clamd.ctl` (FileNotFoundError)" state described in
[antivirus troubleshooting](antivirus.md#socket-missing). If it reports a problem, the upgrade itself still
completes; run `sudo personaldocs antivirus repair` again after fixing the cause (for example too little memory).

What changes:

- **Passwordless is the default** unless it was explicitly turned off before. The sign-in page shows **Sign in with
  Passkey** before the password, and people who already have a discoverable passkey can use it straight away. See
  [the sign-in screen](passkeys.md#sign-in-screen).
- People can sign in with their **email address** instead of the username (when it belongs to exactly one active
  account).
- **Administrators** (the Administrator role) can now reset the passwords of accounts that are not main
  administrators, in Settings → Users. See [password reset](password-reset.md).
- A **temporary password reset always signs the person out** on every device.
- New security notifications (password reset requested, administrator reset, temporary password issued, password
  reset completed, account locked, Google linked or removed) with [mandatory security text](notifications.md#security-templates).
- The Antivirus page shows **Healthy / Degraded / Unavailable / Error** based on a real scan, and **Run self-test** and
  **Diagnose / Repair**. Unavailable and Error now put Security Health **At Risk**.

Check by hand after upgrading:

1. Settings → Security → Antivirus shows **Healthy** and **Run self-test** passes.
2. **Reboot the LXC once** (or `pct reboot <id>` on the Proxmox host) and check the Antivirus page again; reboot
   persistence has not been tested on a real host yet.
3. Sign in with **Sign in with Passkey** on each device and browser you use.
4. Send a password reset email to yourself (Forgot password? on the sign-in page) and check that it arrives and the
   link works once.
5. If you prefer passkeys only after the password, set Settings → Authentication → **Passkey sign-in mode** to
   *Password + Passkey*.

To go back, restore the pre-upgrade backup: this release adds migrations, so `sudo personaldocs rollback` is refused
unless the previous release knows them (see [Rollback](#rollback)). The ClamAV changes are host configuration and stay
in place; they also work with the previous release. To restore Debian's ClamAV configuration, copy
`/etc/clamav/clamd.conf.personaldocs-backup` back to `/etc/clamav/clamd.conf` and restart `clamav-daemon`. The drop-in
and tmpfiles files can stay.

## Upgrading to the rich notifications release (Change Set O) {#change-set-o}

```
sudo personaldocs upgrade
# or: bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
```

No extra post-upgrade step is needed for this release. If you are coming from a release **before Change Set M**,
the `sudo personaldocs post-upgrade` step described [below](#change-set-m) still applies once. No new system packages
are installed; two small Python packages for Web Push, `http-ece` 1.2.1 and `py-vapid` 1.9.4, are installed
automatically with the release.

This release adds **one database migration**, applied automatically after the verified backup:

- `notify.0002_rich_notifications`: event, category, severity, icon, summary, details and a TEST flag on in-app
  notifications; event, severity, the HTML part, the push payload, the provider's message id and a TEST flag on
  outgoing messages; new tables for push subscriptions, notification templates and expiry snoozes. Its data step
  sorts existing in-app notifications into categories by their kind; their title, text, links and read state are
  unchanged.

What changes and what stays:

- Existing SMTP and Telegram configuration, everyone's preferences, the critical events and their channels and the
  expiry schedules are unchanged.
- Email becomes an HTML message with a plain-text part; Telegram messages get formatting and buttons (buttons only on
  an `https://` address); the in-app list becomes the Notification Center with banners.
- Push is a new channel. It is **never added to anyone's channels automatically**; it needs the `https://` address.
- The keys for signing push messages are created on first use, stored encrypted in the database and included in
  backups.

After upgrading (optional):

1. **Settings → Notifications → Templates**: review the wording of the events you care about and use
   **Send a TEST message to yourself** to see the email, Telegram, in-app and push versions. See
   [templates](notifications.md#templates).
2. Decide on **Include document numbers in email/Telegram** (off by default) and the **repeat cooldown** (24 hours).
   See [privacy](notifications.md#privacy) and [noise control](notifications.md#noise).
3. Family members who want push turn it on **per device** in My account → Notifications → *Push notifications on
   this device* (on iPhone/iPad after adding the app to the Home Screen). See [push](notifications.md#push).

To go back, restore the pre-upgrade backup: this release adds a migration, so `sudo personaldocs rollback` is refused
unless the previous release knows it (see [Rollback](#rollback)).

## Upgrading to the document types release (Change Set N) {#change-set-n}

```
sudo personaldocs upgrade
# or: bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
sudo personaldocs doctor     # info line: typed / untyped / with suggestions
```

No extra post-upgrade step is needed for this release. If you are coming from a release **before Change Set M**,
the `sudo personaldocs post-upgrade` step described [below](#change-set-m) still applies once. No new system packages
are installed.

This release adds **one database migration**, applied automatically after the verified backup:

- `library.0009_document_type_templates`: document type templates (fields with type, role, required, OCR/AI and
  search flags), per-type reminder days, the source and confirmation of each document's type, pending type
  suggestions, provenance of each detail, and the suggested type of a folder. Its data step:
  - gives every existing type its template: the standard fields of its starting template plus the fields its OCR
    policy listed;
  - keeps the type of every **typed** document and marks it confirmed with the source *Migrated*;
  - leaves **untyped** documents untyped (types are not guessed from field names);
  - turns values of typed documents that are not in the template into **additional details** of that document,
    except confirmed issue, expiry and "does not expire" values, whose field is added to the template so dates and
    reminders keep working;
  - deletes nothing.

After upgrading (optional):

1. `sudo personaldocs manage document_types report` prints how many documents are typed, untyped and have
   suggestions.
2. Set a **suggested document type** on folders that hold one kind of document (folder ⋮ → *Suggested document
   type…*). It only affects new uploads. See [folder suggestions](document-types.md#folder-suggestions).
3. **Settings → Documents & folders → Document types → Review untyped documents**: assign types to older untyped
   documents; nothing is applied until you confirm. See [review](document-types.md#review-untyped).
4. Check the templates and reminder days of the types you use. See [managing types](document-types.md#manage).

To go back, restore the pre-upgrade backup: this release adds a migration, so `sudo personaldocs rollback` is refused
unless the previous release knows it (see [Rollback](#rollback)).

## Upgrading to the antivirus, authentik and security center release (Change Set M) {#change-set-m}

```
sudo personaldocs upgrade
sudo personaldocs post-upgrade   # once, when coming from an older release: installs ClamAV and the host helper
sudo personaldocs status     # clamav-daemon, clamav-freshclam and personaldocs-host.path should be active
sudo personaldocs doctor     # ClamAV, signature age, host helper, HTTPS, storage thresholds, pending reboot
```

The upgrade is run by the previously installed `personaldocs` command, which does not know the new installer steps
yet; `post-upgrade` then runs the steps of the new command (ClamAV, host helper units, optional security tools). It is
safe to repeat, keeps all data, keys and accounts, and `sudo personaldocs repair` does the same and more. The one-line
`personal-DM.sh -- upgrade` runs `post-upgrade` for you, and from this release on `personaldocs upgrade` calls it
itself, so later upgrades need no extra step.

This release adds **five database migrations**, applied automatically after the verified backup:

- `accounts.0005_administrator_role`: the **Administrator** role (`is_admin`). No existing account gets it.
- `accounts.0006_external_identity`: authentik account links.
- `library.0008_antivirus`: the scan status per file. Every existing file is marked *Not scanned* ("Stored before
  antivirus scanning was added").
- `security.0002_antivirus` and `security.0003_security_center`: library scan runs, security test history, OS update
  and reboot records, and security records.

After upgrading:

- **Antivirus:** `clamav`, `clamav-daemon` and `clamav-freshclam` are installed and clamd listens only on the local
  socket `/run/clamav/clamd.ctl`. ClamAV needs about **1.2 GB of memory**; on a smaller machine use
  `sudo personaldocs repair --without-antivirus` and turn scanning off in Settings → Security → Antivirus. The first
  signature download can take a few minutes. Then run **Scan entire existing library** in Settings → Security →
  Antivirus so older files get a real status. See [antivirus](antivirus.md#install).
- **Host helper:** `personaldocs-host.path` is installed, so Settings → Security can check and install Debian
  security updates, update ClamAV signatures, inspect the firewall and reboot. Nothing is installed automatically.
  See [OS updates](security-center.md#updates).
- **HSTS:** for an `https://` public origin the app now sends `Strict-Transport-Security` (one year). Set
  `PD_HSTS_SECONDS=0` in `/etc/personaldocs/personaldocs.env` to turn it off, or a smaller value while testing. See
  [reverse proxy](reverse-proxy.md#hsts).
- **Settings → Security reorganised:** it is now the security center (Overview, Antivirus, Security test, OS updates,
  Firewall, Security records, Storage). The country/IP access policy, GeoIP, alerts and traffic analytics moved to
  **Settings → Security → Access policy**; their values are unchanged.
- **Deployment exposure** starts as *LAN only*. If the site is published on the Internet, change it and check
  **Internet Ready**. See [Internet Ready](security-center.md#internet-ready).
- **authentik** stays off until you configure it. See [authentik](authentik.md#setup).
- **Nothing is deleted:** existing accounts, folders, documents, versions and records are kept. Security records are
  kept for one year by default.

To go back, restore the pre-upgrade backup: this release adds migrations, so `sudo personaldocs rollback` is refused
unless the previous release knows them (see [Rollback](#rollback)). ClamAV stays installed; remove it with
`apt-get remove clamav-daemon clamav-freshclam` if wanted.

## Upgrading to the selective OCR / Overview release (Change Sets K and L) {#selective-ocr-overview}

```
sudo personaldocs upgrade
# or: bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade
sudo personaldocs doctor     # also reports missing OCR language packs
sudo personaldocs repair     # only if doctor reports a missing language pack
```

This release adds **three database migrations**, applied automatically after the verified backup:

- `library.0006`: OCR state, sources, languages and errors per document, and the OCR policy fields per document type.
- `library.0007`: fills the policy. Each type gets its expected fields and English as default language, and the
  *Employee / company ID* type is added. On an **existing installation** (setup already completed) every type and
  untyped documents are set to **Automatic with AI allowed**, so uploads are recognised as before. Documents that
  were already recognised get the state *Confirmed* (or *Needs review* if suggestions are open). **New
  installations** start with **Manual** OCR and no AI access to recognised text.
- `core.0003`: the weather cache and holiday corrections tables.

After upgrading:

- **Accounts:** every existing account, folder and document is kept. No accounts are added or removed. New
  installations create only the Main Administrator; see [setup](setup.md#six-accounts).
- **Python packages:** the new dependencies (`holidays`, `hijridate`, `python-dateutil`, `six`) are installed by the
  upgrade in the new release.
- **OCR language packs:** upgrade and repair install the Tesseract packs for the offered languages (English, Arabic
  and Hindi by default: `tesseract-ocr-ara`, `tesseract-ocr-hin`). If `doctor` lists a missing pack, run
  `sudo personaldocs repair`.
- **OCR policy:** review **Settings → OCR & processing → OCR policy per document type** and switch types to *Manual*
  or *Disabled* where automatic OCR or AI is not wanted. See [selective OCR](ocr-corrections.md#selective).
- **Overview:** people who had saved a widget choice keep it; they add the new widgets (Today, Weather, Month
  calendar, Upcoming holidays, Documents summary, Shared with me, Recent activity) with **Customize Overview**.
  People who never chose get the new default set. See [Overview](overview.md).
- **Weather** is off until an administrator enables it in Settings → Overview & sign-in.
- **Sign-in page:** uses the *Minimal* design and the default title until you change it. See
  [sign-in page designs](login-designs.md).

To go back, `sudo personaldocs rollback` works only while the previous release knows every applied migration; this
release adds migrations, so otherwise restore the pre-upgrade backup (see [Rollback](#rollback)).

## Upgrading to the browsing, OCR and installer release (Change Set J) {#change-set-j}

```
sudo personaldocs upgrade
sudo personaldocs repair     # installs tesseract-ocr-osd (orientation detection) on older installations
sudo personaldocs doctor
```

This release adds **three database migrations**, applied automatically by the upgrade after its verified backup:

- `library.0004`: OCR quality per version and the "Does not expire" flag. Existing documents are unchanged.
- `library.0005`: sub-folders whose icon was assigned automatically now use the standard 📁 icon. Folders directly
  in a person's area keep their suggested icon, and icons someone chose are kept.
- `core.0002`: if the application name is still the old default "Personal Documents", it becomes "Personal
  Documents Management System". A name you chose is kept.

After upgrading:

- **Folder view:** each person's view (List, Thumbnails, Details) and sort order are now saved to their account.
  The first time, everyone starts with List / Newest first.
- **OCR:** new uploads use the improved pipeline. To improve an older scan, open it and use **Re-run OCR…** in the
  Text (OCR) tab.
  Confirmed details are never overwritten.
- **One-line installer:** from now on you can also upgrade with
  `bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade`
  (the raw URL works only while the repository is public).
- **Browser cache:** the app reloads its new version automatically; if a page looks old, reload it once.

## Upgrading to the public-release corrections (October 2026) {#change-set-2026-10-ui}

Same commands as below — `sudo personaldocs upgrade`, then (once, if you never ran it after the security release)
`sudo personaldocs repair`, then `sudo personaldocs doctor`. This step adds **no database migrations**; all new
options are stored as settings. After upgrading:

- **Notifications:** your earlier channel choices become the starting point of the new per-event table. Check
  **Settings → Notifications → Critical notifications / Channels for critical notifications / Delivery problems**:
  if email or Telegram are not configured yet, either configure them (Settings → Connections) or remove them from
  the critical channels.
- **Backups** keep running daily at the same time; choose weekly or monthly in Settings → Storage & backup if you
  prefer.
- **Dashboard** (now called Overview): your previous widget list is kept (sections that were always shown stay
  visible); use **Customize Overview** to change it.
- **Browser cache:** the app reloads its new version automatically; if a page looks old, reload it once.

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
1. Settings → Security & access (since Change Set M: Settings → Security → Access policy): enter MaxMind credentials and **Update now** for GeoIP; review alerts; enable traffic analytics.
2. Settings → Authentication: decide on passkeys / passwordless / required two-step verification.
3. Settings → Local AI: add a profile pointing at your LAN AI server.
4. `sudo personaldocs doctor` to confirm the real client IP, GeoIP, passkey origin and AI checks.

## Rollback {#rollback}

```
sudo personaldocs rollback
```

Switches back to the previous release only if its code knows every migration applied in the database (same schema). If the newer version changed the schema, running old code is refused. Then either:

- reverse the newer release's migrations with the newer release still active, then roll back. Each "Upgrading to
  Change Set …" section above names its migrations; for example `sudo personaldocs manage migrate core 0006` returns
  the `core` app to migration 0006. Only reversible migrations can be undone this way; or
- restore the pre-upgrade backup (`personaldocs restore /mnt/nas-backup/personaldocs/backup-...`).

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
