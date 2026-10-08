# Implementation status

Last updated: 2026-10-07 · Version 0.1.0 (pre-release)

## Summary

Every internal build stage (1–8) is implemented, plus change set 2026-10 (profile photos, optional Local AI, login audit, real client IP, GeoIP, country/IP access policy, security alerts, traffic analytics, passkeys and authentication policy) change sets H/I (UI, import destinations, critical/optional notifications, backup schedules, drag and drop and Move to, full-page viewer, mobile/PWA parity, public-release readiness) and change set J (portal overflow menus with rename/archive/permanent delete, folder icons, List/Thumbnails/Details views with sorting, desktop file-and-folder drop with hierarchy, own library first, measured OCR preprocessing with confidence and re-run, "No expiry", the public title, the one-line installer `personal-DM.sh` and a LinkedIn-ready README), change set K (selective multilingual OCR with a policy per document type, source/page/language selection, OCR review queue and Remove OCR data; the customizable Overview with Today/Hijri, weather, month calendar and holidays; sign-in page designs and custom wallpaper) change set L (setup creates only the Main Administrator, optional family members) and change set M (ClamAV antivirus with quarantine, authentik sign-in, the Administrator role, the security center with Internet Ready, the Basic Internet Security Test, OS security updates and controlled reboot through a root host helper, firewall monitoring, the Security Health score, security record retention and Storage Health) and change set N (document types as editable data with metadata templates, value provenance, type suggestions, safe type changes with previous details, re-mapping of existing OCR data, one-off details and promotion, bulk classification, folder suggested types and the review of untyped documents) and change set O (rich notifications: one structured message rendered for in-app, HTML email with a plain-text part, Telegram with buttons and Web Push; the Notification Center with banners; event-specific actions; the Template Manager with previews and TEST sends; delivery history; noise control) and change set P (Sign in with Passkey on the first sign-in screen with passkey autofill and the Passwordless / Password + Passkey mode; administrator password reset with a one-time temporary password or a branded reset email and Main Administrator protection; security notification templates with mandatory security text, branding and footer; ClamAV diagnosis, repair and self-test with operational health states): data model, settings registry, setup, accounts, permissions, delegation, authentication (password, TOTP, Google linking, console recovery), storage, versions, renewals, archive, imports, OCR/previews/extraction, search, UI/PWA/themes, offline/export, reminders over four channels (in-app, email, Telegram, Web Push), sharing, IMAP import, audit, backup/restore/integrity, native operations tooling, CI and documentation.

**Release readiness: not yet approved for family production use.** The code and its automated tests are complete for the initial scope. The remaining release gates need environments that were not available in the build container (see Blockers). Per the release rules, the first family release should wait until AT-26 (Debian 13 install/upgrade) and AT-24 (restore on a clean LXC) have been validated on the real Proxmox host.

**Acceptance scenarios AT-01…AT-210** (200 scenarios; the numbers AT-51…AT-60 were never assigned). The status of
each one is in [TRACEABILITY.md](TRACEABILITY.md). Summary, based on the latest recorded runs in
[TEST_REPORT.md](TEST_REPORT.md):

| Result | Count | Scenarios |
|---|---|---|
| Passed (automated tests, or for AT-136 a documented review) | 154 | all scenarios not listed below |
| Passed in automated tests; real-environment validation still pending | 40 | AT-17, 19, 21, 31, 39, 40, 69, 71, 76, 83, 90, 91, 98, 99, 111, 122, 125, 130, 134, 140, 142, 146, 147, 148, 149, 153, 154, 155, 174, 175, 177, 178, 181, 194, 195, 197, 202, 205, 206, 208 |
| Blocked (external environment) | 5 | AT-14, AT-26 (Pending-env); AT-24, AT-27, AT-30 (Partial: the remaining part needs a real Debian 13 LXC) |
| Not run (manual steps, not automated) | 1 | AT-15 |

The pending real-environment parts (real hardware, real providers or credentials) are listed under Blockers below and
are not reported as passed. AT-194 is counted from the parity steps of the browser suite: **59 PASS, 0 FAIL**
(Change Set O run). Browser suite after Change Set P: **62 PASS, 0 FAIL** (no serious or critical accessibility violations)

## Completed (with evidence)

