import { useState } from "react";
import { Link } from "react-router-dom";
import { api, formatDateTime } from "../../api";
import { resetAiStatus } from "../../ai";
import SettingsForm from "../../components/SettingsForm";
import { HelpTip, Icon, Modal, Skeleton, useAsync, useToast } from "../../components/ui";

type Profile = {
  id?: number; name: string; enabled: boolean; is_default: boolean; provider: "openai" | "ollama"; base_url: string; api_key_configured?: boolean;
  text_model: string; vision_model: string; embedding_model: string; timeout_seconds: number; max_input_chars: number; max_output_tokens: number;
  privacy: "local" | "lan" | "external"; external_acknowledged: boolean; features: string[];
};

const BLANK: Profile = { name: "", enabled: true, is_default: false, provider: "openai", base_url: "http://192.168.1.50:1234/v1", text_model: "", vision_model: "",
  embedding_model: "", timeout_seconds: 60, max_input_chars: 12000, max_output_tokens: 800, privacy: "lan", external_acknowledged: false, features: [] };
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
          <div className="field"><label htmlFor="ai-prov">Connection type</label><select id="ai-prov" value={p.provider} onChange={(e) => set("provider", e.target.value)}>
            <option value="openai">OpenAI-compatible (LM Studio, llama.cpp, vLLM, LocalAI)</option><option value="ollama">Ollama</option></select></div>
          <div className="field"><label htmlFor="ai-url">Server URL</label><input id="ai-url" type="url" required value={p.base_url} onChange={(e) => set("base_url", e.target.value)} />
            <div className="hint">{p.provider === "ollama" ? "e.g. http://192.168.1.50:11434" : "e.g. http://192.168.1.50:1234/v1 (LM Studio)"}</div></div>
          <div className="field"><label htmlFor="ai-key">API key (optional)</label><input id="ai-key" type="password" autoComplete="new-password" value={p.api_key || ""} onChange={(e) => set("api_key", e.target.value)} placeholder={p.api_key_configured ? "•••••• stored (leave empty to keep)" : "Not needed for most local servers"} />
            {p.api_key_configured && <label className="check small"><input type="checkbox" checked={!!p.clear_api_key} onChange={(e) => set("clear_api_key", e.target.checked)} /> Remove stored key</label>}</div>
        </div>
        <datalist id="ai-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
          {[["text_model", "Text model", "Answers questions and suggests metadata"], ["vision_model", "Vision model (optional)", "Reads images when a scan has no OCR text"], ["embedding_model", "Embedding model", "Needed for semantic search"]].map(([k, l, h]) => (
            <div className="field" key={k}><label htmlFor={`ai-${k}`}>{l}</label><input id={`ai-${k}`} type="text" list="ai-models" value={(p as any)[k]} onChange={(e) => set(k, e.target.value)} /><div className="hint">{h}</div></div>
          ))}
        </div>
        {p.id && <div><button type="button" className="btn small" onClick={discover}><Icon name="search" size={16} /> Discover models on the server</button></div>}
        <fieldset className="field"><legend>Privacy classification <HelpTip text="Checked on every request against the server's real address. A LAN profile that points outside your network is refused and no text is sent." link="/help/local-ai#privacy" /></legend>
          {PRIVACY.map(([k, l, d]) => <label key={k} className="check"><input type="radio" name="ai-privacy" checked={p.privacy === k} onChange={() => set("privacy", k)} /> <strong>{l}</strong> — <span className="small">{d}</span></label>)}
        </fieldset>
        {p.privacy === "external" && (
          <div className="alert danger"><strong>Warning:</strong> with an external endpoint, OCR text, titles and questions about your documents are sent outside your home network to that server.
            <label className="check"><input type="checkbox" checked={p.external_acknowledged} onChange={(e) => set("external_acknowledged", e.target.checked)} /> I understand that selected document content may leave the local network.</label></div>
        )}
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

