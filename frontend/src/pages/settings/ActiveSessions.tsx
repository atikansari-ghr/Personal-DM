import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, formatDateTime } from "../../api";
import SettingsForm from "../../components/SettingsForm";
import { Confirm, HelpTip, Icon, Modal, Skeleton, useAsync, useToast } from "../../components/ui";
import { useSession } from "../../session";

/** Security → Active Sessions (Change Set AB). Active = activity within the configured threshold; Signed In = a valid
 * session that has been idle longer. Locations come from Trusted Zones first, then the private-network check, then
 * the local GeoIP database (approximate). No GPS, no cookies or tokens are ever shown. */

export type SessionRow = {
  id: string; current: boolean; user: { id: string; name: string; username: string }; state: "active" | "signed_in"; state_label: string;
  ip?: string | null; trust: string; network?: string; untrusted: boolean;
  location: { text: string; source: string; approximate: boolean; zone: string; country: string };
  device: { kind: string; browser: string; os: string; label: string; state: string; recognized_label?: string };
  login_at?: string; last_activity_at: string; idle_seconds: number; age_seconds?: number; method?: string; risk: string; risk_reasons?: string[];
};

const RISK_CLASS: Record<string, string> = { normal: "ok", low: "neutral", warning: "soon", high: "danger" };

export function ago(seconds: number) {
  if (seconds < 60) return "Active now";
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
}

export function StateBadge({ r }: { r: Pick<SessionRow, "state" | "state_label"> }) {
  return <span className={`badge ${r.state === "active" ? "ok" : "neutral"}`} data-session-state={r.state}>{r.state_label}</span>;
}

export function Place({ r }: { r: Pick<SessionRow, "location" | "trust" | "untrusted"> }) {
  return (
    <span className="small">
      {r.location.text}{r.location.approximate && <> · <abbr title="Approximate location from the local GeoIP database (country or city level, never a street address)">Approx.</abbr></>}
      {" · "}<span className={r.untrusted ? "warn-ink" : ""}>{r.trust}</span>
    </span>
  );
}

