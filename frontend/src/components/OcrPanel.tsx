import { useEffect, useState } from "react";
import { api, formatBytes, formatDateTime } from "../api";
import { Confirm, CopyButton, Icon, Modal, Skeleton, useToast } from "./ui";

/** Selective text recognition (OCR): status, chosen sources/pages/languages, results, re-run and removal. */

export interface OcrFile { version: string; number: number; name: string; format: string; page_count: number | null; size: number; current: boolean; additional: boolean; ocr_applied: boolean; ocr_pages: string; ocrable: boolean }
export interface OcrResult {
  version: string; number: number; name: string; pages: string; text: string; quality: any;
  engine: string; engine_label: string; model: string; profile: string; ocr_at: string | null;
}
export interface OcrStatus {
  state: string; mode: string; sources: { version: string; pages: string }[]; languages: string[]; default_languages: string[];
  error: string; updated_at: string | null; ai_allowed: boolean; can_run: boolean; can_edit: boolean; paused: boolean;
  job: { status: string } | null; files: OcrFile[]; results: OcrResult[];
  languages_available: { code: string; name: string; installed: boolean }[];
  override: string; profile: string; default_profile: string; embedded_text_hidden: boolean; embedded_text: boolean;
  type_mode: string; profiles: { key: string; label: string }[]; engine_default: string;
}

export const PROFILE_LABEL: Record<string, string> = { en: "English", ar_en: "Arabic + English", hi_en: "Hindi (Devanagari) + English", te_en: "Telugu + English", ta_en: "Tamil + English" };
export const ENGINE_LABEL: Record<string, string> = { paddleocr: "PaddleOCR (PP-OCRv5)", tesseract: "Tesseract (Legacy)", unknown: "Unknown (earlier version)" };
export function EngineBadge({ engine }: { engine: string }) {
  return <span className={`badge ${engine === "paddleocr" ? "ok" : "neutral"}`} title="OCR engine that produced this text">{ENGINE_LABEL[engine] || engine}</span>;
}

export const OCR_STATE_LABEL: Record<string, [string, string]> = {
  not_processed: ["Not processed", "neutral"], queued: ["Queued", "neutral"], processing: ["Processing", "neutral"],
  needs_review: ["Needs review", "soon"], confirmed: ["Confirmed", "ok"], failed: ["Failed", "danger"], removed: ["OCR removed", "neutral"], disabled: ["Disabled", "neutral"],
};
export function OcrStateBadge({ state }: { state: string }) {
  const [label, cls] = OCR_STATE_LABEL[state] || [state, "neutral"];
  return <span className={`badge ${cls}`} title="Text recognition status">OCR: {label}</span>;
}

function ResultText({ text, quality, result }: { text: string; quality: any; result?: OcrResult }) {
  const low = new Set<number>(quality?.low_lines || []);
  const confidence: number | null = quality?.confidence ?? null;
  const level = confidence === null ? "" : confidence >= 85 ? "ok" : confidence >= 60 ? "soon" : "danger";
  return (
    <div className="stack" style={{ gap: ".4rem" }}>
      <div className="row small" style={{ flexWrap: "wrap" }}>
        {result && <EngineBadge engine={result.engine} />}
        {result?.profile && result.engine === "paddleocr" && <span className="badge neutral" title="Language profile">{PROFILE_LABEL[result.profile] || result.profile}</span>}
        {result?.model && <span className="small muted" title="Recognition model">{result.model}</span>}
        {result?.ocr_at && <span className="small muted">{formatDateTime(result.ocr_at)}</span>}
        {confidence !== null && <span className={`badge ${level}`} title="Mean word confidence reported by the OCR engine">OCR confidence {Math.round(confidence)}%</span>}
        {quality?.rotation ? <span className="badge neutral">Rotated {quality.rotation}°</span> : null}
        {result?.engine !== "paddleocr" && quality?.languages?.length ? <span className="badge neutral" title="Tesseract languages">{quality.languages.join(" + ")}</span> : null}
        <CopyButton label="Text" getValue={() => text} />
      </div>
      <pre className="preview-text">{text.split("\n").map((ln, i) => low.has(i) ? <span key={i} className="ocr-low" title="Low confidence">{ln}{"\n"}</span> : <span key={i}>{ln}{"\n"}</span>)}</pre>
    </div>
  );
}

