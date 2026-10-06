import { useEffect, useState } from "react";
import { api, formatBytes, formatDateTime } from "../api";
import { Confirm, CopyButton, Icon, Modal, Skeleton, useToast } from "./ui";

/** Selective text recognition (OCR): status, chosen sources/pages/languages, results, re-run and removal. */

export interface OcrFile { version: string; number: number; name: string; format: string; page_count: number | null; size: number; current: boolean; additional: boolean; ocr_applied: boolean; ocr_pages: string; ocrable: boolean }
export interface OcrStatus {
  state: string; mode: string; sources: { version: string; pages: string }[]; languages: string[]; default_languages: string[];
  error: string; updated_at: string | null; ai_allowed: boolean; can_run: boolean; can_edit: boolean; paused: boolean;
  job: { status: string } | null; files: OcrFile[];
  results: { version: string; number: number; name: string; pages: string; text: string; quality: any }[];
  languages_available: { code: string; name: string; installed: boolean }[];
}

export const OCR_STATE_LABEL: Record<string, [string, string]> = {
  not_processed: ["Not processed", "neutral"], queued: ["Queued", "neutral"], processing: ["Processing", "neutral"],
  needs_review: ["Needs review", "soon"], confirmed: ["Confirmed", "ok"], failed: ["Failed", "danger"], removed: ["OCR removed", "neutral"],
};
export function OcrStateBadge({ state }: { state: string }) {
  const [label, cls] = OCR_STATE_LABEL[state] || [state, "neutral"];
  return <span className={`badge ${cls}`} title="Text recognition status">OCR: {label}</span>;
}

function ResultText({ text, quality }: { text: string; quality: any }) {
  const low = new Set<number>(quality?.low_lines || []);
  const confidence: number | null = quality?.confidence ?? null;
  const level = confidence === null ? "" : confidence >= 85 ? "ok" : confidence >= 60 ? "soon" : "danger";
  return (
    <div className="stack" style={{ gap: ".4rem" }}>
      <div className="row small">
        {confidence !== null && <span className={`badge ${level}`} title="Mean word confidence reported by the OCR engine">OCR confidence {Math.round(confidence)}%</span>}
        {quality?.rotation ? <span className="badge neutral">Rotated {quality.rotation}°</span> : null}
        {quality?.languages?.length ? <span className="badge neutral">{quality.languages.join(" + ")}</span> : null}
        <CopyButton label="Text" getValue={() => text} />
      </div>
      <pre className="preview-text">{text.split("\n").map((ln, i) => low.has(i) ? <span key={i} className="ocr-low" title="Low confidence">{ln}{"\n"}</span> : <span key={i}>{ln}{"\n"}</span>)}</pre>
    </div>
  );
}

export function OcrRunDialog({ docId, status, onClose, onDone }: { docId: string; status: OcrStatus; onClose: () => void; onDone: (s: OcrStatus) => void }) {
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
        try { onDone(await api<OcrStatus>(`documents/${docId}/ocr`, { body: { sources, languages: langs, rotate: rotate === "auto" ? null : Number(rotate), set_primary: primary } })); }
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
        <fieldset className="field"><legend>Languages</legend>
          <div className="row">{status.languages_available.map((l) => (
            <label key={l.code} className="check" title={l.installed ? "" : "Language pack not installed on the server"}>
              <input type="checkbox" disabled={!l.installed} checked={langs.includes(l.code)} onChange={(e) => setLangs((x) => e.target.checked ? [...x, l.code] : x.filter((y) => y !== l.code))} /> {l.name}{l.installed ? "" : " (not installed)"}
            </label>
          ))}</div>
          <div className="hint">Choose the languages printed on the document; combining several is slower.</div>
        </fieldset>
        {anyImage && (
          <div className="field"><label htmlFor="ocr-rot">Orientation of photos</label>
            <select id="ocr-rot" value={rotate} onChange={(e) => setRotate(e.target.value)} style={{ maxWidth: 260 }}>
              <option value="auto">Detect automatically</option><option value="90">Rotate 90° clockwise</option><option value="180">Rotate 180° (upside down)</option>
              <option value="270">Rotate 90° anticlockwise</option><option value="0">As stored (no rotation)</option>
            </select></div>
        )}
        <label className="check"><input type="checkbox" checked={primary} onChange={(e) => setPrimary(e.target.checked)} /> Use these files as the primary OCR source {status.mode === "automatic" ? "(Automatic OCR processes only this source set)" : ""}</label>
        <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy || !sources.length || !langs.length}>Run OCR</button></div>
      </form>
    </Modal>
  );
}

