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