export function OcrRunDialog({ docId, status, onClose, onDone }: { docId: string; status: OcrStatus; onClose: () => void; onDone: (s: OcrStatus) => void }) {
  const [engine, setEngine] = useState<string>(status.engine_default || "paddleocr");
  const [profile, setProfile] = useState<string>(status.profile || status.default_profile || "en");
  const rerun = status.results.length > 0;
  const ocrable = status.files.filter((f) => f.ocrable);
  const initial = status.sources.length ? status.sources : ocrable.filter((f) => f.current).map((f) => ({ version: f.version, pages: "" }));
  const [chosen, setChosen] = useState<Record<string, { on: boolean; pages: string }>>(() =>
    Object.fromEntries(ocrable.map((f) => { const s = initial.find((x) => x.version === f.version); return [f.version, { on: !!s, pages: s?.pages || "" }]; })));
  const [langs, setLangs] = useState<string[]>(status.languages.length ? status.languages : status.default_languages);
  const [rotate, setRotate] = useState("auto");
  const [primary, setPrimary] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const sources = Object.entries(chosen).filter(([, c]) => c.on).map(([version, c]) => ({ version, pages: c.pages.trim() }));
  const anyImage = sources.some((s) => ocrable.find((f) => f.version === s.version)?.format === "image");
  return (
    <Modal title="Text recognition (OCR)" onClose={onClose}>
      <form className="stack" onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setErr("");
        const body: any = { sources, rotate: rotate === "auto" ? null : Number(rotate), set_primary: primary, reprocess: rerun };
        // the default engine is not sent, so the server may fall back to Tesseract when PaddleOCR is unavailable;
        // an engine the person picked explicitly is sent and never silently replaced
        if (engine !== status.engine_default) body.engine = engine;
        if (engine === "paddleocr") body.profile = profile; else body.languages = langs;
        try { onDone(await api<OcrStatus>(`documents/${docId}/ocr`, { body })); }
        catch (x: any) { setErr(x.message); }
        finally { setBusy(false); }
      }}>
        {err && <div className="alert error" role="alert">{err}</div>}
        <p className="small">Only the files and pages you choose are recognised. The original files are never changed. Confirmed details are kept; a different reading is shown next to them for you to decide.</p>
        <fieldset className="field"><legend>Source files</legend>
          {ocrable.length === 0 && <p className="small muted">This document has no scan or image that can be recognised.</p>}
          {ocrable.map((f) => (
            <div key={f.version} className="row" style={{ alignItems: "center", flexWrap: "wrap" }}>
              <label className="check grow"><input type="checkbox" checked={chosen[f.version]?.on || false} onChange={(e) => setChosen((c) => ({ ...c, [f.version]: { ...c[f.version], on: e.target.checked } }))} />
                {" "}{f.name} <span className="small muted">v{f.number}{f.current ? " · current" : ""}{f.additional ? " · additional side/copy" : ""}{f.page_count ? ` · ${f.page_count} page${f.page_count > 1 ? "s" : ""}` : ""} · {formatBytes(f.size)}</span></label>
              {f.format === "pdf" && chosen[f.version]?.on && (
                <input type="text" aria-label={`Pages of ${f.name}`} placeholder="All pages (or e.g. 1-2, 5)" value={chosen[f.version].pages} style={{ maxWidth: 200 }}
                  onChange={(e) => setChosen((c) => ({ ...c, [f.version]: { ...c[f.version], pages: e.target.value } }))} />
              )}
            </div>
          ))}
        </fieldset>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <div className="field grow"><label htmlFor="ocr-engine">OCR engine</label>
            <select id="ocr-engine" value={engine} onChange={(e) => setEngine(e.target.value)}>
              <option value="paddleocr">PaddleOCR (PP-OCRv5) — recommended</option><option value="tesseract">Tesseract (Legacy)</option>
            </select></div>
          {engine === "paddleocr" && (
            <div className="field grow"><label htmlFor="ocr-profile">Language profile</label>
              <select id="ocr-profile" value={profile} onChange={(e) => setProfile(e.target.value)}>
                {status.profiles.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
              </select></div>
          )}
        </div>
        {rerun && <p className="small muted">Re-running replaces the current OCR text only after the new run succeeds; if it fails, the previous result stays.</p>}
        {engine === "tesseract" && <fieldset className="field"><legend>Languages (Tesseract)</legend>
          <div className="row">{status.languages_available.map((l) => (
            <label key={l.code} className="check" title={l.installed ? "" : "Language pack not installed on the server"}>
              <input type="checkbox" disabled={!l.installed} checked={langs.includes(l.code)} onChange={(e) => setLangs((x) => e.target.checked ? [...x, l.code] : x.filter((y) => y !== l.code))} /> {l.name}{l.installed ? "" : " (not installed)"}
            </label>
          ))}</div>
          <div className="hint">Choose the languages printed on the document; combining several is slower.</div>
        </fieldset>}
        {anyImage && (
          <div className="field"><label htmlFor="ocr-rot">Orientation of photos</label>
            <select id="ocr-rot" value={rotate} onChange={(e) => setRotate(e.target.value)} style={{ maxWidth: 260 }}>
              <option value="auto">Detect automatically</option><option value="90">Rotate 90° clockwise</option><option value="180">Rotate 180° (upside down)</option>
              <option value="270">Rotate 90° anticlockwise</option><option value="0">As stored (no rotation)</option>
            </select></div>
        )}
        <label className="check"><input type="checkbox" checked={primary} onChange={(e) => setPrimary(e.target.checked)} /> Use these files as the primary OCR source {status.mode === "automatic" ? "(Automatic OCR processes only this source set)" : ""}</label>
        <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy || !sources.length || (engine === "tesseract" && !langs.length)}>{rerun ? "Re-run OCR" : "Run OCR"}</button></div>
      </form>
    </Modal>
  );
}