function Detail({ id, canTerminate, onClose, onDone }: { id: string; canTerminate: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const { data, error } = useAsync(() => api<SessionRow & { can_terminate: boolean }>(`security/sessions/${id}`), [id]);
  const [confirm, setConfirm] = useState(false);
  return (
    <Modal title="Session details" onClose={onClose}>
      {error && <div className="alert error">{error}</div>}
      {!data ? <Skeleton /> : (
        <div className="stack" data-session-detail={data.id}>
          <table className="kv-table small"><tbody>
            <tr><th>User</th><td>{data.user.name} ({data.user.username}){data.current && " — this session"}</td></tr>
            <tr><th>State <HelpTip id="sessions.active" /></th><td><StateBadge r={data} /> · last activity {ago(data.idle_seconds)} ({formatDateTime(data.last_activity_at)})</td></tr>
            <tr><th>IP address</th><td><code>{data.ip || "unknown"}</code></td></tr>
            <tr><th>Trust <HelpTip id="sessions.trusted_zone" /></th><td>{data.trust}{data.location.zone ? ` — Trusted Zone “${data.location.zone}”` : ""}</td></tr>
            <tr><th>Location <HelpTip id="sessions.approximate" /></th><td>{data.location.text} <span className="muted">({data.location.source})</span></td></tr>
            <tr><th>Device</th><td>{data.device.browser || "Browser"} on {data.device.os || "unknown system"} · {data.device.kind}</td></tr>
            <tr><th>Recognized device</th><td>{data.device.state === "recognized" ? `Recognized${data.device.recognized_label ? ` (${data.device.recognized_label})` : ""}` : data.device.state === "unrecognized" ? "Marked Unrecognized" : "Not recorded"}</td></tr>
            <tr><th>Sign-in method</th><td>{data.method || "—"}</td></tr>
            <tr><th>Signed in</th><td>{data.login_at ? formatDateTime(data.login_at) : "—"}{data.age_seconds != null ? ` (${ago(data.age_seconds).replace("Active now", "just now")})` : ""}</td></tr>
            <tr><th>Risk <HelpTip id="sessions.risk" /></th><td><span className={`badge ${RISK_CLASS[data.risk] || "neutral"}`}>{data.risk}</span>{(data.risk_reasons || []).length > 0 && <ul className="small">{data.risk_reasons!.map((x) => <li key={x}>{x}</li>)}</ul>}</td></tr>
          </tbody></table>
          {canTerminate && data.can_terminate && (
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn danger" onClick={() => setConfirm(true)} data-terminate>Terminate Session…</button> <HelpTip id="sessions.terminate" />
            </div>
          )}
          {data.current && <p className="small muted">This is your own current session: use Sign out to end it.</p>}
        </div>
      )}
      {confirm && data && <Confirm title="Terminate Session" danger confirmLabel="Terminate Session" onClose={() => setConfirm(false)}
        message={<div className="stack small"><p>{data.user.name}'s session on {data.device.browser || "a browser"} on {data.device.os || "an unknown system"} ends at once; that device must sign in again. Their other sessions are not affected and the device stays recognized (this is not Mark Unrecognized).</p><p>{data.user.name} is notified and the action is recorded in the audit log.</p></div>}
        onConfirm={async () => { try { await api(`security/sessions/${data.id}/terminate`, { body: { confirm: true } }); toast("Session terminated"); setConfirm(false); onDone(); } catch (e: any) { toast(e.message, "error"); } }} />}
    </Modal>
  );
}

export default function ActiveSessions() {
  const { session } = useSession();
  const main = !!session?.user?.is_main_admin;
  const [params, setParams] = useSearchParams();
  const [f, setF] = useState({ state: "", user: "", trust: "", risk: "", device: "", location: "" });
  const { data, error, reload } = useAsync(() => api<any>("security/sessions", { query: f }), [f]);
  const detail = params.get("session");
  const openDetail = (id: string | null) => { const p = new URLSearchParams(params); if (id) p.set("session", id); else p.delete("session"); setParams(p); };
  return (
    <div className="stack" data-active-sessions>
      <div className="card">
        <div className="row between" style={{ flexWrap: "wrap" }}>
          <h2 style={{ margin: 0 }}>Active Sessions <HelpTip id="sessions.page" /></h2>
          {data && <div className="row small" data-session-counts>
            <span className="badge ok">{data.counts.active} Active</span><span className="badge neutral">{data.counts.signed_in} Signed In</span>
            <span className={`badge ${data.counts.untrusted ? "soon" : "neutral"}`}>{data.counts.untrusted} Untrusted</span>
          </div>}
        </div>
        <p className="small muted">Active: activity within the last {data?.threshold_minutes ?? 5} minutes <HelpTip id="sessions.active" />. Signed In: still signed in but idle longer <HelpTip id="sessions.signed_in" />. Locations are approximate unless a Trusted Zone matches; no GPS is used.</p>
        <div className="row filter-row" style={{ flexWrap: "wrap", gap: ".4rem" }}>
          <select aria-label="State" value={f.state} onChange={(e) => setF({ ...f, state: e.target.value })}><option value="">Active and Signed In</option><option value="active">Active</option><option value="signed_in">Signed In (idle)</option></select>
          <select aria-label="User" value={f.user} onChange={(e) => setF({ ...f, user: e.target.value })}><option value="">Everyone</option>{(data?.users || []).map((u: any) => <option key={u.id} value={u.id}>{u.name}</option>)}</select>
          <select aria-label="Trust" value={f.trust} onChange={(e) => setF({ ...f, trust: e.target.value })}><option value="">Any trust</option><option value="trusted">Trusted / private</option><option value="untrusted">Untrusted</option></select>
          <select aria-label="Risk" value={f.risk} onChange={(e) => setF({ ...f, risk: e.target.value })}><option value="">Any risk</option>{["normal", "low", "warning", "high"].map((x) => <option key={x} value={x}>{x}</option>)}</select>
          <select aria-label="Device" value={f.device} onChange={(e) => setF({ ...f, device: e.target.value })}><option value="">Any device</option>{["desktop", "mobile", "tablet"].map((x) => <option key={x} value={x}>{x}</option>)}</select>
          <input type="search" aria-label="Location or Trusted Zone" placeholder="Location or Trusted Zone" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} />
          <button className="btn small" onClick={reload}><Icon name="refresh" size={14} /> Refresh</button>
        </div>
      </div>
      {error && <div className="alert error">{error}</div>}
      {!data ? <Skeleton lines={5} /> : data.sessions.length === 0 ? <div className="empty small">No sessions match.</div> : (
        <div className="card">
          <table className="responsive" data-session-table><thead><tr><th>User</th><th>State</th><th className="hide-mobile">IP address</th><th>Location / trust</th><th className="hide-mobile">Device</th><th className="hide-mobile">Signed in</th><th>Last activity</th><th className="hide-mobile">Method</th><th>Risk</th></tr></thead>
            <tbody>
              {data.sessions.map((r: SessionRow) => (
                <tr key={r.id} className="clickable" tabIndex={0} data-session={r.id} onClick={() => openDetail(r.id)} onKeyDown={(e) => e.key === "Enter" && openDetail(r.id)}>
                  <td><strong>{r.user.name}</strong>{r.current && <span className="badge neutral small">you</span>}</td>
                  <td><StateBadge r={r} /></td>
                  <td className="hide-mobile"><code>{r.ip || "—"}</code></td>
                  <td><Place r={r} /></td>
                  <td className="hide-mobile small">{r.device.browser} · {r.device.os} · {r.device.kind}{r.device.state === "recognized" ? " · recognized" : r.device.state === "unrecognized" ? " · unrecognized" : ""}</td>
                  <td className="hide-mobile small">{r.login_at ? formatDateTime(r.login_at) : "—"}</td>
                  <td className="small">{ago(r.idle_seconds)}</td>
                  <td className="hide-mobile small">{r.method}</td>
                  <td><span className={`badge ${RISK_CLASS[r.risk] || "neutral"}`}>{r.risk}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {main && <SettingsForm section="sessions" title="Sessions" />}
      <p className="small muted">Your own devices: <Link to="/settings/account?tab=security#sessions">My account → Sessions</Link>. Trusted Zones: <Link to="/settings/activity?view=map">Sign-in map & Trusted Zones</Link>.</p>
      {detail && <Detail id={detail} canTerminate={!!data?.can_terminate} onClose={() => openDetail(null)} onDone={() => { openDetail(null); reload(); }} />}
    </div>
  );
}

/** The Overview tile: compact (counts), medium (counts and a few people) or large (rows with device and location),
 * chosen from the tile's width — the same component at every size. */
export function SessionsTile({ cols }: { cols: number }) {
  const { data } = useAsync(() => api<any>("security/sessions/summary", { background: true }), []);
  if (!data) return <Skeleton lines={2} />;
  const mode = cols <= 3 ? "compact" : cols <= 6 ? "medium" : "large";
  const c = data.counts;
  return (
    <div className="stack sessions-tile" data-sessions-tile={mode}>
      <div className="row" style={{ gap: ".35rem", flexWrap: "wrap" }}>
        <strong data-count="active">{c.active} Active</strong><span className="muted">·</span><span data-count="signed_in">{c.signed_in} Signed In</span>
        {c.untrusted > 0 && <span className="badge soon" data-count="untrusted">{c.untrusted} Untrusted</span>}
      </div>
      {mode !== "compact" && (
        <ul className="sessions-rows">
          {data.sessions.slice(0, mode === "medium" ? 3 : 8).map((r: SessionRow) => (
            <li key={r.id} className="row between" style={{ flexWrap: "nowrap" }}>
              <strong className="ellipsis">{r.user.name.split(" ")[0]}</strong>
              <span className="small">{ago(r.idle_seconds)}</span>
              <span className="small ellipsis">{r.location.text}{r.location.approximate ? " · Approx." : ` · ${r.trust}`}</span>
              {mode === "large" && <span className="small muted ellipsis hide-mobile">{r.device.browser} · {r.device.os}</span>}
            </li>
          ))}
        </ul>
      )}
      <Link to={data.link} className="small">View All Sessions ›</Link>
    </div>
  );
}
