import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, formatBytes, formatDateTime } from "../../api";
import SettingsForm from "../../components/SettingsForm";
import { Confirm, HelpTip, Icon, Skeleton, useAsync, useToast } from "../../components/ui";

type Policy = {
  policy: { enabled: boolean; mode: "off" | "blocklist" | "allowlist"; unknown_action: "allow" | "deny"; updated_at: string; updated_by: string | null; can_rollback: boolean };
  allowed: string[];
  blocked: string[];
  temporary: { id: number; country: string; country_name: string; starts_at: string; ends_at: string; reason: string; state: string; created_by: string | null }[];
  ip_rules: { id: number; cidr: string; kind: "trusted" | "blocked"; description: string; enabled: boolean; expires_at: string | null; automatic: boolean; live: boolean; created_by: string | null; created_at: string }[];
  countries: Record<string, string>;
  you: { ip: string | null; allowed: boolean; reason: string; country: string; country_name: string };
  proxy: { trusted_proxies: string[]; peer: string | null; via_trusted_proxy: boolean; forwarded_header: boolean; client_ip: string | null };
  geoip: { installed: boolean; build_date: string | null; database_type: string | null; last_success: string | null; last_attempt: string | null; last_error: string | null };
  emergency_disabled: boolean;
};

const REASONS: Record<string, string> = {
  internal: "LAN / internal address (always allowed)", ip_trusted: "trusted IP", ip_blocked: "blocked IP", policy_off: "policy off",
  country_unknown: "country unknown", temporary_access: "temporary access", country_allowed: "allowed country",
  country_not_allowed: "country not in allow list", country_blocked: "blocked country", country_not_blocked: "country not blocked",
  health_check: "health check", emergency_disabled: "emergency switch on the server", no_address: "no address",
};

function CountryPicker({ label, value, onChange, countries }: { label: string; value: string[]; onChange: (v: string[]) => void; countries: Record<string, string> }) {
  const [text, setText] = useState("");
  const id = `cp-${label.replace(/\W/g, "")}`;
  const add = () => {
    const t = text.trim();
    const code = Object.keys(countries).find((c) => c === t.toUpperCase() || countries[c].toLowerCase() === t.toLowerCase() || `${countries[c]} (${c})` === t);
    if (code && !value.includes(code)) onChange([...value, code].sort());
    setText("");
  };
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="row">
        {value.map((c) => <span key={c} className="badge">{countries[c] || c} ({c}) <button type="button" className="icon-btn" style={{ minWidth: 18, minHeight: 18, padding: 0 }} aria-label={`Remove ${countries[c] || c}`} onClick={() => onChange(value.filter((x) => x !== c))}>×</button></span>)}
        {value.length === 0 && <span className="small muted">None selected</span>}
      </div>
      <div className="row">
        <input id={id} list={`${id}-list`} type="text" placeholder="Type a country, e.g. Saudi Arabia" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} style={{ maxWidth: 320 }} />
        <datalist id={`${id}-list`}>{Object.entries(countries).map(([c, n]) => <option key={c} value={`${n} (${c})`} />)}</datalist>
        <button type="button" className="btn small" onClick={add} disabled={!text.trim()}>Add</button>
      </div>
    </div>
  );
}