function RemoveDialog({ docId, status, onClose, onDone }: { docId: string; status: OcrStatus; onClose: () => void; onDone: (s: OcrStatus, freed: number) => void }) {
  const [embedded, setEmbedded] = useState(false);
  const [disable, setDisable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const engines = Array.from(new Set(status.results.map((r) => ENGINE_LABEL[r.engine] || r.engine)));
  return (
    <Modal title="Remove OCR data" onClose={onClose}>
      <div className="stack">
        {err && <div className="alert error" role="alert">{err}</div>}
        <p>Deleted: the recognised text{engines.length ? ` from ${engines.join(" and ")}` : ""}, text positions and confidence values, the searchable PDF copy, search-index entries built from them, unconfirmed suggested details, Local AI suggestions and semantic-search data from this text, and queued Local AI work.</p>
        <p><strong>Kept:</strong> the original file and every version, the title, type, owner, folder, permissions, notes, tags, manually entered and confirmed details (raw OCR excerpts next to them are cleared), and the audit history.</p>
        {(status.embedded_text || status.results.length > 0) && (
          <label className="check"><input type="checkbox" checked={embedded} onChange={(e) => setEmbedded(e.target.checked)} /> Also hide the text layer embedded in the file (from the scanner or an earlier OCR program). The file itself is not changed.</label>
        )}
        <label className="check"><input type="checkbox" checked={disable} onChange={(e) => setDisable(e.target.checked)} /> Also disable OCR for this document (Automatic OCR, Regenerate preview, repairs and bulk re-processing will not recognise it again)</label>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn danger" disabled={busy} onClick={async () => {
            setBusy(true);
            try { const r = await api<OcrStatus & { bytes_freed: number }>(`documents/${docId}/ocr`, { method: "DELETE", body: { confirm: true, include_embedded: embedded, disable } }); onDone(r, r.bytes_freed || 0); }
            catch (x: any) { setErr(x.message); } finally { setBusy(false); }
          }}>Remove OCR data</button>
        </div>
      </div>
    </Modal>
  );
}