export default function OcrPanel({ docId, onChanged }: { docId: string; onChanged: () => void }) {
  const toast = useToast();
  const [status, setStatus] = useState<OcrStatus | null>(null);
  const [dialog, setDialog] = useState("");
  const [error, setError] = useState("");
  const load = () => api<OcrStatus>(`documents/${docId}/ocr`).then(setStatus).catch((e) => setError(e.message));
  useEffect(() => { setStatus(null); load(); }, [docId]);
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
          <span className="small muted">Policy: {status.mode === "disabled" ? "OCR disabled for this type" : status.mode === "automatic" ? "Automatic (primary source only)" : "Manual"}</span>
          {status.paused && running && <span className="badge soon">Queue paused by the administrator</span>}
        </div>
        <div className="row">
          {status.can_run && !running && <button className="btn small primary" onClick={() => setDialog("run")}><Icon name="refresh" size={16} /> {status.results.length ? "Re-run OCR…" : "Run OCR…"}</button>}
          {status.can_edit && status.state === "queued" && status.job?.status === "queued" && <button className="btn small" onClick={() => api<OcrStatus>(`documents/${docId}/ocr/cancel`, { method: "POST" }).then((s) => { setStatus(s); toast("OCR cancelled"); }).catch((e) => toast(e.message, "error"))}>Cancel</button>}
          {status.can_edit && status.state === "needs_review" && <button className="btn small" onClick={() => api<OcrStatus>(`documents/${docId}/ocr/reviewed`, { method: "POST" }).then((s) => { setStatus(s); onChanged(); })}>Mark reviewed</button>}
          {status.can_edit && status.results.length > 0 && !running && <button className="btn small danger" onClick={() => setDialog("remove")}>Remove OCR data…</button>}
        </div>
      </div>
      {sourceNames.length > 0 && <p className="small muted">Source: {sourceNames.join(" + ")}{status.languages.length ? ` · ${status.languages.join(" + ")}` : ""}{status.updated_at ? ` · ${formatDateTime(status.updated_at)}` : ""}</p>}
      {status.state === "failed" && <div className="alert error">Text recognition failed: {status.error || "unknown error"}. Try another page range, language or orientation.</div>}
      {running && <div className="alert">Text recognition is {status.state === "queued" ? "waiting in the queue" : "running"}…</div>}
      {status.results.length === 0 && !running && (
        <div className="empty small">{status.mode === "disabled" ? "Text recognition is disabled for this document type." : status.state === "removed" ? "OCR data was removed. The original file is unchanged." : "This document has not been recognised. Choose Run OCR to read selected files or pages."}</div>
      )}
      {status.results.some((r) => r.quality?.low_lines?.length) && <p className="small muted">Greyed lines were read with low confidence and are not used for suggested details.</p>}
      {status.results.map((r) => (
        <div key={r.version}>
          {status.results.length > 1 && <h4 style={{ margin: ".4rem 0" }}>{r.name}{r.pages ? ` · pages ${r.pages}` : ""}</h4>}
          <ResultText text={r.text} quality={r.quality} />
        </div>
      ))}
      {dialog === "run" && <OcrRunDialog docId={docId} status={status} onClose={() => setDialog("")} onDone={(s) => { setStatus(s); setDialog(""); toast("Text recognition queued"); onChanged(); }} />}
      {dialog === "remove" && (
        <Confirm title="Remove OCR data" danger confirmLabel="Remove OCR data" onClose={() => setDialog("")}
          message={<p>The recognised text, its search entries, confidence values and the details suggested from it are deleted, together with the searchable PDF copy. <strong>The original file stays unchanged</strong>, and details you have confirmed are kept. You can run OCR again later.</p>}
          onConfirm={async () => { try { const s = await api<OcrStatus>(`documents/${docId}/ocr`, { method: "DELETE", body: { confirm: true } }); setStatus(s); setDialog(""); toast("OCR data removed"); onChanged(); } catch (x: any) { toast(x.message, "error"); } }} />
      )}
    </div>
  );
}
