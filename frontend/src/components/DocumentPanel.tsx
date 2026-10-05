import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, formatBytes, formatDate, formatDateTime, upload } from "../api";
import { saveOffline } from "../offline";
import { useSession } from "../session";
import type { DocDetail, DocRow, Meta } from "../types";
import PermissionsDialog from "./PermissionsDialog";
import { Avatar, Confirm, CopyButton, ExpiryBadge, HelpTip, Icon, Modal, Skeleton, StateBadge, useToast } from "./ui";

const FIELD_LABELS: Record<string, string> = {
  full_name: "Full name", document_number: "Document number", issue_date: "Issue date", expiry_date: "Expiry date", date_of_birth: "Date of birth",
  nationality: "Nationality", issuer: "Issuer", country_code: "Country code", sex: "Sex", place_of_issue: "Place of issue",
};
const DATE_KEYS = ["issue_date", "expiry_date", "date_of_birth"];

function Preview({ doc }: { doc: DocDetail }) {
  const v = doc.current_version;
  const [text, setText] = useState("");
  useEffect(() => {
    setText("");
    if (v?.format === "text") fetch(`/api/documents/${doc.id}/preview`, { credentials: "same-origin" }).then((r) => r.text()).then((t) => setText(t.slice(0, 200000)));
  }, [doc.id, v?.id, v?.format]);
  if (!v) return <div className="empty">No file.</div>;
  if (["queued", "processing"].includes(v.state)) return <div className="empty"><Icon name="refresh" /> Processing… the preview appears when OCR and conversion finish.</div>;
  if (v.format === "image") return <img className="preview-img" src={`/api/documents/${doc.id}/file?version=${v.id}`} alt={`Preview of ${doc.title}`} />;
  if (v.format === "text") return <pre className="preview-text">{text}</pre>;
  if (v.has_preview && (v.format === "pdf" || v.format === "office"))
    return <iframe className="preview-frame" title={`Preview of ${doc.title}`} src={`/api/documents/${doc.id}/preview?version=${v.id}`} />;
  return (
    <div className="empty">
      <Icon name="file" size={40} />
      <p>{v.error || "No preview is available for this file type."}</p>
      {v.format === "dicom" && <p className="small">DICOM studies are kept intact. Export the whole folder to open it in your medical image viewer.</p>}
    </div>
  );
}

