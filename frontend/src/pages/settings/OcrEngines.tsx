import { useEffect, useState } from "react";
import { api, formatBytes, formatDateTime } from "../../api";
import { ENGINE_LABEL } from "../../components/OcrPanel";
import { Confirm, HelpTip, Icon, Modal, Skeleton, useToast } from "../../components/ui";

/** Settings → OCR & processing (Change Set Q): engine health, Existing OCR Data (inventory, bulk, orphans) and
 *  Test OCR / Compare Engines. Administrator only; every action is also enforced by the server. */

interface Profile { key: string; label: string; offered: boolean; paddle_models: string[]; paddle_installed: boolean; tesseract_languages: string[] }
interface Engines {
  default_engine: string; fallback: boolean; model: string; device: string; threads: number; memory_mb: number;
  paddle: { installed: boolean; python: string; home: string; paddle: string; paddleocr: string; paddlex: string; cpu_avx: boolean | null; models: string[]; required_models: string[]; missing_models: string[]; selftest: any; healthy: boolean; error: string; checked_at: string | null };
  preprocessing: { orientation: boolean; textline: boolean; unwarping: boolean };
  profiles: Profile[]; tesseract: { version: string; languages: { code: string; name: string; configured: boolean; installed: boolean }[] };
  queue: { queued: number; running: number; concurrency: number; paused: boolean };
  limits: { max_file_mb: number; max_pages: number; timeout_seconds: number }; temp_bytes: number; models_bytes: number;
}