function PolicyCard({ data, reload }: { data: Policy; reload: () => void }) {
  const toast = useToast();
  const [enabled, setEnabled] = useState(data.policy.enabled);
  const [mode, setMode] = useState(data.policy.mode === "off" ? "allowlist" : data.policy.mode);
  const [unknown, setUnknown] = useState(data.policy.unknown_action);
  const [allowed, setAllowed] = useState(data.allowed);
  const [blocked, setBlocked] = useState(data.blocked);
  const [lockout, setLockout] = useState<string | null>(null);
  const [confirmApply, setConfirmApply] = useState(false);
  const save = (confirm_lockout = false) =>
    api("admin/security/policy", { method: "PUT", body: { enabled, mode: enabled ? mode : "off", unknown_action: unknown, allowed, blocked, confirm_lockout } })
      .then(() => { toast("Access policy saved"); setLockout(null); reload(); })
      .catch((e: ApiError) => (e.status === 409 ? setLockout(e.message) : toast(e.message, "error")));
  const active = data.policy.enabled && data.policy.mode !== "off";
  const effect = !enabled ? "Country filtering will be OFF: every country can reach the sign-in page (IP rules still apply)."
    : mode === "allowlist" ? `ALLOW LIST: only ${allowed.map((c) => data.countries[c] || c).join(", ") || "no countries"} can reach the app. Every other country is blocked before sign-in.`
      : `BLOCK LIST: every country can reach the app except ${blocked.map((c) => data.countries[c] || c).join(", ") || "none"}.`;
  return (
    <div className="card">
      <h2>Geographic access control <HelpTip text="Applied before sign-in, to every request. LAN addresses, trusted IPs and the health check are always allowed." link="/help/security-access#country-policy" /></h2>
      <div className={`banner ${active ? (data.policy.mode === "allowlist" ? "warn" : "info") : ""}`} role="status" style={{ padding: ".6rem .8rem", borderRadius: 8, background: active ? "var(--warn-bg)" : "var(--brand-soft)", color: active ? "var(--warn-ink)" : undefined }}>
        <strong>Active now: </strong>
        {!active ? "Off — no country filtering." : data.policy.mode === "allowlist" ? `Allow list — only ${data.allowed.map((c) => data.countries[c] || c).join(", ")}` : `Block list — blocking ${data.blocked.map((c) => data.countries[c] || c).join(", ") || "no countries"}`}
        {data.policy.updated_by && <span className="small muted"> · changed by {data.policy.updated_by} {formatDateTime(data.policy.updated_at)}</span>}
      </div>
      {data.emergency_disabled && <p className="error-text">The server's emergency switch (PD_ACCESS_POLICY_DISABLED=1) is on: the policy is not enforced.</p>}
      <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enable geographic access control</label>
      {enabled && (
        <>
          <fieldset className="field"><legend>Policy mode</legend>
            <label className="check"><input type="radio" name="geo-mode" checked={mode === "allowlist"} onChange={() => setMode("allowlist")} /> <strong>Allow list</strong> — block every country except the ones selected</label>
            <label className="check"><input type="radio" name="geo-mode" checked={mode === "blocklist"} onChange={() => setMode("blocklist")} /> <strong>Block list</strong> — allow every country except the ones selected</label>
          </fieldset>
          {mode === "allowlist" ? <CountryPicker label="Allowed countries" value={allowed} onChange={setAllowed} countries={data.countries} />
            : <CountryPicker label="Blocked countries" value={blocked} onChange={setBlocked} countries={data.countries} />}
          <div className="field"><label htmlFor="geo-unknown">When the country cannot be determined</label>
            <select id="geo-unknown" value={unknown} onChange={(e) => setUnknown(e.target.value as any)} style={{ maxWidth: 260 }}>
              <option value="allow">Allow (safer against lock-outs)</option><option value="deny">Deny (stricter)</option>
            </select>
            <p className="small muted">Happens when no GeoIP database is installed or the address is not in it.</p></div>
        </>
      )}
      <p className="small"><strong>Effect:</strong> {effect}</p>
      <div className="row">
        <button className="btn primary" onClick={() => (enabled && mode === "allowlist" ? setConfirmApply(true) : save())}>Apply policy</button>
        {data.policy.can_rollback && <button className="btn" onClick={() => api("admin/security/policy/rollback", { method: "POST" }).then(() => { toast("Previous policy restored"); reload(); })}>Undo last change</button>}
      </div>
      <p className="small muted">Locked out? On the server run <code>personaldocs access-policy off</code> (or <code>trust-ip &lt;your IP&gt;</code>). <Link to="/help/security-access#recovery">Recovery guide</Link></p>
      {confirmApply && <Confirm title="Activate allow list?" message={effect + " Make sure family members who travel have temporary access."} confirmLabel="Activate" onConfirm={() => { setConfirmApply(false); save(); }} onClose={() => setConfirmApply(false)} />}
      {lockout && <Confirm title="You may lock yourself out" danger message={lockout} confirmLabel="Apply anyway" onConfirm={() => save(true)} onClose={() => setLockout(null)} />}
    </div>
  );
}

function ConnectionCard({ data }: { data: Policy }) {
  const p = data.proxy;
  const proxyWarning = !p.via_trusted_proxy && p.forwarded_header
    ? `Your request arrived from ${p.peer} with a forwarded header, but that address is not a trusted proxy. Add it to PD_TRUSTED_PROXY_IPS so real client IPs are used.`
    : "";
  return (
    <div className="card">
      <h2>Your connection <HelpTip text="How the server sees you right now: the real client IP after trusted-proxy handling, and what the policy decides for it." link="/help/security-access#real-ip" /></h2>
      <p>IP <strong>{data.you.ip || "unknown"}</strong> · {data.you.country_name || "country unknown"} · <span className={`badge ${data.you.allowed ? "ok" : "danger"}`}>{data.you.allowed ? "allowed" : "denied"}</span> <span className="small muted">({REASONS[data.you.reason] || data.you.reason})</span></p>
      <p className="small">Trusted proxies: {p.trusted_proxies.join(", ") || "none"} · request came {p.via_trusted_proxy ? `through trusted proxy ${p.peer}` : `directly from ${p.peer}`}</p>
      {proxyWarning && <p className="error-text small">{proxyWarning}</p>}
    </div>
  );
}

function TemporaryCard({ data, reload }: { data: Policy; reload: () => void }) {
  const toast = useToast();
  const now = new Date();
  const local = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [f, setF] = useState({ country: "", starts_at: local(now), ends_at: local(new Date(now.getTime() + 14 * 86400000)), reason: "" });
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const code = Object.keys(data.countries).find((c) => `${data.countries[c]} (${c})` === f.country || c === f.country.toUpperCase()) || f.country;
    api("admin/security/temporary", { body: { ...f, country: code, starts_at: new Date(f.starts_at).toISOString(), ends_at: new Date(f.ends_at).toISOString() } })
      .then(() => { toast("Temporary access added"); setF({ ...f, country: "", reason: "" }); reload(); }).catch((x) => toast(x.message, "error"));
  };
  return (
    <div className="card">
      <h2>Temporary country access <HelpTip text="For travel: allows a country for a time window even if the policy blocks it. It stops working automatically at the end time." link="/help/security-access#temporary" /></h2>
      {data.temporary.length === 0 ? <p className="small muted">No temporary access rules.</p> : (
        <table className="responsive"><thead><tr><th>Country</th><th>Window</th><th>Reason</th><th>State</th><th /></tr></thead><tbody>
          {data.temporary.map((t) => <tr key={t.id}><td>{t.country_name}</td><td className="small">{formatDateTime(t.starts_at)} → {formatDateTime(t.ends_at)}</td><td className="small">{t.reason}<div className="muted">{t.created_by}</div></td>
            <td><span className={`badge ${t.state === "active" ? "ok" : t.state === "expired" ? "neutral" : ""}`}>{t.state}</span></td>
            <td><button className="btn small ghost" onClick={() => api(`admin/security/temporary/${t.id}`, { method: "DELETE" }).then(reload)}>Remove</button></td></tr>)}
        </tbody></table>
      )}
      <form className="row" onSubmit={submit} style={{ alignItems: "flex-end" }}>
        <div className="field"><label htmlFor="tmp-country">Country</label><input id="tmp-country" list="tmp-country-list" type="text" required value={f.country} onChange={(e) => setF({ ...f, country: e.target.value })} style={{ maxWidth: 220 }} />
          <datalist id="tmp-country-list">{Object.entries(data.countries).map(([c, n]) => <option key={c} value={`${n} (${c})`} />)}</datalist></div>
        <div className="field"><label htmlFor="tmp-start">From</label><input id="tmp-start" type="datetime-local" required value={f.starts_at} onChange={(e) => setF({ ...f, starts_at: e.target.value })} /></div>
        <div className="field"><label htmlFor="tmp-end">Until</label><input id="tmp-end" type="datetime-local" required value={f.ends_at} onChange={(e) => setF({ ...f, ends_at: e.target.value })} /></div>
        <div className="field"><label htmlFor="tmp-reason">Reason</label><input id="tmp-reason" type="text" required placeholder="Family trip" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} style={{ maxWidth: 220 }} /></div>
        <button className="btn">Add</button>
      </form>
    </div>
  );
}

