import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { Confirm, HelpTip, Icon, Modal, Skeleton, useToast } from "../../components/ui";

/** Settings → Documents & folders → Document types: types, their metadata templates, and review of untyped documents. */

interface TField { id: number; key: string; label: string; field_type: string; enabled: boolean; required: boolean; order: number; help_text: string; extract: boolean; searchable: boolean; role: string; choices: string[]; validation: Record<string, any> }
interface DType { id: number; name: string; emoji: string; description: string; has_expiry: boolean; archived: boolean; template: string; fields: TField[]; sort_order: number; reminder_days: number[]; is_custom: boolean; documents: number }
interface Payload { types: DType[]; field_types: string[]; roles: string[]; templates: string[]; standard_fields: Record<string, string>; report: Record<string, number> }

const FT_LABEL: Record<string, string> = { text: "Short text", long_text: "Long text / notes", date: "Date", number: "Number", boolean: "Yes / no", select: "List", country: "Country", person: "Person / name", identifier: "Identifier / number" };
const ROLE_LABEL: Record<string, string> = { "": "—", expiry: "Expiry date (reminders)", issue: "Issue date", no_expiry: "Does not expire" };

function FieldDialog({ type, field, data, onClose, onDone }: { type: DType; field: TField | null; data: Payload; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState<any>(field ? { ...field, choices: field.choices.join(", "), pattern: field.validation?.pattern || "", max_length: field.validation?.max_length || "" }
    : { key: "", label: "", field_type: "text", enabled: true, required: false, extract: false, searchable: true, role: "", help_text: "", choices: "", pattern: "", max_length: "" });
  const [err, setErr] = useState("");
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    const body: any = { label: f.label, field_type: f.field_type, enabled: f.enabled, required: f.required, extract: f.extract, searchable: f.searchable, role: f.role, help_text: f.help_text, choices: f.choices,
      validation: { ...(f.pattern ? { pattern: f.pattern } : {}), ...(f.max_length ? { max_length: f.max_length } : {}) } };
    if (!field && f.key) body.key = f.key;
    try { await api(field ? `document-types/${type.id}/fields/${field.id}` : `document-types/${type.id}/fields`, { method: field ? "PATCH" : "POST", body }); onDone(); }
    catch (x: any) { setErr(x.message); }
  };
  return (
    <Modal title={field ? `Edit field — ${field.label}` : `Add a field to ${type.name}`} onClose={onClose}>
      <form className="stack" onSubmit={save}>
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="field"><label htmlFor="fl">Label</label><input type="text" id="fl" value={f.label} onChange={(e) => set("label", e.target.value)} required /></div>
        {!field && <div className="field"><label htmlFor="fk">Key (optional) <HelpTip text="Stable internal name. Renaming the label later never loses values. Standard keys (e.g. expiry_date) let OCR suggest values." /></label>
          <input type="text" id="fk" value={f.key} list="std-keys" onChange={(e) => set("key", e.target.value)} placeholder="made from the label" />
          <datalist id="std-keys">{Object.entries(data.standard_fields).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</datalist></div>}
        {field && <p className="small muted">Key: <code>{field.key}</code></p>}
        <div className="grid two">
          <div className="field"><label htmlFor="ft">Field type</label><select id="ft" value={f.field_type} onChange={(e) => set("field_type", e.target.value)}>{data.field_types.map((t) => <option key={t} value={t}>{FT_LABEL[t] || t}</option>)}</select></div>
          <div className="field"><label htmlFor="fr">Role <HelpTip text="The Expiry date role drives reminders (only from confirmed values). One field per role." /></label><select id="fr" value={f.role} onChange={(e) => set("role", e.target.value)}>{["", ...data.roles].map((r) => <option key={r} value={r}>{ROLE_LABEL[r] || r}</option>)}</select></div>
        </div>
        {f.field_type === "select" && <div className="field"><label htmlFor="fc">Choices (comma separated)</label><input type="text" id="fc" value={f.choices} onChange={(e) => set("choices", e.target.value)} /></div>}
        <div className="field"><label htmlFor="fh">Help text</label><input type="text" id="fh" value={f.help_text} onChange={(e) => set("help_text", e.target.value)} /></div>
        <div className="row">
          <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => set("enabled", e.target.checked)} /> Shown</label>
          <label className="check"><input type="checkbox" checked={f.required} onChange={(e) => set("required", e.target.checked)} /> Required</label>
          <label className="check"><input type="checkbox" checked={f.extract} onChange={(e) => set("extract", e.target.checked)} /> OCR / Local AI may suggest</label>
          <label className="check"><input type="checkbox" checked={f.searchable} onChange={(e) => set("searchable", e.target.checked)} /> Searchable</label>
        </div>
        {["text", "identifier", "person", "country"].includes(f.field_type) && <div className="grid two">
          <div className="field"><label htmlFor="fp">Format (regular expression, optional)</label><input type="text" id="fp" value={f.pattern} onChange={(e) => set("pattern", e.target.value)} placeholder="e.g. [A-Z][0-9]{7}" /></div>
          <div className="field"><label htmlFor="fm">Maximum length</label><input id="fm" type="number" min={1} value={f.max_length} onChange={(e) => set("max_length", e.target.value)} /></div></div>}
        <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary">Save field</button></div>
      </form>
    </Modal>
  );
}