- Change set P (2026-10-07): `tests/test_auth_password_clamav.py` (18 tests, AT-196…AT-210): all passed, including a
  simulated Debian 13 host (fake `systemctl`, `dpkg`, `clamconf`, `freshclam`, `runuser` and a fake clamd) that
  reproduces the missing-socket / LocalSocket-mismatch state and the skipped-start-condition state and checks the
  repair. `tests/test_antivirus_live.py::test_live_self_test_diagnosis_and_health` passed against a **real clamd
  (ClamAV 1.5.4)** in the development container (clean = Clean, EICAR detected, temporary files removed, no document
  stored); the diagnosis tool was also run against that daemon stopped (Unavailable, `FileNotFoundError` reported) and
  running (self-test PASSED). Earlier tests updated: passkey policy, the password reset email (now HTML) and the
  account-locked alert. Full backend suite: **350 passed** (fresh test database, including the live ClamAV tests).
  `scripts/e2e.sh` with the new steps *AT-196 Sign in with Passkey on the first sign-in screen*, *AT-200/201
  administrator resets a password: temporary password shown once* and *AT-205..207 antivirus: Diagnose / Repair panel
  and clean + EICAR self-test*: **62 PASS, 0 FAIL** (no serious or critical accessibility violations). Not run: a real Debian 13 / Proxmox LXC upgrade and repair,
  reboot persistence on a real host, real passkey platforms and real SMTP delivery. Details:
  [Change set P](#change-set-p).

- Change set O (2026-10-07): `tests/test_rich_notifications.py` (19 tests, AT-176…AT-193 and AT-195): all passed.
  The affected earlier suites (expiry, events, notification policy, security, antivirus, passkeys, auth, security
  center, document types, authentik): 125 passed after the change. Full backend suite: **331 passed** (330 in the full run plus the live ClamAV test re-run once the local daemon was started).
  `scripts/e2e.sh`: **59 PASS, 0 FAIL**, with the new desktop step *AT-176..186 rich notifications: TEST messages,
  Notification Center, banners, template manager* and `AT-194 <viewport>: Notification Center cards, filters and
  actions by touch without clipping` for tablet, mobile-portrait and mobile-landscape; `/notifications` and
  `/settings/notifications` are in the overflow route list and the accessibility audit. Not run: real mail clients,
  a real Telegram bot, real Web Push services and devices, an installed PWA on real devices and an upgrade of a real
  Debian 13 installation. Details: [Change set O](#change-set-o).

- Change set N (2026-10-07): `tests/test_document_types.py` (16 tests, AT-161…AT-174): all passed. Full backend
  suite: **312 passed**. `scripts/e2e.sh`: **55 PASS, 0 FAIL**, adding the desktop step *AT-161..175 document
  types: set from Details, suggestion, safe change, custom detail, templates* and `AT-175 <viewport>: Details, type selection and previous values work by touch without clipping`
  for tablet, mobile-portrait and mobile-landscape;
  the accessibility audit now includes `/settings/documents` (no serious or critical violations). In one earlier run
  with the local ClamAV daemon stopped, two desktop drag/move parity steps failed; they passed in the full rerun with
  the daemon running. Not run: the installed PWA on real iOS/Android devices and an upgrade of a real Debian 13 /
  Proxmox installation with production data. Details: [Change set N](#change-set-n).

- Change set M (2026-10-07): new backend tests `tests/test_antivirus.py` (9, fake clamd with the EICAR test string,
  AT-138…AT-145, AT-160), `tests/test_antivirus_live.py` (1, executed against a **real ClamAV 1.5.4 daemon** in the
  development container: EICAR detected and quarantined, a clean file reported clean; skipped where no clamd runs),
  `tests/test_authentik.py` (5, fake OIDC provider with real RS256 tokens and PKCE, AT-146…AT-148) and
  `tests/test_security_center.py` (17, AT-149…AT-160 with stubbed HTTPS responses and host commands): all passed.
  Full backend suite: **296 passed** tests. `scripts/e2e.sh`: **51 PASS, 0 FAIL**, adding antivirus quarantine and
  release with EICAR, the security center overview, security test, storage, OS updates, firewall and records views,
  and the authentik settings and sign-in button; the accessibility audit includes the security views.

- Change sets K and L (2026-10-06): new backend tests `tests/test_selective_ocr.py` (11, AT-101…AT-115),
  `tests/test_overview.py` (15, AT-116…AT-130 backend parts, including a fake local weather server) and
  `tests/test_family_setup.py` (AT-131…AT-135, AT-137); the full backend suite passes (for the current count see the
  `scripts/verify.sh` output). `scripts/e2e.sh`: 48 PASS, 0 FAIL, covering the setup wizard (administrator plus
  optional members), manual OCR on a passport, selective OCR and the review queue, Overview customize / weather (fake
  local provider) / calendar / holidays, holiday countries and corrections, all five sign-in designs at desktop and
  phone, and the accessibility audit (now also `/ocr-review` and `/settings/overview`) with 0 blocking violations in
  3 themes. OCR contrast fix with a sparse-ink regression sample; benchmark mean F1 0.61 → 0.97 (12 samples).
- Backend: 232 automated tests passing (incl. `test_security` 30, `test_ai` 15, `test_passkeys` 14, `test_photos` 9, `test_browser_moves` 11, `test_browsing_v3` 7, `test_ocr_quality` 6, `test_notification_policy` 7, `test_backup_schedule` 3, `test_preferences` 3). Frontend: 17 unit tests (vitest). One-line installer: 18 stubbed lifecycle checks. OCR benchmark: mean F1 0.61 → 0.97. (`docs/TEST_REPORT.md`).
- Frontend: type-checked production build; browser end-to-end flow (`tests/e2e/flow.mjs`) and parity/viewer/browsing checks (`tests/e2e/parity.mjs`; 48 PASS, 0 FAIL in `scripts/e2e.sh` on 2026-10-06; 31/31 at change set J) at desktop, tablet, phone portrait and landscape; accessibility audit with 0 serious/critical violations in 3 themes; README screenshots in `docs/images/screenshots/`.
- Tooling: one-line installer `personal-DM.sh` (menu + commands, delegates to the tools below); guided installers `scripts/proxmox-create-lxc.sh` (Proxmox host: creates the container) and `scripts/easy-install.sh` (inside the LXC: asks all parameters and installs, configures, connects the NAS, backs up and checks); `scripts/personaldocs` (install, upgrade, rollback, repair, status, doctor, backup, restore, integrity, recover-admin, setup-token, logs, manage, nas-apply), systemd units, `scripts/verify.sh`, GitHub Actions CI with prebuilt frontend release asset.
- New migrations: `security.0001_initial`, `ai.0001_initial`, `accounts.0003_profile_photo`, `accounts.0004_passkeys`, `library.0004_ocr_quality_no_expiry`, `library.0005_subfolder_default_icon` (data: automatic sub-folder icons → 📁), `core.0002_public_title` (data: old default name → new title), `library.0006_selective_ocr`, `library.0007_selective_ocr_defaults` (data: existing installations keep automatic OCR with AI allowed; new installations Manual), `core.0003_overview` (weather cache, holiday corrections), `accounts.0005_administrator_role`, `accounts.0006_external_identity` (authentik links), `library.0008_antivirus` (data: existing files marked Not scanned), `security.0002_antivirus`, `security.0003_security_center`, `library.0009_document_type_templates` (data: templates for every type, typed documents confirmed as migrated), `notify.0002_rich_notifications` (data: existing in-app notifications classified by kind, text unchanged), `accounts.0007_passkey_mode` (data: explicit passwordless choice kept, passwordless on for discoverable passkeys), `notify.0003_template_brand_footer` — applied by `personaldocs upgrade`.
- Documentation: 38 bundled guides (new in change set P: password reset; in change set O: notifications; in change set N: document types; in change set M: antivirus, authentik, security center), `docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md`, README, CONTRIBUTING, SECURITY (`docs/guides/`), requirements, traceability, architecture and 15 ADRs, generated settings reference, test report, release checklist, changelog.

## Change set Q: PaddleOCR (PP-OCRv5) and the complete OCR lifecycle {#change-set-q}

**Numbering.** The change prompt called this "Change Set P" with AT-191…AT-210. Those numbers were already used, so
it is **Change Set Q** with **AT-211…AT-230** (prompt AT-n → AT-(n+20); full mapping in [TRACEABILITY.md](TRACEABILITY.md)).
Decision record: [ADR 0016](adr/0016-paddleocr-ocr-lifecycle.md).

**Root cause: removed OCR text came back.** The pipeline was mapped end to end; nine causes were found and fixed:

1. *Remove OCR data* reset the search text to the PDF's embedded text layer, so text from the scanner or an earlier
   OCR program stayed searchable. It can now be hidden (`Document.ignore_embedded_text`).
2. The Remove button was hidden when no version was marked `ocr_applied`; it is now offered whenever OCR or embedded
   text exists.
3. *Regenerate preview* (`/reprocess` → `process_version`) and the integrity repair re-ran automatic OCR, and
   migration 0007 had made every type *Automatic* on upgraded installs. These jobs now carry `auto_ocr: False`.
4. Queued or running Local AI jobs recreated suggestions and semantic chunks after removal. They now carry the
   document's `ocr_epoch`; removal bumps it and cancels queued AI work.
5. Confirmed details kept raw OCR excerpts (`DocumentField.source_excerpt`); removal clears them.
6. A page-range re-run left the previous full `searchable.pdf`, still served by the preview and share links. A run now
   replaces or deletes the superseded copy, and removal deletes every `searchable*.pdf` of the document.
7. Stale searchable files inside known version directories were never detected. Removal and the orphan analysis
   find them now.
8. Policy switches never deleted data, and nothing said so. The UI now offers *Remove* and *Disable* explicitly; the
   per-document override beats the type.
9. `set_current_version` rebuilt the search text without `document_text()`, and removal left `ocr_sources` and
   `ocr_languages` set. Both are fixed.

**Previous OCR storage / index map** (before this change):

| Where | What |
|---|---|
| `DocumentVersion` | `text`, `ocr_applied`, `ocr_quality`, `ocr_pages`, `searchable_path`, `pdfa` |
| `Document` | `content_text`, `search_vector` (GIN index; weights A title, B type/correspondent/tags/owner/fields, C `content_text`), `type_suggestions`, `ocr_sources`, `ocr_languages`, `ocr_state` |
| `DocumentField` | proposals with `source_excerpt` (raw OCR snippets) |
| Local AI | `AISuggestion`, `DocumentChunk` (semantic-search embeddings), queued `AIJob`s |
| Files | `DERIVATIVES_DIR/<id[:2]>/<id>/searchable.pdf` (plus `thumb.png`, `preview.pdf`); scratch folders `TMP_DIR/ocr-*`, `proc-*` |

New in this change:

- `DocumentVersion`: `ocr_engine`, `ocr_model`, `ocr_profile`, `ocr_blocks`, `ocr_at`.
- `Document`: `ocr_override`, `ocr_profile`, `ignore_embedded_text`, `ocr_epoch`.
- `DocumentType.ocr_profile`.
- `OcrRun` (metadata only).
- Scratch folders `TMP_DIR/paddle-*` and `ocrtest-*`.

**Runtime actually validated** (development container, CPU, AVX):

- PaddlePaddle **3.2.2**, PaddleOCR **3.7.0** and PaddleX **3.7.2** on Python 3.13.
- Models: `PP-OCRv5_mobile_det`, `en_` / `arabic_` / `devanagari_` / `te_` / `ta_PP-OCRv5_mobile_rec`, and
  `PP-LCNet_x1_0_doc_ori`.
- PaddlePaddle 3.3.1 crashed on CPU in oneDNN (`ConvertPirAttribute2RuntimeAttribute`), and PaddleOCR 3.2.0 lacks the
  ar/hi/te/ta PP-OCRv5 models, hence the pins.
- **Effective defaults:** engine PaddleOCR; mobile models; profiles offered English, Arabic + English and Hindi +
  English; default profile English; document orientation on; text-line orientation **off** (measured, see
  [benchmark](OCR_BENCHMARK.md#engines)); unwarping off.
- **Health:** a real inference self-test read "PERSONAL DOCUMENTS OCR SELF TEST 2027" in 2.5–3.8 s
  (`manage.py doctor`, `test_live_at211_*`).

**6 GB / 4 vCPU worker configuration:**

- one heavy job at a time (`processing.heavy_concurrency` = 1);
- PaddleOCR with 2 CPU threads and `RLIMIT_AS` 3000 MB per job, plus a CPU-time limit and a timeout;
- worker unit `MemoryHigh=3400M`, `MemoryMax=4000M`, `CPUWeight=50`.

Measured peak RSS of the worker process: 1.3–1.9 GB. The self-test also passes under a 3 GB address-space limit.

**Not validated here:**

- a real Debian 13 / Proxmox LXC with 6 GB: install, upgrade, repair, reboot and load;
- real family documents (no sanitised real samples; every benchmark sample is synthetic);
- a real Local AI server with PP-OCRv5 output (mocked in tests);
- Hugging Face model download from a fresh server (models were downloaded from the BOS mirror in the container).

## Change set P: passkey sign-in, password reset, security templates, ClamAV repair {#change-set-p}

**Numbering.** The change prompt called this "Change Set O" with AT-176…AT-190; those numbers already belonged to the
rich notifications change set, so it is **Change Set P** with **AT-196…AT-210** (prompt AT-176 → AT-196 … AT-190 →
AT-210; full mapping in [TRACEABILITY.md](TRACEABILITY.md)).

**Root cause: passkey only after the password.** Passwordless sign-in was gated by `auth.allow_passwordless`, which
defaulted to off, plus a per-person opt-in. So passkeys were only offered as the second step after the password, and
the old "Sign in with a passkey" button stayed hidden. Fixed with `auth.passkey_mode` (Passwordless by default,
Password + Passkey as the alternative), migration `accounts.0007_passkey_mode` (keeps an explicit earlier choice and
turns passwordless on for accounts with a discoverable passkey), the sign-in page order password → "or" → **Sign in
with Passkey** → authentik/Google, passkey autofill (`autocomplete="username webauthn"`, conditional mediation), and
passwordless turned on automatically after enrolling a discoverable passkey. Sign-in also accepts an email address
that belongs to exactly one active account.

**Root cause: ClamAV "Unavailable … /run/clamav/clamd.ctl (FileNotFoundError)".** Verified against the Debian 13
packages `clamav-daemon` / `clamav-freshclam` 1.4.3+dfsg-1: `clamav-daemon.service` is socket-activated
(`Requires=clamav-daemon.socket`; the socket unit listens on `/run/clamav/clamd.ctl` with `RemoveOnStop=True`); both
units have a `ConditionPathExistsGlob` on the `main` and `daily` signatures, so without signatures they are skipped
with no error and nothing starts them later; the service has no `Restart=`, so a clamd killed by the out-of-memory
killer stays down; and Debian's `LocalSocket /var/run/clamav/clamd.ctl` is a different string from the socket unit's
`/run/clamav/clamd.ctl`. The earlier installer kept that line (it only added `LocalSocket` when missing). When the
strings differ, clamd does not adopt the systemd socket, binds its own file and deletes it when it stops or restarts,
leaving the app's path missing. The engine version and signature date on the page were cached from the last
successful contact and were not proof that scanning worked. Which cause applies on a given host is shown by the new
diagnosis; the most likely one for the reported upgrade is the LocalSocket mismatch.

**Implemented.**

- `backend/apps/ops/clamav_check.py` (standard library only): diagnosis and repair shared by the `personaldocs`
  command, the root host helper (`antivirus_repair`) and the web app. Repair: packages, clamd.conf (`LocalSocket` =
  socket unit path, no TCP, `LocalSocketMode 666`, `FixStaleSocket true`, `StreamMaxLength 1100M`,
  `ConcurrentDatabaseReload no`, removes the unsupported `EnableVersionCommand` (and any option `clamconf` rejects), one-time backup `clamd.conf.personaldocs-backup`,
  `clamconf` validation), restart drop-in `50-personaldocs.conf`, tmpfiles `personaldocs-clamav.conf`, signatures,
  unit order, stale pid, wait for `PONG` (up to 4 minutes), access by the `personaldocs` account (`runuser`), final
  diagnosis and self-test; success only for Healthy/Degraded; never a TCP port.
- `personaldocs antivirus status|repair|selftest`; install, upgrade (post-upgrade), post-upgrade and repair run the
  repair; `antivirus.socket` synced with `manage antivirus sync-socket`; `doctor` starts with the root diagnosis and
  adds three app checks. Django command `antivirus status|selftest|sync-socket PATH`.
- Antivirus page: Healthy / Degraded / Unavailable / Error / Turned off, Socket row, "last seen … not proof" for the
  engine, Self-test row, **Run self-test**, **Diagnose / Repair** with **Repair antivirus**. Security Health: 0 points
  and At Risk for Unavailable and Error. Daily self-test in the hourly check. API `GET /api/security/antivirus/diagnose`,
  `POST /api/security/antivirus/selftest`, `POST /api/security/antivirus/repair`.
- `backend/apps/accounts/password_reset.py`: temporary password (16 characters, hash only, shown once, never emailed,
  forced change, all sessions end, tokens invalidated) and branded single-use reset email (`auth.reset_token_minutes`,
  newer request invalidates older links, never in the outbox, in-app history, Telegram, push or logs, https on
  Internet deployments); Main Administrator protection; `POST /api/family/members/<id>/reset-password`; **Reset
  password…** dialog in `pages/settings/Family.tsx`.
- Security events `security.password_reset_requested`, `security.password_admin_reset`, `security.temporary_password`,
  `security.password_changed`, `security.account_locked`, `security.google` (critical by default); mandatory security
  text on every security event; template **Branding name** and **Footer / help text** (migration
  `notify.0003_template_brand_footer`).

**Handover evidence.** See [TEST_REPORT.md](TEST_REPORT.md#change-set-p) for the effective socket path after repair
(`/run/clamav/clamd.ctl`), service identity access, self-test results, password-reset security results and the
per-AT statuses.

**Not executed (must be done on real systems).** A real Debian 13 / Proxmox LXC upgrade and `personaldocs antivirus
repair`; reboot / LXC restart persistence on a real host; `clamav-daemon` restart and freshclam updates on a real
systemd host; real passkey sign-in on iPhone/iPad Safari, Android Chrome, Windows Hello, macOS, Bitwarden/1Password
and hardware security keys (the automated tests used a software authenticator); real SMTP delivery of the reset email
to real mail clients.

**Next steps.** On the Proxmox LXC: `sudo personaldocs upgrade`, then `sudo personaldocs antivirus status` and
`sudo personaldocs doctor`; check the Antivirus page shows Healthy and **Run self-test** passes; reboot the LXC and
check again; sign in with a passkey on each device; send a reset email to yourself. Record the results in
`TEST_REPORT.md`.

## Change set O: rich notifications {#change-set-o}

**Inventory before the change.**

- Channels: in-app (`Notification` rows), email and Telegram (`OutboxMessage` with a plain-text body, delivered by
  the worker). No Web Push.
- One plain-text layout, `apps/notify/templates.py::render`, produced every body. Telegram received the same plain
  text as email; the in-app feed showed only a title with a generic icon.
- Events were raised with hard-coded strings at each call site: `apps/notify/events.py` (access granted, documents
  added, documents archived/deleted, import finished, backup failed, integrity problems, processing
  failed/completed), `apps/notify/expiry.py` (expiry reminders), `apps/security/alerts.py` (new IP, new country,
  failed sign-ins, policy changes …), `apps/security/antivirus.py` (threat, released, unavailable, definitions),
  `apps/security/center.py` and `views_center.py` (security test findings, storage warnings, reboot), and the
  passkey, TOTP and recovery-code events.

**Old rendering paths replaced.** All call sites now build a structured `Message` (directly, or through
`rich.from_legacy` for the older `notify()` arguments) and hand it to `dispatch`; `templates.render` now only
builds the plain-text layout (for example the plain-text part of email and the plain-text preview). Severity, category and icon come from the event catalogue instead of each call
site.

**Unified schema and renderers** (`apps/notify/rich.py`): `Message` (event, severity, category, icon, title,
heading, summary, details with icons and a *sensitive* flag, actions with *in-app only*, guidance, items, link,
placeholder context, TEST flag). Renderers: `render_in_app` (card data in `Notification.data`), `render_email`
(subject, plain text, HTML), `render_telegram` (HTML parse mode, inline URL buttons on https, plain-text fallback),
`render_push` (lock-screen safe by `me.push_preview`). `apps/notify/icons.py` is the central icon map (emoji, SVG name,
accessible label) with severity colours that always come with a text label. `apps/notify/event_defs.py` gives each
event a category, default severity and icon and adds `security.authentik` and `document.changed`, plus the channel
`push`. `apps/notify/events.py::default_actions` defines the event-specific actions; `rich.safe_path` refuses API and
release paths. `apps/notify/webpush.py` implements VAPID (key pair on first use, stored encrypted) and aes128gcm with
`http-ece` 1.2.1 and `py-vapid` 1.9.4, the push-service allowlist and removal of expired subscriptions. Template
overrides (`NotificationTemplate`) are applied by `rich.apply_template` after `check_template_text` validation;
`floor_severity` keeps critical events at Warning or above. The repeat cooldown is the `cooldown_group` of
`events.notify`.

**Frontend.** `pages/Notifications.tsx` (Notification Center), `components/NotificationCard.tsx`,
`components/NotificationBanners.tsx` (polling every 60 s and on navigation), `pages/settings/NotificationTemplates.tsx`
(Template Manager with previews, TEST, Delivery history), the push section of My account → Notifications, and
`sw.ts` (shows push notifications and opens only same-origin pages).

**API** (under `/api`): `GET notifications`, `POST notifications/read`, `POST notifications/<id>/action`,
`GET/POST/DELETE notifications/push`, `POST notifications/push/test`, `GET notifications/templates`,
`PUT/DELETE notifications/templates/<event>`, `POST notifications/templates/<event>/preview`,
`POST notifications/templates/<event>/test`, `GET notifications/deliveries`.

**Settings.** `notifications.include_document_number` (off), `notifications.push_enabled` (on),
`notifications.repeat_cooldown_hours` (24, 1–168), `me.push_preview` (standard).

**Migration** `notify.0002_rich_notifications`: new fields on `Notification` (event, category, severity, icon,
summary, data, is_test) and `OutboxMessage` (event, severity, html, payload, provider_ref, is_test); new tables
`PushSubscription`, `NotificationTemplate`, `ExpirySnooze`; a data step classifies existing in-app notifications by
kind without touching title, text, links or read state. SMTP/Telegram configuration, preferences, critical events and
channels and expiry schedules are unchanged; push is never added to anyone's channels.

**Tests.** `tests/test_rich_notifications.py`: 19 tests (AT-176…AT-193, AT-195), all passed; the push test decrypts
the encrypted payload with the subscriber key; `http://`, `127.0.0.1`, unknown hosts and URLs with credentials are
refused as endpoints; `<script>`, `<img onerror>`, Markdown and Telegram markup are escaped; TEST sends create only
the audit entry `notifications.test_sent`. Affected earlier suites: 125 passed. Full backend suite: **331 passed** (330 in the full run plus the live ClamAV test re-run once the local daemon was started).
`scripts/e2e.sh` (desktop step AT-176..186 and AT-194 at tablet, mobile-portrait and mobile-landscape):
**59 PASS, 0 FAIL**.

**Pending (not run).** Real SMTP delivery and HTML rendering in Gmail, Outlook and Apple Mail; a real Telegram bot
with inline buttons on an https address; real Web Push on Android/Chrome, the iOS/iPadOS Home Screen app, Firefox and
Windows; an installed PWA on real devices; upgrade of a real Debian 13 installation.

**Limitations.** Email, Telegram and push providers only report that they accepted a message, not that it was shown
or read. HTML email appearance differs between mail programs; the plain-text part carries the same content. Push
needs the HTTPS address, and on iPhone/iPad the app must be on the Home Screen.

## Change set N: document types and metadata templates {#change-set-n}

**Root cause of the reported defect.** The Details panel (`frontend/src/components/DocumentPanel.tsx`) rendered
"Type" as a hard-coded read-only row ("—" when unset); the type could only be changed through the hidden
"Rename / edit details…" dialog. Detail rows came from a fixed frontend label list (`FIELD_LABELS`) and from
`DocumentField` rows written by OCR extraction regardless of type. Uploads without a chosen type stayed untyped, so
OCR details appeared with Type "—". Two further defects were found and fixed: the old bulk `set_type` action could
overwrite confirmed types, and the older `DELETE /api/metadata/type/<id>` endpoint could hard-delete a type in use,
silently untyping its documents.

**Data model** (migration `library.0009_document_type_templates`):

- `DocumentType`: `description`, `sort_order`, `reminder_days` (empty = global setting). Types are seeded editable
  data (`seed_defaults`), not code constants.
- `DocumentTypeField` (template field): stable `key`, `label`, `field_type` (text, long_text, date, number, boolean,
  select, country, person, identifier), `enabled`, `required`, `order`, `help_text`, `extract`, `searchable`, `role`
  (expiry, issue, no_expiry), `choices`, `validation` (pattern, min, max, max_length).
- `Document`: `type_source` (manual, folder, ocr, ai, import, system, migrated), `type_confirmed`,
  `type_suggestions` (pending, with source, reason and confidence), `details_incomplete_ok`.
- `DocumentField`: `label`, `scope` (type, custom, unmapped), `overridden`, `previous_type`, `updated_at`; sources
  manual, ocr, mrz, ai, import, system, migrated.
- `Folder.suggested_type` (a suggestion only; inherited by sub-folders).

**Migration behaviour.** Every type gets its template (the defaults of its starting template plus the fields its OCR
policy listed). Typed documents keep their type, marked confirmed with source *migrated*. Untyped documents stay
untyped; no type is guessed from field names. Values of typed documents outside the template become additional
details (scope *custom*), except confirmed issue, expiry and no-expiry values, whose field is added to the template
so dates and reminders keep working. Nothing is deleted.

**Behaviour.** `library/doctypes.py` holds templates, validation, details status, suggestions (folder, OCR text,
Local AI), the type-change plan and change, previous-value resolution, OCR re-mapping, promotion and the report;
`library/views_types.py` serves `/api/documents/<id>/type`, `/remap-ocr`, `/api/documents/bulk-type`,
`/api/document-types` (and `/admin`, `/<id>`, `/<id>/fields`, `/review`). Frontend: `components/DocumentDetails.tsx`
(Details panel, type dialogs, bulk dialog, folder suggestion), `pages/settings/DocumentTypes.tsx` (types, template
editor, review of untyped documents), `components/UploadDialog.tsx`. Only confirmed values of the expiry-role field
drive the expiry date and reminders; per-type reminder days override the global schedule. Local AI extraction for a
typed document proposes only template fields marked extractable. `personaldocs manage document_types report` and
`personaldocs doctor` report the counts.

**Tests.** `tests/test_document_types.py`: 16 tests (AT-161…AT-174), all passed. Parity: the desktop document types
step and the AT-175 touch steps (tablet, mobile-portrait, mobile-landscape), all passed; full `scripts/e2e.sh`
55 PASS, 0 FAIL. Not automated: the bulk skip of documents with another confirmed type and the bulk preview counts.
Pending (not run): installed PWA on real iOS/Android devices; upgrade of a real Debian 13 / Proxmox installation with
existing production data.

**Limitations.** Type suggestions from OCR text are keyword and MRZ rules, not a classifier; a document with unusual
wording gets no suggestion and stays *Not assigned* until someone sets the type.

## Blockers (external validation)

| Gate | Needed |
|---|---|
| AT-26 native install, interrupted rerun, upgrade, rollback, repair | A fresh Debian 13 LXC on the Proxmox host, plus the real private repository URL and a read-only token |
| AT-24 restore on a clean LXC | Second LXC (or reinstall) and a mounted NAS share |
| Guided installers and NAS mounting on real hosts | A Proxmox host, a privileged LXC with `mount=nfs;cifs`, and a real NFS/SMB share (only dry runs and a simulated `systemctl` were possible here) |
| AT-17 live SMTP/Telegram | SMTP relay credentials; a Telegram bot token |
| AT-19 live IMAP | A test mailbox |
| AT-21 live Google | A Google Cloud OAuth client and the public HTTPS origin |
| AT-14 real devices | An Android phone and an iPhone |
| AT-39/41 real proxy IPs | Sign-ins through the real NPM / Pangolin (Newt) with `PD_TRUSTED_PROXY_IPS` set; check *Your connection* |
| AT-40/49 MaxMind download | A MaxMind account ID and GeoLite2 license key (download path tested only with a simulated server) |
| AT-31..36 live AI servers | LM Studio and/or Ollama on the LAN with a text and an embedding model (tested against a fake OpenAI/Ollama server) |
| Passkeys / TOTP autofill on real clients | iPhone, Android, Windows Hello, Bitwarden/1Password on the HTTPS origin (tested with a software WebAuthn authenticator) |
| AT-76/83 real devices | Installed PWA on a real Android phone and iPhone/iPad (automated checks used emulated viewports) |
| AT-69 real delivery | SMTP and Telegram credentials to see the new templates in a real inbox/chat |
| Public release | Making the repository public (owner action in GitHub settings; license chosen: MIT) |
| AT-98/99 one-line installer for real | A fresh Debian 13 VM/LXC with systemd, and a **public** repository so the raw URL works (tested here with stubbed system commands only) |
| AT-90/91 real desktop drag | Dragging a folder from Windows Explorer / Finder into Chrome, Edge, Firefox and Safari (tested with a synthetic DataTransfer and unit-tested folder walk) |
| AT-111 real Arabic/Hindi scans | Non-sensitive printed Arabic and Hindi test pages on the production server (only synthetic samples were used) |
| AT-125 real weather provider | Outbound internet access from the LXC to Open-Meteo (tested with a fake local provider) |
| AT-128/130 real phones | Sign-in designs on a real Android phone and iPhone (emulated viewports only) |
| AT-27 resource-constrained load | Benchmark on the 2 vCPU / 4 GB LXC with realistic multi-page scans |
| AT-146..148 real authentik | A real authentik server with an OAuth2/OpenID provider (tested against a local fake OIDC provider with real RS256 tokens and PKCE) |
| AT-149 Internet Ready on the real path | Public DNS, a valid TLS certificate and an Internet-accessible staging site (the passing path was tested only with mocked responses) |
| AT-153..155 real host helper | Debian 13 with systemd: `personaldocs-host.path` as root installing apt security updates, rebooting and inspecting ufw/nftables (tested with stubbed commands only) |
| AT-140/142 ClamAV on Debian 13 | `clamav-daemon` and automatic `clamav-freshclam` updates on Debian 13 (the live scan test ran against ClamAV 1.5.4 in the development container; freshclam updates were not exercised) |
| Change set O real channels | SMTP to Gmail/Outlook/Apple Mail (HTML rendering), a Telegram bot on the https address (inline buttons), Web Push on Android/Chrome, an iPhone/iPad Home Screen app, Firefox and Windows; upgrade of a real Debian 13 installation (tested with mocked providers only) |
| Change set P on a real host | A real Debian 13 / Proxmox LXC upgrade with `personaldocs antivirus repair` (verified only on a simulated Debian host and against a real clamd in the development container); a reboot / LXC restart to confirm the drop-in and tmpfiles persistence; `clamav-daemon` restart and freshclam updates under real systemd |
| Change set P passkeys and email | Sign in with Passkey on iPhone/iPad Safari, Android Chrome, Windows Hello, macOS, Bitwarden/1Password and hardware security keys (software authenticator only); the reset email through a real SMTP server in real mail clients (mocked SMTP only) |
| Change set M install/upgrade | A real Proxmox/LXC install and an upgrade from the previous release: ClamAV memory use on 4 GB, `--without-antivirus`, host helper installation, `status`/`doctor` output |

None of these are being reported as passed. Exact steps are in `docs/TEST_REPORT.md`.

## Known limitations and simplifications

- The six annotated reference screenshots mentioned in the change prompt arrived during the work as chat images; they were used as requirements only and are not committed.
- Drag and drop needs a mouse/trackpad; touch screens use **Move to…** (same server checks).
- PDF.js renders pages as images (no selectable text layer in the viewer); the recognised text is in the **Text** tab.
- English, Arabic and Hindi are offered by default; Arabic and Hindi recognition was only checked with synthetic
  samples, not with real scans. Strong glare is still the weakest case in the benchmark (F1 0.70): ink that is
  washed out in the photo cannot be recovered, so the guide tells people to retake such photos.
- Folders dropped from the desktop in a browser without the File and Directory Entries API are reported and not
  uploaded; such users should use **Import folder**.
- The four annotated V3 screenshots (menu clipping, rename/delete, sub-folder icon/views, drag-drop, OCR junk) were
  used as requirements only and are not committed.

- Browser offline storage behaviour (quota, account switching) is implemented but covered by manual steps, not automated tests.
- The audit log records document views on the detail endpoint. File and preview fetches are not individually audited, except downloads.
- The accessibility audit is automated (axe-core, WCAG 2.1 A/AA) and clean; a manual screen-reader review has not been done.
- Antivirus is fail-open: when ClamAV is down, files stay usable and are marked Not scanned. Archives are scanned as
  one file with ClamAV's limits; a Clean archive does not prove each inner file was inspected.
- The Basic Internet Security Test is a baseline of this application and this host only. It is not a penetration test
  and does not prove the system is free of vulnerabilities. The Security Health score is a summary, not a certification.
- Firewall support is monitoring only; rules are changed on the host.
- The ClamAV repair (Change Set P) was verified on a simulated Debian 13 host and against a real clamd (ClamAV 1.5.4)
  in a development container, not yet on a real Debian 13 Proxmox LXC; administrators must run
  `sudo personaldocs antivirus repair` (or the upgrade) and check the result.
- The new `personaldocs doctor` and `status` checks (ClamAV, signatures, host helper, Internet HTTPS, storage
  thresholds, pending reboot) have no dedicated automated test; they are covered only by the pending Debian 13 run.

## Next executable steps

1. Push the repository to the private GitHub remote. Create a fine-grained read-only token.
2. On the Proxmox host run `scripts/proxmox-create-lxc.sh` (or create a Debian 13 LXC and run `scripts/easy-install.sh` inside it), following `docs/guides/installation.md#guided`. Record results in `TEST_REPORT.md`.
3. Configure NPM or Pangolin, then check the NAS connection in Settings → Storage & backup. Run *Back up now*, then a restore drill on a second LXC.
4. Configure SMTP, Telegram and, optionally, Google. Run the live checks listed in the test report.
5. On the LXC check `personaldocs status` (ClamAV, freshclam, host helper), run **Scan entire existing library**,
   **Check for updates** and the **Basic Internet Security Test**, and connect a test authentik provider; record the
   results in `TEST_REPORT.md`.
6. Run `scripts/bench_processing.py` on the LXC with realistic scans. Tune `processing.heavy_concurrency` and `PD_PROCESS_MEMORY_LIMIT_MB`.
7. Change Set P on the LXC: `sudo personaldocs upgrade`, `sudo personaldocs antivirus status`, Antivirus page
   **Healthy** and **Run self-test** passed, reboot the LXC and check again, **Sign in with Passkey** on each device,
   a reset email to yourself; record the results in `TEST_REPORT.md`.
8. Tag `v0.1.0` once the gates pass (`docs/RELEASE_CHECKLIST.md`).
9. Public release (owner decisions): enable GitHub private vulnerability reporting, run `scripts/privacy_check.sh --history`, then change the repository visibility in GitHub settings.

## Session log

- 2026-10-07 (change set P): Sign in with Passkey on the first sign-in screen with passkey autofill, Passkey sign-in
  mode (Passwordless default / Password + Passkey) replacing `auth.allow_passwordless`, passwordless turned on after
  enrolling a discoverable passkey, email-or-username sign-in; administrator **Reset password…** with a temporary
  password shown once or a branded single-use reset email, Main Administrator protection; security events for
  password resets, account locked and Google links with mandatory security text, template branding and footer;
  ClamAV diagnosis, repair and self-test (`clamav_check.py`, `personaldocs antivirus`, host-helper
  `antivirus_repair`, Diagnose / Repair, Healthy / Degraded / Unavailable / Error in Security Health). Fixed: passkeys
  only after the password (root cause above) and ClamAV "Unavailable … /run/clamav/clamd.ctl (FileNotFoundError)"
  after upgrade (root cause above).

- 2026-10-07 (change set O): rich notifications — one structured message with severity, category, icons, details,
  actions and guidance rendered for in-app, HTML email with a plain-text part, Telegram (HTML, buttons, plain-text
  fallback) and Web Push (VAPID, aes128gcm, push-service allowlist, lock-screen detail per person); the Notification
  Center with filters, details and banners; event-specific actions without tokens and never a quarantine release;
  the Template Manager with allowlisted placeholders, previews and TEST sends; delivery history; repeat cooldown for
  recurring conditions; masked document numbers only on request; migration `notify.0002_rich_notifications`.

- 2026-10-07 (change set N): document types as editable data with metadata templates (field types, roles,
  required, OCR/AI and searchable flags, validation, order), the Details panel with the type row, status, template
  fields, additional and previous details, value provenance, type suggestions from folders, OCR text and Local AI,
  safe type changes with preview and map/keep/remove, re-mapping of existing OCR data, one-off details and
  promotion, bulk Set type…, folder suggested types, Settings → Documents & folders → Document types with the review
  of untyped documents, per-type reminder days and the `document_types report` command. Fixed: the read-only Type row
  (root cause above), bulk `set_type` overwriting confirmed types, and the metadata delete endpoint untyping
  documents.

- 2026-10-07 (change set M): ClamAV antivirus (background scan over the local clamd socket, fail-open, statuses,
  quarantine with main-administrator release and delete, size limit, library scan with pause/resume/cancel and
  schedule, freshclam and Update now, critical alerts, quarantine excluded from backups and integrity reports),
  authentik OpenID Connect sign-in (PKCE, state, nonce, explicit linking, provisioning, group-to-role mapping), the
  Administrator role, the security center (Internet Ready and HSTS, Basic Internet Security Test, OS security updates
  and controlled reboot through the root host helper, firewall monitoring, Security Health score, security record
  retention and purge, Storage Health and safe cleanup), installer, `status` and `doctor` additions; Settings →
  Security reorganised (access policy under Security → Access policy); the "administrators" 2FA policy now covers
  Administrators.

- 2026-10-06 (change sets K and L): selective OCR (policy per type Disabled/Manual/Automatic, languages, expected
  fields and AI permission; custom types; source, page and language selection; front and back as one job; states,
  cancel, Mark reviewed, Remove OCR data; OCR review queue; limits and pause; language packs via doctor/repair),
  Overview widgets (Today with Hijri via `hijridate`, weather proxy with cache, month calendar, upcoming holidays from
  the `holidays` library with administrator corrections, Documents summary, Shared with me, Recent activity;
  Customize Overview with sizes and styles), sign-in designs (five bundled presets, custom wallpaper and logo,
  re-encoded and stripped of metadata), and the admin-only setup with optional members. Fixed: the OCR contrast
  stretch clipped sparse ink and erased text (regression sample added); calendar accessibility roles.

- 2026-10-05 (change set J): portal overflow menus (fixed: menus clipped by the breadcrumb bar and scrolling panels; keyboard-opened menus did not receive focus), document rename/archive/permanent delete and folder rename/icon/share/archive from the menu, standard 📁 for sub-folders with an approved icon picker and data migration, List/Thumbnails/Details with server-side sorting saved per account, desktop file-and-folder drop with hierarchy, own library first and expanded, OCR rework (root causes: EXIF orientation ignored, no rotation/skew handling, month-first dates rejected, header/value columns not paired; benchmark 0.61 → 0.97), "No expiry" documents, public title, demo owner (now the demo label A. Ansari), `personal-DM.sh`, LinkedIn-ready README, Ko-fi `FUNDING.yml`.

- 2026-10-05 (change sets H/I): folder tree identity, validated file-type icons, atomic and serialised moves (fixed: members could not move their own documents; concurrent opposite moves could orphan folders; moves into archived folders), drag and drop and Move to…, PDF.js viewer with zoom/fit, import destination picker with exact preview, dashboard widget editor, critical/optional notification catalogue with templates and bulk summaries, daily/weekly/monthly backups, tablet overflow fixes, malformed-filter 500 fixed, open-redirect hardening of `?next=`, dependency upgrades (PDF.js 6.4 for GHSA-hq66-cqwq-w95j, React Router 7.18 for GHSA-wrjc-x8rr-h8h6), public README/guides/SECURITY/CONTRIBUTING, privacy check (tree and history clean; one real LAN address replaced in code/tests).

- 2026-10-05: change set 2026-10 implemented (AT-31..AT-50, passkeys) with 74 new tests; docs, traceability, settings reference and upgrade notes updated. Live validation of proxies, MaxMind, AI servers and real authenticators is listed under Blockers.

- 2026-10-04: closed the previous limitations — resizable panels (mouse and keyboard, remembered per account), per-device session list with individual sign-out, optional folder templates for new members, event notifications (access granted, import finished, processing failed, backup failed, integrity problems), PDF/A-2b validation (veraPDF when installed, structural check otherwise), automated accessibility audit with a CI end-to-end job. Fixed during verification: an outbox duplicate-key insert could break an enclosing transaction (now a savepoint); changing your own password signed out the current device (now only other devices).

- 2026-10-03: initial implementation of the whole scope. Commands run are summarised in `TEST_REPORT.md`. Fixed during verification: a row lock on an outer join in processing; backup folder name collisions and pruning order (now sorted by manifest time); `on_commit` handling in tests; idempotent retry of completed browser import items; Chrome PDF preview blocked by CSP sandbox (sandbox now applied only to non-PDF/image responses).
- 2026-10-04: NAS connection moved into Settings → Storage & backup (NFS or SMB, validated fields, Connect/Disconnect, live status and actionable errors). The web app writes a request file; a path-activated root helper (standard library only, re-validates every field, fixed mount unit `/mnt/pdnas`, SMB credentials in a root-only file) mounts the share, creates the backup folder, checks write access and the app adopts it as the backup destination. New guided installers ask every parameter and perform the whole LXC installation; `manage.py apply_settings` applies validated settings from a file.
