import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, formatBytes, formatDate, formatDateTime } from "../../api";
import SettingsForm from "../../components/SettingsForm";
import { Confirm, HelpTip, Icon, Modal, Skeleton, useAsync, useToast } from "../../components/ui";
import { useSession } from "../../session";
import { SecurityPanel } from "./Security";

/** Settings → Security: overview and score, antivirus, Internet security test, OS updates, firewall, records, storage. */

const SEV_CLASS: Record<string, string> = { critical: "danger", high: "danger", medium: "soon", low: "neutral", info: "neutral" };
const STATUS_CLASS: Record<string, string> = { passed: "ok", warning: "soon", failed: "danger", error: "danger", running: "neutral" };
const AV_LABEL: Record<string, [string, string]> = {
  pending: ["Scan pending", "neutral"], clean: ["Clean", "ok"], not_scanned: ["Not scanned", "soon"], size_limit: ["Not scanned — size limit exceeded", "soon"],
  failed: ["Scan failed", "danger"], threat: ["Threat detected", "danger"], quarantined: ["Quarantined", "danger"], released: ["Released from quarantine", "soon"],
};

export function AvBadge({ status, compact }: { status?: string | null; compact?: boolean }) {
  if (!status) return null;
  const [label, cls] = AV_LABEL[status] || [status, "neutral"];
  if (compact && status === "clean") return <span className="av-dot ok" role="img" title="Antivirus: clean" aria-label="Antivirus: clean"><Icon name="shield" size={14} /></span>;
  if (compact && status === "pending") return <span className="av-dot" role="img" title="Antivirus scan pending" aria-label="Antivirus scan pending"><Icon name="shield" size={14} /></span>;
  return <span className={`badge ${cls}`} title={`Antivirus: ${label}`}><Icon name="shield" size={12} /> {compact && status.startsWith("not") ? "Not scanned" : label}</span>;
}

function usePoll(reload: () => void, active: boolean, ms = 3000) {
  useEffect(() => {
    if (!active) return;
    const t = setInterval(reload, ms);
    return () => clearInterval(t);
  }, [active]);
}

function ScoreRing({ score, status }: { score: number; status: string }) {
  const cls = status === "Healthy" ? "ok" : status === "Attention" ? "soon" : "danger";
  const deg = Math.round((score / 100) * 360);
  return (
    <div className={`score-ring ${cls}`} style={{ ["--deg" as any]: `${deg}deg` }} role="img" aria-label={`Security score ${score} of 100, ${status}`}>
      <div><strong>{score}</strong><span>/100</span></div>
    </div>
  );
}

