import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatDate, formatDateTime } from "../api";
import type { DocDetail, Field, Meta, TemplateField } from "../types";
import { Avatar, Confirm, CopyButton, ExpiryBadge, HelpTip, Icon, Modal, useToast } from "./ui";

/**
 * Document Details (Change Set N): the document type with its template, values with their origin, one-off details
 * and values kept from a previous type. A folder says where a document is kept; the type says what it is.
 */

const STD_LABELS: Record<string, string> = {
  full_name: "Full name", document_number: "Document number", issue_date: "Issue date", expiry_date: "Expiry date", date_of_birth: "Date of birth",
  nationality: "Nationality", issuer: "Issuer", country_code: "Country code", sex: "Sex", place_of_issue: "Place of issue", no_expiry: "Does not expire",
};
const STD_TYPES: Record<string, string> = { issue_date: "date", expiry_date: "date", date_of_birth: "date", no_expiry: "boolean", sex: "select" };

type TypeOption = { id: number; name: string; emoji?: string; archived?: boolean; description?: string };

export function useDocumentTypes(enabled = true) {
  const [types, setTypes] = useState<TypeOption[]>([]);
  useEffect(() => { if (enabled) api<{ types: TypeOption[] }>("document-types").then((r) => setTypes(r.types)).catch(() => undefined); }, [enabled]);
  return types;
}

function fieldType(key: string, tf?: TemplateField) { return tf?.field_type || STD_TYPES[key] || "text"; }

function display(f: Field, ftype: string) {
  if (!f.value) return "—";
  if (ftype === "date") return formatDate(f.value);
  if (ftype === "boolean") return f.value === "yes" ? "Yes" : f.value === "no" ? "No" : f.value;
  return f.value;
}

function ValueInput({ ftype, label, value, onChange, choices }: { ftype: string; label: string; value: string; onChange: (v: string) => void; choices?: string[] }) {
  const common = { "aria-label": label, autoFocus: true, style: { maxWidth: 260 } } as const;
  if (ftype === "boolean") return <select {...common} value={value} onChange={(e) => onChange(e.target.value)}><option value="">—</option><option value="yes">Yes</option><option value="no">No</option></select>;
  if (ftype === "select") return <select {...common} value={value} onChange={(e) => onChange(e.target.value)}><option value="">—</option>{(choices || []).map((c) => <option key={c}>{c}</option>)}</select>;
  if (ftype === "long_text") return <textarea {...common} rows={3} value={value} onChange={(e) => onChange(e.target.value)} />;
  return <input {...common} type={ftype === "date" ? "date" : ftype === "number" ? "number" : "text"} value={value} onChange={(e) => onChange(e.target.value)} />;
}

/** Origin and state of one value: Suggested / Confirmed / Edited, and where it came from. */
export function Provenance({ f }: { f: Field }) {
  const who = f.confirmed_by ? ` by ${f.confirmed_by}` : "";
  const when = f.confirmed_at ? ` on ${formatDateTime(f.confirmed_at)}` : f.updated_at ? `, changed ${formatDateTime(f.updated_at)}` : "";
  const title = `Source: ${f.source_label || f.source}${f.status === "confirmed" ? `. Confirmed${who}${when}` : ". Not confirmed yet"}${f.overridden ? ". A person replaced the OCR / AI value" : ""}`;
  return (
    <span className="prov" title={title}>
      {f.status === "proposed" ? <span className="badge soon">Suggested</span> : f.overridden ? <span className="badge neutral">Edited</span> : null}
      <span className="prov-src">{f.source_label || f.source}</span>
    </span>
  );
}

