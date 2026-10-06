# Traceability matrix

Status key: **Done** means implemented with automated tests passing. **Partial** means implemented but some aspect is untested or simplified (see notes). **Pending-env** means implemented, but validation needs an environment or credential that was not available. All test results are from the run recorded in [TEST_REPORT.md](TEST_REPORT.md).

## Acceptance scenarios

| ID | Scenario (abridged) | Code | Tests | Docs | Status |
|---|---|---|---|---|---|
| AT-01 | Setup creates six real-name accounts; Dad is admin and head; rerun does not duplicate | `accounts/services.py::complete_setup`, `pages/Setup.tsx` | `test_setup_accounts::test_at01_*`, `test_setup_requires_valid_token*`, e2e step 1 | guides/setup.md | Done |
| AT-02 | Grandparents and sibling groups; heads; scoped delegates; no escalation or cross-group access | `library/permissions.py`, `accounts/services.py::set_delegation, check_membership_escalation` | `test_permissions::test_at02_*` | guides/extended-family.md | Done |
| AT-03 | Inheritance, exceptions, moves and revocation across API, previews, OCR, snippets, versions, saved views, exports, shares | `permissions.py`, `views.py::get_doc`, `search.py`, `export.py`, `views_share.py::_lookup` | `test_permissions::test_at03_*, test_inheritance_*, test_folder_move_*`, `test_documents::test_at18_*` (creator loses permission), `test_processing::test_at11_*` | guides/extended-family.md | Done |
| AT-04 | Browser mapping of old names to confirmed accounts; deep paths kept; shared/unmapped need explicit treatment | `library/imports.py`, `views_import.py`, `pages/ImportWizard.tsx` | `test_imports::test_at04_*`, `test_regular_user_cannot_map_*` | guides/folder-imports.md | Done (browser folder picker not run in e2e) |
| AT-05 | Server import leaves source unchanged; rejects escape and outside symlinks; resumes without duplicates | `imports.py::scan_server, import_server_job, import_item` | `test_imports::test_at05_*` (2 tests) | guides/folder-imports.md#server | Done |
| AT-06 | Two identical uploads stay separate; colliding names never overwrite | `storage.py`, `services.py::_commit_version` | `test_documents::test_at06_*` | guides/folder-imports.md#duplicates | Done |
| AT-07 | Image-only PDF becomes searchable; original byte-identical; PDF/A validated; unsupported is honest | `processing.py` | `test_processing::test_at07_*`, `test_image_upload_is_ocrd`, `test_born_digital_*`, `test_documents::test_uploaded_executable_*` | guides/ocr-corrections.md | Done (PDF/A-2b validated by veraPDF 1.30.2 in tests; built-in structural check when veraPDF is absent — `test_pdfa`) |
| AT-08 | Discrepancies go to review; confirmed corrections change naming and reminders; manual entry when extraction fails | `extraction.py`, `services.py::apply_confirmed_fields` | `test_processing::test_mrz_*, test_labelled_*, test_at08_*`, `test_documents::test_impossible_dates_*`, `test_expiry::test_proposed_dates_never_*` | guides/ocr-corrections.md | Done |
| AT-09 | Renewals separate with confirmed year ranges; improved scans use versions | `services.py::create_document(renews), add_version, generated_title` | `test_documents::test_at09_*`, e2e step 6 | guides/originals-versions.md | Done |
| AT-10 | Office previews local, originals kept; DICOM export keeps paths and hashes; executables never run | `processing.py::_office_to_pdf`, `export.py` | `test_processing::test_at10_*` (2), `test_documents::test_uploaded_executable_*` | guides/office-dicom.md | Done |
| AT-11 | Filtering, autocomplete, highlights, saved views and similarity without leaks | `search.py` | `test_processing::test_at11_*`, `test_born_digital_*`, `test_permissions::test_at03_*` | guides/search.md | Done |
| AT-12 | Three-panel and full-page views, per-user themes on desktop and mobile; independent choices | `pages/Folders.tsx`, `Lists.tsx::DocumentPage`, `styles.css`, `me.theme` | e2e steps 5, 10, 12; `test_ops::test_settings_api_*` | guides/themes.md | Done: e2e flow + automated axe audit in all themes (`tests/e2e/a11y.mjs`); full-page layout preference not covered by e2e |
| AT-13 | Emoji suggestions and overrides persist and never change access | `services.py::suggest_emoji`, `views.py::folder_detail` | `test_documents::test_at13_*` | guides/folder-imports.md#emoji | Done |
| AT-14 | PWA installable, camera/file upload, native sharing, tested fallbacks | `manifest.webmanifest`, `sw.ts`, `UploadDialog.tsx`, `DocumentPanel.tsx::ShareDialog`, `UploadShared.tsx` | e2e step 12 (manifest checks, mobile viewport) | guides/mobile-pwa.md | Pending-env: real Android/iOS install, share sheet and camera not tested |
| AT-15 | Offline saves and export; quota, restart, account switch, revocation on reconnect; limits explained | `offline.ts`, `export.py` | `test_ops::test_export_*` (2), `test_offline_revalidation_*`, `test_processing::test_at10_dicom_*` | guides/offline-export.md | Partial: browser-side cache, quota and account-switch behaviour implemented but not automated |
| AT-16 | Frozen-clock reminders: thresholds, timezone, correction, expiry-day stop, head change, duplicates, retry, restart | `notify/expiry.py`, `scheduler.py` | `test_expiry` (8 tests) | guides/expiry-rules.md | Done |
| AT-17 | Required channels; visible missing details; SMTP/Telegram delivery and failures without document numbers | `expiry.py::channels_for, channel_issue, deliver_outbox`, `notify/views.py` | `test_expiry::test_at17_*, test_email_and_telegram_*, test_telegram_linking_*` | guides/expiry-rules.md#channels, smtp.md, telegram.md | Done with mocks; Pending-env: real SMTP server and Telegram bot |
| AT-18 | Link expiry, password, revoke and archive behaviour; brute force rate-limited | `views_share.py` | `test_documents::test_at18_*, test_at23_*` | guides/sharing.md | Done |
| AT-19 | Personal IMAP imports to writable folders only; idempotent polls and retries; private credentials | `mailimport/imap.py`, `views.py` | `test_mailimport` (3 tests, IMAP test double) | guides/settings.md, Account → Email imports | Done with test double; Pending-env: real mailbox |
| AT-20 | Single-use expiring resets; TOTP and backup codes; restricted, audited console recovery | `accounts/views.py`, `services.py`, `recover_admin.py` | `test_auth::test_password_reset_*` (2), `test_totp_*`, `test_admin_resets_*`, `test_console_recovery_*`, `test_setup_accounts::test_forced_password_change_*` | guides/totp-recovery.md | Done |
| AT-21 | Google enable/configure, link after verification, sign in to the same account, unlink; unknown users cannot register | `accounts/google.py`, Settings → Authentication, Account → Linked | `test_auth::test_at21_*` (2), `test_google_link_requires_recent_verification` | guides/google.md | Done (protocol tests with a local RSA key); Pending-env: live Google login |
| AT-22 | Wrong issuer, audience, nonce or state; duplicate identity; disabled provider or user; TOTP bypass all fail safely | `google.py::verify_id_token, handle_callback` | `test_auth::test_at22_*` | guides/google.md#troubleshooting | Done |
| AT-23 | Archive retains indefinitely; admin-only restore and purge; archived items leave links and reminders | `services.py::archive_*`, `ArchivePage` | `test_documents::test_at23_*`, `test_expiry::test_renewed_and_archived_*` | guides/archive.md | Done |
| AT-24 | NAS outage detected; consistent backup; restore recovers accounts, permissions, originals, versions, settings and secrets | `ops/backup.py`, `restore.py` | `test_ops::test_at24_*` (2, including a full restore round trip), `test_backup_now_requires_*` | guides/backup-restore.md | Partial: round trip verified in place on PostgreSQL 16; restore into a separate clean Debian 13 LXC not performed |
| AT-25 | Integrity checker finds missing and corrupt files; repair keeps originals and keys | `ops/integrity.py` | `test_ops::test_at25_*` | guides/backup-restore.md#integrity | Done |
| AT-26 | Native fresh install, interrupted rerun, upgrade success/failure, rollback and repair on Debian 13 | `scripts/personaldocs`, `scripts/easy-install.sh`, `scripts/proxmox-create-lxc.sh`, `deployment/systemd/*` | `bash -n` and shellcheck in verify.sh; installer dry runs; `tests/test_nas.py` (NAS helper with simulated systemctl) | guides/installation.md, upgrades.md | Pending-env: no Debian 13 LXC with systemd was available |
| AT-27 | Load measured under 2 vCPU / 4 GB; disk-full and worker crash keep committed data | `jobs.py` (leases), `storage.check_disk_space`, `sandbox.py` limits | `test_ops::test_job_lease_*, test_heavy_jobs_*`; benchmark in TEST_REPORT | ARCHITECTURE.md | Partial: measured on a 4 vCPU / 15 GB host; disk-full not simulated |
| AT-28 | Settings have descriptions, tooltips, working help links, permissions, defaults and matching docs | `core/registry.py`, `SettingsForm.tsx` | `test_ops::test_at28_*, test_settings_reference_*, test_settings_api_*, test_help_*` | SETTINGS_REFERENCE.md | Done |
| AT-29 | Audit without secrets; direct object access and malformed input do not leak | `core/audit.py` | `test_ops::test_at29_*, test_malformed_*, test_health_*`, `test_permissions::test_cross_family_*`, `test_documents::test_document_number_is_masked_*` | guides/settings.md#activity | Done |
| AT-30 | No credentials, real documents, databases or private reference files in the repository or release; private update flow tested | `.gitignore`, `scripts/verify.sh` hygiene step | verify.sh | private-github.md | Partial: hygiene automated; private update flow pending (AT-26) |