export function HealthSummary({ h, compact }: { h: any; compact?: boolean }) {
  return (
    <div className={`sec-health${compact ? " compact" : ""}`}>
      <div className="row" style={{ flexWrap: "nowrap", alignItems: "center" }}>
        <ScoreRing score={h.score} status={h.status} />
        <div className="grow">
          <div className={`sec-status ${h.status === "Healthy" ? "ok" : h.status === "Attention" ? "soon" : "danger"}`}>{h.status}</div>
          <div className="small muted">Security score {h.score}/100{h.status !== h.band ? ` (score alone: ${h.band})` : ""} · {h.deployment === "internet" ? (h.internet_ready ? "Internet Ready" : "Internet-facing, not Internet Ready") : "LAN only"}</div>
        </div>
      </div>
      {h.forced.length > 0 && (
        <div className="alert error" role="alert"><strong>At Risk regardless of the score:</strong><ul style={{ margin: ".3rem 0 0 1.1rem", padding: 0 }}>{h.forced.map((f: string) => <li key={f}>{f}</li>)}</ul></div>
      )}
      <ul className="plain-list sec-components">
        {Object.entries(h.components).map(([k, c]: [string, any]) => (
          <li key={k}>
            <Link to={c.link} className="row" style={{ flexWrap: "nowrap", textDecoration: "none", color: "inherit" }}>
              <span className={`sec-dot ${c.status}`} aria-hidden="true" />
              <span className="grow"><strong>{COMPONENT_LABEL[k] || k}</strong>{!compact && <span className="small muted"> — {c.detail}</span>}</span>
              <span className="small muted">{c.points}/{c.max}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

const COMPONENT_LABEL: Record<string, string> = { antivirus: "Antivirus (ClamAV)", https: "HTTPS / TLS", security_test: "Internet security test", os_updates: "Debian security updates", firewall: "Firewall", reboot: "Reboot status", authentik: "authentik" };

function OverviewView() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<any>("security/health"), []);
  const https = useAsync(() => api<any>("security/https"), []);
  const [busy, setBusy] = useState(false);
  if (!data) return <Skeleton lines={6} />;
  return (
    <div className="stack">
      <div className="two-col">
        <section className="card"><h2>Security Health <HelpTip text="A weighted score of the checks below. It is not a certification, and a high score never hides a critical condition." link="/help/security-center#score" /></h2><HealthSummary h={data} /></section>
        <section className="card">
          <h2>Internet exposure</h2>
          {https.data ? (
            <div className="stack">
              <p className="small">{https.data.deployment === "internet" ? (https.data.internet_ready ? <span className="badge ok">Internet Ready</span> : <span className="badge danger">Not Internet Ready</span>) : <span className="badge neutral">LAN only — not Internet Ready</span>}
                {https.data.checked_at && <span className="muted"> · checked {formatDateTime(https.data.checked_at)}</span>}</p>
              {(https.data.checks || []).map((c: any) => (
                <div key={c.key} className="row small" style={{ flexWrap: "nowrap" }}><Icon name={c.ok ? "check" : "x"} size={16} /><span className="grow"><strong>{c.name}</strong> <span className="muted">{c.detail}</span>{!c.ok && c.remediation && <div className="muted">{c.remediation}</div>}</span></div>
              ))}
              <button className="btn small" disabled={busy} onClick={async () => { setBusy(true); try { await api("security/https", { method: "POST" }); https.reload(); reload(); } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); } }}><Icon name="refresh" size={16} /> Check HTTPS now</button>
            </div>
          ) : <Skeleton />}
        </section>
      </div>
      <SettingsForm section="security_center" title="Exposure, retention and storage thresholds" />
    </div>
  );
}

function ReleaseDialog({ f, onClose, onDone }: { f: any; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [err, setErr] = useState("");
  return (
    <Modal title="Release a quarantined file" onClose={onClose}>
      <form className="stack" onSubmit={async (e) => { e.preventDefault(); try { await api(`security/antivirus/quarantine/${f.version}/release`, { body: { confirm: ack, reason } }); onDone(); } catch (x: any) { setErr(x.message); } }}>
        <div className="alert error" role="alert"><strong>ClamAV detected malware in this file: {f.signature}.</strong> Releasing it makes it downloadable and previewable again for everyone who can see the document. Only release a file you know is a false positive.</div>
        <p className="small"><strong>{f.name}</strong> · {f.title} · {f.owner}</p>
        {err && <div className="alert error">{err}</div>}
        <div className="field"><label htmlFor="rel-reason">Reason (kept in the audit log)</label><textarea id="rel-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Confirmed false positive: …" /></div>
        <label className="check"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I understand the risk and want to release this file.</label>
        <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn danger" disabled={!ack || reason.trim().length < 10}>Release file</button></div>
      </form>
    </Modal>
  );
}

const AV_STATE_CLASS: Record<string, string> = { healthy: "ok", degraded: "soon", unavailable: "danger", error: "danger", disabled: "neutral" };
const CHECK_ICON: Record<string, string> = { ok: "✔", warn: "!", fail: "✘", info: "•" };

/** Diagnose (read-only, as the web service account) and Repair (fixed root steps run by the host helper). */
function AntivirusDiagnose({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const { data, reload, error } = useAsync(() => api<any>("security/antivirus/diagnose"), []);
  const repairing = ["requested", "running"].includes(data?.repair?.state);
  usePoll(reload, repairing);
  const d = data?.diagnosis;
  const repair = async () => {
    try { await api("security/antivirus/repair", { method: "POST" }); toast("Repair requested; it can take a few minutes while ClamAV loads its signatures"); reload(); }
    catch (e: any) { toast(e.message, "error"); }
  };
  return (
    <section className="card" aria-live="polite">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2>Diagnose / Repair antivirus</h2>
        <button className="icon-btn" aria-label="Close diagnosis" onClick={onClose}><Icon name="x" size={18} /></button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {!d ? <Skeleton lines={6} /> : <>
        <p>Result: <span className={`badge ${AV_STATE_CLASS[d.status] || "neutral"}`}>{d.status}</span> · socket <code>{d.socket}</code></p>
        {d.cause && <div className="alert warn"><strong>Detected issue:</strong> {d.cause}</div>}
        <ul className="plain-list diag-list">
          {d.checks.map((c: any) => (
            <li key={c.key} className={`diag-${c.state}`}><span aria-hidden="true">{CHECK_ICON[c.state]}</span> <strong>{c.label}</strong>: <span className="small">{c.detail}</span>
              {c.fix && c.state !== "ok" && <div className="small muted">Fix: <code>{c.fix}</code></div>}</li>
          ))}
        </ul>
        <p className="small muted">These checks run as the Personal DM service account. Service and journal details need root; the repair below (or <code>{data.manual_fix}</code> on the server) checks those too.</p>
        <div className="row">
          <button className="btn small primary" disabled={repairing || !data.helper_installed} onClick={repair}><Icon name="settings" size={16} /> {repairing ? "Repair running…" : "Repair antivirus"}</button>
          <button className="btn small ghost" onClick={reload}>Diagnose again</button>
        </div>
        {!data.helper_installed && <p className="small">The host helper is not installed, so the app cannot run the repair. On the server run: <code>{data.manual_fix}</code></p>}
        {data.repair?.state && (
          <div style={{ marginTop: ".8rem" }}>
            <h3>Last repair <span className={`badge ${data.repair.state === "done" ? "ok" : data.repair.state === "failed" ? "danger" : "soon"}`}>{data.repair.state}</span></h3>
            {data.repair.finished_at && <p className="small muted">{formatDateTime(data.repair.finished_at)}</p>}
            {(data.repair.steps || []).length > 0 && <ol className="small">{data.repair.steps.map((s: any, i: number) => <li key={i}>{s.ok ? "✔" : "✘"} {s.step}: {s.detail}</li>)}</ol>}
            {data.repair.error && <p className="error-text small">{data.repair.error} — if it cannot be repaired automatically, run <code>{data.manual_fix}</code> on the server and see Help → Antivirus.</p>}
          </div>
        )}
      </>}
    </section>
  );
}

function AntivirusView() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<any>("security/antivirus"), []);
  const [release, setRelease] = useState<any>(null);
  const [del, setDel] = useState<any>(null);
  const [diag, setDiag] = useState(false);
  const upd = useAsync(() => api<any>("security/antivirus/update/status"), []);
  usePoll(() => { reload(); upd.reload(); }, !!(data?.active_run?.status === "running" || ["requested", "running"].includes(upd.data?.state)));
  if (!data) return <Skeleton lines={8} />;
  const h = data.health;
  const act = async (fn: () => Promise<any>, ok: string) => { try { await fn(); toast(ok); reload(); upd.reload(); } catch (e: any) { toast(e.message, "error"); } };
  const run = data.active_run;
  return (
    <div className="stack">
      <section className="card">
        <h2>Antivirus (ClamAV) <HelpTip text="New files are scanned in the background by the local ClamAV daemon. Files stay usable while they are scanned." link="/help/antivirus" /></h2>
        <div className="kv2">
          <span className="k">Status</span><span><span className={`badge ${AV_STATE_CLASS[h.state] || "neutral"}`}>{h.state_label || h.status}</span>{h.state === "degraded" && <span className="small muted"> Definitions out of date</span>} {h.error && <span className="small muted">{h.error}</span>}</span>
          <span className="k">Socket</span><span><code>{h.socket}</code></span>
          <span className="k">Engine</span><span>{h.engine || "—"}{h.metadata_stale && h.engine && <span className="small muted"> (last seen {h.last_ok_at ? formatDateTime(h.last_ok_at) : "earlier"}; not proof that scanning works)</span>}</span>
          <span className="k">Signatures</span><span>{data.signatures.version || "—"}{data.signatures.date && <> · {formatDateTime(data.signatures.date)} ({data.signatures.age_days} days old)</>}</span>
          <span className="k">Self-test</span><span>{h.self_test ? <>{h.self_test.ok ? <span className="badge ok">Passed</span> : <span className="badge danger">Failed</span>} <span className="small muted">{formatDateTime(h.self_test.at)} · {h.self_test.detail}</span></> : <span className="small muted">Not run yet</span>}</span>
          <span className="k">Automatic updates</span><span>{data.signatures.updater}</span>
          <span className="k">Last manual update</span><span>{upd.data?.state ? <>{upd.data.state}{upd.data.finished_at && ` · ${formatDateTime(upd.data.finished_at)}`}{upd.data.error && <span className="error-text small"> {upd.data.error}</span>}</> : "—"}</span>
          <span className="k">Scan size limit</span><span>{data.max_scan_mb} MB</span>
          <span className="k">Scheduled re-scan</span><span>{data.schedule.frequency === "disabled" ? "Disabled" : `${data.schedule.frequency}, next ${data.schedule.next ? formatDateTime(data.schedule.next) : "—"}`}</span>
        </div>
        <div className="row" style={{ marginTop: ".7rem" }}>
          <button className="btn small" onClick={() => act(() => api("security/antivirus/update", { method: "POST" }), "Signature update requested")}><Icon name="refresh" size={16} /> Update now</button>
          <button className="btn small primary" disabled={!!run} onClick={() => act(() => api("security/antivirus/scan", { body: {} }), "Library scan started")}><Icon name="shield" size={16} /> Scan entire existing library</button>
          <button className="btn small ghost" onClick={() => act(() => api("security/antivirus?refresh=1"), "Status refreshed")}>Refresh status</button>
          <button className="btn small" disabled={h.state === "disabled"} onClick={() => act(async () => { const r = await api<any>("security/antivirus/selftest", { method: "POST" }); if (!r.ok) throw new Error(`Self-test failed: ${r.detail}`); }, "Self-test passed: clean file Clean, EICAR detected")}><Icon name="check" size={16} /> Run self-test</button>
          <button className={`btn small ${["unavailable", "error"].includes(h.state) ? "primary" : ""}`} onClick={() => setDiag(true)}><Icon name="settings" size={16} /> Diagnose / Repair</button>
        </div>
        <p className="small muted" style={{ marginTop: ".5rem" }}>{data.archive_note}</p>
      </section>
      {diag && <AntivirusDiagnose onClose={() => { setDiag(false); reload(); }} />}
      {run && (
        <section className="card">
          <h2>Library scan {run.status === "paused" && <span className="badge soon">Paused</span>}</h2>
          <div className="progress" role="progressbar" aria-valuenow={run.done} aria-valuemax={run.total}><div style={{ width: `${run.total ? Math.round((run.done / run.total) * 100) : 0}%` }} /></div>
          <p className="small">{run.done} of {run.total} files · {Object.entries(run.counts || {}).map(([k, v]) => `${v} ${AV_LABEL[k]?.[0].toLowerCase() || k}`).join(", ") || "starting"}</p>
          <div className="row">
            {run.status === "running" ? <button className="btn small" onClick={() => act(() => api(`security/antivirus/runs/${run.id}`, { body: { action: "pause" } }), "Paused")}>Pause</button>
              : <button className="btn small" onClick={() => act(() => api(`security/antivirus/runs/${run.id}`, { body: { action: "resume" } }), "Resumed")}>Resume</button>}
            <button className="btn small danger" onClick={() => act(() => api(`security/antivirus/runs/${run.id}`, { body: { action: "cancel" } }), "Cancelled")}>Cancel</button>
          </div>
        </section>
      )}
      <section className="card">
        <h2>Quarantine {data.quarantine.length > 0 && <span className="badge danger">{data.quarantine.length}</span>}</h2>
        {data.quarantine.length === 0 ? <div className="empty small">No file is in quarantine.</div> : (
          <table className="responsive"><thead><tr><th>File</th><th>Detection</th><th className="hide-mobile">Detected</th><th /></tr></thead><tbody>
            {data.quarantine.map((f: any) => (
              <tr key={f.version}><td><strong>{f.name}</strong><div className="small muted">{f.title} · {f.owner}</div></td><td><span className="badge danger">{f.signature}</span></td>
                <td className="hide-mobile small">{f.scanned_at ? formatDateTime(f.scanned_at) : ""}</td>
                <td className="row">{data.can_release ? <><button className="btn small" onClick={() => setRelease(f)}>Release…</button><button className="btn small danger" onClick={() => setDel(f)}>Delete…</button></> : <span className="small muted">Main administrator decides</span>}</td></tr>
            ))}
          </tbody></table>
        )}
      </section>
      <section className="card">
        <h2>Files not scanned or failed</h2>
        {data.problems.length === 0 ? <div className="empty small">Every file was scanned.</div> : (
          <table className="responsive"><thead><tr><th>File</th><th>Status</th><th className="hide-mobile">Why</th><th /></tr></thead><tbody>
            {data.problems.map((f: any) => (
              <tr key={f.version}><td><Link to={`/documents/${f.document}`}>{f.name}</Link><div className="small muted">{f.owner} · {formatBytes(f.size)}</div></td><td><AvBadge status={f.status} /></td>
                <td className="hide-mobile small muted">{f.detail}</td>
                <td><button className="btn small" onClick={() => act(() => api("security/antivirus/scan", { body: { document: f.document } }), "Re-scan queued")}>Re-scan</button></td></tr>
            ))}
          </tbody></table>
        )}
      </section>
      {data.released.length > 0 && (
        <section className="card"><h2>Released files</h2>
          <ul className="plain-list small">{data.released.map((f: any) => <li key={f.version}><strong>{f.name}</strong> ({f.signature}) — released by {f.released_by} on {formatDateTime(f.released_at)}: “{f.release_reason}”</li>)}</ul></section>
      )}
      <section className="card"><h2>Recent library scans</h2>
        {data.runs.length === 0 ? <div className="empty small">No library scan yet.</div> : (
          <table className="responsive"><thead><tr><th>Started</th><th>Kind</th><th>Status</th><th>Files</th></tr></thead><tbody>
            {data.runs.map((r: any) => <tr key={r.id}><td>{formatDateTime(r.started_at)}<div className="small muted">{r.started_by}</div></td><td>{r.kind}</td><td>{r.status}</td><td>{r.done}/{r.total}</td></tr>)}
          </tbody></table>
        )}
      </section>
      <SettingsForm section="antivirus" title="Antivirus settings" />
      {release && <ReleaseDialog f={release} onClose={() => setRelease(null)} onDone={() => { setRelease(null); toast("File released from quarantine"); reload(); }} />}
      {del && <Confirm title="Delete quarantined file" danger typeToConfirm="DELETE" confirmLabel="Delete permanently"
        message={<p>The quarantined copy of <strong>{del.name}</strong> is deleted permanently. If it is the document's only file, the document is deleted too. This cannot be undone.</p>}
        onClose={() => setDel(null)} onConfirm={async () => { try { await api(`security/antivirus/quarantine/${del.version}/delete`, { body: { confirm_text: "DELETE" } }); setDel(null); toast("Deleted"); reload(); } catch (e: any) { toast(e.message, "error"); } }} />}
    </div>
  );
}

function SecurityTestView() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<any>("security/tests"), []);
  const [selected, setSelected] = useState<any>(null);
  usePoll(reload, data?.runs?.[0]?.status === "running");
  if (!data) return <Skeleton lines={6} />;
  const run = selected || data.latest;
  const cats: Record<string, any[]> = {};
  (run?.findings || []).forEach((x: any) => { (cats[x.category] = cats[x.category] || []).push(x); });
  const counts = run?.summary?.counts || {};
  return (
    <div className="stack">
      <section className="card">
        <h2>Basic Internet Security Test <HelpTip text="Runs only when you start it. Checks this application and this server; never other devices on your network." link="/help/security-center#test" /></h2>
        <p className="small muted">{data.note}</p>
        <button className="btn primary" disabled={data.runs?.[0]?.status === "running"} onClick={async () => { try { await api("security/tests", { method: "POST" }); toast("Security test started"); reload(); } catch (e: any) { toast(e.message, "error"); } }}><Icon name="shield" /> Run Security Test</button>
      </section>
      {run && (
        <section className="card">
          <h2>{run.id === data.latest?.id ? "Latest result" : `Result of ${formatDateTime(run.started_at)}`} <span className={`badge ${STATUS_CLASS[run.status]}`}>{run.status === "passed" ? "Passed" : run.status === "warning" ? "Warning" : run.status === "failed" ? "Failed" : run.status}</span></h2>
          <p className="small muted">{formatDateTime(run.started_at)} · started by {run.started_by || "—"} · {run.deployment === "internet" ? "Internet-facing" : "LAN only"}{run.summary?.checks ? ` · ${run.summary.passed} of ${run.summary.checks} checks passed` : ""}</p>
          {(counts.critical > 0 || counts.high > 0) && <div className="alert error" role="alert"><strong>{counts.critical} Critical and {counts.high} High finding(s) are unresolved.</strong> Deployment is not blocked, but this result is not a pass.</div>}
          {run.summary?.resolved?.length > 0 && <p className="small"><span className="badge ok">{run.summary.resolved.length} resolved</span> since the previous test{run.summary.new?.length ? <> · <span className="badge soon">{run.summary.new.length} new</span></> : ""}</p>}
          {run.status === "running" ? <Skeleton lines={4} /> : Object.entries(cats).map(([cat, items]) => (
            <details key={cat} open={items.some((x) => x.status === "fail" || x.status === "warn")} className="finding-group">
              <summary><strong>{cat}</strong> <span className="small muted">{items.filter((x) => x.status === "pass").length}/{items.length} passed</span></summary>
              <ul className="plain-list">{items.map((x) => (
                <li key={x.id} className="finding">
                  <div className="row" style={{ flexWrap: "nowrap" }}><Icon name={x.status === "pass" ? "check" : x.status === "info" ? "info" : "x"} size={16} />
                    <span className="grow"><strong>{x.check}</strong>{x.detail && <span className="small muted"> — {x.detail}</span>}</span>
                    {x.status !== "pass" && x.status !== "info" && <span className={`badge ${SEV_CLASS[x.severity]}`}>{x.severity}</span>}
                    {x.resolution && <span className="badge neutral">{x.resolution}</span>}</div>
                  {x.remediation && x.status !== "pass" && <div className="small" style={{ marginLeft: "1.6rem" }}>Fix: {x.remediation}</div>}
                </li>
              ))}</ul>
            </details>
          ))}
        </section>
      )}
      <section className="card"><h2>History (kept one year)</h2>
        {data.runs.length === 0 ? <div className="empty small">No test has been run yet.</div> : (
          <table className="responsive"><thead><tr><th>Date</th><th>Status</th><th>Critical / High / Medium</th><th /></tr></thead><tbody>
            {data.runs.map((r: any) => <tr key={r.id}><td>{formatDateTime(r.started_at)}<div className="small muted">{r.started_by}</div></td><td><span className={`badge ${STATUS_CLASS[r.status]}`}>{r.status}</span></td>
              <td>{r.summary?.counts ? `${r.summary.counts.critical} / ${r.summary.counts.high} / ${r.summary.counts.medium}` : "—"}</td>
              <td><button className="btn small ghost" onClick={async () => setSelected(r.id === data.latest?.id ? null : await api(`security/tests/${r.id}`))}>View</button></td></tr>)}
          </tbody></table>
        )}
      </section>
    </div>
  );
}

