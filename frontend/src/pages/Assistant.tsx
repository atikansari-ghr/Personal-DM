import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { useAiStatus } from "../ai";
import { HelpTip, Icon } from "../components/ui";

type Turn = { q: string; answer?: string; error?: string; sources: { id: string; title: string }[] };

const EXAMPLES = ["Find my passport", "When does my passport expire?", "Which of my documents expire within six months?", "Which documents are missing an expiry date?"];

/** Document assistant: answers only from documents the signed-in person may open. */
export default function AssistantPage() {
  const ai = useAiStatus();
  const [params] = useSearchParams();
  const docId = params.get("document") || "";
  const [q, setQ] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  if (ai && !ai.assistant) return <div className="empty"><h1>Document assistant</h1><p>The local AI assistant is not enabled for your account.</p><Link to="/search">Use search instead</Link></div>;
  const ask = async (question: string) => {
    if (!question.trim()) return;
    setBusy(true);
    try {
      const r = await api<any>("ai/assistant", { body: { question, document: docId || undefined } });
      setTurns((t) => [{ q: question, answer: r.answer.replace(/\[doc:[0-9a-f-]{36}\]/g, "").trim(), sources: r.sources }, ...t]);
    } catch (e: any) {
      const err = e as ApiError;
      setTurns((t) => [{ q: question, error: err.message, sources: err.data?.sources || [] }, ...t]);
    } finally {
      setBusy(false);
      setQ("");
    }
  };
  return (
    <div className="stack">
      <div className="page-head"><div><h1><Icon name="sparkle" /> Ask about your documents <HelpTip text="Answers use only documents you are allowed to open, through your family's own AI server. Check important details in the document itself." link="/help/local-ai#assistant" /></h1>
        <p className="muted">{docId ? "Asking about one document." : "Searches across the documents you can open."}</p></div></div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <label htmlFor="ask-q" className="sr-only">Question</label>
        <input id="ask-q" type="text" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. When does my passport expire?" style={{ flex: 1, minWidth: 220 }} maxLength={1000} />
        <button className="btn primary" disabled={busy || !q.trim()}>{busy ? "Thinking…" : "Ask"}</button>
      </form>
      {turns.length === 0 && <div className="row">{EXAMPLES.map((e) => <button key={e} className="btn small ghost" onClick={() => ask(e)} disabled={busy}>{e}</button>)}</div>}
      {turns.map((t, i) => (
        <div key={i} className="card">
          <p className="small muted">You asked: {t.q}</p>
          {t.answer && <p style={{ whiteSpace: "pre-wrap" }}>{t.answer}</p>}
          {t.error && <p className="error-text">{t.error}{t.sources.length > 0 && " — these documents match your question:"}</p>}
          {t.sources.length > 0 && <ul className="small">{t.sources.map((s) => <li key={s.id}><Link to={`/documents/${s.id}`}>{s.title}</Link></li>)}</ul>}
        </div>
      ))}
    </div>
  );
}