function IpRulesCard({ data, reload }: { data: Policy; reload: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ cidr: "", kind: "trusted", description: "", expires_at: "" });
  const [lockout, setLockout] = useState<string | null>(null);
  const add = (confirm_lockout = false) =>
    api("admin/security/ip-rules", { body: { ...f, expires_at: f.expires_at ? new Date(f.expires_at).toISOString() : null, confirm_lockout } })
      .then(() => { toast("IP rule added"); setF({ cidr: "", kind: f.kind, description: "", expires_at: "" }); setLockout(null); reload(); })
      .catch((e: ApiError) => (e.status === 409 ? setLockout(e.message) : toast(e.message, "error")));
  return (
    <div className="card">
      <h2>Trusted and blocked IP addresses <HelpTip text="Order: a blocked IP always wins, then trusted IPs bypass the country policy. Addresses or CIDR ranges, IPv4 or IPv6." link="/help/security-access#ip-rules" /></h2>
      {data.ip_rules.length === 0 ? <p className="small muted">No IP rules.</p> : (
        <table className="responsive"><thead><tr><th>Address</th><th>Type</th><th>Description</th><th>Expires</th><th>Enabled</th><th /></tr></thead><tbody>
          {data.ip_rules.map((r) => <tr key={r.id}><td><code>{r.cidr}</code></td><td><span className={`badge ${r.kind === "trusted" ? "ok" : "danger"}`}>{r.kind}</span>{r.automatic && <span className="badge neutral">automatic</span>}</td>
            <td className="small">{r.description}<div className="muted">{r.created_by}</div></td><td className="small">{r.expires_at ? formatDateTime(r.expires_at) : "never"}{!r.live && r.enabled && <div className="muted">expired</div>}</td>
            <td><input type="checkbox" aria-label={`Enable ${r.cidr}`} checked={r.enabled} onChange={(e) => api(`admin/security/ip-rules/${r.id}`, { method: "PATCH", body: { enabled: e.target.checked } }).then(reload).catch((x) => toast(x.message, "error"))} /></td>
            <td><button className="btn small ghost" onClick={() => api(`admin/security/ip-rules/${r.id}`, { method: "DELETE" }).then(reload)}>Remove</button></td></tr>)}
        </tbody></table>
      )}
      <form className="row" onSubmit={(e) => { e.preventDefault(); add(); }} style={{ alignItems: "flex-end" }}>
        <div className="field"><label htmlFor="ip-cidr">IP or CIDR</label><input id="ip-cidr" type="text" required placeholder="203.0.113.7 or 203.0.113.0/24" value={f.cidr} onChange={(e) => setF({ ...f, cidr: e.target.value })} style={{ maxWidth: 230 }} /></div>
        <div className="field"><label htmlFor="ip-kind">Type</label><select id="ip-kind" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="trusted">Trusted</option><option value="blocked">Blocked</option></select></div>
        <div className="field"><label htmlFor="ip-desc">{f.kind === "blocked" ? "Reason" : "Description"}</label><input id="ip-desc" type="text" required={f.kind === "blocked"} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} style={{ maxWidth: 220 }} /></div>
        <div className="field"><label htmlFor="ip-exp">Expires (optional)</label><input id="ip-exp" type="datetime-local" value={f.expires_at} onChange={(e) => setF({ ...f, expires_at: e.target.value })} /></div>
        <button className="btn">Add</button>
      </form>
      {lockout && <Confirm title="This includes your own address" danger message={lockout} confirmLabel="Block anyway" onConfirm={() => add(true)} onClose={() => setLockout(null)} />}
    </div>
  );
}