function UpdatesView() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<any>("security/os-updates"), []);
  const [install, setInstall] = useState<{ override?: boolean; detail?: string } | null>(null);
  const [reason, setReason] = useState("");
  const [reboot, setReboot] = useState<any>(null);
  const [log, setLog] = useState<string | null>(null);
  usePoll(reload, !!data?.runs?.some((r: any) => ["requested", "running"].includes(r.status)));
  if (!data) return <Skeleton lines={6} />;
  const doInstall = async () => {
    try {
      await api("security/os-updates/install", { body: { confirm: true, override_backup: !!install?.override, override_reason: reason } });
      toast("Installing security updates"); setInstall(null); setReason(""); reload();
    } catch (e: any) {
      if (e.data?.code === "backup_failed") setInstall({ override: false, detail: e.data.detail });
      else toast(e.message, "error");
    }
  };
  return (
    <div className="stack">
      {!data.helper_installed && <div className="alert warn">The host helper is not installed, so updates and reboots cannot be started from here. On the server run <code>sudo personaldocs repair</code>, or update by hand: <code>{data.manual_commands.join(" && ")}</code>.</div>}
      <section className="card">
        <h2>Debian security updates <HelpTip text="Only security updates are installed, and only when you choose to. A database and settings backup is taken first." link="/help/security-center#updates" /></h2>
        <p className="small muted">{data.unattended}</p>
        <p>{data.check_state === "done" ? (data.pending.length ? <span className="badge danger">{data.pending.length} security update(s) pending</span> : <span className="badge ok">No pending security updates</span>) : <span className="badge neutral">Not checked yet</span>}
          {data.checked_at && <span className="small muted"> · checked {formatDateTime(data.checked_at)}</span>}
          {data.reboot_required && <span className="badge soon" style={{ marginLeft: ".4rem" }}>Reboot required</span>}</p>
        {data.pending.length > 0 && <table className="responsive"><thead><tr><th>Package</th><th>Installed</th><th>New</th></tr></thead><tbody>{data.pending.map((p: any) => <tr key={p.package}><td>{p.package}</td><td className="small">{p.current}</td><td className="small">{p.candidate}</td></tr>)}</tbody></table>}
        <div className="row" style={{ marginTop: ".6rem" }}>
          <button className="btn small" disabled={!data.helper_installed} onClick={() => api("security/os-updates/check", { method: "POST" }).then(() => { toast("Checking for updates"); reload(); }).catch((e) => toast(e.message, "error"))}><Icon name="refresh" size={16} /> Check for updates</button>
          <button className="btn small primary" disabled={!data.helper_installed || !data.pending.length} onClick={() => setInstall({})}>Install security updates…</button>
          <button className="btn small danger" disabled={!data.helper_installed} onClick={async () => setReboot(await api("security/reboot"))}>Reboot server…</button>
        </div>
        {data.post_reboot?.checked_at && <p className="small" style={{ marginTop: ".5rem" }}>After the last reboot: {Object.entries(data.post_reboot.services || {}).map(([k, v]) => `${k} ${v === true ? "OK" : v === false ? "not running" : v}`).join(" · ")}</p>}
      </section>
      <section className="card"><h2>Update and reboot history</h2>
        {data.runs.length === 0 ? <div className="empty small">Nothing yet.</div> : (
          <table className="responsive"><thead><tr><th>Requested</th><th>Action</th><th>Status</th><th className="hide-mobile">Backup</th><th /></tr></thead><tbody>
            {data.runs.map((r: any) => <tr key={r.id}><td>{formatDateTime(r.requested_at)}<div className="small muted">{r.requested_by}</div></td><td>{r.action === "install_updates" ? "Install updates" : r.action === "check_updates" ? "Check" : "Reboot"}{r.packages?.length ? <div className="small muted">{r.packages.length} package(s)</div> : null}</td>
              <td>{r.status}{r.error && <div className="small error-text">{r.error}</div>}{r.reboot_required && <div><span className="badge soon">Reboot required</span></div>}</td>
              <td className="hide-mobile small">{r.backup_status ? (r.backup_override ? <span className="badge danger" title={r.override_reason}>Overridden</span> : r.backup_status) : "—"}</td>
              <td>{r.has_log && <button className="btn small ghost" onClick={async () => setLog((await api(`security/os-updates/${r.id}/log`)).log || "(empty)")}>Log</button>}</td></tr>)}
          </tbody></table>
        )}
      </section>
      {install && (
        <Modal title="Install security updates" onClose={() => setInstall(null)}>
          <div className="stack">
            {install.detail === undefined ? <p>A backup of the database and settings is taken first. If it fails, nothing is installed unless you override it. This is not a Proxmox snapshot; take one on the host for a full rollback.</p>
              : <div className="alert error" role="alert"><strong>The backup failed:</strong> {install.detail}<br />Installing without a backup means you cannot roll back the application data if something goes wrong.</div>}
            {install.detail !== undefined && <>
              <label className="check"><input type="checkbox" checked={!!install.override} onChange={(e) => setInstall({ ...install, override: e.target.checked })} /> Install anyway without a backup</label>
              {install.override && <div className="field"><label htmlFor="ov-r">Reason (audited)</label><input id="ov-r" value={reason} onChange={(e) => setReason(e.target.value)} /></div>}
            </>}
            <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn" onClick={() => setInstall(null)}>Cancel</button>
              <button className="btn primary" disabled={install.detail !== undefined && (!install.override || reason.trim().length < 10)} onClick={doInstall}>{install.override ? "Install without backup" : "Back up and install"}</button></div>
          </div>
        </Modal>
      )}
      {reboot && (
        <Confirm title="Reboot the server" danger confirmLabel="Reboot now"
          message={<div className="stack"><p>Personal DM stops its worker and scheduler (the current job finishes first), then the host reboots. The site is unavailable for a few minutes.</p>
            {reboot.warnings.length > 0 && <div className="alert warn"><ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{reboot.warnings.map((w: string) => <li key={w}>{w}</li>)}</ul></div>}</div>}
          onClose={() => setReboot(null)} onConfirm={async () => { try { await api("security/reboot", { body: { confirm: true } }); setReboot(null); toast("Reboot requested"); reload(); } catch (e: any) { toast(e.message, "error"); } }} />
      )}
      {log !== null && <Modal title="Update log" wide onClose={() => setLog(null)}><pre className="preview-text" style={{ maxHeight: "60vh" }}>{log}</pre></Modal>}
    </div>
  );
}

