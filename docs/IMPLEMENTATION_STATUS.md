# Implementation status

Last updated: 2026-10-11 · Version 0.1.0 (pre-release)

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

## Change set Z: optional AI Document Intelligence and the OCR engine order {#change-set-z}

**Numbering.** Prompt AT-416…AT-435 → **AT-441…AT-460** (AT-416…AT-440 belong to Change Sets X and Y); see
[TRACEABILITY.md](TRACEABILITY.md#change-set-z). Requirements ADI-1…ADI-14 in [REQUIREMENTS.md](REQUIREMENTS.md#change-set-z).
**Migrations:** `core.0008_ocr_engine_order_ai_mode` (settings, data only, reversible) and `ai.0003_intelligence`
(additive fields and the AI output table, reversible). Upgrade notes: [upgrades.md](guides/upgrades.md#change-set-z).

| Area | What was built | Files |
| --- | --- | --- |
| OCR engine order | `processing.ocr_engine_order` (new `order_list` setting type: order kept) and `processing.ocr_mode` replace *Default OCR engine* / *Fall back to Tesseract*; `resolve_engine` walks the order and records why engines were skipped; engines overview with availability | `library/ocr_engines.py`, `core/registry.py`, `library/ocr_views.py`, `SettingsForm.tsx`, `OcrEngines.tsx` |
| light-ocr | Adapter for the `@arcships/light-ocr` 0.5.9 CLI (JSON lines → the PaddleOCR line shape with boxes and confidence), status, real-recognition self-test, sandboxed process per page; pinned `package.json` + lockfile; installer/upgrade/repair install it with `npm ci` (non-fatal), `personaldocs ocr light-ocr[-reinstall]`, doctor checks | `library/ocr_engines.py`, `library/ocr_runs.py`, `backend/light-ocr/`, `scripts/personaldocs`, `ops/.../doctor.py` |
| AI modes | `ai.mode` (on demand / OCR only / OCR + AI / Smart Auto), Smart Auto triggers and threshold, `ai.cloud_automatic`, `ai.allow_profile_choice`; `after_processing` follows the mode; `ai.auto_analyze` migrated | `ai/jobs.py`, `ai/service.py`, `core/registry.py` |
| Providers | OpenAI, Anthropic (Messages), Gemini (generateContent), OpenRouter next to the local adapters; usage tokens; capabilities; `guard_payload` refuses images/files a profile may not receive | `ai/providers.py` |
| Local / Cloud | `AIProfile.location` and four Cloud send controls; `plan_payload` (the one policy check), `ConsentRequired` + `disclosure`; metadata left out of prompts when not allowed | `ai/service.py`, `ai/views.py`, `ai/models.py` |
| AI Actions | `run_action` for analyze, extract, verify, summarize, suggest_type, filename, expiry (background jobs) and ask (document-scoped); `AIOutput` for disposable results; per-action source (OCR text / page image / PDF) | `ai/service.py`, `ai/jobs.py`, `ai/views.py`, `AIActions.tsx` |
| Review | Evidence (observed — checked against the OCR text — or inferred), AI confidence, conflict flag; accept / edit then accept / accept selected / reject all; conflicts need confirmation | `ai/service.py` `_store_suggestions`, `accept`; `AISuggestions.tsx` |
| Safety | System policy + task + delimited untrusted document (random marker, forged markers neutralised); dates only when the year is printed, numbers/names only when present | `ai/service.py` `build_messages`, `wrap_document`, `_date_in_text` |
| Provenance | Job trigger, profile name snapshot, provider, Local/Cloud, data categories, usage; AI History and output deletion in Document Details; status labels | `ai/models.py`, `ai/views.py` `job_json`, `status_label` |
| Settings / doctor | Settings → AI: Document Processing (mode), provider choice, Local/Cloud badge, send controls, Last Test, **Test Profile**; doctor: AI mode, default profile, provider/model/capabilities, key stored yes/no, reachability | `LocalAI.tsx`, `ai/views.py` `_save_test`, `doctor.py` |

**Decisions.**
- *Runtime fallback.* Auto mode skips engines that are unavailable before recognition starts (not installed, failed
  self-test, missing model, profile not supported). An engine that crashes on a document still fails the run safely
  instead of handing the document to the next engine, because AT-214 / AT-224 require exactly that.
- *light-ocr profiles.* The PP-OCRv6 Small bundle reads Latin script; the Arabic, Devanagari, Telugu and Tamil
  profiles go to the next engine with the reason recorded.
- *Node.js.* light-ocr declares Node ≥ 22 but runs on Debian 13's Node 20 (verified with 0.5.9); the installer
  requires 20+.
- *Upgrades.* An installation that had AI on with automatic analysis keeps *OCR + AI* (an opt-in already made) for
  new uploads only; nothing existing is queued. Automatic AI never uses a Cloud profile unless allowed (off).

## Change set Y: OCR → AI document analysis pipeline {#change-set-y}

**Numbering.** Prompt AT-401…AT-415 → **AT-426…AT-440** (the prompt also called itself "Change Set X", which is taken);
see [TRACEABILITY.md](TRACEABILITY.md#change-set-y). Requirements AIP-1…AIP-10 in [REQUIREMENTS.md](REQUIREMENTS.md#change-set-y).
**Migration:** `ai.0002_analysis_stages` (additive, reversible; marks earlier failed analyses as retryable, never as successful).

### Reproduced failure and root cause

An LM Studio profile (`qwen3-8b`, embeddings `text-embedding-nomic-embed-text-v1.5`): assistant jobs succeeded,
every Analyze Document job failed with *unavailable: The AI server returned HTTP 400*. Reproduced against a server that
answers like LM Studio (`tests/fake_ai_server.py`, `lmstudio` mode; `test_reported_http_400_reproduced_and_explained`):
the sanitized server answer is `'response_format.type' must be 'json_schema' or 'text'`.

| Problem | Root cause | Fix | Files |
| --- | --- | --- | --- |
| HTTP 400 on Analyze Document only | Analysis sent `response_format: {"type": "json_object"}` (the assistant sends a plain chat) | `json_schema` structured output; one prompt-only fallback when a server rejects it; remembered per profile | `ai/providers.py` |
| "unavailable", queued again | Every HTTP status ≥ 300 was classified *unavailable* (retryable) and the server's explanation was dropped | Status classes (auth, model missing, too large, bad request, transient 408/425/429/5xx); sanitized server message, rejected capability | `ai/providers.py`, `ai/jobs.py` |
| No usable text → image sent / AI called | Without text, the preview image went to a vision model; empty text still reached the AI | OCR first (reuse, or queue OCR with the configured engine and resume when it finishes); empty OCR fails before AI | `ai/service.py`, `ai/jobs.py`, `library/ocr_runs.py` |
| Opaque queue | No stages; retries reused the same status; repeated clicks added jobs | Stages and safe details on AIJob; bounded retries with next-retry time; one analysis per document; Retry action | `ai/models.py`, `ai/jobs.py`, `ai/views.py`, `LocalAI.tsx`, `AISuggestions.tsx` |
| Reasoning models | `<think>` blocks could precede (and contain braces before) the JSON | Stripped before parsing; cut-off answers reported | `ai/providers.py` |
| Long OCR text | Silently cut at *Max text sent* | Page-order split into up to three parts, results merged, remainder recorded | `ai/service.py` |
| No way to isolate OCR vs AI | One "Test connection" | Step-by-step connection test with model roles, Test AI analysis, Test OCR per engine | `ai/views.py`, `LocalAI.tsx` |

### Known limitations

- The real LM Studio server and the real PaddleOCR runtime were not available in this environment: LM Studio was
  emulated (its documented error for `json_object`, its `/api/v0/models` type listing); PaddleOCR used the existing fake
  worker in tests. Live verification against the reported server: **Blocked / Not Executed**.
- The vision model setting is kept but no longer used by Analyze Document (OCR-first by design).

## Change set X: performance {#change-set-x}

**Numbering.** Prompt AT-376…AT-400 → **AT-401…AT-425** (the prompt also called itself "Change Set W", which is
taken); see [TRACEABILITY.md](TRACEABILITY.md#change-set-x). Requirements PERF-1…PERF-12 in
[REQUIREMENTS.md](REQUIREMENTS.md#change-set-x). Measurements and the bottleneck table: [PERFORMANCE.md](PERFORMANCE.md).
**Migrations:** `core.0007_performance_metrics`, `library.0012_doc_active_folder_idx` (additive, reversible). The
layout is unchanged except the new Settings → Performance tab and a **Load more** row under long folder lists.

### Root causes

| Area | Root cause | Fix | Files |
| --- | --- | --- | --- |
| Settings, notification preferences, session | `config.get`/`get_user` ran one query per read; endpoints read hundreds of settings | Per-request snapshot (one query for global settings, one per person), invalidated on write in the same request, never holds secrets | `core/config.py`, `core/middleware.py`, `notify/catalog.py` |
| Document lists (folders, search, dashboard) | `current_version` not joined (a query per row); full `content_text`, `search_vector` and OCR JSON fetched; `DISTINCT` over all columns | `select_related` + `defer`; `DISTINCT` only for the tag filter | `library/search.py`, `library/views.py` |
| Folder view | Fixed `limit=200`, no further pages | 100 per page, scroll or Load more, requests cancelled on folder/sort change | `frontend/src/pages/Folders.tsx` |
| Frontend size | All screens in one 829 KB file; WhiteNoise served it uncompressed with `max-age=60` | Route and Settings-section splitting, idle prefetch, build-time Brotli/gzip, immutable caching of hashed files, reload once on a missing chunk | `App.tsx`, `lazy.ts`, `pages/Settings.tsx`, `vite.config.ts`, `settings.py` |
| Settings data | One endpoint returned every setting (107 KB) for every section and every save | `?section=` / `?keys=` filters, `?brief=1` saves, stale-while-revalidate section cache | `core/views.py`, `api.ts`, `SettingsForm.tsx` |
| Concurrency | 2 sync gunicorn workers: two slow requests blocked everyone | `deployment/gunicorn.conf.py`: 2 × 4 gthread (measured) | `deployment/*`, `scripts/personaldocs` |
| Dashboard | 4 COUNT queries; full document rows | One conditional aggregate, deferred columns (health summaries stay fresh: a 30 s cache was tried and removed after the backup-health test caught a stale value) | `library/views.py` |
| Folder-tree counts | Sequential scan of documents | Partial index, index-only count | `library/migrations/0012_*` |
| Background contention | No reaction to sustained pressure | Adaptive throttling of non-urgent job starts, bounded | `core/throttle.py`, `core/jobs.py`, scheduler |
| No visibility | No performance data | Request/job/system metrics (aggregated), Performance page, Diagnostic Report | `core/perf.py`, `core/perf_views.py`, `Performance.tsx` |

### Known limitations

- Measured in a 4 vCPU / 16 GB development container (web server pinned to 2 cores); the production-equivalent
  6 GB LXC was not available.
- Thumbnails stay `no-store` (no browser disk cache) on purpose: document images must not persist on shared devices.
- Family members list: one passkey-count query per person remains (family scale).
- Search snippet generation (~70 ms at 8,000 documents) is part of the unchanged search design.
- Cache counters on the Performance page are those of the web process that answered the request.
- `personaldocs rollback` needs the two migrations reversed first (upgrades.md#change-set-x).

## Change set W: named sign-in designs and rotation, complete details and IPs, Notification Detail Level {#change-set-w}

**Numbering.** The change prompt numbered its acceptance tests AT-351…AT-375. Here they are **AT-376…AT-400** (prompt
AT-n → AT-(n+25)); see [TRACEABILITY.md](TRACEABILITY.md#change-set-w). Requirements SD-, ROT-, MD-, IP- and ND- are
in [REQUIREMENTS.md](REQUIREMENTS.md#change-set-w). **Migrations:** `core.0004_notification_detail_level`,
`core.0005_signin_designs`, `core.0006_signin_designs_data` (all additive and idempotent). The existing layout was
kept: the design manager replaces the single design picker in the same card.

### Defect 1: only one sign-in design, and its colours ignored the wallpaper

| | |
| --- | --- |
| Issue | Only one design could exist (a choice of five drawings or one uploaded wallpaper), and the sign-in panel kept the default green colours whatever the wallpaper looked like. |
| Root cause | The design was two settings (`login.design`, `login.wallpaper_file`) rather than an entity, so there was nothing to name, keep, duplicate or rotate. The panel colours were fixed CSS tokens of the sign-in theme; the wallpaper was never analysed. One wallpaper file was used for every screen size with `background-size: cover`, so phones cropped it arbitrarily. |
| Fix | New model `SigninDesign` with assets, focal point, overlay, colour mode, analysis, overrides and palette (`core/designs.py`). Built-ins are protected rows. The wallpaper is validated by content (`branding.process`), the original kept and Desktop/Tablet/Phone derivatives made with `ImageOps.fit` around the focal point. `analyse()` measures the panel-side strip and the bottom strip; `build_palette()` chooses a light or dark panel and adjusts ink, button, muted and link colours until WCAG contrast is met; Custom overrides are kept. The palette is applied as CSS tokens on `.auth` (`Auth.tsx paletteStyle`), the responsive wallpaper through media queries. Activation is atomic and audited and keeps the old settings in step for rollback. Damaged assets fall back to the default with a main-administrator alert; file cleanup is reference-aware; backups include every referenced design file. Rotation (`core/rotation.py`) reuses the backup scheduler's `ops.schedule` (last valid day) and runs from the existing scheduler tick. |
| Files | `backend/apps/core/models.py`, `designs.py` (new), `rotation.py` (new), `design_views.py` (new), `branding.py`, `branding_views.py`, `views.py`, `registry.py`, migrations 0005/0006; `backend/apps/notify/management/commands/scheduler.py`; `backend/apps/ops/bk_engine.py`, `backup.py`; `backend/personaldocs/urls.py`; `frontend/src/pages/Auth.tsx`, `pages/settings/SigninDesigns.tsx` (new), `OverviewAdmin.tsx`, `components/ui.tsx`, `styles.css` |
| Migration / config | `core.0006` creates the built-ins, turns an uploaded wallpaper into **Custom wallpaper** (position → focal point, overlay kept) and keeps the active design. |

### Defect 2: document numbers shown as "••••1234"

| | |
| --- | --- |
| Issue | The owner of a driving licence saw only the last digits of its number in Details, OCR review and notifications. |
| Root cause | `library/services.mask()` was applied to every field marked `SENSITIVE` when serialising, for every viewer, and the masked value was also what the editor started from; notifications masked digit runs in `notify/templates.mask_numbers` independently. Authorisation was already enforced by the document access check, so masking hid data from exactly the people allowed to see it. |
| Fix | `field_json` returns the complete value to anyone who passed the document access check; identifiers are flagged `identifier` instead of being masked. Document history and the audit log store no identifier values at all (`history_value` returns ""; `audit._FORBIDDEN_KEYS` unchanged). OCR proposals keep the complete suggested value; values under 0.7 confidence are flagged `low_confidence` and shown with **Review**; manual corrections are never replaced by a later scan. `DocumentPanel` switches to Details when recognition finishes. Copy copies `f.value` and does not call the server. |
| Files | `backend/apps/library/services.py`, `serializers.py`, `doctypes.py`, `models.py`; `frontend/src/types.ts`, `components/DocumentDetails.tsx`, `components/DocumentPanel.tsx`, `pages/OcrReview.tsx` |

### Defect 3: IP addresses shown as "192.168.x.10" / "public address"

| | |
| --- | --- |
| Issue | Sign-in alerts (e.g. Telegram) and sign-in history did not show the complete IP. |
| Root cause | `security/location.privacy_ip()` shortened private addresses and replaced public ones with a network label; the sign-in API and alert templates used it. |
| Fix | `privacy_ip()` returns the complete IPv4/IPv6 address (or "unknown"); `views_signins` returns `e.ip`. Who may see whose sign-ins is unchanged. |
| Files | `backend/apps/security/location.py`, `alerts.py`, `views_signins.py` |

### Change: Notification Detail Level

| | |
| --- | --- |
| Design | System setting `notifications.detail_level` (Full default, Minimal) and personal `me.notification_detail` (system / full / minimal). `notify/templates.detail_for(user, document)` sets the level and whether the recipient may open the document (`AccessContext.can(doc, VIEW)`) in context variables for the duration of one recipient's rendering. `rich._value` is the single place where every channel's values are formatted: document identifiers and names only when Full **and** allowed, IPs only when Full. Secrets are never part of a notification. |
| Files | `backend/apps/notify/templates.py`, `rich.py`, `expiry.py`, `views.py`; `backend/apps/core/registry.py`, migration 0004; `frontend/src/pages/settings/Account.tsx` |
| Migration | `core.0004` sets **Minimal** where *Include names* had been turned off, otherwise Full. |

### Known limitations

- Delivery to real Email, Telegram, WhatsApp, Discord and Web Push accounts was not executed here (no accounts); the
  shared renderer is covered by unit tests for every channel.
- A design's Desktop, Tablet and Phone versions of a migrated wallpaper are made on first display, not during the
  migration, so the first sign-in page load after the upgrade is slightly slower.
- Search keeps the per-type *searchable* setting for identifiers; this is a search option, not masking.

## Change set V: NAS in Backup Destinations, English sign-in map, tooltips, Help permissions, WhatsApp pairing {#change-set-v}

**Numbering.** The change prompt numbered its acceptance tests AT-331…AT-350. Here they are **AT-356…AT-375** (prompt
AT-n → AT-(n+25)); see [TRACEABILITY.md](TRACEABILITY.md#change-set-v). Requirements NAS-, BQ-, TT-, HLP-, MAP- and
WA- are in [REQUIREMENTS.md](REQUIREMENTS.md#change-set-v). **Migrations:** `ops.0003_nas_into_destinations`,
`security.0005_map_english_labels`, `notify.0005_whatsapp_verification` (all additive; the old `nas.*` settings stay).
The existing layout was kept; the only structural change is the requested NAS consolidation.

### Defect 1: WhatsApp phone stays on "Connecting" and never links

| | |
| --- | --- |
| Issue | After scanning the QR code, the phone showed *Connecting…* indefinitely and Personal DM never became Connected. |
| Root cause | (1) After a successful pair, WhatsApp closes the socket with **515 restartRequired** and expects the client to reconnect using the newly issued credentials. The bridge 1.0.0 close handler returned early for every close while a link was pending without a JID (`if (s.state === "pending" && !s.jid) return;`), so it never reconnected and the phone waited forever. (2) Credentials were written with a 500 ms debounce but a restart re-read them from disk, so a quick restart could start from stale keys. (3) The pinned library (`@whiskeysockets/baileys` 6.7.x) is now tagged *legacy*; the maintained line is 7.x. |
| Fix | New session manager `bridge/whatsapp/session.mjs`: on 515 the bridge flushes the credentials and reopens the socket with the same in-memory auth state; a generation counter ignores events from replaced sockets. One link attempt is valid 5 minutes (`LINK_WINDOW_MS`); WhatsApp rotates the QR every 20–30 s inside it, and a 408 QR timeout reopens the connection within the same window instead of failing. A forced new QR inside the window is refused (409 "still valid for m:ss"); after expiry or a definitive failure it is allowed at once. Stages are reported live; after open the bridge sends a verification message to the person's own chat. Disconnects reconnect with exponential back-off (2 s … 5 min) without a new QR; 401/403/500 → **Relink Required** (credentials wiped, person notified through another channel); 405/411 → **incompatible** (main administrators alerted once a day by email/Telegram). Library: Baileys **7.0.0-rc14**, pinned exactly; no `fetchLatestWaWebVersion` (it spoofs a browser user agent). Admin `/diagnostics`: DNS, HTTPS to web.whatsapp.com with clock skew, storage write probe, sessions (by person), last 50 sanitized events. systemd restarts the bridge after exit 75 (**Restart Bridge**). |
| Files | `bridge/whatsapp/session.mjs` (new), `server.mjs`, `package.json`, `package-lock.json`, `compat.json`, `test/session.test.mjs` (new); `backend/apps/notify/whatsapp.py`, `views.py`, `models.py` + `0005_whatsapp_verification`, `expiry.py`, `event_defs.py`, `catalog.py`, `routing.py`; `deployment/systemd/personaldocs-whatsapp.service`; `scripts/personaldocs`; `frontend/src/components/NotificationRouting.tsx`, `pages/settings/Admin.tsx` |
| Migration / config | `sudo personaldocs whatsapp-bridge update` (sessions archived first; automatic rollback on a failed self-test). Existing links are kept; people who never got past *Connecting* link again. |
| Tests | `bridge/whatsapp/test/session.test.mjs` (10, fake socket: 515 restart, stale-socket events, 5-minute window, 408 renewal, 409 rule, back-off, 401 relink, 411 incompatible, verification, rate limit); CV `test_at370_*` … `test_at373_*`; corrective.mjs "AT-370/AT-371/AT-372", "AT-373" |
| Evidence | Live in this container against real WhatsApp servers (no phone): bridge 1.1.0 obtained QR codes, kept one attempt open for 300 s (11 codes, one 408 renewal at 162 s), ended with *link expired*; diagnostics DNS/network/clock/storage OK. Screenshots `whatsapp-linking.png`, `whatsapp-verified.png`, `whatsapp-diagnostics.png` (fake bridge, no QR). |
| Limitation | **A real phone pairing (prompt AT-344 = AT-369) was not executed: no phone or WhatsApp account is available here. Blocked / Not Executed.** A single QR picture cannot stay valid for 5 minutes: WhatsApp's protocol rotates it; the 5-minute window applies to the link attempt. |

### Defect 2: Storage & NAS separate from Backup Destinations

| | |
| --- | --- |
| Issue | The NAS was set up under Settings → Storage & NAS and then added again as a destination (two places, two states). |
| Root cause | Historical: the NAS mount helper (Change Set E) predates encrypted destinations (Change Set T); T only linked to it. |
| Fix | NAS fields live in the destination editor (SMB / NFS / Already mounted); the SMB password is write-only (empty keeps the stored one). One Personal-DM-managed share; further shares are *Already mounted*. **Test Connection** drives the root mount helper and reports a category (DNS, reachability, authentication, share, mount not allowed, client tools, write permission, capacity). The Storage tab is removed, `/settings/storage` redirects to Destinations, the integrity check moved to Security Center → Storage, legacy settings to the Overview, recovery validation to Policies. Migration `ops.0003` (`nas_migration.run`) is idempotent and non-destructive; failures become **Needs Attention** with Edit Configuration / Test Connection / **Retry Migration**. Capacity thresholds 20 % / 10 % (per destination override) with one alert per destination, level and day. |
| Files | `backend/apps/ops/nas_migration.py` (new), `migrations/0003_nas_into_destinations.py` (new), `bk_views.py`, `bk_engine.py`, `bk_destinations.py`, `nas_helper.py`, `core/registry.py`, `personaldocs/urls.py`; `frontend/src/pages/settings/Backup.tsx`, `Admin.tsx`, `SecurityCenter.tsx`, `pages/Settings.tsx` |
| Tests | CV `test_at356_*` … `test_at359_*`; `tests/test_nas.py`; corrective.mjs "AT-356/AT-374", "AT-358" |
| Limitation | **No real SMB/NFS server here**: mounting is exercised with the faked helper (`tests/test_nas.py`). Blocked / Not Executed against a real NAS. |

### Defect 3: no per-destination Backup Now, concurrent backup jobs

| | |
| --- | --- |
| Root cause | Backup jobs were ordinary jobs; two could be claimed at once and the second failed on the backup lock, and a manual job could start before an older scheduled one. |
| Fix | `jobs.handler(..., serial=True)`: while a serial job runs no other serial job is claimed; otherwise only the oldest due serial job may start (FIFO by creation time; priority cannot jump it). Jobs are database rows, so the queue survives navigation, sign-out and restarts. **Backup Now** (confirmation required, duplicate → 409) makes a Full, full-system point stored on that destination only and reports Preparing → Backing Up → Verifying → Completed / Failed. No Cancel action. |
| Files | `backend/apps/core/jobs.py`, `ops/bk_views.py`, `ops/bk_engine.py`; `frontend/src/pages/settings/Backup.tsx` |
| Tests | CV `test_at360_*`, `test_at361_*`; corrective.mjs "AT-360/AT-361" |

### Defect 4: tooltips clipped

| | |
| --- | --- |
| Root cause | `.tip-pop` was `position: absolute` inside its trigger, always above it; cards, tables and dialogs with `overflow: hidden/auto` clipped it, and near the top or sides it left the viewport. |
| Fix | One shared `HelpTip`: rendered into `document.body` (portal), `position: fixed`, measured placement that flips below/above and shifts horizontally to stay 8 px inside the viewport, follows scroll and resize, closes on Escape and outside tap, stays open on tap (touch), `role=tooltip` + `aria-describedby`. Text comes from `helpRegistry.ts` by id; **Learn more** appears only when the person may open that guide. A test fails if an id used in the code is missing from the registry or a registry link points to a missing heading. |
| Files | `frontend/src/components/ui.tsx`, `helpRegistry.ts` (new), `styles.css` |
| Tests | CV `test_at362_*`, `test_at363_*`; corrective.mjs "AT-362/AT-363" (desktop table, dialog, phone tap; viewport bounds, topmost element, ARIA) |

### Defect 5: Help not permission-aware

| | |
| --- | --- |
| Root cause | `/api/help` listed and searched every guide and `/api/help/<slug>` returned any guide; only the index labelled an audience. |
| Fix | `core/help_access.py`: guide audiences (all, delegate, admin, main_admin, maintainer) and `<!-- audience-section -->` blocks. The server filters the index, categories, search and excerpts, guide text and direct URLs (404 = same as missing), and unlinks links to unreadable guides; checked per request. Admin procedures inside everyday guides (console commands, provider settings, bridge updates) are in main-administrator sections. |
| Files | `backend/apps/core/help_access.py` (new), `core/views.py`; `docs/guides/*.md` (audience markers); `frontend/src/pages/Help.tsx` |
| Tests | CV `test_at364_*`, `test_at365_*` (incl. "no `sudo` line visible to a family member"); corrective.mjs "AT-364/AT-365" |
| Limitation | Screenshot files under `/api/help/asset/` are served to any signed-in person (they contain only synthetic data). |

### Defect 6: sign-in map labels in Arabic; no details, clustering or filters

| | |
| --- | --- |
| Root cause | OpenStreetMap standard tiles are pre-rendered images labelled in the local language; a raster tile cannot be relabelled. CARTO's English raster tiles now require an API key. |
| Fix | Default provider **OpenFreeMap** (`tiles.openfreemap.org/styles/liberty`, OpenStreetMap vector tiles, no key, attribution shown): MapLibre GL 5.6.2 (CSP build, worker from `'self'`, no `blob:`/`eval`) inside Leaflet via `@maplibre/maplibre-gl-leaflet`; every text layer uses `coalesce(name:en, name_en, name:latin, name)`. Without WebGL → OSM raster fallback with a note. Markers: hover = person, IP, zone/place; click/tap = details panel (time, method, IP, place and source, network, zone, device, browser, OS, device state, risk and reasons). Pixel clustering (34 px, recomputed on zoom) with counts and the worst risk colour. One filtered dataset for map and list (Today / 7 / 30 / 90 / 365 days / custom; person, trust/zone, risk, device; default 7 days); list rows select markers and vice versa; *Location unavailable* badge. Scope enforced by the server (unchanged). |
| Files | `backend/apps/security/mapprov.py`, `views_signins.py`, `migrations/0005_map_english_labels.py` (new); `frontend/src/components/SigninMap.tsx`, `MapUnavailable.tsx`, `pages/settings/Signins.tsx`, `vite.config.ts`, `package.json` |
| Tests | CV `test_at366_*` … `test_at368_*`; corrective.mjs "AT-366", "AT-367/AT-368" (style answered locally); screenshots.mjs uses the real OpenFreeMap service |
| Limitation | Not tested from the production address. OpenFreeMap is a free community service without an SLA; MapTiler/Stadia/custom remain available. |

## Change set U: corrective fixes for the folder tree, sign-in map, sign-in designs, WhatsApp and Discord {#change-set-u}

**Numbering.** The change prompt numbered its acceptance tests AT-311…AT-330. Here they are **AT-336…AT-355** (prompt
AT-n → AT-(n+25)); the mapping is in [TRACEABILITY.md](TRACEABILITY.md). Requirements FT-, MP-, SD- and CN- are in
[REQUIREMENTS.md](REQUIREMENTS.md). **No database migrations.** Two settings were added (`security.map_provider`,
`security.map_api_key`); everything else is code. Users, documents, permissions, settings, backups, Trusted Zones and
existing notification channels are untouched.

### Defect 1: folder tree rows out of line

| | |
| --- | --- |
| Issue | Expanders, icons and names did not line up between levels, and rows without children were shifted (screenshot from the field). |
| Root cause | Change Set T added `.tree button { width: 100%; text-align: left }` for the Recovery Explorer's folder list. The folder tree also has the class `tree`, so its expander buttons were stretched across the row; rows without an expander had no placeholder. |
| Fix | The Recovery Explorer rule is scoped to `.rp-folders`. Every tree row is a CSS grid with fixed columns (expander, icon, name, extras) built from shared tokens (`--tree-indent`, `--tree-expander`, `--tree-icon`, `--tree-gap`, `--tree-line`). A row without children keeps an empty expander slot. Names wrap inside their column (`overflow-wrap: anywhere`) and the row aligns to the first line. No pixel nudges and no per-folder offsets. |
| Files | `frontend/src/styles.css`, `frontend/src/pages/Folders.tsx`, `frontend/src/pages/Recovery.tsx` |
| Migration / config | None |
| Tests | corrective.mjs "AT-336/AT-337/AT-338" (3 viewports × 5 themes, geometry measured per row), "AT-336 … right-to-left", "AT-339" (keyboard); layout.mjs; a11y.mjs |
| Evidence | `docs/images/screenshots/folders-tree.png`; `tests/e2e/out/corrective/tree-*.png` |
| Limitation | Measured in Chromium only. |

### Defect 2: sign-in map shows "403 Access blocked" tiles

| | |
| --- | --- |
| Issue | Every map tile showed OpenStreetMap's "Access blocked" picture. |
| Root cause | The site sends `Referrer-Policy: same-origin` for every response (Django `SECURE_REFERRER_POLICY`), so the browser sent tile requests to `tile.openstreetmap.org` **without a `Referer`**. The OpenStreetMap tile usage policy blocks requests without a valid Referer and answers HTTP 403 with an image, which Leaflet drew as tiles. There was no way to choose another provider and nothing told the administrator what had happened. |
| Fix | Tiles and the test request use `strict-origin-when-cross-origin`, so the provider sees only this site's origin (no path, no query). This is the browser's normal, truthful header: no spoofing, no proxying, no scraping. The provider is configurable: OpenStreetMap (low volume), MapTiler or Stadia Maps with the administrator's own key, or a custom/self-hosted server. A one-tile probe runs before the map; if it fails (401, 403, 429, network), the map shows **Map unavailable** with the reason and the fix. Tiles are never retried in a loop: after 4 failures and no successes the layer is removed. **Test Map Provider** (main administrator) records the result, the status and the time (audited, without the key). The Content-Security-Policy allows only the configured tile origin for `img-src` and `connect-src`, and is updated as soon as the setting changes. Sign-in addresses are never sent to the tile server. |
| Files | `backend/apps/security/mapprov.py` (new), `views_signins.py`, `core/middleware.py`, `core/views.py`, `core/registry.py`, `ops/.../doctor.py`, `personaldocs/urls.py`; `frontend/src/components/MapUnavailable.tsx` (new), `SigninMap.tsx`, `pages/settings/Security.tsx`, `Signins.tsx` |
| Migration / config | Settings only. A custom tile address set earlier is detected and keeps being used (provider "Custom"). Proxies that set their own CSP must allow the tile origin in `img-src` and `connect-src`. |
| Tests | CU `test_at340_*`, `test_at341_*`, `test_at342_*`, `test_at343_*`; corrective.mjs "AT-340", "AT-341/AT-342" ×4, "AT-343" (tiles intercepted with `page.route`: no request reaches a real provider) |
| Evidence | `security-map-provider.png`, `security-map-unavailable.png`; `tests/e2e/out/corrective/map-unavailable-403.png` |
| Limitation | Not tested against real OpenStreetMap, MapTiler or Stadia from a production address. A tile server without CORS headers cannot report a status to the test (shown as *No status*, not as a failure). |

### Defect 3: sign-in design thumbnails nearly black

| | |
| --- | --- |
| Issue | Under the Dark and Glass themes the sign-in design thumbnails in Settings → Overview & sign-in were almost black. |
| Root cause | (1) The wallpaper layer (`.auth-wallpaper { z-index: -2 }`) inside a thumbnail without its own stacking context was painted *behind* the card background. (2) The drawings use theme variables, so they took the administrator's own (dark) theme colours. (3) The sign-in page itself inherited the last user's theme from the browser's local storage. |
| Fix | Thumbnails isolate their stacking context. The sign-in page, the thumbnails and both previews always use the sign-in theme (`SIGNIN_THEME`, Default Green). Choosing a design now previews it; **Save design** publishes it and **Discard** drops it. There is a **Live sign-in preview** (Desktop or Phone) and a large **Preview Sign-in Page**. |
| Files | `frontend/src/pages/Auth.tsx`, `pages/settings/OverviewAdmin.tsx`, `styles.css` |
| Migration / config | None. The saved design and every person's theme are kept. |
| Tests | CU `test_at345_*`; corrective.mjs "AT-344" (mean luminance and contrast of every thumbnail in 5 themes, identical across themes), "AT-345/AT-346"; parity.mjs sign-in steps; `test_overview.py` AT-128…AT-130 |
| Evidence | `settings-login-design.png`; `tests/e2e/out/corrective/designs-dark-theme.png`, `preview-phone.png` |
| Limitation | Chromium only. |

### Defect 4: WhatsApp Personal shown as "Planned"; WhatsApp and Discord could not be turned on

| | |
| --- | --- |
| Issue | With the bridge installed and running (`whatsapp-bridge 1.0.0 (protocol 1) on 127.0.0.1:8095`), Settings → Connections still said *WhatsApp — Planned*, and there was no switch to turn it on. |
| Root cause | A hard-coded "Planned" card left over from before Change Set T. The Connections panel lists its settings explicitly and `discord.enabled`, `whatsapp.enabled` and `whatsapp.bridge_url` were never added to it, so nobody could enable either channel, although the CLI says "turn it on in Settings → Connections". The bridge status also returned "disabled" without asking the bridge when the switch was off. |
| Fix | New `GET /api/admin/connections` (main administrator): a card per provider with its real state (Connected, Configured, Disabled, Available but not configured, Degraded, Not installed) and counts only. `whatsapp.service_status()` checks installation, systemd state, reachability, version, protocol, tested versions and update, also while the switch is off (*Installed and running – turned off*). New administrator sections for Discord and WhatsApp Personal with their switches and the bridge service table. People see **Disabled by Admin** or **Service unavailable**, the QR code refreshes by itself, Reconnect and Unlink, and their last notification. The routing matrix explains why a chosen channel cannot deliver. |
| Files | `backend/apps/notify/whatsapp.py`, `notify/views.py`, `personaldocs/urls.py`; `frontend/src/pages/settings/Admin.tsx`, `components/NotificationRouting.tsx`, `styles.css`; `tests/fake_whatsapp_bridge.py` (standalone mode for the browser tests) |
| Migration / config | None. Discord and WhatsApp stay off until the administrator turns them on; saved webhooks and links are kept. |
| Tests | CU `test_at348_*` … `test_at353_*`; corrective.mjs "AT-348/AT-349", "AT-348", "AT-350", "AT-351", "AT-352/AT-353" (fake bridge started by `scripts/e2e.sh`); `test_notification_channels.py` |
| Evidence | `connections-whatsapp.png`, `notifications-channels.png` |
| Limitation | A real phone scanning a real QR code and a real Discord server were not available (Not Run). The browser tests use an obviously fake QR. |

## Change set T: encrypted backup and recovery, notification routing, sign-in security, rich guides {#change-set-t}

**Numbering.** The change prompt numbered its acceptance tests AT-251…AT-310. Here they are **AT-276…AT-335** (prompt
AT-n → AT-(n+25)); the mapping is in [TRACEABILITY.md](TRACEABILITY.md#change-set-t-2026-10-encrypted-backup-and-recovery-notification-routing-sign-in-security-rich-guides).
Decisions: [ADR 0020](adr/0020-encrypted-recovery-points.md), [ADR 0021](adr/0021-notification-routing-channels.md),
[ADR 0022](adr/0022-trusted-zones-signin-map-risk.md).

**Investigation (before implementing).**

| Area | What was there before | What was missing |
| --- | --- | --- |
| Backup | One plain folder backup per run on one NAS share (database dump, originals, settings, optional key), daily/weekly/monthly | Encryption, incrementals, several destinations, deep verification, granular restore, fresh-server recovery |
| Restore | Console `personaldocs restore DIR` onto an installed system | Recovery onto a clean server; impact analysis; per-person restore |
| Notifications | Per-event channel matrix: in-app, email, Telegram, push; WhatsApp "planned" | Per-category routing, fallback, quiet hours, digests, Discord, WhatsApp |
| Sign-in records | IP, country (GeoIP), device, method; home network shown as "Unknown country" | Trusted Zones, map, risk with reasons, recognised devices |
| Help | Flat list of guides, plain Markdown, few screenshots | Categories, navigation, callouts, screenshots next to the steps, link checking |

**Implemented.**

- **Backend:**
  - `apps/ops`: models (0001), settings migration (0002), and the modules `bk_crypto`, `bk_keys`, `bk_destinations`,
    `bk_engine`, `bk_validation`, `bk_restore`, `bk_rotate`, `bk_recover`, `bk_integrations` and `bk_views`;
  - `manage.py recover` and `manage.py backup` (rewritten);
  - doctor checks.
- **Notifications:** route categories, Outbox routing fields, `routing.py`, `discord.py`, `whatsapp.py`, sandbox mode
  and the integration hold.
- **Security:** `location.py` (Trusted Zones, local GeoIP, risk), the `RecognizedDevice` model with the device cookie,
  the sign-in map API with scope checks, and Mark Unrecognized.
- **Frontend:**
  - Settings → Backup & Recovery, the Recovery page, step-up dialogs;
  - notification routing, Discord and WhatsApp cards, My deliveries and Delivery health;
  - My account → Sign-in security, Trusted Zones and the sign-in map (Leaflet);
  - the Help navigation and callouts.
- **Operations:**
  - installer option *Recover Existing Installation*;
  - `personaldocs recover`, `backup run|list|health|verify` and `whatsapp-bridge …`;
  - `personaldocs-whatsapp.service`;
  - upgrade pre-backup with `--pre-change`.
- **Docs:**
  - 5 new guides and 2 rewritten (backup and restore, notifications);
  - `scripts/check_docs.py`, run in `verify.sh` and pytest;
  - 15 new screenshots;
  - ADRs 0020–0022.

**Not verified here (needs real accounts or hardware).** These are recorded in TEST_REPORT as Not Run or Requires Real
Account, never as passed:

- a clean Debian 13 LXC recovery drill;
- live NAS, S3, Google Drive and OneDrive destinations and bootstrap recovery;
- linking a real WhatsApp phone and a live bridge update;
- a real Discord server;
- Firefox and Safari.

## Change set S: offline access, PWA identity, premium themes, public screenshots {#change-set-s}

**Numbering.** The change prompt called this "Change Set R" with AT-226…AT-250; here it is **Change Set S** with
**AT-251…AT-275** (prompt AT-n → AT-(n+25); mapping in [TRACEABILITY.md](TRACEABILITY.md)). Decisions:
[ADR 0018](adr/0018-offline-device-scope.md), [ADR 0019](adr/0019-theme-tokens-glass.md).

**Investigation (before implementing).**

| Area | What was there before | What was missing |
| --- | --- | --- |
| Offline | Per-document only: a localStorage index and a Cache Storage bucket per account; revocation through `/api/offline/validate`; removed at sign-out unless "keep" | Folders, devices, update handling, server policy |
| Service worker | Caches only the app shell; never API answers or files (unchanged) | — |
| Manifest | Correct basic fields | `id`; maskable icons for small sizes |
| Apple icon | Pointed at the 192 px icon | No Apple title |

Further findings:

- The SPA catch-all answered `/apple-touch-icon.png`, `/apple-touch-icon-precomposed.png` and `/favicon.ico` with
  `200 text/html`.
- WhiteNoise served the manifest as `application/octet-stream`.
- Themes swapped five brand variables; 165 colour literals in `styles.css` (white surfaces everywhere).
- Public screenshots: 50 images, all at 1×, mixed 1366/1440 widths. Four (login audit, Local AI, security access,
  passkeys) had no capture script left and showed older UI.

**iPhone "A" icon.** The physical device could not be tested here. Defects that produce exactly this symptom were
found and fixed:

- HTML answered for the conventional Apple icon paths;
- no Apple title or 180 px icon.

Also documented: a proxy that requires sign-in for icon files gives the same symptom (now checked by `check-access`).
iOS keeps old shortcut icons, so a fresh install is required.

**Implemented.**

- Backend:
  - `apps/library/offline.py` (devices, estimate, selections, sync, admin);
  - models `OfflineDevice`, `OfflineSelection`, `User.offline_allowed`;
  - 7 settings in section *Offline & PWA*;
  - session payload `offline`;
  - 404 for missing file paths;
  - manifest MIME type;
  - doctor and check-access icon checks.
- Frontend:
  - `offline.ts` sync engine;
  - `components/OfflineUI.tsx` (menus, dialog, badges, tree marker);
  - `pages/Offline.tsx`;
  - `pages/settings/OfflineAdmin.tsx`;
  - `components/ThemeGallery.tsx`;
  - token-based `styles.css` with the Dark, Glass Light and Glass Dark presets;
  - `theme-hint.js` and theme-color.
- Icons: `public/icon.svg` (master) and generated PNG/ICO by `scripts/make_icons.mjs`.
- Tests:
  - `tests/test_offline_sync.py` (9) and `tests/test_pwa_identity.py` (4);
  - `tests/e2e/offline.mjs` (9 steps), `pwa.mjs` (4), `themes.mjs` (6), `screenshots.mjs` (5);
  - `a11y.mjs` in 6 themes;
  - `parity.mjs` screenshots through `snap()` (2×, 1440×900, privacy gate).

**Not run here (need real devices or platforms):**

- iPhone/iPad Add to Home Screen;
- Android and desktop installs;
- offline behaviour on a real phone;
- glass performance on low-end phones;
- browsers other than Chromium.

These are on the release checklist.

**Next step:** the release checklist items above on a real Debian 13 LXC and devices.

## Change set R: UI alignment, responsive layout and visual regression {#change-set-r}

**Numbering.** The change prompt called this "Change Set Q" with AT-211…AT-225. Those numbers belong to the PaddleOCR
change set, so it is **Change Set R** with **AT-231…AT-245** (prompt AT-n → AT-(n+20); mapping in
[TRACEABILITY.md](TRACEABILITY.md)). Decision record: [ADR 0017](adr/0017-ui-layout-primitives.md). Rules for
contributors: [UI layout rules](guides/ui-layout.md).

**Root cause of the screenshot defect.** The document header was a wrapping flex row:

- the title block was `.grow` = `flex: 1`, so `flex-basis: 0`;
- next to it sat an actions row of four non-wrapping buttons (about 520 px).

Flexbox wraps only when the items' basis sizes don't fit. With a basis of 0 the row never wrapped, so the buttons
kept their width and the title got the rest. Reproduced with synthetic documents at 1920×1080: pane 746 px, title
**192 px**, a long name on 6 lines. The metadata row (badges, shield, "file · size · v1") was squeezed the same way.

A second cause: responsive rules depended on the window width, so a narrow pane on a wide screen got the desktop
layout. In tablet portrait the preview pane was **273 px**, next to the folder tree, with the four buttons stacked
one per line.

**Fix (shared rules, no pixel nudges):**

- **Flex basis.** `.row > .grow` and `.list-item > .grow` get a 12 rem basis, and list rows may wrap, so actions and
  badges wrap instead of squeezing text.
- **Reusable header.** `.doc-header` / `.doc-header-main` / `.doc-actions`, `.doc-badges` (status badges as one
  group; antivirus shown as a labelled badge) and `.doc-meta` (separators stay with the preceding item; long names
  wrap anywhere).
- **Container queries** on the preview pane, full page and viewer:
  - actions take their own row below 60 rem;
  - icon buttons with accessible names below 34 rem;
  - a one-row scrolling viewer toolbar below 34 rem.
- **Responsive modes.** Three panels only from 1280 px, otherwise an open document gets the full width. List and
  preview share the width equally.
- **Other components.** Settings rows switch to one column when two 16 rem columns don't fit; help tables keep
  9 rem columns and scroll sideways; headings use `overflow-wrap: break-word`.

**After the fix:**

- the title gets the full pane width at every viewport (713 px of 746 at 1920×1080);
- normal names fit on one line;
- the tablet-portrait pane is 513 px.

Before/after images are in `docs/images/layout/`.

**Global audit.** `tests/e2e/layout.mjs` covers 27 screens at 7 viewports:

- login / passkey (through the parity suite), Overview, Folders, the list view, document preview and the full page;
- search, shared, offline, archive, OCR review, notifications;
- settings: family, account security, document types, OCR & processing (engines, existing OCR data, test/compare),
  notification policy;
- every Security Center view (overview, antivirus, security test, OS updates, firewall, records, storage, access
  policy);
- help.

Defects found outside the reported screen and fixed:

- document list cards: name and details squeezed to 61 px beside the badges at 1366 px;
- the shared, search and archive lists: the same, 38 px at 430 px;
- the tab-bar note "No details yet": 42 px;
- the Overview date widget;
- settings label columns on tablets;
- help table columns;
- the ⋮ menus closing when opened after a page scroll (fixed in Change Set Q).

The list view and grid views are covered through the Folders screens. The details/table view and the thumbnail
grid were not separately audited with long names: **Not Run**.

**Not tested here:**

- browsers other than Chromium;
- an installed PWA on real phones and tablets (AT-241);
- real right-to-left application UI (not supported by design).

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
| AT-302 clean-server recovery (Change set T) | A clean Debian 13 LXC: installer → *Recover Existing Installation* from a real USB/NAS copy, in Normal and Compromise mode (tested here by restoring the real PostgreSQL test database from encrypted points, and by the stubbed installer test) |
| AT-303/304 live destinations | A NAS share, an S3-compatible bucket (MinIO or a provider), and Google Drive and OneDrive accounts with OAuth apps (local destinations, a SigV4 known-answer test and mocked HTTP only) |
| AT-313/315 real WhatsApp | A test phone to link by QR through the bridge, and a live `whatsapp-bridge update` / `rollback` (bridge self-test and a fake bridge only) |
| AT-317 real Discord | A Discord server with a webhook (mocked HTTP only) |
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
