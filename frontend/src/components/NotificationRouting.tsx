import { useState } from "react";
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
  return (
    <>
      <div className="card" id="routing">
        <h2>Routing by category <HelpTip text="Set the channels of a whole category at once, a fallback chain (the first channel that works is used; the next one only if it fails), and whether normal messages arrive immediately or in a daily/weekly digest. Critical security and backup alerts always arrive immediately." link="/help/notifications#routing" /></h2>
        <div className="table-scroll"><table className="matrix routing">
          <thead><tr><th scope="col">Category</th><th scope="col">Channels</th><th scope="col">Fallback chain</th><th scope="col">Delivery</th></tr></thead>
          <tbody>{data.categories.map((c: any) => <RoutingRow key={c.key} cat={c} events={data.events.filter((e: any) => e.category === c.key)} configured={configured} put={put} />)}</tbody>
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

function RoutingRow({ cat, events, configured, put }: { cat: any; events: any[]; configured: Set<string>; put: (b: any, m?: string) => void }) {
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
            onChange={(e) => setChannel(ch, e.target.checked)} aria-label={`${cat.label} by ${LABEL[ch]}`} /> {LABEL[ch]}</label>))}</div></td>
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
  if (!d.data.available && !d.data.webhook) return null;
  const w = d.data.webhook;
  return (
    <div className="card" id="discord">
      <h2>Discord</h2>
      <p className="small muted">Uses an official Discord webhook for one channel you control. The address is stored encrypted and never shown again. <a href="/help/discord#setup">How to create a webhook</a></p>
      {w ? (
        <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <span className={`badge ${w.status === "connected" ? "ok" : w.status === "untested" ? "neutral" : "danger"}`}>{({ connected: "Connected", untested: "Not tested yet", failed: "Failed", removed_by_discord: "Deleted in Discord" } as any)[w.status] || w.status}</span>
          <code className="small">{w.hint}</code>{w.error && <span className="small muted">{w.error}</span>}
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

export function WhatsAppCard() {
  const toast = useToast();
  const w = useAsync<any>(() => api("notifications/whatsapp"), []);
  if (!w.data) return null;
  if (!w.data.available && !w.data.linked && w.data.state === "not_linked") return null;
  const act = (body: any, method = "POST") => api("notifications/whatsapp", { method, body }).then(w.reload).catch((e) => toast(e.message, "error"));
  const s = w.data;
  return (
    <div className="card" id="whatsapp">
      <h2>WhatsApp Personal <span className="badge-group"><span className="badge warn">Experimental</span><span className="badge neutral">Unofficial</span><span className="badge neutral">Self-hosted</span></span></h2>
      <div className="callout experimental">Links your own WhatsApp account as a linked device and sends you your Personal DM notifications as messages to yourself. It is not the WhatsApp Business Platform, not supported or endorsed by WhatsApp or Meta, and WhatsApp may disconnect it at any time. It is notification-only: nothing here can read your chats or message anyone else. <a href="/help/whatsapp-personal">Learn more</a></div>
      <p>Status: <strong>{s.label || s.state}</strong>{s.number_hint && <span className="small muted"> · number ending {s.number_hint}</span>}{s.error && <span className="small muted"> · {s.error}</span>}</p>
      {s.state === "pending" && s.qr_svg && (
        <div className="qr-box"><div className="qr" aria-label="QR code for linking WhatsApp" role="img" dangerouslySetInnerHTML={{ __html: s.qr_svg }} />
          <ol className="small"><li>Open WhatsApp on your phone → Settings → Linked devices → Link a device.</li><li>Scan this code within about a minute.</li><li>Press “I scanned it”.</li></ol>
          <button className="btn" onClick={w.reload}>I scanned it</button></div>
      )}
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        {(s.state === "not_linked" || s.state === "reconnect_required" || s.state === "disconnected") && <button className="btn primary" onClick={() => act({ action: "link" })}>{s.state === "not_linked" ? "Link WhatsApp" : "Link again (new QR)"}</button>}
        {s.state === "degraded" && <button className="btn" onClick={() => act({ action: "reconnect" })}>Reconnect</button>}
        {s.state === "connected" && <button className="btn" onClick={() => api("notifications/channel-test", { body: { channel: "whatsapp" } }).then(() => toast("Test sent")).catch((e) => toast(e.message, "error"))}>Send test</button>}
        {s.state !== "not_linked" && <button className="btn danger" onClick={() => act({}, "DELETE")}>Unlink</button>}
      </div>
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