function FirewallView() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<any>("security/firewall"), []);
  usePoll(reload, ["requested", "running"].includes(data?.state));
  if (!data) return <Skeleton lines={5} />;
  const fw = data.firewall;
  return (
    <div className="stack">
      <section className="card">
        <h2>Firewall status <HelpTip text="Monitoring only: Personal DM never changes firewall rules." link="/help/security-center#firewall" /></h2>
        <p className="small muted">{data.note}</p>
        {!data.helper_installed ? <div className="alert warn">The host helper is not installed (sudo personaldocs repair).</div> : !fw ? <div className="empty small">Not checked yet.</div> : (
          <div className="kv2"><span className="k">Firewall</span><span>{fw.active ? <span className="badge ok">Active</span> : <span className="badge danger">Not active</span>} {fw.tool || "none"} · {fw.rules} rule(s)</span>
            <span className="k">Checked</span><span>{data.checked_at ? formatDateTime(data.checked_at) : "—"}</span></div>
        )}
        <button className="btn small" style={{ marginTop: ".6rem" }} disabled={!data.helper_installed} onClick={() => api("security/firewall", { method: "POST" }).then(() => { toast("Checking…"); reload(); }).catch((e) => toast(e.message, "error"))}><Icon name="refresh" size={16} /> Check now</button>
      </section>
      {(data.exposed_local_only.length > 0 || data.unexpected.length > 0) && (
        <div className="alert warn" role="alert">{data.exposed_local_only.map((s: any) => <div key={s.port}><strong>{s.process || "A service"} is reachable on {s.address}:{s.port}</strong> — it should listen on localhost only.</div>)}
          {data.unexpected.filter((s: any) => ![3310, 5432].includes(s.port)).map((s: any) => <div key={`${s.address}:${s.port}`}>Unexpected service {s.process || "?"} on {s.address}:{s.port}.</div>)}</div>
      )}
      <section className="card"><h2>Listening services</h2>
        {data.listening.length === 0 ? <div className="empty small">No data yet.</div> : (
          <table className="responsive"><thead><tr><th>Port</th><th>Address</th><th>Process</th><th>Exposure</th></tr></thead><tbody>
            {data.listening.map((s: any, i: number) => <tr key={i}><td>{s.proto} {s.port}</td><td>{s.address}</td><td>{s.process}</td><td>{s.public ? (data.expected_ports[String(s.port)] ? <span className="badge neutral">Expected: {data.expected_ports[String(s.port)]}</span> : <span className="badge soon">Network</span>) : <span className="badge ok">Local only</span>}</td></tr>)}
          </tbody></table>
        )}
      </section>
    </div>
  );
}