## Other requirements

| Req | Implementation | Tests | Status |
|---|---|---|---|
| DEP-2 proxy | `settings.py` (`PD_BEHIND_PROXY`, `TRUSTED_PROXY_IPS`), range requests in `views.py::_stream`, gunicorn `--forwarded-allow-ips` | `test_documents::test_original_is_byte_identical_*` (range) | Done; NPM/Pangolin config documented, not live-tested |
| DEP-4 private GitHub | `scripts/personaldocs::git_auth` (credential helper reading a 0600 file; SSH deploy key option) | — | Pending-env |
| ACC-3 last admin | `services.guard_last_admin` | `test_last_main_admin_*` | Done |
| LIB-7 bulk edit | `views.py::documents_bulk` | `test_bulk_edit_*` | Done (standard and typed custom fields editable in the details pane) |
| UI-5 help | `core/views.py::help_*`, `ui.tsx::renderMarkdown` (escapes HTML, restricts link schemes) | `test_help_*`, e2e step 11 | Done |
| OPS-1 mount detection | `backup.check_target` (mount point + marker) | `test_at24_backup_detects_*` | Done |
| OPS-4 audit retention | `scheduler.tick` | — | Implemented; untested |
| OPS-5 upgrade/rollback | `cmd_upgrade`, `schema_compatible`, `cmd_rollback` | — | Pending-env |

