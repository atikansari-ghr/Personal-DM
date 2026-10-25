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