export function OcrEngineStatus() {
  const toast = useToast();
  const [d, setD] = useState<Engines | null>(null);
  const [busy, setBusy] = useState(false);
  const load = (refresh = false) => api<Engines>("ocr/engines", { query: refresh ? { refresh: 1 } : {} }).then(setD).catch((e) => toast(e.message, "error"));
  useEffect(() => { load(); }, []);
  if (!d) return <div className="card"><Skeleton /></div>;
  const p = d.paddle;
  const health = !p.installed ? ["Not installed", "danger"] : p.missing_models.length ? ["Models missing", "danger"] : p.healthy ? ["Healthy", "ok"] : p.selftest ? ["Self-test failed", "danger"] : ["Not tested", "soon"];
  return (
    <section className="card" aria-labelledby="ocr-eng-h">
      <div className="row between"><h2 id="ocr-eng-h">OCR engines <HelpTip text="PaddleOCR (PP-OCRv5) is the preferred engine. Tesseract stays available as Legacy / Fallback. Changing the default engine affects new OCR runs only; existing OCR results are never re-processed automatically." link="/help/ocr-engines#engine" /></h2>
        <span className="row">
          <button className="btn small" onClick={() => load(true)}><Icon name="refresh" size={16} /> Refresh</button>
          <button className="btn small primary" disabled={busy} onClick={async () => {
            setBusy(true);
            try { const r = await api<any>("ocr/engines/selftest", { method: "POST" }); toast(r.healthy ? `Self-test passed in ${r.seconds}s` : `Self-test failed: ${r.message || r.error || "no text recognised"}`, r.healthy ? "ok" : "error"); load(true); }
            catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
          }}>Run self-test</button>
        </span></div>
      <div className="grid-2">
        <div className="stack" style={{ gap: ".3rem" }}>
          <h3 style={{ margin: 0 }}>PaddleOCR (PP-OCRv5) <span className={`badge ${health[1]}`}>{health[0]}</span>{d.default_engine === "paddleocr" && <span className="badge">Default</span>}</h3>
          <div className="small">Versions: PaddlePaddle {p.paddle || "—"} · PaddleOCR {p.paddleocr || "—"} · PaddleX {p.paddlex || "—"}</div>
          <div className="small">Model: {d.model === "server" ? "Server (higher accuracy, slower)" : "Mobile (fast, lower memory)"} · CPU · {d.threads} thread{d.threads > 1 ? "s" : ""} · memory limit {d.memory_mb} MB{p.cpu_avx === false ? " · CPU without AVX" : ""}</div>
          <div className="small">Preprocessing: orientation {d.preprocessing.orientation ? "on" : "off"} · text-line orientation {d.preprocessing.textline ? "on" : "off"} · unwarping {d.preprocessing.unwarping ? "on" : "off"}</div>
          {p.selftest && <div className="small muted">Last self-test (real inference): {p.selftest.healthy ? "passed" : "failed"}{p.selftest.seconds ? ` in ${p.selftest.seconds}s` : ""}{p.selftest.checked_at ? ` · ${formatDateTime(p.selftest.checked_at)}` : ""}</div>}
          {p.missing_models.length > 0 && <div className="alert warn small">Missing models: {p.missing_models.join(", ")}. Run <code>sudo personaldocs ocr install-models</code> on the server.</div>}
          {!p.installed && <div className="alert warn small">The PaddleOCR runtime is not installed. Run <code>sudo personaldocs upgrade</code> (or <code>repair</code>). Until then {d.fallback ? "new OCR uses Tesseract (fallback)" : "OCR with PaddleOCR fails visibly"}.</div>}
          {p.error && <div className="small muted">{p.error}</div>}
          <div className="small muted">Models stored: {formatBytes(d.models_bytes)} · OCR scratch files: {formatBytes(d.temp_bytes)}</div>
        </div>
        <div className="stack" style={{ gap: ".3rem" }}>
          <h3 style={{ margin: 0 }}>Tesseract (Legacy) {d.default_engine === "tesseract" && <span className="badge">Default</span>}</h3>
          <div className="small">{d.tesseract.version ? `Version ${d.tesseract.version}` : "Not installed"} · fallback {d.fallback ? "on" : "off"}</div>
          <div className="small">Language packs: {d.tesseract.languages.filter((l) => l.installed).map((l) => l.code).join(", ") || "none"}</div>
          <div className="small muted">Queue: {d.queue.running} running · {d.queue.queued} waiting · {d.queue.concurrency} at a time{d.queue.paused ? " · paused" : ""}</div>
          <div className="small muted">Limits: {d.limits.max_file_mb} MB · {d.limits.max_pages} pages · {d.limits.timeout_seconds}s per file</div>
        </div>
      </div>
      <h3>Language profiles</h3>
      <div style={{ overflowX: "auto" }}>
        <table className="responsive"><thead><tr><th>Profile</th><th>Offered</th><th>PP-OCRv5 models</th><th>Tesseract (Legacy)</th></tr></thead><tbody>
          {d.profiles.map((pr) => (
            <tr key={pr.key}><td>{pr.label}</td><td>{pr.offered ? "Yes" : "No"}</td>
              <td className="small">{pr.paddle_installed ? <span className="badge ok">Installed</span> : <span className="badge soon">Missing</span>} {pr.paddle_models.join(" + ")}</td>
              <td className="small">{pr.tesseract_languages.join("+")}</td></tr>
          ))}
        </tbody></table>
      </div>
    </section>
  );
}

interface Inventory {
  counts: Record<string, number>; storage: { text: number; blocks: number; searchable: number; chunks: number; total: number };
  orphans: { count: number; bytes: number; items: { key: string; label: string; count: number; bytes: number }[] };
  total: number; page: number;
  documents: { id: string; title: string; owner: string; type: string; folder: string; ocr_state: string; disabled: boolean; engines: string[]; profile: string; ocr_at: string | null; text_chars: number; embedded_text_hidden: boolean }[];
  runs: { id: number; document: string; title: string; engine: string; error: string; created_at: string }[];
}
const ACTIONS: [string, string][] = [["remove", "Remove OCR data"], ["remove_disable", "Remove and disable OCR"], ["disable", "Disable OCR"], ["enable", "Enable OCR"], ["reprocess", "Re-process with PP-OCRv5"], ["set_profile", "Set language profile"]];