function ProfilesCard() {
  const list = useAsync(() => api<{ profiles: Profile[] }>("ai/profiles"), []);
  const [edit, setEdit] = useState<Profile | null>(null);
  const [results, setResults] = useState<Record<number, any>>({});
  const test = (p: Profile) => api<any>(`ai/profiles/${p.id}/test`, { method: "POST" })
    .then((r) => setResults({ ...results, [p.id!]: r }))
    .catch((e) => setResults({ ...results, [p.id!]: { error: e.message, ...(e.data || {}) } }));
  if (!list.data) return <Skeleton />;
  return (
    <div className="card">
      <h2>AI profiles <HelpTip text="A profile is one AI server connection. The default profile serves the features; there is never a fallback to another server or to the cloud." link="/help/local-ai#profiles" /></h2>
      {list.data.profiles.length === 0 && <p className="small muted">No AI server configured yet. Add an LM Studio, Ollama or other OpenAI-compatible server running on your network.</p>}
      {list.data.profiles.map((p) => {
        const r = results[p.id!];
        return (
          <div key={p.id} className="list-item" style={{ alignItems: "flex-start" }}>
            <div className="grow">
              <strong>{p.name}</strong> {p.is_default && <span className="badge ok">default</span>} {!p.enabled && <span className="badge neutral">disabled</span>}
              <span className={`badge ${p.privacy === "external" ? "danger" : "neutral"}`}>{PRIVACY.find((x) => x[0] === p.privacy)?.[1]}</span>
              <div className="small muted">{p.provider === "ollama" ? "Ollama" : "OpenAI-compatible"} · {p.base_url} · text: {p.text_model || "—"} · embeddings: {p.embedding_model || "—"}</div>
              {r && (r.error ? <div className="small error-text">{r.error}</div> : <div className="small">✓ Connected ({r.privacy_actual}, {r.latency_ms} ms) · {r.models?.length || 0} models{r.missing_models?.length ? ` · missing: ${r.missing_models.join(", ")}` : ""}{r.chat_ok ? " · chat OK" : ""}{r.embedding_dimensions ? ` · embeddings ${r.embedding_dimensions}-d` : ""}</div>)}
            </div>
            <div className="row" style={{ gap: ".3rem" }}>
              <button className="btn small" onClick={() => test(p)}>Test connection</button>
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
        {jobs.data.jobs.slice(0, 30).map((j: any) => <tr key={j.id}><td>{j.kind}{j.document && <div className="small"><Link to={`/documents/${j.document}`}>document</Link></div>}</td><td className="small">{j.requested_by || "—"}</td>
          <td className="small">{j.profile ? `${j.profile} · ${j.model}` : "—"}</td>
          <td><span className={`badge ${j.status === "failed" ? "danger" : j.status === "done" ? "ok" : "neutral"}`}>{j.status}</span>{j.error && <div className="small error-text">{j.error_category}: {j.error}</div>}</td>
          <td className="small">{formatDateTime(j.finished_at || j.created_at)}</td></tr>)}
      </tbody></table>
      <button className="btn small" onClick={() => api<any>("ai/reindex", { method: "POST" }).then((r) => toast(`${r.queued} documents queued for the semantic index`)).catch((e) => toast(e.message, "error"))}>Rebuild semantic index</button>
    </div>
  );
}

export default function LocalAIPanel() {
  return (
    <div className="stack">
      <div className="card"><p>Local AI is optional. Uploads, OCR, search, reminders and sharing work the same without it. AI only <strong>suggests</strong> metadata — nothing changes until a person accepts it — and the assistant only sees documents the asking person may open. <Link to="/help/local-ai">Local AI guide</Link></p>
        <p className="small muted">A 2-CPU / 4 GB container cannot run useful models itself: run LM Studio or Ollama on a PC or server on your LAN and connect it here.</p></div>
      <SettingsForm section="ai" title="Features" />
      <ProfilesCard />
      <AiJobsCard />
    </div>
  );
}
