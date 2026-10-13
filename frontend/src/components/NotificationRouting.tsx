import { useEffect, useState } from "react";
import { api, formatDateTime } from "../api";
import { HelpTip, Icon, Skeleton, useAsync, useToast } from "./ui";

// My account → Notifications: routing per category (channels, fallback chain, digest), quiet hours, Discord,
// WhatsApp Personal (experimental) and my delivery status. Labels match docs/guides/notifications.md.

const LABEL: Record<string, string> = { in_app: "In-app", email: "Email", telegram: "Telegram", push: "Push", discord: "Discord", whatsapp: "WhatsApp Personal" };
const EXTERNAL = ["whatsapp", "telegram", "discord", "push", "email"];

export function NotificationRouting({ data, reload }: { data: any; reload: () => void }) {
  const toast = useToast();
  const [quiet, setQuiet] = useState(data.quiet_hours || { enabled: false, start: "22:00", end: "07:00" });
  const [tz, setTz] = useState(data.timezone || "");
  const [digestTime, setDigestTime] = useState(data.digest_time || "08:00");
  const put = (body: any, msg = "Saved") => api("notifications/routing", { method: "PUT", body }).then(() => { toast(msg); reload(); }).catch((e) => toast(e.message, "error"));
  const configured = new Set<string>((data.channels || []).filter((c: any) => c.configured).map((c: any) => c.channel));
  // channels the administrator set up but that cannot reach me (not linked, disconnected, no address…)
  const issues: Record<string, string> = Object.fromEntries((data.channels || []).filter((c: any) => c.configured && c.issue).map((c: any) => [c.channel, c.issue]));
  return (
    <>
      <div className="card" id="routing">
        <h2>Routing by category <HelpTip text="Set the channels of a whole category at once, a fallback chain (the first channel that works is used; the next one only if it fails), and whether normal messages arrive immediately or in a daily/weekly digest. Critical security and backup alerts always arrive immediately." link="/help/notifications#routing" /></h2>
        <div className="table-scroll"><table className="matrix routing">
          <thead><tr><th scope="col">Category</th><th scope="col">Channels</th><th scope="col">Fallback chain</th><th scope="col">Delivery</th></tr></thead>
          <tbody>{data.categories.map((c: any) => <RoutingRow key={c.key} cat={c} events={data.events.filter((e: any) => e.category === c.key)} configured={configured} issues={issues} put={put} />)}</tbody>
        </table></div>
        <p className="small muted">In-app always shows every notification. A channel the administrator requires is always used on its own, whatever the chain.</p>
      </div>
      <div className="card" id="quiet-hours">
        <h2>Quiet hours</h2>
        <p className="small muted">Normal notifications to external channels wait until the quiet period ends. Critical security, account-compromise and backup alerts are never held.</p>
        <div className="row" style={{ gap: 12, flexWrap: "wrap", alignItems: "end" }}>
          <label className="check"><input type="checkbox" checked={!!quiet.enabled} onChange={(e) => setQuiet({ ...quiet, enabled: e.target.checked })} /> Quiet hours on</label>
          <div className="field"><label htmlFor="qh-start">From</label><input id="qh-start" type="time" value={quiet.start} onChange={(e) => setQuiet({ ...quiet, start: e.target.value })} /></div>
          <div className="field"><label htmlFor="qh-end">Until</label><input id="qh-end" type="time" value={quiet.end} onChange={(e) => setQuiet({ ...quiet, end: e.target.value })} /></div>
          <div className="field"><label htmlFor="qh-tz">My timezone</label><input id="qh-tz" value={tz} placeholder={data.installation_timezone} onChange={(e) => setTz(e.target.value)} /></div>
          <div className="field"><label htmlFor="dg-time">Digest time</label><input id="dg-time" type="time" value={digestTime} onChange={(e) => setDigestTime(e.target.value)} /></div>
          <button className="btn primary" onClick={() => put({ quiet_hours: quiet, timezone: tz, digest_time: digestTime })}>Save</button>
        </div>
      </div>
    </>
  );
}

