import { useEffect, useState } from "react";
import OcrTypes from "./OcrTypes";
import DocumentTypesAdmin from "./DocumentTypes";
import { api, formatBytes, formatDateTime } from "../../api";
import SettingsForm from "../../components/SettingsForm";
import AuthentikAdmin from "./Authentik";
import { CopyButton, Icon, Skeleton, useAsync, useToast } from "../../components/ui";
import type { Meta } from "../../types";

export function DocumentsPanel() {
  const toast = useToast();
  const meta = useAsync(() => api<Meta>("metadata"), []);
  const [kind, setKind] = useState("tag");
  const [name, setName] = useState("");
  const [ftype, setFtype] = useState("text");
  return (
    <div className="stack">
      <SettingsForm section="documents" title="Documents & folders" />
      <DocumentTypesAdmin />
      <div className="card">
        <h2>Tags, issuers and custom fields</h2>
        <p className="small muted">None of these are mandatory. Custom fields here can be added to any document as an additional detail; fields that belong to a type are set in its template above.</p>
        {meta.data ? (
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
            <div><h3>Tags</h3><div className="row">{meta.data.tags.map((t) => <span key={t.id} className="badge">{t.name} <button className="icon-btn" style={{ minWidth: 18, minHeight: 18, padding: 0 }} aria-label={`Remove tag ${t.name}`} onClick={() => api(`metadata/tag/${t.id}`, { method: "DELETE" }).then(meta.reload)}>×</button></span>)}</div>
              <h3 style={{ marginTop: "1rem" }}>Custom fields</h3><ul className="small">{meta.data.fields.map((f) => <li key={f.key}>{f.label} ({f.type}{f.choices.length ? `: ${f.choices.join(", ")}` : ""})</li>)}</ul></div>
          </div>
        ) : <Skeleton />}
        <form className="row" onSubmit={(e) => { e.preventDefault(); api("metadata", { body: { kind, name, type: ftype } }).then(() => { setName(""); meta.reload(); toast("Added"); }).catch((x) => toast(x.message, "error")); }}>
          <select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)} style={{ maxWidth: 170 }}><option value="tag">Tag</option><option value="correspondent">Issuer</option><option value="field">Custom field</option></select>
          <input aria-label="Name" type="text" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 220 }} />
          {kind === "field" && <select aria-label="Field type" value={ftype} onChange={(e) => setFtype(e.target.value)} style={{ maxWidth: 140 }}>{["text", "date", "number", "boolean", "choice"].map((t) => <option key={t}>{t}</option>)}</select>}
          <button className="btn" disabled={!name}>Add</button>
        </form>
      </div>
    </div>
  );
}

function JobsCard() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<any>("jobs"), []);
  if (!data) return <Skeleton />;
  return (
    <div className="card">
      <h2>Processing queue <button className="btn small" onClick={reload}><Icon name="refresh" size={16} /> Refresh</button></h2>
      <p>{data.counts.queued} queued · {data.counts.running} running · {data.counts.failed} failed</p>
      <table className="responsive"><thead><tr><th>Job</th><th>Status</th><th>When</th><th /></tr></thead><tbody>
        {data.jobs.slice(0, 30).map((j: any) => (
          <tr key={j.id}><td>{j.kind}{j.error && <div className="small error-text" style={{ whiteSpace: "pre-wrap" }}>{j.error.split("\n")[0]}</div>}</td><td><span className={`badge ${j.status === "failed" ? "danger" : j.status === "done" ? "ok" : "neutral"}`}>{j.status}</span> <span className="small muted">×{j.attempts}</span></td>
            <td className="small">{formatDateTime(j.finished_at || j.created_at)}</td><td>{j.status === "failed" && <button className="btn small" onClick={() => api(`jobs/${j.id}/retry`, { method: "POST" }).then(() => { toast("Retrying"); reload(); })}>Retry</button>}</td></tr>
        ))}
      </tbody></table>
    </div>
  );
}

export function ProcessingPanel() {
  return <div className="stack"><SettingsForm section="processing" title="OCR & processing" /><OcrTypes /><JobsCard /></div>;
}