function GeoIpCard({ data, reload }: { data: Policy; reload: () => void }) {
  const toast = useToast();
  const g = data.geoip;
  const [ip, setIp] = useState("");
  const [result, setResult] = useState<string>("");
  const upload = (file: File) => {
    const form = new FormData();
    form.append("file", file);
    api("admin/security/geoip/upload", { form }).then(() => { toast("GeoIP database installed"); reload(); }).catch((x) => toast(x.message, "error"));
  };
  return (
    <div className="card">
      <h2>GeoIP database <HelpTip text="Country lookups use a database on this server; visitor addresses are never sent to a lookup service." link="/help/security-access#geoip" /></h2>
      <div className="row">
        <span className={`badge ${g.installed && !g.last_error ? "ok" : g.installed ? "warn" : "danger"}`}>{g.installed ? `Installed (${g.database_type})` : "Not installed"}</span>
        {g.build_date && <span className="small">Database date {g.build_date}</span>}
        {g.last_success && <span className="small muted">Last update {formatDateTime(g.last_success)}</span>}
      </div>
      {g.last_error && <p className="error-text small">Last problem: {g.last_error}</p>}
      <p className="small muted">Enter the free MaxMind account ID and license key below (Alerts & protection), then update. Location is approximate: mobile networks, VPNs and company networks often appear elsewhere.</p>
      <div className="row">
        <button className="btn" onClick={() => api("admin/security/geoip", { body: { action: "update" } }).then(() => toast("Update queued — refresh in a minute")).catch((x) => toast(x.message, "error"))}>Update now</button>
        <label className="btn">Upload .mmdb<input type="file" accept=".mmdb" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>
        <button className="btn small" onClick={reload}><Icon name="refresh" size={16} /> Refresh</button>
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); api("admin/security/policy/test", { body: { ip } }).then((r) => setResult(`${r.ip}: ${r.country_name || "unknown country"} → ${r.allowed ? "allowed" : "DENIED"} (${REASONS[r.reason] || r.reason})`)).catch((x) => setResult(x.message)); }}>
        <label htmlFor="geo-test" className="sr-only">Address to test</label>
        <input id="geo-test" type="text" placeholder="Test an address against the policy" value={ip} onChange={(e) => setIp(e.target.value)} style={{ maxWidth: 280 }} />
        <button className="btn small" disabled={!ip}>Test</button>
        {result && <span className="small" role="status">{result}</span>}
      </form>
    </div>
  );
}