function Preview({ type }: { type: DType }) {
  const fields = type.fields.filter((f) => f.enabled);
  return (
    <div className="card type-preview" aria-label={`Preview of the ${type.name} details`}>
      <div className="small muted">Preview — what the Details panel shows</div>
      <h3 className="details-h">{type.name} details</h3>
      <div className="kv">{fields.map((f) => <div key={f.id} style={{ display: "contents" }}><div className="k">{f.label}{f.required && <span className="req"> *</span>}</div><div className="v muted">—{f.role === "expiry" && <span className="badge neutral" style={{ marginLeft: ".4rem" }}>reminders</span>}</div><div className="c" /></div>)}</div>
      {fields.length === 0 && <p className="small muted">No fields shown.</p>}
    </div>
  );
}

function TypeEditor({ type, data, all, onClose, reload }: { type: DType; data: Payload; all: DType[]; onClose: () => void; reload: () => void }) {
  const toast = useToast();
  const [s, setS] = useState({ name: type.name, emoji: type.emoji, description: type.description, has_expiry: type.has_expiry, reminder_days: type.reminder_days.join(", ") });
  const [field, setField] = useState<TField | null | "new">(null);
  const [del, setDel] = useState(false);
  const [target, setTarget] = useState("");
  const fields = [...type.fields].sort((a, b) => a.order - b.order);
  const move = async (i: number, d: number) => {
    const ids = fields.map((f) => f.id);
    const j = i + d;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    await api(`document-types/${type.id}/fields`, { body: { reorder: ids } });
    reload();
  };
  const saveType = async (e: React.FormEvent) => {
    e.preventDefault();
    try { await api(`document-types/${type.id}`, { method: "PATCH", body: s }); toast("Document type saved"); reload(); } catch (x: any) { toast(x.message, "error"); }
  };
  return (
    <Modal title={`${type.emoji || ""} ${type.name}`.trim()} onClose={onClose} wide>
      <div className="stack">
        <form className="stack" onSubmit={saveType}>
          <div className="grid two">
            <div className="field"><label htmlFor="tn">Display name</label><input type="text" id="tn" value={s.name} onChange={(e) => setS({ ...s, name: e.target.value })} /></div>
            <div className="field"><label htmlFor="te">Icon (emoji)</label><input type="text" id="te" value={s.emoji} maxLength={16} onChange={(e) => setS({ ...s, emoji: e.target.value })} style={{ maxWidth: 120 }} /></div>
          </div>
          <div className="field"><label htmlFor="td">Description / help text</label><input type="text" id="td" value={s.description} onChange={(e) => setS({ ...s, description: e.target.value })} /></div>
          <div className="row">
            <label className="check"><input type="checkbox" checked={s.has_expiry} onChange={(e) => setS({ ...s, has_expiry: e.target.checked })} /> Expiry-aware</label>
            <div className="field"><label htmlFor="trd">Reminder days <HelpTip text="Days before the expiry date when reminders are sent for this type. Empty = the global setting." /></label><input type="text" id="trd" value={s.reminder_days} placeholder="global setting" onChange={(e) => setS({ ...s, reminder_days: e.target.value })} style={{ maxWidth: 200 }} /></div>
          </div>
          <div className="row"><button className="btn primary">Save type</button><span className="small muted">{type.documents} document{type.documents === 1 ? "" : "s"} use this type. OCR mode and languages: Settings → OCR & processing.</span></div>
        </form>
        <div className="row between"><h3>Metadata template</h3><button className="btn small" onClick={() => setField("new")}><Icon name="plus" size={16} /> Add field</button></div>
        <div style={{ overflowX: "auto" }}>
          <table className="responsive tfields"><thead><tr><th>Order</th><th>Field</th><th>Type</th><th>Settings</th><th /></tr></thead><tbody>
            {fields.map((f, i) => (
              <tr key={f.id} className={f.enabled ? "" : "muted"}>
                <td className="row" style={{ gap: 0, flexWrap: "nowrap" }}>
                  <button className="icon-btn" aria-label={`Move ${f.label} up`} disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
                  <button className="icon-btn" aria-label={`Move ${f.label} down`} disabled={i === fields.length - 1} onClick={() => move(i, 1)}>↓</button>
                </td>
                <td><strong>{f.label}</strong>{f.required && <span className="req"> *</span>}<div className="small muted mono">{f.key}</div></td>
                <td className="small">{FT_LABEL[f.field_type] || f.field_type}{f.role && <div><span className="badge neutral">{ROLE_LABEL[f.role]}</span></div>}</td>
                <td className="small">{[f.enabled ? "shown" : "hidden", f.extract ? "OCR/AI" : "", f.searchable ? "searchable" : "not searchable"].filter(Boolean).join(" · ")}</td>
                <td><button className="btn small ghost" onClick={() => setField(f)}>Edit…</button></td>
              </tr>
            ))}
          </tbody></table>
        </div>
        <Preview type={type} />
        <div className="row between">
          <button className="btn" onClick={async () => { try { await api(`document-types/${type.id}`, { method: "PATCH", body: { archived: !type.archived } }); reload(); } catch (x: any) { toast(x.message, "error"); } }}>{type.archived ? "Restore type" : "Archive type"}</button>
          <button className="btn danger ghost" onClick={() => setDel(true)}>Delete…</button>
        </div>
      </div>
      {field && <FieldDialog type={type} field={field === "new" ? null : field} data={data} onClose={() => setField(null)} onDone={() => { setField(null); reload(); }} />}
      {del && (type.documents > 0 ? (
        <Modal title={`Delete ${type.name}`} onClose={() => setDel(false)}>
          <div className="stack">
            <p>{type.documents} document{type.documents === 1 ? "" : "s"} use this type. Archive it instead (documents keep it), or move them to another type first. Values that do not fit the new type are kept for review.</p>
            <div className="field"><label htmlFor="rt">Move documents to</label><select id="rt" value={target} onChange={(e) => setTarget(e.target.value)}><option value="">Choose a type…</option>{all.filter((t) => t.id !== type.id && !t.archived).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></div>
            <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn" onClick={() => setDel(false)}>Cancel</button>
              <button className="btn danger" disabled={!target} onClick={async () => { try { await api(`document-types/${type.id}`, { method: "DELETE", body: { reassign_to: Number(target) } }); toast("Documents moved and type deleted"); onClose(); reload(); } catch (x: any) { toast(x.message, "error"); } }}>Move and delete</button></div>
          </div>
        </Modal>
      ) : (
        <Confirm title={`Delete ${type.name}`} danger confirmLabel="Delete" message={<p>No document uses this type. Its template is deleted too.</p>} onClose={() => setDel(false)}
          onConfirm={async () => { try { await api(`document-types/${type.id}`, { method: "DELETE" }); onClose(); reload(); } catch (x: any) { toast(x.message, "error"); } }} />
      ))}
    </Modal>
  );
}

function Review({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const [data, setData] = useState<{ items: any[] } | null>(null);
  const [pick, setPick] = useState<Record<string, string>>({});
  const load = () => api<any>("document-types/review").then((r) => { setData(r); setPick(Object.fromEntries(r.items.filter((i: any) => !i.suggestions.some((s: any) => s.conflict)).map((i: any) => [i.id, `${i.suggestions[0].type}|${i.suggestions[0].source}`]))); });
  useEffect(() => { load(); }, []);
  if (!data) return <Skeleton />;
  const chosen = Object.entries(pick).filter(([, v]) => v);
  return (
    <div className="stack">
      <p className="small muted">Untyped documents with a folder or OCR suggestion. Nothing is applied until you confirm; conflicting suggestions start unselected.</p>
      {data.items.length === 0 ? <div className="empty">No suggestions to review.</div> : (
        <table className="responsive"><thead><tr><th>Document</th><th>Suggestion</th></tr></thead><tbody>
          {data.items.map((i) => (
            <tr key={i.id}><td>{i.title}<div className="small muted">{i.owner} · {i.folder}</div></td>
              <td><select aria-label={`Type for ${i.title}`} value={pick[i.id] || ""} onChange={(e) => setPick({ ...pick, [i.id]: e.target.value })}>
                <option value="">Leave untyped</option>
                {i.suggestions.map((s: any) => <option key={`${s.type}|${s.source}`} value={`${s.type}|${s.source}`}>{s.name} — {s.source_label}{s.conflict ? " (conflict)" : ""}</option>)}
              </select></td></tr>
          ))}
        </tbody></table>
      )}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn primary" disabled={!chosen.length} onClick={async () => {
          const r = await api<any>("document-types/review", { body: { items: chosen.map(([id, v]) => ({ id, type: Number(v.split("|")[0]), source: v.split("|")[1] })) } });
          toast(`${r.applied} document${r.applied === 1 ? "" : "s"} classified`); load(); onDone();
        }}>Apply {chosen.length} selected</button>
      </div>
    </div>
  );
}