function DeliveryProblems() {
  const { data } = useAsync(() => api<any>("notifications/problems"), []);
  if (!data) return null;
  return (
    <div className="card">
      <h2>Delivery problems</h2>
      {data.unconfigured.length > 0 && (
        <div className="alert warn">Critical notifications are set to use {data.unconfigured.map((u: any) => u.channel === "email" ? "Email" : "Telegram").join(" and ")}, which {data.unconfigured.length > 1 ? "are" : "is"} not configured yet (Settings → Connections). Until then they are recorded as skipped and only delivered in-app — or remove the channel from “Channels for critical notifications”.</div>
      )}
      {data.people.length === 0 ? <p className="muted">Every active person can receive the required notifications.</p> : (
        <>
          <p className="small muted">These people would miss required (critical or reminder) notifications on some channels. Messages for them are recorded as “skipped” with the reason — never as sent.</p>
          <table className="responsive"><thead><tr><th>Person</th><th>Problem</th></tr></thead><tbody>
            {data.people.map((p: any) => <tr key={p.username}><td>{p.user}</td><td>{p.problems.map((x: any) => <div key={x.channel} className="small">{x.channel}: {x.issue}</div>)}</td></tr>)}
          </tbody></table>
        </>
      )}
      {data.skipped_messages > 0 && <p className="small muted">{data.skipped_messages} external message(s) were skipped in total; see Delivery history.</p>}
    </div>
  );
}

export function NotificationsAdmin() {
  const toast = useToast();
  const preview = useAsync(() => api<any>("notifications/preview"), []);
  const hist = useAsync(() => api<{ deliveries: any[] }>("notifications/deliveries"), []);
  return (
    <div className="stack">
      <SettingsForm section="notifications" title="Notification policy">
        <div className="alert small">Expiry reminders go to the document owner and the head of their reminder group (plus delegates with “receive reminders”), once per threshold, and stop after the expiry day. Only confirmed expiry dates count. Critical notifications cannot be turned off by family members; everything else is chosen by each person under My account → Notifications.</div>
      </SettingsForm>
      <DeliveryProblems />
      <div className="grid two-col">
        <div className="card">
          <h2>Message preview</h2>
          {preview.data && <><p><strong>{preview.data.subject}</strong></p><pre className="preview-text small">{preview.data.body}</pre><p className="small muted">{preview.data.note}</p></>}
          <button className="btn" onClick={() => api("notifications/run", { method: "POST" }).then((r) => { toast(`${r.reminders} reminder(s) queued, ${r.sent} delivered`); hist.reload(); })}>Run reminder check now</button>
        </div>
        <div className="card">
          <h2>Delivery history</h2>
          {hist.data ? hist.data.deliveries.length === 0 ? <p className="muted">No external deliveries yet.</p> : (
            <table className="responsive"><tbody>{hist.data.deliveries.slice(0, 30).map((d) => <tr key={d.id}><td className="small">{formatDateTime(d.created_at)}<br />{d.user} · {d.channel}</td><td><span className={`badge ${d.status === "sent" ? "ok" : d.status === "failed" ? "danger" : "neutral"}`}>{d.status}</span>{d.error && <div className="small muted">{d.error}</div>}</td></tr>)}</tbody></table>
          ) : <Skeleton />}
        </div>
      </div>
    </div>
  );
}