export function SecurityPanel() {
  const state = useAsync(() => api<Policy>("admin/security/policy"), []);
  if (!state.data) return state.error ? <p className="error-text">{state.error}</p> : <Skeleton lines={6} />;
  return (
    <div className="stack">
      <ConnectionCard data={state.data} />
      <PolicyCard key={state.data.policy.updated_at} data={state.data} reload={state.reload} />
      <TemporaryCard data={state.data} reload={state.reload} />
      <IpRulesCard data={state.data} reload={state.reload} />
      <GeoIpCard data={state.data} reload={state.reload} />
      <SettingsForm section="security" title="Alerts, login protection, GeoIP and traffic analytics" />
      <p className="small muted">Authentication options (passkeys, two-step verification policy) are under <Link to="/settings/authentication">Authentication</Link>. Sign-in history is in <Link to="/settings/activity?view=logins">Activity & health → Login audit</Link>.</p>
    </div>
  );
}

const FLAG_LABEL: Record<string, string> = { new_ip: "new IP", new_country: "new country", policy_exception: "temporary access", escalated: "auto-blocked" };

export function LoginAuditPanel() {
  const members = useAsync(() => api<{ members: { id: string; display_name: string }[] }>("family/members"), []);
  const [f, setF] = useState({ user: "", username: "", ip: "", country: "", result: "", method: "", from: "", to: "" });
  const [offset, setOffset] = useState(0);
  const q = useMemo(() => ({ ...f, offset }), [f, offset]);
  const data = useAsync(() => api<any>("admin/security/logins", { query: q }), [JSON.stringify(q)]);
  const set = (k: string, v: string) => { setOffset(0); setF({ ...f, [k]: v }); };
  const s = data.data?.summary;
  return (
    <div className="stack">
      {s && (
        <div className="grid stats" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          {[["Successful (24 h)", s.success_24h], ["Failed (24 h)", s.failed_24h], ["Successful (7 days)", s.success_7d], ["Failed (7 days)", s.failed_7d], ["New IP sign-ins (7 days)", s.new_ip_7d], ["New countries (7 days)", s.new_country_7d]].map(([l, v]) =>
            <div key={l as string} className="card"><div className="small muted">{l}</div><div style={{ fontSize: "1.6rem", fontWeight: 700 }}>{v}</div></div>)}
        </div>
      )}
      {s && (s.countries.length > 0 || s.top_failed_ips.length > 0) && (
        <div className="card">
          <h3>Last 7 days</h3>
          <div className="row" style={{ alignItems: "flex-start", gap: "2rem" }}>
            <div><div className="small muted">Countries</div><ul className="small">{s.countries.map((c: any) => <li key={c.country}>{c.country_name || c.country}: {c.success} ok, {c.failed} failed</li>)}</ul></div>
            <div><div className="small muted">Sign-in methods</div><ul className="small">{s.methods.map((m: any) => <li key={m.method}>{m.method}: {m.n}</li>)}</ul></div>
            <div><div className="small muted">Most failed attempts</div><ul className="small">{s.top_failed_ips.map((m: any) => <li key={m.ip}><button className="link" onClick={() => set("ip", m.ip)}>{m.ip}</button> {m.country} · {m.n}</li>)}</ul></div>
          </div>
        </div>
      )}
      <div className="card">
        <h2>Login audit <HelpTip text="Every sign-in, failure and sign-out recorded by the app itself, with the real client IP and local GeoIP country. Never contains passwords or codes." link="/help/security-access#login-audit" /></h2>
        <div className="row">
          <select aria-label="Person" value={f.user} onChange={(e) => set("user", e.target.value)} style={{ maxWidth: 170 }}><option value="">Everyone</option>{members.data?.members.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}</select>
          <input aria-label="Username typed" type="text" placeholder="Username" value={f.username} onChange={(e) => set("username", e.target.value)} style={{ maxWidth: 140 }} />
          <input aria-label="IP address" type="text" placeholder="IP" value={f.ip} onChange={(e) => set("ip", e.target.value)} style={{ maxWidth: 150 }} />
          <input aria-label="Country code" type="text" placeholder="Country (SA)" maxLength={2} value={f.country} onChange={(e) => set("country", e.target.value)} style={{ maxWidth: 110 }} />
          <select aria-label="Result" value={f.result} onChange={(e) => set("result", e.target.value)} style={{ maxWidth: 140 }}><option value="">Any result</option><option value="success">Success</option><option value="failure">Failure</option><option value="denied">Denied</option><option value="logout">Sign-out</option></select>
          <select aria-label="Method" value={f.method} onChange={(e) => set("method", e.target.value)} style={{ maxWidth: 160 }}><option value="">Any method</option>{["password", "totp", "passkey", "google", "recovery"].map((m) => <option key={m} value={m}>{m}</option>)}</select>
          <input aria-label="From date" type="date" value={f.from} onChange={(e) => set("from", e.target.value)} />
          <input aria-label="To date" type="date" value={f.to} onChange={(e) => set("to", e.target.value)} />
        </div>
        {data.data ? (
          <>
            <table className="responsive"><thead><tr><th>When</th><th>Account</th><th>Result</th><th>Method</th><th>From</th><th className="hide-mobile">Device</th></tr></thead><tbody>
              {data.data.events.map((e: any) => <tr key={e.id}><td className="small">{formatDateTime(e.at)}</td><td>{e.user || <span className="muted">{e.username || "—"}</span>}</td>
                <td><span className={`badge ${e.result === "success" ? "ok" : e.result === "logout" ? "neutral" : "danger"}`}>{e.result}</span>{e.reason && <div className="small muted">{e.reason}</div>}</td>
                <td className="small">{e.method}</td><td className="small"><code>{e.ip}</code> {e.country_name}{e.flags.map((x: string) => <span key={x} className="badge warn" style={{ marginLeft: 4 }}>{FLAG_LABEL[x] || x}</span>)}</td>
                <td className="small muted hide-mobile">{e.browser} · {e.os} · {e.device}</td></tr>)}
            </tbody></table>
            <div className="row">{offset > 0 && <button className="btn small" onClick={() => setOffset(offset - 100)}>Newer</button>}{offset + 100 < data.data.total && <button className="btn small" onClick={() => setOffset(offset + 100)}>Older</button>}<span className="small muted">{data.data.total} events · kept {data.data.retention_days || "forever"} days</span></div>
          </>
        ) : <Skeleton />}
      </div>
    </div>
  );
}

