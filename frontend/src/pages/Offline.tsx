import { useEffect, useState } from "react";
import { api, formatBytes, formatDateTime } from "../api";
import { Icon, useToast } from "../components/ui";
import { keepAfterSignOut, listOffline, offlineSupported, openOffline, removeOffline, requestPersistence, revalidate, setKeepAfterSignOut, storageInfo, type OfflineItem } from "../offline";
import FileTypeIcon, { kindFromMime } from "../components/FileTypeIcon";
import { useSession } from "../session";

export default function OfflinePage() {
  const { session, offline } = useSession();
  const toast = useToast();
  const uid = session?.user?.id || "";
  const [items, setItems] = useState<OfflineItem[]>([]);
  const [info, setInfo] = useState<{ usage?: number; quota?: number; persisted?: boolean }>({});
  const [keep, setKeep] = useState(false);
  const [plan, setPlan] = useState<any>(null);
  const [partMb, setPartMb] = useState(2048);
  const refresh = () => { setItems(listOffline(uid)); storageInfo().then(setInfo); };
  useEffect(() => {
    if (!uid) return;
    setKeep(keepAfterSignOut(uid));
    refresh();
    if (!offline) revalidate(uid).then((r) => { if (r.revoked) toast(`${r.revoked} offline file(s) removed: access was revoked.`); refresh(); }).catch(() => undefined);
  }, [uid, offline]);
  useEffect(() => { if (!offline) api("export/plan", { query: { part_mb: partMb } }).then(setPlan).catch(() => undefined); }, [partMb, offline]);
  const open = async (it: OfflineItem) => {
    const url = await openOffline(uid, it);
    if (!url) return toast("This offline copy is missing; save it again.", "error");
    window.open(url, "_blank", "noopener");
  };
  const total = items.reduce((s, i) => s + i.size, 0);
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Offline files</h1><p className="muted">Files you explicitly saved on this device for use without a connection.</p></div></div>
      {!offlineSupported() && <div className="alert warn">This browser does not support offline storage. Use the library export below instead.</div>}
      <div className="grid stats">
        <div className="card stat"><Icon name="download" size={30} /><div><div className="muted small">Saved on this device</div><div className="num">{items.length}</div><div className="small muted">{formatBytes(total)}</div></div></div>
        <div className="card stat"><Icon name="db" size={30} /><div><div className="muted small">Browser storage</div><div className="num" style={{ fontSize: "1.2rem" }}>{info.quota ? `${formatBytes(info.usage)} of ${formatBytes(info.quota)}` : "Unknown"}</div>
          <div className="small muted">{info.persisted ? "Protected from automatic clean-up" : <button className="btn small" onClick={async () => { const ok = await requestPersistence(); toast(ok ? "Storage protected" : "The browser declined; files may be removed when space is low.", ok ? "ok" : "error"); refresh(); }}>Protect storage</button>}</div></div></div>
      </div>
      <div className="card">
        <h2>Saved files</h2>
        {items.length === 0 ? <p className="muted">Nothing saved yet. Open a document and choose “Save for offline use”.</p> : items.map((it) => (
          <div key={it.documentId} className="list-item">
            <FileTypeIcon kind={kindFromMime(it.mime, it.name)} size="sm" />
            <div className="grow"><div style={{ fontWeight: 600 }}>{it.title}</div><div className="small muted">{it.name} · {formatBytes(it.size)} · saved {formatDateTime(it.savedAt)}</div></div>
            {it.stale && <span className="badge soon">Newer version online</span>}
            <button className="btn small" onClick={() => open(it)}>Open</button>
            <button className="btn small danger" onClick={async () => { await removeOffline(uid, it.documentId); refresh(); }}>Remove</button>
          </div>
        ))}
        <label className="check" style={{ marginTop: ".8rem" }}><input type="checkbox" checked={keep} onChange={(e) => { setKeep(e.target.checked); setKeepAfterSignOut(uid, e.target.checked); }} /> Keep my offline files on this device after I sign out</label>
        <p className="small muted">By default your offline files are deleted when you sign out, and other accounts on this device never see them. When you reconnect, files you no longer have access to are removed. The app cannot recall copies while a device stays offline.</p>
      </div>
      {!offline && plan && (
        <div className="card">
          <h2>Export my whole library</h2>
          <p className="muted small">For large libraries, a ZIP export is more reliable than browser storage. It contains every document you can download, in its folder structure, with a manifest and SHA-256 checksums. Exported files are outside the app's control.</p>
          <div className="row"><label htmlFor="part">Part size</label><select id="part" value={partMb} onChange={(e) => setPartMb(Number(e.target.value))} style={{ maxWidth: 180 }}><option value={512}>512 MB</option><option value={2048}>2 GB</option><option value={4096}>4 GB</option></select></div>
          <p>{plan.files} files · {formatBytes(plan.bytes)} · {plan.parts.length} part(s)</p>
          <div className="row">{plan.parts.map((p: any) => <a key={p.part} className="btn" href={`/api/export/download?part=${p.part}&part_mb=${partMb}`}><Icon name="download" /> Part {p.part} ({formatBytes(p.bytes)})</a>)}</div>
        </div>
      )}
    </div>
  );
}
