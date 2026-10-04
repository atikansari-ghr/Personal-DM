import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, formatBytes, formatDate } from "../api";
import DocumentPanel from "../components/DocumentPanel";
import { PanelHandles, usePanelWidths } from "../components/PanelResizer";
import PermissionsDialog from "../components/PermissionsDialog";
import UploadDialog from "../components/UploadDialog";
import { Confirm, EmojiPicker, ExpiryBadge, Icon, Modal, Skeleton, StateBadge, useToast } from "../components/ui";
import { useSession } from "../session";
import type { DocRow, FolderNode } from "../types";

function TreeNode({ node, children, active, expanded, toggle, select, level }: {
  node: FolderNode; children: FolderNode[]; active: string; expanded: Set<string>; toggle: (id: string) => void; select: (id: string) => void; level: number;
}) {
  const open = expanded.has(node.id);
  return (
    <li role="treeitem" aria-expanded={children.length ? open : undefined} aria-selected={active === node.id} aria-level={level}>
      <div className={`tree-node ${active === node.id ? "active" : ""} ${node.path_only ? "path-only" : ""}`}
        onClick={() => !node.path_only && select(node.id)} tabIndex={node.path_only ? -1 : 0}
        onKeyDown={(e) => {
          if (e.key === "Enter") select(node.id);
          if (e.key === "ArrowRight" && !open) toggle(node.id);
          if (e.key === "ArrowLeft" && open) toggle(node.id);
        }}>
        <button className="caret" tabIndex={-1} aria-label={open ? "Collapse" : "Expand"} onClick={(e) => { e.stopPropagation(); toggle(node.id); }} style={{ visibility: children.length ? "visible" : "hidden" }}>{open ? "▾" : "▸"}</button>
        <span aria-hidden="true">{node.emoji || "📁"}</span>
        <span>{node.name}</span>
        {node.count > 0 && <span className="count">{node.count}</span>}
      </div>
      {open && children.length > 0 && <ul role="group">{children.map((c) => <TreeChild key={c.id} node={c} active={active} expanded={expanded} toggle={toggle} select={select} level={level + 1} />)}</ul>}
    </li>
  );
}
let childrenOf: Map<string | null, FolderNode[]> = new Map();
function TreeChild(props: { node: FolderNode; active: string; expanded: Set<string>; toggle: (id: string) => void; select: (id: string) => void; level: number }) {
  return <TreeNode {...props} children={childrenOf.get(props.node.id) || []} />;
}