function RecordsView() {
  const toast = useToast();
  const [cats, setCats] = useState<string[]>(["antivirus", "authentication", "security_tests", "os_updates", "alerts"]);
  const [days, setDays] = useState(365);
  const [preview, setPreview] = useState<any>(null);
  const [confirm, setConfirm] = useState(false);
  const analyse = async () => { try { setPreview(await api("security/records", { query: { categories: cats.join(","), older_than_days: days } })); } catch (e: any) { toast(e.message, "error"); } };
  useEffect(() => { analyse(); }, []);
  const labels: Record<string, string> = preview?.available || {};
  return (
    <div className="stack">
      <section className="card">
        <h2>Security records <HelpTip text="Antivirus events, sign-in records, security tests, OS update runs and security alerts are kept at least one year." link="/help/security-center#retention" /></h2>
        <fieldset className="field"><legend>Categories</legend>
          {Object.entries(labels).map(([k, l]) => <label key={k} className="check"><input type="checkbox" checked={cats.includes(k)} onChange={(e) => setCats(e.target.checked ? [...cats, k] : cats.filter((x) => x !== k))} /> {l}</label>)}
        </fieldset>
        <div className="field"><label htmlFor="rec-days">Older than (days)</label><input id="rec-days" type="number" min={30} value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ maxWidth: 140 }} /></div>
        <div className="row"><button className="btn" onClick={analyse}>Cleanup analysis</button><button className="btn danger" disabled={!preview || !preview.total_records} onClick={() => setConfirm(true)}>Purge…</button></div>
      </section>
      {preview && (
        <section className="card"><h2>Cleanup analysis</h2>
          {preview.below_retention && <div className="alert warn">These records are younger than the retention period. Purging them shortens the security history.</div>}
          <table className="responsive"><thead><tr><th>Category</th><th>Records</th><th>Est. space</th><th>Protected</th></tr></thead><tbody>
            {preview.categories.map((c: any) => <tr key={c.key}><td>{c.label}</td><td>{c.records}{c.files ? ` + ${c.files} log file(s)` : ""}</td><td>{formatBytes(c.estimated_bytes)}</td><td>{c.protected}</td></tr>)}
          </tbody></table>
          <p className="small">Older than {formatDate(preview.before)} · {preview.total_records} record(s) · about {formatBytes(preview.estimated_bytes)}</p>
          <p className="small muted">{preview.protected_note}</p>
        </section>
      )}
      {confirm && preview && <Confirm title="Purge security records" danger confirmLabel={`Purge ${preview.total_records} record(s)`} message={<p>This permanently deletes the records listed in the analysis. A record of this purge is kept. Original documents are never affected.</p>}
        onClose={() => setConfirm(false)} onConfirm={async () => { try { const r = await api("security/records", { body: { categories: cats, older_than_days: days, confirm: true } }); toast(`Purged ${Object.values(r.removed).reduce((a: number, b: any) => a + b, 0)} record(s)`); setConfirm(false); analyse(); } catch (e: any) { toast(e.message, "error"); } }} />}
    </div>
  );
}

