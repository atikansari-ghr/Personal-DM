import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatBytes, formatDateTime } from "../api";
import { Confirm, Icon, useToast } from "../components/ui";
import {
  STATUS_LABEL, forgetThisDevice, isLocked, keepAfterSignOut, offlineSupported, openOffline, removeSelection, requestPersistence,
  setKeepAfterSignOut, statusOf, storageInfo, syncNow, updateNow, useOffline, type OfflineItem, type Selection,
} from "../offline";
import { OfflineBadge } from "../components/OfflineUI";
import FileTypeIcon, { kindFromMime } from "../components/FileTypeIcon";
import { useSession } from "../session";

interface Device { id: string; label: string; platform: string; installed_app: boolean; last_sync_at: string | null; items: number; bytes: number; failures: number; selections: number }

export default function OfflinePage() {
  const { session, offline } = useSession();
  const toast = useToast();
  const uid = session?.user?.id || "";
  const st = useOffline(uid);
  const [info, setInfo] = useState<{ usage?: number; quota?: number; persisted?: boolean }>({});
  const [keep, setKeep] = useState(false);
  const [plan, setPlan] = useState<any>(null);
  const [partMb, setPartMb] = useState(2048);
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [confirm, setConfirm] = useState<"" | "forget">("");
  const [rename, setRename] = useState<{ id: string; label: string } | null>(null);
  const items = Object.values(st.items).sort((a, b) => (a.path || "").localeCompare(b.path || "") || a.title.localeCompare(b.title));
  const loadDevices = () => api<{ devices: Device[] }>("offline/devices").then((r) => setDevices(r.devices)).catch(() => undefined);
  useEffect(() => {
    if (!uid) return;
    setKeep(keepAfterSignOut(uid));
    storageInfo().then(setInfo);
    if (!offline) {
      syncNow(uid).then((r) => { if (r.removed && !r.wiped) toast(`${r.removed} offline cop${r.removed === 1 ? "y" : "ies"} removed (access changed or no longer selected).`); storageInfo().then(setInfo); loadDevices(); });
      loadDevices();
    }
  }, [uid, offline]);
  useEffect(() => { if (!offline) api("export/plan", { query: { part_mb: partMb } }).then(setPlan).catch(() => undefined); }, [partMb, offline]);

  const open = async (it: OfflineItem) => {
    const url = await openOffline(uid, it);
    if (!url) return toast(isLocked(st) ? "Offline copies are locked until this device connects and you sign in again." : "This offline copy is missing; update it.", "error");
    window.open(url, "_blank", "noopener");
  };
  const total = items.reduce((s, i) => s + (i.size || 0), 0);
  const pending = items.filter((i) => ["update_available", "failed", "downloading", "updating"].includes(statusOf(st, i.documentId)));
  const failed = items.filter((i) => i.status === "failed");
  const folders = st.selections.filter((s) => s.kind === "folder");
  const docSel = (docId: string) => st.selections.find((s) => s.kind === "document" && s.document === docId);
  const inFolder = (sel: Selection) => items.filter((i) => i.selections?.includes(sel.id));
  const policyClears = st.policy?.logout_policy === "always_clear";
  const thisDevice = devices?.find((d) => d.id === st.deviceId);
  const others = (devices || []).filter((d) => d.id !== st.deviceId);

  return (
    <div className="stack">
      <div className="page-head">
        <div><h1>Offline access</h1><p className="muted">Folders and documents you chose to keep on this device, for use without a connection.</p></div>
        {!offline && offlineSupported() && (
          <div className="row">
            <button className="btn" disabled={st.syncing} onClick={() => syncNow(uid).then((r) => toast(r.error ? r.error : "Checked for changes", r.error ? "error" : "ok"))}><Icon name="refresh" /> {st.syncing ? "Syncing…" : "Sync now"}</button>
            <button className="btn primary" disabled={st.syncing || pending.length === 0} onClick={() => updateNow(uid).then((r) => toast(r.failed ? `${r.failed} could not be updated` : "All offline copies are up to date", r.failed ? "error" : "ok"))}><Icon name="download" /> Update all</button>
          </div>
        )}
      </div>
      {!offlineSupported() && <div className="alert warn">This browser does not support offline storage. Use the library export below instead.</div>}
      {offline && <div className="alert info" role="status"><Icon name="cloud" size={16} /> You are offline. Offline copies can be opened; changes are checked when the connection returns.</div>}
      {!st.allowed && st.reason && <div className="alert warn" role="alert">{st.reason}</div>}
      {isLocked(st) && <div className="alert warn" role="alert"><Icon name="lock" size={16} /> Offline copies are locked: this device has not synced for more than {st.policy?.max_days_without_sync} days. Connect and sign in to unlock them.</div>}
      {st.lastError && !offline && <div className="alert error">Last sync failed: {st.lastError}</div>}

      <div className="grid stats">
        <div className="card stat"><Icon name="monitor" size={30} /><div>
          <div className="muted small">This device</div>
          <div className="num" style={{ fontSize: "1.15rem" }}>{thisDevice?.label || st.deviceLabel || "Not set up yet"}</div>
          <div className="small muted">{st.lastSync ? `Last sync ${formatDateTime(st.lastSync)}` : "Not synced yet"}{thisDevice && !offline && <> · <button className="link" onClick={() => setRename({ id: thisDevice.id, label: thisDevice.label })}>Rename</button></>}</div>
        </div></div>
        <div className="card stat"><Icon name="offline" size={30} /><div>
          <div className="muted small">Offline on this device</div><div className="num">{items.length}</div>
          <div className="small muted">{formatBytes(total)} · {folders.length} folder{folders.length === 1 ? "" : "s"}</div>
        </div></div>
        <div className="card stat"><Icon name="refresh" size={30} /><div>
          <div className="muted small">Pending updates</div><div className={`num ${pending.length ? "warn" : ""}`}>{pending.length}</div>
          <div className="small muted">{failed.length ? `${failed.length} failed` : "No failures"}</div>
        </div></div>
        <div className="card stat"><Icon name="db" size={30} /><div>
          <div className="muted small">Browser storage</div>
          <div className="num" style={{ fontSize: "1.15rem" }}>{info.quota ? `${formatBytes(info.usage)} of ${formatBytes(info.quota)}` : "Unknown"}</div>
          {info.quota ? <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(((info.usage || 0) / info.quota) * 100)} aria-label="Browser storage used"><span style={{ width: `${Math.min(100, ((info.usage || 0) / info.quota) * 100)}%` }} /></div> : null}
          <div className="small muted">Suggested limit {formatBytes((st.policy?.device_quota_mb || 2048) * 1024 * 1024)}</div>
        </div></div>
      </div>

      <div className="card">
        <h2>Offline folders</h2>
        {folders.length === 0 ? <p className="muted">No folders yet. In <Link to="/folders">Folders</Link>, open a folder's <strong>⋮</strong> menu and choose <strong>Make available offline…</strong>.</p> : folders.map((sel) => {
          const docs = inFolder(sel);
          const notReady = docs.filter((d) => statusOf(st, d.documentId) !== "available").length;
          return (
            <div key={sel.id} className="list-item">
              <Icon name="folder" />
              <div className="grow">
                <div style={{ fontWeight: 600 }}>{sel.name}</div>
                <div className="doc-meta small muted"><span>{sel.recursive ? "With all subfolders" : "This folder only"}</span><span>{docs.length} document{docs.length === 1 ? "" : "s"}</span><span>{formatBytes(docs.reduce((n, d) => n + (d.size || 0), 0))}</span></div>
              </div>
              <span className={`badge ${!sel.available ? "neutral" : notReady ? "warn" : "ok"}`}><Icon name={!sel.available ? "lock" : notReady ? "refresh" : "check"} size={13} />{!sel.available ? "No longer available" : notReady ? `${notReady} not up to date` : "Up to date"}</span>
              {sel.folder && sel.available && <Link className="btn small" to={`/folders/${sel.folder}`}>Open folder</Link>}
              {!offline && <button className="btn small danger" onClick={() => removeSelection(uid, sel).then(() => toast("Offline copy removed from this device"))}>Remove offline copy</button>}
            </div>
          );
        })}
      </div>

      <div className="card">
        <h2>Offline documents</h2>
        {items.length === 0 ? <p className="muted">Nothing on this device yet. Open a document's <strong>⋮</strong> menu and choose <strong>Make available offline</strong>.</p> : items.map((it) => {
          const status = statusOf(st, it.documentId);
          const own = docSel(it.documentId);
          return (
            <div key={it.documentId} className="list-item" data-offline-doc={it.documentId}>
              <FileTypeIcon kind={kindFromMime(it.mime, it.name)} size="sm" />
              <div className="grow">
                <div style={{ fontWeight: 600 }}>{it.title}</div>
                <div className="doc-meta small muted">{it.path && <span>{it.path}</span>}<span>{it.name}</span><span>{formatBytes(it.size)}</span>{it.versionNumber ? <span>v{it.versionNumber}</span> : null}{it.savedAt && <span>saved {formatDateTime(it.savedAt)}</span>}</div>
                {it.error && <div className="small error-text">{it.error}</div>}
              </div>
              <OfflineBadge docId={it.documentId} />
              <button className="btn small" disabled={!it.savedAt || status === "locked"} onClick={() => open(it)}>Open</button>
              {!offline && ["update_available", "failed", "outdated"].includes(status) && <button className="btn small" onClick={() => updateNow(uid, it.documentId)}>Update</button>}
              {!offline && own && <button className="btn small danger" onClick={() => removeSelection(uid, own).then(() => toast("Offline copy removed"))}>Remove</button>}
            </div>
          );
        })}
        <p className="small muted" style={{ marginTop: ".6rem" }}>Status legend: {(["available", "downloading", "update_available", "updating", "outdated", "failed"] as const).map((s) => STATUS_LABEL[s]).join(" · ")}.</p>
      </div>

      <div className="card">
        <h2>Manage storage</h2>
        <div className="row between">
          <div className="grow"><strong>Protect from automatic clean-up</strong><div className="small muted">{info.persisted ? "This browser will not remove offline copies when it runs low on space." : "The browser may remove offline copies when the device runs low on space."}</div></div>
          {!info.persisted && <button className="btn small" onClick={async () => { const ok = await requestPersistence(); toast(ok ? "Storage protected" : "The browser declined; copies may be removed when space is low.", ok ? "ok" : "error"); storageInfo().then(setInfo); }}>Protect storage</button>}
        </div>
        <label className="check" style={{ marginTop: ".8rem" }}>
          <input type="checkbox" checked={keep && !policyClears} disabled={policyClears} onChange={(e) => { setKeep(e.target.checked); setKeepAfterSignOut(uid, e.target.checked); }} />
          Keep my offline copies on this device after I sign out
        </label>
        <p className="small muted">{policyClears ? "Your administrator requires offline copies to be removed at sign-out." : "By default your offline copies are deleted when you sign out."} Other accounts on this device never see them. When you reconnect, copies you no longer have access to are removed. {st.policy?.max_days_without_sync ? `Copies lock after ${st.policy.max_days_without_sync} days without a sync.` : ""} The app cannot erase copies from a device that stays offline.</p>
        {!offline && <button className="btn danger" onClick={() => setConfirm("forget")}><Icon name="x" /> Remove all offline copies from this device</button>}
      </div>

      {!offline && others.length > 0 && (
        <div className="card">
          <h2>Your other devices</h2>
          {others.map((d) => (
            <div key={d.id} className="list-item">
              <Icon name="monitor" />
              <div className="grow"><div style={{ fontWeight: 600 }}>{d.label}</div>
                <div className="doc-meta small muted"><span>{d.platform}</span><span>{d.items} copies</span><span>{formatBytes(d.bytes)}</span><span>{d.last_sync_at ? `last sync ${formatDateTime(d.last_sync_at)}` : "never synced"}</span></div></div>
              <button className="btn small" onClick={() => setRename({ id: d.id, label: d.label })}>Rename</button>
              <button className="btn small danger" onClick={() => api(`offline/devices/${d.id}`, { method: "DELETE" }).then(() => { toast("Device forgotten. Its copies are removed when it next connects."); loadDevices(); })}>Forget</button>
            </div>
          ))}
        </div>
      )}

      {!offline && plan && (
        <div className="card">
          <h2>Export my whole library</h2>
          <p className="muted small">For large libraries, a ZIP export is more reliable than browser storage. It contains every document you can download, in its folder structure, with a manifest and SHA-256 checksums. Exported files are outside the app's control.</p>
          <div className="row"><label htmlFor="part">Part size</label><select id="part" value={partMb} onChange={(e) => setPartMb(Number(e.target.value))} style={{ maxWidth: 180 }}><option value={512}>512 MB</option><option value={2048}>2 GB</option><option value={4096}>4 GB</option></select></div>
          <p>{plan.files} files · {formatBytes(plan.bytes)} · {plan.parts.length} part(s)</p>
          <div className="row">{plan.parts.map((p: any) => <a key={p.part} className="btn" href={`/api/export/download?part=${p.part}&part_mb=${partMb}`}><Icon name="download" /> Part {p.part} ({formatBytes(p.bytes)})</a>)}</div>
        </div>
      )}
      {confirm === "forget" && <Confirm title="Remove all offline copies?" message={<p>Every offline folder and document of your account is deleted from this device, and the device is forgotten. Your documents on the server are not affected.</p>}
        confirmLabel="Remove all" danger onClose={() => setConfirm("")} onConfirm={async () => { await forgetThisDevice(uid); setConfirm(""); toast("Offline copies removed from this device"); storageInfo().then(setInfo); loadDevices(); }} />}
      {rename && (
        <div className="modal-backdrop" role="presentation" onClick={() => setRename(null)}>
          <form className="modal" role="dialog" aria-modal="true" aria-label="Rename device" onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => { e.preventDefault(); api(`offline/devices/${rename.id}`, { method: "PATCH", body: { label: rename.label } }).then(() => { setRename(null); loadDevices(); }).catch((er) => toast(er.message, "error")); }}>
            <h2>Rename device</h2>
            <div className="field"><label htmlFor="devname">Name</label><input id="devname" type="text" maxLength={80} value={rename.label} onChange={(e) => setRename({ ...rename, label: e.target.value })} autoFocus /></div>
            <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={() => setRename(null)}>Cancel</button><button className="btn primary">Save</button></div>
          </form>
        </div>
      )}
    </div>
  );
}
