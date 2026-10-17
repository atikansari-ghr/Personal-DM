import { useState } from "react";
import { Link } from "react-router-dom";
import { api, formatDateTime } from "../../api";
import { aiJobFacts, aiJobText, resetAiStatus } from "../../ai";
import SettingsForm from "../../components/SettingsForm";
import { HelpTip, Icon, Modal, Skeleton, useAsync, useToast } from "../../components/ui";

type Provider = "openai" | "ollama" | "openai_cloud" | "anthropic" | "gemini" | "openrouter";
type Profile = {
  id?: number; name: string; enabled: boolean; is_default: boolean; provider: Provider; provider_label?: string; base_url: string; api_key_configured?: boolean;
  text_model: string; vision_model: string; embedding_model: string; timeout_seconds: number; max_input_chars: number; max_output_tokens: number;
  privacy: "local" | "lan" | "external"; external_acknowledged: boolean; features: string[]; capabilities?: Record<string, string>;
  location?: "local" | "cloud"; cloud_send_ocr_text: boolean; cloud_send_metadata: boolean; cloud_send_images: boolean; cloud_send_files: boolean;
  supports?: Record<string, boolean | string>; last_test?: { at: string; ok: boolean; kind: string; latency_ms?: number; error?: string; steps: { step: string; ok: boolean }[] } | null;
};

const BLANK: Profile = { name: "", enabled: true, is_default: false, provider: "openai", base_url: "http://192.168.1.50:1234/v1", text_model: "", vision_model: "",
  embedding_model: "", timeout_seconds: 60, max_input_chars: 12000, max_output_tokens: 800, privacy: "lan", external_acknowledged: false, features: [],
  cloud_send_ocr_text: false, cloud_send_metadata: false, cloud_send_images: false, cloud_send_files: false };
/** Change Set Z: Local LLM servers and cloud providers. Cloud providers are always Cloud profiles. */
const PROVIDERS: [Provider, string, string][] = [
  ["openai", "Local LLM — OpenAI-compatible (LM Studio, llama.cpp, vLLM, LocalAI)", "http://192.168.1.50:1234/v1"],
  ["ollama", "Local LLM — Ollama", "http://192.168.1.50:11434"],
  ["openai_cloud", "OpenAI (cloud)", "https://api.openai.com/v1"],
  ["anthropic", "Anthropic Claude (cloud)", "https://api.anthropic.com"],
  ["gemini", "Google Gemini (cloud)", "https://generativelanguage.googleapis.com"],
  ["openrouter", "OpenRouter (cloud)", "https://openrouter.ai/api/v1"],
];
const CLOUD_PROVIDERS = ["openai_cloud", "anthropic", "gemini", "openrouter"];
const CLOUD_SEND: [keyof Profile, string, string][] = [
  ["cloud_send_ocr_text", "OCR text", "The recognised text of the document. Needed by every AI Action."],
  ["cloud_send_metadata", "Selected metadata", "Title, Document Type, issuer, dates, tags and folder names, as context."],
  ["cloud_send_images", "Original images", "The page image (vision). Off by default; people must confirm each send."],
  ["cloud_send_files", "Original PDF / files", "The original PDF. Off by default; people must confirm each send."],
];
const FEATURE_LABELS: Record<string, string> = { ocr_assist: "OCR assist", smart_organization: "Smart organisation", semantic_search: "Semantic search", assistant: "Document assistant" };
const PRIVACY: [string, string, string][] = [
  ["local", "Local only", "The AI server runs on this server, next to the app."],
  ["lan", "Private LAN", "Another machine on your home network (e.g. a PC with LM Studio or Ollama)."],
  ["external", "External endpoint", "A server outside your network. Selected document/OCR text WILL leave your network."],
];