function Fields({ doc, onChange }: { doc: DocDetail; onChange: () => void }) {
  const canEdit = doc.caps.includes("edit");
  const toast = useToast();
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [newKey, setNewKey] = useState("");
  const [custom, setCustom] = useState<Meta["fields"]>([]);
  useEffect(() => { if (canEdit) api<Meta>("metadata").then((m) => setCustom(m.fields)).catch(() => undefined); }, [canEdit]);
  const customLabel = (key: string) => custom.find((c) => `custom:${c.key}` === key)?.label;
  const proposed = doc.fields.filter((f) => f.status === "proposed");
  const save = async (key: string, v: string, confirm = true) => {
    try {
      await api(`documents/${doc.id}/fields`, { body: { key, value: v, confirm } });
      setEditing(null);
      onChange();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const rows: [string, string, React.ReactNode, boolean][] = [
    ["owner", "Owner", doc.owner.display_name, false],
    ["type", "Type", doc.type?.name || "—", false],
  ];
  return (
    <div className="stack">
      {doc.review_flags.map((f) => <div key={f} className="alert warn">{f}</div>)}
      {proposed.length > 0 && (
        <div className="alert warn row between">
          <span><strong>{proposed.length} suggested value{proposed.length > 1 ? "s" : ""}</strong> from OCR. Check them against the document: suggestions do not rename the document or schedule reminders until confirmed.</span>
          {canEdit && <button className="btn small primary" onClick={() => api(`documents/${doc.id}/fields`, { body: { confirm_all: true } }).then(onChange)}>Confirm all</button>}
        </div>
      )}
      <div className="kv">
        {rows.map(([k, label, val]) => (
          <div key={k} style={{ display: "contents" }}><div className="k">{label}</div><div className="v">{k === "owner" ? <span className="row" style={{ gap: ".4rem" }}><Avatar user={doc.owner} size="sm" /> {val}</span> : val}</div><div className="c"><CopyButton label={label} getValue={() => String(val)} /></div></div>
        ))}
        {doc.fields.map((f) => (
          <div key={f.key} style={{ display: "contents" }}>
            <div className="k">{FIELD_LABELS[f.key] || customLabel(f.key) || f.key.replace(/^custom:/, "").replace(/_/g, " ")}</div>
            <div className="v">
              {editing === f.key ? (
                <form className="row" onSubmit={(e) => { e.preventDefault(); save(f.key, value); }}>
                  <input aria-label={`Edit ${f.key}`} type={DATE_KEYS.includes(f.key) || custom.find((c) => `custom:${c.key}` === f.key)?.type === "date" ? "date" : custom.find((c) => `custom:${c.key}` === f.key)?.type === "number" ? "number" : "text"} value={value} onChange={(e) => setValue(e.target.value)} style={{ maxWidth: 220 }} autoFocus />
                  <button className="btn small primary">Save</button><button type="button" className="btn small" onClick={() => setEditing(null)}>Cancel</button>
                </form>
              ) : (
                <>
                  <span>{DATE_KEYS.includes(f.key) ? formatDate(f.value) : f.value || "—"}</span>
                  {f.key === "expiry_date" && f.status === "confirmed" && <ExpiryBadge expiry={doc.expiry} />}
                  {f.status === "proposed" && <span className="badge soon" title={`Source: ${f.source}`}>Suggested</span>}
                  {f.flags.map((fl) => <span key={fl} className="badge danger" title={fl}>Check</span>)}
                  {f.excerpt && f.status === "proposed" && <HelpTip text={`Found in text: “${f.excerpt}”`} />}
                  {f.proposed_value && <span className="small muted">New scan suggests {f.proposed_value}</span>}
                </>
              )}
            </div>
            <div className="c row" style={{ gap: 0, flexWrap: "nowrap" }}>
              <CopyButton label={FIELD_LABELS[f.key] || f.key} getValue={async () => (f.sensitive ? (await api(`documents/${doc.id}/fields/${f.key}/reveal`)).value : f.value)} />
              {canEdit && editing !== f.key && (
                <>
                  {f.status === "proposed" && <button className="icon-btn" aria-label={`Confirm ${f.key}`} title="Confirm" onClick={() => save(f.key, f.value)}><Icon name="check" size={18} /></button>}
                  <button className="icon-btn" aria-label={`Edit ${f.key}`} title="Edit" onClick={async () => { setEditing(f.key); setValue(f.sensitive ? (await api(`documents/${doc.id}/fields/${f.key}/reveal`)).value : f.value); }}><Icon name="settings" size={18} /></button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
      {canEdit && (
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (newKey) { setEditing(newKey); setValue(""); save(newKey, "", true).then(() => setNewKey("")); } }}>
          <select aria-label="Add a detail" value={newKey} onChange={(e) => setNewKey(e.target.value)} style={{ maxWidth: 260 }}>
            <option value="">Add a detail…</option>
            {Object.entries(FIELD_LABELS).filter(([k]) => !doc.fields.some((f) => f.key === k)).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            {custom.filter((c) => !doc.fields.some((f) => f.key === `custom:${c.key}`)).map((c) => <option key={c.key} value={`custom:${c.key}`}>{c.label} ({c.type})</option>)}
          </select>
          <button className="btn small" disabled={!newKey}><Icon name="plus" size={16} /> Add</button>
        </form>
      )}
      {doc.renews && <p className="small">Renews: <Link to={`/documents/${doc.renews.id}`}>{doc.renews.title}</Link></p>}
      {doc.renewed_by.map((r) => <p key={r.id} className="small">Renewed by: <Link to={`/documents/${r.id}`}>{r.title}</Link></p>)}
      {doc.tags.length > 0 && <div className="row">{doc.tags.map((t) => <span key={t.id} className="badge">{t.name}</span>)}</div>}
      {doc.source_path && <p className="small muted">Imported from: {doc.source_path}</p>}
    </div>
  );
}

function VersionDialog({ doc, mode, onClose, onDone }: { doc: DocDetail; mode: "version" | "renew"; onClose: () => void; onDone: (id?: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [comment, setComment] = useState("");
  const [err, setErr] = useState("");
  const [p, setP] = useState<number | null>(null);
  return (
    <Modal title={mode === "version" ? "Upload a new version" : "Add renewed document"} onClose={onClose}>
      <div className="stack">
        <div className="alert">
          {mode === "version"
            ? "Use this for a better scan or corrected copy of the same document. The original stays in version history; details stay shared."
            : "Use this when the credential was renewed (e.g. a new passport). A separate record is created and linked; the old one keeps its dates and history."}
        </div>
        <input type="file" aria-label="File" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        {mode === "version" && <div className="field"><label htmlFor="vc">What changed? (optional)</label><input id="vc" type="text" value={comment} onChange={(e) => setComment(e.target.value)} /></div>}
        {p !== null && <div className="progress"><div style={{ width: `${p * 100}%` }} /></div>}
        {err && <div className="alert error">{err}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!file || p !== null} onClick={async () => {
            const f = new FormData();
            f.set("file", file!);
            f.set("comment", comment);
            try { setP(0); const r = await upload<any>(`documents/${doc.id}/${mode === "version" ? "versions" : "renew"}`, f, setP); onDone(mode === "renew" ? r.id : undefined); } catch (e: any) { setErr(e.message); setP(null); }
          }}>Upload</button>
        </div>
      </div>
    </Modal>
  );
}

function ShareDialog({ doc, onClose }: { doc: DocDetail; onClose: () => void }) {
  const toast = useToast();
  const [shares, setShares] = useState<any[]>([]);
  const [days, setDays] = useState(7);
  const [password, setPassword] = useState("");
  const [allowDownload, setAllowDownload] = useState(true);
  const [created, setCreated] = useState<string>("");
  const load = () => api<{ shares: any[] }>(`documents/${doc.id}/shares`).then((r) => setShares(r.shares));
  useEffect(() => { load(); }, []);
  const nativeShare = async () => {
    try {
      const res = await fetch(`/api/documents/${doc.id}/file?download=1`, { credentials: "same-origin" });
      const blob = await res.blob();
      const file = new File([blob], doc.current_version?.original_name || "document", { type: blob.type });
      if ((navigator as any).canShare?.({ files: [file] })) await navigator.share({ files: [file], title: doc.title });
      else toast("This device cannot share files directly. Download the file and share it from your device instead.", "error");
    } catch (e: any) {
      if (e?.name !== "AbortError") toast("Sharing was not completed.", "error");
    }
  };
  return (
    <Modal title="Share" onClose={onClose}>
      <div className="stack">
        {doc.caps.includes("download") && (
          <div className="card">
            <h3>Share a copy from this device</h3>
            <p className="small muted">Uses your phone or computer's share menu where supported. A shared copy is independent: link expiry and revocation do not affect it.</p>
            <button className="btn" onClick={nativeShare}><Icon name="share" /> Share file…</button>
          </div>
        )}
        {doc.caps.includes("share") && (
          <div className="card">
            <h3>Public link</h3>
            <p className="small muted">Anyone with the link can open only this version of this document until it expires or you revoke it.</p>
            <div className="row">
              <div className="field"><label htmlFor="days">Valid for (days)</label><input id="days" type="number" min={1} max={90} value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ width: 110 }} /></div>
              <div className="field grow"><label htmlFor="spw">Password (optional)</label><input id="spw" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
            </div>
            <label className="check field"><input type="checkbox" checked={allowDownload} onChange={(e) => setAllowDownload(e.target.checked)} /> Allow download</label>
            <button className="btn primary" onClick={async () => {
              try { const r = await api<any>(`documents/${doc.id}/shares`, { body: { days, password, allow_download: allowDownload } }); setCreated(r.url); setPassword(""); load(); } catch (e: any) { toast(e.message, "error"); }
            }}>Create link</button>
            {created && (
              <div className="alert ok" style={{ marginTop: ".8rem" }}>
                <div className="small">Copy this link now — it is shown only once.</div>
                <div className="row" style={{ flexWrap: "nowrap" }}><code className="grow" style={{ overflowWrap: "anywhere" }}>{created}</code><CopyButton label="Link" getValue={() => created} /></div>
              </div>
            )}
          </div>
        )}
        {shares.length > 0 && (
          <table className="responsive"><thead><tr><th>Link</th><th>Status</th><th>Expires</th><th /></tr></thead><tbody>
            {shares.map((s) => (
              <tr key={s.id}><td className="mono">{s.hint}… v{s.version}{s.has_password ? " 🔒" : ""}</td><td><span className={`badge ${s.status === "active" ? "ok" : "neutral"}`}>{s.status}</span> <span className="small muted">{s.access_count} opens</span></td>
                <td>{formatDateTime(s.expires_at)}</td><td>{s.status === "active" && <button className="btn small danger" onClick={() => api(`shares/${s.id}`, { method: "DELETE" }).then(load)}>Revoke</button>}</td></tr>
            ))}
          </tbody></table>
        )}
      </div>
    </Modal>
  );
}

function EditDialog({ doc, onClose, onDone }: { doc: DocDetail; onClose: () => void; onDone: () => void }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [title, setTitle] = useState(doc.title);
  const [type, setType] = useState(doc.type?.id ? String(doc.type.id) : "");
  const [corr, setCorr] = useState(doc.correspondent?.name || "");
  const [tags, setTags] = useState(doc.tags.map((t) => t.name).join(", "));
  const [err, setErr] = useState("");
  useEffect(() => { api<Meta>("metadata").then(setMeta); }, []);
  return (
    <Modal title="Edit details" onClose={onClose}>
      <form className="stack" onSubmit={async (e) => {
        e.preventDefault();
        try {
          const body: any = { doc_type: type || null, correspondent: corr || null, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) };
          if (title !== doc.title) body.title = title;
          await api(`documents/${doc.id}`, { method: "PATCH", body });
          onDone();
        } catch (x: any) { setErr(x.message); }
      }}>
        {err && <div className="alert error">{err}</div>}
        <div className="field"><label htmlFor="et">Title</label><input id="et" type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
          {doc.title_is_custom && <button type="button" className="btn small ghost" onClick={() => api(`documents/${doc.id}`, { method: "PATCH", body: { reset_title: true } }).then(onDone)}>Use generated name</button>}</div>
        <div className="field"><label htmlFor="ety">Type</label><select id="ety" value={type} onChange={(e) => setType(e.target.value)}><option value="">Not set</option>{meta?.types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></div>
        <div className="field"><label htmlFor="eco">Issuer / correspondent</label><input id="eco" type="text" list="corrs" value={corr} onChange={(e) => setCorr(e.target.value)} /><datalist id="corrs">{meta?.correspondents.map((c) => <option key={c.id} value={c.name} />)}</datalist></div>
        <div className="field"><label htmlFor="eta">Tags (comma separated)</label><input id="eta" type="text" value={tags} onChange={(e) => setTags(e.target.value)} /></div>
        <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary">Save</button></div>
      </form>
    </Modal>
  );
}

export default function DocumentPanel({ id, full, onChanged }: { id: string; full?: boolean; onChanged?: () => void }) {
  const { session } = useSession();
  const nav = useNavigate();
  const toast = useToast();
  const [doc, setDoc] = useState<DocDetail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("details");
  const [dialog, setDialog] = useState<string>("");
  const [ocrText, setOcrText] = useState<string | null>(null);
  const [similar, setSimilar] = useState<(DocRow & { reasons: string[] })[] | null>(null);
  const load = () => api<DocDetail>(`documents/${id}`).then((d) => { setDoc(d); setError(""); }).catch((e) => setError(e.status === 404 ? "This document does not exist or you do not have access to it." : e.message));
  useEffect(() => { setDoc(null); setTab("details"); setOcrText(null); setSimilar(null); load(); }, [id]);
  useEffect(() => {
    if (!doc || !["queued", "processing"].includes(doc.state)) return;
    const t = setTimeout(load, 4000);
    return () => clearTimeout(t);
  }, [doc]);
  useEffect(() => {
    if (tab === "text" && ocrText === null) api(`documents/${id}/text`).then((r) => setOcrText(r.text));
    if (tab === "similar" && similar === null) api(`documents/${id}/similar`).then((r) => setSimilar(r.similar));
  }, [tab]);
  if (error) return <div className="alert error" style={{ margin: "1rem" }}>{error}</div>;
  if (!doc) return <div style={{ padding: "1rem" }}><Skeleton lines={8} /></div>;
  const changed = () => { load(); onChanged?.(); };
  const can = (c: string) => doc.caps.includes(c);
  const v = doc.current_version;

  return (
    <div style={{ padding: full ? 0 : "1rem" }} className="stack">
      <div className="row between" style={{ alignItems: "flex-start" }}>
        <div className="grow">
          <h2 style={{ fontSize: full ? "1.6rem" : "1.25rem", marginBottom: ".2rem" }}>{doc.title}</h2>
          <div className="row small muted"><StateBadge state={doc.state} /><ExpiryBadge expiry={doc.expiry} />{v && <span>{v.original_name} · {formatBytes(v.size)} · v{v.number}</span>}{doc.archived && <span className="badge neutral">Archived</span>}</div>
        </div>
        <div className="row">
          {can("download") && v && <a className="btn primary" href={`/api/documents/${doc.id}/file?download=1`}><Icon name="download" /> Download</a>}
          {(can("share") || can("download")) && <button className="btn" onClick={() => setDialog("share")}><Icon name="share" /> Share</button>}
          {!full ? <Link className="btn" to={`/documents/${doc.id}`}><Icon name="external" /> Open full page</Link> : null}
          <div style={{ position: "relative" }}>
            <button className="btn" aria-haspopup="menu" aria-expanded={dialog === "menu"} onClick={() => setDialog(dialog === "menu" ? "" : "menu")} aria-label="More actions"><Icon name="more" /></button>
            {dialog === "menu" && (
              <div className="suggest" role="menu" style={{ right: 0, left: "auto", minWidth: 230 }}>
                {can("edit") && <button role="menuitem" onClick={() => setDialog("edit")}>Edit details</button>}
                {can("version") && <button role="menuitem" onClick={() => setDialog("version")}>Upload new version (better scan)</button>}
                {doc.folder && <button role="menuitem" onClick={() => setDialog("renew")}>Add renewed document</button>}
                {can("download") && v && <button role="menuitem" onClick={async () => { try { await saveOffline(session!.user!.id, doc, v); toast("Saved for offline use on this device"); } catch (e: any) { toast(e.message, "error"); } setDialog(""); }}>Save for offline use</button>}
                <button role="menuitem" onClick={() => setDialog("perms")}>Who has access</button>
                {can("edit") && <button role="menuitem" onClick={() => api(`documents/${doc.id}/reprocess`, { method: "POST" }).then(() => { toast("Processing queued"); setDialog(""); changed(); })}>Re-run OCR / preview</button>}
                {can("archive") && !doc.archived && <button role="menuitem" onClick={() => setDialog("archive")}>Archive</button>}
              </div>
            )}
          </div>
        </div>
      </div>
      <Preview doc={doc} />
      <div className="tabs" role="tablist">
        {[["details", "Details"], ["text", "Text"], ["versions", `Versions (${doc.versions.length})`], ["similar", "More like this"], ...(doc.history.length ? [["history", "History"]] : [])].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{l}</button>
        ))}
        {doc.fields.length > 0 && !doc.fields.some((f) => f.status === "proposed") && <span className="badge ok" style={{ marginLeft: "auto", alignSelf: "center" }}><Icon name="check" size={13} /> Details confirmed</span>}
      </div>
      {tab === "details" && <Fields doc={doc} onChange={changed} />}
      {tab === "text" && (ocrText === null ? <Skeleton /> : ocrText ? (
        <div><div className="row between"><span className="small muted">{v?.ocr_applied ? "Recognised locally with OCR — check important values." : "Text extracted from the file."}</span><CopyButton label="Text" getValue={() => ocrText} /></div><pre className="preview-text">{ocrText}</pre></div>
      ) : <div className="empty">No text available for this document.</div>)}
      {tab === "versions" && (
        <table className="responsive"><thead><tr><th>Version</th><th>File</th><th>Added</th><th /></tr></thead><tbody>
          {doc.versions.map((ver) => (
            <tr key={ver.id}>
              <td>v{ver.number} {ver.id === v?.id && <span className="badge">Current</span>}{ver.pdfa_check && (
                <span className={`badge ${ver.pdfa_check.compliant ? "ok" : "soon"}`}
                  title={ver.pdfa_check.compliant ? `${ver.pdfa_check.profile} — ${ver.pdfa_check.full_validation ? "validated by veraPDF" : "structural check, not a full validation"}` : ver.pdfa_check.failed_rules.map((r) => r.description).join("; ")}>
                  {ver.pdfa_check.compliant ? "PDF/A ✓" : "PDF/A issues"}{ver.pdfa_check.full_validation ? "" : "*"}
                </span>
              )}</td>
              <td>{ver.original_name}<div className="small muted">{formatBytes(ver.size)} · {ver.comment}</div><div className="small muted mono" title="SHA-256 checksum">{ver.sha256.slice(0, 16)}…</div></td>
              <td>{formatDateTime(ver.created_at)}<div className="small muted">{ver.created_by}</div></td>
              <td className="row">
                {can("download") && <a className="btn small" href={`/api/documents/${doc.id}/file?download=1&version=${ver.id}`}>Download</a>}
                {can("version") && ver.id !== v?.id && <button className="btn small" onClick={() => api(`documents/${doc.id}/versions/${ver.id}/current`, { method: "POST" }).then(changed)}>Make current</button>}
              </td>
            </tr>
          ))}
        </tbody></table>
      )}
      {tab === "similar" && (similar === null ? <Skeleton /> : similar.length === 0 ? <div className="empty">No similar documents found.</div> : (
        <div>{similar.map((s) => <Link key={s.id} to={`/documents/${s.id}`} className="list-item" style={{ color: "inherit", textDecoration: "none" }}><span className="doc-icon"><Icon name="file" size={18} /></span><div className="grow"><div style={{ fontWeight: 600 }}>{s.title}</div><div className="small muted">{s.owner.display_name} · {s.reasons.join(", ")}</div></div></Link>)}
          <p className="small muted">Similarity uses shared words, type, issuer and tags — not AI.</p></div>
      ))}
      {tab === "history" && (
        <ul className="small">{doc.history.map((h, i) => <li key={i}>{formatDateTime(h.at)} — {h.actor || "system"}: {h.action.replace(/_/g, " ")} {Object.keys(h.changes || {}).length ? <span className="muted">{JSON.stringify(h.changes)}</span> : null}</li>)}</ul>
      )}
      {dialog === "edit" && <EditDialog doc={doc} onClose={() => setDialog("")} onDone={() => { setDialog(""); changed(); }} />}
      {(dialog === "version" || dialog === "renew") && <VersionDialog doc={doc} mode={dialog} onClose={() => setDialog("")} onDone={(newId) => { setDialog(""); changed(); if (newId) nav(`/documents/${newId}`); }} />}
      {dialog === "share" && <ShareDialog doc={doc} onClose={() => setDialog("")} />}
      {dialog === "perms" && <PermissionsDialog target={{ kind: "documents", id: doc.id, name: doc.title }} onClose={() => { setDialog(""); changed(); }} />}
      {dialog === "archive" && (
        <Confirm title="Archive document" message={<p>“{doc.title}” will be hidden from everyone except the main administrator, its public links stop working and reminders stop. The administrator can restore it.</p>}
          confirmLabel="Archive" danger onClose={() => setDialog("")}
          onConfirm={async () => { await api(`documents/${doc.id}/archive`, { method: "POST" }); toast("Document archived"); setDialog(""); onChanged?.(); if (full) nav("/folders"); }} />
      )}
      <p className="small muted">Added {formatDateTime(doc.created_at)}. Viewing a document shows its content; disabling download cannot prevent screenshots.</p>
    </div>
  );
}
