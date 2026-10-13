import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, formatBytes, formatDateTime } from "../../api";
import { useStepUp } from "../../components/StepUp";
import SettingsForm from "../../components/SettingsForm";
import { HelpTip, Icon, Modal, Skeleton, useAsync, useToast } from "../../components/ui";

// Settings → Backup & Recovery (main administrator). Every label here matches docs/guides/backup-restore.md.

type Health = { state: "healthy" | "attention" | "critical"; label: string; warnings: string[]; latest: any; latest_verified: any; latest_full: any;
  destinations: any[]; readiness: any; validation: any };
type Overview = { health: Health; policies: any[]; destinations: any[]; points: any[]; legacy: any[]; key: any; retiring: number[]; rotation: any;
  running: string[]; kinds: { kind: string; label: string; config: string[]; secrets: string[] }[]; stepup_valid: boolean; restores: any[] };

const STATE_CLASS: Record<string, string> = { healthy: "ok", attention: "warn", critical: "danger", verified: "ok", partial: "warn", warning: "warn",
  failed: "danger", running: "neutral", stored_verified: "ok", stored_warning: "warn", retry_pending: "warn", auth_required: "danger",
  unavailable: "danger", insufficient_storage: "danger", uploading: "neutral", deleted: "neutral" };
const VIEWS: [string, string][] = [["overview", "Overview"], ["policies", "Policies & schedule"], ["destinations", "Destinations"],
  ["points", "Recovery points"], ["key", "Recovery Key"], ["restores", "Restores & reports"]];
const FIELD_LABELS: Record<string, string> = { path: "Folder path", require_mount: "Require mounted share", endpoint: "Endpoint (https://…)", region: "Region",
  bucket: "Bucket", prefix: "Folder prefix", folder_id: "Folder id", folder: "Folder", access_key: "Access key", secret_key: "Secret key",
  session_token: "Session token (optional)", client_id: "OAuth client id", client_secret: "OAuth client secret", refresh_token: "Refresh token" };

export function HealthBadge({ state, label }: { state: string; label: string }) {
  return <span className={`badge ${STATE_CLASS[state] || "neutral"}`} data-health={state}><Icon name={state === "healthy" || state === "verified" ? "check" : "alert"} size={14} /> {label}</span>;
}

export default function BackupPanel() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") || "overview";
  const toast = useToast();
  const { data, reload, loading, error } = useAsync<Overview>(() => api("backup/overview"), []);
  const step = useStepUp(toast);
  useEffect(() => {
    if (!data?.running.length) return;
    const t = setInterval(reload, 5000);
    return () => clearInterval(t);
  }, [data?.running.length]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <div className="alert error">{error}</div>;
  if (loading && !data) return <Skeleton lines={8} />;
  if (!data) return null;
  return (
    <div className="stack backup-page">
      <nav className="tabs sub" aria-label="Backup & Recovery views">
        {VIEWS.map(([k, l]) => <button key={k} type="button" className={view === k ? "active" : ""} aria-current={view === k ? "page" : undefined}
          onClick={() => setParams(k === "overview" ? {} : { view: k })}>{l}</button>)}
      </nav>
      {view === "overview" && <OverviewView data={data} reload={reload} />}
      {view === "policies" && <PoliciesView data={data} reload={reload} step={step} />}
      {view === "destinations" && <DestinationsView data={data} reload={reload} step={step} />}
      {view === "points" && <PointsView data={data} reload={reload} step={step} />}
      {view === "key" && <KeyView data={data} reload={reload} step={step} />}
      {view === "restores" && <RestoresView data={data} />}
      {step.dialog}
    </div>
  );
}

function OverviewView({ data, reload }: { data: Overview; reload: () => void }) {
  const toast = useToast();
  const h = data.health;
  const post = useAsync<any>(() => api("backup/post-recovery"), []);
  const run = (kind: string) => api<any>("backup/now", { body: { kind } }).then((r) => { toast(`${kind === "full" ? "Full" : "Incremental"} backup ${r.position ? `queued (${r.position} job(s) ahead)` : "started"} — it cannot be cancelled once it runs`); reload(); }).catch((e) => toast(e.message, "error"));
  return (
    <>
      {post.data?.integrations?.active && <PostRecovery data={post.data} reload={post.reload} />}
      {post.data?.security_review?.required && !post.data?.integrations?.active && <PostRecovery data={post.data} reload={post.reload} />}
      <section className="card" aria-labelledby="bk-health">
        <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem" }}>
          <h2 id="bk-health" style={{ margin: 0 }}>Backup & Recovery Health <HealthBadge state={h.state} label={h.label} /></h2>
          <div className="row" style={{ gap: "0.5rem" }}>
            <button className="btn primary" disabled={!data.destinations.length} onClick={() => run("full")}>
              {data.running.includes("backup_point") ? "Back up now (Full) — queues after the running job" : "Back up now (Full)"}</button>
            <button className="btn" disabled={!data.destinations.length} onClick={() => run("incremental")}>Incremental now</button>
          </div>
        </div>
        <p className="small muted">Calculated from verified recovery points and destination checks, not from whether the scheduler is running. <a href="/help/backup-restore#health">Learn more</a></p>
        <div className="stat-grid">
          <Stat label="Newest verified point" value={h.latest_verified ? `${h.latest_verified.kind === "full" ? "Full" : "Incremental"} · ${formatDateTime(h.latest_verified.created_at)}` : "None yet"} />
          <Stat label="Newest Full backup" value={h.latest_full ? formatDateTime(h.latest_full.created_at) : "None yet"} />
          <Stat label="Recovery Readiness" value={h.readiness.label} hint={h.readiness.detail} />
          <Stat label="Recovery validation" value={h.validation.label.replace("Recovery Validation: ", "")} hint={h.validation.detail} />
        </div>
        {h.warnings.length > 0 && <ul className="warn-list">{h.warnings.map((w) => <li key={w}><Icon name="alert" size={16} /> {w}</li>)}</ul>}
        {!data.destinations.length && (
          <div className="callout tip"><strong>Start here:</strong> add a destination (local folder, NAS share, S3, Google Drive or OneDrive). The
            recommended policy — weekly Full backup and an incremental every 4 hours, kept 4 weeks — is created with it.{" "}
            <Link to="/settings/backup?view=destinations">Add a destination</Link></div>
        )}
      </section>
      <section className="card">
        <h2>Destinations</h2>
        {h.destinations.length ? (
          <div className="table-wrap"><table className="table"><thead><tr><th>Destination</th><th>Type</th><th>Health</th><th>Free space</th><th>Checked</th></tr></thead>
            <tbody>{h.destinations.map((d) => <tr key={d.id}><td>{d.name}</td><td>{d.kind}</td><td><HealthBadge state={d.health === "healthy" ? "healthy" : d.health === "unknown" ? "running" : "critical"} label={d.health.replace(/_/g, " ")} />{d.detail && <div className="small muted">{d.detail}</div>}</td>
              <td>{d.free_bytes != null ? formatBytes(d.free_bytes) : "—"}</td><td>{d.checked_at ? formatDateTime(d.checked_at) : "—"}</td></tr>)}</tbody></table></div>
        ) : <p className="muted">No destination yet.</p>}
      </section>
      <section className="card">
        <h2>Recent recovery points</h2>
        <PointTable points={data.points.slice(0, 6)} />
        <p className="small"><Link to="/settings/backup?view=points">All recovery points</Link> · <Link to="/recovery">Recovery Explorer</Link></p>
      </section>
      {data.legacy.length > 0 && (
        <section className="card">
          <h2>Legacy folder backups <HelpTip text="Unencrypted backups made before encrypted recovery points. They are kept and listed, never deleted automatically, and can be restored from the console with personaldocs restore." link="/help/backup-restore#legacy" /></h2>
          <ul>{data.legacy.slice(0, 5).map((l) => <li key={l.path}><code>{l.name}</code> · {formatDateTime(l.created_at)} · {l.files} files</li>)}</ul>
          <details><summary className="small">Legacy settings</summary><SettingsForm keys={["backup.target", "backup.require_mount", "backup.keep_daily"]} title="Legacy folder backups" /></details>
        </section>
      )}
    </>
  );
}

