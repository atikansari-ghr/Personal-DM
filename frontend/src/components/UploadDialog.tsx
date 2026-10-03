import { useEffect, useRef, useState } from "react";
import { api, formatBytes, upload } from "../api";
import { useSession } from "../session";
import type { FolderNode, Meta, User } from "../types";
import { Icon, Modal, useToast } from "./ui";

export function folderLabel(folders: FolderNode[], id: string): string {
  const byId = new Map(folders.map((f) => [f.id, f]));
  const parts: string[] = [];
  let node = byId.get(id);
  let guard = 0;
  while (node && guard++ < 40) {
    if (node.parent) parts.unshift(`${node.emoji} ${node.name}`);
    node = node.parent ? byId.get(node.parent) : undefined;
  }
  return parts.join(" / ") || "Family library";
}

export function FolderSelect({ folders, value, onChange, cap = "upload", id = "folder-select" }: { folders: FolderNode[]; value: string; onChange: (v: string) => void; cap?: string; id?: string }) {
  const options = folders.filter((f) => f.caps.includes(cap)).map((f) => ({ id: f.id, label: folderLabel(folders, f.id) })).sort((a, b) => a.label.localeCompare(b.label));
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose a folder…</option>
      {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
    </select>
  );
}

export default function UploadDialog({ onClose, onDone, folderId, initialFiles }: { onClose: () => void; onDone: () => void; folderId?: string; initialFiles?: File[] }) {
  const { session } = useSession();
  const toast = useToast();
  const [folders, setFolders] = useState<FolderNode[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [members, setMembers] = useState<User[]>([]);
  const [folder, setFolder] = useState(folderId || "");
  const [owner, setOwner] = useState("");
  const [docType, setDocType] = useState("");
  const [title, setTitle] = useState("");
  const [files, setFiles] = useState<File[]>(initialFiles || []);
  const [progress, setProgress] = useState<number | null>(null);
  const [errors, setErrors] = useState<{ file: string; error: string }[]>([]);
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api<{ folders: FolderNode[] }>("folders").then((r) => setFolders(r.folders));
    api<Meta>("metadata").then(setMeta);
    api<{ members: User[] }>("family/members").then((r) => setMembers(r.members));
  }, []);
  const selected = folders.find((f) => f.id === folder);
  const needsOwner = selected && !selected.owner;

  const submit = async () => {
    const form = new FormData();
    form.set("folder", folder);
    if (owner) form.set("owner", owner);
    if (docType) form.set("doc_type", docType);
    if (title && files.length === 1) form.set("title", title);
    files.forEach((f) => form.append("files", f));
    setProgress(0);
    setErrors([]);
    try {
      const r = await upload<{ documents: any[]; errors: any[] }>("documents", form, setProgress);
      toast(`${r.documents.length} document${r.documents.length === 1 ? "" : "s"} uploaded. Processing runs in the background.`);
      if (r.errors.length) setErrors(r.errors);
      else onDone();
    } catch (e: any) {
      setErrors(e.data?.errors?.length ? e.data.errors : [{ file: "", error: e.message }]);
    } finally {
      setProgress(null);
    }
  };

  return (
    <Modal title="Upload documents" onClose={onClose}>
      <div className="stack">
        <div className="field">
          <label htmlFor="folder-select">Folder</label>
          <FolderSelect folders={folders} value={folder} onChange={setFolder} />
        </div>
        {needsOwner && (
          <div className="field">
            <label htmlFor="owner">Whose documents are these?</label>
            <select id="owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">Me ({session?.user?.display_name})</option>
              {members.filter((m) => m.id !== session?.user?.id).map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="dtype">Document type (optional)</label>
          <select id="dtype" value={docType} onChange={(e) => setDocType(e.target.value)}>
            <option value="">Not set</option>
            {meta?.types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <div className="hint">With a type and confirmed dates, names are generated like “Name Passport (2016–2026)”.</div>
        </div>
        {files.length === 1 && (
          <div className="field"><label htmlFor="title">Title (optional)</label><input id="title" type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={files[0].name} /></div>
        )}
        <div className={`dropzone ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); setFiles((f) => [...f, ...Array.from(e.dataTransfer.files)]); }}>
          <p>Drag files here, or</p>
          <div className="row" style={{ justifyContent: "center" }}>
            <button type="button" className="btn" onClick={() => fileInput.current?.click()}><Icon name="file" /> Choose files</button>
            <button type="button" className="btn" onClick={() => cameraInput.current?.click()}><Icon name="camera" /> Take photo</button>
          </div>
          <input ref={fileInput} type="file" multiple hidden onChange={(e) => setFiles((f) => [...f, ...Array.from(e.target.files || [])])} />
          <input ref={cameraInput} type="file" accept="image/*" capture="environment" hidden onChange={(e) => setFiles((f) => [...f, ...Array.from(e.target.files || [])])} />
        </div>
        {files.length > 0 && (
          <ul className="small" aria-label="Selected files">
            {files.map((f, i) => (
              <li key={i} className="row between">
                <span>{f.name} · {formatBytes(f.size)}</span>
                <button className="icon-btn" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}><Icon name="x" size={16} /></button>
              </li>
            ))}
          </ul>
        )}
        <p className="muted small">Uploading the same file twice creates two separate documents. To replace a scan or add a renewed passport, open the existing document instead.</p>
        {progress !== null && <div className="progress" role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${progress * 100}%` }} /></div>}
        {errors.map((e, i) => <div key={i} className="alert error">{e.file && <strong>{e.file}: </strong>}{e.error}</div>)}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!folder || !files.length || progress !== null} onClick={submit}><Icon name="upload" /> Upload {files.length || ""}</button>
        </div>
      </div>
    </Modal>
  );
}