## Additions (2026-10-04)

| Feature | Implementation | Tests | Docs | Status |
|---|---|---|---|---|
| Resizable panels | `components/PanelResizer.tsx`, `styles.css` | `a11y.mjs` keyboard resize + persistence | guides/themes.md#resize | Done |
| Per-device sessions | `accounts/sessions.py`, `UserSession`, `me/sessions` API, Security tab | `test_sessions` (5) | guides/totp-recovery.md#sessions | Done |
| Folder templates | `registry.documents.member_template`, `services.apply_template`, setup/member/folder actions | `test_templates` (5) | guides/folder-imports.md#templates | Done |
| Event notifications | `notify/events.py` (access, import, processing, backup, integrity) | `test_events` (6) | guides/expiry-rules.md#other-alerts | Done |
| PDF/A validation | `library/pdfa.py`, `pdfa_check` command, `--with-verapdf` | `test_pdfa` (4) | guides/ocr-corrections.md#pdfa | Done |
| Accessibility audit | `tests/e2e/a11y.mjs`, `scripts/e2e.sh`, CI `e2e` job | — | guides/testing.md | Done |

## Change set 2026-10: profile photos, Local AI, security & access, passkeys

| ID | Scenario (abridged) | Code | Tests | Docs | Status |
|---|---|---|---|---|---|
| AT-31 | AI profile configured, tested, models discovered; privacy class enforced | `ai/providers.py` (`classify_endpoint`, `check_privacy`), `ai/views.py` | `test_ai::test_at31_*` (fake local server) | guides/local-ai.md#profiles, #privacy | Done (live LM Studio/Ollama: Pending-env) |
| AT-32/33 | OCR assist and smart organisation suggest; nothing changes until accepted | `ai/service.analyze_document`, `ai/service.accept`, `AISuggestions.tsx` | `test_ai::test_at32_at33_*` | guides/local-ai.md#ocr-assist, #smart-organization | Done |
| AT-34 | Assistant and semantic search only use permitted documents | `ai/service.retrieve`, `semantic_search`, `ask` (start from `ctx.documents()`) | `test_ai::test_at34_*` (records prompts) | guides/local-ai.md#permissions | Done |
| AT-35 | Revoking access revokes AI retrieval immediately | as AT-34 | `test_ai::test_at35_*` | guides/local-ai.md#permissions | Done |
| AT-36 | AI outage does not break uploads, OCR, search or reminders | `ai/jobs.py` (`RetryLater`/`PermanentFailure`, after commit) | `test_ai::test_at36_*` | guides/local-ai.md#overview | Done |
| AT-37 | Profile photo upload, crop, replace, remove | `accounts/photos.py`, `PhotoEditor.tsx` | `test_photos::test_at37_*` | guides/getting-started.md#profile-photo | Done |
| AT-38 | Photo requires authentication and visibility | `accounts/views.py` photo views | `test_photos::test_at38_*` | guides/getting-started.md#profile-photo | Done |
| AT-39 | Login events record real client IP through the trusted proxy | `security/netutil.py`, `security/login_audit.py` | `test_security::test_at39_*` | guides/security-access.md#real-ip | Done (real NPM/Pangolin: Pending-env) |
| AT-40 | Local GeoIP lookup; no external lookups | `security/geoip.py` | `test_security::test_at40_*`, `test_geoip_update_installs_valid_download` | guides/security-access.md#geoip | Done (real MaxMind download: Pending-env) |
| AT-41 | Untrusted clients cannot spoof X-Forwarded-For | `netutil.client_ip` | `test_security::test_at41_*`, `test_client_ip_trusted_proxy_rightmost_untrusted` | guides/security-access.md#real-ip | Done |
| AT-42 | Allow list: only Saudi Arabia and India | `security/policy.py`, `AccessPolicyMiddleware` | `test_security::test_at42_*`, `test_block_list_and_unknown_locations` | guides/security-access.md#example-sa-in | Done |
| AT-43 | Denied before authentication code runs | `AccessPolicyMiddleware` (before sessions/auth) | `test_security::test_at43_*` | guides/security-access.md#overview | Done |
| AT-44 | IP rule precedence (blocked > trusted > country) | `policy.evaluate` | `test_security::test_at44_*`, `test_emergency_environment_switch` | guides/security-access.md#precedence | Done |
| AT-45 | Temporary country access window, flagged sign-ins | `TemporaryCountryAccess`, `jobs.expire_temporary_access` | `test_security::test_at45_*`, `test_temporary_access_sign_in_is_flagged` | guides/security-access.md#temporary | Done |
| AT-46 | Admin filters login audit; members cannot | `security/views.logins`, `LoginAuditPanel` | `test_security::test_at46_*` | guides/security-access.md#login-audit | Done |
| AT-47 | Traffic analytics admin-only; privacy-safe log; GoAccess or built-in summary | `security/traffic.py`, `jobs.goaccess_report` | `test_security::test_at47_*`, `test_access_log_is_privacy_safe`, `test_goaccess_report_parsed`, `test_builtin_summary_without_goaccess` | guides/security-access.md#goaccess | Done |
| AT-48 | Security alerts: escalation, new country, policy changes, throttled and secret-free | `security/alerts.py` | `test_failed_login_escalation_blocks_and_alerts`, `test_alerts_are_throttled_and_secret_free`, `test_new_country_alert`, `test_policy_change_alerts_and_audit` | guides/security-access.md#alerts | Done |
| AT-49 | Failed GeoIP update keeps the old database and policy | `geoip.install_file` (validate, then atomic replace) | `test_security::test_at49_*` | guides/security-access.md#geoip | Done |
| AT-50 | Console recovery from a misconfigured policy | `management/commands/access_policy.py`, `personaldocs access-policy` | `test_security::test_at50_*`, `test_lockout_protection_on_policy_change` | guides/security-access.md#recovery | Done |
| PK-1..PK-n | Passkeys: 2FA and passwordless, recent-auth, policy, recovery, no secrets in records | `accounts/passkeys.py`, `Passkeys.tsx`, `Reauth.tsx`, `webauthn.ts` | `test_passkeys` (14, real WebAuthn via software authenticator) | guides/passkeys.md | Done (real browsers/password managers: Pending-env) |
| TOTP autofill | `autocomplete="one-time-code"`, `inputmode="numeric"` on code fields | `Auth.tsx`, `Account.tsx` | e2e flow (TOTP step) | guides/totp-recovery.md#password-managers | Done (real password managers: Pending-env) |