function StorageView() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<any>("security/storage?refresh=1"), []);
  const [kinds, setKinds] = useState<string[]>([]);
  const [confirm, setConfirm] = useState(false);
  if (!data) return <Skeleton lines={6} />;
  const cls = data.status === "critical" ? "danger" : data.status === "warning" ? "soon" : "ok";
  const max = Math.max(...data.categories.map((c: any) => c.bytes || 0), 1);
  return (
    <div className="stack">
      <section className="card">
        <h2>Storage Health <span className={`badge ${cls}`}>{data.status === "ok" ? "OK" : data.status}</span></h2>
        <div className="progress big" role="progressbar" aria-valuenow={data.percent} aria-valuemax={100} aria-label="Disk used"><div className={cls} style={{ width: `${data.percent}%` }} /></div>
        <p>{formatBytes(data.used)} of {formatBytes(data.total)} used ({data.percent}%) · {formatBytes(data.free)} free <span className="small muted">· warning at {data.thresholds.warning}%, critical at {data.thresholds.critical}%</span></p>
        <table className="responsive"><thead><tr><th>Category</th><th>Size</th><th className="hide-mobile" style={{ width: "40%" }} /></tr></thead><tbody>
          {data.categories.map((c: any) => <tr key={c.key}><td>{c.label}</td><td>{c.bytes === null ? "—" : formatBytes(c.bytes)}</td><td className="hide-mobile"><div className="progress"><div style={{ width: `${((c.bytes || 0) / max) * 100}%` }} /></div></td></tr>)}
        </tbody></table>
        {data.last_backup_bytes ? <p className="small muted">Last NAS backup: {formatBytes(data.last_backup_bytes)} (on the NAS, not this disk).</p> : null}
      </section>
      <section className="card">
        <h2>Safe cleanup</h2>
        <p className="small muted">Only regenerable or expired data can be removed here. Never removed: {data.cleanup.never.join("; ")}.</p>
        {data.cleanup.items.map((i: any) => <label key={i.key} className="check"><input type="checkbox" checked={kinds.includes(i.key)} disabled={!i.count} onChange={(e) => setKinds(e.target.checked ? [...kinds, i.key] : kinds.filter((x) => x !== i.key))} /> {i.label} — {i.count} item(s), about {formatBytes(i.bytes)}</label>)}
        <button className="btn" style={{ marginTop: ".6rem" }} disabled={!kinds.length} onClick={() => setConfirm(true)}>Clean up…</button>
      </section>
      <SettingsForm keys={["storage.warn_percent", "storage.critical_percent"]} title="Thresholds" />
      {confirm && <Confirm title="Clean up storage" confirmLabel="Clean up" message={<p>Removes the selected items. Original documents and quarantined files are not affected.</p>}
        onClose={() => setConfirm(false)} onConfirm={async () => { try { await api("security/storage", { body: { kinds, confirm: true } }); toast("Cleanup finished"); setConfirm(false); setKinds([]); reload(); } catch (e: any) { toast(e.message, "error"); } }} />}
    </div>
  );
}

const VIEWS: [string, string][] = [["overview", "Overview"], ["antivirus", "Antivirus"], ["test", "Security test"], ["updates", "OS updates"],
  ["firewall", "Firewall"], ["records", "Security records"], ["storage", "Storage"], ["access", "Access policy"]];

export default function SecurityCenter() {
  const [params, setParams] = useSearchParams();
  const { session } = useSession();
  const main = !!session?.user?.is_main_admin;
  const views = VIEWS.filter(([k]) => k !== "access" || main);
  const view = params.get("view") || "overview";
  return (
    <div className="stack">
      <nav className="tabs sub" aria-label="Security views">
        {views.map(([k, l]) => <button key={k} type="button" className={view === k ? "active" : ""} aria-current={view === k ? "page" : undefined} onClick={() => setParams(k === "overview" ? {} : { view: k })}>{l}</button>)}
      </nav>
      {view === "overview" && <OverviewView />}
      {view === "antivirus" && <AntivirusView />}
      {view === "test" && <SecurityTestView />}
      {view === "updates" && <UpdatesView />}
      {view === "firewall" && <FirewallView />}
      {view === "records" && <RecordsView />}
      {view === "storage" && <StorageView />}
      {view === "access" && main && <SecurityPanel />}
    </div>
  );
}