function RoutingRow({ cat, events, configured, issues, put }: { cat: any; events: any[]; configured: Set<string>; issues: Record<string, string>; put: (b: any, m?: string) => void }) {
  const [chain, setChain] = useState<string[]>(cat.fallback || []);
  const optional = events.filter((e) => !e.critical);
  const on = (ch: string) => optional.length > 0 && optional.every((e) => e.channels.includes(ch));
  const some = (ch: string) => optional.some((e) => e.channels.includes(ch));
  const setChannel = (ch: string, value: boolean) => {
    const current = ["in_app", ...EXTERNAL].filter((c) => (c === ch ? value : on(c)));
    put({ category_channels: { category: cat.key, channels: Array.from(new Set(["in_app", ...current])) } }, `${cat.label}: ${LABEL[ch]} ${value ? "on" : "off"}`);
  };
  const saveChain = (next: string[]) => { setChain(next); put({ routing: { [cat.key]: { fallback: next, digest: cat.digest } } }, `${cat.label}: fallback saved`); };
  return (
    <tr>
      <th scope="row">{cat.label}<div className="small muted" style={{ fontWeight: 400 }}>{events.length} event(s){events.some((e) => e.critical) ? " · some critical" : ""}</div></th>
      <td data-label="Channels"><div className="chip-row">{EXTERNAL.map((ch) => (
        <label key={ch} className={`chip ${configured.has(ch) ? "" : "disabled"}`} title={configured.has(ch) ? "" : `${LABEL[ch]} is not set up by the administrator`}>
          <input type="checkbox" checked={on(ch)} ref={(el) => { if (el) el.indeterminate = !on(ch) && some(ch); }} disabled={!configured.has(ch) || !optional.length}
            onChange={(e) => setChannel(ch, e.target.checked)} aria-label={`${cat.label} by ${LABEL[ch]}`} /> {LABEL[ch]}</label>))}</div>
        {EXTERNAL.filter((ch) => some(ch) && issues[ch]).map((ch) => <div key={ch} className="small warn-text route-issue">{LABEL[ch]}: {issues[ch]} — your fallback chain is used meanwhile.</div>)}</td>
      <td data-label="Fallback chain">
        <ol className="chain">{chain.map((ch, i) => <li key={ch}>{LABEL[ch]}
          <button type="button" className="icon-btn" aria-label={`Move ${LABEL[ch]} up`} disabled={i === 0} onClick={() => { const n = [...chain]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; saveChain(n); }}><Icon name="left" size={14} /></button>
          <button type="button" className="icon-btn" aria-label={`Remove ${LABEL[ch]} from the chain`} onClick={() => saveChain(chain.filter((c) => c !== ch))}><Icon name="x" size={14} /></button></li>)}</ol>
        <select aria-label={`Add a channel to the ${cat.label} fallback chain`} value="" onChange={(e) => e.target.value && saveChain([...chain, e.target.value])}>
          <option value="">{chain.length ? "Then…" : "Add chain…"}</option>{EXTERNAL.filter((c) => !chain.includes(c) && configured.has(c)).map((c) => <option key={c} value={c}>{LABEL[c]}</option>)}</select>
      </td>
      <td data-label="Delivery"><select aria-label={`${cat.label} delivery`} value={cat.digest} onChange={(e) => put({ routing: { [cat.key]: { fallback: chain, digest: e.target.value } } }, `${cat.label}: delivery saved`)}>
        <option value="immediate">Immediately</option><option value="daily">Daily digest</option><option value="weekly">Weekly digest</option></select></td>
    </tr>
  );
}

