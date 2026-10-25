// Central tooltip / contextual help registry (Change Set V). Components refer to a stable id
// (<HelpTip id="backup.queue" />) instead of repeating their own wording. `link` points to a Help guide anchor; the
// link is only shown to people whose role may open that guide (`audience`, same rules as the server:
// all | delegate | admin | main_admin). tests/test_corrective_v.py checks that every id used in the code exists here
// and that every link resolves to an existing guide heading.
import type { Session } from "../types";

export type Audience = "all" | "delegate" | "admin" | "main_admin";
export type HelpEntry = { text: string; link?: string; audience?: Audience };

export const HELP: Record<string, HelpEntry> = {
  "backup.queue": { text: "Backups and verifications run one at a time, in the order they were requested. A running backup cannot be cancelled; closing the page or signing out does not stop it.", link: "/help/backup-restore#backup-now", audience: "main_admin" },
  "backup.capacity": { text: "Warning below 20 % free space, critical below 10 % (each destination can override this). Valid backups are never deleted to make room.", link: "/help/backup-restore#capacity", audience: "main_admin" },
  "nas.connection": { text: "SMB or NFS: Personal DM mounts the share itself (privileged LXC with mount=nfs;cifs). Already mounted: the Proxmox host or you mounted it and you enter the folder.", link: "/help/backup-restore#nas", audience: "main_admin" },
  "whatsapp.link": { text: "Link your own WhatsApp account as a linked device. The link attempt stays valid for 5 minutes; WhatsApp renews the picture itself about every 20–30 seconds.", link: "/help/whatsapp-personal#link", audience: "all" },
  "whatsapp.diagnostics": { text: "Safe checks only: versions, DNS, network, system time, session storage and pairing state. Never QR codes, keys, numbers or messages.", link: "/help/whatsapp-personal#diagnostics", audience: "main_admin" },
  "map.filters": { text: "The map and the list below use the same filters. Default: last 7 days. Sign-in records are kept for one year.", link: "/help/security-map#filters", audience: "all" },
  "map.markers": { text: "Point at a marker for the name, address and place; click or tap it for all details. Markers at the same place are grouped with a number.", link: "/help/security-map#map", audience: "all" },
  "help.permissions": { text: "Help shows only the guides for features you can use. Administrators see more.", link: "/help/troubleshooting#everyone", audience: "all" },
  // Change Set AA
  "ai.source": { text: "What the AI reads. Original Document modes send the PDF or image itself to a Local AI that can read files or images; OCR Text sends only the recognised text.", link: "/help/local-ai#processing-source", audience: "all" },
  "ai.source.ocr_text": { text: "OCR Text: the configured OCR engines read the document first; only the recognised text goes to the AI. The original file is never sent.", link: "/help/local-ai#processing-source", audience: "all" },
  "ai.source.original": { text: "Original Document — Local AI: the PDF or image goes straight to a Local AI profile that supports it. OCR is not run. If the AI cannot read it, the action fails and you can retry with OCR fallback.", link: "/help/local-ai#processing-source", audience: "all" },
  "ai.source.original_fallback": { text: "Original Document — Local AI + OCR Fallback (recommended): the Local AI reads the original first. If it cannot (unsupported file, error, time-out, unusable answer), the OCR engines run in the order the Main Admin set and the AI reads their text instead. Every step is recorded in AI History.", link: "/help/local-ai#ocr-fallback", audience: "all" },
  "ai.source.default": { text: "Used for new AI actions unless someone with permission chooses another source for one action. Changing it affects future processing only.", link: "/help/local-ai#processing-source", audience: "main_admin" },
  "dashboard.edit": { text: "Edit Layout: drag tiles, resize them with the corner handle (or the size buttons), arrange them in your own groups. Nothing moves outside Edit Layout. Your layout is yours alone and follows you to every device.", link: "/help/overview#edit-layout", audience: "all" },
  "dashboard.groups": { text: "Groups are your own headings, such as Family or Renewals. Removing a group never removes its tiles: they move to the group you choose, or to General.", link: "/help/overview#groups", audience: "all" },
  "dashboard.reset": { text: "Reset Layout puts your Overview back to the default tiles, sizes and groups. Only your layout changes; no document or setting is touched.", link: "/help/overview#reset-layout", audience: "all" },
  "fields.archive": { text: "Archive hides the field from new documents, the Details panel, required checks and OCR / AI suggestions. Every value already stored is kept and comes back when you restore the field.", link: "/help/document-types#archive-fields", audience: "main_admin" },
  "fields.archived": { text: "Archived fields keep their definition and stored values. Restore brings the same field back; permanent deletion (Main Admin only) removes the field and its stored values from the live application.", link: "/help/document-types#archived-fields", audience: "main_admin" },
  "fields.delete": { text: "Permanent deletion removes the field and its values from the live application after step-up authentication. Backups already taken keep what they contained. Archive is the standard way to remove a field.", link: "/help/document-types#permanent-deletion", audience: "main_admin" },
  "fields.order": { text: "Drag the handle to change the order, or focus it and press the up and down arrow keys. Values belong to the field itself, so the order never changes stored data.", link: "/help/document-types#field-order", audience: "main_admin" },
  // Change Set AB: Maintenance & Operations and Active Sessions
  "maint.job": { text: "Every operation here is a Maintenance Job kept on the server with its steps, result, error and log. Refreshing the page, signing out or a service restart never loses it.", link: "/help/maintenance#maintenance-jobs", audience: "admin" },
  "maint.check_updates": { text: "Compares the installed version with the configured update source (repository and branch). It never installs anything.", link: "/help/maintenance#check-for-updates", audience: "main_admin" },
  "maint.upgrade": { text: "Preflight, an automatic verified backup, the update, dependencies, migrations, frontend build, restart and health checks. A failed backup stops the update before anything changes.", link: "/help/maintenance#update-application", audience: "main_admin" },
  "maint.doctor": { text: "Read-only diagnostics of every component — the same checks as sudo personaldocs doctor. PASS, WARNING, FAIL, NOT CONFIGURED, NOT APPLICABLE or NOT TESTED per check.", link: "/help/maintenance#doctor", audience: "admin" },
  "maint.repair": { text: "Analyze first: you see each detected problem, the proposed repair, what it affects, the risk and whether a restart or backup is needed. Nothing changes until you confirm; the result is verified afterwards.", link: "/help/maintenance#repair", audience: "main_admin" },
  "maint.health": { text: "Database, OCR, AI, Security, Backup and Storage health from the same sources as their own pages.", link: "/help/maintenance#health-panels", audience: "admin" },
  "maint.health.database": { text: "Database reachable, version, size, connections and pending migrations.", link: "/help/maintenance#health-panels", audience: "admin" },
  "maint.health.ocr": { text: "Whether the primary OCR engine and its fallbacks work, the queue and recent failures.", link: "/help/maintenance#health-panels", audience: "admin" },
  "maint.health.ai": { text: "AI mode, default profile, provider and location, last test and recent failures. Keys are never shown.", link: "/help/maintenance#health-panels", audience: "admin" },
  "maint.health.security": { text: "The Security Health score and the checks that lower it.", link: "/help/maintenance#health-panels", audience: "admin" },
  "maint.health.backup": { text: "Backup & Recovery Health from verified recovery points, not from a running schedule.", link: "/help/maintenance#health-panels", audience: "admin" },
  "maint.health.storage": { text: "Disk use against the warning and critical thresholds.", link: "/help/maintenance#health-panels", audience: "admin" },
  "maint.restart": { text: "Restarts only the Personal DM services (web, worker, scheduler) and checks their health. The page reconnects by itself.", link: "/help/maintenance#restart", audience: "main_admin" },
  "maint.caches": { text: "Only rebuildable caches. Documents, OCR text and provenance, metadata, backups, logs, AI history, configuration, offline data and recovery material are never deleted.", link: "/help/maintenance#safe-caches", audience: "main_admin" },
  "maint.system_info": { text: "Versions, operating system, uptime, CPU, memory, storage, database, OCR and AI details and the workers. No secret is shown.", link: "/help/maintenance#system-information", audience: "main_admin" },
  "maint.history": { text: "Every maintenance operation with its result. Filter by operation, status and date. Full logs are kept for the maintenance log retention period.", link: "/help/maintenance#job-history", audience: "admin" },
  "maint.technical": { text: "The failed step, component, time, exit code, the exact (sanitized) error, the log lines around it, and a detected condition and probable cause only when one is known.", link: "/help/maintenance#technical-details", audience: "main_admin" },
  "maint.full_log": { text: "The complete output of the operation. Passwords, keys, tokens, cookies and credentials are removed on the server before you see or download it.", link: "/help/maintenance#full-log", audience: "main_admin" },
  "maint.support_report": { text: "A sanitized report with the job, its steps, technical details, system information and log. The anonymized version also replaces IP addresses, user and host names, document paths and network names.", link: "/help/maintenance#support-report", audience: "main_admin" },
  "maint.retry": { text: "Starts the same operation again as a new job linked to this one; this job stays in the history.", link: "/help/maintenance#retry", audience: "main_admin" },
  "maint.rollback": { text: "Returns to the previous release only when the database is still compatible with it. After incompatible migrations, restore the pre-upgrade backup instead.", link: "/help/maintenance#rollback", audience: "main_admin" },
  "maint.recovery_required": { text: "The operation stopped in a state the application cannot fix by itself. Follow the Recovery Guide: restore the pre-upgrade backup or roll back if the schema is compatible.", link: "/help/maintenance#recovery-required", audience: "main_admin" },
  "sessions.page": { text: "Every valid session you may see: who, from where, on which device and how recently. Session cookies and tokens are never shown.", link: "/help/active-sessions#visibility", audience: "admin" },
  "sessions.active": { text: "Active: the person did something within the Active threshold (default 5 minutes). Background refreshes do not count.", link: "/help/active-sessions#active-threshold", audience: "all" },
  "sessions.signed_in": { text: "Signed In: still signed in, but idle longer than the Active threshold.", link: "/help/active-sessions#active-threshold", audience: "all" },
  "sessions.trusted_zone": { text: "A network the administrator named (Home, VPN …). It is shown first and is one risk signal; it does not make a session automatically safe.", link: "/help/active-sessions#location-and-trust", audience: "all" },
  "sessions.approximate": { text: "Outside a Trusted Zone the place comes from a local GeoIP database: country or city at best, never a street address. GPS is never used.", link: "/help/active-sessions#location-and-trust", audience: "all" },
  "sessions.risk": { text: "From the sign-in risk classification, raised when the address moved to a public network or the device was marked Unrecognized.", link: "/help/active-sessions#risk", audience: "admin" },
  "sessions.terminate": { text: "Ends this one session on the server; the device must sign in again. The person is notified. The device stays recognized — Mark Unrecognized is a different action.", link: "/help/active-sessions#terminate-session", audience: "main_admin" },
  "metadata.archived": { text: "Values of fields the administrator archived. They are kept, shown only here, and labelled Archived.", link: "/help/document-types#archived-metadata", audience: "all" },
};

export function canSee(session: Session | null | undefined, audience: Audience = "all"): boolean {
  if (audience === "all") return true;
  const u = session?.user;
  if (!u) return false;
  if (u.is_main_admin) return true;
  if (audience === "admin") return !!u.is_admin;
  if (audience === "delegate") return !!u.is_admin || (session?.delegations || []).length > 0;
  return false;
}
