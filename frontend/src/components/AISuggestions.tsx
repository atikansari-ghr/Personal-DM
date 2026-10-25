import { useEffect, useState } from "react";
import { api, formatDateTime } from "../api";
import { aiJobFacts, aiJobText, useAiStatus } from "../ai";
import { HelpTip, Icon, useAsync, useToast } from "./ui";

const LABEL: Record<string, string> = { title: "Title", doc_type: "Document type", correspondent: "Issuer", tags: "Tags", folder: "Folder",
  issue_date: "Issue date", expiry_date: "Expiry date", document_number: "Document number", summary: "Summary", full_name: "Name" };

/** AI suggestions for one document. Nothing changes until a person with edit rights accepts a suggestion (as it is,
 *  or edited first). A suggestion that differs from a value a person set is a conflict and needs an explicit confirm.
 *  The AI's confidence is shown on its own — never combined with the OCR confidence. */
export default function AISuggestions({ docId, onChange }: { docId: string; onChange: () => void }) {
  const ai = useAiStatus();
  const toast = useToast();
  const data = useAsync(() => api<any>(`documents/${docId}/ai/suggestions`), [docId]);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<{ id: number; value: string } | null>(null);
  const active = ["queued", "running"].includes(data.data?.last_job?.status);
  useEffect(() => {  // an AI Action was started or finished in the AI Actions panel of this document
    const on = (e: Event) => { if ((e as CustomEvent).detail === docId) data.reload(); };
    window.addEventListener("pd:ai-changed", on);
    return () => window.removeEventListener("pd:ai-changed", on);
  }, [docId]);
  useEffect(() => {  // while an analysis runs, look again every 5 s (only on this open document)
    if (!active) return;
    const t = window.setTimeout(data.reload, 5000);
    return () => window.clearTimeout(t);
  }, [active, data.data]);
  if (!ai || !(ai.ocr_assist || ai.smart_organization) || !data.data) return null;
  const { suggestions, can_edit, last_job } = data.data;
  const send = async (sid: number, body: any) => {
    setBusy(true);
    try {
      const r = await api<any>(`documents/${docId}/ai/suggestions/${sid}`, { body });
      if (r.skipped_conflicts?.length) toast(`Not applied (they differ from values a person set — review them one by one): ${r.skipped_conflicts.map((f: string) => LABEL[f] || f).join(", ")}`, "error");
      setPicked(new Set());
      setEditing(null);
      data.reload();
      if (body.action === "accept") onChange();
    } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  };
  const accept = (s: any, value?: any) => {
    if (s.conflict && !window.confirm(`${LABEL[s.field] || s.field}: replace “${s.current || "the current value"}”, which a person set, with “${value ?? s.display}”?`)) return;
    send(s.id, { action: "accept", ...(value !== undefined ? { value } : {}), ...(s.conflict ? { confirm: true } : {}) });
  };
  const toggle = (id: number) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  return (
    <div className="card" style={{ borderStyle: "dashed" }} data-ai-suggestions>
      <h3><Icon name="sparkle" size={18} /> AI suggestions <HelpTip text="Suggested by AI from the OCR text. They are only applied when you accept them; dates you accept become confirmed and drive reminders. “Observed” means the value is printed in the OCR text; “inferred” means the AI concluded it." link="/help/local-ai#suggestions" /></h3>
      {suggestions.length === 0 ? (
        <div className="small" data-ai-job={last_job?.status || "none"} role="status">
          <p className={last_job?.status === "failed" ? "error-text" : "muted"} style={{ margin: 0 }}>
            {last_job ? (last_job.status === "done" ? "No open suggestions." : `${last_job.action || "AI analysis"} ${aiJobText(last_job, formatDateTime)}`) : "No AI analysis yet."}</p>
          {last_job && aiJobFacts(last_job.detail) && <p className="muted" style={{ margin: 0 }}>{aiJobFacts(last_job.detail)}</p>}
        </div>
      ) : (
        <table className="responsive"><thead><tr>{can_edit && <th><span className="sr-only">Select</span></th>}<th>Field</th><th>Suggestion</th><th className="hide-mobile">Current</th><th /></tr></thead><tbody>
          {suggestions.map((s: any) => (
            <tr key={s.id} data-suggestion={s.field} data-conflict={s.conflict ? "1" : undefined}>
              {can_edit && <td>{s.field !== "summary" && <input type="checkbox" aria-label={`Select ${s.field_label || LABEL[s.field] || s.field}`} checked={picked.has(s.id)} onChange={() => toggle(s.id)} />}</td>}
              <td>{s.field_label || LABEL[s.field] || s.field}</td>
              <td>{editing?.id === s.id
                ? <form className="row" style={{ gap: ".3rem" }} onSubmit={(e) => { e.preventDefault(); if (editing) accept(s, editing.value); }}>
                    <input type={s.field.endsWith("_date") ? "date" : "text"} aria-label={`Edit ${s.field_label || LABEL[s.field] || s.field}`} value={editing?.value ?? ""} onChange={(e) => setEditing({ id: s.id, value: e.target.value })} />
                    <button className="btn small primary" disabled={busy}>Accept edited</button><button type="button" className="btn small ghost" onClick={() => setEditing(null)}>Cancel</button></form>
                : <strong>{s.display}</strong>}
                <div className="small muted">
                  {s.evidence && <span className={`badge ${s.evidence === "observed" ? "ok" : "neutral"}`} title={s.evidence === "observed" ? "Printed in the OCR text" : "Concluded by the AI, not printed as such"}>{s.evidence === "observed" ? "Observed" : "Inferred"}</span>}
                  {s.ai_confidence != null && <span title="The AI's own confidence (not the OCR confidence)"> AI confidence {Math.round(s.ai_confidence * 100)}%</span>}
                  {s.conflict && <span className="badge danger" title="Differs from a value a person set">Conflict</span>}
                  {s.source && <span className="badge neutral" data-suggestion-source={s.source} title="What the AI read">{s.source === "original" ? `Original document${s.page ? ` · page ${s.page}` : ""}` : "OCR text"}</span>}
                  {s.note && <span> · {s.note}</span>}
                </div></td>
              <td className="small muted hide-mobile">{s.current || "—"}</td>
              <td>{can_edit && s.field !== "summary" && editing?.id !== s.id && <div className="row" style={{ gap: ".3rem" }}>
                  <button className="btn small primary" disabled={busy} onClick={() => accept(s)}>Accept</button>
                  {s.editable && <button className="btn small ghost" disabled={busy} onClick={() => setEditing({ id: s.id, value: Array.isArray(s.value) ? s.value.join(", ") : String(s.value) })}>Edit</button>}
                  <button className="btn small ghost" disabled={busy} onClick={() => send(s.id, { action: "dismiss" })}>Reject</button></div>}
                {can_edit && s.field === "summary" && <button className="btn small ghost" disabled={busy} onClick={() => send(s.id, { action: "dismiss" })}>Hide</button>}</td>
            </tr>
          ))}
        </tbody></table>
      )}
      {can_edit && (
        <div className="row" style={{ flexWrap: "wrap" }}>
          {picked.size > 0 && <button className="btn small primary" disabled={busy} onClick={() => send(0, { action: "accept", ids: Array.from(picked) })}>Accept selected ({picked.size})</button>}
          {suggestions.length > 1 && <button className="btn small" disabled={busy} onClick={() => send(0, { action: "accept" })}>Accept all</button>}
          {suggestions.length > 0 && <button className="btn small ghost" disabled={busy} onClick={() => send(0, { action: "dismiss" })}>Reject all</button>}
          <button className="btn small ghost" disabled={busy} onClick={() => api(`documents/${docId}/ai/analyze`, { method: "POST" }).then(() => { toast("AI analysis queued"); data.reload(); }).catch((e) => toast(e.message, "error"))}>Analyse again</button>
        </div>
      )}
    </div>
  );
}
