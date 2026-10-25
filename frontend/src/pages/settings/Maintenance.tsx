import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError, formatBytes, formatDateTime } from "../../api";
import SettingsForm from "../../components/SettingsForm";
import { useStepUp } from "../../components/StepUp";
import { Confirm, CopyButton, HelpTip, Icon, Modal, Skeleton, useAsync, useToast } from "../../components/ui";
import { useSession } from "../../session";

/** Settings → System → Maintenance & Operations (Change Set AB). Every operation is a durable Maintenance Job on the
 * server: this page only starts jobs and shows them, so refreshing, signing out or a service restart never loses one.
 * There is no shell here — only the fixed operations below. */

type Step = { key: string; label: string; status: string; started_at: string | null; finished_at: string | null; detail: string };
type Job = {
  id: string; operation: string; operation_label: string; status: string; active: boolean; requested_by: string; requested_at: string;
  started_at: string | null; finished_at: string | null; current_step: string; summary: string; exit_code: number | null;
  version_from: string; version_to: string; backup_ref: string; recovery_state: string; failure_class: string; parent: string | null;
  has_log: boolean; steps: Step[]; details?: any; result?: any; verification?: any; retries?: string[]; recovery_guide?: string;
};

export const STATUS_LABELS: Record<string, [string, string]> = {
  queued: ["Queued", "neutral"], running: ["Running", "neutral"], waiting_confirmation: ["Waiting for Confirmation", "soon"],
  succeeded: ["Succeeded", "ok"], succeeded_warnings: ["Succeeded with Warnings", "soon"], partially_failed: ["Partially Failed", "danger"],
  failed: ["Failed", "danger"], recovery_required: ["Recovery Required", "danger"], rolled_back: ["Rolled Back", "soon"], cancelled: ["Cancelled", "neutral"],
};
const STEP_ICON: Record<string, [string, string]> = {
  succeeded: ["check", "ok"], failed: ["x", "danger"], running: ["refresh", "neutral"], warning: ["alert", "soon"], skipped: ["minus", "neutral"],
  not_run: ["minus", "neutral"], pending: ["clock", "neutral"],
};
const DOCTOR_CLASS: Record<string, string> = { PASS: "ok", WARNING: "soon", FAIL: "danger", "NOT CONFIGURED": "neutral", "NOT APPLICABLE": "neutral", "NOT TESTED": "soon", INFO: "neutral" };
const PANEL_CLASS: Record<string, [string, string]> = { ok: ["Healthy", "ok"], warning: ["Attention", "soon"], critical: ["Critical", "danger"], not_configured: ["Not configured", "neutral"], unknown: ["Unknown", "neutral"] };
const UPGRADE_STEPS = ["Authorization and step-up", "Maintenance lock", "Preflight checks", "Target version validation", "Disk space", "Automatic pre-upgrade backup",
  "Backup verification", "Fetch application code", "Install dependencies", "Frontend build", "Database migrations", "Restart services", "Health checks", "Release lock", "Report"];

export function JobStatus({ status }: { status: string }) {
  const [label, cls] = STATUS_LABELS[status] || [status, "neutral"];
  return <span className={`badge ${cls}`} data-status={status}>{label}</span>;
}

