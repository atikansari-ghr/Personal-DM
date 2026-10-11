import { useEffect, useState } from "react";
import { api, formatBytes, formatDate, formatDateTime } from "../api";
import { useSession } from "../session";
import { HelpTip, Icon, Modal, Skeleton, useAsync, useToast } from "../components/ui";
import { ImpactView, ReportView } from "./settings/Backup";

// Recovery Explorer: browse retained recovery points (people → folders → documents → versions), compare with today,
// analyse the impact and restore. Everyone sees only what they may recover under today's permissions.

type Point = { id: string; kind: string; created_at: string; status?: string | null };
const MODES: [string, string, string][] = [
  ["keep_new", "Keep current + restore as new version", "Safest. Nothing current changes; restored files are added to the history."],
  ["replace", "Replace current version", "The restored version becomes current and the details go back to the backup's values. The present version stays in the history."],
  ["skip", "Skip existing", "Only missing items are re-created; existing documents are left untouched."],
];

export default function RecoveryPage() {
  const { session } = useSession();
  const main = !!session?.user?.is_main_admin;
  const mine = useAsync<any>(() => api("recovery/mine"), []);
  const points = useAsync<{ points: Point[] }>(() => api("recovery/points"), []);
  const [pid, setPid] = useState("");
  const [owner, setOwner] = useState("");
  const [folder, setFolder] = useState("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [restore, setRestore] = useState<{ kind: string; target: any; label: string } | null>(null);
  const [compare, setCompare] = useState<string | null>(null);
  useEffect(() => { if (!pid && points.data?.points.length) setPid(points.data.points[0].id); }, [points.data, pid]);
  const tree = useAsync<any>(() => (pid ? api(`recovery/points/${pid}`, { query: { owner, folder, q: query } }) : Promise.resolve(null)), [pid, owner, folder, query]);
  return (
    <div className="stack recovery-page">
      <div className="page-head"><div><h1>Recovery Explorer</h1><p className="muted">Browse earlier backups and restore documents, versions, folders{main ? " or a whole person's data" : ""}. <a href="/help/backup-restore#explorer">Learn more</a></p></div></div>
      <section className="card my-recovery" aria-labelledby="my-rec">
        <h2 id="my-rec">My Recovery</h2>
        {mine.data ? <p>{mine.data.protected ? <><Icon name="check" size={16} /> {mine.data.message} Last successful backup: <strong>{formatDateTime(mine.data.last_successful_backup)}</strong> · {mine.data.points_available} recovery point(s) available.</> : <><Icon name="alert" size={16} /> {mine.data.message}</>}</p> : <Skeleton lines={1} />}
      </section>
      {points.data && !points.data.points.length ? <div className="empty card"><h2>No recovery points yet</h2><p>Once the family's encrypted backups have run and been verified, earlier states of your documents appear here.</p></div> : (
        <div className="recovery-grid">
          <aside className="card recovery-side">
            <div className="field"><label htmlFor="rp-point">Restore point</label>
              <select id="rp-point" value={pid} onChange={(e) => { setPid(e.target.value); setFolder(""); }}>
                {points.data?.points.map((p) => <option key={p.id} value={p.id}>{formatDateTime(p.created_at)} · {p.kind === "full" ? "Full" : "Incremental"}</option>)}
              </select></div>
            <ol className="timeline" aria-label="Recovery point timeline">{points.data?.points.slice(0, 12).map((p) => <li key={p.id}><button type="button" className={p.id === pid ? "active" : ""} aria-current={p.id === pid ? "true" : undefined} onClick={() => { setPid(p.id); setFolder(""); }}>
              <span className={`dot ${p.kind}`} aria-hidden="true" />{formatDateTime(p.created_at)}<span className="small muted"> {p.kind === "full" ? "Full" : "Incr."}</span></button></li>)}</ol>
            {tree.data?.users?.length > 1 || main ? (
              <div className="field"><label htmlFor="rp-owner">Person</label><select id="rp-owner" value={owner} onChange={(e) => { setOwner(e.target.value); setFolder(""); }}>
                <option value="">Everyone I may recover</option>{tree.data?.users?.map((u: any) => <option key={u.id} value={u.id}>{u.display_name}{u.exists ? "" : " (account deleted)"}</option>)}</select></div>
            ) : null}
            {main && owner && tree.data?.users?.find((u: any) => u.id === owner) && (
              <button className="btn small" onClick={() => setRestore({ kind: "user", target: { user: owner }, label: `everything of ${tree.data.users.find((u: any) => u.id === owner).display_name}` })}>Restore this person's data…</button>
            )}
            <h3 className="small muted" style={{ marginTop: "1rem" }}>Folders</h3>
            <ul className="tree plain">
              <li><button type="button" className={!folder ? "active" : ""} onClick={() => setFolder("")}>All folders</button></li>
              {tree.data?.folders?.map((f: any) => <li key={f.id} style={{ paddingLeft: `${Math.min(f.path.length - 1, 5) * 0.8}rem` }}>
                <button type="button" className={folder === f.id ? "active" : ""} onClick={() => setFolder(f.id)}><Icon name="folder" size={14} /> {f.name}{!f.exists && <span className="badge neutral" style={{ marginLeft: 4 }}>deleted</span>}</button></li>)}
            </ul>
          </aside>
          <section className="card recovery-main">
            <form className="row" style={{ gap: 8, flexWrap: "wrap" }} onSubmit={(e) => { e.preventDefault(); setQuery(q); }}>
              <input type="search" aria-label="Search this recovery point" placeholder="Search names in this recovery point" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1, minWidth: 180 }} />
              <button className="btn">Search</button>
              {folder && <button type="button" className="btn" onClick={() => setRestore({ kind: "folder", target: { folder }, label: `the folder “${tree.data?.folders?.find((f: any) => f.id === folder)?.name}” and its subfolders` })}>Restore this folder…</button>}
            </form>
            {tree.loading && !tree.data ? <Skeleton lines={6} /> : tree.error ? <div className="alert error">{tree.error}</div> : (
              <>
                <p className="small muted">{tree.data?.total ?? 0} document(s){tree.data?.total > 500 ? " (first 500 shown)" : ""}</p>
                <ul className="plain doc-recovery-list">
                  {tree.data?.documents?.map((d: any) => <li key={d.id} className="recovery-doc">
                    <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                      <div><strong>{d.title}</strong> {d.exists ? (d.current_newer ? <span className="badge warn">Changed since</span> : <span className="badge ok">Exists</span>) : <span className="badge danger">Deleted</span>}
                        <div className="small muted">{d.folder_path.join(" / ")} · {d.owner}{d.expiry_date ? ` · expires ${formatDate(d.expiry_date)}` : ""}</div></div>
                      <div className="row" style={{ gap: 4 }}>
                        {d.exists && <button className="btn small" onClick={() => setCompare(d.id)}>Compare</button>}
                        <button className="btn small primary" onClick={() => setRestore({ kind: "document", target: { document: d.id }, label: `“${d.title}”` })}>Restore…</button>
                      </div>
                    </div>
                    <details><summary className="small">{d.versions.length} version(s)</summary>
                      <ul className="plain versions">{d.versions.map((v: any) => <li key={v.id} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
                        <span>v{v.number} · {v.original_name} · {formatBytes(v.size)} · {formatDateTime(v.created_at)}{v.is_current && <span className="badge neutral" style={{ marginLeft: 4 }}>current then</span>}{v.in_current && <span className="badge ok" style={{ marginLeft: 4 }}>in today's history</span>}</span>
                        <button className="btn small" onClick={() => setRestore({ kind: "version", target: { document: d.id, version: v.id }, label: `version ${v.number} of “${d.title}”` })}>Restore version…</button></li>)}</ul>
                    </details>
                  </li>)}
                </ul>
              </>
            )}
          </section>
        </div>
      )}
      {restore && pid && <RestoreDialog point={pid} spec={restore} users={tree.data?.users || []} onClose={() => setRestore(null)} onDone={() => { setRestore(null); tree.reload(); }} />}
      {compare && pid && <CompareDialog point={pid} doc={compare} onClose={() => setCompare(null)} />}
    </div>
  );
}