function DisableDialog({ docId, status, onClose, onDone }: { docId: string; status: OcrStatus; onClose: () => void; onDone: (s: OcrStatus) => void }) {
  const [removeExisting, setRemoveExisting] = useState(false);
  const [err, setErr] = useState("");
  const has = status.results.length > 0;
  return (
    <Modal title="Disable OCR for this document" onClose={onClose}>
      <div className="stack">
        {err && <div className="alert error" role="alert">{err}</div>}
        <p>No new text recognition runs for this document — not from an Automatic document type, Regenerate preview, a repair or a bulk action — until you enable it again. The original file is not changed.</p>
        {has && (
          <fieldset className="field"><legend>Existing OCR data</legend>
            <label className="check"><input type="radio" name="dis-keep" checked={!removeExisting} onChange={() => setRemoveExisting(false)} /> Keep the existing OCR text (it stays searchable)</label>
            <label className="check"><input type="radio" name="dis-keep" checked={removeExisting} onChange={() => setRemoveExisting(true)} /> Remove the existing OCR data too</label>
          </fieldset>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn danger" onClick={() => api<OcrStatus>(`documents/${docId}/ocr/mode`, { body: { disabled: true, remove_existing: removeExisting } }).then(onDone).catch((x) => setErr(x.message))}>Disable OCR</button>
        </div>
      </div>
    </Modal>
  );
}

export default function OcrPanel({ docId, onChanged, request }: { docId: string; onChanged: () => void; request?: { action: string; n: number } }) {
  const toast = useToast();
  const [status, setStatus] = useState<OcrStatus | null>(null);
  const [dialog, setDialog] = useState("");
  const [error, setError] = useState("");
  const load = () => api<OcrStatus>(`documents/${docId}/ocr`).then(setStatus).catch((e) => setError(e.message));
  useEffect(() => { setStatus(null); load(); }, [docId]);
  useEffect(() => { if (request && request.action !== "view") setDialog(request.action); }, [request?.n]);
  const enable = () => api<OcrStatus>(`documents/${docId}/ocr/mode`, { body: { disabled: false } }).then((s) => { setStatus(s); toast("OCR enabled for this document"); onChanged(); }).catch((e) => toast(e.message, "error"));
  useEffect(() => {
    if (!status || !["queued", "processing"].includes(status.state)) return;
    const t = setTimeout(load, 3000);
    return () => clearTimeout(t);
  }, [status]);
  if (error) return <div className="alert error">{error}</div>;
  if (!status) return <Skeleton />;
  const running = ["queued", "processing"].includes(status.state);
  const sourceNames = status.sources.map((s) => { const f = status.files.find((x) => x.version === s.version); return f ? `${f.name}${s.pages ? ` (pages ${s.pages})` : ""}` : null; }).filter(Boolean);
  return (
    <div className="stack ocr-panel">
      <div className="row between">
        <div className="row">
          <OcrStateBadge state={status.state} />
          <span className="small muted">Policy: {status.override === "disabled" ? "OCR disabled for this document" : status.mode === "disabled" ? "OCR disabled for this type" : status.mode === "automatic" ? "Automatic (primary source only)" : "Manual"}</span>
          {status.embedded_text_hidden && <span className="badge neutral" title="The text layer embedded in the file is not used for search">Embedded text hidden</span>}
          {status.paused && running && <span className="badge soon">Queue paused by the administrator</span>}
        </div>
        <div className="row">
          {status.can_run && !running && <button className="btn small primary" onClick={() => setDialog("run")}><Icon name="refresh" size={16} /> {status.results.length ? "Re-run OCR…" : "Run OCR…"}</button>}
          {status.can_edit && status.state === "queued" && status.job?.status === "queued" && <button className="btn small" onClick={() => api<OcrStatus>(`documents/${docId}/ocr/cancel`, { method: "POST" }).then((s) => { setStatus(s); toast("OCR cancelled"); }).catch((e) => toast(e.message, "error"))}>Cancel</button>}
          {status.can_edit && status.state === "needs_review" && <button className="btn small" onClick={() => api<OcrStatus>(`documents/${docId}/ocr/reviewed`, { method: "POST" }).then((s) => { setStatus(s); onChanged(); })}>Mark reviewed</button>}
          {status.can_edit && (status.results.length > 0 || status.embedded_text) && !running && <button className="btn small danger" onClick={() => setDialog("remove")}>Remove OCR data…</button>}
          {status.can_edit && status.override !== "disabled" && !running && <button className="btn small" onClick={() => setDialog("disable")}>Disable OCR for this document…</button>}
          {status.can_edit && status.override === "disabled" && <button className="btn small" onClick={enable}>Enable OCR for this document</button>}
        </div>
      </div>
      {sourceNames.length > 0 && <p className="small muted">Source: {sourceNames.join(" + ")}{status.results.some((r) => r.engine === "paddleocr") && status.profile ? ` · ${PROFILE_LABEL[status.profile] || status.profile}` : status.languages.length ? ` · ${status.languages.join(" + ")}` : ""}{status.updated_at ? ` · ${formatDateTime(status.updated_at)}` : ""}</p>}
      {status.state === "failed" && <div className="alert error">Text recognition failed: {status.error || "unknown error"}. Try another page range, language or orientation.</div>}
      {running && <div className="alert">Text recognition is {status.state === "queued" ? "waiting in the queue" : "running"}…</div>}
      {status.results.length === 0 && !running && (
        <div className="empty small">{status.override === "disabled" ? "Text recognition is disabled for this document." : status.mode === "disabled" ? "Text recognition is disabled for this document type." : status.state === "removed" ? "OCR data was removed. The original file is unchanged." : "This document has not been recognised. Choose Run OCR to read selected files or pages."}</div>
      )}
      {status.results.some((r) => r.quality?.low_lines?.length) && <p className="small muted">Greyed lines were read with low confidence and are not used for suggested details.</p>}
      {status.results.map((r) => (
        <div key={r.version}>
          {status.results.length > 1 && <h4 style={{ margin: ".4rem 0" }}>{r.name}{r.pages ? ` · pages ${r.pages}` : ""}</h4>}
          <ResultText text={r.text} quality={r.quality} result={r} />
        </div>
      ))}
      {dialog === "run" && !status.can_run && <Confirm title="Text recognition is disabled" message={<p>{status.override === "disabled" ? "OCR is disabled for this document. Enable it first." : "OCR is disabled for this document type or globally."}</p>} confirmLabel="OK" onConfirm={() => setDialog("")} onClose={() => setDialog("")} />}
      {dialog === "run" && status.can_run && <OcrRunDialog docId={docId} status={status} onClose={() => setDialog("")} onDone={(s) => { setStatus(s); setDialog(""); toast("Text recognition queued"); onChanged(); }} />}
      {dialog === "remove" && <RemoveDialog docId={docId} status={status} onClose={() => setDialog("")} onDone={(s, freed) => { setStatus(s); setDialog(""); toast(`OCR data removed${freed ? ` · ${formatBytes(freed)} freed` : ""}`); onChanged(); }} />}
      {dialog === "disable" && <DisableDialog docId={docId} status={status} onClose={() => setDialog("")} onDone={(s) => { setStatus(s); setDialog(""); toast("OCR disabled for this document"); onChanged(); }} />}
    </div>
  );
}
