import { lazy, Suspense, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatDateTime } from "../../api";
import { useSession } from "../../session";
import { HelpTip, Icon, Modal, Skeleton, useAsync, useToast } from "../../components/ui";

const SigninMap = lazy(() => import("../../components/SigninMap"));
import { MapUnavailable } from "../../components/MapUnavailable";

const RISK: Record<string, [string, string]> = { normal: ["Normal", "ok"], low: ["Low", "neutral"], warning: ["Warning", "warn"], high: ["High", "danger"] };

/** My account → Sign-in security: map, recent sign-ins with explainable risk, recognised devices. Administrators
 * (main administrator: everyone; membership delegates: their group) can switch the person. */
const PERIODS: [string, string][] = [["today", "Today"], ["7", "Last 7 days"], ["30", "Last 30 days"], ["90", "Last 90 days"], ["365", "Last year"], ["custom", "Custom range…"]];

/** My account → Sign-in security: map and list share one filtered dataset (default: last 7 days), markers and list rows
 * select each other, details open on click/tap. Administrators (main administrator: everyone; membership delegates:
 * their group) can switch the person; the server enforces the scope. */
export function SigninSecurity({ adminView = false }: { adminView?: boolean }) {
  const { session } = useSession();
  const toast = useToast();
  const [who, setWho] = useState(adminView ? "all" : "");
  const [f, setF] = useState({ period: "7", from: "", to: "", trust: "", risk: "", device: "" });
  const [selected, setSelected] = useState<number[]>([]);
  const [unrec, setUnrec] = useState<any | null>(null);
  const [next, setNext] = useState<any[] | null>(null);
  const q = { user: who || undefined, period: f.period, from: f.period === "custom" ? f.from : undefined, to: f.period === "custom" ? f.to : undefined,
    trust: f.trust || undefined, risk: f.risk || undefined, device: f.device || undefined };
  const ready = f.period !== "custom" || (f.from && f.to);
  const map = useAsync<any>(() => (ready ? api("security/map", { query: q }) : Promise.resolve(null)), [JSON.stringify(q), ready]);
  const devices = useAsync<any>(() => api("security/devices", { query: { user: who && who !== "all" ? who : undefined } }), [who]);
  const mark = (d: any) => api(`security/devices/${d.id}/unrecognize`, { method: "POST" }).then((r) => { setUnrec(null); setNext(r.next_steps); devices.reload(); toast(`${r.sessions_ended} session(s) ended`); }).catch((e) => toast(e.message, "error"));
  const own = !who || who === String(session?.user?.id);
  const events: any[] = map.data?.events || [];
  const chosen = events.filter((e) => selected.includes(e.id));
  const set = (k: string, v: string) => { setSelected([]); setF({ ...f, [k]: v }); };
  return (
    <div className="stack signins">
      <section className="card">
        <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <h2 style={{ margin: 0 }}>Sign-in map <HelpTip id="map.markers" /></h2>
        </div>
        <div className="row map-filters" style={{ gap: 8, flexWrap: "wrap", marginTop: 6 }} role="group" aria-label="Filters for the map and the list">
          {map.data?.people?.length > 0 && <select aria-label="Person" value={who} onChange={(e) => { setSelected([]); setWho(e.target.value); }}>
            {adminView && <option value="all">Everyone I may see</option>}<option value="">Me</option>
            {map.data.people.filter((p: any) => p.id !== String(session?.user?.id)).map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
          <select aria-label="Period" value={f.period} onChange={(e) => set("period", e.target.value)}>{PERIODS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          {f.period === "custom" && <><input type="date" aria-label="From" value={f.from} onChange={(e) => set("from", e.target.value)} /><input type="date" aria-label="To" value={f.to} onChange={(e) => set("to", e.target.value)} /></>}
          <select aria-label="Trusted Zone" value={f.trust} onChange={(e) => set("trust", e.target.value)}><option value="">All networks</option><option value="trusted">In a Trusted Zone</option><option value="untrusted">Not in a Trusted Zone</option>
            {(map.data?.zones_for_filter || []).map((z: any) => <option key={z.id} value={`zone:${z.id}`}>Zone: {z.name}</option>)}</select>
          <select aria-label="Risk" value={f.risk} onChange={(e) => set("risk", e.target.value)}><option value="">Any risk</option>{Object.entries(RISK).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}</select>
          <select aria-label="Device" value={f.device} onChange={(e) => set("device", e.target.value)}><option value="">Any device</option><option value="recognized">Recognised device</option><option value="unrecognized">Unrecognized device</option><option value="new">New device</option></select>
          <HelpTip id="map.filters" />
        </div>
        {!ready ? <p className="small muted">Choose a start and end date.</p> : map.loading && !map.data ? <Skeleton lines={6} /> : map.data && (
          <>
            {map.data.map.enabled ? <Suspense fallback={<Skeleton lines={6} />}><SigninMap events={events} zones={map.data.zones} config={map.data.map} selected={selected} onSelect={setSelected} /></Suspense>
              : map.data.map.unavailable ? <MapUnavailable reason={map.data.map.unavailable} admin={map.data.map.admin} />
              : <p className="muted">The map is turned off by the administrator; the list below shows every sign-in.</p>}
            <p className="small muted"><Icon name="lock" size={14} /> {map.data.map.privacy} History is kept {map.data.retention_days} days.{map.data.map.english_labels ? " Place names are shown in English." : ""}</p>
            <div className="legend small"><span><i className="dot zone" /> Configured Trusted Zone location</span><span><i className="dot city" /> GeoIP (approximate)</span><span><i className="dot country" /> GeoIP country level</span><span><i className="dot cluster" /> Several sign-ins (number)</span></div>
          </>
        )}
        {chosen.length > 0 && <SigninDetails events={chosen} showPerson={!own || adminView} onPick={(id) => setSelected([id])} onClose={() => setSelected([])} />}
      </section>
      <section className="card">
        <h2>Recent sign-ins <span className="small muted">({events.length}, same filters as the map)</span></h2>
        {map.data && (events.length ? <div className="table-wrap"><table className="table signin-list">
          <thead><tr><th>When</th>{(!own || adminView) && <th>Person</th>}<th>Location / network</th><th>IP address</th><th>Device</th><th>Risk</th></tr></thead>
          <tbody>{events.slice(0, 200).map((e: any) => <tr key={e.id} data-event={e.id} className={`${e.risk === "high" ? "risk-high" : ""} ${selected.includes(e.id) ? "selected" : ""}`} aria-selected={selected.includes(e.id)}
            tabIndex={0} onClick={() => setSelected([e.id])} onKeyDown={(k) => { if (k.key === "Enter") setSelected([e.id]); }}>
            <td>{formatDateTime(e.at)}<div className="small muted">{e.result === "success" ? e.method : `${e.result} (${e.method || "—"})`}</div></td>
            {(!own || adminView) && <td>{e.user}</td>}
            <td>{e.location || "—"}{e.lat == null && <span className="badge neutral" style={{ marginLeft: 6 }}>Location unavailable</span>}<div className="small muted">{e.network === "trusted_zone" ? `${e.zone} — Trusted Zone` : e.network === "private" ? "Private network" : e.network === "public" ? "Public network" : ""}{e.coord_label ? ` · ${e.coord_label}` : ""}</div></td>
            <td><code className="small">{e.ip || "—"}</code></td>
            <td className="small">{e.device || "—"}{e.new_device && <div><span className="badge neutral">new device</span></div>}{e.device_state === "unrecognized" && <div><span className="badge danger">Unrecognized</span></div>}</td>
            <td>{e.risk && RISK[e.risk] ? <><span className={`badge ${RISK[e.risk][1]}`}>{RISK[e.risk][0]}</span>{e.risk_reasons?.length > 0 && <details className="small" onClick={(x) => x.stopPropagation()}><summary>Why</summary><ul>{e.risk_reasons.map((r: string) => <li key={r}>{r}</li>)}</ul></details>}</> : "—"}</td>
          </tr>)}</tbody></table></div> : <p className="muted">No sign-ins match these filters.</p>)}
        <p className="small muted">Risk is a hint, never a block: GeoIP can be wrong (mobile networks, VPNs). A sign-in from a Trusted Zone is not automatically safe. Select a row to show it on the map.</p>
      </section>
      <section className="card" id="devices">
        <h2>Recognised devices</h2>
        {devices.data && (devices.data.devices.length ? <ul className="plain device-list">{devices.data.devices.map((d: any) => <li key={d.id} className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
          <div><Icon name="monitor" size={16} /> <strong>{d.label}</strong>{d.current && <span className="badge ok" style={{ marginLeft: 6 }}>This device</span>}{d.status === "unrecognized" && <span className="badge danger" style={{ marginLeft: 6 }}>Unrecognized</span>}
            <div className="small muted">First seen {formatDateTime(d.first_seen)} · last {formatDateTime(d.last_seen)} · {d.active_sessions} active session(s){d.last_ip ? ` · ${d.last_ip}` : ""}</div></div>
          {d.status !== "unrecognized" && !d.current && <button className="btn small danger" onClick={() => setUnrec(d)}>Mark Unrecognized</button>}
        </li>)}</ul> : <p className="muted">No devices recorded yet.</p>)}
        <p className="small muted">To end a single session without distrusting the device, use <Link to="/settings/account?tab=security#sessions">Password & security → Sessions</Link>.</p>
      </section>
      {unrec && <Modal title="Mark this device Unrecognized?" onClose={() => setUnrec(null)}><div className="stack">
        <p><strong>{unrec.label}</strong> — every session of this device ends now and it is no longer recognised. You will get a security notification and the action is recorded in the audit log.</p>
        <p className="small muted">Your password, passkeys and other devices are not changed automatically. You can review them next.</p>
        <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn" onClick={() => setUnrec(null)}>Cancel</button><button className="btn danger" onClick={() => mark(unrec)}>Mark Unrecognized</button></div></div></Modal>}
      {next && <Modal title="Device marked Unrecognized" onClose={() => setNext(null)}><div className="stack">
        <p>Recommended next steps (nothing was changed automatically):</p>
        <ul className="plain">{next.map((s) => <li key={s.key}><Link to={s.path} onClick={() => setNext(null)}><Icon name="arrow" size={14} /> {s.label}</Link></li>)}</ul></div></Modal>}
    </div>
  );
}

/** Details of the sign-in(s) behind a marker or cluster (click/tap), or of a row selected in the list. */
function SigninDetails({ events, showPerson, onPick, onClose }: { events: any[]; showPerson: boolean; onPick: (id: number) => void; onClose: () => void }) {
  if (events.length > 1) return (
    <div className="card signin-detail" role="region" aria-label="Sign-ins at this place">
      <div className="row" style={{ justifyContent: "space-between" }}><strong>{events.length} sign-ins at this place</strong><button className="btn small ghost" onClick={onClose} aria-label="Close details">✕</button></div>
      <ul className="plain">{events.map((e) => <li key={e.id}><button className="link-btn" onClick={() => onPick(e.id)}>{formatDateTime(e.at)} · {e.user} · {e.ip || "—"}</button></li>)}</ul>
    </div>
  );
  const e = events[0];
  return (
    <div className="card signin-detail" role="region" aria-label="Sign-in details" data-detail={e.id}>
      <div className="row" style={{ justifyContent: "space-between" }}><strong>Sign-in details</strong><button className="btn small ghost" onClick={onClose} aria-label="Close details">✕</button></div>
      <dl className="dest-facts small">
        {showPerson && <><dt>Person</dt><dd>{e.user}</dd></>}
        <dt>When</dt><dd>{formatDateTime(e.at)} · {e.result === "success" ? e.method : `${e.result} (${e.method || "—"})`}</dd>
        <dt>IP address</dt><dd><code>{e.ip || "—"}</code></dd>
        <dt>Location</dt><dd>{e.location || "—"}{e.lat == null ? " · Location unavailable on the map" : e.coord_label ? ` · ${e.coord_label}` : ""}</dd>
        <dt>Network</dt><dd>{e.network === "trusted_zone" ? `${e.zone} (Trusted Zone)` : e.network === "private" ? "Private network" : e.network === "public" ? "Public network" : "Unknown"}</dd>
        <dt>Device</dt><dd>{[e.browser, e.os, e.device_type].filter(Boolean).join(" · ") || "—"}{e.new_device ? " · new device" : ""}</dd>
        <dt>Device state</dt><dd>{e.device_state === "unrecognized" ? <span className="badge danger">Unrecognized</span> : e.device_state === "recognized" ? "Recognised" : "Unknown"}</dd>
        <dt>Risk</dt><dd>{e.risk && RISK[e.risk] ? <span className={`badge ${RISK[e.risk][1]}`}>{RISK[e.risk][0]}</span> : "—"}{e.risk_reasons?.length ? ` · ${e.risk_reasons.join("; ")}` : ""}</dd>
      </dl>
    </div>
  );
}

/** Settings → Activity & health → Sign-in map & Trusted Zones (main administrator). */
export function SigninAdmin() {
  return (
    <div className="stack">
      <TrustedZones />
      <SigninSecurity adminView />
    </div>
  );
}

function TrustedZones() {
  const toast = useToast();
  const z = useAsync<any>(() => api("security/zones"), []);
  const [edit, setEdit] = useState<any | null>(null);
  const [probe, setProbe] = useState("");
  const [probeRes, setProbeRes] = useState<any>(null);
  return (
    <section className="card">
      <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>Trusted Zones</h2><button className="btn primary" onClick={() => setEdit({ name: "", cidrs: "", classification: "home", description: "", pin: null })}>Add zone</button></div>
      <p className="small muted">Name your own networks (Home, VPN, Office) so sign-ins from them show “Home” instead of an unknown country. A zone can hold several IPv4 and IPv6 networks. The optional map pin is shown as a configured location, never as GeoIP. Being inside a zone is one risk signal, not proof that a sign-in is safe. <a href="/help/security-map#trusted-zones">Learn more</a></p>
      {z.data && <div className="table-wrap"><table className="table"><thead><tr><th>Zone</th><th>Networks</th><th>Map pin</th><th /></tr></thead>
        <tbody>{z.data.zones.map((x: any) => <tr key={x.id}><td><strong>{x.name}</strong><div className="small muted">{x.classification_label}{x.description ? ` · ${x.description}` : ""}</div></td>
          <td className="small">{x.cidrs.map((c: string) => <code key={c} style={{ display: "block" }}>{c}</code>)}</td>
          <td className="small">{x.pin ? `${x.pin.lat}, ${x.pin.lon}` : "—"}</td><td><button className="btn small" onClick={() => setEdit({ ...x, cidrs: x.cidrs.join("\n") })}>Edit</button></td></tr>)}</tbody></table></div>}
      <form className="row" style={{ gap: 8, flexWrap: "wrap", marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); api("security/zones/test", { body: { ip: probe } }).then(setProbeRes).catch((er) => toast(er.message, "error")); }}>
        <label htmlFor="zone-probe" className="small">Test an address</label><input id="zone-probe" value={probe} onChange={(e) => setProbe(e.target.value)} placeholder="192.168.2.10" style={{ maxWidth: 200 }} /><button className="btn small">Test</button>
        {probeRes && <span className="small" role="status">{probeRes.location} ({probeRes.network.replace("_", " ")})</span>}
      </form>
      {edit && <ZoneDialog zone={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); z.reload(); }} />}
    </section>
  );
}

function ZoneDialog({ zone, onClose, onSaved }: { zone: any; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState({ ...zone, lat: zone.pin?.lat ?? "", lon: zone.pin?.lon ?? "" });
  const [err, setErr] = useState("");
  const save = () => {
    const body = { name: v.name, cidrs: v.cidrs, classification: v.classification, description: v.description, pin: v.lat !== "" && v.lon !== "" ? { lat: v.lat, lon: v.lon, label: v.name } : null };
    (zone.id ? api(`security/zones/${zone.id}`, { method: "PUT", body }) : api("security/zones", { body })).then(onSaved).catch((e) => setErr(e.message));
  };
  return (
    <Modal title={zone.id ? `Edit “${zone.name}”` : "Add Trusted Zone"} onClose={onClose}>
      <div className="stack">
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="field"><label htmlFor="z-name">Friendly name</label><input id="z-name" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} placeholder="Home" /></div>
        <div className="field"><label htmlFor="z-cidrs">Networks (one per line, CIDR)</label><textarea id="z-cidrs" rows={4} value={v.cidrs} onChange={(e) => setV({ ...v, cidrs: e.target.value })} placeholder={"192.168.2.0/24\nfd00:1::/64"} /></div>
        <div className="field"><label htmlFor="z-class">Type</label><select id="z-class" value={v.classification} onChange={(e) => setV({ ...v, classification: e.target.value })}><option value="home">Home</option><option value="vpn">VPN</option><option value="office">Office</option><option value="family">Family</option><option value="other">Other</option></select></div>
        <div className="field"><label htmlFor="z-desc">Description (optional)</label><input id="z-desc" value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} /></div>
        <fieldset className="field"><legend>Map pin (optional) <HelpTip text="Decimal degrees, e.g. from a map app. Shown as 'configured Trusted Zone location'. Use an approximate point; it does not need to be your exact address." /></legend>
          <div className="row" style={{ gap: 8 }}><input aria-label="Latitude" placeholder="Latitude" value={v.lat} onChange={(e) => setV({ ...v, lat: e.target.value })} /><input aria-label="Longitude" placeholder="Longitude" value={v.lon} onChange={(e) => setV({ ...v, lon: e.target.value })} /></div></fieldset>
        <div className="row" style={{ justifyContent: "space-between" }}>
          {zone.id ? <button className="btn danger" onClick={() => api(`security/zones/${zone.id}`, { method: "DELETE" }).then(onSaved)}>Delete</button> : <span />}
          <div className="row"><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save}>Save</button></div>
        </div>
      </div>
    </Modal>
  );
}