## Change set H/I (2026-10): UI, import, notifications, backup, mobile/PWA, viewer, public release

Browser checks are in `tests/e2e/parity.mjs` (run by `scripts/e2e.sh`, results in `docs/parity-report.json`).

| ID | Scenario (abridged) | Code | Tests | Docs | Status |
|---|---|---|---|---|---|
| AT-61 | Own area identified; no other trees leak | `serializers.folder_json` (`owner_user`), `FolderPicker.folderLabel`, `Folders.tsx` (`.my-area`) | `test_browser_moves::test_at61_*`; parity AT-61 | guides/getting-started.md#my-documents | Done |
| AT-62 | File-type icons from validated content | `library/filetypes.py`, `services.detect_format`, `FileTypeIcon.tsx` | `test_browser_moves::test_at62_*`, `test_file_kind_*`; parity AT-62 (list, grid) | guides/getting-started.md#file-types | Done |
| AT-63 | Import into an existing destination sub-folder with a safe picker | `imports.validate_mapping`, `ImportWizard.tsx` + `FolderPicker` | `test_imports::test_at63_*` (2); parity AT-63/64 | guides/folder-imports.md#destination | Done |
| AT-64 | Hierarchy preserved exactly as previewed | `imports.preview_tree`, `_sub_parts`, `destination_for` | `test_imports::test_at63_at64_*`, `test_at64_*`; parity AT-63/64 | guides/folder-imports.md#destination | Done |
| AT-65 | Widget selector without typed ids | `registry` `widget_list`, `WidgetListEditor.tsx`, `Dashboard.tsx` | `test_preferences::test_at65_*`; parity AT-65/66 | guides/getting-started.md#dashboard | Done |
| AT-66 | Widget order by drag/keyboard, synced | as AT-65, `session.tsx` (refresh on foreground) | `test_preferences::test_at66_at78_*`; parity AT-65/66, AT-78 | guides/getting-started.md#dashboard | Done |
| AT-67 | Critical events cannot be disabled; missing destinations reported | `notify/catalog.py`, `views.my_notification_preferences`, `views.delivery_problems` | `test_notification_policy::test_at67_*` (2), `test_unconfigured_*` | guides/expiry-rules.md#critical | Done |
| AT-68 | Optional event × channel matrix per person | `catalog.preferences`, `Account.tsx` (matrix) | `test_notification_policy::test_at68_*`; parity AT-68 | guides/expiry-rules.md#optional | Done |
| AT-69 | Templates useful and secret-free; links need sign-in | `notify/templates.py`, `events.notify`, `alerts._login_facts` | `test_notification_policy::test_at69_*` (2) | guides/expiry-rules.md#templates | Done (real email/Telegram delivery: Pending-env) |
| AT-70 | Bulk actions consolidated | `events.documents_added`, `import_finished`, `documents_removed` | `test_notification_policy::test_at70_*` | guides/expiry-rules.md#templates | Done |
| AT-71 | Daily/weekly/monthly backups persist, run, report | `ops/schedule.py`, scheduler `tick`, `ops/views.backup_status` | `test_backup_schedule` (3); parity AT-71 | guides/backup-restore.md#schedule | Done (real NAS: Pending-env) |
| AT-72 | Document drag and drop | `Folders.tsx` (DnD), `services.move_document` (atomic, audited) | `test_browser_moves::test_at72_*`; parity AT-72 | guides/getting-started.md#moving | Done |
| AT-73 | Folder drag and drop; self/descendant/denied refused | `services.move_folder` (advisory lock, cycle check), `views.folder_detail` (atomic) | `test_browser_moves::test_at73_*` (2); parity AT-73 | guides/getting-started.md#moving | Done |
| AT-74 | Failed moves never lose/duplicate/orphan | `services.move_*` (transactions, `move_widens_access`) | `test_at74_*` (3, incl. concurrent opposite moves) | guides/getting-started.md#moving | Done |
| AT-75 | Mobile Move To | `Folders.tsx` (`RowMenu`, `MoveDialog`) | parity AT-75 (desktop, phone portrait, landscape) | guides/mobile-pwa.md#parity | Done |
| AT-76 | Mobile/PWA parity of major workflows | responsive CSS, `Folders.tsx`, `DocViewer.tsx` | parity AT-76/77 (22 screens × tablet, phone portrait, phone landscape) | guides/mobile-pwa.md#parity | Done (real devices/installed PWA: Pending-env) |
| AT-77 | Responsive UX: no overflow, usable controls | `styles.css` (tablet fixes, matrix, viewer toolbar) | parity AT-76/77, AT-83; `a11y.mjs` (0 serious) | guides/mobile-pwa.md#parity | Done |
| AT-78 | Cross-device settings | server-side preferences, `session.tsx` | `test_preferences::test_at66_at78_*`; parity AT-78 | guides/mobile-pwa.md#parity | Done |
| AT-79 | No secrets/private data; Atik Ansari as author | `scripts/privacy_check.sh` (tree + `--history`), `.gitignore`, `frontend/package.json` | `scripts/verify.sh` hygiene step | CONTRIBUTING.md, SECURITY.md | Done (visibility change not performed: needs owner) |
| AT-80 | README screenshots, docs links, commands, claims | `README.md`, `docs/images/screenshots/` | `privacy_check.sh` link check; parity regenerates screenshots | README.md, docs/USER_GUIDE.md, docs/ADMIN_GUIDE.md | Done |
| AT-81 | PDF zoom and fit controls | `DocViewer.tsx`, `pdfjs.ts` (PDF.js, local assets) | parity AT-81 (zoom steps, %, fit page/width, 100%, pages, keys, resize, original unchanged) | guides/getting-started.md#viewer | Done |
| AT-82 | Image zoom/fit, aspect ratio, scrolling | `DocViewer.tsx` | parity AT-82 (PNG, JPEG, WebP) | guides/getting-started.md#viewer | Done |
| AT-83 | Viewer responsive/mobile | `styles.css` (`.viewer-toolbar`) | parity AT-83 (tablet, phone portrait/landscape: reachable, ≥24 px, tap zoom) | guides/getting-started.md#viewer | Done (real devices: Pending-env) |
| AT-84 | Viewer authorisation and failure handling | unchanged `document_preview`/`document_file` checks, `DocViewer` error state | parity AT-84 (anonymous refused, damaged PDF, no external requests); `test_documents`, `test_permissions` | guides/getting-started.md#viewer | Done |