function RestoreDialog({ point, spec, users, onClose, onDone }: { point: string; spec: { kind: string; target: any; label: string }; users: any[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [mode, setMode] = useState("keep_new");
  const [opt, setOpt] = useState("staging");
  const [transfer, setTransfer] = useState("");
  const [impact, setImpact] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const deletedUser = spec.kind === "user" && users.find((u) => u.id === spec.target.user && !u.exists);
  const target = { ...spec.target, ...(deletedUser ? { user_option: opt, transfer_to: opt === "transfer" ? transfer : undefined } : {}) };
  const analyse = () => { setErr(""); setBusy(true); api("recovery/restore", { body: { point, kind: spec.kind, target, mode } }).then((r) => setImpact(r.impact)).catch((e) => setErr(e.message)).finally(() => setBusy(false)); };
  const execute = () => { setBusy(true); api("recovery/restore", { body: { point, kind: spec.kind, target, mode, execute: true } }).then((r) => { setResult(r); toast(r.status === "completed" ? "Restore completed" : `Restore ${r.status}`, r.status === "completed" ? "ok" : "error"); }).catch((e) => setErr(e.message)).finally(() => setBusy(false)); };
  return (
    <Modal title={`Restore ${spec.label}`} onClose={result ? onDone : onClose} wide>
      <div className="stack">
        {err && <div className="alert error" role="alert">{err}</div>}
        {result ? <><div className="callout tip">Restore {result.status}. Restored items keep a note “Restored from backup”.</div><ReportView run={result} /><div className="row" style={{ justifyContent: "flex-end" }}><button className="btn primary" onClick={onDone}>Done</button></div></> : <>
          <fieldset className="field"><legend>If something already exists <HelpTip text="Chosen before anything changes. No mode deletes current data." /></legend>
            {MODES.map(([k, l, d]) => <label key={k} className="check radio-card"><input type="radio" name="mode" value={k} checked={mode === k} onChange={() => { setMode(k); setImpact(null); }} /> <span><strong>{l}</strong>{k === "keep_new" && <span className="badge ok" style={{ marginLeft: 6 }}>Default</span>}<br /><span className="small muted">{d}</span></span></label>)}
          </fieldset>
          {deletedUser && <fieldset className="field"><legend>This account no longer exists</legend>
            <label className="check"><input type="radio" name="opt" checked={opt === "recreate"} onChange={() => setOpt("recreate")} /> Re-create the account (a new password is required; old sessions, passkeys and two-step settings are not restored)</label>
            <label className="check"><input type="radio" name="opt" checked={opt === "transfer"} onChange={() => setOpt("transfer")} /> Restore into another person's library</label>
            {opt === "transfer" && <select aria-label="Person who receives the data" value={transfer} onChange={(e) => setTransfer(e.target.value)}><option value="">Choose a person…</option>{users.filter((u) => u.exists).map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}</select>}
            <label className="check"><input type="radio" name="opt" checked={opt === "staging"} onChange={() => setOpt("staging")} /> Recovery staging area (visible only to the main administrator)</label>
          </fieldset>}
          {!impact ? <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={busy || (deletedUser && opt === "transfer" && !transfer)} onClick={analyse}>Analyse impact</button></div> : <>
            <h3>Restore Impact Analysis</h3>
            <ImpactView impact={impact} />
            <div className="row" style={{ justifyContent: "flex-end", flexWrap: "wrap" }}>
              <button className="btn" onClick={() => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(impact, null, 1)], { type: "application/json" })); a.download = "restore-impact-analysis.json"; a.click(); }}>Export analysis</button>
              <button className="btn" onClick={() => setImpact(null)}>Change options</button>
              <button className="btn primary" disabled={busy} onClick={execute}>Restore now</button>
            </div></>}
        </>}
      </div>
    </Modal>
  );
}

function CompareDialog({ point, doc, onClose }: { point: string; doc: string; onClose: () => void }) {
  const c = useAsync<any>(() => api(`recovery/points/${point}/compare/${doc}`), [point, doc]);
  return (
    <Modal title="Backup compared with today" onClose={onClose} wide>
      {c.loading ? <Skeleton /> : c.error ? <div className="alert error">{c.error}</div> : (
        <div className="table-wrap"><table className="table"><thead><tr><th>Field</th><th>In the backup</th><th>Today</th></tr></thead>
          <tbody>{c.data.rows.map((r: any) => <tr key={r.label} className={r.same ? "" : "changed"}><td>{r.label}</td><td>{String(r.backup ?? "—")}</td><td>{String(r.current ?? "—")}{!r.same && <span className="badge warn" style={{ marginLeft: 6 }}>changed</span>}</td></tr>)}</tbody></table></div>
      )}
    </Modal>
  );
}