export default function DocumentTypesAdmin() {
  const toast = useToast();
  const [params] = useSearchParams();
  const [data, setData] = useState<Payload | null>(null);
  const [open, setOpen] = useState<number | null>(params.get("type") ? Number(params.get("type")) : null);
  const [adding, setAdding] = useState(false);
  const [review, setReview] = useState(false);
  const [archived, setArchived] = useState(false);
  const [nt, setNt] = useState({ name: "", template: "generic", has_expiry: false, copy_from: "" });
  const load = () => api<Payload>("document-types/admin").then(setData);
  useEffect(() => { load(); }, []);
  if (!data) return <div className="card"><Skeleton /></div>;
  const current = data.types.find((t) => t.id === open);
  const r = data.report;
  return (
    <section className="card" id="document-types" aria-labelledby="dt-h">
      <div className="row between"><h2 id="dt-h">Document types <HelpTip text="A folder says where a document is kept; the type says what it is. Each type has a metadata template that the Details panel shows." link="/help/document-types" /></h2>
        <button className="btn small" onClick={() => setAdding(true)}><Icon name="plus" size={16} /> Add a document type</button></div>
      <div className="row small type-report">
        <span>{r.typed} typed</span><span>{r.untyped} untyped</span>
        {(r.with_suggestions + r.folder_suggestions) > 0 && <button className="btn small" onClick={() => setReview(true)}>Review untyped documents ({Math.max(r.with_suggestions, r.folder_suggestions)})</button>}
        {r.unmapped_values > 0 && <span className="badge soon">{r.unmapped_values} previous values waiting for review</span>}
      </div>
      <div className="type-list">
        {data.types.filter((t) => archived || !t.archived).map((t) => (
          <button key={t.id} className={`type-card ${t.archived ? "muted" : ""}`} onClick={() => setOpen(t.id)} aria-label={`Edit document type ${t.name}`}>
            <span className="type-emoji" aria-hidden="true">{t.emoji || "📄"}</span>
            <span className="grow"><strong>{t.name}</strong>{t.archived && <span className="badge neutral" style={{ marginLeft: ".3rem" }}>archived</span>}
              <span className="small muted block">{t.fields.filter((f) => f.enabled).length} fields · {t.documents} document{t.documents === 1 ? "" : "s"}{t.has_expiry ? " · expires" : ""}</span></span>
          </button>
        ))}
      </div>
      <label className="check small"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived types</label>
      {current && <TypeEditor type={current} data={data} all={data.types} onClose={() => setOpen(null)} reload={load} />}
      {review && <Modal title="Review untyped documents" onClose={() => setReview(false)} wide><Review onDone={load} /></Modal>}
      {adding && (
        <Modal title="Add a document type" onClose={() => setAdding(false)}>
          <form className="stack" onSubmit={async (e) => { e.preventDefault(); try { const t = await api<DType>("document-types/admin", { body: { ...nt, copy_from: nt.copy_from ? Number(nt.copy_from) : undefined } }); setAdding(false); await load(); setOpen(t.id); } catch (x: any) { toast(x.message, "error"); } }}>
            <div className="field"><label htmlFor="ntn">Name</label><input type="text" id="ntn" value={nt.name} onChange={(e) => setNt({ ...nt, name: e.target.value })} required /></div>
            <div className="field"><label htmlFor="ntt">Start from</label><select id="ntt" value={nt.copy_from ? `copy:${nt.copy_from}` : nt.template} onChange={(e) => e.target.value.startsWith("copy:") ? setNt({ ...nt, copy_from: e.target.value.slice(5) }) : setNt({ ...nt, template: e.target.value, copy_from: "" })}>
              {data.templates.map((t) => <option key={t} value={t}>Standard fields: {t.replace(/_/g, " ")}</option>)}
              {data.types.map((t) => <option key={t.id} value={`copy:${t.id}`}>Copy the template of {t.name}</option>)}
            </select></div>
            <label className="check"><input type="checkbox" checked={nt.has_expiry} onChange={(e) => setNt({ ...nt, has_expiry: e.target.checked })} /> Expiry-aware</label>
            <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={() => setAdding(false)}>Cancel</button><button className="btn primary" disabled={!nt.name.trim()}>Create</button></div>
          </form>
        </Modal>
      )}
    </section>
  );
}