export function DiscordCard() {
  const toast = useToast();
  const d = useAsync<any>(() => api("notifications/discord"), []);
  const [url, setUrl] = useState("");
  if (!d.data) return null;
  const w = d.data.webhook;
  if (!d.data.available && !w) return (
    <div className="card" id="discord" data-state="disabled">
      <h2>Discord <span className="badge neutral">Disabled by Admin</span></h2>
      <p className="small muted">Discord delivery is available once the main administrator turns it on in Settings → Connections. <a href="/help/discord">Learn more</a></p>
    </div>
  );
  return (
    <div className="card" id="discord" data-state={w ? w.status : "not_configured"}>
      <h2>Discord {!d.data.available && <span className="badge neutral">Disabled by Admin</span>}</h2>
      <p className="small muted">Uses an official Discord webhook for one channel you control. The address is stored encrypted and never shown again. <a href="/help/discord#setup">How to create a webhook</a></p>
      {w ? (
        <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <span className={`badge ${w.status === "connected" ? "ok" : w.status === "untested" ? "neutral" : "danger"}`}>{({ connected: "Connected", untested: "Not tested yet", failed: "Failed", removed_by_discord: "Deleted in Discord" } as any)[w.status] || w.status}</span>
          <code className="small">{w.hint}</code>{w.error && <span className="small muted">{w.error}</span>}
          {(w.last_tested_at || w.last_delivery_at) && <span className="small muted">{w.last_tested_at && `Last test ${formatDateTime(w.last_tested_at)}`}{w.last_tested_at && w.last_delivery_at && " · "}{w.last_delivery_at && `last delivery ${formatDateTime(w.last_delivery_at)}`}</span>}
          <label className="check"><input type="checkbox" checked={w.enabled} onChange={(e) => api("notifications/discord", { method: "PUT", body: { enabled: e.target.checked } }).then(d.reload)} /> Enabled</label>
          <button className="btn small" onClick={() => api("notifications/channel-test", { body: { channel: "discord" } }).then(() => { toast("Test sent to Discord"); d.reload(); }).catch((e) => toast(e.message, "error"))}>Send test</button>
          <button className="btn small danger" onClick={() => api("notifications/discord", { method: "DELETE" }).then(d.reload)}>Remove</button>
        </div>
      ) : (
        <form className="row" style={{ gap: 8, flexWrap: "wrap" }} onSubmit={(e) => { e.preventDefault(); api("notifications/discord", { method: "PUT", body: { url } }).then(() => { setUrl(""); toast("Webhook saved"); d.reload(); }).catch((er) => toast(er.message, "error")); }}>
          <label htmlFor="dc-url" className="sr-only">Discord webhook address</label>
          <input id="dc-url" type="password" autoComplete="off" placeholder="https://discord.com/api/webhooks/…" value={url} onChange={(e) => setUrl(e.target.value)} style={{ flex: 1, minWidth: 240 }} />
          <button className="btn primary" disabled={!url}>Save webhook</button>
        </form>
      )}
      <p className="small muted">Then choose Discord per category in Routing by category.</p>
    </div>
  );
}

const WA_STAGE_LABEL: Record<string, string> = { qr_ready: "QR Ready", scanned: "Scanned", connecting: "Connecting", authenticating: "Authenticating",
  saving_session: "Saving Session", sending_verification: "Sending Verification" };
const WA_BADGE: Record<string, string> = { verified: "ok", verify_pending: "neutral", verify_failed: "warn", disconnected: "warn",
  reconnect_required: "danger", pairing_failed: "danger", link_expired: "neutral", incompatible: "danger", degraded: "warn", not_linked: "neutral" };
const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

/** WhatsApp Personal (Change Set V): live pairing progress from the bridge's real state, a 5-minute link window with
 *  a countdown, truthful Linked & Verified / Verification Pending / Test Failed states, Reconnect and Relink. */