function FieldRow({ doc, f, tf, label, canEdit, onSaved, extra }: { doc: DocDetail; f?: Field; tf?: TemplateField; label: string; canEdit: boolean; onSaved: () => void; extra?: React.ReactNode }) {
  const toast = useToast();
  const key = f?.key || tf!.key;
  const ftype = fieldType(key, tf);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const save = async (v: string) => {
    try { await api(`documents/${doc.id}/fields`, { body: { key, value: v, confirm: true } }); setEditing(false); onSaved(); }
    catch (e: any) { toast(e.message, "error"); }
  };
  const start = async () => { setValue(f ? (f.sensitive ? (await api<any>(`documents/${doc.id}/fields/${key}/reveal`)).value : f.value) : ""); setEditing(true); };
  return (
    <div style={{ display: "contents" }}>
      <div className="k">{label}{tf?.required && <span className="req" aria-label="required" title="Required"> *</span>}{tf?.help_text && <HelpTip text={tf.help_text} />}</div>
      <div className="v">
        {editing ? (
          <form className="row" onSubmit={(e) => { e.preventDefault(); save(value); }}>
            <ValueInput ftype={ftype} label={`Edit ${label}`} value={value} onChange={setValue} choices={tf?.choices || (key === "sex" ? ["F", "M", "X"] : undefined)} />
            <button className="btn small primary">Save</button><button type="button" className="btn small" onClick={() => setEditing(false)}>Cancel</button>
          </form>
        ) : (
          <>
            <span className={f?.value ? "" : "muted"}>{f ? display(f, ftype) : "—"}</span>
            {f && tf?.role === "expiry" && f.status === "confirmed" && <ExpiryBadge expiry={doc.expiry} />}
            {f && <Provenance f={f} />}
            {f?.flags.map((fl) => <span key={fl} className="badge danger" title={fl}>Check</span>)}
            {f?.excerpt && f.status === "proposed" && <HelpTip text={`Found in text: “${f.excerpt}”`} />}
            {f?.proposed_value && <span className="small muted">New scan suggests {f.proposed_value}</span>}
            {extra}
          </>
        )}
      </div>
      <div className="c row" style={{ gap: 0, flexWrap: "nowrap" }}>
        {f?.value && <CopyButton label={label} getValue={async () => (f.sensitive ? (await api<any>(`documents/${doc.id}/fields/${key}/reveal`)).value : f.value)} />}
        {canEdit && !editing && (
          <>
            {f?.status === "proposed" && <button className="icon-btn" aria-label={`Confirm ${label}`} title="Confirm" onClick={() => save(f.value)}><Icon name="check" size={18} /></button>}
            <button className="icon-btn" aria-label={`${f?.value ? "Edit" : "Add"} ${label}`} title={f?.value ? "Edit" : "Add"} onClick={start}><Icon name={f?.value ? "settings" : "plus"} size={18} /></button>
          </>
        )}
      </div>
    </div>
  );
}

