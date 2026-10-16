import { useEffect, useState } from "react";
import { api, formatDateTime } from "../api";
import { aiJobFacts, aiJobText, useAiStatus } from "../ai";
import { HelpTip, Icon, useAsync, useToast } from "./ui";

const LABEL: Record<string, string> = { title: "Title", doc_type: "Document type", correspondent: "Issuer", tags: "Tags", folder: "Folder",
  issue_date: "Issue date", expiry_date: "Expiry date", document_number: "Document number", summary: "Summary" };

/** AI suggestions for one document. Nothing changes until a person with edit rights accepts a suggestion. */
export default function AISuggestions({ docId, onChange }: { docId: string; onChange: () => void }) {
  const ai = useAiStatus();
  const toast = useToast();
  const data = useAsync(() => api<any>(`documents/${docId}/ai/suggestions`), [docId]);
  const [busy, setBusy] = useState(false);
  const active = ["queued", "running"].includes(data.data?.last_job?.status);
  useEffect(() => {  // while an analysis runs, look again every 5 s (only on this open document)
    if (!active) return;
    const t = window.setTimeout(data.reload, 5000);
    return () => window.clearTimeout(t);
  }, [active, data.data]);
  if (!ai || !(ai.ocr_assist || ai.smart_organization) || !data.data) return null;
  const { suggestions, can_edit, last_job } = data.data;
  const decide = async (id: number, action: "accept" | "dismiss") => {
    setBusy(true);
    try { await api(`documents/${docId}/ai/suggestions/${id}`, { body: { action } }); data.reload(); if (action === "accept") onChange(); }
    catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <div className="card" style={{ borderStyle: "dashed" }}>
      <h3><Icon name="sparkle" size={18} /> AI suggestions <HelpTip text="Suggested by your local AI from the OCR text. They are only applied when you accept them; dates you accept become confirmed and drive reminders." link="/help/local-ai#ocr-assist" /></h3>
      {suggestions.length === 0 ? (
        <div className="small" data-ai-job={last_job?.status || "none"} role="status">
          <p className={last_job?.status === "failed" ? "error-text" : "muted"} style={{ margin: 0 }}>
            {last_job ? (last_job.status === "done" ? "No open suggestions." : `AI analysis ${aiJobText(last_job, formatDateTime)}`) : "No AI analysis yet."}</p>
          {last_job && aiJobFacts(last_job.detail) && <p className="muted" style={{ margin: 0 }}>{aiJobFacts(last_job.detail)}</p>}
        </div>
      ) : (
        <table className="responsive"><thead><tr><th>Field</th><th>Suggestion</th><th className="hide-mobile">Current</th><th /></tr></thead><tbody>
          {suggestions.map((s: any) => <tr key={s.id}><td>{LABEL[s.field] || s.field}</td><td><strong>{s.display}</strong></td><td className="small muted hide-mobile">{s.current || "—"}</td>
            <td>{can_edit && s.field !== "summary" && <div className="row" style={{ gap: ".3rem" }}><button className="btn small primary" disabled={busy} onClick={() => decide(s.id, "accept")}>Accept</button><button className="btn small ghost" disabled={busy} onClick={() => decide(s.id, "dismiss")}>Dismiss</button></div>}
              {can_edit && s.field === "summary" && <button className="btn small ghost" disabled={busy} onClick={() => decide(s.id, "dismiss")}>Hide</button>}</td></tr>)}
        </tbody></table>
      )}
      {can_edit && (
        <div className="row">
          {suggestions.length > 1 && <button className="btn small" disabled={busy} onClick={() => decide(0, "accept")}>Accept all</button>}
          <button className="btn small ghost" disabled={busy} onClick={() => api(`documents/${docId}/ai/analyze`, { method: "POST" }).then(() => { toast("AI analysis queued"); data.reload(); }).catch((e) => toast(e.message, "error"))}>Analyse again</button>
        </div>
      )}
    </div>
  );
}