function PostRecovery({ data, reload }: { data: any; reload: () => void }) {
  const toast = useToast();
  const act = (body: any) => api("backup/post-recovery", { body }).then(reload).catch((e) => toast(e.message, "error"));
  return (
    <section className="card callout critical" aria-labelledby="post-rec">
      <h2 id="post-rec">After the recovery</h2>
      {data.security_review?.required && <p><strong>Security review required</strong> (Compromise/Cyberattack recovery). Change passwords, review accounts, passkeys and the sign-in map, rotate the Recovery Key. <Link to="/settings/backup?view=restores">Recovery & Security Report</Link></p>}
      {data.integrations?.active && (
        <>
          <p>External integrations stay on hold until a connection test passes. Nothing is sent or fetched through them until then.</p>
          <ul className="plain">{data.integrations.items.map((i: any) => <li key={i.key}><HealthBadge state={i.state === "verified" ? "verified" : "critical"} label={i.state_label} /> {i.label}{i.detail && <span className="small muted"> — {i.detail}</span>}
            {i.state !== "verified" && <button className="btn small" style={{ marginLeft: 8 }} onClick={() => act({ action: "accept", item: i.key })}>Accept as fixed</button>}</li>)}</ul>
          <button className="btn primary" onClick={() => act({ action: "verify" })}>Verify again</button>
        </>
      )}
    </section>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <div className="stat"><div className="small muted">{label}{hint && <HelpTip text={hint} />}</div><div className="num">{value}</div></div>;
}

export function PointTable({ points, actions }: { points: any[]; actions?: (p: any) => React.ReactNode }) {
  if (!points.length) return <p className="muted">No recovery points yet.</p>;
  return (
    <div className="table-wrap"><table className="table points-table">
      <thead><tr><th>Created</th><th>Type</th><th>Status</th><th>Copies</th><th>Size</th><th>Key</th>{actions && <th><span className="sr-only">Actions</span></th>}</tr></thead>
      <tbody>{points.map((p) => (
        <tr key={p.id}>
          <td>{formatDateTime(p.created_at)}<div className="small muted">{p.trigger === "pre_change" ? "Safety backup" : p.trigger === "manual" ? "Manual" : p.trigger === "rotation" ? "Rotation" : "Scheduled"}{p.reason ? ` · ${p.reason}` : ""}</div></td>
          <td>{p.kind === "full" ? "Full" : "Incremental"}{p.dependents > 0 && <div className="small muted">{p.dependents} incremental(s) depend on it</div>}</td>
          <td><HealthBadge state={p.status} label={{ verified: "Verified", partial: "Partially protected", warning: "Warning", failed: "Failed", running: "Running" }[p.status as string] || p.status} /></td>
          <td>{(p.copies || []).map((c: any) => <div key={c.destination} className="small"><span className={`badge ${STATE_CLASS[c.state] || "neutral"}`}>{c.label}</span> {c.destination}</div>)}</td>
          <td>{formatBytes(p.size_bytes)}</td><td>gen {p.key_generation}</td>
          {actions && <td className="row" style={{ gap: 4, flexWrap: "wrap" }}>{actions(p)}</td>}
        </tr>))}</tbody>
    </table></div>
  );
}

// ---------------------------------------------------------------- policies

function PoliciesView({ data, reload, step }: { data: Overview; reload: () => void; step: ReturnType<typeof useStepUp> }) {
  const [edit, setEdit] = useState<any | null>(null);
  return (
    <section className="card">
      <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>Policies & schedule</h2>
        <button className="btn" onClick={() => setEdit({ name: "", full_frequency: "weekly", full_weekday: "sun", full_month_day: 1, full_time: "02:30", incremental_hours: 4, retention_weeks: 4, destinations: data.destinations.map((d) => d.id), enabled: true, verify_deep: true, notify_success: false, validation_days: 0 })}>Add policy</button></div>
      <p className="small muted">Every policy backs up the whole system (database, documents and versions, OCR data, settings and encrypted secrets). Choose what to restore later, in the Recovery Explorer. Ordinary uploads and edits never start a backup; only the schedule and high-risk changes do. <a href="/help/backup-restore#policies">Learn more</a></p>
      <div className="table-wrap"><table className="table"><thead><tr><th>Policy</th><th>Schedule</th><th>Keep</th><th>Destinations</th><th>Next Full</th><th /></tr></thead>
        <tbody>{data.policies.map((p) => <tr key={p.id}><td>{p.name}{!p.enabled && <span className="badge neutral" style={{ marginLeft: 6 }}>Off</span>}</td><td>{p.describe}</td><td>{p.retention_weeks} weeks</td>
          <td>{p.destinations.map((id: number) => data.destinations.find((d) => d.id === id)?.name).filter(Boolean).join(", ") || "—"}</td>
          <td>{p.next_full ? formatDateTime(p.next_full) : "—"}</td>
          <td><button className="btn small" onClick={() => setEdit(p)}>Edit</button></td></tr>)}</tbody></table></div>
      <details className="small"><summary>Automated recovery validation (isolated database and folder)</summary>
        <SettingsForm keys={["recovery.validation_database", "recovery.validation_dir"]} title="Recovery validation" /></details>
      {edit && <PolicyDialog policy={edit} destinations={data.destinations} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); }} step={step} />}
    </section>
  );
}