export function WhatsAppCard() {
  const toast = useToast();
  const w = useAsync<any>(() => api("notifications/whatsapp"), []);
  const [busy, setBusy] = useState(false);
  const [left, setLeft] = useState<number | null>(null);
  const linking = w.data?.state === "pending";
  useEffect(() => { // follow the pairing live; slower polling while waiting for the scan
    if (!linking) return;
    const t = window.setInterval(() => w.reload(), w.data?.stage === "qr_ready" ? 4000 : 2000);
    return () => window.clearInterval(t);
  }, [linking, w.data?.stage]);
  useEffect(() => { // the countdown runs locally between polls
    if (w.data?.link_expires_in_s == null) { setLeft(null); return; }
    setLeft(w.data.link_expires_in_s);
    const t = window.setInterval(() => setLeft((x) => (x == null ? x : Math.max(0, x - 1))), 1000);
    return () => window.clearInterval(t);
  }, [w.data?.link_expires_in_s]);
  if (!w.data) return null;
  const act = (body: any, method = "POST") => { setBusy(true); return api("notifications/whatsapp", { method, body }).then(w.reload).catch((e) => toast(e.message, "error")).finally(() => setBusy(false)); };
  const test = () => { setBusy(true); api("notifications/channel-test", { body: { channel: "whatsapp" } }).then(() => { toast("Test notification sent to your own WhatsApp chat"); w.reload(); })
    .catch((e) => { toast(e.message, "error"); w.reload(); }).finally(() => setBusy(false)); };
  const s = w.data;
  const svcDown = s.available && s.service && !["healthy", "degraded"].includes(s.service.state);
  if (!s.available && s.state === "not_linked") return (
    <div className="card" id="whatsapp" data-state="disabled">
      <h2>WhatsApp Personal <span className="badge-group"><span className="badge neutral">Disabled by Admin</span></span></h2>
      <p className="small muted">WhatsApp Personal (experimental, unofficial, self-hosted) is available once the main administrator installs the bridge and turns it on in Settings → Connections. <a href="/help/whatsapp-personal">Learn more</a></p>
    </div>
  );
  const key = s.key || s.state;
  const stageIdx = linking ? Math.max(0, (s.stages || []).indexOf(s.stage)) : -1;
  return (
    <div className="card" id="whatsapp" data-state={svcDown ? "service_unavailable" : s.state} data-key={key} data-stage={s.stage || ""}>
      <h2>WhatsApp Personal <span className="badge-group">{!s.available && <span className="badge neutral">Disabled by Admin</span>}<span className="badge warn">Experimental</span><span className="badge neutral">Unofficial</span><span className="badge neutral">Self-hosted</span></span></h2>
      <div className="callout experimental">Links your own WhatsApp account as a linked device and sends you your Personal DM notifications as messages to yourself. It is not the WhatsApp Business Platform, not supported or endorsed by WhatsApp or Meta, and WhatsApp may disconnect it at any time. It is notification-only: nothing here can read your chats or message anyone else. <a href="/help/whatsapp-personal">Learn more</a></div>
      {svcDown && <div className="alert warn small" role="status"><strong>Service unavailable.</strong> The WhatsApp bridge on the server is not responding ({s.service.label}). Your fallback channels are used meanwhile; the administrator can check it in Settings → Connections.</div>}
      <p role="status" aria-live="polite">Status: {linking ? <strong>Linking — {s.label}</strong> : <span className={`badge ${WA_BADGE[key] || "neutral"}`} data-wa-status={key}>{s.label || s.state}</span>}
        {s.number_hint && !linking && <span className="small muted"> · number ending {s.number_hint}</span>}
        {s.state === "disconnected" && s.next_retry_in_s != null && <span className="small muted"> · next attempt in {s.next_retry_in_s} s (no new QR code needed)</span>}
        {s.last_delivery_at && <span className="small muted"> · last notification {formatDateTime(s.last_delivery_at)}</span>}</p>
      {s.error && !linking && <p className="small warn-text">{s.error}</p>}
      {linking && (
        <ol className="wa-stages" aria-label="Pairing progress">
          {(s.stages || []).map((st: string, i: number) => <li key={st} className={i < stageIdx ? "done" : i === stageIdx ? "current" : ""} aria-current={i === stageIdx ? "step" : undefined}>{WA_STAGE_LABEL[st] || st}</li>)}
          <li className="">Linked &amp; Verified</li>
        </ol>
      )}
      {linking && s.stage === "qr_ready" && s.qr_svg && (
        <div className="qr-box"><div className="qr" aria-label="QR code for linking WhatsApp" role="img" dangerouslySetInnerHTML={{ __html: s.qr_svg }} />
          <div>
            <ol className="small"><li>Open WhatsApp on your phone → Settings → Linked devices → Link a device.</li><li>Scan this code. WhatsApp itself renews the picture every 20–30 seconds; keep this page open.</li><li>The steps above update by themselves after the scan — do not scan again while the phone shows Connecting.</li></ol>
            {left != null && <p className="small" data-countdown={left}><strong>Expires in {mmss(left)}</strong> (this link attempt stays valid for 5 minutes)</p>}
            <button className="btn" disabled={busy} onClick={w.reload}>Check now</button>
          </div></div>
      )}
      {linking && s.stage && s.stage !== "qr_ready" && <p className="small muted">Your phone accepted the code. Keep WhatsApp open on the phone until this card shows <strong>Linked &amp; Verified</strong>.</p>}
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        {(s.state === "not_linked") && <button className="btn primary" disabled={busy || !s.available} onClick={() => act({ action: "link" })}>Link WhatsApp</button>}
        {["link_expired", "pairing_failed", "reconnect_required", "incompatible"].includes(s.state) && s.can_new_qr && <button className="btn primary" disabled={busy || !s.available} onClick={() => act({ action: "link", new_qr: true })}>{s.state === "reconnect_required" ? "Relink (new QR code)" : "Generate new QR code"}</button>}
        {s.state === "connected" && <button className="btn" disabled={busy} onClick={test}>Send Test Notification</button>}
        {(s.state === "connected" || s.state === "disconnected" || s.state === "degraded") && <button className="btn" disabled={busy} onClick={() => act({ action: "reconnect" })}>Reconnect</button>}
        {s.state !== "not_linked" && <button className="btn danger" disabled={busy} onClick={() => act({}, "DELETE")}>Unlink</button>}
      </div>
      {s.state === "pairing_failed" && <p className="small muted">Pairing stopped at <strong>{WA_STAGE_LABEL[s.failure_stage] || s.failure_stage || "an early step"}</strong>. You can generate a new QR code at once. If it keeps failing, ask the administrator to run the WhatsApp diagnostics. <a href="/help/whatsapp-personal#troubleshooting">Troubleshooting</a></p>}
    </div>
  );
}