function ProfileDialog({ initial, onClose, onSaved }: { initial: Profile; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [p, setP] = useState<Profile & { api_key?: string; clear_api_key?: boolean }>({ ...initial });
  const [models, setModels] = useState<string[]>([]);
  const set = (k: string, v: any) => setP({ ...p, [k]: v });
  const cloud = CLOUD_PROVIDERS.includes(p.provider) || p.privacy === "external";
  const save = async () => {
    try {
      if (p.id) await api(`ai/profiles/${p.id}`, { method: "PATCH", body: p });
      else await api("ai/profiles", { body: p });
      toast("AI profile saved");
      resetAiStatus();
      onSaved();
    } catch (e: any) { toast(e.message, "error"); }
  };
  const discover = () => p.id && api<{ models: string[] }>(`ai/profiles/${p.id}/models`).then((r) => { setModels(r.models); toast(`${r.models.length} models found`); }).catch((e) => toast(e.message, "error"));
  return (
    <Modal title={p.id ? `Edit ${initial.name}` : "Add AI profile"} onClose={onClose} wide>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
          <div className="field"><label htmlFor="ai-name">Profile name</label><input id="ai-name" type="text" required value={p.name} onChange={(e) => set("name", e.target.value)} placeholder="LM Studio PC" /></div>
          <div className="field"><label htmlFor="ai-prov">Provider</label><select id="ai-prov" value={p.provider} onChange={(e) => {
            const prov = e.target.value as Provider; const def = PROVIDERS.find((x) => x[0] === prov)![2];
            setP({ ...p, provider: prov, base_url: CLOUD_PROVIDERS.includes(prov) || !p.base_url || PROVIDERS.some((x) => x[2] === p.base_url) ? def : p.base_url,
              ...(CLOUD_PROVIDERS.includes(prov) ? { privacy: "external" } : {}) });
          }}>
            {PROVIDERS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <div className="hint">{cloud ? <span className="badge danger">Cloud</span> : <span className="badge ok">Local</span>} {cloud ? "Document content you allow below leaves your network." : "Runs on your own server or LAN."}</div></div>
          <div className="field"><label htmlFor="ai-url">Server URL</label><input id="ai-url" type="url" required value={p.base_url} onChange={(e) => set("base_url", e.target.value)} />
            <div className="hint">e.g. {PROVIDERS.find((x) => x[0] === p.provider)?.[2]}</div></div>
          <div className="field"><label htmlFor="ai-key">API key {CLOUD_PROVIDERS.includes(p.provider) ? "(required, stored encrypted, never shown again)" : "(optional)"}</label><input id="ai-key" type="password" autoComplete="new-password" value={p.api_key || ""} onChange={(e) => set("api_key", e.target.value)} placeholder={p.api_key_configured ? "•••••• stored (leave empty to keep)" : "Not needed for most local servers"} />
            {p.api_key_configured && <label className="check small"><input type="checkbox" checked={!!p.clear_api_key} onChange={(e) => set("clear_api_key", e.target.checked)} /> Remove stored key</label>}</div>
        </div>
        <datalist id="ai-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
          {[["text_model", "Text model", "A chat model (not an embedding model). AI Actions send it the OCR text"], ["vision_model", "Vision model (optional)", "Only used when a person chooses to analyse the page image (and, for a Cloud profile, original images are allowed)"], ["embedding_model", "Embedding model", "Only for semantic search; never used to write answers"]].map(([k, l, h]) => (
            <div className="field" key={k}><label htmlFor={`ai-${k}`}>{l}</label><input id={`ai-${k}`} type="text" list="ai-models" value={(p as any)[k]} onChange={(e) => set(k, e.target.value)} /><div className="hint">{h}</div></div>
          ))}
        </div>
        {p.id && <div><button type="button" className="btn small" onClick={discover}><Icon name="search" size={16} /> Discover models on the server</button></div>}
        {!CLOUD_PROVIDERS.includes(p.provider) && <fieldset className="field"><legend>Privacy classification <HelpTip text="Checked on every request against the server's real address. A LAN profile that points outside your network is refused and no text is sent." link="/help/local-ai#privacy" /></legend>
          {PRIVACY.map(([k, l, d]) => <label key={k} className="check"><input type="radio" name="ai-privacy" checked={p.privacy === k} onChange={() => set("privacy", k)} /> <strong>{l}</strong> — <span className="small">{d}</span></label>)}
        </fieldset>}
        {cloud && (
          <div className="alert danger" data-cloud-profile><strong>Cloud profile:</strong> only the data categories you switch on below are sent to this provider. Original images and files stay off unless you enable them, and people confirm each send.
            <label className="check"><input type="checkbox" checked={p.external_acknowledged} onChange={(e) => set("external_acknowledged", e.target.checked)} /> I understand that selected document content may leave the local network.</label></div>
        )}
        {cloud && <fieldset className="field" aria-label="Data this Cloud profile may receive"><legend>Data this Cloud profile may receive <HelpTip text="Independent controls. Nothing else is ever sent; API keys are never shown." link="/help/local-ai#cloud-privacy" /></legend>
          {CLOUD_SEND.map(([k, l, d]) => <label key={k} className="check"><input type="checkbox" checked={!!p[k]} onChange={(e) => set(k, e.target.checked)} /> <strong>{l}</strong> — <span className="small">{d}</span></label>)}
        </fieldset>}
        <fieldset className="field"><legend>Features this profile may serve</legend>
          <div className="row">{Object.entries(FEATURE_LABELS).map(([k, l]) => <label key={k} className="check"><input type="checkbox" checked={p.features.length === 0 || p.features.includes(k)} onChange={(e) => {
            const all = Object.keys(FEATURE_LABELS);
            const cur = p.features.length === 0 ? all : p.features;
            const next = e.target.checked ? [...cur, k] : cur.filter((x) => x !== k);
            set("features", next.length === all.length ? [] : next);
          }} /> {l}</label>)}</div></fieldset>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
          <div className="field"><label htmlFor="ai-timeout">Timeout (seconds)</label><input id="ai-timeout" type="number" min={5} max={600} value={p.timeout_seconds} onChange={(e) => set("timeout_seconds", Number(e.target.value))} /></div>
          <div className="field"><label htmlFor="ai-in">Max text sent (characters)</label><input id="ai-in" type="number" min={1000} max={200000} value={p.max_input_chars} onChange={(e) => set("max_input_chars", Number(e.target.value))} /></div>
          <div className="field"><label htmlFor="ai-out">Max reply (tokens)</label><input id="ai-out" type="number" min={64} max={8192} value={p.max_output_tokens} onChange={(e) => set("max_output_tokens", Number(e.target.value))} /></div>
        </div>
        <div className="row">
          <label className="check"><input type="checkbox" checked={p.enabled} onChange={(e) => set("enabled", e.target.checked)} /> Enabled</label>
          <label className="check"><input type="checkbox" checked={p.is_default} onChange={(e) => set("is_default", e.target.checked)} /> Default profile</label>
        </div>
        <button className="btn primary">Save profile</button>
      </form>
    </Modal>
  );
}

function TestResult({ r }: { r: any }) {
  if (!r) return null;
  if (r.busy) return <div className="small muted" role="status">Testing…</div>;
  if (r.kind === "analysis") {
    return r.error
      ? <div className="small error-text" role="status">✗ Test AI analysis failed · AI analysis: {r.error}</div>
      : <div className="small" role="status">✓ AI analysis works ({r.latency_ms} ms, {r.structured_output === "schema" ? "structured output" : "JSON by prompt"}{r.fallback ? " — this server has no structured output, so the plain-prompt mode is used" : ""}). Read back: {Object.keys(r.fields || {}).join(", ") || "nothing"}{r.dates_correct?.length === 2 ? " · dates correct" : " · check the dates"}</div>;
  }
  return (
    <div className="small" role="status" data-test-result>
      {r.error && <div className="error-text">✗ {r.error}</div>}
      {r.steps?.length > 0 && <ul className="plain test-steps">{r.steps.map((s: any, i: number) => <li key={i}>{s.ok ? "✓" : "✗"} {s.step}{s.detail ? ` — ${s.detail}` : ""}</li>)}</ul>}
      {!r.error && <div>Connected ({r.privacy_actual}, {r.latency_ms} ms) · {r.models?.length || 0} models</div>}
    </div>
  );
}

function OcrTests() {
  const [res, setRes] = useState<Record<string, any>>({});
  const run = (engine: string) => {
    setRes((x) => ({ ...x, [engine]: { busy: true } }));
    api<any>("ai/test-ocr", { body: { engine } }).then((r) => setRes((x) => ({ ...x, [engine]: r })))
      .catch((e) => setRes((x) => ({ ...x, [engine]: { ok: false, error: e.message } })));
  };
  return (
    <div className="card" id="ai-ocr-tests">
      <h2>Test OCR <HelpTip text="Analyze Document always runs text recognition first and sends only the recognised text to the AI text model. Test each OCR engine here on a generated sample, and the AI separately in the profile above, to see which part fails." link="/help/local-ai#diagnostics" /></h2>
      <div className="row" style={{ gap: ".4rem", flexWrap: "wrap" }}>
        <button className="btn small" onClick={() => run("light-ocr")}>Test OCR — light-ocr</button>
        <button className="btn small" onClick={() => run("tesseract")}>Test OCR — Tesseract</button>
        <button className="btn small" onClick={() => run("paddleocr")}>Test OCR — PaddleOCR</button>
      </div>
      {["light-ocr", "tesseract", "paddleocr"].map((e) => res[e] && (
        <div key={e} className="small" role="status">{res[e].busy ? `${e === "tesseract" ? "Tesseract" : e === "light-ocr" ? "light-ocr" : "PaddleOCR"}: testing…`
          : res[e].ok ? `✓ ${res[e].label || e}: read ${res[e].chars} characters in ${res[e].seconds} s${res[e].accuracy != null ? ` · accuracy ${res[e].accuracy}%` : ""}`
            : <span className="error-text">✗ {res[e].label || e}: {res[e].error || "no text was recognised"}</span>}</div>
      ))}
    </div>
  );
}

function ProfilesCard() {
  const list = useAsync(() => api<{ profiles: Profile[] }>("ai/profiles"), []);
  const [edit, setEdit] = useState<Profile | null>(null);
  const [results, setResults] = useState<Record<string, any>>({});
  const put = (key: string, v: any) => setResults((x) => ({ ...x, [key]: v }));
  const test = (p: Profile) => {
    put(`c${p.id}`, { busy: true });
    api<any>(`ai/profiles/${p.id}/test`, { method: "POST" }).then((r) => { put(`c${p.id}`, r); list.reload(); })
      .catch((e) => { put(`c${p.id}`, { error: e.message, ...(e.data || {}) }); list.reload(); });
  };
  const testAnalysis = (p: Profile) => {
    put(`a${p.id}`, { busy: true, kind: "analysis" });
    api<any>(`ai/profiles/${p.id}/test-analysis`, { method: "POST" }).then((r) => { put(`a${p.id}`, { ...r, kind: "analysis" }); list.reload(); })
      .catch((e) => put(`a${p.id}`, { error: e.message, kind: "analysis" }));
  };
  if (!list.data) return <Skeleton />;
  return (
    <div className="card">
      <h2>AI profiles <HelpTip text="A profile is one AI connection: a Local LLM server or a cloud provider. The default profile serves the AI Actions; there is never a fallback to another server or to the cloud." link="/help/local-ai#profiles" /></h2>
      {list.data.profiles.length === 0 && <p className="small muted">No AI configured yet. Add an LM Studio, Ollama or other OpenAI-compatible server running on your network (Local), or a cloud provider (Cloud).</p>}
      {list.data.profiles.map((p) => {
        return (
          <div key={p.id} className="list-item" style={{ alignItems: "flex-start" }}>
            <div className="grow">
              <strong>{p.name}</strong> {p.is_default && <span className="badge ok">default</span>} {!p.enabled && <span className="badge neutral">disabled</span>}
              <span className={`badge ${p.location === "cloud" ? "danger" : "ok"}`} data-location={p.location}>{p.location === "cloud" ? "Cloud" : "Local"}</span>
              <span className={`badge ${p.privacy === "external" ? "danger" : "neutral"}`}>{PRIVACY.find((x) => x[0] === p.privacy)?.[1]}</span>
              <div className="small muted">{p.provider_label || p.provider} · {p.base_url} · text: {p.text_model || "—"} · vision: {p.vision_model || "—"} · embeddings: {p.embedding_model || "—"} · API key {p.api_key_configured ? "stored" : "not set"}</div>
              {p.supports && <div className="small muted">Can: {Object.entries(p.supports).filter(([, v]) => v === true).map(([k]) => ({ text: "text analysis", vision: "page images", file: "PDF files", structured_json: "structured JSON", embeddings: "embeddings" } as Record<string, string>)[k] || k).join(", ") || "—"}</div>}
              {p.location === "cloud" && <div className="small muted">Sends: {CLOUD_SEND.filter(([k]) => p[k]).map(([, l]) => l).join(", ") || "nothing (all categories off)"}</div>}
              <div className="small muted" data-last-test>Last test: {p.last_test ? `${p.last_test.ok ? "✓ passed" : "✗ failed"} (${p.last_test.kind}) ${formatDateTime(p.last_test.at)}${p.last_test.steps?.length ? ` · checks run: ${p.last_test.steps.map((s) => `${s.ok ? "✓" : "✗"} ${s.step}`).join(", ")}` : ""}` : "never"}</div>
              {p.capabilities?.structured_output && <div className="small muted">Structured output: {p.capabilities.structured_output === "supported" ? "supported" : "not supported by this server (JSON is requested in the prompt instead)"}</div>}
              <TestResult r={results[`c${p.id}`]} />
              <TestResult r={results[`a${p.id}`]} />
            </div>
            <div className="row" style={{ gap: ".3rem", flexWrap: "wrap" }}>
              <button className="btn small" onClick={() => test(p)}>Test Profile</button>
              <button className="btn small" onClick={() => testAnalysis(p)}>Test AI analysis</button>
              <button className="btn small ghost" onClick={() => setEdit(p)}>Edit</button>
              <button className="btn small ghost" onClick={() => api(`ai/profiles/${p.id}`, { method: "DELETE" }).then(() => { resetAiStatus(); list.reload(); })}>Remove</button>
            </div>
          </div>
        );
      })}
      <button className="btn" onClick={() => setEdit({ ...BLANK })}><Icon name="plus" size={16} /> Add AI profile</button>
      {edit && <ProfileDialog initial={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload(); }} />}
    </div>
  );
}

function AiJobsCard() {
  const toast = useToast();
  const jobs = useAsync(() => api<any>("ai/jobs"), []);
  if (!jobs.data) return <Skeleton />;
  return (
    <div className="card">
      <h2>AI jobs <button className="btn small" onClick={jobs.reload}><Icon name="refresh" size={16} /> Refresh</button></h2>
      <p className="small">{jobs.data.counts.queued} queued · {jobs.data.counts.running} running · {jobs.data.counts.failed} failed. Document content is never shown here.</p>
      <table className="responsive"><thead><tr><th>Job</th><th>Requested by</th><th>Model</th><th>Status</th><th>When</th></tr></thead><tbody>
        {jobs.data.jobs.slice(0, 30).map((j: any) => <tr key={j.id}><td>{j.action || j.kind}{j.trigger && j.trigger !== "manual" && <span className="badge neutral">{j.trigger === "smart" ? "Smart Auto" : "OCR + AI"}</span>}{j.document && <div className="small"><Link to={`/documents/${j.document}`}>document</Link></div>}</td><td className="small">{j.requested_by || "—"}</td>
          <td className="small">{j.profile ? `${j.profile} · ${j.model}` : "—"}{j.location && <div><span className={`badge ${j.location === "cloud" ? "danger" : "ok"}`}>{j.location === "cloud" ? "Cloud" : "Local"}</span>{j.data_sent?.length ? ` sent: ${j.data_sent.join(", ")}` : ""}</div>}</td>
          <td><span className={`badge ${j.status === "failed" ? "danger" : j.status === "done" ? "ok" : "neutral"}`}>{j.status_label || j.status}</span>
            {j.status !== "done" && <div className={`small ${j.status === "failed" ? "error-text" : "muted"}`} data-job-state>{aiJobText(j, formatDateTime).replace(/^\w+ · /, "")}</div>}
            {j.status === "queued" && j.next_retry_at && j.error && <div className="small muted">Last attempt: {j.error}</div>}
            {aiJobFacts(j.detail) && <div className="small muted">{aiJobFacts(j.detail)}</div>}
            {j.status === "failed" && j.retryable && j.document && <button className="btn small ghost" onClick={() => api(`ai/jobs/${j.id}/retry`, { method: "POST" }).then(() => { toast("Queued again"); jobs.reload(); }).catch((e) => toast(e.message, "error"))}>Retry</button>}</td>
          <td className="small">{formatDateTime(j.finished_at || j.created_at)}</td></tr>)}
      </tbody></table>
      <button className="btn small" onClick={() => api<any>("ai/reindex", { method: "POST" }).then((r) => toast(`${r.queued} documents queued for the semantic index`)).catch((e) => toast(e.message, "error"))}>Rebuild semantic index</button>
    </div>
  );
}

export default function LocalAIPanel() {
  return (
    <div className="stack">
      <div className="card"><p>AI is optional and is <strong>not</strong> an OCR engine: OCR (Settings → OCR) always reads the document first and works the same without AI. AI only <strong>suggests</strong> — nothing changes until a person accepts it — and Ask AI only sees documents the asking person may open. <Link to="/help/local-ai">AI guide</Link></p>
        <p className="small muted">A 2-CPU / 4 GB container cannot run useful models itself: run LM Studio or Ollama on a PC or server on your LAN (Local), or add a cloud provider (Cloud) and choose exactly what it may receive.</p></div>
      <SettingsForm section="ai" title="Document Processing" />
      <ProfilesCard />
      <OcrTests />
      <AiJobsCard />
    </div>
  );
}