export function ConnectionsPanel() {
  const toast = useToast();
  const connectors = useAsync(() => api<{ accounts: any[] }>("admin/email-connectors"), []);
  const test = (channel: string) => api("notifications/test", { body: { channel } }).then((r) => toast(r.detail)).catch((e) => toast(e.message, "error"));
  return (
    <div className="stack">
      <SettingsForm keys={["smtp.enabled", "smtp.host", "smtp.port", "smtp.security", "smtp.username", "smtp.password", "smtp.from_address"]} title="Email (SMTP)">
        <button className="btn" onClick={() => test("email")}>Send test email to me</button>
      </SettingsForm>
      <SettingsForm keys={["telegram.enabled", "telegram.bot_token", "telegram.bot_username"]} title="Telegram">
        <button className="btn" onClick={() => test("telegram")}>Test connection</button>
      </SettingsForm>
      <div className="card row between"><div><h2>WhatsApp</h2><p className="small muted">Personal WhatsApp notifications are planned for a later release. Nothing is sent via WhatsApp today.</p></div><span className="badge neutral">Planned</span></div>
      <div className="card">
        <h2>Personal email-import connectors</h2>
        <p className="small muted">Family members configure their own mailboxes. You can disable a malfunctioning connector; you never see its password.</p>
        {connectors.data?.accounts.length === 0 && <p className="muted">None configured.</p>}
        {connectors.data?.accounts.map((a) => (
          <div key={a.id} className="row between list-item"><span>{a.user} · {a.label} ({a.host}) {a.last_error && <span className="small error-text">{a.last_error}</span>}</span>
            <button className="btn small" onClick={() => api("admin/email-connectors", { body: { id: a.id, disabled: !a.disabled_by_admin } }).then(connectors.reload)}>{a.disabled_by_admin ? "Re-enable" : "Disable"}</button></div>
        ))}
      </div>
    </div>
  );
}

export function AuthPanel() {
  const diag = useAsync(() => api<any>("auth/google/diagnostics"), []);
  return (
    <div className="stack">
      <SettingsForm keys={["auth.session_days", "auth.reset_token_minutes", "auth.login_rate_limit"]} title="Passwords & sessions">
        <p className="small muted">Authenticator apps (TOTP) are optional for each person and configured in their own account. Administrator-issued passwords must be changed at first sign-in. A locked-out main administrator recovers with <code>personaldocs recover-admin</code> on the server console.</p>
      </SettingsForm>
      <SettingsForm keys={["google.enabled", "google.client_id", "google.client_secret"]} title="Google sign-in">
        {diag.data && (
          <div className="stack" style={{ marginTop: ".8rem" }}>
            <div><strong>Authorised redirect URI</strong> (register exactly this in Google Cloud Console):<div className="row"><code>{diag.data.callback_url}</code><CopyButton label="Callback URL" getValue={() => diag.data.callback_url} /></div></div>
            <ul className="small">{diag.data.checks.map((c: any) => <li key={c.name}>{c.ok ? "✅" : "❌"} {c.name}{c.detail ? ` — ${c.detail}` : ""}</li>)}</ul>
            <p className="small muted">{diag.data.note} <a href="/help/google">Google setup guide</a></p>
            <button className="btn small" onClick={diag.reload}>Re-run checks</button>
          </div>
        )}
      </SettingsForm>
      <AuthentikAdmin />
    </div>
  );
}

function NasCard({ onChange }: { onChange: () => void }) {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<{ status: any; mount_point: string }>("backup/nas"), []);
  const state = data?.status?.state;
  useEffect(() => {
    if (state !== "pending") return;
    const t = setTimeout(() => { reload(); onChange(); }, 2500);
    return () => clearTimeout(t);
  }, [data]);
  const act = (action: string) => api("backup/nas", { body: { action } }).then(() => { reload(); }).catch((e) => toast(e.message, "error"));
  const badge: Record<string, [string, string]> = {
    mounted: ["ok", "Connected"], pending: ["neutral", "Connecting…"], error: ["danger", "Problem"],
    unmounted: ["neutral", "Disconnected"], not_configured: ["neutral", "Not connected"],
  };
  const [cls, label] = badge[state] || ["neutral", state || "…"];
  return (
    <SettingsForm keys={["nas.type", "nas.server", "nas.share", "nas.subfolder", "nas.username", "nas.password", "nas.domain", "nas.version"]} title="NAS connection">
      <div className="card" style={{ marginTop: ".8rem", background: "var(--brand-softer)" }} role="status" aria-live="polite">
        <div className="row between">
          <div className="row"><strong>Status:</strong> <span className={`badge ${cls}`}>{label}</span></div>
          <div className="row">
            <button className="btn primary" disabled={state === "pending"} onClick={() => act("mount")}>Connect NAS</button>
            {state === "mounted" && <button className="btn" onClick={() => act("unmount")}>Disconnect</button>}
          </div>
        </div>
        {data?.status?.message && <p className="small" style={{ marginTop: ".4rem" }}>{data.status.message}</p>}
        {data?.status?.free_bytes !== undefined && state === "mounted" && <p className="small muted">{formatBytes(data.status.free_bytes)} free of {formatBytes(data.status.total_bytes)}</p>}
        {data?.status?.detail && <details><summary className="small">Technical details</summary><pre className="preview-text small">{data.status.detail}</pre></details>}
        <p className="small muted">Save the fields above first, then press Connect NAS. The share is mounted at {data?.mount_point || "/mnt/pdnas"} and used as the backup destination. NFS/SMB mounting needs a privileged container with the Proxmox feature mount=nfs;cifs — otherwise choose “Already mounted” and enter the folder in Backup settings. <a href="/help/backup-restore#nas">Help</a></p>
      </div>
    </SettingsForm>
  );
}

