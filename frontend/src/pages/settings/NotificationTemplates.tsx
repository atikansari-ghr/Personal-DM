import { useEffect, useMemo, useState } from "react";
import { api, formatDateTime } from "../../api";
import NotificationCard, { CATEGORY_LABEL, SEVERITY_LABEL } from "../../components/NotificationCard";
import { HelpTip, Icon, Modal, Skeleton, useAsync, useToast } from "../../components/ui";

/** Settings → Notifications → Templates: safe presentation overrides per event and channel, previews for every
 *  channel with sanitised sample data, and clearly marked TEST messages. Critical status and severity floors come
 *  from the security policy and cannot be weakened here. */

const CH_LABEL: Record<string, string> = { "": "All channels", in_app: "In-app", email: "Email", telegram: "Telegram", push: "Push" };

function Preview({ data, tab, setTab }: { data: any; tab: string; setTab: (t: string) => void }) {
  return (
    <div className="stack">
      <div className="tabs sub" role="tablist" aria-label="Preview channel">
        {[["email", "Email (desktop)"], ["email-mobile", "Email (mobile)"], ["telegram", "Telegram"], ["in_app", "In-app"], ["push", "Push"], ["text", "Plain text"]].map(([k, l]) =>
          <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {(tab === "email" || tab === "email-mobile") && (
        <div className="preview-frame-wrap"><p className="small"><strong>Subject:</strong> {data.email.subject}</p>
          <iframe title="Email preview" sandbox="" srcDoc={data.email.html} className={`email-preview ${tab === "email-mobile" ? "mobile" : ""}`} /></div>
      )}
      {tab === "text" && <pre className="preview-text small">{data.email.text}</pre>}
      {tab === "telegram" && (
        <div className="tg-preview">
          <div className="tg-bubble" dangerouslySetInnerHTML={{ __html: tgSafe(data.telegram.text) }} />
          {data.telegram.reply_markup ? (
            <div className="tg-buttons">{data.telegram.reply_markup.inline_keyboard.map((row: any[], i: number) => <div key={i} className="row">{row.map((b) => <span key={b.text} className="tg-button">{b.text}</span>)}</div>)}</div>
          ) : <p className="small muted">Buttons appear when the app has an https:// address; until then the links are part of the text.</p>}
        </div>
      )}
      {tab === "in_app" && <NotificationCard n={{ ...data.in_app, icon: data.in_app.icon, read: false }} preview />}
      {tab === "push" && (
        <div className="push-preview" aria-label="Push notification preview">
          <div className="small muted">Personal Documents · now</div><strong>{data.push.title}</strong><div>{data.push.body}</div>
        </div>
      )}
      <p className="small muted">{data.note}</p>
    </div>
  );
}

/** Telegram's HTML subset rendered for the preview: everything is already escaped by the server; only <b>, <i>,
 *  <a> and line breaks are kept (links are inert in the preview). */
function tgSafe(html: string) {
  return html.replace(/<a href="[^"]*">/g, "<u>").replace(/<\/a>/g, "</u>").replace(/<(?!\/?(b|i|u)>)[^>]*>/g, "").replace(/\n/g, "<br>");
}

function Editor({ ev, meta, onClose, onSaved }: { ev: any; meta: any; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [channel, setChannel] = useState("");
  const current = ev.overrides.find((o: any) => o.channel === channel) || {};
  const [f, setF] = useState<any>({});
  const [preview, setPreview] = useState<any>(null);
  const [tab, setTab] = useState("email");
  const [err, setErr] = useState("");
  const [testCh, setTestCh] = useState<string[]>(["in_app"]);
  useEffect(() => { setF({ title: current.title || "", heading: current.heading || "", summary: current.summary || "", icon: current.icon || "", severity: current.severity || "", action_labels: current.action_labels || {} }); }, [channel, ev.key]);
  useEffect(() => {
    const t = setTimeout(() => api<any>(`notifications/templates/${ev.key}/preview`, { body: { draft: { ...f, channel } } }).then((r) => { setPreview(r); setErr(""); }).catch((e) => setErr(e.message)), 300);
    return () => clearTimeout(t);
  }, [JSON.stringify(f), channel]);
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const sevChoices = meta.severities.filter((s: any) => !ev.critical || ["warning", "critical"].includes(s.key));
  return (
    <Modal title={`Template — ${ev.label}`} onClose={onClose} wide>
      <div className="tmpl-editor">
        <form className="stack" onSubmit={async (e) => { e.preventDefault(); try { await api(`notifications/templates/${ev.key}`, { method: "PUT", body: { ...f, channel } }); toast("Template saved"); onSaved(); } catch (x: any) { setErr(x.message); } }}>
          {ev.critical && <div className="alert small"><Icon name="lock" size={14} /> Critical notification: people cannot turn it off and it is never shown below Warning. Wording, icon and labels can change.</div>}
          {err && <div className="alert error" role="alert">{err}</div>}
          <div className="field"><label htmlFor="t-ch">Applies to</label><select id="t-ch" value={channel} onChange={(e) => setChannel(e.target.value)}>{["", ...meta.channels].map((c: string) => <option key={c} value={c}>{CH_LABEL[c]}</option>)}</select></div>
          <div className="field"><label htmlFor="t-title">Title / subject <HelpTip text="Leave empty to keep the system wording. Placeholders like {document_type} are filled with real values; names are masked outside the app." /></label><input id="t-title" type="text" value={f.title || ""} onChange={(e) => set("title", e.target.value)} placeholder="System default" /></div>
          <div className="field"><label htmlFor="t-head">Heading</label><input id="t-head" type="text" value={f.heading || ""} onChange={(e) => set("heading", e.target.value)} placeholder="System default" /></div>
          <div className="field"><label htmlFor="t-sum">Summary</label><textarea id="t-sum" rows={2} value={f.summary || ""} onChange={(e) => set("summary", e.target.value)} placeholder="System default" /></div>
          <div className="grid two">
            <div className="field"><label htmlFor="t-icon">Icon</label><select id="t-icon" value={f.icon || ""} onChange={(e) => set("icon", e.target.value)}><option value="">Default</option>{meta.icons.map((i: any) => <option key={i.key} value={i.key}>{i.emoji} {i.label}</option>)}</select></div>
            <div className="field"><label htmlFor="t-sev">Severity shown</label><select id="t-sev" value={f.severity || ""} onChange={(e) => set("severity", e.target.value)}><option value="">Default ({SEVERITY_LABEL[ev.severity]})</option>{sevChoices.map((s: any) => <option key={s.key} value={s.key}>{s.label}</option>)}</select></div>
          </div>
          {ev.actions.length > 0 && <fieldset className="field"><legend>Action labels</legend>{ev.actions.map((a: any) => (
            <div key={a.key} className="row"><label htmlFor={`al-${a.key}`} className="small" style={{ minWidth: 150 }}>{a.label}{a.in_app_only ? " (in-app)" : ""}</label>
              <input id={`al-${a.key}`} type="text" maxLength={40} value={f.action_labels?.[a.key] || ""} placeholder={a.label} onChange={(e) => set("action_labels", { ...f.action_labels, [a.key]: e.target.value })} style={{ maxWidth: 220 }} /></div>))}</fieldset>}
          <details className="small"><summary>Placeholders</summary><ul className="ph-list">{Object.entries(meta.placeholders).map(([k, l]) => <li key={k}><code>{`{${k}}`}</code> — {String(l)}</li>)}</ul></details>
          <div className="row">
            <button className="btn primary">Save</button>
            <button type="button" className="btn" onClick={async () => { await api(`notifications/templates/${ev.key}?channel=${channel}`, { method: "DELETE" }); toast("Reset to the system default"); onSaved(); }}>Reset to default</button>
          </div>
          <fieldset className="field"><legend>Send a TEST message to yourself</legend>
            <div className="row">{["in_app", "email", "telegram", "push"].map((c) => <label key={c} className="check small"><input type="checkbox" checked={testCh.includes(c)} onChange={(e) => setTestCh(e.target.checked ? [...testCh, c] : testCh.filter((x) => x !== c))} /> {CH_LABEL[c]}</label>)}</div>
            <button type="button" className="btn small" disabled={!testCh.length} onClick={async () => {
              try { const r = await api<any>(`notifications/templates/${ev.key}/test`, { body: { channels: testCh } }); toast(Object.entries(r.results).map(([c, v]) => `${CH_LABEL[c]}: ${v}`).join(" · ")); }
              catch (x: any) { toast(x.message, "error"); }
            }}>Send TEST</button>
            <p className="small muted">TEST messages use sample data, are marked TEST and create no real event. Saved changes apply to the TEST message.</p>
          </fieldset>
        </form>
        <div>{preview ? <Preview data={preview} tab={tab} setTab={setTab} /> : <Skeleton />}</div>
      </div>
    </Modal>
  );
}

export function NotificationTemplates() {
  const { data, reload } = useAsync(() => api<any>("notifications/templates"), []);
  const [open, setOpen] = useState<string | null>(null);
  const [cat, setCat] = useState("");
  const events = useMemo(() => (data?.events || []).filter((e: any) => !cat || e.category === cat), [data, cat]);
  if (!data) return <div className="card"><Skeleton /></div>;
  const ev = data.events.find((e: any) => e.key === open);
  return (
    <section className="card" id="templates" aria-labelledby="tmpl-h">
      <div className="row between"><h2 id="tmpl-h">Templates <HelpTip text="Change wording, icon, severity shown and action labels per event and channel. No code or HTML is accepted." link="/help/notifications" /></h2>
        <select aria-label="Category" value={cat} onChange={(e) => setCat(e.target.value)} style={{ maxWidth: 220 }}><option value="">All categories</option>{Object.entries(CATEGORY_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
      <div className="tmpl-list">
        {events.map((e: any) => (
          <button key={e.key} type="button" className="tmpl-row" onClick={() => setOpen(e.key)} aria-label={`Edit template ${e.label}`}>
            <span className={`sev-badge sev-${e.severity}`}>{SEVERITY_LABEL[e.severity]}</span>
            <span className="grow"><strong>{e.label}</strong> <span className="small muted">{CATEGORY_LABEL[e.category]}</span>
              {e.critical && <span className="badge neutral" style={{ marginLeft: ".3rem" }}><Icon name="lock" size={12} /> critical</span>}
              {e.overrides.length > 0 && <span className="badge ok" style={{ marginLeft: ".3rem" }}>customised</span>}</span>
            <Icon name="right" size={16} />
          </button>
        ))}
      </div>
      {ev && <Editor ev={ev} meta={data} onClose={() => setOpen(null)} onSaved={() => { reload(); }} />}
    </section>
  );
}

export function DeliveryHistory() {
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const { data, reload } = useAsync(() => api<{ deliveries: any[] }>("notifications/deliveries", { query: { ...(channel ? { channel } : {}), ...(status ? { status } : {}) } }), [channel, status]);
  return (
    <section className="card" aria-labelledby="dh-h">
      <div className="row between"><h2 id="dh-h">Delivery history</h2>
        <div className="row">
          <select aria-label="Channel" value={channel} onChange={(e) => setChannel(e.target.value)}><option value="">All channels</option>{["email", "telegram", "push"].map((c) => <option key={c} value={c}>{CH_LABEL[c]}</option>)}</select>
          <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All states</option><option value="pending">Queued / retrying</option><option value="sent">Sent</option><option value="failed">Failed</option><option value="skipped">Skipped</option></select>
          <button className="btn small" onClick={reload}><Icon name="refresh" size={14} /> Refresh</button>
        </div></div>
      <p className="small muted">Sent means the provider accepted the message; actual delivery is shown only when the provider reports it. Errors are shown without credentials.</p>
      {!data ? <Skeleton /> : data.deliveries.length === 0 ? <p className="muted">No external deliveries yet.</p> : (
        <div className="table-scroll"><table className="responsive delivery-table"><thead><tr><th>When</th><th>Event</th><th>Recipient</th><th>Channel</th><th>State</th></tr></thead><tbody>
          {data.deliveries.slice(0, 100).map((d) => (
            <tr key={d.id}>
              <td data-label="When" className="small">{formatDateTime(d.created_at)}{d.sent_at && <div className="muted">sent {formatDateTime(d.sent_at)}</div>}</td>
              <td data-label="Event"><span dir="auto">{d.event_label}</span>{d.test && <span className="badge neutral" style={{ marginLeft: ".3rem" }}>TEST</span>}</td>
              <td data-label="Recipient">{d.user}</td>
              <td data-label="Channel">{CH_LABEL[d.channel] || d.channel}</td>
              <td data-label="State"><span className={`badge ${d.status === "sent" ? "ok" : d.status === "failed" ? "danger" : d.state === "retrying" ? "soon" : "neutral"}`}>{d.state}</span>
                {d.attempts > 1 && <span className="small muted"> {d.attempts} attempts</span>}
                {d.next_attempt_at && <div className="small muted">next try {formatDateTime(d.next_attempt_at)}</div>}
                {d.delivered && <div className="small muted">{d.delivered}</div>}
                {d.error && <div className="small error-text">{d.error}</div>}</td>
            </tr>
          ))}
        </tbody></table></div>
      )}
    </section>
  );
}
