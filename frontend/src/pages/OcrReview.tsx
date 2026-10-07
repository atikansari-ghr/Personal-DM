import { useState } from "react";
import { Link } from "react-router-dom";
import { api, formatDate, formatDateTime } from "../api";
import { OcrStateBadge } from "../components/OcrPanel";
import { useDocumentTypes } from "../components/DocumentDetails";
import { Icon, Skeleton, useAsync, useToast } from "../components/ui";

/** OCR review queue: recognised documents waiting for a person to check the suggested details. Only documents the
 *  signed-in person may edit are listed. */

const LABELS: Record<string, string> = {
  full_name: "Name", document_number: "Number", issue_date: "Issue date", expiry_date: "Expiry date", no_expiry: "Does not expire",
  date_of_birth: "Date of birth", nationality: "Nationality", issuer: "Issuer", country_code: "Country", sex: "Sex", place_of_issue: "Place of issue",
};
const DATES = ["issue_date", "expiry_date", "date_of_birth"];

export default function OcrReviewPage() {
  const toast = useToast();
  const [tick, setTick] = useState(0);
  const [typeFilter, setTypeFilter] = useState("");
  const types = useDocumentTypes();
  const { data, error } = useAsync(() => api<{ items: any[] }>(`ocr/review${typeFilter ? `?type=${typeFilter}` : ""}`), [tick, typeFilter]);
  const [editing, setEditing] = useState<string>("");
  const [value, setValue] = useState("");
  const reload = () => setTick((t) => t + 1);
  const field = async (doc: string, key: string, v: string | null, confirm = true) => {
    try {
      await api(`documents/${doc}/fields`, { body: v === null ? { key, delete: true } : { key, value: v, confirm } });
      setEditing("");
      reload();
    } catch (e: any) { toast(e.message, "error"); }
  };
  return (
    <div>
      <div className="page-head"><h1>OCR review</h1></div>
      <p className="muted">Details suggested by text recognition are not used until you confirm them. Accept, correct or reject each one; confirmed values are never overwritten by a later OCR run.</p>
      <div className="field" style={{ maxWidth: 280 }}><label htmlFor="ocr-type-filter">Document type</label>
        <select id="ocr-type-filter" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}><option value="">All types</option><option value="none">Not assigned</option>{types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></div>
      {error && <div className="alert error">{error}</div>}
      {!data ? <Skeleton lines={6} /> : data.items.length === 0 ? <div className="empty"><Icon name="check" /> Nothing waiting for review.</div> : (
        <div className="stack">{data.items.map((d) => (
          <section key={d.id} className="card review-item">
            <div className="row between">
              <div><h2 style={{ fontSize: "1.1rem", margin: 0 }}><Link to={`/documents/${d.id}`}>{d.title}</Link></h2>
                <div className="small muted">{d.owner.display_name}{d.type ? ` · ${d.type}` : ""}{d.updated_at ? ` · ${formatDateTime(d.updated_at)}` : ""}{d.languages?.length ? ` · ${d.languages.join(" + ")}` : ""}{d.confidence != null ? ` · confidence ${Math.round(d.confidence)}%` : ""}</div></div>
              <OcrStateBadge state={d.ocr_state} />
            </div>
            {d.ocr_state === "failed" && <div className="alert error">Text recognition failed: {d.error || "unknown error"}. <Link to={`/documents/${d.id}`}>Open the document</Link> to choose other pages, languages or orientation.</div>}
            {d.proposed.length > 0 && (
              <table className="responsive"><thead><tr><th>Detail</th><th>Suggested</th><th>Notes</th><th /></tr></thead><tbody>
                {d.proposed.map((f: any) => (
                  <tr key={f.key}>
                    <td>{LABELS[f.key] || f.key.replace(/^custom:/, "")}</td>
                    <td>{editing === `${d.id}:${f.key}` ? (
                      <form className="row" onSubmit={(e) => { e.preventDefault(); field(d.id, f.key, value); }}>
                        <input aria-label={`Correct ${LABELS[f.key] || f.key}`} type={DATES.includes(f.key) ? "date" : "text"} value={value} onChange={(e) => setValue(e.target.value)} style={{ maxWidth: 200 }} autoFocus />
                        <button className="btn small primary">Save</button><button type="button" className="btn small" onClick={() => setEditing("")}>Cancel</button>
                      </form>
                    ) : <strong>{DATES.includes(f.key) ? formatDate(f.value) : f.key === "no_expiry" ? "Yes" : f.value}</strong>}</td>
                    <td className="small">{f.flags.map((x: string) => <div key={x} className="error-text">{x}</div>)}{f.excerpt && <div className="muted">“{f.excerpt}”</div>}</td>
                    <td className="row" style={{ gap: ".3rem", flexWrap: "nowrap" }}>
                      <button className="btn small primary" onClick={() => field(d.id, f.key, f.value)} aria-label={`Accept ${LABELS[f.key] || f.key}`}>Accept</button>
                      <button className="btn small" onClick={() => { setEditing(`${d.id}:${f.key}`); setValue(f.sensitive ? "" : f.value); }}>Correct</button>
                      <button className="btn small ghost" onClick={() => field(d.id, f.key, null)} aria-label={`Reject ${LABELS[f.key] || f.key}`}>Reject</button>
                    </td>
                  </tr>
                ))}
              </tbody></table>
            )}
            <div className="row">
              <Link className="btn small" to={`/documents/${d.id}`}>Open document</Link>
              {d.proposed.length === 0 && d.ocr_state === "needs_review" && <button className="btn small" onClick={() => api(`documents/${d.id}/ocr/reviewed`, { method: "POST" }).then(reload)}>Mark reviewed</button>}
            </div>
          </section>
        ))}</div>
      )}
    </div>
  );
}