export function StoragePanel() {
  const toast = useToast();
  const st = useAsync(() => api<any>("backup"), []);
  const integ = useAsync(() => api<any>("integrity"), []);
  const [plan, setPlan] = useState<string[] | null>(null);
  return (
    <div className="stack">
      {st.data && (
        <div className="card">
          <h2>Backup status <button className="btn small primary" disabled={!st.data.destination.ok || st.data.running} onClick={() => api("backup/run", { method: "POST" }).then(() => { toast("Backup started"); st.reload(); }).catch((e) => toast(e.message, "error"))}>{st.data.running ? "Backup running…" : "Back up now"}</button></h2>
          <p>Destination: {st.data.target || "not configured"} — {st.data.destination.ok ? <span className="badge ok">Reachable</span> : <span className="badge danger">Not available</span>}</p>
          {!st.data.destination.ok && <div className="alert warn">{st.data.destination.error}</div>}
          <p>Last success: {st.data.status.last_success ? formatDateTime(st.data.status.last_success) : "never"} {st.data.status.last_verified === true && <span className="badge ok">Verified</span>}
            {st.data.status.last_bytes !== undefined && <span className="muted small"> · {formatBytes(st.data.status.last_bytes)} in {st.data.status.last_seconds}s</span>}</p>
          {st.data.status.last_error && <div className="alert error">Last attempt failed{st.data.status.last_failure ? ` (${formatDateTime(st.data.status.last_failure)})` : ""}: {st.data.status.last_error}</div>}
          <p>Schedule: <strong>{st.data.schedule}</strong>{st.data.next_run && <> · next backup {formatDateTime(st.data.next_run)}</>} · keeps the last {st.data.keep} successful backups</p>
          <p className="small muted">Restores are done from the server console (<code>personaldocs restore</code>) so a web session can never overwrite the library. A Proxmox snapshot is a useful extra layer but is not a verified application backup.</p>
        </div>
      )}
      <NasCard onChange={st.reload} />
      <SettingsForm keys={["backup.target", "backup.require_mount", "backup.enabled", "backup.frequency", "backup.weekday", "backup.month_day", "backup.schedule_time", "backup.keep_daily", "backup.include_keys"]} title="Backup settings" />
      <div className="card">
        <h2>Integrity check</h2>
        <p className="small muted">Looks for missing or altered originals, broken version references and orphaned files. Repairs never delete originals or regenerate keys.</p>
        {integ.data?.report ? (
          <div>
            <p>Last check {formatDateTime(integ.data.report.checked_at)}: {integ.data.report.ok ? <span className="badge ok">No problems</span> : <span className="badge danger">{integ.data.report.problem_count} problems</span>} ({integ.data.report.versions} files)</p>
            {!integ.data.report.ok && <ul className="small">{integ.data.report.problems.slice(0, 20).map((p: any, i: number) => <li key={i}>{p.type.replace(/_/g, " ")} {p.path || p.document}</li>)}</ul>}
          </div>
        ) : <p className="muted">No check has run yet.</p>}
        <div className="row">
          <button className="btn" onClick={() => api("integrity", { body: { checksums: true } }).then(() => toast("Check queued — refresh in a moment"))}>Run full check</button>
          <button className="btn" onClick={() => api("integrity", { body: { repair: true } }).then((r) => setPlan(r.actions))}>Plan repairs</button>
          <button className="btn small" onClick={integ.reload}>Refresh</button>
        </div>
        {plan && (
          <div className="stack" style={{ marginTop: ".8rem" }}>
            {plan.length === 0 ? <p>Nothing to repair.</p> : <ul className="small">{plan.map((a, i) => <li key={i}>{a}</li>)}</ul>}
            {plan.some((a) => !a.startsWith("MANUAL")) && <button className="btn primary" onClick={() => api("integrity", { body: { repair: true, confirm: true } }).then(() => { toast("Safe repairs applied"); setPlan(null); integ.reload(); })}>Apply safe repairs</button>}
          </div>
        )}
      </div>
    </div>
  );
}

