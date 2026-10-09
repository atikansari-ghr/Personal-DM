import { useEffect, useState } from "react";
import { formatBytes } from "../api";
import {
  STATUS_LABEL, documentSelection, estimate, folderSelection, makeAvailable, offlineSupported, removeSelection, statusOf, updateNow, useOffline,
  type OfflineState, type OfflineStatus, type SyncResult,
} from "../offline";
import { useSession } from "../session";
import type { MenuItem } from "./Menu";
import { Icon, Modal, useToast } from "./ui";

const STATUS_ICON: Record<OfflineStatus, string> = {
  available: "check", downloading: "download", update_available: "refresh", updating: "refresh", outdated: "clock",
  failed: "alert", locked: "lock", none: "offline",
};
const STATUS_CLASS: Record<OfflineStatus, string> = {
  available: "ok", downloading: "neutral", update_available: "warn", updating: "neutral", outdated: "warn", failed: "danger",
  locked: "neutral", none: "neutral",
};

/** Offline status of one document on this device: icon + text, never colour alone. Renders nothing for
 *  "not available offline" unless ``showNone`` (lists stay quiet; the document header says it explicitly). */
export function OfflineBadge({ docId, showNone, compact }: { docId: string; showNone?: boolean; compact?: boolean }) {
  const { session } = useSession();
  const st = useOffline(session?.user?.id);
  const status = statusOf(st, docId);
  if (status === "none" && !showNone) return null;
  const it = st.items[docId];
  const busy = status === "downloading" || status === "updating";
  const label = `${STATUS_LABEL[status]}${busy && it?.progress !== undefined ? ` ${it.progress}%` : ""}`;
  return (
    <span className={`badge ${STATUS_CLASS[status]} offline-badge`} title={it?.error ? `${label}: ${it.error}` : label}
      role={busy ? "status" : undefined} aria-label={compact ? label : undefined} data-offline-status={status}>
      <Icon name={STATUS_ICON[status]} size={13} />
      {compact ? <span className="sr-only">{label}</span> : <span>{label}</span>}
    </span>
  );
}

/** Small "available offline" marker for a folder in the tree. */
export function FolderOfflineMark({ folderId }: { folderId: string }) {
  const { session } = useSession();
  const st = useOffline(session?.user?.id);
  const sel = folderSelection(st, folderId);
  if (!sel) return null;
  const docs = Object.values(st.items).filter((i) => i.selections?.includes(sel.id));
  const pending = docs.filter((i) => i.status !== "available").length;
  const label = pending ? `Offline: ${pending} of ${docs.length} not up to date` : `Available offline (${docs.length})`;
  return <span className="offline-mark" title={label} aria-label={label} role="img"><Icon name={pending ? "refresh" : "offline"} size={13} /></span>;
}

export function useOfflineAvailable(): { ok: boolean; reason: string } {
  const { session } = useSession();
  if (!offlineSupported()) return { ok: false, reason: "This browser does not support offline storage." };
  if (session?.offline && !session.offline.allowed) return { ok: false, reason: session.offline.reason };
  return { ok: true, reason: "" };
}

/** "⋮" menu entries for a folder: Make available offline… / Update offline copy / Remove offline copy. */
export function useOfflineMenus() {
  const { session } = useSession();
  const uid = session?.user?.id || "";
  const st = useOffline(uid);
  const toast = useToast();
  const avail = useOfflineAvailable();
  const [dialog, setDialog] = useState<{ kind: "folder" | "document"; id: string; name: string } | null>(null);

  const report = (r: { downloaded: number; updated: number; removed: number; failed: number; error?: string }, done: string) => {
    if (r.error) return toast(r.error, "error");
    toast(r.failed ? `${done} ${r.failed} file(s) could not be downloaded; see Offline files.` : done, r.failed ? "error" : "ok");
  };

  const folderItems = (f: { id: string; name: string; caps: string[]; path_only?: boolean }): MenuItem[] => {
    const sel = folderSelection(st, f.id);
    const ok = avail.ok && !f.path_only && f.caps.includes("download");
    return [
      { label: "Make available offline…", hidden: !ok || !!sel, onSelect: () => setDialog({ kind: "folder", id: f.id, name: f.name }) },
      { label: "Update offline copy", hidden: !ok || !sel, onSelect: () => updateNow(uid).then((r) => report(r, "Offline copy updated.")) },
      { label: "Remove offline copy", hidden: !sel, onSelect: () => removeSelection(uid, sel!).then(() => toast("Offline copy removed from this device")).catch((e) => toast(e.message, "error")) },
    ];
  };

  const documentItems = (d: { id: string; title: string; caps: string[] }): MenuItem[] => {
    const sel = documentSelection(st, d.id);
    const status = statusOf(st, d.id);
    const ok = avail.ok && d.caps.includes("download");
    const viaFolder = status !== "none" && !sel;
    return [
      { label: "Make available offline", hidden: !ok || status !== "none",
        onSelect: () => makeAvailable(uid, { document: d.id }).then(({ sync }) => sync.then((r) => report(r, "Available offline on this device."))).catch((e) => toast(e.message, "error")) },
      { label: "Update offline copy", hidden: !ok || status === "none",
        onSelect: () => updateNow(uid, d.id).then((r) => report(r, "Offline copy updated.")) },
      { label: "Remove offline copy", hidden: status === "none",
        onSelect: () => viaFolder
          ? toast("This document is offline because its folder is. Remove the folder's offline copy instead.", "error")
          : removeSelection(uid, sel!).then(() => toast("Offline copy removed from this device")).catch((e) => toast(e.message, "error")) },
    ];
  };

  const dialogEl = dialog ? <MakeOfflineDialog target={dialog} uid={uid} onClose={() => setDialog(null)}
    onDone={(n, sync) => { setDialog(null); toast(`Downloading ${n} document(s) for offline use…`); sync.then((r) => report(r, "Folder available offline on this device.")); }} /> : null;
  return { folderItems, documentItems, dialog: dialogEl, state: st as OfflineState };
}