## Change set J (2026-10): browsing, OCR quality, one-line installer, public presentation

| ID | Scenario (abridged) | Code | Tests | Docs | Status |
|---|---|---|---|---|---|
| AT-85 | Overflow menus not clipped, in viewport, keyboard/Escape/outside click, one at a time | `components/Menu.tsx` (portal), `Folders.tsx`, `DocumentPanel.tsx` | parity AT-85 (folder + row menu, elementFromPoint, bottom edge, keys) | guides/getting-started.md#actions | Done |
| AT-86 | Rename / archive / permanent delete with permission, confirmation and audit | `Folders.tsx` (`docMenu`, rename/archive/purge dialogs), `views.document_view` | `test_browsing_v3::test_at86_*`; parity AT-86 | guides/getting-started.md#actions | Done |
| AT-87 | Sub-folders default to 📁; approved icon list; reset to default | `services.default_emoji`, `APPROVED_ICONS`, `views.folder_detail`, icon dialog | `test_browsing_v3::test_at87_*`, `test_documents::test_at13_*`, `test_templates`; parity AT-87/88 | guides/getting-started.md#icons | Done |
| AT-88 | Icons preserved through move/import/upgrade | `services.move_folder`, migration `library.0005` | `test_browsing_v3::test_at88_*` (2) | guides/folder-imports.md#emoji | Done (backup/restore keeps the database row: covered by existing backup tests) |
| AT-89 | List / Thumbnails / Details, sorting, per-user synced | `docview.ts`, `Folders.tsx`, `search.SORTS`, `me.doc_view`/`me.doc_sort` | `test_browsing_v3::test_at89_*`; parity AT-89; `units.test.ts` | guides/getting-started.md#views | Done |
| AT-90 | External file drop with progress and failure report | `dropUpload.ts`, `views._upload` / `_DropTree` | `test_browsing_v3::test_at90_*`; parity AT-90 (synthetic DataTransfer) | guides/getting-started.md#drop | Done (real Explorer/Finder drag: Pending-env) |
| AT-91 | External folder hierarchy recreated, traversal refused | `dropUpload.collectDropped` (entries API), `_DropTree.folder_for` (`normalize_rel`) | `test_browsing_v3::test_at91_*`, `test_at90_*`; `units.test.ts` (folder walk, fallback) | guides/getting-started.md#drop | Done (browser folder walk with a real OS drag: Pending-env) |
| AT-92 | Own library first and expanded; others collapsed | `Folders.tsx` (landing + expansion), `FolderPicker.folderChildren` | parity AT-92 | guides/getting-started.md#my-documents | Done |
| AT-93 | Measured OCR preprocessing | `library/ocr.py`, `scripts/ocr_benchmark.py`, `tests/ocr_samples.py` | `test_ocr_quality::test_at93_*`, `test_ocr_reports_*` | OCR_BENCHMARK.md, guides/ocr-corrections.md#quality | Done (mean F1 0.61 → 0.97 on 12 synthetic samples) |
| AT-94 | Structured fields incl. column layout and No Expiry | `extraction.py` (`parse_columns`, `find_no_expiry`, `parse_date_info`), `Document.no_expiry` | `test_ocr_quality::test_column_layout_*`, `test_at94_*` (2) | guides/ocr-corrections.md#no-expiry | Done |
| AT-95 | Corrections persist across OCR re-runs; rotation re-run | `services.apply_*`, `views.document_reprocess` (`rotate`), `RerunDialog` | `test_ocr_quality::test_at95_*`; parity AT-93/94 | guides/ocr-corrections.md#quality | Done |
| AT-96 | Public title everywhere; internal ids stable | `registry general.app_name`, manifest, `index.html`, README, docs, installer, migration `core.0002` | `test_ops` (settings reference), e2e screenshots | README.md | Done |
| AT-97 | Demo owner Atik Ansari in public screenshots | `tests/e2e/flow.mjs`, `parity.mjs` | parity AT-61, AT-92 | README.md#screenshots | Done |
| AT-98 | One-line installer | `personal-DM.sh` | `tests/installer/test_personal_dm.sh` (stubbed, 18 checks); shellcheck | README.md#install, guides/installation.md#one-line | Done (real Debian 13 install/upgrade and the public raw URL: Pending-env) |
| AT-99 | Installer lifecycle: install, upgrade, repair, doctor, status, backup, restore, recover-admin; fails loudly; no secrets | `personal-DM.sh` → `scripts/easy-install.sh`, `scripts/personaldocs` | `tests/installer/test_personal_dm.sh` | guides/installation.md#one-line, guides/upgrades.md#change-set-j | Done (on real hardware: Pending-env) |
| AT-100 | LinkedIn-ready README, Ko-fi, FUNDING.yml, topics recommended | `README.md`, `.github/FUNDING.yml` | `privacy_check.sh` link check | README.md | Done (topics and visibility: owner action) |