export function MyDeliveries() {
  const d = useAsync<any>(() => api("notifications/my-deliveries"), []);
  if (!d.data) return <Skeleton lines={2} />;
  const rows = d.data.deliveries.slice(0, 50);
  return (
    <div className="card" id="deliveries" style={{ marginTop: "1rem" }}>
      <h2>My delivery status</h2>
      <p className="small muted">What happened to each message on each channel. Not Selected channels are those you have not chosen for an event (see the matrix above).</p>
      {rows.length ? <div className="table-wrap"><table className="table">
        <thead><tr><th>When</th><th>Message</th><th>Channel</th><th>Status</th></tr></thead>
        <tbody>{rows.map((r: any) => <tr key={r.id}><td className="small">{formatDateTime(r.created_at)}</td><td>{r.subject}</td><td>{r.channel_label}{r.fallback_from && <div className="small muted">fallback after {LABEL[r.fallback_from]}</div>}</td>
          <td><span className={`badge ${({ sent: "ok", digested: "ok", failed: "danger", fallback: "warn", disconnected: "danger", retrying: "warn", held: "neutral", digest: "neutral", queued: "neutral" } as any)[r.status] || "neutral"}`}>{r.status_label}</span>{r.error && r.status !== "sent" && <div className="small muted">{r.error}</div>}</td></tr>)}</tbody></table></div>
        : <p className="muted">No messages to external channels yet.</p>}
    </div>
  );
}
