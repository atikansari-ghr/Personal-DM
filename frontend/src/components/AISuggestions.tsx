import { useState } from "react";
import { api } from "../api";
import { useAiStatus } from "../ai";
import { HelpTip, Icon, useAsync, useToast } from "./ui";

const LABEL: Record<string, string> = { title: "Title", doc_type: "Document type", correspondent: "Issuer", tags: "Tags", folder: "Folder",
  issue_date: "Issue date", expiry_date: "Expiry date", document_number: "Document number", summary: "Summary" };

/** AI suggestions for one document. Nothing changes until a person with edit rights accepts a suggestion. */
export default function AISuggestions({ docId, onChange }: { docId: string; onChange: () => void }) {
  const ai = useAiStatus();
  const toast = useToast();
  const data = useAsync(() => api<any>(`documents/${docId}/ai/suggestions`), [docId]);
  const [busy, setBusy] = useState(false);
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
        <p className="small muted">{last_job ? (last_job.status === "failed" ? `The last AI analysis failed: ${last_job.error}` : last_job.status === "done" ? "No open suggestions." : `AI analysis ${last_job.status}…`) : "No AI analysis yet."}</p>
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
          <button className="btn small ghost" disabled={busy} onClick={() => api(`documents/${docId}/ai/analyze`, { method: "POST" }).then(() => { toast("AI analysis queued"); setTimeout(data.reload, 4000); }).catch((e) => toast(e.message, "error"))}>Analyse again</button>
        </div>
      )}
    </div>
  );
}