export function ActivityPanel() {
  const [filter, setFilter] = useState({ action: "", outcome: "" });
  const [offset, setOffset] = useState(0);
  const log = useAsync(() => api<{ events: any[]; total: number }>("audit", { query: { ...filter, offset } }), [filter.action, filter.outcome, offset]);
  const health = useAsync(() => api<any>("admin/health"), []);
  return (
    <div className="stack">
      {health.data && (
        <div className="card">
          <h2>Health</h2>
          <div className="row">
            {Object.entries(health.data.services).map(([k, v]) => <span key={k} className={`badge ${v ? "ok" : "danger"}`}>{v ? "✓" : "✗"} {k}</span>)}
            {Object.entries(health.data.tools).map(([k, v]) => <span key={k} className={`badge ${v ? "ok" : "danger"}`}>{v ? "✓" : "✗"} {k}</span>)}
            <span className={`badge ${health.data.disk.low ? "danger" : "ok"}`}>Disk: {formatBytes(health.data.disk.free)} free of {formatBytes(health.data.disk.total)}</span>
            <span className={`badge ${health.data.jobs.failed ? "danger" : "ok"}`}>{health.data.jobs.failed} failed jobs</span>
          </div>
          <p className="small muted">Version {health.data.version} · public address {health.data.public_origin}. For a full redacted diagnostic run <code>personaldocs doctor</code> on the server.</p>
        </div>
      )}
      <SettingsForm section="activity" title="Retention" />
      <div className="card">
        <h2>Audit log</h2>
        <div className="row">
          <select aria-label="Event type" value={filter.action} onChange={(e) => { setOffset(0); setFilter({ ...filter, action: e.target.value }); }} style={{ maxWidth: 220 }}>
            <option value="">All events</option>{["auth", "document", "share", "permission", "family", "delegation", "backup", "recovery", "settings", "export", "offline", "import"].map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <select aria-label="Outcome" value={filter.outcome} onChange={(e) => { setOffset(0); setFilter({ ...filter, outcome: e.target.value }); }} style={{ maxWidth: 180 }}>
            <option value="">Any outcome</option><option value="success">Success</option><option value="failure">Failure</option><option value="denied">Denied</option>
          </select>
        </div>
        {log.data ? (
          <>
            <table className="responsive"><thead><tr><th>When</th><th>Who</th><th>Event</th><th className="hide-mobile">Details</th></tr></thead><tbody>
              {log.data.events.map((e) => <tr key={e.id}><td className="small">{formatDateTime(e.at)}</td><td>{e.actor}</td><td>{e.action} {e.outcome !== "success" && <span className="badge danger">{e.outcome}</span>}</td><td className="small muted hide-mobile">{e.target_type} {Object.keys(e.context || {}).length ? JSON.stringify(e.context) : ""} {e.ip}</td></tr>)}
            </tbody></table>
            <div className="row">{offset > 0 && <button className="btn small" onClick={() => setOffset(offset - 100)}>Newer</button>}{offset + 100 < log.data.total && <button className="btn small" onClick={() => setOffset(offset + 100)}>Older</button>}<span className="small muted">{log.data.total} events</span></div>
          </>
        ) : <Skeleton />}
        <p className="small muted">The audit log records actions without passwords, tokens, codes, full document numbers or document text. It is not tamper-proof against someone with root access to the server.</p>
      </div>
    </div>
  );
}