export function TrafficPanel() {
  const toast = useToast();
  const t = useAsync(() => api<any>("admin/security/traffic"), []);
  if (!t.data) return <Skeleton lines={5} />;
  const s = t.data.summary;
  const st = t.data.status;
  return (
    <div className="stack">
      <div className="card">
        <h2>Traffic analytics <HelpTip text="Summarised from the app's privacy-safe access log by GoAccess (or the built-in summary). Nothing is published; only the main administrator sees this." link="/help/security-access#goaccess" /></h2>
        {!t.data.enabled && <p>Traffic analytics is off. Turn on <strong>Traffic analytics (GoAccess)</strong> in <Link to="/settings/security?view=access">Security → Access policy</Link>.</p>}
        <div className="row">
          <span className={`badge ${st.goaccess_installed ? "ok" : "neutral"}`}>{st.goaccess_installed ? "GoAccess installed" : "GoAccess not installed (built-in summary)"}</span>
          <span className={`badge ${st.access_log_exists ? "ok" : "warn"}`}>{st.access_log_exists ? "Access log active" : "No access log yet"}</span>
          {st.last_report && <span className="small muted">Report from {formatDateTime(st.last_report)} ({st.source})</span>}
        </div>
        {st.error && <p className="error-text small">{st.error}</p>}
        <div className="row">
          <button className="btn" onClick={() => api("admin/security/traffic", { method: "POST" }).then(() => toast("Report queued — refresh in a moment"))}>Build report now</button>
          <button className="btn small" onClick={t.reload}><Icon name="refresh" size={16} /> Refresh</button>
          {st.source === "goaccess" && <a className="btn small" href="/api/admin/security/traffic/report.html">Download full GoAccess report</a>}
        </div>
      </div>
      {s && (
        <>
          <div className="grid stats" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
            {[["Requests", s.requests], ["Unique visitors", s.visitors], ["Bandwidth", formatBytes(s.bandwidth)], ["401 / 403 / 404", `${s.errors["401"]} / ${s.errors["403"]} / ${s.errors["404"]}`], ["Bots / scanners", s.bots ?? "—"]].map(([l, v]) =>
              <div key={l as string} className="card"><div className="small muted">{l}</div><div style={{ fontSize: "1.4rem", fontWeight: 700 }}>{v}</div></div>)}
          </div>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
            <div className="card"><h3>Countries</h3><ul className="small">{s.countries.map((c: any) => <li key={c.country}>{c.country}: {c.requests}</li>)}</ul></div>
            <div className="card"><h3>Top source IPs</h3><ul className="small">{s.top_ips.map((c: any) => <li key={c.ip}><code>{c.ip}</code>: {c.requests}</li>)}</ul></div>
            <div className="card"><h3>Status codes</h3><ul className="small">{Object.entries(s.statuses).map(([k, v]) => <li key={k}>{k}: {String(v)}</li>)}</ul></div>
            <div className="card"><h3>Requested paths</h3><ul className="small">{s.endpoints.map((c: any) => <li key={c.path}><code>{c.path}</code>: {c.requests}</li>)}</ul></div>
            <div className="card"><h3>User agents</h3><ul className="small">{s.user_agents.map((c: any) => <li key={c.agent} style={{ wordBreak: "break-all" }}>{c.agent}: {c.requests}</li>)}</ul></div>
            <div className="card"><h3>Requests per day</h3><ul className="small">{s.per_day.map((c: any) => <li key={c.day}>{c.day}: {c.requests}</li>)}</ul></div>
          </div>
        </>
      )}
      <div className="card"><h3>Refused by the access policy (7 days)</h3>
        {t.data.blocked.length === 0 ? <p className="small muted">Nothing refused.</p> : <ul className="small">{t.data.blocked.map((b: any, i: number) => <li key={i}>{REASONS[b.reason] || b.reason}{b.country && ` · ${b.country}`}: {b.requests}</li>)}</ul>}
      </div>
    </div>
  );
}
