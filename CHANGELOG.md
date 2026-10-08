# Changelog

## 0.1.0 — unreleased

The first implementation of the full initial-release scope. See `docs/IMPLEMENTATION_STATUS.md` for the validation still pending before family production use.

### Fixed (2026-10-08) — UI alignment and responsive layout (Change Set R)
- **Document preview header.** The title wrapped word by word in a narrow column while the pane had free width (746 px pane, 192 px title at 1920×1080). Badges and the shield were detached, and "file · size · version" broke item by item.
  - Root cause: the shared header row gave the title `flex: 1` (basis 0), so the wrapping row never wrapped and the action buttons took the space.
  - The shared rule now gives growing items a real basis, so actions move to their own row before text is squeezed.
  - The header is a reusable component: title; status badges as one group (antivirus as a labelled badge); file details whose separators never start a line; actions.
- **Responsive by available space.** The preview pane, the full page and the viewer adapt to their own width (CSS container queries), not the window's.
  - Narrow panes show *Share* / *Open full page* as named icon buttons.
  - The viewer toolbar becomes one scrolling row instead of several ragged rows.
- **Three panels from 1280 px.** Below that, an open document uses the full width with *Back to folder* (it was squeezed to 273 px next to the tree on tablets). List and preview share the width equally.
- **Other squeezed layouts found by the new audit:**
  - document list cards (status badges moved under the name; very long names wrap);
  - the tab bar's "No details yet";
  - the Overview date widget;
  - settings rows on tablets (one column when two don't fit);
  - help tables (minimum column width, sideways scrolling on phones).
- **Menus:** the ⋮ menus no longer close when opened right after a page scroll.

### Added (2026-10-08) — Change Set R
- `tests/e2e/layout.mjs`, run by `scripts/e2e.sh` and CI, covers 27 screens at 1920×1080, 1440×900, 1366×768, tablet landscape and portrait, and 430/390 px phones.
  - Checks: horizontal overflow, squeezed text, wrapped button labels, icon/label misalignment, overlapping or off-screen controls, and unnamed icon-only controls.
  - Document header checks with short, long, very long and Arabic synthetic names; menus and dialogs inside the viewport and keyboard reachable; visible focus.
  - Header geometry regression against the reviewed `tests/e2e/layout-baseline.json`.
  - Report in `docs/layout-report.json`; review screenshots are a CI artifact.
- Contributor guide [UI layout rules](docs/guides/ui-layout.md), ADR 0017, before/after images in `docs/images/layout/`.

### Fixed (2026-10-08) — PP-OCRv5 model download failed during upgrade
- `personaldocs upgrade` could report "Some PP-OCRv5 models could not be downloaded: PermissionError: [Errno 13] Permission denied: 'None'". The model libraries ran as the service user inside root's working directory, using download caches outside the model folder. The installer now runs them inside `/var/lib/personaldocs/paddle`, with their own temp and cache folders there, and passes an HTTPS proxy through when one is set. An installer error now also names where it failed, and the full traceback goes to `/var/log/personaldocs/install.log`. Retry with `sudo personaldocs ocr install-models`.

### Added (2026-10-08) — PaddleOCR (PP-OCRv5) and the complete OCR lifecycle (Change Set Q)
- **PaddleOCR with PP-OCRv5** is the default OCR engine (`processing.ocr_engine`); **Tesseract (Legacy)** stays as the fallback (`processing.ocr_engine_fallback`) and as an explicit choice. It runs locally in an isolated environment `/opt/personaldocs/paddle-venv` (PaddlePaddle 3.2.2, PaddleOCR 3.7.0, PaddleX 3.7.2, pinned in `backend/requirements-paddle.txt`) through `apps/library/paddle_worker.py`. The worker runs under the sandbox with a memory limit (`processing.paddle_memory_mb`, 3000 MB), a CPU limit, a timeout and one job at a time. Models live in `/var/lib/personaldocs/paddle` and are never downloaded while recognising.
- **Language profiles** English, Arabic + English, Hindi (Devanagari) + English, Telugu + English, Tamil + English (`processing.ocr_profiles`, `processing.ocr_default_profile`, per document type `ocr_profile`). Advanced settings: model Mobile/Server, CPU threads, document orientation, text-line orientation, unwarping.
- Every OCR result records its **engine, model, profile and date**. PaddleOCR results also store text positions (`ocr_blocks`). Every run is recorded in `OcrRun` (metadata only, never text).
- **Health = real inference**: a self-test recognises a generated image (Settings → OCR & processing → *OCR engines* → **Run self-test**, `sudo personaldocs ocr status|selftest|install-models|reinstall`, `personaldocs doctor`).
- Document **⋮ More actions**: **Run / Re-run OCR…** (engine and profile), **View OCR text**, **Remove OCR data…** (optionally also hiding the embedded text layer and disabling OCR), **Disable / Enable OCR for this document** (keep or remove existing text). API `POST /api/documents/<id>/ocr/mode`.
- Settings → OCR & processing:
  - **Existing OCR data** (main administrator): counts by engine, storage, filters, and **bulk actions** (Remove, Remove and disable, Disable, Enable, Re-process with PP-OCRv5, Set language profile) with a mandatory preview and throttled background batches.
  - **Orphaned OCR data**: Analyze (dry run) and Clean.
  - **Test OCR / Compare engines**: a sanitised file with character accuracy against the expected text; the temporary files are always deleted.

  API: `GET /api/ocr/engines`, `POST /api/ocr/engines/selftest`, `GET /api/ocr/inventory`, `POST /api/ocr/bulk`, `GET|POST /api/ocr/orphans` and `POST /api/ocr/test`.
- Security Health → Storage gains **OCR text**, **OCR cache**, **OCR orphans** and **OCR models**.
- `scripts/ocr_engine_benchmark.py` (PP-OCRv5 vs Tesseract on synthetic English, Arabic, Hindi, Telugu and Tamil samples), results in `docs/OCR_BENCHMARK.md`. Guide [OCR engines](docs/guides/ocr-engines.md); ADR 0016; tests AT-211..AT-230 (the prompt's AT-191..AT-210, renumbered).
- Migration `library.0010_ocr_engines_lifecycle` labels existing OCR as Tesseract (Legacy) or Unknown and maps each type's Tesseract languages to a profile. It never queues OCR.

### Changed (2026-10-08) — Change Set Q
- Changing the default engine affects new runs only; existing OCR is never re-processed automatically.
- A re-run is staged: the new result replaces the old one only after every source succeeded, otherwise the previous text, index and searchable copy stay.
- An engine crash, timeout or memory-limit stop fails once instead of being retried three times.
- *Regenerate preview* and the integrity repair no longer start OCR (`process_version` with `auto_ocr: False`).
- Local AI jobs carry the document's OCR epoch and discard results produced from text that was removed meanwhile.
- The PaddleOCR installer step needs AVX and about 3 GB free disk. `--without-paddleocr` / `PD_NO_PADDLE=1` skips it. The worker unit gains `MemoryHigh=3400M`, `MemoryMax=4000M` and `CPUWeight=50`.

### Fixed (2026-10-08) — removed OCR text came back (Change Set Q)
- *Remove OCR data* reset the search text to the PDF's embedded text layer, so text from a scanner or earlier OCR stayed searchable. It can now be hidden too.
- The Remove button was hidden when no version was marked as recognised.
- *Regenerate preview* and integrity repairs re-ran OCR on *Automatic* types.
- Queued or running Local AI jobs recreated suggestions and semantic chunks after removal.
- Confirmed details kept raw OCR excerpts.
- A page-range re-run left the previous full searchable PDF, which previews and shares still served. Stale searchable copies are now removed.
- Switching a version to current rebuilt the search text without the OCR rules.
- Removal left OCR sources and languages set.
- Run OCR… sent the default engine explicitly, which disabled the Tesseract fallback: without the PaddleOCR runtime (no AVX, `--without-paddleocr`) every run from the dialog failed. The default engine is now left to the server, so fallback applies; an engine the person picks is still never replaced.
- The ⋮ menus closed by themselves when a long menu was scrolled, or when it was opened right after a page scroll (the late scroll event closed it although the menu's button had not moved).

### Fixed (2026-10-08) — ClamAV would not start on Debian 13: unknown option `EnableVersionCommand`
- Earlier releases (Change Set M installer and the Change Set P repair) wrote `EnableVersionCommand true` into `/etc/clamav/clamd.conf`. Only Ubuntu's patched clamd knows that option; Debian 13's clamd 1.4.3 stops with "Unknown option EnableVersionCommand", so the socket `/run/clamav/clamd.ctl` never appeared and the Antivirus page showed Unavailable.
- The repair (`sudo personaldocs antivirus repair`, also run by upgrade/post-upgrade/repair and the Diagnose / Repair button) now removes it, and removes any other option `clamconf` reports as unknown. The diagnosis reports an unsupported option as the cause. The app reads engine and signature versions without it.

### Added (2026-10-07) — passkey sign-in on the first screen, administrator password reset, security templates, ClamAV repair (Change Set P)
- **Sign in with Passkey** on the first sign-in screen (password, "or", Sign in with Passkey, then authentik/Google when enabled), passkey autofill in the username field (WebAuthn conditional mediation, `autocomplete="username webauthn"`), greyed out with "Passkeys need the secure HTTPS address of this app" on plain http.
- **Passkey sign-in mode** (`auth.passkey_mode`): *Passwordless* (default) or *Password + Passkey*; passwordless sign-in uses a discoverable credential with user verification required and a single-use challenge. Enrolling a discoverable passkey in passwordless mode turns passwordless on for that account (opt-out under Passkeys).
- Sign-in with an **email address** instead of the username when it belongs to exactly one active account.
- **Administrator password reset** (Settings → Family & access, or Settings → Users for the Administrator role → **Reset password…**, recent confirmation required): **Generate temporary password** (16 characters, shown once with Copy, hash only, never emailed, forced change, all sessions end, older reset links invalidated) or **Send password reset email** (branded HTML + plain text, single-use link valid `auth.reset_token_minutes`). Main Administrator protection; audited as `family.password_reset_by_admin` / `family.password_reset_email`. API `POST /api/family/members/<id>/reset-password`.
- Security events (critical by default): *Password reset requested*, *Administrator reset your password*, *Temporary password issued*, *Password reset completed*, *Account locked* (person and administrators, once per lock window) and *Google account linked or removed*.
- **Mandatory security text** on every security event, always shown in email (red box, `IMPORTANT:` lines), Telegram (bold ⚠️) and in-app (red note) and locked in the Template Manager; templates gain **Branding name** and **Footer / help text**.
- **ClamAV diagnosis and repair** (`backend/apps/ops/clamav_check.py`, standard library only, shared by the CLI, the root host helper and the web app): packages, signatures, daemon and socket units (including a skipped start condition and out-of-memory kills), restart policy, effective socket path versus `LocalSocket`, no TCP listener, `/run/clamav`, socket file, stale pid, service-account access, version, clean + EICAR self-test, memory and journal hints, with a likely cause and fixes.
- `sudo personaldocs antivirus status|repair|selftest`; `manage antivirus status|selftest|sync-socket PATH`; host-helper action `antivirus_repair`.
- Antivirus page: status **Healthy / Degraded / Unavailable / Error / Turned off**, Socket and Self-test rows, **Run self-test** and **Diagnose / Repair** with **Repair antivirus**. API `GET /api/security/antivirus/diagnose`, `POST /api/security/antivirus/selftest`, `POST /api/security/antivirus/repair`.
- Migrations `accounts.0007_passkey_mode` and `notify.0003_template_brand_footer`; guide password reset; ADR 0015; new screenshots `login-passkey.png`, `admin-reset-password.png`, `security-antivirus-diagnose.png` (synthetic data).

### Changed (2026-10-07) — Change Set P
- `auth.passkey_mode` replaces `auth.allow_passwordless`; the upgrade keeps an explicit earlier choice (saved off → Password + Passkey) and otherwise makes passwordless the default, turning it on for accounts that already have a discoverable passkey.
- Administrators (the Administrator role) can reset the passwords of accounts that are not main administrators; a temporary-password reset always ends every session of that person.
- The self-service **Forgot password?** email is now the branded HTML + plain-text message; reset links are never stored in the notification outbox, in-app history, Telegram, push or logs.
- `account.login` is now *New sign-in*, `security.new_country` *Unusual sign-in (new country)*, `security.authentik` *authentik account linked or removed*.
- `personaldocs install`, `upgrade` (through `post-upgrade`), `post-upgrade` and `repair` run the ClamAV repair and a real self-test instead of assuming that installed packages mean antivirus works; `antivirus.socket` is synced to the effective socket. `personaldocs doctor` starts with the root ClamAV diagnosis and adds *ClamAV socket used by the app*, *ClamAV scanner operational (reachable and scans)* and *ClamAV self-test*.
- Antivirus health comes from a live scan: Unavailable and Error give 0 Security Health points and force At Risk; the hourly check runs the self-test daily and after a failure; cached engine versions are shown as "last seen … not proof that scanning works".

### Fixed (2026-10-07) — Change Set P
- Passkeys were only offered after the password because passwordless sign-in was off by default and also needed a per-person opt-in, so the passkey button stayed hidden.
- ClamAV "Unavailable … /run/clamav/clamd.ctl (FileNotFoundError)" after upgrades: the installer kept Debian's `LocalSocket /var/run/clamav/clamd.ctl`, which differs as a string from the systemd socket unit's `/run/clamav/clamd.ctl`, so clamd did not adopt the systemd socket and removed its own socket file on stop/restart; units skipped by their start condition when signatures were missing were never started later; a clamd killed for lack of memory was not restarted. The repair sets `LocalSocket` to the socket unit path and installs a restart drop-in (`Restart=on-failure`) and a tmpfiles entry for `/run/clamav`. Verified on a simulated Debian 13 host and against a real clamd; not yet on a real Debian 13 Proxmox LXC.
- The Antivirus page showed an engine version and signature date while ClamAV was unreachable, suggesting scanning worked.

### Added (2026-10-07) — rich notification formatting, icons, templates and interactive actions (Change Set O)
- **One structured message per notification** (event, severity Critical/Warning/Success/Information, category, icon, title, heading, summary, details with icons, actions, guidance) rendered for in-app, email, Telegram and push, with a central icon list (SVG with accessible labels in the app, emoji in email and Telegram) and severity always shown as text.
- **Rich email**: responsive HTML part (header, severity and category badges, headline, summary, details table, buttons, guidance, footer; table layout, inline styles, no JavaScript, no images or tracking pixels, `dir="auto"`) plus the plain-text part.
- **Rich Telegram**: HTML formatting with an emoji per detail and inline buttons on an `https://` address; plain-text fallback.
- **Web Push** as a fourth channel: turned on per device in My account → Notifications (*Turn on for this device*, *Send test push*, device list with *Remove*), lock-screen detail Minimal / Standard / Detailed (`me.push_preview`), encrypted payloads signed with VAPID keys stored encrypted, only known push services (Apple, Google, Mozilla, Microsoft) over HTTPS, expired subscriptions removed; new Python dependencies `http-ece` 1.2.1 and `py-vapid` 1.9.4.
- **Notification Center** (`/notifications`): cards with icon, severity, category, summary, time, unread dot, actions and *Show details*; Mark read / unread, Mark all read, filters All/Unread, category and severity, *Load more*. **Banners** for new warning, critical and success notifications.
- **Event-specific actions** (Open Document, Go to Folder, View Expiry Reminders, Snooze 7 days, Review Activity, Manage Sessions, Change Password, View Security Event, Security Health, View System Status, Open Storage Health, Run Cleanup Analysis, View Import Report …); application paths only, no tokens, never a quarantine release.
- **Template Manager** (Settings → Notifications → Templates, main administrator): title/subject, heading, summary with allowlisted placeholders, icon, severity shown and action labels per event and channel; live previews (email desktop and mobile, Telegram, in-app, push, plain text); Reset to default; **Send a TEST message to yourself**; audited.
- **Delivery history** with queued / retrying / sent / failed / skipped, attempts, "accepted by the provider", redacted errors, filters and TEST rows.
- New events *authentik account linked/unlinked* (critical by default) and *documents moved, restored, re-typed or confirmed by someone else* (optional, in-app).
- Expiry reminders use the document type and confirmed details (name, expiry date, days left, folder), with severity by days left; optional masked document number.
- Settings `notifications.include_document_number` (off), `notifications.push_enabled` (on), `notifications.repeat_cooldown_hours` (24), `me.push_preview` (standard).
- API: `/api/notifications` (list, `read`, `<id>/action`, `push`, `push/test`, `templates`, `templates/<event>`, `/preview`, `/test`, `deliveries`).
- Migration `notify.0002_rich_notifications`; guide notifications; ADR 0014; new screenshots (synthetic data).

### Changed (2026-10-07) — Change Set O
- Email is now multipart (HTML and plain text) instead of plain text only.
- Telegram messages are now HTML-formatted with buttons instead of the same plain text as email.
- The in-app notification list is replaced by the Notification Center with cards, details, actions, filters and banners.
- Severity, category and icon come from the event catalogue instead of hard-coded strings at each call site; security and system events use the policy severity (antivirus events critical and for administrators only, OS update results, reboot requests, security test findings, storage warnings).
- Recurring conditions (antivirus unavailable, stale or failed signature updates, storage warnings) are repeated to the same person only after the repeat cooldown; new critical events are still sent at once.
- Existing SMTP/Telegram configuration, preferences, critical events and channels and expiry schedules are kept; push is never added to anyone's channels automatically.

### Fixed (2026-10-07) — Change Set O
- The in-app feed showed only a title with a generic icon, so severity and the affected document or device were not visible without opening the linked page.
- Recurring conditions could notify the same person again every day when the daily key changed.

### Added (2026-10-07) — document types, metadata templates, field sources and type assignment (Change Set N)
- **Document types as editable data** (Settings → Documents & folders → Document types, main administrator): list with document counts; add from a standard template (passport, visa, residence permit / iqama, national ID, driving licence, employee ID, insurance, certificate, generic) or a copy of another type; edit name, icon, description, expiry awareness and **per-type reminder days**; archive/restore; delete only when unused or after moving its documents to another type.
- **Metadata templates** per type: fields with stable key, label, field type (text, long text, date, number, yes/no, select, country, person, identifier), shown, required, order (↑/↓, keyboard accessible), help text, *OCR / Local AI may suggest*, searchable, role (expiry, issue, no expiry), choices and validation (pattern, min, max, max length), with a preview of the Details panel.
- **Details panel**: Owner, Document type with **Set type** / **Change…** (read-only for viewers, *Not assigned* when empty, **Manage** for the main administrator), a details status (*Details confirmed*, *Incomplete: …*, *Needs review: …*) with **Confirm as incomplete**, the template fields, **Additional details** and **Previous details — needs review**.
- **Value provenance**: *Suggested* / *Edited* badges and source chips (Manual, OCR, OCR (MRZ), Local AI, Imported, System, Migrated) with who and when confirmed.
- **Type suggestions** from the folder, from OCR text (MRZ or wording, with reason and confidence) and from the local AI, with Accept… / Change… / Ignore; conflicts shown, never decided automatically.
- **Safe type change** with a preview (kept values, previous details with reason, additional details, new empty fields, expiry warning); previous details can be mapped, kept or removed; **Re-map existing OCR data** without a new OCR scan.
- **Additional details** (*New detail for this document…*) and promotion to the template (**Add to … template…**, main administrator).
- Type assignment in the upload dialog, the Details panel, the document ⋮ menu / More actions and **bulk Set type…** (preview, confirmed types protected unless explicitly overridden); folder ⋮ **Suggested document type…**; **Review untyped documents** for the main administrator.
- OCR review queue filter by document type; searchable template fields indexed (identifiers not by default).
- API: `/api/documents/<id>/type`, `/api/documents/<id>/remap-ocr`, `/api/documents/bulk-type`, `/api/document-types` (`/admin`, `/<id>`, `/<id>/fields`, `/review`); `PATCH /api/folders/<id>` accepts `suggested_type`.
- `personaldocs manage document_types report`; `personaldocs doctor` prints typed / untyped / suggested counts.
- Migration `library.0009_document_type_templates`; guide document types; ADR 0013; new screenshots (synthetic data).

### Changed (2026-10-07) — Change Set N
- Detail rows come from the document type's template instead of a fixed frontend label list; OCR and the local AI propose only template fields marked extractable for typed documents.
- Only the confirmed value of the template field with the expiry role drives the expiry date and reminders; a type's reminder days override the global schedule; a type change re-derives the expiry date.
- Folder and document type are explicitly independent: moving never changes the type, changing the type never moves the file.
- On upgrade every type gets a template, typed documents keep their type (confirmed, source *Migrated*), untyped documents stay untyped, and values outside a template become additional details. Nothing is deleted.
- Settings → OCR & processing → *OCR by document type* stays in sync with the templates' OCR/AI flags.

### Fixed (2026-10-07) — Change Set N
- The Details panel showed **Type** as a hard-coded read-only row ("—" when unset), changeable only through the hidden "Rename / edit details…" dialog, so documents with OCR details appeared untyped with no visible way to set the type.
- The bulk `set_type` action could overwrite confirmed types; it now follows the same safe rules as a single change.
- The older `DELETE /api/metadata/type/<id>` endpoint could hard-delete a type in use and silently untype its documents; deleting a type in use is now refused.

### Added (2026-10-07) — antivirus, authentik, security center, storage health (Change Set M)
- **ClamAV antivirus:** every new file is scanned in the background through the local clamd socket `/run/clamav/clamd.ctl` (no TCP port); statuses Scan pending, Clean, Not scanned, Not scanned — size limit exceeded, Scan failed, Threat detected, Quarantined and Released from quarantine; fail-open when ClamAV is down.
- Quarantine in `<data>/quarantine`: preview, download, sharing, export, OCR and Local AI blocked; only the main administrator can release (warning, confirmation, reason, audited) or delete (type DELETE). Quarantined files are excluded from backups and from integrity "missing" reports.
- Maximum scan size (default 50 MB), **Scan entire existing library** with progress, pause, resume and cancel, optional daily/weekly/monthly re-scan, automatic freshclam updates and **Update now**, stale (2 days) and critically stale (7 days) signatures; critical administrator notifications for threats, releases, scanner problems and stale or failed signature updates.
- **authentik** sign-in (Settings → Authentication → External identity providers): OpenID Connect with PKCE, state and nonce, HTTPS issuers only, encrypted client secret, button label and logo, connection test. Links made only by the person (My account → Password & security → Link authentik account), never by email; revocable by the main administrator. Provisioning "existing accounts only" by default, optional automatic member accounts, optional group → role mapping (Member or Administrator), all audited. Local sign-in always stays available.
- **Administrator** role (Settings → Family & access → Edit): access to Settings → Security and administrator security notifications, without any document or folder access.
- **Security center** (Settings → Security): Overview, Antivirus, Security test, OS updates, Firewall, Security records, Storage and Access policy. Deployment exposure (LAN only / Internet) and **Internet Ready** HTTPS checks; HSTS for https origins (`PD_HSTS_SECONDS`, default one year).
- **Basic Internet Security Test**, started manually only: baseline checks of this application and this host, Passed/Warning/Failed with severities and fixes, comparison with the previous run, one year of history; Critical and High findings warn but never block. Optional `pip-audit` with `--with-security-tools`.
- **OS security updates** through a root host helper (`personaldocs-host.path`, `personaldocs host-apply`, fixed actions only): list and install Debian security updates after a local database and settings backup (`<data>/pre-update-backups`, newest 3), logs, *Reboot required*, and a controlled **Reboot server** with preflight warnings and service health afterwards. No unattended updates.
- **Firewall monitoring** (ufw/nftables state, listening services, unexpected exposure); no controls change rules.
- **Security Health** score (0–100, Healthy / Attention / At Risk, forcing conditions) for administrators on the Overview and in the security center.
- **Security records** retention (default 365 days, nightly cleanup) and a manual purge with cleanup analysis; **Storage Health** with categories, 80 % / 90 % thresholds and a safe cleanup. Original documents are never deleted by any of these workflows.
- Installer: `clamav`, `clamav-daemon` and `clamav-freshclam` with a local-socket-only configuration (`--without-antivirus` to skip; about 1.2 GB of memory), the host helper, and `--with-security-tools`. `personaldocs status` and `doctor` report ClamAV, freshclam, the host helper, signature age, files pending scan, Internet HTTPS, storage thresholds and a pending reboot.
- Migrations `accounts.0005_administrator_role`, `accounts.0006_external_identity`, `library.0008_antivirus`, `security.0002_antivirus`, `security.0003_security_center`; guides antivirus, authentik and security center; ADR 0012.

### Changed (2026-10-07) — Change Set M
- `personaldocs post-upgrade` runs the setup steps a new release adds (ClamAV, host helper units, optional security tools); `personaldocs upgrade` and `personal-DM.sh -- upgrade` call it, so the new components are installed during upgrades.
- Settings → Security reorganised into the security center; the country/IP access policy, GeoIP, alerts and traffic analytics moved to **Settings → Security → Access policy** (main administrator only). Values are unchanged.
- Files stored before this release are marked *Not scanned* until **Scan entire existing library** runs.
- HTTPS installations now send `Strict-Transport-Security` (one year; `PD_HSTS_SECONDS=0` turns it off).

### Fixed (2026-10-07) — Change Set M
- The "administrators" two-step verification policy now also covers accounts with the Administrator role.

### Added (2026-10-06) — selective OCR, Overview, sign-in designs, admin-only setup (Change Sets K and L)
- Selective OCR: a policy per document type (Disabled, Manual, Automatic) with default languages, expected fields and whether the local AI may read the text; custom types can be added and archived (built-in and in-use types are never deleted).
- **Run OCR…** with chosen source files (front and back via **⋮ → Add another side or copy…** as one job), pages and ranges (`1-2, 5`) and languages; English, Arabic and Hindi offered by default; missing Tesseract packs reported by `personaldocs doctor` and installed by install, upgrade and repair.
- OCR states (Not processed, Queued, Processing, Needs review, Confirmed, Failed, OCR removed), Cancel, **Mark reviewed**, **Remove OCR data…** (original and confirmed details kept), the **OCR review** page, and limits for file size, pages, queue length and attempts, plus **Pause OCR queue**.
- Overview: Today (Gregorian and Hijri, Umm al-Qura, installation timezone, ±2 day adjustment), Weather (Open-Meteo through the server with a shared cache, off by default, city per person), Documents summary, Month calendar, Upcoming holidays (bundled `holidays` library; Saudi Arabia and India by default; provisional moon-dependent dates; administrator corrections), Shared with me and Recent activity.
- **Customize Overview**: add, remove, reorder, resize on a responsive grid, rectangular or circular styles, widget settings, reset; saved per account on every device.
- Sign-in page designs: Minimal (default), Nature, Travel, Family and Neutral; custom wallpaper (re-encoded, metadata removed, backed up), position, overlay, title, tagline and logo in **Settings → Overview & sign-in**.
- Setup: an optional **Add family members** step after the Main Administrator, with generated temporary passwords.
- Search filter `shared=1`; new dependencies `holidays`, `hijridate`, `python-dateutil` and `six`; migrations `library.0006`, `library.0007` and `core.0003`; ADR 0011.

### Changed (2026-10-06) — Change Sets K and L
- Setup creates only the Main Administrator; it no longer creates default family accounts. Upgraded installations keep every existing account, and deactivating a member never deletes their documents.
- New installations recognise text only on request (Manual OCR); upgraded installations keep automatic OCR with AI allowed per type.
- The dashboard is now the **Overview**, with a new default widget set for new accounts; accounts that had chosen widgets keep their choice. Settings → My account → Appearance → *Dashboard widgets* is now *Overview widgets*.

### Fixed (2026-10-06) — Change Sets K and L
- The OCR contrast stretch clipped sparse ink and could erase text on mostly blank scans (regression sample added; benchmark mean F1 stays 0.61 → 0.97).
- Calendar accessibility roles on the Overview month calendar.

### Added (2026-10-05) — browsing, OCR quality, one-line installer (Change Set J)
- ⋮ menus that open on top of every panel and stay on screen (keyboard, Escape, outside click), with Rename, Share, Archive and (administrator) Delete permanently for documents, and Rename, Change icon, Share and Archive for folders.
- Folder icons: sub-folders default to 📁; icons chosen from a list with **Reset to default**; chosen icons survive moves and upgrades.
- List, Thumbnails and Details views with sorting, saved per account and synchronised across devices.
- Drag files and whole folders from the desktop: the folder structure is recreated below the drop target, with a progress card and a per-file report.
- Your own library is listed first and opened; other areas stay closed.
- OCR: measured preprocessing (orientation, deskew, contrast, upscale, denoise), confidence per document with unreliable lines greyed out, **Re-run OCR** with a chosen rotation, card layouts ("Badge No | Expiry Date") and "No Expiry Date" understood; mean accuracy on the synthetic benchmark 0.61 → 0.97 (`docs/OCR_BENCHMARK.md`).
- Public title "Personal Documents Management System"; one-line installer `personal-DM.sh`; LinkedIn-ready README; Ko-fi support link.

### Fixed (2026-10-05) — Change Set J
- Folder and row menus were clipped by the breadcrumb bar and scrolling panels.
- Sub-folders got name-based emoji (e.g. 🏠 deep inside a folder) instead of a folder icon.
- Phone photos stored sideways and upside-down scans produced junk OCR text; "12-31-2030" (month first) was not recognised; "Badge No  Expiry Date" header/value layouts were not read.

### Added (2026-10-05) — UI, import, notifications, backups, mobile, viewer, public release
- "My Documents — <name>" with avatar at the top of the folder tree; avatars for every member's area.
- File-type icons (PDF, JPG, PNG, WEBP, TXT, DOC, XLS, PPT, ZIP, DCM, FILE) from validated content.
- Drag and drop of documents and folders, and **Move to…** with a folder picker on every device.
- Built-in viewer (PDF.js, local): zoom 25–400 %, fit page, fit width, 100 %, pages, full screen, keyboard shortcuts.
- Import: choose a destination sub-folder (or any permitted folder), keep the top folder or not, and preview the exact final hierarchy (new/existing).
- Dashboard widgets chosen with checkboxes and ordered by drag or ↑/↓; synced per account.
- Critical notifications (administrator-chosen, cannot be turned off, missing destinations flagged) and optional notifications per event and channel; one detailed template; bulk summaries; archive vs permanent deletion messages; optional "every sign-in" information.
- Backups daily, weekly or monthly with next-run status and catch-up.
- `docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md`, `SECURITY.md`, `CONTRIBUTING.md`, public README with screenshots; `scripts/privacy_check.sh`; frontend unit tests; tablet/phone parity checks.

### Fixed (2026-10-05)
- Members could not move their own documents between their own folders (now allowed when nobody gains access).
- Two opposite folder moves at the same time could detach folders; moves into archived folders were possible; a refused move could still apply a rename sent with it.
- Dropping a file outside an upload area opened it in the browser and left the app.
- Malformed list filters (`folder=undefined`) caused a server error.
- Horizontal scrolling on family settings and help at tablet widths.
- Security: `?next=` after sign-in only accepts in-app paths; PDF.js 6.4.299 (GHSA-hq66-cqwq-w95j) and React Router 7.18 (GHSA-wrjc-x8rr-h8h6).

### Added (2026-10-05) — profile photos, Local AI, security & access, passkeys
- Profile photos with crop/zoom, shown in the header, family list, permissions and document history.
- Optional Local AI (off by default): AI profiles for OpenAI-compatible servers (LM Studio, llama.cpp, vLLM) and Ollama, privacy classes (local/LAN/external) checked before every request, OCR assist and smart organisation as reviewable suggestions, document assistant with citations, semantic search, AI job list. Permission-filtered retrieval; no cloud fallback.
- Login audit (method, real IP, country, browser/OS/device, new-IP/new-country/temporary-access flags) with filters and retention.
- Real client IP through trusted proxies only (`PD_TRUSTED_PROXY_IPS`), with a "Your connection" diagnostic.
- Local GeoIP (MaxMind download with validation and atomic install, or `.mmdb` upload), weekly updates.
- Country access policy (off / block list / allow list, unknown-location action), temporary travel access, trusted and blocked IPs with expiry, documented precedence, lock-out confirmation, undo, and `personaldocs access-policy` console recovery (`PD_ACCESS_POLICY_DISABLED=1` emergency switch).
- Security alerts (failed-sign-in escalation with automatic blocks, new country/IP, temporary access, policy changes, GeoIP/GoAccess problems, account security changes), throttled and secret-free.
- Traffic analytics: privacy-safe access log, hourly GoAccess (or built-in) report, blocked-request statistics.
- Passkeys (WebAuthn) as a second step and optional passwordless sign-in; authentication policy (allow TOTP/passkeys/passwordless, require two-step verification for none/admins/everyone without lock-out), recent-auth window for sensitive changes, admin "Reset 2FA" and `recover-admin --reset-2fa`.
- TOTP fields work with password-manager autofill (`autocomplete="one-time-code"`).
- Installer/upgrade: GoAccess package, access-log rotation, new migrations; `doctor` checks proxy trust, GeoIP, passkey origin and AI profiles; backups include profile photos.

### Added (2026-10-04)
- Resizable folder-tree and document-list panels (mouse and keyboard), remembered per account.
- Active sessions list with sign-out of individual devices.
- Optional folder templates for new members (setup wizard, add member, apply to any folder).
- Notifications for access granted, finished imports, processing failures, failed backups and integrity problems, with a per-user switch for external channels.
- PDF/A-2b validation of searchable copies (veraPDF when installed via `--with-verapdf`, structural check otherwise) and `manage.py pdfa_check`.
- Automated accessibility audit (axe-core) and a CI end-to-end job.

- Connect the NAS backup share (NFS or SMB) from Settings → Storage & backup, with status, Disconnect and actionable errors (`personaldocs nas-apply`).
- Guided installers: `scripts/proxmox-create-lxc.sh` (creates the Debian 13 container on Proxmox) and `scripts/easy-install.sh` (asks every parameter and installs, configures, connects the NAS, backs up and checks), with `--dry-run`.
- `manage.py apply_settings FILE` to apply validated settings from a file.

### Fixed (2026-10-04)
- Duplicate notification keys could abort an enclosing database transaction.
- Changing your own password signed out the device you were using.

### Added
- First-run setup wizard (one-time console code) creating the family accounts (since Change Set L: only the Main Administrator, with optional members); extended-family groups, heads and scoped delegation.
- Default-deny capability permissions with folder inheritance, document exceptions and access explanations.
- Folder library with emoji suggestions, immutable checksummed originals, versions, renewals and archive/restore/purge.
- Local OCR (Tesseract/OCRmyPDF, searchable PDF/A), LibreOffice previews, thumbnails, DICOM-safe storage.
- Proposed detail extraction (labels and passport MRZ with check digits) with discrepancy flags and confirmation, plus copy buttons.
- Full-text search with highlights, autocomplete, saved views and non-AI similarity.
- Browser and server/NAS folder import wizard with explicit mapping, resumable and idempotent.
- Expiry reminders (90/60/30/7/0) over in-app, SMTP and Telegram with an idempotent outbox; verified Telegram linking.
- Public share links (expiring, password, pinned version, rate-limited); native device sharing.
- Installable PWA, camera upload, Web Share Target, opt-in per-account offline copies, streaming ZIP exports.
- Password sign-in, optional TOTP with recovery codes, Google account linking (OIDC + PKCE), console admin recovery.
- Per-user IMAP email import rules.
- Application backups to a NAS with verification and retention; console restore; integrity checker; audit log; health page.
- `personaldocs` CLI for install/upgrade/rollback/repair on Debian 13; systemd units; CI; bundled help; three themes.