export function OcrExistingData() {
  const toast = useToast();
  const [inv, setInv] = useState<Inventory | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({ engine: "any" });
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [bulk, setBulk] = useState<{ action: string; preview: any; all: boolean } | null>(null);
  const [profile, setProfile] = useState("en");
  const [orphans, setOrphans] = useState<any | null>(null);
  const [confirmClean, setConfirmClean] = useState(false);
  const load = () => api<Inventory>("ocr/inventory", { query: { ...filters, page } }).then(setInv).catch((e) => toast(e.message, "error"));
  useEffect(() => { load(); }, [JSON.stringify(filters), page]);
  if (!inv) return <div className="card"><Skeleton /></div>;
  const c = inv.counts;
  const preview = async (action: string, all: boolean) => {
    try {
      const body = all ? { action, filters } : { action, ids: Array.from(sel) };
      setBulk({ action, all, preview: await api("ocr/bulk", { body }) });
    } catch (e: any) { toast(e.message, "error"); }
  };
  const setF = (k: string, v: string) => { setPage(1); setSel(new Set()); setFilters((f) => ({ ...f, [k]: v })); };
  return (
    <section className="card" aria-labelledby="ocr-data-h">
      <h2 id="ocr-data-h">Existing OCR data <HelpTip text="Every document with recognised text, which engine produced it, and the storage it uses. Bulk actions show a preview first and never change originals, versions or confirmed details." link="/help/ocr-engines#existing-data" /></h2>
      <div className="row small" style={{ flexWrap: "wrap" }}>
        <span className="badge">{c.documents_with_ocr} with OCR</span><span className="badge ok">{c.paddleocr} PaddleOCR</span><span className="badge neutral">{c.tesseract} Tesseract</span>
        <span className="badge neutral">{c.unknown} unknown engine</span><span className="badge neutral">{c.indexed} searchable</span><span className="badge neutral">{c.disabled} OCR disabled</span>
        <span className={`badge ${c.failed ? "danger" : "neutral"}`}>{c.failed} failed</span><span className="badge neutral">{c.queued} queued</span>
      </div>
      <p className="small muted">Storage: text {formatBytes(inv.storage.text)} · text blocks {formatBytes(inv.storage.blocks)} · searchable copies {formatBytes(inv.storage.searchable)} · semantic chunks {formatBytes(inv.storage.chunks)} · total {formatBytes(inv.storage.total)}</p>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <select aria-label="Engine filter" value={filters.engine || ""} onChange={(e) => setF("engine", e.target.value)}>
          <option value="any">Any OCR</option><option value="paddleocr">PaddleOCR</option><option value="tesseract">Tesseract</option><option value="unknown">Unknown engine</option><option value="none">No OCR</option><option value="">All documents</option>
        </select>
        <select aria-label="Status filter" value={filters.status || ""} onChange={(e) => setF("status", e.target.value)}>
          <option value="">Any status</option><option value="needs_review">Needs review</option><option value="confirmed">Confirmed</option><option value="failed">Failed</option><option value="removed">Removed</option><option value="disabled">Disabled</option>
        </select>
        <select aria-label="Disabled filter" value={filters.disabled || ""} onChange={(e) => setF("disabled", e.target.value)}>
          <option value="">OCR enabled or disabled</option><option value="1">OCR disabled</option><option value="0">OCR enabled</option>
        </select>
        <label className="small">From <input type="date" value={filters.date_from || ""} onChange={(e) => setF("date_from", e.target.value)} /></label>
        <label className="small">To <input type="date" value={filters.date_to || ""} onChange={(e) => setF("date_to", e.target.value)} /></label>
      </div>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <select aria-label="Bulk action" id="ocr-bulk-action" defaultValue="">
          <option value="" disabled>Bulk action…</option>{ACTIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <button className="btn small" disabled={!sel.size} onClick={() => { const a = (document.getElementById("ocr-bulk-action") as HTMLSelectElement).value; if (a) preview(a, false); else toast("Choose a bulk action", "error"); }}>Preview for {sel.size} selected</button>
        <button className="btn small" disabled={!inv.total} onClick={() => { const a = (document.getElementById("ocr-bulk-action") as HTMLSelectElement).value; if (a) preview(a, true); else toast("Choose a bulk action", "error"); }}>Preview for all {inv.total} matching</button>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="responsive"><thead><tr>
          <th><input type="checkbox" aria-label="Select all on this page" checked={inv.documents.length > 0 && inv.documents.every((d) => sel.has(d.id))} onChange={(e) => setSel(e.target.checked ? new Set(inv.documents.map((d) => d.id)) : new Set())} /></th>
          <th>Document</th><th>Owner</th><th>Engine</th><th>Profile</th><th>Status</th><th>Recognised</th><th>Text</th></tr></thead><tbody>
          {inv.documents.map((d) => (
            <tr key={d.id}>
              <td><input type="checkbox" aria-label={`Select ${d.title}`} checked={sel.has(d.id)} onChange={(e) => setSel((s) => { const n = new Set(s); e.target.checked ? n.add(d.id) : n.delete(d.id); return n; })} /></td>
              <td><a href={`/documents/${d.id}`}>{d.title}</a><div className="small muted">{[d.type, d.folder].filter(Boolean).join(" · ")}</div></td>
              <td className="small">{d.owner}</td>
              <td className="small">{d.engines.map((e) => ENGINE_LABEL[e] || e).join(", ") || "—"}</td>
              <td className="small">{d.profile || "—"}</td>
              <td className="small">{d.ocr_state}{d.disabled ? " · OCR disabled" : ""}{d.embedded_text_hidden ? " · embedded text hidden" : ""}</td>
              <td className="small">{d.ocr_at ? formatDateTime(d.ocr_at) : "—"}</td>
              <td className="small">{d.text_chars.toLocaleString()} chars</td>
            </tr>
          ))}
          {!inv.documents.length && <tr><td colSpan={8} className="small muted">No documents match.</td></tr>}
        </tbody></table>
      </div>
      {inv.total > 50 && <div className="row small"><button className="btn small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page} of {Math.ceil(inv.total / 50)}</span><button className="btn small" disabled={page * 50 >= inv.total} onClick={() => setPage(page + 1)}>Next</button></div>}
      {inv.runs.length > 0 && <details><summary className="small">Failed OCR runs ({inv.runs.length})</summary><ul className="small">{inv.runs.map((r) => <li key={r.id}><a href={`/documents/${r.document}`}>{r.title}</a> · {ENGINE_LABEL[r.engine] || r.engine} · {formatDateTime(r.created_at)} · {r.error}</li>)}</ul></details>}

      <h3>Orphaned OCR data <HelpTip text="Derived OCR files and records that no document refers to any more. Analyze is a dry run; Clean removes only what the analysis lists, never originals, versions, confirmed details, previews or running jobs." link="/help/ocr-engines#orphans" /></h3>
      <p className="small">{inv.orphans.count ? `${inv.orphans.count} item(s), ${formatBytes(inv.orphans.bytes)} reclaimable.` : "No orphaned OCR data found."}</p>
      <div className="row">
        <button className="btn small" onClick={() => api("ocr/orphans").then(setOrphans).catch((e) => toast(e.message, "error"))}>Analyze (dry run)</button>
        {orphans && orphans.count > 0 && <button className="btn small danger" onClick={() => setConfirmClean(true)}>Clean {orphans.count} item(s)…</button>}
      </div>
      {orphans && (
        <ul className="small">{orphans.items.map((i: any) => <li key={i.key}>{i.label}: {i.count}{i.bytes ? ` · ${formatBytes(i.bytes)}` : ""}</li>)}
          <li className="muted">Never touched: {(orphans.never || []).join(", ")}</li></ul>
      )}
      {confirmClean && <Confirm title="Clean orphaned OCR data" danger confirmLabel="Clean" onClose={() => setConfirmClean(false)}
        message={<p>Removes the {orphans.count} item(s) listed by the dry run ({formatBytes(orphans.bytes)}). Originals, versions, confirmed details, previews and running jobs are not touched.</p>}
        onConfirm={async () => { try { const r = await api<any>("ocr/orphans", { body: { confirm: true } }); toast(`Removed ${r.removed} item(s), ${formatBytes(r.bytes)} freed`); setOrphans(null); setConfirmClean(false); load(); } catch (e: any) { toast(e.message, "error"); } }} />}

      {bulk && (
        <Modal title={ACTIONS.find(([k]) => k === bulk.action)?.[1] || "Bulk action"} onClose={() => setBulk(null)}>
          <div className="stack">
            <p><strong>{bulk.preview.affected}</strong> document(s) affected · {bulk.preview.with_ocr} have OCR text{bulk.preview.reclaimable_bytes ? ` · about ${formatBytes(bulk.preview.reclaimable_bytes)} reclaimed` : ""}.</p>
            <div className="alert warn small">{bulk.preview.warning}</div>
            <p className="small">Kept: {bulk.preview.kept.join(", ")}.</p>
            {bulk.action === "set_profile" && <div className="field"><label htmlFor="bulk-prof">Language profile</label><select id="bulk-prof" value={profile} onChange={(e) => setProfile(e.target.value)}>
              {[["en", "English"], ["ar_en", "Arabic + English"], ["hi_en", "Hindi (Devanagari) + English"], ["te_en", "Telugu + English"], ["ta_en", "Tamil + English"]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>}
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setBulk(null)}>Cancel</button>
              <button className={`btn ${bulk.action.startsWith("remove") ? "danger" : "primary"}`} disabled={!bulk.preview.affected} onClick={async () => {
                try {
                  const body: any = { action: bulk.action, confirm: true, profile, ...(bulk.all ? { filters } : { ids: Array.from(sel) }) };
                  const r = await api<any>("ocr/bulk", { body });
                  toast(`${r.queued} document(s) queued`); setBulk(null); setSel(new Set()); setTimeout(load, 1500);
                } catch (e: any) { toast(e.message, "error"); }
              }}>Confirm for {bulk.preview.affected} document(s)</button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  );
}

export function OcrTest() {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [profile, setProfile] = useState("en");
  const [compare, setCompare] = useState(false);
  const [expected, setExpected] = useState("");
  const [pages, setPages] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any | null>(null);
  return (
    <section className="card" aria-labelledby="ocr-test-h">
      <h2 id="ocr-test-h">Test OCR / Compare engines <HelpTip text="Use a sanitised sample (never a real passport or ID). The file is processed locally and deleted afterwards; it is not added to the library." link="/help/ocr-engines#test" /></h2>
      <form className="stack" onSubmit={async (e) => {
        e.preventDefault();
        if (!file) return;
        const form = new FormData();
        form.append("file", file);
        form.append("engines", compare ? "paddleocr,tesseract" : "paddleocr");
        form.append("profile", profile);
        if (expected.trim()) form.append("expected", expected);
        if (pages.trim()) form.append("pages", pages);
        setBusy(true);
        setRes(null);
        try { setRes(await api("ocr/test", { method: "POST", form })); } catch (x: any) { toast(x.message, "error"); } finally { setBusy(false); }
      }}>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <input type="file" aria-label="Test file" accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          <select aria-label="Test profile" value={profile} onChange={(e) => setProfile(e.target.value)}>
            {[["en", "English"], ["ar_en", "Arabic + English"], ["hi_en", "Hindi (Devanagari) + English"], ["te_en", "Telugu + English"], ["ta_en", "Tamil + English"]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <input type="text" aria-label="Pages" placeholder="Pages (PDF), e.g. 1-2" value={pages} onChange={(e) => setPages(e.target.value)} style={{ maxWidth: 180 }} />
          <label className="check"><input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} /> Compare with Tesseract (Legacy)</label>
        </div>
        <textarea aria-label="Expected text" rows={2} placeholder="Expected text (optional) — gives a character accuracy for each engine" value={expected} onChange={(e) => setExpected(e.target.value)} />
        <div><button className="btn primary" disabled={!file || busy}>{busy ? "Recognising…" : compare ? "Compare engines" : "Test OCR"}</button></div>
      </form>
      {res && (
        <div className="stack">
          <p className="small muted">{res.note} Temporary files removed: {res.artifacts_removed ? "yes" : "no"}.</p>
          <div className={res.results.length > 1 ? "grid-2" : ""}>
            {res.results.map((r: any) => (
              <div key={r.engine} className="stack" style={{ gap: ".3rem" }}>
                <h3 style={{ margin: 0 }}>{r.label}</h3>
                {r.ok ? <>
                  <div className="small">{r.model} · {r.seconds}s · {r.line_count} lines · {r.low_confidence_lines} low-confidence{r.mean_score != null ? ` · mean score ${r.mean_score}` : ""}{r.accuracy != null ? ` · accuracy ${r.accuracy}%` : ""}{r.has_geometry ? " · text positions" : ""}</div>
                  <pre className="preview-text" style={{ maxHeight: 300 }}>{r.text}</pre>
                </> : <div className="alert error small">{r.error}</div>}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