export default function FoldersPage() {
  const { folderId, docId } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { session } = useSession();
  const [folders, setFolders] = useState<FolderNode[] | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [docs, setDocs] = useState<DocRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [view, setView] = useState<"list" | "grid">(() => (localStorage.getItem("pd-view") as any) || "list");
  const [dialog, setDialog] = useState("");
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showTree, setShowTree] = useState(!folderId);
  const panels = usePanelWidths(session?.user?.id);
  const treeRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLElement>(null);
  const fullPage = session?.preferences?.layout === "full_page";

  const loadFolders = () => api<{ folders: FolderNode[] }>("folders").then((r) => setFolders(r.folders));
  useEffect(() => { loadFolders(); }, []);
  const byId = useMemo(() => new Map((folders || []).map((f) => [f.id, f])), [folders]);
  childrenOf = useMemo(() => {
    const m = new Map<string | null, FolderNode[]>();
    (folders || []).forEach((f) => {
      const key = f.parent && byId.has(f.parent) ? f.parent : null;
      m.set(key, [...(m.get(key) || []), f]);
    });
    return m;
  }, [folders, byId]);
  const roots = childrenOf.get(null) || [];
  // default selection: first viewable folder; expand path to active
  useEffect(() => {
    if (!folders) return;
    if (!folderId) {
      const first = folders.find((f) => f.kind === "personal_root" && !f.path_only) || folders.find((f) => !f.path_only);
      if (first) nav(`/folders/${first.id}`, { replace: true });
      return;
    }
    const exp = new Set(expanded);
    roots.forEach((r) => exp.add(r.id));
    let n = byId.get(folderId);
    while (n?.parent) { exp.add(n.parent); n = byId.get(n.parent); }
    setExpanded(exp);
  }, [folders, folderId]);
  const loadDocs = () => {
    if (!folderId) return;
    setDocs(null);
    api<{ documents: DocRow[]; total: number }>("documents", { query: { folder: folderId, limit: 200 } }).then((r) => { setDocs(r.documents); setTotal(r.total); });
  };
  useEffect(() => { loadDocs(); setSelected(new Set()); }, [folderId]);
  const folder = folderId ? byId.get(folderId) : undefined;
  const path: FolderNode[] = [];
  for (let n = folder; n; n = n.parent ? byId.get(n.parent) : undefined) path.unshift(n);
  const subfolders = folderId ? childrenOf.get(folderId) || [] : [];
  const can = (c: string) => !!folder?.caps.includes(c);
  const openDoc = (id: string) => (fullPage ? nav(`/documents/${id}`) : nav(`/folders/${folderId}/${id}`));

  const bulk = async (action: string, value?: string) => {
    const r = await api<any>("documents/bulk", { body: { ids: [...selected], action, value } });
    toast(`${r.succeeded} updated${r.failed ? `, ${r.failed} not permitted` : ""}`, r.failed ? "error" : "ok");
    setSelected(new Set());
    loadDocs();
    loadFolders();
  };

  if (!folders) return <Skeleton lines={8} />;
  if (!folders.length) return <div className="empty"><h2>No folders yet</h2><p>Ask your family administrator to give you access.</p></div>;

  return (
    <div>
      <div className="page-head">
        <h1>Folders</h1>
        <div className="row">
          <Link className="btn" to="/imports/new"><Icon name="folder" /> Import folder</Link>
          {can("upload") && <button className="btn primary" onClick={() => setDialog("upload")}><Icon name="upload" /> Upload</button>}
          <div className="row" role="group" aria-label="View mode" style={{ gap: 0 }}>
            <button className={`btn ${view === "list" ? "primary" : ""}`} aria-pressed={view === "list"} onClick={() => { setView("list"); localStorage.setItem("pd-view", "list"); }} aria-label="List view"><Icon name="list" /></button>
            <button className={`btn ${view === "grid" ? "primary" : ""}`} aria-pressed={view === "grid"} onClick={() => { setView("grid"); localStorage.setItem("pd-view", "grid"); }} aria-label="Grid view"><Icon name="grid" /></button>
          </div>
        </div>
      </div>
      <div className={`browser ${docId ? "has-doc" : ""} ${showTree ? "show-tree" : ""}`} style={panels.style}>
        <PanelHandles treeRef={treeRef} listRef={listRef} widths={panels.widths} save={panels.save} reset={panels.reset} />
        <section className="tree tree-pane" aria-label="Folder tree" ref={treeRef}>
          <ul role="tree">{roots.map((r) => <TreeNode key={r.id} node={r} children={childrenOf.get(r.id) || []} active={folderId || ""} expanded={expanded} level={1}
            toggle={(id) => setExpanded((e) => { const n = new Set(e); n.has(id) ? n.delete(id) : n.add(id); return n; })}
            select={(id) => { setShowTree(false); nav(`/folders/${id}`); }} />)}</ul>
        </section>
        <section className="list-pane" aria-label="Documents" ref={listRef}>
          <div className="row between" style={{ paddingRight: ".6rem" }}>
            <nav className="breadcrumb" aria-label="Breadcrumb">
              <button className="btn small ghost" onClick={() => setShowTree(true)} aria-label="Show folders" style={{ padding: "0 .3rem" }}>☰</button>
              {path.filter((p) => p.parent).map((p, i, arr) => (
                <span key={p.id}>{i < arr.length - 1 ? <><Link to={`/folders/${p.id}`}>{p.emoji} {p.name}</Link> /</> : <strong style={{ color: "var(--ink)" }}>{p.emoji} {p.name}</strong>}</span>
              ))}
            </nav>
            {folder && (
              <div style={{ position: "relative" }}>
                <button className="icon-btn" aria-label="Folder actions" aria-haspopup="menu" onClick={() => setDialog(dialog === "fmenu" ? "" : "fmenu")}><Icon name="more" /></button>
                {dialog === "fmenu" && (
                  <div className="suggest" role="menu" style={{ right: 0, left: "auto", minWidth: 220 }}>
                    {can("organize") && <button role="menuitem" onClick={() => { setName(""); setEmoji(""); setDialog("new"); }}>New subfolder</button>}
                    {can("organize") && <button role="menuitem" onClick={() => { setName(folder.name); setEmoji(folder.emoji); setDialog("rename"); }}>Rename / emoji</button>}
                    {can("organize") && <button role="menuitem" onClick={() => api<{ created: number }>(`folders/${folder.id}/apply-template`, { method: "POST" }).then((r) => { toast(r.created ? `${r.created} template folder(s) added` : "All template folders already exist"); setDialog(""); loadFolders(); }).catch((e) => toast(e.message, "error"))}>Apply folder template</button>}
                    <button role="menuitem" onClick={() => setDialog("perms")}>Who has access</button>
                    {can("download") && <a role="menuitem" className="suggest-link" style={{ display: "block", padding: ".55rem .8rem", color: "inherit", textDecoration: "none" }} href={`/api/export/download?folder=${folder.id}`}>Download folder (ZIP)</a>}
                    {can("archive") && folder.parent && <button role="menuitem" onClick={() => setDialog("archive")}>Archive folder</button>}
                  </div>
                )}
              </div>
            )}
          </div>
          {selected.size > 0 && (
            <div className="row card" style={{ margin: ".5rem", padding: ".5rem" }}>
              <strong>{selected.size} selected</strong>
              <button className="btn small" onClick={() => { const t = prompt("Tag to add"); if (t) bulk("tag_add", t); }}>Add tag</button>
              <button className="btn small" onClick={() => setDialog("move")}>Move…</button>
              <button className="btn small danger" onClick={() => bulk("archive")}>Archive</button>
              <button className="btn small ghost" onClick={() => setSelected(new Set())}>Clear</button>
            </div>
          )}
          {subfolders.length > 0 && (
            <div className="row" style={{ padding: ".3rem .7rem" }}>
              {subfolders.filter((s) => !s.path_only).map((s) => <Link key={s.id} to={`/folders/${s.id}`} className="btn small">{s.emoji} {s.name} <span className="muted">{s.count || ""}</span></Link>)}
            </div>
          )}
          {docs === null ? <div style={{ padding: "1rem" }}><Skeleton /></div> : docs.length === 0 ? (
            <div className="empty">This folder has no documents{can("upload") ? " yet — drop files with Upload." : "."}</div>
          ) : view === "list" ? docs.map((d) => (
            <div key={d.id} className={`doc-card ${docId === d.id ? "active" : ""}`} onClick={() => openDoc(d.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && openDoc(d.id)} role="button" aria-current={docId === d.id}>
              <input type="checkbox" aria-label={`Select ${d.title}`} checked={selected.has(d.id)} onClick={(e) => e.stopPropagation()}
                onChange={(e) => setSelected((s) => { const n = new Set(s); e.target.checked ? n.add(d.id) : n.delete(d.id); return n; })} />
              <span className="doc-icon"><Icon name="file" size={18} /></span>
              <div className="grow"><div style={{ fontWeight: 600 }}>{d.title}</div><div className="small muted">{(d.format || "").toUpperCase()} · {formatBytes(d.size)} · {formatDate(d.created_at)}</div></div>
              <StateBadge state={d.state} />{d.expiry && d.expiry.level !== "ok" && <ExpiryBadge expiry={d.expiry} />}
            </div>
          )) : (
            <div className="doc-grid">{docs.map((d) => (
              <div key={d.id} className={`doc-card ${docId === d.id ? "active" : ""}`} onClick={() => openDoc(d.id)} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && openDoc(d.id)}>
                {d.has_thumbnail ? <img className="thumb" src={`/api/documents/${d.id}/thumbnail`} alt="" loading="lazy" /> : <div className="thumb" aria-hidden="true">📄</div>}
                <div className="small" style={{ fontWeight: 600 }}>{d.title}</div>
                <ExpiryBadge expiry={d.expiry} />
              </div>
            ))}</div>
          )}
          {docs && total > docs.length && <p className="small muted" style={{ padding: ".6rem" }}>Showing {docs.length} of {total}. Use search to narrow down.</p>}
        </section>
        <section className="detail-pane" aria-label="Document details">
          {docId ? (
            <>
              <button className="btn small ghost hide-desktop-detail" onClick={() => nav(`/folders/${folderId}`)} style={{ margin: ".5rem" }}>← Back to folder</button>
              <DocumentPanel id={docId} onChanged={() => { loadDocs(); loadFolders(); }} />
            </>
          ) : <div className="empty">Select a document to preview it here.</div>}
        </section>
      </div>
      {dialog === "upload" && folderId && <UploadDialog folderId={folderId} onClose={() => setDialog("")} onDone={() => { setDialog(""); loadDocs(); loadFolders(); }} />}
      {(dialog === "new" || dialog === "rename") && folder && (
        <Modal title={dialog === "new" ? "New folder" : "Rename folder"} onClose={() => setDialog("")}>
          <form className="stack" onSubmit={async (e) => {
            e.preventDefault();
            try {
              if (dialog === "new") { const f = await api<FolderNode>("folders", { body: { parent: folder.id, name, emoji: emoji || undefined } }); nav(`/folders/${f.id}`); }
              else await api(`folders/${folder.id}`, { method: "PATCH", body: { name, emoji } });
              setDialog(""); loadFolders();
            } catch (x: any) { toast(x.message, "error"); }
          }}>
            <div className="field"><label htmlFor="fname">Name</label><input id="fname" type="text" value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div className="field"><p style={{ fontWeight: 550, margin: "0 0 .3rem" }}>Emoji <span className="muted small">(optional — a suggestion is made from the name)</span></p><EmojiPicker value={emoji} onPick={(e) => setEmoji(e === emoji ? "" : e)} /></div>
            <p className="small muted">Emoji are only labels; they never change who can see the folder.</p>
            <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={() => setDialog("")}>Cancel</button><button className="btn primary" disabled={!name.trim()}>Save</button></div>
          </form>
        </Modal>
      )}
      {dialog === "move" && (
        <Modal title="Move documents" onClose={() => setDialog("")}>
          <MoveForm folders={folders} onMove={(target) => { setDialog(""); bulk("move", target); }} />
        </Modal>
      )}
      {dialog === "perms" && folder && <PermissionsDialog target={{ kind: "folders", id: folder.id, name: folder.name }} onClose={() => { setDialog(""); loadFolders(); }} />}
      {dialog === "archive" && folder && (
        <Confirm title="Archive folder" danger confirmLabel="Archive" onClose={() => setDialog("")}
          message={<p>“{folder.name}” and everything inside will be hidden from everyone but the main administrator, and public links inside it stop working. Nothing is deleted.</p>}
          onConfirm={async () => { try { await api(`folders/${folder.id}/archive`, { method: "POST" }); setDialog(""); nav(folder.parent ? `/folders/${folder.parent}` : "/folders"); loadFolders(); } catch (x: any) { toast(x.message, "error"); } }} />
      )}
    </div>
  );
}

function MoveForm({ folders, onMove }: { folders: FolderNode[]; onMove: (id: string) => void }) {
  const [target, setTarget] = useState("");
  const options = folders.filter((f) => f.caps.includes("upload"));
  return (
    <div className="stack">
      <select aria-label="Destination folder" value={target} onChange={(e) => setTarget(e.target.value)}>
        <option value="">Choose destination…</option>
        {options.map((f) => <option key={f.id} value={f.id}>{f.emoji} {f.name}</option>)}
      </select>
      <p className="small muted">Moving can change who can see a document (it inherits the new folder's access). Items you cannot move are reported.</p>
      <button className="btn primary" disabled={!target} onClick={() => onMove(target)}>Move</button>
    </div>
  );
}
