import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, formatBytes, formatDate } from "../api";
import DocumentPanel from "../components/DocumentPanel";
import { PanelHandles, usePanelWidths } from "../components/PanelResizer";
import PermissionsDialog from "../components/PermissionsDialog";
import UploadDialog from "../components/UploadDialog";
import FileTypeIcon from "../components/FileTypeIcon";
import FolderPicker, { descendantIds, FolderIcon, folderChildren, folderLabel } from "../components/FolderPicker";
import { Avatar, Confirm, EmojiPicker, ExpiryBadge, Icon, Modal, Skeleton, StateBadge, useToast } from "../components/ui";
import { useSession } from "../session";
import type { DocRow, FolderNode } from "../types";

type Drag = { type: "docs"; ids: string[] } | { type: "folder"; id: string };
type TreeProps = {
  node: FolderNode; active: string; expanded: Set<string>; toggle: (id: string, open?: boolean) => void; select: (id: string) => void; level: number;
  me?: string | null; dnd: Dnd;
};
interface Dnd {
  drag: React.MutableRefObject<Drag | null>;
  over: string;
  setOver: (id: string) => void;
  why: (target: FolderNode) => string; // "" = drop allowed
  drop: (target: FolderNode) => void;
  startFolder: (f: FolderNode) => boolean;
}