function MakeOfflineDialog({ target, uid, onClose, onDone }: {
  target: { kind: "folder" | "document"; id: string; name: string }; uid: string; onClose: () => void;
  onDone: (count: number, sync: Promise<SyncResult>) => void;
}) {
  const [recursive, setRecursive] = useState(true);
  const [est, setEst] = useState<Awaited<ReturnType<typeof estimate>> | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [space, setSpace] = useState<number | undefined>();
  useEffect(() => {
    setEst(null);
    estimate({ folder: target.id, recursive }).then(setEst).catch((e) => setErr(e.message));
  }, [recursive, target.id]);
  useEffect(() => { navigator.storage?.estimate?.().then((e) => setSpace(e.quota !== undefined && e.usage !== undefined ? e.quota - e.usage : undefined)).catch(() => undefined); }, []);
  const large = est && est.bytes > est.large_bytes;
  const overQuota = est && est.bytes > est.quota_bytes;
  const noSpace = est && space !== undefined && est.bytes * 1.1 > space;
  const go = async () => {
    setBusy(true);
    try { onDone(est?.documents || 0, (await makeAvailable(uid, { folder: target.id, recursive })).sync); } catch (e: any) { setErr(e.message); setBusy(false); }
  };
  return (
    <Modal title={`Make “${target.name}” available offline`} onClose={onClose}>
      <p className="small muted">Copies are kept only on this device, for your account. Other devices and other people are not affected.</p>
      <fieldset className="radio-cards">
        <legend className="sr-only">What to keep offline</legend>
        <label className="check"><input type="radio" name="scope" checked={recursive} onChange={() => setRecursive(true)} /> <span><strong>This folder and all subfolders</strong> <span className="badge">Recommended</span></span></label>
        <label className="check"><input type="radio" name="scope" checked={!recursive} onChange={() => setRecursive(false)} /> <span><strong>This folder only</strong></span></label>
      </fieldset>
      <div className="card offline-estimate" aria-live="polite">
        {!est && !err && <span className="muted small">Calculating…</span>}
        {est && <>
          <div className="row between"><span>Documents</span><strong>{est.documents}</strong></div>
          {recursive && <div className="row between"><span>Subfolders</span><strong>{est.subfolders}</strong></div>}
          <div className="row between"><span>Estimated size</span><strong>{formatBytes(est.bytes)}</strong></div>
          {space !== undefined && <div className="row between small muted"><span>Free browser storage</span><span>{formatBytes(space)}</span></div>}
          {(est.not_downloadable > 0 || est.blocked > 0) && <p className="small muted">{est.not_downloadable > 0 && `${est.not_downloadable} document(s) without download permission are left out. `}{est.blocked > 0 && `${est.blocked} quarantined file(s) are left out.`}</p>}
          <p className="small muted">New documents added to {recursive ? "this folder or its subfolders" : "this folder"} later are downloaded at the next sync.</p>
        </>}
      </div>
      {large && <div className="alert warn" role="alert"><Icon name="alert" size={16} /> Large download ({formatBytes(est!.bytes)}). Use Wi-Fi if your connection is metered.</div>}
      {overQuota && <div className="alert warn">This is more than the suggested {formatBytes(est!.quota_bytes)} per device.</div>}
      {noSpace && <div className="alert error">Not enough browser storage on this device for this folder.</div>}
      {err && <div className="alert error">{err}</div>}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={!est || busy || !!noSpace || est.documents === 0} onClick={go}>
          <Icon name="offline" /> {busy ? "Starting…" : large ? "Download anyway" : "Make available offline"}
        </button>
      </div>
    </Modal>
  );
}