function PolicyDialog({ policy, destinations, onClose, onSaved, step }: { policy: any; destinations: any[]; onClose: () => void; onSaved: () => void; step: ReturnType<typeof useStepUp> }) {
  const [p, setP] = useState({ ...policy });
  const [err, setErr] = useState("");
  const set = (k: string, v: any) => setP((x: any) => ({ ...x, [k]: v }));
  const save = () => (p.id ? api(`backup/policies/${p.id}`, { method: "PUT", body: p }) : api("backup/policies", { body: p })).then(onSaved).catch((e) => setErr(e.message));
  return (
    <Modal title={p.id ? `Edit policy “${policy.name}”` : "Add policy"} onClose={onClose} wide>
      <div className="stack">
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="form-grid">
          <div className="field"><label htmlFor="pol-name">Name</label><input id="pol-name" value={p.name} onChange={(e) => set("name", e.target.value)} /></div>
          <div className="field"><label htmlFor="pol-freq">Full backup</label>
            <select id="pol-freq" value={p.full_frequency} onChange={(e) => set("full_frequency", e.target.value)}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></div>
          {p.full_frequency === "weekly" && <div className="field"><label htmlFor="pol-day">Day</label>
            <select id="pol-day" value={p.full_weekday} onChange={(e) => set("full_weekday", e.target.value)}>{["mon", "tue", "wed", "thu", "fri", "sat", "sun"].map((d) => <option key={d} value={d}>{({ mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" } as any)[d]}</option>)}</select></div>}
          {p.full_frequency === "monthly" && <div className="field"><label htmlFor="pol-md">Day of month</label><input id="pol-md" type="number" min={1} max={31} value={p.full_month_day} onChange={(e) => set("full_month_day", Number(e.target.value))} /></div>}
          <div className="field"><label htmlFor="pol-time">Time</label><input id="pol-time" type="time" value={p.full_time} onChange={(e) => set("full_time", e.target.value)} /></div>
          <div className="field"><label htmlFor="pol-inc">Incremental every (hours, 0 = off) <HelpTip text="Incrementals store only new files and a complete database snapshot. Recommended: 4 hours." /></label><input id="pol-inc" type="number" min={0} max={168} value={p.incremental_hours} onChange={(e) => set("incremental_hours", Number(e.target.value))} /></div>
          <div className="field"><label htmlFor="pol-ret">Keep Full backups (weeks) <HelpTip text="Incrementals are kept with their Full backup. A Full backup is never deleted while an incremental needs it, and the newest usable chain is always kept." /></label><input id="pol-ret" type="number" min={1} max={520} value={p.retention_weeks} onChange={(e) => set("retention_weeks", Number(e.target.value))} /></div>
          <div className="field"><label htmlFor="pol-val">Automated recovery validation every (days, 0 = off)</label><input id="pol-val" type="number" min={0} max={365} value={p.validation_days} onChange={(e) => set("validation_days", Number(e.target.value))} /></div>
        </div>
        <fieldset className="field"><legend>Destinations (each copy is tracked separately)</legend>
          {destinations.length ? destinations.map((d) => <label key={d.id} className="check"><input type="checkbox" checked={p.destinations.includes(d.id)} onChange={(e) => set("destinations", e.target.checked ? [...p.destinations, d.id] : p.destinations.filter((x: number) => x !== d.id))} /> {d.name} <span className="small muted">({d.kind_label})</span></label>) : <p className="muted">Add a destination first.</p>}
        </fieldset>
        <label className="check"><input type="checkbox" checked={p.enabled} onChange={(e) => set("enabled", e.target.checked)} /> Policy active</label>
        <label className="check"><input type="checkbox" checked={p.notify_success} onChange={(e) => set("notify_success", e.target.checked)} /> Also notify when a scheduled backup succeeds</label>
        <div className="row" style={{ justifyContent: "space-between" }}>
          {p.id ? <button className="btn danger" onClick={() => step.run("Remove this backup policy", () => api(`backup/policies/${p.id}`, { method: "DELETE" }).then(onSaved))}>Remove policy</button> : <span />}
          <div className="row"><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save}>Save</button></div>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- destinations

const DEST_HEALTH: Record<string, [string, string]> = { healthy: ["healthy", "Connected"], unknown: ["running", "Not tested"], unavailable: ["critical", "Unavailable"],
  needs_attention: ["attention", "Needs Attention"], auth_required: ["critical", "Authentication required"], insufficient_storage: ["critical", "Insufficient Backup Storage"] };
const CAP_CLASS: Record<string, string> = { ok: "ok", warning: "warn", critical: "danger", unknown: "neutral" };
const destWhere = (d: any) => d.nas?.managed ? `${(d.nas.connection || "").toUpperCase()} · ${d.nas.server || "?"}${d.nas.connection === "nfs" ? ":" : "/"}${d.nas.share || ""} → ${d.config.path}` : (d.config.path || d.config.bucket || d.config.folder_id || d.config.folder || "—");

function DestinationsView({ data, reload, step }: { data: Overview; reload: () => void; step: ReturnType<typeof useStepUp> }) {
  const [edit, setEdit] = useState<any | null>(null);
  const [confirm, setConfirm] = useState<any | null>(null);
  const [testing, setTesting] = useState<Record<number, string>>({});
  const toast = useToast();
  const queue = useAsync<any>(() => api("backup/jobs"), []);
  const active = (queue.data?.jobs || []).some((j: any) => !["Completed", "Failed"].includes(j.state));
  useEffect(() => { if (!active) return; const t = setInterval(() => { queue.reload(); reload(); }, 4000); return () => clearInterval(t); }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  const test = async (d: any, body: any = {}) => {
    setTesting((t) => ({ ...t, [d.id]: body.action === "disconnect" ? "Disconnecting…" : "Testing…" }));
    try {
      let r = await api<any>(`backup/destinations/${d.id}/test`, { body });
      for (let i = 0; r.pending && i < 40; i++) { // the NAS mount runs in a system service; ask again until it answered
        setTesting((t) => ({ ...t, [d.id]: r.detail || "Connecting…" }));
        await new Promise((res) => setTimeout(res, 2500));
        r = await api<any>(`backup/destinations/${d.id}/test`, { body: { poll: true } });
      }
      toast(r.ok ? `“${d.name}” connected${r.free != null ? ` · ${formatBytes(r.free)} free` : ""}` : `${d.name}: ${r.category_label ? `${r.category_label} — ` : ""}${r.detail}`, r.ok ? "ok" : "error");
    } catch (e: any) { toast(e.message, "error"); }
    setTesting((t) => { const n = { ...t }; delete n[d.id]; return n; });
    reload();
  };
  const retryMigration = (d: any) => api<any>(`backup/destinations/${d.id}/retry-migration`, { body: {} }).then((r) => { toast(r.result === "migrated" ? "Migration completed — run Test Connection" : `Still needs attention: ${r.problem || "check the configuration"}`, r.result === "migrated" ? "ok" : "error"); reload(); }).catch((e) => toast(e.message, "error"));
  return (
    <section className="card">
      <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>Destinations</h2><button className="btn primary" onClick={() => setEdit({ kind: "local", name: "", config: {}, secrets: {} })}>Add destination</button></div>
      <p className="small muted">Only encrypted files ever reach a destination. Credentials are stored encrypted and are never shown again. Personal DM never deletes valid backups to make room: a full destination fails and alerts. <a href="/help/backup-restore#destinations">Learn more</a></p>
      <div className="dest-grid">
        {data.destinations.map((d) => {
          const [hs, hl] = DEST_HEALTH[d.health] || ["critical", d.health.replace(/_/g, " ")];
          const cap = d.capacity || {};
          return (
            <article key={d.id} className="dest-card" data-dest={d.name} data-health={d.health}>
              <div className="row" style={{ justifyContent: "space-between", gap: 6, flexWrap: "wrap" }}>
                <strong>{d.name}{!d.enabled && <span className="badge neutral" style={{ marginLeft: 6 }}>Off</span>}</strong>
                <HealthBadge state={hs} label={hl} />
              </div>
              <div className="small muted">{d.kind_label}{d.nas ? ` · ${d.nas.managed ? (d.nas.connection === "smb" ? "SMB / Windows share" : "NFS export") : "Already mounted"}` : ""}</div>
              <div className="small mono dest-where">{destWhere(d)}</div>
              {d.needs_attention && <div className="alert warn small" role="status"><strong>Needs Attention — Migration incomplete; existing backup data preserved.</strong> {d.health_detail.replace(/^Migration incomplete; existing backup data preserved:?\s*/, "")}</div>}
              {!d.needs_attention && d.health_detail && d.health !== "healthy" && <p className="small warn-text">{d.health_detail}</p>}
              {d.nas?.mount?.category_label && d.health !== "healthy" && <p className="small">Diagnosis: <strong>{d.nas.mount.category_label}</strong></p>}
              <dl className="dest-facts small">
                <dt>Space</dt><dd>{d.total_bytes ? <><span className={`badge ${CAP_CLASS[cap.state] || "neutral"}`} data-capacity={cap.state}>{cap.free_pct} % free</span> {formatBytes(d.free_bytes)} of {formatBytes(d.total_bytes)}</> : "Unknown until the first test"}</dd>
                <dt>Last test</dt><dd>{d.checked_at ? formatDateTime(d.checked_at) : "Never"}</dd>
                <dt>Last backup</dt><dd>{d.last_backup ? `${formatDateTime(d.last_backup.at)} · ${d.last_backup.label}` : "None yet"}</dd>
                <dt>Next backup</dt><dd>{d.next_backup ? formatDateTime(d.next_backup) : "Not in an enabled policy"}</dd>
                {d.retry && <><dt>Retry</dt><dd>Retry pending{d.retry.next_at ? ` · next attempt ${formatDateTime(d.retry.next_at)}` : ""} (attempt {d.retry.attempts})</dd></>}
              </dl>
              <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
                <button className="btn small" disabled={!!testing[d.id]} onClick={() => test(d)}>{testing[d.id] || "Test Connection"}</button>
                <button className="btn small" onClick={() => setEdit({ ...d, secrets: {}, nasIn: { ...(d.nas || {}) } })}>{d.needs_attention ? "Edit Configuration" : "Edit"}</button>
                {d.needs_attention && <button className="btn small" onClick={() => retryMigration(d)}>Retry Migration</button>}
                <button className="btn small primary" disabled={!d.enabled} onClick={() => setConfirm(d)}>Backup Now</button>
                {d.nas?.managed && d.nas?.mount?.state === "mounted" && <button className="btn small ghost" disabled={!!testing[d.id]} onClick={() => test(d, { action: "disconnect" })}>Disconnect</button>}
              </div>
              <details className="small"><summary>Details & troubleshooting</summary>
                <p>{d.nas?.mount?.message || d.health_detail || "No problems reported."}</p>
                {d.nas?.managed && <p className="muted">Mounted by Personal DM at <code>{d.config.path}</code>{d.nas.password_set ? " · password stored (encrypted)" : ""}.</p>}
                <p><a href="/help/backup-restore#nas-troubleshooting">Troubleshooting guide</a></p>
              </details>
            </article>
          );
        })}
      </div>
      {!data.destinations.length && <p className="muted">No destination yet.</p>}
      <BackupQueue jobs={queue.data?.jobs || []} />
      {edit && <DestinationDialog dest={edit} kinds={data.kinds} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); }} step={step} />}
      {confirm && <BackupNowDialog dest={confirm} warnings={data.health.warnings} onClose={() => setConfirm(null)} onQueued={() => { setConfirm(null); queue.reload(); reload(); }} />}
    </section>
  );
}

/** Durable FIFO queue: one backup or verification at a time; later ones wait their turn. Running jobs cannot be cancelled. */
function BackupQueue({ jobs }: { jobs: any[] }) {
  if (!jobs.length) return null;
  const cls: Record<string, string> = { Queued: "neutral", Preparing: "neutral", "Backing Up": "neutral", Verifying: "neutral", Completed: "ok", Failed: "danger" };
  return (
    <div className="stack" style={{ marginTop: "1rem" }} id="backup-queue">
      <h3 style={{ margin: 0 }}>Backup jobs <HelpTip id="backup.queue" /></h3>
      <div className="table-wrap"><table className="table small"><thead><tr><th>Requested</th><th>What</th><th>State</th><th>Finished</th></tr></thead>
        <tbody>{jobs.slice(0, 10).map((j) => <tr key={j.id} data-job-state={j.state}><td>{formatDateTime(j.created_at)}</td>
          <td>{j.kind === "backup_point" ? `${j.backup_kind === "incremental" ? "Incremental" : "Full"} backup${j.destinations.length ? ` → ${j.destinations.join(", ")}` : " (policy)"}` : j.kind.replace(/_/g, " ")} · {j.trigger || "scheduled"}</td>
          <td><span className={`badge ${cls[j.state] || "neutral"}`}>{j.state}</span>{j.error && <div className="small muted">{j.error}</div>}</td><td>{j.finished_at ? formatDateTime(j.finished_at) : "—"}</td></tr>)}</tbody></table></div>
      <p className="small muted">Jobs run one at a time in the order they were requested (a manual backup never jumps ahead of a scheduled one). A running backup cannot be cancelled; closing the page or signing out does not stop it.</p>
    </div>
  );
}

function BackupNowDialog({ dest, warnings, onClose, onQueued }: { dest: any; warnings: string[]; onClose: () => void; onQueued: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const cap = dest.capacity || {};
  const mine = warnings.filter((w) => w.startsWith(`${dest.name}:`));
  const go = () => { setBusy(true); api<any>(`backup/destinations/${dest.id}/backup-now`, { body: { confirm: true } })
    .then((r) => { toast(r.position ? `Backup queued — ${r.position} job(s) ahead` : "Backup started"); onQueued(); }).catch((e) => toast(e.message, "error")).finally(() => setBusy(false)); };
  return (
    <Modal title={`Backup Now → ${dest.name}`} onClose={onClose}>
      <div className="stack">
        <dl className="dest-facts small">
          <dt>Destination</dt><dd>{dest.name} ({dest.kind_label})</dd>
          <dt>Scope</dt><dd>Full system: database, every document version and original, OCR text, photos, branding, settings and protected secrets (encrypted)</dd>
          <dt>Type</dt><dd>Full recovery point, stored on this destination only and kept until you delete it</dd>
          <dt>Space</dt><dd>{dest.total_bytes ? `${formatBytes(dest.free_bytes)} free of ${formatBytes(dest.total_bytes)} (${cap.free_pct} %)` : "Unknown — run Test Connection first"}</dd>
        </dl>
        {(mine.length > 0 || dest.health !== "healthy") && <div className="alert warn small" role="status">{dest.health !== "healthy" && <div>Health: {dest.health.replace(/_/g, " ")}{dest.health_detail ? ` — ${dest.health_detail}` : ""}</div>}{mine.map((w) => <div key={w}>{w}</div>)}</div>}
        <div className="callout warn"><strong>This backup cannot be cancelled once it starts.</strong> It runs in the background (closing the page or signing out does not stop it). If another backup is running or queued, this one waits its turn.</div>
        <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={busy} onClick={go}>Start backup</button></div>
      </div>
    </Modal>
  );
}

const NAS_LABELS: Record<string, string> = { server: "NAS server", share: "Share / export", subfolder: "Folder on the share", username: "SMB username", domain: "SMB domain/workgroup", version: "Protocol version" };
const NAS_HELP: Record<string, string> = { server: "Hostname or IP address of the NAS", share: "SMB share name (e.g. backups) or NFS export path (e.g. /volume1/backups)",
  subfolder: "Created if missing; backups are written to /mnt/pdnas/<folder>", version: "Optional: SMB 3.0 / 2.1, NFS 3 / 4 / 4.1" };

function DestinationDialog({ dest, kinds, onClose, onSaved, step }: { dest: any; kinds: Overview["kinds"]; onClose: () => void; onSaved: () => void; step: ReturnType<typeof useStepUp> }) {
  const [d, setD] = useState({ ...dest, config: { connection: dest.nas?.connection || "smb", ...dest.config, ...(dest.nas?.connection ? { connection: dest.nas.connection } : {}) }, secrets: {} as Record<string, string>, nasIn: { subfolder: "personaldocs", ...(dest.nasIn || {}) } });
  const [err, setErr] = useState("");
  const kind = kinds.find((k) => k.kind === d.kind)!;
  const conn = d.config.connection || "smb";
  const managed = d.kind === "nas" && conn !== "mounted";
  const body = () => { const { nasIn, nas, ...rest } = d; return { ...rest, ...(d.kind === "nas" ? { nas: managed ? nasIn : undefined } : {}) }; };
  const save = () => (d.id ? api(`backup/destinations/${d.id}`, { method: "PUT", body: body() }) : api("backup/destinations", { body: body() })).then(onSaved).catch((e) => setErr(e.message));
  const cfgFields = kind.config.filter((f) => !["connection", "warn_pct", "crit_pct"].includes(f) && !(managed && (f === "path" || f === "require_mount")));
  const setNas = (f: string, v: string) => setD({ ...d, nasIn: { ...d.nasIn, [f]: v } });
  return (
    <Modal title={d.id ? `Edit “${dest.name}”` : "Add destination"} onClose={onClose} wide>
      <div className="stack">
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="form-grid">
          <div className="field"><label htmlFor="dst-name">Name</label><input id="dst-name" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} /></div>
          <div className="field"><label htmlFor="dst-kind">Type</label><select id="dst-kind" value={d.kind} disabled={!!d.id} onChange={(e) => setD({ ...d, kind: e.target.value, config: e.target.value === "nas" ? { connection: "smb" } : {} })}>{kinds.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}</select></div>
          {d.kind === "nas" && <div className="field"><label htmlFor="dst-connection">Connection <HelpTip id="nas.connection" /></label>
            <select id="dst-connection" value={conn} onChange={(e) => setD({ ...d, config: { ...d.config, connection: e.target.value } })}>
              <option value="smb">SMB / Windows share (mounted by Personal DM)</option><option value="nfs">NFS export (mounted by Personal DM)</option><option value="mounted">Already mounted (Proxmox bind mount or your own mount)</option></select></div>}
          {managed && ["server", "share", "subfolder", ...(conn === "smb" ? ["username", "domain"] : []), "version"].map((f) => (
            <div key={f} className="field"><label htmlFor={`dst-nas-${f}`}>{NAS_LABELS[f]}</label><input id={`dst-nas-${f}`} value={d.nasIn[f] || ""} onChange={(e) => setNas(f, e.target.value)}
              placeholder={{ server: "nas.local", share: conn === "nfs" ? "/volume1/backups" : "backups", subfolder: "personaldocs", version: conn === "nfs" ? "4.1" : "3.0", username: "backup-user" }[f] || ""} />
              {NAS_HELP[f] && <span className="small muted">{NAS_HELP[f]}</span>}</div>
          ))}
          {managed && conn === "smb" && <div className="field"><label htmlFor="dst-nas-password">SMB password{d.nas?.password_set && <span className="small muted"> (stored — leave empty to keep)</span>}</label>
            <input id="dst-nas-password" type="password" autoComplete="new-password" value={d.secrets.password || ""} onChange={(e) => setD({ ...d, secrets: { ...d.secrets, password: e.target.value } })} /></div>}
          {cfgFields.map((f) => f === "require_mount" ? (
            <label key={f} className="check"><input type="checkbox" checked={d.config[f] !== false} onChange={(e) => setD({ ...d, config: { ...d.config, [f]: e.target.checked } })} /> {FIELD_LABELS[f]}</label>
          ) : (
            <div key={f} className="field"><label htmlFor={`dst-${f}`}>{FIELD_LABELS[f] || f}</label><input id={`dst-${f}`} value={d.config[f] || ""} onChange={(e) => setD({ ...d, config: { ...d.config, [f]: e.target.value } })}
              placeholder={{ path: d.kind === "nas" ? "/mnt/nas-backup/personaldocs" : "/srv/backups/personaldocs", endpoint: "https://s3.example.com", bucket: "family-backups", folder: "Apps/PersonalDocs" }[f] || ""} /></div>
          ))}
          {kind.secrets.map((f) => <div key={f} className="field"><label htmlFor={`dst-${f}`}>{FIELD_LABELS[f] || f}{d.secrets_set?.includes(f) && <span className="small muted"> (stored — leave empty to keep)</span>}</label>
            <input id={`dst-${f}`} type="password" autoComplete="off" value={d.secrets[f] || ""} onChange={(e) => setD({ ...d, secrets: { ...d.secrets, [f]: e.target.value } })} /></div>)}
          {(d.kind === "local" || d.kind === "nas") && <>
            <div className="field"><label htmlFor="dst-warn">Space warning below (%) <HelpTip id="backup.capacity" /></label><input id="dst-warn" type="number" min={1} max={90} placeholder="20" value={d.config.warn_pct ?? ""} onChange={(e) => setD({ ...d, config: { ...d.config, warn_pct: e.target.value } })} /></div>
            <div className="field"><label htmlFor="dst-crit">Space critical below (%)</label><input id="dst-crit" type="number" min={1} max={90} placeholder="10" value={d.config.crit_pct ?? ""} onChange={(e) => setD({ ...d, config: { ...d.config, crit_pct: e.target.value } })} /></div>
          </>}
        </div>
        {managed && <p className="small muted">Personal DM mounts the share at <code>/mnt/pdnas/{d.nasIn.subfolder || "personaldocs"}</code> through its system service when you press <strong>Test Connection</strong>. Mounting NFS/SMB inside an LXC needs a privileged container with the Proxmox feature <code>mount=nfs;cifs</code>; otherwise mount the share on the Proxmox host and choose <em>Already mounted</em>. <a href="/help/backup-restore#nas">Learn more</a></p>}
        {d.kind === "nas" && !managed && <p className="small muted">The folder must be on a mounted share and contain the marker file <code>.personaldocs-backup-target</code>.</p>}
        {(d.kind === "gdrive" || d.kind === "onedrive") && <div className="callout info">Uses your own OAuth app (client id/secret) and a refresh token with access to one folder. See <a href={`/help/backup-restore#${d.kind}`}>the guide</a> for the exact steps.</div>}
        <label className="check"><input type="checkbox" checked={d.enabled !== false} onChange={(e) => setD({ ...d, enabled: e.target.checked })} /> Enabled</label>
        <div className="row" style={{ justifyContent: "space-between" }}>
          {d.id ? <button className="btn danger" onClick={() => step.run("Remove this backup destination", () => api(`backup/destinations/${d.id}`, { method: "DELETE", body: { confirm: true } }).then(onSaved))}>Remove</button> : <span />}
          <div className="row"><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save}>Save</button></div>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- recovery points

function PointsView({ data, reload, step }: { data: Overview; reload: () => void; step: ReturnType<typeof useStepUp> }) {
  const toast = useToast();
  const [del, setDel] = useState<any | null>(null);
  const [detail, setDetail] = useState<any | null>(null);
  const action = (p: any, a: string) => api(`backup/points/${p.id}/${a}`, { method: "POST" }).then(() => { toast(a === "verify" ? "Deep verification started" : "Test Restore started"); reload(); }).catch((e) => toast(e.message, "error"));
  const download = (p: any) => step.run("Download a complete encrypted backup package", async () => {
    const r = await fetch(`/api/backup/points/${p.id}/download`, { credentials: "same-origin" });
    if (r.status === 403) { const j = await r.json(); throw Object.assign(new Error(j.error), { data: j }); }
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "Download failed");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await r.blob());
    a.download = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "personaldocs-recovery.tar";
    a.click();
    URL.revokeObjectURL(a.href);
  });
  return (
    <section className="card">
      <h2>Recovery points</h2>
      <p className="small muted">Deep verification reads every copy back, authenticates each encrypted file, checks the manifest, the database dump, the secrets package and the chain. A Test Restore also restores the database into a temporary database when allowed. <a href="/help/backup-restore#verification">Learn more</a></p>
      <PointTable points={data.points} actions={(p) => <>
        <button className="btn small" onClick={() => setDetail(p)}>Details</button>
        <button className="btn small" onClick={() => action(p, "verify")}>Verify</button>
        <button className="btn small" onClick={() => action(p, "test-restore")}>Test Restore</button>
        <button className="btn small" onClick={() => download(p)}>Download</button>
        <button className="btn small danger" onClick={() => api(`backup/points/${p.id}/delete`).then(setDel)}>Delete</button></>} />
      {detail && <Modal title="Recovery point details" onClose={() => setDetail(null)} wide><PointDetail p={detail} /></Modal>}
      {del && <DeleteDialog preview={del} onClose={() => setDel(null)} onDone={() => { setDel(null); reload(); }} step={step} />}
    </section>
  );
}

function PointDetail({ p }: { p: any }) {
  return (
    <div className="stack">
      <p>{p.kind === "full" ? "Full" : "Incremental"} · {formatDateTime(p.created_at)} · key generation {p.key_generation} · app {p.app_version}</p>
      {p.counts && <p className="small">{p.counts.users} accounts · {p.counts.folders} folders · {p.counts.documents} documents · {p.counts.versions} versions · {p.counts.objects_new} new files in this point</p>}
      {Object.entries(p.verification || {}).map(([dest, v]: any) => (
        <div key={dest}><h3>{(p.copies.find((c: any) => String(c.destination_id) === dest) || {}).destination || "Copy"} — {v.status}</h3>
          <ul className="plain">{(v.checks || []).map((c: any) => <li key={c.check}><Icon name={c.ok ? "check" : "alert"} size={14} /> {c.check}{c.detail && <span className="small muted"> — {c.detail}</span>}</li>)}</ul></div>
      ))}
      {p.warnings?.length > 0 && <div className="callout warning">{p.warnings.join("; ")}</div>}
    </div>
  );
}

function DeleteDialog({ preview, onClose, onDone, step }: { preview: any; onClose: () => void; onDone: () => void; step: ReturnType<typeof useStepUp> }) {
  const [withDeps, setWithDeps] = useState(false);
  const p = preview.point;
  return (
    <Modal title="Delete recovery point" onClose={onClose}>
      <div className="stack">
        <p><strong>{p.kind === "full" ? "Full" : "Incremental"} backup of {formatDateTime(p.created_at)}</strong> · {formatBytes(p.size_bytes)} · {p.copies.length} copies</p>
        {preview.dependents.length > 0 && <div className="callout warning">{preview.dependents.length} later recovery point(s) depend on it and would become unusable. They can only be deleted together.
          <label className="check"><input type="checkbox" checked={withDeps} onChange={(e) => setWithDeps(e.target.checked)} /> Also delete the {preview.dependents.length} dependent point(s)</label></div>}
        <p className="small">After deletion {preview.coverage.remaining_points} verified point(s) remain{preview.coverage.oldest_remaining ? `, from ${formatDateTime(preview.coverage.oldest_remaining)}` : ""}. {preview.coverage.warning}</p>
        <p className="small muted">{preview.note} Deletion needs step-up authentication, is audited and sends a security notification.</p>
        <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn danger" disabled={preview.dependents.length > 0 && !withDeps} onClick={() => step.run("Delete a recovery point", () => api(`backup/points/${p.id}/delete`, { body: { include_dependents: withDeps } }).then(onDone))}>Delete</button></div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- Recovery Key and Emergency Recovery Package

function KeyView({ data, reload, step }: { data: Overview; reload: () => void; step: ReturnType<typeof useStepUp> }) {
  const toast = useToast();
  const [shown, setShown] = useState<{ key: string; until: number } | null>(null);
  const [exporting, setExporting] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [left, setLeft] = useState(0);
  const timer = useRef<number>();
  useEffect(() => {
    if (!shown) return;
    timer.current = window.setInterval(() => {
      const s = Math.max(0, Math.round((shown.until - Date.now()) / 1000));
      setLeft(s);
      if (s === 0) setShown(null);  // auto-hide
    }, 500);
    return () => window.clearInterval(timer.current);
  }, [shown]);
  const reveal = () => step.run("Reveal the Backup Recovery Key", () => api("backup/key/reveal", { method: "POST" }).then((r) => setShown({ key: r.key, until: Date.now() + r.hide_after_seconds * 1000 })));
  const r = data.health.readiness;
  return (
    <>
      <section className="card">
        <h2>Backup Recovery Key</h2>
        <div className="callout critical"><strong>Anyone with this key and a copy of your backups can read every family document.</strong> Personal DM shows it only to the main administrator after step-up authentication, hides it again after a minute, never logs or sends it, and notifies you each time it is revealed. <a href="/help/backup-restore#recovery-key">Learn more</a></div>
        {data.key ? <p>Current key: generation <strong>{data.key.generation}</strong> · fingerprint <code>{data.key.fingerprint}</code> (the fingerprint is not secret; it lets you check you hold the right key)</p>
          : <p className="muted">The key is created with the first encrypted backup.</p>}
        {data.retiring.length > 0 && <div className="callout warning">Rotation incomplete: generation(s) {data.retiring.join(", ")} still protect copies on unreachable destinations. The old key stays usable until they are migrated. <button className="btn small" onClick={() => step.run("Retry the key rotation", () => api("backup/key/rotate", { body: { retry: true } }).then(() => { toast("Retry started"); reload(); }))}>Retry rotation</button></div>}
        {shown ? (
          <div className="key-reveal" role="group" aria-label="Backup Recovery Key">
            <code className="key-text">{shown.key}</code>
            <div className="row" style={{ gap: 8 }}><button className="btn small" onClick={() => { navigator.clipboard?.writeText(shown.key).then(() => { toast("Key copied. The clipboard is cleared in 30 seconds."); setTimeout(() => navigator.clipboard?.writeText(""), 30000); }); }}>Copy</button>
              <button className="btn small" onClick={() => setShown(null)}>Hide now</button><span className="small muted">Hides in {left} s</span></div>
          </div>
        ) : <button className="btn" disabled={!data.key} onClick={reveal}>Reveal Recovery Key…</button>}
      </section>
      <section className="card">
        <h2>Emergency Recovery Package <HealthBadge state={r.state === "ready" ? "verified" : r.state === "no_key" ? "running" : "critical"} label={r.label} /></h2>
        <p>An offline file with the Recovery Key, sealed with a passphrase you choose. Store it on a USB stick in a safe or in a password vault — not next to your backups. Personal DM records only that and when you exported it, never where you keep it.</p>
        {r.exported_at && <p className="small muted">Last export: {formatDateTime(r.exported_at)} (key generation {r.exported_generation})</p>}
        <button className="btn primary" disabled={!data.key} onClick={() => setExporting(true)}>Export Emergency Recovery Package…</button>
      </section>
      <section className="card">
        <h2>Rotate Recovery Key</h2>
        <p>Creates a new key generation, makes a safety backup, re-encrypts every reachable retained backup with the new key, verifies each copy, and only then removes the old copies. Destinations that cannot be reached are listed; the old key stays usable for them. Export a new Emergency Recovery Package afterwards.</p>
        {data.rotation && <p className="small">Last rotation: <span className={`badge ${STATE_CLASS[data.rotation.status === "complete" ? "verified" : data.rotation.status === "partial" ? "partial" : data.rotation.status === "running" ? "running" : "failed"]}`}>{data.rotation.status}</span> {formatDateTime(data.rotation.started_at)}
          {data.rotation.results.filter((x: any) => x.state !== "migrated").length > 0 && <> · not migrated: {Array.from(new Set(data.rotation.results.filter((x: any) => x.state !== "migrated").map((x: any) => x.destination))).join(", ")}</>}</p>}
        <button className="btn danger" disabled={!data.key || data.running.length > 0} onClick={() => setConfirmRotate(true)}>Rotate Recovery Key…</button>
      </section>
      {exporting && <EmergencyDialog onClose={() => setExporting(false)} onDone={() => { setExporting(false); reload(); }} step={step} />}
      {confirmRotate && <Modal title="Rotate the Backup Recovery Key?" onClose={() => setConfirmRotate(false)}><div className="stack">
        <p>All retained backups are re-encrypted. This can take a while for large libraries and runs in the background. You will need to export a new Emergency Recovery Package.</p>
        <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn" onClick={() => setConfirmRotate(false)}>Cancel</button>
          <button className="btn danger" onClick={() => { setConfirmRotate(false); step.run("Rotate the Backup Recovery Key", () => api("backup/key/rotate", { method: "POST" }).then(() => { toast("Key rotation started"); reload(); })); }}>Rotate</button></div></div></Modal>}
    </>
  );
}

function EmergencyDialog({ onClose, onDone, step }: { onClose: () => void; onDone: () => void; step: ReturnType<typeof useStepUp> }) {
  const [pp, setPp] = useState("");
  const [pp2, setPp2] = useState("");
  const toast = useToast();
  const go = () => step.run("Export the Emergency Recovery Package", async () => {
    const res = await fetch("/api/backup/emergency", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "") }, body: JSON.stringify({ passphrase: pp, confirm: pp2 }) });
    if (!res.ok) { const j = await res.json(); throw Object.assign(new Error(j.error), { data: j }); }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = (res.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "personaldocs-emergency-recovery.pdrp";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("Emergency Recovery Package downloaded. Move it to offline storage.");
    onDone();
  });
  return (
    <Modal title="Export Emergency Recovery Package" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); go(); }}>
        <p className="small">Choose a passphrase of at least 12 characters. Nobody — including Personal DM — can recover it. Write it down separately from the file.</p>
        <div className="field"><label htmlFor="erp-1">Passphrase</label><input id="erp-1" type="password" autoComplete="new-password" value={pp} onChange={(e) => setPp(e.target.value)} /></div>
        <div className="field"><label htmlFor="erp-2">Repeat passphrase</label><input id="erp-2" type="password" autoComplete="new-password" value={pp2} onChange={(e) => setPp2(e.target.value)} /></div>
        {pp && pp.length < 12 && <p className="small" role="status">At least 12 characters.</p>}
        <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={pp.length < 12 || pp !== pp2}>Export</button></div>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------- restores and reports

function RestoresView({ data }: { data: Overview }) {
  const runs = useAsync<any>(() => api("recovery/runs"), []);
  const [open, setOpen] = useState<any | null>(null);
  const all = [...(data.restores || []), ...((runs.data?.runs || []).filter((r: any) => !["full", "test", "validation"].includes(r.kind)))];
  return (
    <section className="card">
      <h2>Restores & reports</h2>
      <p className="small muted">Every restore is audited. Full-system recoveries create a Recovery & Security Report (never containing passwords, keys, tokens or webhook addresses). <a href="/help/disaster-recovery#report">Learn more</a></p>
      {all.length ? <div className="table-wrap"><table className="table"><thead><tr><th>When</th><th>Type</th><th>Status</th><th>Recovery point</th><th>By</th><th /></tr></thead>
        <tbody>{all.map((r: any) => <tr key={r.id}><td>{formatDateTime(r.created_at)}</td><td>{({ full: "Full system", test: "Test Restore", validation: "Recovery validation" } as any)[r.kind] || r.kind}{r.recovery_mode ? ` (${r.recovery_mode})` : ""}</td>
          <td><HealthBadge state={r.status === "completed" ? "verified" : r.status === "running" ? "running" : "failed"} label={r.status} />{r.summary && <div className="small muted">{r.summary}</div>}</td><td>{r.point_label}</td><td>{r.actor}</td>
          <td><button className="btn small" onClick={() => api(`recovery/runs/${r.id}`).then(setOpen)}>Open</button></td></tr>)}</tbody></table></div> : <p className="muted">No restores yet.</p>}
      {open && <Modal title={open.kind === "full" ? "Recovery & Security Report" : "Restore details"} onClose={() => setOpen(null)} wide><ReportView run={open} /></Modal>}
    </section>
  );
}

export function ReportView({ run }: { run: any }) {
  const rep = run.report || {};
  const checks = run.result?.checks || rep.checks || [];
  return (
    <div className="stack report">
      {rep.mode && <p><strong>Mode:</strong> {rep.mode === "compromise" ? "Compromise / cyberattack recovery" : "Normal disaster recovery"} · <strong>Restore point:</strong> {rep.restore_point?.kind} {formatDateTime(rep.restore_point?.created_at)}</p>}
      {rep.restored && <p className="small">{rep.restored.users} accounts · {rep.restored.folders} folders · {rep.restored.documents} documents · {rep.restored.versions} versions · {rep.restored.files?.restored} files</p>}
      {checks.length > 0 && <><h3>Checks</h3><ul className="plain">{checks.map((c: any) => <li key={c.check}><Icon name={c.ok ? "check" : "alert"} size={14} /> {c.check}{c.detail && <span className="small muted"> — {c.detail}</span>}</li>)}</ul></>}
      {rep.integrations?.length > 0 && <><h3>Integrations</h3><ul className="plain">{rep.integrations.map((i: any) => <li key={i.key}>{i.label}: <strong>{i.state_label}</strong>{i.detail && <span className="small muted"> — {i.detail}</span>}</li>)}</ul></>}
      {rep.session_and_device_trust && <p className="small"><strong>Sessions and device trust:</strong> {rep.session_and_device_trust.sessions || `${rep.session_and_device_trust.sessions_ended ?? 0} sessions ended, ${rep.session_and_device_trust.devices_untrusted ?? 0} devices untrusted, ${rep.session_and_device_trust.mfa || ""}`}</p>}
      {rep.follow_up?.length > 0 && <><h3>Recommended follow-up</h3><ol>{rep.follow_up.map((f: string) => <li key={f}>{f}</li>)}</ol></>}
      {run.impact && !rep.mode && <ImpactView impact={run.impact} />}
      {run.result?.failed?.length > 0 && <div className="callout warning">Failed items: {run.result.failed.map((f: any) => `${f.item} (${f.error})`).join("; ")}</div>}
      <a className="btn small" href={`/api/recovery/runs/${run.id}?export=1`}>Export report (JSON)</a>
    </div>
  );
}

export function ImpactView({ impact }: { impact: any }) {
  const c = impact.counts || {};
  return (
    <div className="stack impact">
      <div className="stat-grid">
        <div className="stat"><div className="small muted">Documents re-created</div><div className="num">{c.documents_create ?? 0}</div></div>
        <div className="stat"><div className="small muted">Existing documents</div><div className="num">{c.documents_existing ?? 0}</div></div>
        <div className="stat"><div className="small muted">Versions restored</div><div className="num">{c.versions_restore ?? 0}</div></div>
        <div className="stat"><div className="small muted">Folders re-created</div><div className="num">{c.folders_create ?? 0}</div></div>
        <div className="stat"><div className="small muted">Space needed</div><div className="num">{formatBytes(impact.storage?.bytes_needed)}</div></div>
      </div>
      {impact.conflicts?.length > 0 && <div className="callout warning"><strong>Conflicts:</strong> {impact.conflicts.map((x: any) => `${x.document} — ${x.reason}`).join("; ")}</div>}
      {impact.newer_current?.length > 0 && <div className="callout info"><strong>Current items newer than the backup:</strong> {impact.newer_current.map((x: any) => x.document).join(", ")}</div>}
      {impact.replaces_current?.length > 0 && <div className="callout warning"><strong>Will become the current version again:</strong> {impact.replaces_current.join(", ")} (the present version stays in the history)</div>}
      {impact.permission_differences?.length > 0 && <div className="callout info"><strong>Permission differences:</strong> {impact.permission_differences.map((x: any) => `${x.folder}: ${x.only_in_backup} only in the backup, ${x.only_now} only now`).join("; ")}. {impact.permission_differences[0].note}</div>}
      <p className="small"><strong>{impact.deletion_note}</strong>{impact.storage && !impact.storage.ok && " Not enough free disk space for this restore."}</p>
      {impact.actions?.length > 0 && <details><summary>Planned actions ({impact.actions.length})</summary><ul>{impact.actions.map((a: string, i: number) => <li key={i}>{a}</li>)}</ul></details>}
      {impact.warnings?.length > 0 && <ul className="warn-list">{impact.warnings.map((w: string) => <li key={w}>{w}</li>)}</ul>}
    </div>
  );
}