function TreeNode({ node, active, expanded, toggle, select, level, me, dnd }: TreeProps) {
  const children = childrenOf.get(node.id) || [];
  const open = expanded.has(node.id);
  const hoverTimer = useRef<number>();
  const draggable = !node.path_only && dnd.startFolder(node);
  return (
    <li role="treeitem" aria-expanded={children.length ? open : undefined} aria-selected={active === node.id} aria-level={level}>
      <div className={`tree-node ${active === node.id ? "active" : ""} ${node.path_only ? "path-only" : ""} ${dnd.over === node.id ? "drop-ok" : ""}`}
        onClick={() => !node.path_only && select(node.id)} tabIndex={node.path_only ? -1 : 0}
        draggable={draggable}
        onDragStart={(e) => { e.stopPropagation(); dnd.drag.current = { type: "folder", id: node.id }; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", node.name); }}
        onDragEnd={() => { dnd.drag.current = null; dnd.setOver(""); }}
        onDragOver={(e) => {
          if (!dnd.drag.current || node.path_only || dnd.why(node)) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
          if (dnd.over !== node.id) {
            dnd.setOver(node.id);
            window.clearTimeout(hoverTimer.current);
            if (children.length && !open) hoverTimer.current = window.setTimeout(() => toggle(node.id, true), 700);
          }
        }}
        onDragLeave={() => { window.clearTimeout(hoverTimer.current); }}
        onDrop={(e) => { e.preventDefault(); window.clearTimeout(hoverTimer.current); dnd.setOver(""); dnd.drop(node); }}
        onKeyDown={(e) => {
          if (e.key === "Enter") select(node.id);
          if (e.key === "ArrowRight" && !open) toggle(node.id);
          if (e.key === "ArrowLeft" && open) toggle(node.id);
        }}>
        <button className="caret" tabIndex={-1} aria-label={open ? "Collapse" : "Expand"} onClick={(e) => { e.stopPropagation(); toggle(node.id); }} style={{ visibility: children.length ? "visible" : "hidden" }}>{open ? "▾" : "▸"}</button>
        <FolderIcon f={node} />
        <span>{folderLabel(node, me)}</span>
        {node.count > 0 && <span className="count">{node.count}</span>}
      </div>
      {open && children.length > 0 && <ul role="group">{children.map((c) => <TreeNode key={c.id} node={c} active={active} expanded={expanded} toggle={toggle} select={select} level={level + 1} me={me} dnd={dnd} />)}</ul>}
    </li>
  );
}
let childrenOf: Map<string | null, FolderNode[]> = new Map();

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
  const me = session?.user?.id || null;
  childrenOf = useMemo(() => folderChildren(folders || [], me), [folders, me]);
  const myRoot = (folders || []).find((f) => f.kind === "personal_root" && f.owner === me && !f.path_only);
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
    exp.add(folderId);
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

  // ---- moving (drag and drop and "Move to…" share the same checks and the same server calls)
  const drag = useRef<Drag | null>(null);
  const [over, setOver] = useState("");
  const [moving, setMoving] = useState<Drag | null>(null);
  const docsReason = (ids: string[]) => (t: FolderNode) => {
    if (t.path_only) return "You cannot open this folder";
    if (!t.caps.includes("upload")) return "You cannot add documents here";
    if (docs && ids.every((id) => docs.find((d) => d.id === id)?.folder === t.id)) return "Already in this folder";
    return "";
  };
  const folderReason = (id: string) => {
    const blocked = descendantIds(folders || [], id);
    const f = byId.get(id);
    return (t: FolderNode) => {
      if (t.path_only) return "You cannot open this folder";
      if (blocked.has(t.id)) return "A folder cannot go inside itself";
      if (f && f.parent === t.id) return "Already in this folder";
      if (!t.caps.includes("organize")) return "You cannot organise this folder";
      if ((childrenOf.get(t.id) || []).some((c) => f && c.name.toLowerCase() === f.name.toLowerCase())) return "A folder with the same name is already there";
      return "";
    };
  };
  const whyFor = (d: Drag | null) => (t: FolderNode) => (!d ? "Nothing to move" : d.type === "docs" ? docsReason(d.ids)(t) : folderReason(d.id)(t));
  const moveTo = async (d: Drag, target: FolderNode) => {
    try {
      if (d.type === "docs") {
        const r = await api<any>("documents/bulk", { body: { ids: d.ids, action: "move", value: target.id } });
        const errors = (r.results || []).filter((x: any) => !x.ok).map((x: any) => x.error);
        toast(r.failed ? `${r.succeeded} moved, ${r.failed} not moved: ${[...new Set(errors)].join("; ")}` : `${r.succeeded} moved to ${folderLabel(target, me)}`, r.failed ? "error" : "ok");
        setSelected(new Set());
      } else {
        await api(`folders/${d.id}`, { method: "PATCH", body: { parent: target.id } });
        toast(`Folder moved to ${folderLabel(target, me)}`);
      }
    } catch (x: any) {
      toast(x.message, "error");
    }
    loadDocs();
    loadFolders();
  };
  const dnd: Dnd = {
    drag, over, setOver,
    why: (t) => whyFor(drag.current)(t),
    drop: (t) => { const d = drag.current; drag.current = null; if (d && !whyFor(d)(t)) moveTo(d, t); },
    startFolder: (f) => !!f.parent && f.kind === "normal" && f.caps.includes("organize"),
  };
  const startDocDrag = (e: React.DragEvent, d: DocRow) => {
    const ids = selected.has(d.id) ? [...selected] : [d.id];
    drag.current = { type: "docs", ids };
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", ids.length > 1 ? `${ids.length} documents` : d.title);
  };
  const endDrag = () => { drag.current = null; setOver(""); };
  const [rowMenu, setRowMenu] = useState("");

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
          {myRoot && (
            <Link to={`/folders/${myRoot.id}`} className={`my-area ${folderId === myRoot.id ? "active" : ""}`} onClick={() => setShowTree(false)}
              aria-current={folderId === myRoot.id ? "page" : undefined}>
              <Avatar user={session?.user} size="sm" />
              <span>My Documents<small>{session?.user?.display_name}</small></span>
            </Link>
          )}
          <ul role="tree" aria-label="Folders">{roots.map((r) => <TreeNode key={r.id} node={r} active={folderId || ""} expanded={expanded} level={1} me={me} dnd={dnd}
            toggle={(id, force) => setExpanded((e) => { const n = new Set(e); (force ?? !n.has(id)) ? n.add(id) : n.delete(id); return n; })}
            select={(id) => { setShowTree(false); nav(`/folders/${id}`); }} />)}</ul>
        </section>
        <section className="list-pane" aria-label="Documents" ref={listRef}>
          <div className="row between" style={{ paddingRight: ".6rem" }}>
            <nav className="breadcrumb" aria-label="Breadcrumb">
              <button className="btn small ghost" onClick={() => setShowTree(true)} aria-label="Show folders" style={{ padding: "0 .3rem" }}>☰</button>
              {path.filter((p) => p.parent).map((p, i, arr) => (
                <span key={p.id}>{i < arr.length - 1 ? <><Link to={`/folders/${p.id}`}>{p.emoji} {folderLabel(p, me)}</Link> /</> : <strong style={{ color: "var(--ink)" }}>{p.emoji} {folderLabel(p, me)}</strong>}</span>
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
                    {dnd.startFolder(folder) && <button role="menuitem" onClick={() => { setDialog(""); setMoving({ type: "folder", id: folder.id }); }}>Move to…</button>}
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
              <button className="btn small" onClick={() => setMoving({ type: "docs", ids: [...selected] })}>Move to…</button>
              <button className="btn small danger" onClick={() => bulk("archive")}>Archive</button>
              <button className="btn small ghost" onClick={() => setSelected(new Set())}>Clear</button>
            </div>
          )}
          {subfolders.length > 0 && (
            <div className="row" style={{ padding: ".3rem .7rem" }}>
              {subfolders.filter((s) => !s.path_only).map((s) => <Link key={s.id} to={`/folders/${s.id}`} className={`btn small ${over === s.id ? "drop-ok" : ""}`}
                onDragOver={(e) => { if (drag.current && !dnd.why(s)) { e.preventDefault(); setOver(s.id); } }} onDragLeave={() => setOver("")}
                onDrop={(e) => { e.preventDefault(); setOver(""); dnd.drop(s); }}>{s.emoji} {s.name} <span className="muted">{s.count || ""}</span></Link>)}
            </div>
          )}
          {docs === null ? <div style={{ padding: "1rem" }}><Skeleton /></div> : docs.length === 0 ? (
            <div className="empty">This folder has no documents{can("upload") ? " yet — drop files with Upload." : "."}</div>
          ) : view === "list" ? docs.map((d) => (
            <div key={d.id} className={`doc-card ${docId === d.id ? "active" : ""}`} onClick={() => openDoc(d.id)}
              draggable={d.caps.includes("organize")} onDragStart={(e) => startDocDrag(e, d)} onDragEnd={endDrag}>
              <input type="checkbox" aria-label={`Select ${d.title}`} checked={selected.has(d.id)} onClick={(e) => e.stopPropagation()}
                onChange={(e) => setSelected((s) => { const n = new Set(s); e.target.checked ? n.add(d.id) : n.delete(d.id); return n; })} />
              <FileTypeIcon kind={d.file_kind} label={d.file_label} />
              <div className="grow"><button type="button" className="doc-open" aria-current={docId === d.id ? "true" : undefined} onClick={(e) => { e.stopPropagation(); openDoc(d.id); }}>{d.title}</button><div className="small muted">{d.file_label} · {formatBytes(d.size)} · {formatDate(d.created_at)}</div></div>
              <StateBadge state={d.state} />{d.expiry && d.expiry.level !== "ok" && <ExpiryBadge expiry={d.expiry} />}
              <RowMenu d={d} open={rowMenu === d.id} setOpen={(o) => setRowMenu(o ? d.id : "")} openDoc={openDoc} move={() => setMoving({ type: "docs", ids: [d.id] })} />
            </div>
          )) : (
            <div className="doc-grid">{docs.map((d) => (
              <div key={d.id} className={`doc-card ${docId === d.id ? "active" : ""}`} onClick={() => openDoc(d.id)}
                draggable={d.caps.includes("organize")} onDragStart={(e) => startDocDrag(e, d)} onDragEnd={endDrag}>
                <div className="thumb-wrap">
                  {d.has_thumbnail ? <img className="thumb" src={`/api/documents/${d.id}/thumbnail`} alt="" loading="lazy" draggable={false} /> : <div className="thumb" aria-hidden="true"><FileTypeIcon kind={d.file_kind} size="lg" /></div>}
                  {d.has_thumbnail && <FileTypeIcon kind={d.file_kind} label={d.file_label} size="sm" />}
                </div>
                <div className="row between" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                  <button type="button" className="doc-open small" aria-current={docId === d.id ? "true" : undefined} onClick={(e) => { e.stopPropagation(); openDoc(d.id); }}>{d.title}</button>
                  <RowMenu d={d} open={rowMenu === d.id} setOpen={(o) => setRowMenu(o ? d.id : "")} openDoc={openDoc} move={() => setMoving({ type: "docs", ids: [d.id] })} />
                </div>
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
      {moving && (
        <MoveDialog folders={folders} me={me} moving={moving} why={whyFor(moving)} near={moving.type === "folder" ? byId.get(moving.id)?.parent : folderId}
          what={moving.type === "folder" ? `the folder “${byId.get(moving.id)?.name}” and everything in it` : moving.ids.length === 1 ? `“${docs?.find((x) => x.id === moving.ids[0])?.title || "this document"}”` : `${moving.ids.length} documents`}
          onClose={() => setMoving(null)} onMove={(t) => { const d = moving; setMoving(null); moveTo(d, t); }} />
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

function RowMenu({ d, open, setOpen, openDoc, move }: { d: DocRow; open: boolean; setOpen: (o: boolean) => void; openDoc: (id: string) => void; move: () => void }) {
  return (
    <div className="row-menu" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Escape") setOpen(false); }}>
      <button className="icon-btn" aria-label={`More actions for ${d.title}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}><Icon name="more" /></button>
      {open && (
        <div className="suggest" role="menu">
          <button role="menuitem" onClick={() => { setOpen(false); openDoc(d.id); }}>Open</button>
          {d.caps.includes("organize") && <button role="menuitem" onClick={() => { setOpen(false); move(); }}>Move to…</button>}
          {d.caps.includes("download") && <a role="menuitem" className="suggest-link" style={{ display: "block", padding: ".55rem .8rem", color: "inherit", textDecoration: "none" }} href={`/api/documents/${d.id}/file?download=1`}>Download</a>}
        </div>
      )}
    </div>
  );
}

function MoveDialog({ folders, me, moving, why, what, onClose, onMove, near }: {
  folders: FolderNode[]; me: string | null; moving: Drag; why: (t: FolderNode) => string; what: string; onClose: () => void; onMove: (t: FolderNode) => void;
  near?: string | null;
}) {
  const [target, setTarget] = useState("");
  const [step, setStep] = useState<"pick" | "confirm">("pick");
  const t = folders.find((f) => f.id === target);
  return (
    <Modal title="Move to…" onClose={onClose}>
      {step === "pick" ? (
        <div className="stack">
          <p className="small muted">Choose where to move {what}. Folders you cannot use are greyed out with the reason.</p>
          <FolderPicker folders={folders} value={target} onChange={setTarget} reason={why} meId={me} near={near} />
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn" onClick={onClose}>Cancel</button>
            <button className="btn primary" disabled={!t || !!why(t)} onClick={() => setStep("confirm")}>Next</button>
          </div>
        </div>
      ) : (
        <div className="stack">
          <p>Move {what} to <strong>{t ? folderLabel(t, me) : ""}</strong>?</p>
          <p className="small muted">{moving.type === "folder" ? "Sub-folders and documents keep their structure." : ""} Items that inherit access will follow the new folder's access rules. Nothing is copied or deleted; if a move is refused nothing changes.</p>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn" onClick={() => setStep("pick")}>Back</button>
            <button className="btn primary" onClick={() => t && onMove(t)}>Move</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