/** Choose a type, preview what happens to each value, then apply. */
export function TypeDialog({ doc, types, initial, source = "manual", onClose, onDone }: { doc: Pick<DocDetail, "id" | "type">; types: TypeOption[]; initial?: number | null; source?: string; onClose: () => void; onDone: (offerRemap: boolean) => void }) {
  const toast = useToast();
  const [type, setType] = useState<string>(initial ? String(initial) : doc.type ? String(doc.type.id) : "");
  const [plan, setPlan] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setPlan(null);
    if (String(doc.type?.id || "") === type) return;
    api<{ plan: any }>(`documents/${doc.id}/type`, { body: { type: type || null, preview: true } }).then((r) => setPlan(r.plan)).catch((e) => toast(e.message, "error"));
  }, [type]);
  const unchanged = String(doc.type?.id || "") === type;
  const apply = async () => {
    setBusy(true);
    try { await api(`documents/${doc.id}/type`, { body: { type: type || null, source: initial && Number(type) === initial ? source : "manual" } }); onDone(!!plan?.ocr_available && !!type); }
    catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal title={doc.type ? "Change document type" : "Set document type"} onClose={onClose}>
      <div className="stack">
        <p className="small muted">The type says what the document is; the folder only says where it is kept. Changing the type never moves the file and never deletes a value.</p>
        <div className="field"><label htmlFor="type-select">Document type</label>
          <select id="type-select" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">Not assigned</option>
            {types.filter((t) => !t.archived || t.id === doc.type?.id).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          {types.find((t) => String(t.id) === type)?.description && <div className="hint">{types.find((t) => String(t.id) === type)?.description}</div>}
        </div>
        {plan && (
          <div className="type-plan stack" aria-live="polite">
            {plan.keep.length > 0 && <div><strong>Kept ({plan.keep.length})</strong><div className="small">{plan.keep.map((k: any) => k.label).join(", ")}</div></div>}
            {plan.unmapped.length > 0 && (
              <div className="alert warn"><strong>{plan.unmapped.length} value{plan.unmapped.length > 1 ? "s are" : " is"} not part of {plan.to || "the new type"}.</strong> {plan.unmapped.length > 1 ? "They are" : "It is"} kept as <em>previous details</em> for you to map, keep or remove — nothing is deleted.
                <ul className="small">{plan.unmapped.map((u: any) => <li key={u.key}>{u.label}: {u.value || "—"} <span className="muted">({u.reason})</span></li>)}</ul></div>
            )}
            {plan.custom.length > 0 && <div className="small muted">Additional details stay with this document: {plan.custom.map((c: any) => c.label).join(", ")}.</div>}
            {plan.new_fields.length > 0 && <div className="small">New empty fields: {plan.new_fields.map((n: any) => n.label + (n.required ? " *" : "")).join(", ")}</div>}
            {plan.reminder_effect && <div className="alert error">{plan.reminder_effect}</div>}
          </div>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={unchanged || busy || (!plan && !!type)} onClick={apply}>{type ? "Apply type" : "Remove type"}</button>
        </div>
      </div>
    </Modal>
  );
}

function AddDetail({ doc, custom, typed, onSaved }: { doc: DocDetail; custom: Meta["fields"]; typed: boolean; onSaved: () => void }) {
  const toast = useToast();
  const [choice, setChoice] = useState("");
  const [label, setLabel] = useState("");
  const [value, setValue] = useState("");
  const have = new Set(doc.fields.map((f) => f.key));
  const std = typed ? [] : Object.entries(STD_LABELS).filter(([k]) => !have.has(k));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const body: any = { value, confirm: true };
    if (choice === "__new") body.label = label.trim();
    else body.key = choice;
    try { await api(`documents/${doc.id}/fields`, { body }); setChoice(""); setLabel(""); setValue(""); onSaved(); } catch (x: any) { toast(x.message, "error"); }
  };
  return (
    <form className="row add-detail" onSubmit={submit}>
      <select aria-label="Add a detail" value={choice} onChange={(e) => setChoice(e.target.value)} style={{ maxWidth: 230 }}>
        <option value="">Add a detail…</option>
        <option value="__new">New detail for this document…</option>
        {std.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        {custom.filter((c) => !have.has(`custom:${c.key}`)).map((c) => <option key={c.key} value={`custom:${c.key}`}>{c.label} ({c.type})</option>)}
      </select>
      {choice === "__new" && <input type="text" aria-label="Detail name" placeholder="Name, e.g. Old passport number" value={label} onChange={(e) => setLabel(e.target.value)} style={{ maxWidth: 220 }} />}
      {choice && <input type="text" aria-label="Detail value" placeholder="Value" value={value} onChange={(e) => setValue(e.target.value)} style={{ maxWidth: 200 }} />}
      <button className="btn small" disabled={!choice || (choice === "__new" && !label.trim())}><Icon name="plus" size={16} /> Add</button>
    </form>
  );
}

export default function DocumentDetails({ doc, onChange, openTypeDialog }: { doc: DocDetail; onChange: () => void; openTypeDialog?: number }) {
  const canEdit = doc.caps.includes("edit");
  const toast = useToast();
  const types = useDocumentTypes(canEdit);
  const [custom, setCustom] = useState<Meta["fields"]>([]);
  const [typeDialog, setTypeDialog] = useState<{ initial?: number | null; source?: string } | null>(null);
  const [remapOffer, setRemapOffer] = useState(false);
  const [promote, setPromote] = useState<Field | null>(null);
  const [mapTo, setMapTo] = useState<Record<string, string>>({});
  useEffect(() => { if (canEdit) api<Meta>("metadata").then((m) => setCustom(m.fields)).catch(() => undefined); }, [canEdit]);
  useEffect(() => { if (openTypeDialog) setTypeDialog({}); }, [openTypeDialog]);
  const tmap = new Map(doc.template.map((t) => [t.key, t]));
  const byKey = new Map(doc.fields.map((f) => [f.key, f]));
  const templateRows = doc.fields.filter((f) => f.group === "template" && !tmap.has(f.key));  // untyped documents
  const additional = doc.fields.filter((f) => f.group === "additional");
  const unmapped = doc.fields.filter((f) => f.group === "unmapped");
  const st = doc.details_status;
  const suggestions = doc.type_info?.suggestions || [];
  const conflict = suggestions.some((s) => s.conflict);
  const act = (body: any) => api(`documents/${doc.id}/fields`, { body }).then(onChange).catch((e) => toast(e.message, "error"));
  const freeTemplateKeys = doc.template.filter((t) => !byKey.get(t.key)?.value);

  return (
    <div className="stack details-panel">
      {doc.review_flags.map((f) => <div key={f} className="alert warn">{f}</div>)}
      {st.proposed > 0 && (
        <div className="alert warn row between">
          <span><strong>{st.proposed} suggested value{st.proposed > 1 ? "s" : ""}</strong> from OCR or Local AI. Check them against the document: suggestions do not rename the document or schedule reminders until confirmed.</span>
          {canEdit && <button className="btn small primary" onClick={() => act({ confirm_all: true })}>Confirm all</button>}
        </div>
      )}
      {suggestions.length > 0 && canEdit && (
        <div className="alert type-suggest" role="status">
          <div><strong>{conflict ? "Different types are suggested" : "Suggested type"}</strong>{conflict && <span className="small"> — the folder and the recognised text disagree. Choose one, or pick another type.</span>}</div>
          {suggestions.map((s) => (
            <div key={`${s.source}-${s.type}`} className="row between">
              <span>{s.name} <span className="small muted">· {s.source_label}{s.reason ? ` — ${s.reason}` : ""}{s.confidence ? ` (${Math.round(s.confidence * 100)}%)` : ""}</span></span>
              <span className="row" style={{ gap: ".3rem" }}>
                <button className="btn small primary" onClick={() => setTypeDialog({ initial: s.type, source: s.source })}>Accept…</button>
                <button className="btn small" onClick={() => setTypeDialog({})}>Change…</button>
                {s.index !== null && <button className="btn small ghost" onClick={() => api(`documents/${doc.id}/type`, { body: { ignore: true, index: s.index } }).then(onChange)}>Ignore</button>}
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="kv">
        <div style={{ display: "contents" }}><div className="k">Owner</div><div className="v"><span className="row" style={{ gap: ".4rem" }}><Avatar user={doc.owner} size="sm" /> {doc.owner.display_name}</span></div><div className="c" /></div>
        <div style={{ display: "contents" }}>
          <div className="k">Document type</div>
          <div className="v">
            {doc.type ? <span className="type-chip">{doc.type.emoji && <span aria-hidden="true">{doc.type.emoji} </span>}{doc.type.name}</span> : <span className="muted">Not assigned</span>}
            {doc.type && doc.type_info?.source_label && <span className="prov-src" title="How the type was assigned">{doc.type_info.source_label}</span>}
            {canEdit && <button className="btn small" onClick={() => setTypeDialog({})} aria-label={doc.type ? "Change document type" : "Set document type"}>{doc.type ? "Change…" : "Set type"}</button>}
            {doc.can_manage_types && doc.type && <Link className="btn small ghost" to={`/settings/documents?type=${doc.type.id}#document-types`} title="Manage this type's template">Manage</Link>}
          </div>
          <div className="c" />
        </div>
        <div style={{ display: "contents" }}><div className="k">Details</div><div className="v">
          <DetailsBadge doc={doc} />
          {canEdit && st.status === "incomplete" && st.proposed === 0 && st.unmapped === 0 && <button className="btn small ghost" onClick={() => act({ confirm_all: true, allow_incomplete: true })} title={`Empty required: ${st.missing_required.join(", ")}`}>Confirm as incomplete</button>}
        </div><div className="c" /></div>
      </div>

      <h3 className="details-h">{doc.type ? `${doc.type.name} details` : "Details"}</h3>
      {doc.template.length === 0 && templateRows.length === 0 && <p className="small muted">{doc.type ? "This type has no template fields." : "No details yet. Set a document type to get its fields, or add a detail below."}</p>}
      <div className="kv">
        {doc.template.map((tf) => <FieldRow key={tf.key} doc={doc} tf={tf} f={byKey.get(tf.key)} label={tf.label} canEdit={canEdit} onSaved={onChange} />)}
        {templateRows.map((f) => <FieldRow key={f.key} doc={doc} f={f} label={f.label || STD_LABELS[f.key] || f.key} canEdit={canEdit} onSaved={onChange} />)}
      </div>

      {(additional.length > 0 || canEdit) && <h3 className="details-h">Additional details <HelpTip text="Details of this document only. They are not part of the type's template and do not change other documents." /></h3>}
      {additional.length > 0 && (
        <div className="kv">
          {additional.map((f) => (
            <FieldRow key={f.key} doc={doc} f={f} label={f.label || f.key} canEdit={canEdit} onSaved={onChange}
              extra={<>
                {canEdit && <button className="btn small ghost" onClick={() => act({ key: f.key, delete: true })} aria-label={`Remove ${f.label}`}>Remove</button>}
                {doc.can_manage_types && doc.type && <button className="btn small ghost" onClick={() => setPromote(f)}>Add to {doc.type.name} template…</button>}
              </>} />
          ))}
        </div>
      )}
      {canEdit && <AddDetail doc={doc} custom={custom} typed={!!doc.type} onSaved={onChange} />}

      {unmapped.length > 0 && (
        <section className="unmapped" aria-labelledby={`unm-${doc.id}`}>
          <h3 className="details-h" id={`unm-${doc.id}`}>Previous details — needs review</h3>
          <p className="small muted">Kept from {unmapped[0].previous_type || "the earlier type"}. Map each value to a field of {doc.type?.name || "this type"}, keep it as an additional detail, or remove it.</p>
          {unmapped.map((f) => (
            <div key={f.key} className="unmapped-row">
              <div><strong>{f.label}</strong>: {display(f, fieldType(f.key))} <Provenance f={f} /></div>
              {canEdit && (
                <div className="row" style={{ gap: ".3rem" }}>
                  <select aria-label={`Map ${f.label} to`} value={mapTo[f.key] || ""} onChange={(e) => setMapTo({ ...mapTo, [f.key]: e.target.value })} style={{ maxWidth: 190 }}>
                    <option value="">Map to…</option>
                    {freeTemplateKeys.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                  </select>
                  <button className="btn small" disabled={!mapTo[f.key]} onClick={() => act({ key: f.key, action: "map", to: mapTo[f.key] })}>Map</button>
                  <button className="btn small" onClick={() => act({ key: f.key, action: "keep" })}>Keep as detail</button>
                  <button className="btn small ghost danger" onClick={() => act({ key: f.key, action: "remove" })}>Remove</button>
                </div>
              )}
            </div>
          ))}
        </section>
      )}
      {remapOffer && canEdit && (
        <div className="alert row between">
          <span>Recognised text is available. Suggest {doc.type?.name || "this type"}'s fields from it? No new scan is needed.</span>
          <span className="row"><button className="btn small primary" onClick={async () => { try { const r = await api<any>(`documents/${doc.id}/remap-ocr`, { method: "POST" }); toast(`${r.suggestions} suggestion${r.suggestions === 1 ? "" : "s"} to review`); setRemapOffer(false); onChange(); } catch (e: any) { toast(e.message, "error"); } }}>Re-map existing OCR data</button>
            <button className="btn small ghost" onClick={() => setRemapOffer(false)}>Not now</button></span>
        </div>
      )}
      {typeDialog && <TypeDialog doc={doc} types={types} initial={typeDialog.initial} source={typeDialog.source} onClose={() => setTypeDialog(null)} onDone={(offer) => { setTypeDialog(null); setRemapOffer(offer); onChange(); }} />}
      {promote && doc.type && (
        <Confirm title={`Add “${promote.label}” to the ${doc.type.name} template`} confirmLabel="Add to template"
          message={<p>Every {doc.type.name} document will show an empty <strong>{promote.label}</strong> field. Only this document's value is moved into it; other documents are not changed.</p>}
          onClose={() => setPromote(null)}
          onConfirm={async () => { try { await api(`document-types/${doc.type!.id}/fields`, { body: { promote: true, document: doc.id, key: promote.key } }); toast("Added to the template"); setPromote(null); onChange(); } catch (e: any) { toast(e.message, "error"); setPromote(null); } }} />
      )}
    </div>
  );
}

export function DetailsBadge({ doc }: { doc: DocDetail }) {
  const st = doc.details_status;
  if (!st || st.status === "empty") return <span className="small muted">No details yet</span>;
  if (st.status === "confirmed") return <span className="badge ok"><Icon name="check" size={13} /> Details confirmed{st.incomplete_ok && st.missing_required.length ? " (incomplete)" : ""}</span>;
  if (st.status === "incomplete") return <span className="badge soon" title={`Empty required: ${st.missing_required.join(", ")}`}>Incomplete: {st.missing_required.join(", ")}</span>;
  const parts = [st.proposed ? `${st.proposed} suggested` : "", st.unmapped ? `${st.unmapped} previous` : "", doc.type_info?.suggestions?.length && !doc.type?.confirmed ? "type suggested" : ""].filter(Boolean);
  return <span className="badge soon">Needs review{parts.length ? `: ${parts.join(", ")}` : ""}</span>;
}

/** Several documents at once: counts first, confirmed types are protected unless explicitly overwritten. */
export function BulkTypeDialog({ ids, onClose, onDone }: { ids: string[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const types = useDocumentTypes();
  const [type, setType] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [overwrite, setOverwrite] = useState(false);
  useEffect(() => { setPreview(null); if (type) api<any>("documents/bulk-type", { body: { ids, type: Number(type), preview: true } }).then(setPreview).catch((e) => toast(e.message, "error")); }, [type]);
  return (
    <Modal title={`Set document type for ${ids.length} document${ids.length === 1 ? "" : "s"}`} onClose={onClose}>
      <div className="stack">
        <div className="field"><label htmlFor="bulk-type">Document type</label>
          <select id="bulk-type" value={type} onChange={(e) => setType(e.target.value)}><option value="">Choose a type…</option>{types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></div>
        {preview && (
          <div className="stack small" aria-live="polite">
            <div>Now: {Object.entries(preview.current).map(([k, v]) => `${k} (${v})`).join(", ") || "—"}</div>
            {preview.not_allowed > 0 && <div className="alert warn">{preview.not_allowed} document{preview.not_allowed === 1 ? "" : "s"} cannot be changed by you and will be skipped.</div>}
            {preview.already > 0 && <div>{preview.already} already {preview.already === 1 ? "is" : "are"} {preview.type}.</div>}
            {preview.confirmed_other > 0 && (
              <div className="alert warn">{preview.confirmed_other} document{preview.confirmed_other === 1 ? " has" : "s have"} another confirmed type. They are skipped unless you choose otherwise.
                <label className="check"><input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} /> Also change documents with a confirmed type</label></div>
            )}
            <div className="muted">Values that do not fit {preview.type} are kept as previous details for review; files and folders are not changed.</div>
          </div>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!preview || preview.allowed === 0} onClick={async () => {
            try { const r = await api<any>("documents/bulk-type", { body: { ids, type: Number(type), overwrite_confirmed: overwrite } }); toast(`${r.changed} changed${r.skipped ? `, ${r.skipped} skipped` : ""}`); onDone(); }
            catch (e: any) { toast(e.message, "error"); }
          }}>Apply</button>
        </div>
      </div>
    </Modal>
  );
}

/** A folder may suggest a type for uploads. It never moves documents or changes their type. */
export function SuggestedTypeDialog({ folder, onClose, onDone }: { folder: { id: string; name: string; suggested_type?: { id: number; name: string } | null }; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const types = useDocumentTypes();
  const [type, setType] = useState(folder.suggested_type ? String(folder.suggested_type.id) : "");
  return (
    <Modal title={`Suggested document type for “${folder.name}”`} onClose={onClose}>
      <div className="stack">
        <p className="small muted">Uploads into this folder (and its subfolders) start with this type selected; people can change it. Documents already here keep their type, and the folder never changes a type later.</p>
        <div className="field"><label htmlFor="sugg-type">Suggested type</label>
          <select id="sugg-type" value={type} onChange={(e) => setType(e.target.value)}><option value="">No suggestion</option>{types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={async () => { try { await api(`folders/${folder.id}`, { method: "PATCH", body: { suggested_type: type ? Number(type) : null } }); toast("Suggested type saved"); onDone(); } catch (e: any) { toast(e.message, "error"); } }}>Save</button>
        </div>
      </div>
    </Modal>
  );
}
