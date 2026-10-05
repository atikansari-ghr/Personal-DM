import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, formatBytes, upload } from "../api";
import FolderPicker, { descendantIds, folderLabel as nodeLabel } from "../components/FolderPicker";
import { Icon, Modal, Skeleton, useToast } from "../components/ui";
import { useSession } from "../session";
import type { FolderNode, User } from "../types";

const ROOT_FILES = "(files in the top folder)";
const dirSupported = () => "webkitdirectory" in document.createElement("input");

async function walkEntry(entry: any, prefix: string, out: Map<string, File>) {
  if (entry.isFile) {
    const file: File = await new Promise((res, rej) => entry.file(res, rej));
    out.set(prefix + entry.name, file);
  } else if (entry.isDirectory) {
    const reader = entry.createReader();
    let batch: any[] = [];
    do {
      batch = await new Promise((res, rej) => reader.readEntries(res, rej));
      for (const e of batch) await walkEntry(e, `${prefix}${entry.name}/`, out);
    } while (batch.length);
  }
}

export default function ImportWizard() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { session } = useSession();
  const [sess, setSess] = useState<any>(null);
  const [files, setFiles] = useState<Map<string, File>>(new Map());
  const [serverRoot, setServerRoot] = useState("");
  const [mapping, setMapping] = useState<Record<string, any>>({});
  const [members, setMembers] = useState<User[]>([]);
  const [folders, setFolders] = useState<FolderNode[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0, failed: 0 });
  const [error, setError] = useState("");
  const dirInput = useRef<HTMLInputElement>(null);
  const [picking, setPicking] = useState<string | null>(null); // source folder whose destination is being chosen
  const me = session?.user?.id || null;
  const byId = new Map(folders.map((f) => [f.id, f]));
  const pathOf = (id?: string | null) => {
    const out: string[] = [];
    for (let n = id ? byId.get(id) : undefined; n; n = n.parent ? byId.get(n.parent) : undefined) out.unshift(nodeLabel(n, me));
    return out.join(" / ");
  };
  const rootOf = (userId?: string) => folders.find((f) => f.kind === "personal_root" && f.owner === userId);

  const load = () => id && api(`imports/${id}`).then((s) => { setSess(s); setMapping(s.mapping); });
  useEffect(() => { load(); }, [id]);
  useEffect(() => {
    api<{ members: User[] }>("family/members").then((r) => setMembers(r.members));
    api<{ folders: FolderNode[] }>("folders").then((r) => setFolders(r.folders));
  }, []);
  useEffect(() => {
    if (sess?.status !== "importing" || sess.source_type !== "server") return;
    const t = setTimeout(load, 3000);
    return () => clearTimeout(t);
  }, [sess]);

  const scanBrowser = async (map: Map<string, File>) => {
    setFiles(map);
    if (id) return; // resuming: files re-selected for pending uploads
    setBusy(true);
    setError("");
    try {
      const entries = [...map.entries()].map(([path, f]) => ({ path, size: f.size }));
      const s = await api("imports", { body: { source_type: "browser", entries } });
      nav(`/imports/${s.id}`, { replace: true });
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const onDirInput = (list: FileList | null) => {
    if (!list) return;
    const map = new Map<string, File>();
    Array.from(list).forEach((f) => {
      const rel = (f as any).webkitRelativePath || f.name;
      // drop the selected top folder itself so its sub-folders become the mapping units
      const parts = rel.split("/");
      map.set(parts.length > 1 ? parts.slice(1).join("/") : rel, f);
    });
    scanBrowser(map);
  };
  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    const map = new Map<string, File>();
    const items = Array.from(e.dataTransfer.items).map((i) => (i as any).webkitGetAsEntry?.()).filter(Boolean);
    for (const entry of items) {
      if (entry.isDirectory) {
        const reader = entry.createReader();
        let batch: any[] = [];
        do { batch = await new Promise((res, rej) => reader.readEntries(res, rej)); for (const c of batch) await walkEntry(c, "", map); } while (batch.length);
      } else await walkEntry(entry, "", map);
    }
    scanBrowser(map);
  };
  const scanServer = async () => {
    setBusy(true);
    setError("");
    try { const s = await api("imports", { body: { source_type: "server", root: serverRoot } }); nav(`/imports/${s.id}`, { replace: true }); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const saveMapping = async () => {
    setError("");
    try { const s = await api(`imports/${id}`, { method: "PUT", body: { mapping } }); setSess(s); setMapping(s.mapping); return true; }
    catch (e: any) { setError(e.message); return false; }
  };
  const start = async () => {
    if (!(await saveMapping())) return;
    try { const s = await api(`imports/${id}/start`, { method: "POST" }); setSess(s); if (s.source_type === "browser") await uploadPending(); }
    catch (e: any) { setError(e.message); }
  };
  const uploadPending = async () => {
    const { pending } = await api<{ pending: string[] }>(`imports/${id}/pending`);
    const todo = pending.filter((p) => files.has(p));
    setProgress({ done: 0, total: todo.length, failed: 0 });
    let done = 0, failed = 0;
    for (const path of todo) {
      const form = new FormData();
      form.set("path", path);
      form.set("file", files.get(path)!);
      try { const r = await upload<any>(`imports/${id}/items`, form); if (r.status === "failed") failed++; } catch { failed++; }
      done++;
      setProgress({ done, total: todo.length, failed });
    }
    await load();
    if (pending.length > todo.length) toast(`${pending.length - todo.length} files still need uploading — select the same folder again to resume.`, "error");
  };

  if (!id) {
    return (
      <div className="stack">
        <h1>Import a folder</h1>
        <p className="muted">Bring an existing folder structure in. You decide which person each top-level folder belongs to; nothing is assigned automatically and nothing is shared with other family members.</p>
        {error && <div className="alert error">{error}</div>}
        <div className="card stack">
          <h2>From this computer</h2>
          <div className="dropzone" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
            <p>Drag a folder here{dirSupported() ? ", or" : ""}</p>
            {dirSupported() ? (
              <button className="btn primary" disabled={busy} onClick={() => dirInput.current?.click()}><Icon name="folder" /> Choose folder</button>
            ) : <p className="small">This browser cannot select whole folders. Use a desktop browser such as Chrome, Edge or Firefox, or ask the administrator to use the server import.</p>}
            <input ref={dirInput} type="file" hidden multiple {...({ webkitdirectory: "", directory: "" } as any)} onChange={(e) => onDirInput(e.target.files)} />
          </div>
          {busy && <Skeleton />}
        </div>
        {session?.user?.is_main_admin && (
          <div className="card stack">
            <h2>From the server or NAS</h2>
            <p className="small muted">Files are copied into the library. The source folder is never changed, moved or deleted. Only folders listed under Settings → Documents & folders → Approved server import folders can be used.</p>
            <div className="row"><input type="text" aria-label="Server folder path" placeholder="/mnt/nas/old-documents" value={serverRoot} onChange={(e) => setServerRoot(e.target.value)} className="grow" /><button className="btn primary" disabled={!serverRoot || busy} onClick={scanServer}>Scan</button></div>
          </div>
        )}
      </div>
    );
  }
  if (!sess) return <Skeleton lines={8} />;
  const tops = Object.entries(sess.scan.tops || {}) as [string, any][];
  const editable = sess.status === "mapping";
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Import folder</h1><p className="muted">{sess.source_type === "server" ? `Server folder ${sess.source_root}` : "Folder from this device"} · {sess.scan.files} files · {formatBytes(sess.scan.bytes)}{sess.scan.excluded ? ` · ${sess.scan.excluded} excluded` : ""}</p></div>
        <a className="btn" href={`/api/imports/${id}/report`}><Icon name="download" /> Report (CSV)</a></div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {sess.capacity_warning && <div className="alert warn">{sess.capacity_warning}</div>}
      <div className="card">
        <h2>1. Who do these folders belong to?</h2>
        <p className="small muted">Suggestions are only made when a folder name exactly matches an account name. Old names like “user3” must be assigned by you.</p>
        <table className="responsive"><thead><tr><th>Source folder</th><th>Files</th><th>Destination</th></tr></thead><tbody>
          {tops.map(([top, info]) => {
            const m = mapping[top] || {};
            const set = (patch: any) => setMapping({ ...mapping, [top]: { ...m, ...patch, status: "proposed" } });
            return (
              <tr key={top}>
                <td><strong>{top === ROOT_FILES ? "Loose files" : top}</strong>{m.reason && <div className="small muted">{m.reason}</div>}{m.status === "confirmed" && <span className="badge ok">Confirmed</span>}</td>
                <td>{info.files}{info.excluded ? <div className="small muted">{info.excluded} excluded (system/sync)</div> : null}</td>
                <td>
                  <div className="row">
                    <select aria-label={`Action for ${top}`} disabled={!editable} value={m.action || ""} onChange={(e) => set({ action: e.target.value || null })} style={{ maxWidth: 200 }}>
                      <option value="">Decide…</option><option value="user">A person's folder</option><option value="folder">Another folder (shared)</option><option value="skip">Skip</option>
                    </select>
                    {m.action === "user" && (
                      <>
                        <select aria-label={`Person for ${top}`} disabled={!editable} value={m.user || ""} onChange={(e) => set({ user: e.target.value, folder: null })} style={{ maxWidth: 220 }}>
                          <option value="">Choose person…</option>{members.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
                        </select>
                        {m.user && (
                          <button type="button" className="btn small" disabled={!editable} onClick={() => setPicking(top)} aria-label={`Destination sub-folder for ${top}`}>
                            <Icon name="folder" size={16} /> {m.folder ? pathOf(m.folder) : "Top of their folder"}
                          </button>
                        )}
                      </>
                    )}
                    {m.action === "folder" && (
                      <>
                        <button type="button" className="btn small" disabled={!editable} onClick={() => setPicking(top)} aria-label={`Destination folder for ${top}`}>
                          <Icon name="folder" size={16} /> {m.folder ? pathOf(m.folder) : "Choose folder…"}
                        </button>
                        <select aria-label={`Owner for ${top}`} disabled={!editable} value={m.owner || ""} onChange={(e) => set({ owner: e.target.value })} style={{ maxWidth: 200 }}>
                          <option value="">Owner…</option>{members.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
                        </select>
                      </>
                    )}
                    {(m.action === "user" || m.action === "folder") && top !== ROOT_FILES && (
                      <label className="check small"><input type="checkbox" disabled={!editable} checked={m.keep_top ?? m.action === "folder"} onChange={(e) => set({ keep_top: e.target.checked })} /> keep “{top}” as a folder</label>
                    )}
                    {info.excluded > 0 && m.action && m.action !== "skip" && <label className="check small"><input type="checkbox" disabled={!editable} checked={!!m.include_excluded} onChange={(e) => set({ include_excluded: e.target.checked })} /> include excluded items</label>}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody></table>
        {editable && <div className="row" style={{ marginTop: ".8rem" }}><button className="btn" onClick={saveMapping}>Check & preview</button></div>}
      </div>
      {sess.preview.length > 0 && (
        <div className="card">
          <h2>2. Preview</h2>
          <table className="responsive"><thead><tr><th>Source</th><th>Goes to</th><th>Files</th></tr></thead><tbody>
            {sess.preview.map((p: any) => <tr key={p.source}><td>{p.source}</td><td>{p.action === "skip" ? <span className="muted">Skipped</span> : p.destination}</td><td>{p.files} · {formatBytes(p.bytes)}</td></tr>)}
          </tbody></table>
          <p className="small muted">The destination you choose replaces only the top of the import; every sub-folder inside it is recreated as it is. Existing folders with the same name are reused and files are added next to what is there — nothing is overwritten. Imported documents are only visible to their owner (and the main administrator) unless you grant access.</p>
          {sess.preview_tree?.length > 0 ? (
            <details open><summary>Final folder structure ({sess.preview_tree.length} folders)</summary>
              <ul className="import-tree" aria-label="Final folder structure">
                {sess.preview_tree.map((r: any) => (
                  <li key={r.path} style={{ paddingLeft: `${r.depth * 1.1}rem` }}>
                    <span aria-hidden="true">📁</span> {r.depth ? r.path.split(" / ").pop() : r.path}
                    {" "}<span className={`badge ${r.exists ? "" : "ok"}`}>{r.exists ? "existing" : "new"}</span>
                    {r.files > 0 && <span className="small muted"> · {r.files} file{r.files === 1 ? "" : "s"}</span>}
                  </li>
                ))}
              </ul>
            </details>
          ) : <details><summary>Source folder structure ({sess.tree.length} folders)</summary><pre className="preview-text small">{sess.tree.join("\n")}</pre></details>}
        </div>
      )}
      <div className="card">
        <h2>3. Import</h2>
        <p>Status: <strong>{sess.status.replace(/_/g, " ")}</strong> · {sess.counts.done} done · {sess.counts.pending} pending · {sess.counts.failed} failed · {sess.counts.skipped} skipped</p>
        {progress.total > 0 && <div className="progress" role="progressbar" aria-valuenow={progress.done} aria-valuemax={progress.total}><div style={{ width: `${(progress.done / progress.total) * 100}%` }} /></div>}
        <div className="row" style={{ marginTop: ".6rem" }}>
          {editable && <button className="btn primary" onClick={start}>Start import</button>}
          {sess.status === "importing" && sess.source_type === "browser" && (
            files.size ? <button className="btn primary" onClick={uploadPending}>Continue uploading</button> : (
              <><span className="small">To resume, select the same folder again:</span><button className="btn" onClick={() => dirInput.current?.click()}>Choose folder</button>
                <input ref={dirInput} type="file" hidden multiple {...({ webkitdirectory: "" } as any)} onChange={(e) => onDirInput(e.target.files)} /></>
            )
          )}
          {sess.counts.failed > 0 && <button className="btn" onClick={() => api(`imports/${id}/retry`, { method: "POST" }).then((s) => { setSess(s); if (s.source_type === "browser" && files.size) uploadPending(); })}>Retry failed</button>}
          {sess.status.startsWith("done") && <button className="btn primary" onClick={() => nav("/folders")}>Open folders</button>}
        </div>
      </div>
      {picking && (() => {
        const m = mapping[picking] || {};
        const root = m.action === "user" ? rootOf(m.user) : undefined;
        const inside = root ? descendantIds(folders, root.id) : null;
        return (
          <Modal title={`Destination for “${picking === ROOT_FILES ? "Loose files" : picking}”`} onClose={() => setPicking(null)}>
            <FolderPicker folders={folders} meId={me} value={m.folder || root?.id || ""}
              reason={(f) => (inside && !inside.has(f.id) ? "Not in this person's folder" : !f.caps.includes("upload") ? "You cannot add documents here" : "")}
              onChange={(id) => { setMapping({ ...mapping, [picking]: { ...m, folder: root && id === root.id ? null : id, status: "proposed" } }); }} />
            {m.action === "user" && !root && <p className="small muted">You cannot see this person's folder, so only its top level can be used.</p>}
            <div className="row" style={{ justifyContent: "flex-end", marginTop: ".6rem" }}><button className="btn primary" onClick={() => setPicking(null)}>Done</button></div>
          </Modal>
        );
      })()}
    </div>
  );
}