function duration(a: string | null, b: string | null) {
  if (!a) return "";
  const s = Math.max(0, Math.round(((b ? Date.parse(b) : Date.now()) - Date.parse(a)) / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

/** Live job: polls while active (marked as a background refresh), reconnects after a restart of the web service. */
function useJob(id: string | null) {
  const [job, setJob] = useState<Job | null>(null);
  const [offline, setOffline] = useState(false);
  const timer = useRef<number>();
  useEffect(() => {
    if (!id) { setJob(null); return; }
    let live = true, delay = 2000;
    const tick = async () => {
      try {
        const j = await api<Job>(`maintenance/jobs/${id}`, { background: true });
        if (!live) return;
        setJob(j); setOffline(false); delay = 2000;
        if (j.active) timer.current = window.setTimeout(tick, delay);
      } catch (e: any) {
        if (!live) return;
        // a restart or an upgrade stops the web service for a moment: this is not a job failure, keep reconnecting
        if (!(e instanceof ApiError) || e.status >= 500) { setOffline(true); delay = Math.min(15000, delay * 1.5); timer.current = window.setTimeout(tick, delay); }
      }
    };
    tick();
    return () => { live = false; window.clearTimeout(timer.current); };
  }, [id]);
  return { job, offline, setJob };
}

function Steps({ steps }: { steps: Step[] }) {
  return (
    <ol className="mj-steps" aria-label="Steps">
      {steps.map((s) => {
        const [icon, cls] = STEP_ICON[s.status] || ["clock", "neutral"];
        return (
          <li key={s.key} className={`mj-step ${s.status}`} data-step={s.key} data-step-status={s.status}>
            <span className={`mj-dot ${cls}`} aria-hidden="true"><Icon name={icon} size={14} /></span>
            <div className="grow">
              <div className="row between"><strong>{s.label}</strong><span className="small muted">{s.status === "running" ? `running · ${duration(s.started_at, null)}` : s.finished_at ? duration(s.started_at, s.finished_at) : s.status === "pending" ? "pending" : s.status.replace("_", " ")}</span></div>
              {s.detail && <div className="small muted">{s.detail}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function DoctorResults({ result, jobId }: { result: any; jobId: string }) {
  const [open, setOpen] = useState<Record<string, boolean>>(() => Object.fromEntries((result.components || []).map((c: any) => [c.component, c.status === "FAIL"])));
  return (
    <div className="stack" data-doctor>
      <div className="row" style={{ gap: ".4rem", flexWrap: "wrap" }}>
        {Object.entries(result.counts || {}).filter(([, v]) => v).map(([k, v]) => <span key={k} className={`badge ${DOCTOR_CLASS[k] || "neutral"}`}>{k} {String(v)}</span>)}
        <a className="btn small" href={`/api/maintenance/jobs/${jobId}/doctor-report`}><Icon name="download" size={14} /> Download report</a>
        <a className="btn small" href={`/api/maintenance/jobs/${jobId}/doctor-report?anonymize=1`}><Icon name="download" size={14} /> Anonymized report</a>
      </div>
      {(result.components || []).map((c: any) => (
        <div key={c.component} className="card mj-component" data-component={c.component}>
          <button type="button" className="row between mj-expander" aria-expanded={!!open[c.component]} onClick={() => setOpen({ ...open, [c.component]: !open[c.component] })}>
            <strong><Icon name={open[c.component] ? "down" : "right"} size={14} /> {c.component}</strong><span className={`badge ${DOCTOR_CLASS[c.status] || "neutral"}`}>{c.status}</span>
          </button>
          {open[c.component] && (
            <table className="responsive"><tbody>
              {c.results.map((r: any, i: number) => (
                <tr key={i}><td><span className={`badge ${DOCTOR_CLASS[r.status] || "neutral"}`}>{r.status}</span></td><td><strong>{r.check}</strong>{r.detail && <div className="small muted">{r.detail}</div>}{r.recommended && <div className="small">Recommended: {r.recommended}</div>}</td></tr>
              ))}
            </tbody></table>
          )}
        </div>
      ))}
    </div>
  );
}

function RepairPlan({ job, canManage, onChanged }: { job: Job; canManage: boolean; onChanged: (j: Job) => void }) {
  const toast = useToast();
  const step = useStepUp(toast);
  const plan: any[] = job.result?.plan || [];
  const [chosen, setChosen] = useState<string[]>(plan.map((p) => p.item));
  return (
    <div className="stack" data-repair-plan>
      <h3>Repair Plan <HelpTip id="maint.repair" /></h3>
      <p className="small muted">Nothing has been changed yet. Review each proposed repair; only the ones you keep selected will run.</p>
      {plan.map((p) => (
        <div key={p.item} className="card" data-plan-item={p.item}>
          <label className="check"><input type="checkbox" disabled={!canManage || job.status !== "waiting_confirmation"} checked={chosen.includes(p.item)}
            onChange={(e) => setChosen(e.target.checked ? [...chosen, p.item] : chosen.filter((x) => x !== p.item))} /> <strong>{p.problem}</strong></label>
          <table className="kv-table small"><tbody>
            <tr><th>Proposed repair</th><td>{p.proposed}</td></tr>
            <tr><th>Affected</th><td>{(p.affects || []).join(", ")}</td></tr>
            <tr><th>Restart required</th><td>{p.restart ? "Yes" : "No"}</td></tr>
            <tr><th>Backup first</th><td>{p.backup ? "Yes — a verified backup is made before this repair" : "No"}</td></tr>
            <tr><th>Risk</th><td><span className={`badge ${p.risk === "low" ? "ok" : p.risk === "medium" ? "soon" : "danger"}`}>{p.risk}</span></td></tr>
            {p.evidence?.length > 0 && <tr><th>Detected by</th><td>{p.evidence.join("; ")}</td></tr>}
          </tbody></table>
        </div>
      ))}
      {(job.result?.manual || []).length > 0 && (
        <details><summary>{job.result.manual.length} finding(s) without an automatic repair</summary>
          <ul className="small">{job.result.manual.map((m: any, i: number) => <li key={i}><strong>{m.component}: {m.check}</strong> — {m.detail} <em>{m.recommended}</em></li>)}</ul>
        </details>
      )}
      {canManage && job.status === "waiting_confirmation" && (
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={async () => { try { onChanged(await api<Job>(`maintenance/jobs/${job.id}/cancel`, { method: "POST" })); } catch (e: any) { toast(e.message, "error"); } }}>Cancel</button>
          <button className="btn primary" disabled={!chosen.length} data-confirm-repair onClick={() => step.run("run the selected repairs", async () => onChanged(await api<Job>(`maintenance/jobs/${job.id}/confirm`, { body: { items: chosen } })))}>Confirm and repair</button>
        </div>
      )}
      {step.dialog}
    </div>
  );
}

function errorText(job: Job) {
  const d = job.details || {};
  return [`${job.operation_label}: ${job.summary}`, d.failed_step_label && `Failed step: ${d.failed_step_label} (${d.component})`,
    d.timestamp && `Time: ${d.timestamp}`, `Exit code: ${job.exit_code ?? "—"}`, d.error && `Error: ${d.error}`].filter(Boolean).join("\n");
}

export function JobDetail({ id, canManage, onClose, onStart }: { id: string; canManage: boolean; onClose: () => void; onStart: (op: string, body?: any) => void }) {
  const { job, offline, setJob } = useJob(id);
  const toast = useToast();
  const step = useStepUp(toast);
  const [log, setLog] = useState<string | null>(null);
  const [tech, setTech] = useState(false);
  if (!job) return <Modal title="Maintenance job" wide onClose={onClose}><Skeleton /></Modal>;
  const failed = ["failed", "partially_failed", "recovery_required", "rolled_back"].includes(job.status);
  const d = job.details || {};
  const retry = () => step.run(`retry ${job.operation_label}`, async () => {
    const j = await api<Job>(`maintenance/jobs/${job.id}/retry`, { body: { confirm: true } });
    toast("Started again"); onStart("__open", j.id);
  });
  return (
    <Modal title={`${job.operation_label}`} wide onClose={onClose}>
      <div className="stack" data-job={job.id} data-job-status={job.status}>
        {offline && <div className="alert warn" role="status"><Icon name="refresh" size={14} /> Reconnecting… The web service is restarting; the operation continues on the server.</div>}
        <div className="row between" style={{ flexWrap: "wrap" }}>
          <div className="row"><JobStatus status={job.status} /> <span className="small muted">Requested by {job.requested_by} · {formatDateTime(job.requested_at)}{job.finished_at ? ` · finished ${formatDateTime(job.finished_at)}` : ""}</span></div>
          {job.parent && <span className="small muted">Retry of an earlier attempt</span>}
        </div>
        <div className={`alert ${failed ? "error" : job.status.startsWith("succeeded") ? "ok" : ""}`} role={failed ? "alert" : "status"} data-summary>
          <strong>{job.summary || (job.active ? "In progress…" : STATUS_LABELS[job.status]?.[0])}</strong>
          {(job.version_from || job.version_to) && <div className="small">Previous version: {job.version_from || "—"} · Attempted version: {job.version_to || "—"}</div>}
          {job.backup_ref && <div className="small">Backup: {job.backup_ref}</div>}
          {job.recovery_state === "recovery_required" && <div className="small"><strong>Rollback required:</strong> yes — follow the <a href={job.recovery_guide || "/help/troubleshooting#maintenance-recovery"}>Recovery Guide</a>. <HelpTip id="maint.recovery_required" /></div>}
        </div>
        {job.status === "waiting_confirmation" || (job.operation === "repair" && job.result?.plan) ? <RepairPlan job={job} canManage={canManage} onChanged={setJob} /> : null}
        <Steps steps={job.steps} />
        {job.operation === "doctor" && job.result?.components && <DoctorResults result={job.result} jobId={job.id} />}
        {job.operation === "check_updates" && job.result?.state && <UpdateResult r={job.result} />}
        {job.operation === "repair" && job.verification?.remaining?.length > 0 && <div className="alert warn small">Still failing after the repair: {job.verification.remaining.join("; ")}</div>}
        {failed && (
          <div className="stack">
            <button type="button" className="btn small" aria-expanded={tech} onClick={() => setTech(!tech)} data-technical>
              <Icon name={tech ? "down" : "right"} size={14} /> View Technical Details</button>
            <HelpTip id="maint.technical" />
            {tech && (
              <div className="card" data-technical-details>
                <table className="kv-table small"><tbody>
                  <tr><th>Failed step</th><td>{d.failed_step_label || "—"}</td></tr>
                  <tr><th>Component</th><td>{d.component || "—"}</td></tr>
                  <tr><th>Timestamp</th><td>{d.timestamp ? formatDateTime(d.timestamp) : "—"}</td></tr>
                  <tr><th>Exit code / status</th><td>{job.exit_code ?? "—"} · {job.status}</td></tr>
                  <tr><th>Error</th><td><code className="wrap">{d.error || "—"}</code></td></tr>
                  {d.condition && <tr><th>Detected condition</th><td>{d.condition}</td></tr>}
                  {d.probable_cause && <tr><th>Probable cause</th><td>{d.probable_cause}</td></tr>}
                  <tr><th>Recommended action</th><td>{d.recommended || "—"}</td></tr>
                  {d.health && <tr><th>Health</th><td>{d.health}</td></tr>}
                </tbody></table>
                {d.log_context?.length > 0 && <><div className="small muted">Log context (sanitized)</div><pre className="preview-text" style={{ maxHeight: 220 }}>{d.log_context.join("\n")}</pre></>}
              </div>
            )}
          </div>
        )}
        <div className="row" style={{ flexWrap: "wrap", gap: ".4rem" }}>
          {failed && <CopyButton label="Error" getValue={() => errorText(job)} />}
          {canManage && job.has_log && <button className="btn small" onClick={async () => setLog(await api<string>(`maintenance/jobs/${job.id}/log`))}><Icon name="file" size={14} /> View Full Log</button>}
          {canManage && job.has_log && <a className="btn small" href={`/api/maintenance/jobs/${job.id}/log?download=1`}><Icon name="download" size={14} /> Download Full Log</a>}
          {canManage && <a className="btn small" href={`/api/maintenance/jobs/${job.id}/report`}><Icon name="download" size={14} /> Sanitized Support Report</a>}
          {canManage && <a className="btn small" href={`/api/maintenance/jobs/${job.id}/report?anonymize=1`}><Icon name="download" size={14} /> Anonymized report</a>}
          {canManage && job.has_log && <HelpTip id="maint.full_log" />}
          <HelpTip id="maint.support_report" />
          {canManage && !job.active && failed && <><button className="btn small" onClick={retry} data-retry>Retry</button><HelpTip id="maint.retry" /></>}
          {canManage && failed && <button className="btn small" onClick={() => onStart("doctor")}>Run Doctor</button>}
          {canManage && failed && job.operation !== "repair" && <button className="btn small" onClick={() => onStart("repair")}>Repair</button>}
          {canManage && failed && job.operation === "upgrade" && job.recovery_state !== "rolled_back" && <button className="btn small" onClick={() => onStart("rollback")}>Rollback…</button>}
          {failed && <a className="btn small" href={job.recovery_guide || "/help/troubleshooting#maintenance-recovery"}>Recovery Guide</a>}
        </div>
      </div>
      {log !== null && <Modal title="Full log (sanitized)" wide onClose={() => setLog(null)}><pre className="preview-text" style={{ maxHeight: "65vh" }} data-full-log>{log}</pre></Modal>}
      {step.dialog}
    </Modal>
  );
}

function UpdateResult({ r }: { r: any }) {
  return (
    <div className="stack small" data-update-result={r.state}>
      <table className="kv-table"><tbody>
        <tr><th>Installed</th><td>{r.installed_version} <code>{(r.installed_revision || "").slice(0, 10)}</code></td></tr>
        <tr><th>Available</th><td>{r.available_version || "—"} <code>{(r.available_revision || "").slice(0, 10)}</code>{r.tag ? ` (${r.tag})` : ""}</td></tr>
        <tr><th>Source and channel</th><td>{r.source || "not configured"} · {r.channel}</td></tr>
        <tr><th>State</th><td>{({ current: "Up to date", available: `Update available (${r.behind} change(s))`, no_source: "No update source configured", diverged: "Different branch or local build", unknown_installed: "Installed revision unknown to the source" } as any)[r.state] || r.state}</td></tr>
        <tr><th>Last checked</th><td>{r.checked_at ? formatDateTime(r.checked_at) : "—"}</td></tr>
      </tbody></table>
      {(r.warnings || []).map((w: string) => <div key={w} className="alert warn">{w}</div>)}
      {(r.commits || []).length > 0 && <details><summary>Release information ({r.commits.length} change(s))</summary><ul>{r.commits.map((c: string) => <li key={c}><code>{c.slice(0, 7)}</code> {c.slice(8)}</li>)}</ul></details>}
    </div>
  );
}

function HealthPanels() {
  const { data, reload } = useAsync(() => api<{ panels: any[] }>("maintenance/health"), []);
  const [open, setOpen] = useState<string | null>(null);
  if (!data) return <Skeleton />;
  return (
    <div className="mj-panels" data-health-panels>
      {data.panels.map((p) => {
        const [label, cls] = PANEL_CLASS[p.state] || [p.state, "neutral"];
        return (
          <div key={p.key} className="card mj-panel" data-panel={p.key} data-state={p.state}>
            <div className="row between"><strong>{p.label} Health <HelpTip id={`maint.health.${p.key}`} /></strong><span className={`badge ${cls}`}>{label}</span></div>
            <div className="small">{p.summary}</div>
            <button type="button" className="btn small ghost" aria-expanded={open === p.key} onClick={() => setOpen(open === p.key ? null : p.key)}>{open === p.key ? "Hide details" : "Details"}</button>
            {open === p.key && <table className="kv-table small"><tbody>{p.facts.map((f: any, i: number) => <tr key={i}><th>{f.label}</th><td>{String(f.value)}</td></tr>)}</tbody></table>}
            {p.link && <Link className="small" to={p.link}>Open ›</Link>}
          </div>
        );
      })}
      <div><button className="btn small" onClick={reload}><Icon name="refresh" size={14} /> Refresh</button></div>
    </div>
  );
}

function SystemInfo() {
  const { data } = useAsync(() => api<any>("maintenance/system"), []);
  if (!data) return <Skeleton />;
  const up = data.os.uptime_seconds;
  return (
    <table className="kv-table small" data-system-info><tbody>
      <tr><th>Personal DM</th><td>{data.application.version} <code>{data.application.revision}</code> · Python {data.application.python} · Django {data.application.django}</td></tr>
      <tr><th>Operating system</th><td>{data.os.name} · kernel {data.os.kernel} · {data.os.architecture}</td></tr>
      <tr><th>Uptime</th><td>{up == null ? "—" : `${Math.floor(up / 86400)} d ${Math.floor((up % 86400) / 3600)} h`}</td></tr>
      <tr><th>CPU / load</th><td>{data.cpu.count} CPU · load {data.cpu.load.join(" / ")}</td></tr>
      <tr><th>Memory / swap</th><td>{formatBytes(data.memory.available)} free of {formatBytes(data.memory.total)} · swap {formatBytes(data.memory.swap_free)} free of {formatBytes(data.memory.swap_total)}</td></tr>
      <tr><th>Storage</th><td>{formatBytes(data.storage.free)} free of {formatBytes(data.storage.total)}</td></tr>
      <tr><th>Database</th><td>{data.database.version}</td></tr>
      <tr><th>OCR</th><td>{data.ocr.tesseract} · PaddleOCR {data.ocr.paddleocr} · light-ocr {data.ocr.light_ocr} · order {data.ocr.order.join(" → ")}</td></tr>
      <tr><th>AI</th><td>{data.ai.enabled ? `${data.ai.mode} · ${data.ai.default_profile || "no default profile"}${data.ai.provider ? ` (${data.ai.provider}, ${data.ai.location}${data.ai.text_model ? `, ${data.ai.text_model}` : ""})` : ""}` : "Switched off"}</td></tr>
      <tr><th>Workers</th><td>{data.workers.map((w: any) => `${w.name}: ${w.running ? "running" : "not running"}`).join(" · ")}</td></tr>
    </tbody></table>
  );
}

function Caches({ onStart }: { onStart: (op: string, body?: any) => void }) {
  const { data } = useAsync(() => api<any>("maintenance/caches"), []);
  const [chosen, setChosen] = useState<string[] | null>(null);
  const [confirm, setConfirm] = useState(false);
  if (!data) return <Skeleton />;
  const sel = chosen ?? data.caches.map((c: any) => c.key);
  return (
    <div className="stack small" data-caches>
      <ul className="mj-cache-list">
        {data.caches.map((c: any) => (
          <li key={c.key} data-cache={c.key}>
            <label className="check"><input type="checkbox" aria-label={`Clear ${c.label}`} checked={sel.includes(c.key)} onChange={(e) => setChosen(e.target.checked ? [...sel, c.key] : sel.filter((x: string) => x !== c.key))} />
              <span><strong>{c.label}</strong> <span className="muted">· {c.bytes == null ? `${c.items} item(s)` : `${formatBytes(c.bytes)} (${c.items})`}</span></span></label>
            <div><span className="muted">Effect of clearing:</span> {c.effect}</div>
            <div><span className="muted">Regeneration:</span> {c.regeneration}</div>
          </li>
        ))}
      </ul>
      <p className="muted">Never cleared: {data.never.join(", ")}.</p>
      <div><button className="btn small" disabled={!sel.length} onClick={() => setConfirm(true)}>Clear selected caches…</button></div>
      {confirm && <Confirm title="Clear safe caches" confirmLabel="Clear caches" onClose={() => setConfirm(false)}
        message={<p>Only the selected rebuildable caches are removed. Documents, OCR text and provenance, metadata, backups, logs, AI history, configuration and offline data are never touched.</p>}
        onConfirm={() => { setConfirm(false); onStart("clear_caches", { keys: sel, confirm: true }); }} />}
    </div>
  );
}

function History({ onOpen, version }: { onOpen: (id: string) => void; version: number }) {
  const [f, setF] = useState({ operation: "", status: "", from: "", to: "" });
  const { data, error } = useAsync(() => api<{ jobs: Job[]; total: number }>("maintenance/jobs", { query: f }), [f, version]);
  return (
    <div className="stack" data-job-history>
      <div className="row filter-row" style={{ flexWrap: "wrap", gap: ".4rem" }}>
        <select aria-label="Operation" value={f.operation} onChange={(e) => setF({ ...f, operation: e.target.value })}>
          <option value="">All operations</option>
          {["check_updates", "upgrade", "doctor", "repair", "restart", "rollback", "clear_caches"].map((o) => <option key={o} value={o}>{o.replace("_", " ")}</option>)}
        </select>
        <select aria-label="Status" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
          <option value="">All statuses</option>
          {Object.entries(STATUS_LABELS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <label className="small">From <input type="date" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} /></label>
        <label className="small">To <input type="date" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} /></label>
      </div>
      {error && <div className="alert error">{error}</div>}
      {data && (data.jobs.length === 0 ? <div className="empty small">No maintenance operations match.</div> : (
        <table className="responsive"><thead><tr><th>Operation</th><th>Status</th><th>Summary</th><th className="hide-mobile">By</th><th>When</th></tr></thead><tbody>
          {data.jobs.map((j) => (
            <tr key={j.id} className="clickable" tabIndex={0} data-history-job={j.id} onClick={() => onOpen(j.id)} onKeyDown={(e) => e.key === "Enter" && onOpen(j.id)}>
              <td>{j.operation_label}</td><td><JobStatus status={j.status} /></td><td className="small">{j.summary}</td><td className="hide-mobile small">{j.requested_by}</td><td className="small">{formatDateTime(j.requested_at)}</td>
            </tr>
          ))}
        </tbody></table>
      ))}
    </div>
  );
}

export default function MaintenancePanel() {
  const toast = useToast();
  const { session } = useSession();
  const [params, setParams] = useSearchParams();
  const ov = useAsync(() => api<any>("maintenance"), []);
  const step = useStepUp(toast);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [ref, setRef] = useState("");
  const [version, setVersion] = useState(0);
  const openId = params.get("job");
  const open = (id: string | null) => setParams(id ? { job: id } : {});
  const canManage = !!ov.data?.can_manage && !!session?.user?.is_main_admin;
  const start = async (op: string, body?: any) => {
    if (op === "__open") { open(body); return; }
    const call = async () => {
      const j = op === "doctor" ? await api<Job>("maintenance/doctor", { method: "POST" }) : await api<Job>(`maintenance/run/${op}`, { body: body || {} });
      setVersion((v) => v + 1); ov.reload(); open(j.id);
    };
    if (["upgrade", "restart", "rollback"].includes(op)) return step.run(op === "upgrade" ? "update the application" : op === "restart" ? "restart the Personal DM services" : "roll back to the previous release", call);
    try { await call(); } catch (e: any) { toast(e.message, "error"); }
  };
  if (!ov.data) return ov.error ? <div className="alert error">{ov.error}</div> : <Skeleton lines={6} />;
  const o = ov.data;
  const lu = o.last_update_check;
  return (
    <div className="stack" data-maintenance>
      <div className="card">
        <div className="row between" style={{ flexWrap: "wrap" }}>
          <div><h2 style={{ margin: 0 }}>Maintenance &amp; Operations <HelpTip id="maint.job" /></h2>
            <div className="small muted">Installed: <strong>{o.installed.version}</strong> <code>{(o.installed.revision || "").slice(0, 10)}</code> · Root helper: {o.helper_installed ? "installed" : "not installed (run sudo personaldocs repair on the server)"}</div></div>
          {o.active && <button className="btn small" onClick={() => open(o.active.id)} data-active-job><JobStatus status={o.active.status} /> {o.active.operation_label}: {o.active.current_step || "starting"} ›</button>}
        </div>
        {!canManage && <div className="alert small">Read-only: you can see status, health and Doctor results. Only the main administrator can run maintenance operations.</div>}
        {canManage && !o.helper_installed && <div className="alert warn small">The root host helper is not installed, so Check for Updates, Update, Restart, Repair and Rollback are unavailable here. On the server run <code>sudo personaldocs repair</code>; the same commands also work in a terminal (<code>sudo personaldocs upgrade</code>).</div>}
      </div>
      <div className="mj-cards">
        {canManage && <div className="card" data-card="check_updates">
          <h3>Check for Updates <HelpTip id="maint.check_updates" /></h3>
          {lu ? <UpdateResult r={{ ...lu.result, checked_at: lu.result?.checked_at || lu.at }} /> : <p className="small muted">Not checked yet.</p>}
          <button className="btn small" disabled={!o.helper_installed} onClick={() => start("check_updates")}>Check for Updates</button>
        </div>}
        {canManage && <div className="card" data-card="upgrade">
          <h3>Update Application <HelpTip id="maint.upgrade" /></h3>
          <p className="small">Preflight checks, an automatic verified backup, the update, database migrations, frontend build, restart and health checks — with a report. A failed backup stops the update before anything changes.</p>
          <div className="field"><label htmlFor="mj-ref" className="small">Version (optional: branch, tag or commit; default is the configured branch)</label>
            <input id="mj-ref" type="text" maxLength={100} value={ref} onChange={(e) => setRef(e.target.value)} placeholder="main" /></div>
          <button className="btn small primary" disabled={!o.helper_installed || !!o.active} onClick={() => setConfirm("upgrade")}>Update Application…</button>
        </div>}
        <div className="card" data-card="doctor">
          <h3>Doctor <HelpTip id="maint.doctor" /></h3>
          <p className="small">Read-only diagnostics of every component (the same checks as <code>personaldocs doctor</code>). Nothing is changed.</p>
          <button className="btn small" onClick={() => start("doctor")}>Run Doctor</button>
        </div>
        {canManage && <div className="card" data-card="repair">
          <h3>Repair <HelpTip id="maint.repair" /></h3>
          <p className="small">Analyzes the installation and proposes a repair plan. Nothing changes until you review and confirm it.</p>
          <button className="btn small" disabled={!!o.active} onClick={() => start("repair")}>Analyze</button>
        </div>}
        {canManage && <div className="card" data-card="restart">
          <h3>Restart Personal DM Services <HelpTip id="maint.restart" /></h3>
          <p className="small">Restarts only personaldocs-web, -worker and -scheduler, then checks their health. This page reconnects by itself.</p>
          <button className="btn small" disabled={!o.helper_installed || !!o.active} onClick={() => setConfirm("restart")}>Restart services…</button>
        </div>}
        {canManage && <div className="card" data-card="caches"><h3>Clear Safe Caches <HelpTip id="maint.caches" /></h3><Caches onStart={start} /></div>}
      </div>
      <div className="card"><h3>System Status <HelpTip id="maint.health" /></h3><HealthPanels /></div>
      {canManage && <div className="card"><h3>System Information <HelpTip id="maint.system_info" /></h3><SystemInfo /></div>}
      <div className="card"><h3>Maintenance Job History <HelpTip id="maint.history" /></h3><History onOpen={open} version={version} /></div>
      {canManage && <SettingsForm section="maintenance" title="Maintenance log retention" />}
      {confirm === "upgrade" && <Confirm title="Update Application" confirmLabel="Continue" onClose={() => setConfirm(null)}
        message={<div className="stack small"><p>Personal DM will be updated{ref ? ` to ${ref}` : " to the newest version of the configured branch"}. The web interface is briefly unavailable during the restart; this page reconnects and shows the result.</p>
          <ol>{UPGRADE_STEPS.map((s) => <li key={s}>{s}</li>)}</ol><p>You confirm with your password (and second factor) next.</p></div>}
        onConfirm={() => { setConfirm(null); start("upgrade", { confirm: true, ...(ref.trim() ? { ref: ref.trim() } : {}) }); }} />}
      {confirm === "restart" && <Confirm title="Restart Personal DM Services" confirmLabel="Continue" onClose={() => setConfirm(null)}
        message={<p>The web, worker and scheduler services restart (about 10–30 seconds). Running background jobs resume afterwards. Nothing else on the server is restarted.</p>}
        onConfirm={() => { setConfirm(null); start("restart", { confirm: true }); }} />}
      {confirm === "rollback" && <Confirm title="Roll back" confirmLabel="Continue" onClose={() => setConfirm(null)}
        message={<p>Returns to the previous release only if the database is compatible with it; otherwise nothing changes and you are told to restore the pre-upgrade backup. <HelpTip id="maint.rollback" /></p>}
        onConfirm={() => { setConfirm(null); start("rollback", { confirm: true }); }} />}
      {openId && <JobDetail id={openId} canManage={canManage} onClose={() => { open(null); setVersion((v) => v + 1); ov.reload(); }}
        onStart={(op, b) => (op === "rollback" ? setConfirm("rollback") : start(op, b))} />}
      {step.dialog}
    </div>
  );
}
