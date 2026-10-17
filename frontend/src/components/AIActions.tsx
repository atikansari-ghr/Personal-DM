import { useEffect, useState } from "react";
import { api, formatDateTime } from "../api";
import { useAiStatus } from "../ai";
import { HelpTip, Icon, Modal, useAsync, useToast } from "./ui";

/** Change Set Z: AI Actions, AI outputs and AI History of one document (Document Details). The server decides which
 *  actions this person may run (permissions, policy, the profile's capabilities); AI output is labelled and never
 *  changes the document, its OCR or confirmed metadata. */

const SOURCE_LABEL: Record<string, string> = { ocr: "OCR text", image: "Page image", file: "Original PDF" };
const SENT_LABEL: Record<string, string> = { ocr_text: "OCR text", metadata: "metadata", image: "page image", file: "original file" };

type Disclosure = { profile: string; provider: string; location: string; categories: string[]; category_labels: string[]; message: string };

export default function AIActions({ docId, onChange }: { docId: string; onChange: () => void }) {
  const ai = useAiStatus();
  const toast = useToast();
  // only asked when AI is switched on, so documents open without an extra request otherwise
  const data = useAsync(() => (ai?.enabled ? api<any>(`documents/${docId}/ai`) : Promise.resolve(null)), [docId, ai?.enabled]);
  const [source, setSource] = useState<Record<string, string>>({});
  const [profile, setProfile] = useState("");
  const [consent, setConsent] = useState<{ kind: string; source: string; d: Disclosure } | null>(null);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const active = (data.data?.history || []).some((h: any) => ["queued", "running"].includes(h.status));
  const [wasActive, setWasActive] = useState(false);
  useEffect(() => {  // while an action runs, look again every 5 s (only on this open document)
    if (!active) return;
    const t = window.setTimeout(data.reload, 5000);
    return () => window.clearTimeout(t);
  }, [active, data.data]);
  useEffect(() => {  // an action finished: the suggestions panel and the document may have something new to show
    if (wasActive && !active) { window.dispatchEvent(new CustomEvent("pd:ai-changed", { detail: docId })); onChange(); }
    setWasActive(active);
  }, [active]);
  if (!ai || !data.data) return null;
  const { actions, history, outputs } = data.data;
  if (!actions.length && !history.length && !outputs.length) return null;
  const run = async (kind: string, src: string, confirm = false) => {
    try {
      const r = await api<any>(`documents/${docId}/ai/action`, { body: { action: kind, source: src, confirm_cloud: confirm, ...(profile ? { profile: Number(profile) } : {}) } });
      toast(`${actions.find((a: any) => a.kind === kind)?.label || kind} queued — ${r.disclosure?.message || ""}`);
      setConsent(null);
      data.reload();
      window.dispatchEvent(new CustomEvent("pd:ai-changed", { detail: docId }));
    } catch (e: any) {
      if (e.data?.category === "consent" && e.data.disclosure) setConsent({ kind, source: src, d: e.data.disclosure });
      else toast(e.message, "error");
    }
  };
  const ask = async () => {
    if (!question.trim()) return;
    setAsking(true);
    try {
      await api<any>("ai/assistant", { body: { question, document: docId, ...(profile ? { profile: Number(profile) } : {}) } });
      setQuestion("");
      data.reload();
    } catch (e: any) { toast(e.message, "error"); } finally { setAsking(false); }
  };
  const remove = (id: number) => api(`documents/${docId}/ai/outputs/${id}`, { method: "DELETE" }).then(() => data.reload()).catch((e) => toast(e.message, "error"));
  const where = ai.profile ? (ai.profile.location === "cloud" ? "Cloud" : "Local") : "";
  return (
    <div className="card" data-ai-actions>
      <h3><Icon name="sparkle" size={18} /> AI Actions {where && <span className={`badge ${where === "Cloud" ? "danger" : "ok"}`} title={`Default AI profile: ${ai.profile?.name}`}>{where} · {ai.profile?.name}</span>}
        <HelpTip text="AI is optional and works on the OCR text. Its results are labelled AI-generated and are only applied when you accept them. Cloud profiles receive only the data categories the administrator allowed; original images or files need your confirmation each time." link="/help/local-ai#actions" /></h3>
      {ai.profile_choice && (ai.profiles?.length || 0) > 1 && (
        <div className="field"><label htmlFor="ai-profile-choice">AI profile</label>
          <select id="ai-profile-choice" value={profile} onChange={(e) => setProfile(e.target.value)}>
            <option value="">Use system default</option>
            {ai.profiles!.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.location === "cloud" ? "Cloud" : "Local"})</option>)}
          </select></div>
      )}
      {actions.length > 0 && (
        <div className="row" style={{ gap: ".35rem", flexWrap: "wrap" }}>
          {actions.filter((a: any) => a.kind !== "ask").map((a: any) => (
            <span key={a.kind} className="row" style={{ gap: ".2rem" }}>
              <button className="btn small" data-ai-action={a.kind} disabled={history.some((h: any) => h.kind === a.kind && ["queued", "running"].includes(h.status))}
                onClick={() => run(a.kind, source[a.kind] || "ocr")}>{a.label}</button>
              {a.sources.length > 1 && <select aria-label={`${a.label}: what the AI reads`} value={source[a.kind] || "ocr"} onChange={(e) => setSource({ ...source, [a.kind]: e.target.value })}>
                {a.sources.map((s: string) => <option key={s} value={s}>{SOURCE_LABEL[s]}</option>)}</select>}
            </span>
          ))}
        </div>
      )}
      {where === "Cloud" && <p className="small muted" data-cloud-notice>Uses the Cloud profile “{ai.profile?.name}”: it receives {ai.profile?.allowed.filter((c) => c !== "image" && c !== "file").map((c) => SENT_LABEL[c]).join(" and ") || "nothing"} of this document{ai.profile?.allowed.some((c) => c === "image" || c === "file") ? "; page images or files only after you confirm" : "; no original image or file"}.</p>}
      {actions.some((a: any) => a.kind === "ask") && (
        <form className="row" style={{ gap: ".35rem" }} onSubmit={(e) => { e.preventDefault(); ask(); }}>
          <input type="text" className="grow" aria-label="Ask AI about this document" placeholder="Ask AI about this document, e.g. When does it expire?" value={question} maxLength={1000} onChange={(e) => setQuestion(e.target.value)} />
          <button className="btn small primary" disabled={asking || !question.trim()}>{asking ? "Asking…" : "Ask AI"}</button>
        </form>
      )}
      {outputs.map((o: any) => <OutputCard key={o.id} o={o} onRemove={() => remove(o.id)} />)}
      {history.length > 0 && <button className="btn small ghost" aria-expanded={showHistory} onClick={() => setShowHistory(!showHistory)}>AI History ({history.length})</button>}
      {showHistory && (
        <div style={{ overflowX: "auto" }}>
          <table className="responsive" data-ai-history><thead><tr><th>Action</th><th>Profile</th><th>Sent</th><th>Status</th><th>When</th></tr></thead><tbody>
            {history.map((h: any) => (
              <tr key={h.id}><td>{h.action}{h.trigger && h.trigger !== "manual" && <div className="small muted">{h.trigger === "smart" ? "Smart Auto" : "OCR + AI"}</div>}<div className="small muted">{h.requested_by || ""}</div></td>
                <td className="small">{h.profile || "—"}{h.model ? ` · ${h.model}` : ""}{h.location && <div><span className={`badge ${h.location === "cloud" ? "danger" : "ok"}`}>{h.location === "cloud" ? "Cloud" : "Local"}</span></div>}</td>
                <td className="small">{(h.data_sent || []).map((c: string) => SENT_LABEL[c] || c).join(", ") || "nothing"}{h.usage?.input_tokens != null ? <div className="muted">{h.usage.input_tokens} in / {h.usage.output_tokens} out tokens</div> : null}</td>
                <td><span className={`badge ${["failed", "provider_unavailable", "timed_out"].includes(h.status_key) ? "danger" : h.status_key === "completed" ? "ok" : h.status_key === "needs_review" ? "soon" : "neutral"}`} data-status={h.status_key}>{h.status_label}</span>
                  {h.error && <div className="small muted">{h.error}</div>}</td>
                <td className="small">{formatDateTime(h.finished_at || h.created_at)}{h.duration_seconds != null ? ` · ${h.duration_seconds}s` : ""}</td></tr>
            ))}
          </tbody></table>
        </div>
      )}
      {consent && (
        <Modal title="Send the original to a Cloud AI?" onClose={() => setConsent(null)}>
          <div className="stack" data-cloud-disclosure>
            <div className="alert danger">{consent.d.message}</div>
            <ul className="small">
              <li>Profile: <strong>{consent.d.profile}</strong> ({consent.d.provider}, {consent.d.location})</li>
              <li>Data sent: {consent.d.category_labels.join(", ")}</li>
            </ul>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setConsent(null)}>Cancel</button>
              <button className="btn danger" onClick={() => run(consent.kind, consent.source, true)}>Send and run</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

function OutputCard({ o, onRemove }: { o: any; onRemove: () => void }) {
  const c = o.content || {};
  const title = { summary: "Summary", verify: "OCR verification", expiry: "Expiry / renewal", answer: "Ask AI" }[o.kind as string] || o.kind;
  return (
    <div className="ai-output" data-ai-output={o.kind} style={{ borderTop: "1px solid var(--border)", paddingTop: ".5rem" }}>
      <div className="row between"><strong>{title} <span className="badge neutral">AI-generated</span></strong>
        <button className="btn small ghost" aria-label={`Remove this AI ${title.toLowerCase()}`} onClick={onRemove}>Remove</button></div>
      {o.kind === "summary" && <><p style={{ margin: ".2rem 0" }}>{c.summary}</p>{c.key_points?.length > 0 && <ul className="small">{c.key_points.map((k: string, i: number) => <li key={i}>{k}</li>)}</ul>}
        {c.uncertain?.length > 0 && <p className="small muted">Could not be read: {c.uncertain.join("; ")}</p>}</>}
      {o.kind === "verify" && <>
        <p className="small muted">{c.note} OCR confidence {c.ocr_confidence ?? "—"}%{c.ocr_low_confidence_lines ? ` · ${c.ocr_low_confidence_lines} low-confidence lines` : ""}.</p>
        {c.issues?.length ? <ul className="small">{c.issues.map((i: any, n: number) => <li key={n}><code>{i.text}</code> — {i.problem || i.kind.replace("_", " ")}{i.correction ? ` → suggested: ${i.correction}` : ""}{i.check === "rule" ? " (rule check)" : ""}</li>)}</ul> : <p className="small">No likely OCR problems found.</p>}
        {c.missing_fields?.length > 0 && <p className="small">Expected but not found: {c.missing_fields.join(", ")}</p>}</>}
      {o.kind === "expiry" && <>
        <p className="small" style={{ margin: ".2rem 0" }}><strong>Document fact:</strong> {c.document_fact?.status === "found" ? `expires ${c.document_fact.expiry_date}${c.document_fact.excerpt ? ` (printed: “${c.document_fact.excerpt}”)` : ""}` : c.document_fact?.status === "no_expiry_stated" ? "the document states it does not expire" : "no expiry date is printed in the OCR text"}</p>
        <p className="small muted">{c.reminder_policy?.note}</p></>}
      {o.kind === "answer" && <><p className="small" style={{ margin: ".2rem 0" }}><strong>Q:</strong> {o.question}</p><p style={{ margin: ".2rem 0", whiteSpace: "pre-wrap" }}>{c.answer?.replace(/\[doc:[0-9a-f-]{36}\]/g, "")}</p></>}
      <p className="small muted" style={{ margin: 0 }}>{c.provenance ? `Based on: ${(c.provenance.basis || []).join(", ")} · ${c.provenance.profile} (${c.provenance.location === "cloud" ? "Cloud" : "Local"})` : ""} · {formatDateTime(o.created_at)}{o.created_by ? ` · ${o.created_by}` : ""}</p>
    </div>
  );
}
