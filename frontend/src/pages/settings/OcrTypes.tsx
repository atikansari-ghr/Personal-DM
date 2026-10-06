import { useEffect, useState } from "react";
import { api } from "../../api";
import { HelpTip, Icon, Modal, Skeleton, useToast } from "../../components/ui";

/** Settings → OCR & processing: OCR policy per document type (Disabled / Manual / Automatic), languages, AI. */

interface OcrType { id: number; name: string; template: string; emoji: string; ocr_mode: string; ocr_languages: string[]; ocr_fields: string[]; ocr_ai_allowed: boolean; is_custom: boolean; archived: boolean; documents: number }
interface Lang { code: string; name: string; configured: boolean; installed: boolean }

const FIELD_LABELS: Record<string, string> = {
  full_name: "Name", document_number: "Number", issue_date: "Issue date", expiry_date: "Expiry date", no_expiry: "No expiry",
  date_of_birth: "Date of birth", nationality: "Nationality", issuer: "Issuer", country_code: "Country", sex: "Sex", place_of_issue: "Place of issue",
};
const MODES: [string, string][] = [["disabled", "Disabled"], ["manual", "Manual"], ["automatic", "Automatic"]];

export default function OcrTypes() {
  const toast = useToast();
  const [data, setData] = useState<{ types: OcrType[]; templates: string[]; fields: string[]; template_fields: Record<string, string[]>; languages: Lang[] } | null>(null);
  const [edit, setEdit] = useState<OcrType | null>(null);
  const [adding, setAdding] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const load = () => api<any>("ocr/types").then(setData);
  useEffect(() => { load(); }, []);
  if (!data) return <div className="card"><Skeleton /></div>;
  const langs = data.languages.filter((l) => l.configured);
  const missing = langs.filter((l) => !l.installed);
  const patch = async (t: OcrType, body: Partial<OcrType>) => {
    try { await api(`ocr/types/${t.id}`, { method: "PATCH", body }); load(); } catch (e: any) { toast(e.message, "error"); }
  };
  const visible = data.types.filter((t) => showArchived || !t.archived);
  return (
    <section className="card" aria-labelledby="ocr-types-h">
      <div className="row between"><h2 id="ocr-types-h">OCR by document type <HelpTip text="Disabled: never recognised. Manual: only when someone chooses Run OCR. Automatic: the document's primary file is recognised after upload. Other files and old versions are never processed automatically." /></h2>
        <button className="btn small" onClick={() => setAdding(true)}><Icon name="plus" size={16} /> Add a document type</button></div>
      <p className="small muted">Text recognition is selective: nothing is read unless the type allows it. Local AI only receives recognised text of types where it is allowed (and only when Local AI is on).</p>
      {missing.length > 0 && <div className="alert warn">Language pack{missing.length > 1 ? "s" : ""} not installed: {missing.map((l) => l.name).join(", ")}. Run <code>sudo personaldocs repair</code> on the server to install {missing.length > 1 ? "them" : "it"}.</div>}
      <div style={{ overflowX: "auto" }}>
        <table className="responsive ocr-types"><thead><tr><th>Type</th><th>OCR</th><th>Languages</th><th>Local AI</th><th /></tr></thead><tbody>
          {visible.map((t) => (
            <tr key={t.id} className={t.archived ? "muted" : ""}>
              <td><span aria-hidden="true">{t.emoji}</span> {t.name}{t.is_custom && <span className="badge neutral" style={{ marginLeft: ".3rem" }}>custom</span>}{t.archived && <span className="badge neutral" style={{ marginLeft: ".3rem" }}>archived</span>}
                <div className="small muted">{t.ocr_fields.map((f) => FIELD_LABELS[f] || f).join(", ") || "No structured fields"}</div></td>
              <td><select aria-label={`OCR mode for ${t.name}`} value={t.ocr_mode} onChange={(e) => patch(t, { ocr_mode: e.target.value })}>{MODES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></td>
              <td className="small">{t.ocr_languages.map((c) => langs.find((l) => l.code === c)?.name || c).join(" + ")}</td>
              <td><label className="check"><input type="checkbox" checked={t.ocr_ai_allowed} onChange={(e) => patch(t, { ocr_ai_allowed: e.target.checked })} aria-label={`Allow Local AI for ${t.name}`} /> Allowed</label></td>
              <td><button className="btn small ghost" onClick={() => setEdit(t)}>Edit…</button></td>
            </tr>
          ))}
        </tbody></table>
      </div>
      <label className="check small"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show archived types</label>
      {(edit || adding) && <TypeDialog type={edit} data={data} langs={langs} onClose={() => { setEdit(null); setAdding(false); }} onDone={() => { setEdit(null); setAdding(false); load(); }} />}
    </section>
  );
}

function TypeDialog({ type, data, langs, onClose, onDone }: { type: OcrType | null; data: any; langs: Lang[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(type?.name || "");
  const [template, setTemplate] = useState(type?.template || "generic");
  const [mode, setMode] = useState(type?.ocr_mode || "manual");
  const [languages, setLanguages] = useState<string[]>(type?.ocr_languages?.length ? type.ocr_languages : ["eng"]);
  const [fields, setFields] = useState<string[]>(type?.ocr_fields || data.template_fields.generic || []);
  const [ai, setAi] = useState(type?.ocr_ai_allowed || false);
  const [err, setErr] = useState("");
  return (
    <Modal title={type ? `OCR settings · ${type.name}` : "Add a document type"} onClose={onClose}>
      <form className="stack" onSubmit={async (e) => {
        e.preventDefault();
        setErr("");
        const body: any = { ocr_mode: mode, ocr_languages: languages, ocr_fields: fields, ocr_ai_allowed: ai };
        try {
          if (type) await api(`ocr/types/${type.id}`, { method: "PATCH", body: type.is_custom ? { ...body, name } : body });
          else await api("ocr/types", { body: { ...body, name, template } });
          toast(type ? "Document type saved" : "Document type added");
          onDone();
        } catch (x: any) { setErr(x.message); }
      }}>
        {err && <div className="alert error">{err}</div>}
        {(!type || type.is_custom) && <div className="field"><label htmlFor="ot-name">Name</label><input id="ot-name" type="text" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} /></div>}
        {!type && <div className="field"><label htmlFor="ot-tpl">Recognition rules</label>
          <select id="ot-tpl" value={template} onChange={(e) => { setTemplate(e.target.value); setFields(data.template_fields[e.target.value] || []); }}>{data.templates.map((t: string) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}</select></div>}
        <fieldset className="field"><legend>OCR</legend><div className="row">{MODES.map(([k, l]) => <label key={k} className="check"><input type="radio" name="ot-mode" checked={mode === k} onChange={() => setMode(k)} /> {l}</label>)}</div></fieldset>
        <fieldset className="field"><legend>Default languages</legend><div className="row">{langs.map((l) => <label key={l.code} className="check"><input type="checkbox" checked={languages.includes(l.code)} onChange={(e) => setLanguages((x) => e.target.checked ? [...x, l.code] : x.filter((y) => y !== l.code))} /> {l.name}{l.installed ? "" : " (not installed)"}</label>)}</div></fieldset>
        <fieldset className="field"><legend>Expected details</legend><div className="row">{data.fields.map((f: string) => <label key={f} className="check"><input type="checkbox" checked={fields.includes(f)} onChange={(e) => setFields((x) => e.target.checked ? [...x, f] : x.filter((y) => y !== f))} /> {FIELD_LABELS[f] || f}</label>)}</div></fieldset>
        <label className="check"><input type="checkbox" checked={ai} onChange={(e) => setAi(e.target.checked)} /> Allow Local AI to read the recognised text of this type</label>
        <div className="row between">
          {type ? <button type="button" className="btn" onClick={async () => { try { await api(`ocr/types/${type.id}`, { method: "PATCH", body: { archived: !type.archived } }); onDone(); } catch (x: any) { setErr(x.message); } }}>{type.archived ? "Restore type" : "Archive type"}</button> : <span />}
          <span className="row"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!name.trim() || !languages.length}>Save</button></span>
        </div>
        {type && type.documents > 0 && <p className="small muted">{type.documents} document(s) use this type. Archiving hides it for new documents; existing documents keep it.</p>}
      </form>
    </Modal>
  );
}
