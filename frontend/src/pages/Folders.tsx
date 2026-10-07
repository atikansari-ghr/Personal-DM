import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, formatBytes, formatDate } from "../api";
import DocumentPanel, { ShareDialog } from "../components/DocumentPanel";
import Menu, { type MenuItem } from "../components/Menu";
import { collectDropped, isExternalFileDrag, uploadDropped, type DropProgress } from "../dropUpload";
import { DOC_VIEWS, normaliseView, SORT_LABELS, type DocView } from "../docview";
import { PanelHandles, usePanelWidths } from "../components/PanelResizer";
import PermissionsDialog from "../components/PermissionsDialog";
import UploadDialog from "../components/UploadDialog";
import FileTypeIcon from "../components/FileTypeIcon";
import FolderPicker, { descendantIds, FolderIcon, folderChildren, folderLabel } from "../components/FolderPicker";
import { AvBadge } from "./settings/SecurityCenter";
import { Avatar, Confirm, EmojiPicker, ExpiryBadge, Icon, Modal, Skeleton, StateBadge, useToast } from "../components/ui";
import { useSession } from "../session";
import type { DocRow, FolderNode } from "../types";

type Drag = { type: "docs"; ids: string[] } | { type: "folder"; id: string };
type TreeProps = {
  node: FolderNode; active: string; expanded: Set<string>; toggle: (id: string, open?: boolean) => void; select: (id: string) => void; level: number;
  me?: string | null; dnd: Dnd; menu: (f: FolderNode) => MenuItem[];
};
interface Dnd {
  drag: React.MutableRefObject<Drag | null>;
  over: string;
  setOver: (id: string) => void;
  why: (target: FolderNode) => string; // "" = drop allowed
  drop: (target: FolderNode) => void;
  startFolder: (f: FolderNode) => boolean;
  external: (target: FolderNode, e: React.DragEvent) => boolean; // files dragged in from the desktop
}

function TreeNode({ node, active, expanded, toggle, select, level, me, dnd, menu }: TreeProps) {
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
          if (!dnd.drag.current && isExternalFileDrag(e) && !node.path_only && node.caps.includes("upload")) {
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
            if (dnd.over !== node.id) dnd.setOver(node.id);
            return;
          }
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
        onDrop={(e) => {
          window.clearTimeout(hoverTimer.current);
          dnd.setOver("");
          if (!dnd.drag.current && isExternalFileDrag(e)) { e.preventDefault(); e.stopPropagation(); dnd.external(node, e); return; }
          e.preventDefault();
          dnd.drop(node);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") select(node.id);
          if (e.key === "ArrowRight" && !open) toggle(node.id);
          if (e.key === "ArrowLeft" && open) toggle(node.id);
        }}>
        <button className="caret" tabIndex={-1} aria-label={open ? "Collapse" : "Expand"} onClick={(e) => { e.stopPropagation(); toggle(node.id); }} style={{ visibility: children.length ? "visible" : "hidden" }}>{open ? "▾" : "▸"}</button>
        <FolderIcon f={node} />
        <span>{folderLabel(node, me)}</span>
        {node.count > 0 && <span className="count">{node.count}</span>}
        {!node.path_only && <span onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()} style={{ marginLeft: node.count > 0 ? 0 : "auto", display: "inline-flex" }}>
          <Menu label={`Actions for folder ${folderLabel(node, me)}`} className="icon-btn node-menu" items={menu(node)} />
        </span>}
      </div>
      {open && children.length > 0 && <ul role="group">{children.map((c) => <TreeNode key={c.id} node={c} active={active} expanded={expanded} toggle={toggle} select={select} level={level + 1} me={me} dnd={dnd} menu={menu} />)}</ul>}
    </li>
  );
}
let childrenOf: Map<string | null, FolderNode[]> = new Map();

type FolderDlg = { kind: "new" | "rename" | "icon" | "perms" | "archive"; f: FolderNode };
type DocDlg = { kind: "rename" | "archive" | "purge" | "share"; d: DocRow };
type DropState = DropProgress & { target: string };

export default function FoldersPage() {
  const { folderId, docId } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { session } = useSession();
  const [folders, setFolders] = useState<FolderNode[] | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [docs, setDocs] = useState<DocRow[] | null>(null);
  const [docsError, setDocsError] = useState("");
  const [total, setTotal] = useState(0);
  const prefView = session?.preferences?.doc_view;
  const prefSort = session?.preferences?.doc_sort;
  const [view, setView] = useState<DocView>(() => normaliseView(prefView || (() => { try { return localStorage.getItem("pd-view"); } catch { return null; } })()));
  const [sort, setSort] = useState<string>(prefSort || "-added");
  useEffect(() => { if (prefView) setView(normaliseView(prefView)); }, [prefView]); // changed on another device
  useEffect(() => { if (prefSort) setSort(prefSort); }, [prefSort]);
  const savePref = (key: string, value: string) => api("settings", { method: "PUT", body: { values: { [key]: value } } }).catch(() => undefined);
  const chooseView = (v: DocView) => { setView(v); try { localStorage.setItem("pd-view", v); } catch { /* private mode */ } savePref("me.doc_view", v); };
  const chooseSort = (v: string) => { setSort(v); savePref("me.doc_sort", v); };
  const [dialog, setDialog] = useState("");
  const [fdlg, setFdlg] = useState<FolderDlg | null>(null);
  const [ddlg, setDdlg] = useState<DocDlg | null>(null);
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showTree, setShowTree] = useState(!folderId);
  const [dropState, setDropState] = useState<DropState | null>(null);
  const [extOver, setExtOver] = useState(false);
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
  // Landing: the signed-in person's own library. Expanded: their library and the path to the open folder only;
  // other people's areas stay collapsed until opened.
  useEffect(() => {
    if (!folders) return;
    if (!folderId) {
      const first = myRoot || folders.find((f) => f.kind === "personal_root" && !f.path_only) || folders.find((f) => !f.path_only);
      if (first) nav(`/folders/${first.id}`, { replace: true });
      return;
    }
    setExpanded((prev) => {
      const exp = new Set(prev);
      if (myRoot) exp.add(myRoot.id);
      exp.add(folderId);
      for (let n = byId.get(folderId); n?.parent; n = byId.get(n.parent)) exp.add(n.parent);
      return exp;
    });
  }, [folders, folderId]);
  const loadDocs = () => {
    if (!folderId) return;
    setDocs(null);
    setDocsError("");
    api<{ documents: DocRow[]; total: number }>("documents", { query: { folder: folderId, limit: 200, sort } })
      .then((r) => { setDocs(r.documents); setTotal(r.total); })
      .catch((e) => { setDocs([]); setDocsError(e.message); });
  };
  useEffect(() => { loadDocs(); }, [folderId, sort]);
  useEffect(() => { setSelected(new Set()); }, [folderId]);
  const folder = folderId ? byId.get(folderId) : undefined;
  const path: FolderNode[] = [];
  for (let n = folder; n; n = n.parent ? byId.get(n.parent) : undefined) path.unshift(n);
  const subfolders = folderId ? childrenOf.get(folderId) || [] : [];
  const can = (c: string) => !!folder?.caps.includes(c);
  const openDoc = (id: string) => (fullPage ? nav(`/documents/${id}`) : nav(`/folders/${folderId}/${id}`));
  const refresh = () => { loadDocs(); loadFolders(); };

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
    refresh();
  };

  // ---- files and folders dragged in from the desktop: same hierarchy recreated below the drop target
  const dropExternal = (target: FolderNode, e: React.DragEvent) => {
    if (!target.caps.includes("upload")) { toast(`You cannot add documents to ${folderLabel(target, me)}.`, "error"); return false; }
    if (dropState?.running) { toast("Please wait until the current upload finishes.", "error"); return false; }
    const label = folderLabel(target, me);
    const collecting = collectDropped(e.dataTransfer);
    setDropState({ target: label, total: 0, done: 0, failed: [], foldersCreated: 0, running: true, bytes: 0, sent: 0 });
    collecting.then((dropped) => {
      if (!dropped.files.length && !dropped.dirs.length && !dropped.unsupported.length) { setDropState(null); toast("Nothing to upload was found in what you dropped.", "error"); return; }
      return uploadDropped(target.id, dropped, (p) => setDropState({ ...p, target: label })).then((p) => {
        toast(p.failed.length ? `${p.done} uploaded, ${p.failed.length} not uploaded — see the list` : `${p.done} file(s) uploaded to ${label}`, p.failed.length ? "error" : "ok");
        refresh();
      });
    }).catch((x) => { setDropState(null); toast(x?.message || "Could not read what you dropped.", "error"); });
    return true;
  };

  const dnd: Dnd = {
    drag, over, setOver,
    why: (t) => whyFor(drag.current)(t),
    drop: (t) => { const d = drag.current; drag.current = null; if (d && !whyFor(d)(t)) moveTo(d, t); },
    startFolder: (f) => !!f.parent && f.kind === "normal" && f.caps.includes("organize"),
    external: dropExternal,
  };
  const startDocDrag = (e: React.DragEvent, d: DocRow) => {
    const ids = selected.has(d.id) ? [...selected] : [d.id];
    drag.current = { type: "docs", ids };
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", ids.length > 1 ? `${ids.length} documents` : d.title);
  };
  const endDrag = () => { drag.current = null; setOver(""); };

  const bulk = async (action: string, value?: string) => {
    const r = await api<any>("documents/bulk", { body: { ids: [...selected], action, value } });
    toast(`${r.succeeded} updated${r.failed ? `, ${r.failed} not permitted` : ""}`, r.failed ? "error" : "ok");
    setSelected(new Set());
    refresh();
  };

  // ---- action menus (only actions the person may perform are listed)
  const folderMenu = (f: FolderNode): MenuItem[] => {
    const c = (x: string) => f.caps.includes(x);
    return [
      { label: "Open", onSelect: () => { setShowTree(false); nav(`/folders/${f.id}`); } },
      { label: "New subfolder…", hidden: !c("organize"), onSelect: () => { setName(""); setEmoji(""); setFdlg({ kind: "new", f }); } },
      { label: "Rename…", hidden: !c("organize") || f.kind !== "normal", onSelect: () => { setName(f.name); setFdlg({ kind: "rename", f }); } },
      { label: "Change icon…", hidden: !c("organize") || f.kind !== "normal", onSelect: () => { setEmoji(f.emoji_is_custom ? f.emoji : ""); setFdlg({ kind: "icon", f }); } },
      { label: "Move to…", hidden: !dnd.startFolder(f), onSelect: () => setMoving({ type: "folder", id: f.id }) },
      { label: "Share / who has access", onSelect: () => setFdlg({ kind: "perms", f }) },
      { label: "Apply folder template", hidden: !c("organize"), onSelect: () => api<{ created: number }>(`folders/${f.id}/apply-template`, { method: "POST" }).then((r) => { toast(r.created ? `${r.created} template folder(s) added` : "All template folders already exist"); loadFolders(); }).catch((e) => toast(e.message, "error")) },
      { label: "Download folder (ZIP)", hidden: !c("download"), href: `/api/export/download?folder=${f.id}` },
      "separator",
      { label: "Archive folder…", danger: true, hidden: !c("archive") || f.kind !== "normal", onSelect: () => setFdlg({ kind: "archive", f }) },
    ];
  };
  const docMenu = (d: DocRow): MenuItem[] => {
    const c = (x: string) => d.caps.includes(x);
    return [
      { label: "Open", onSelect: () => openDoc(d.id) },
      { label: "Rename…", hidden: !c("edit"), onSelect: () => { setName(d.title); setDdlg({ kind: "rename", d }); } },
      { label: "Move to…", hidden: !c("organize"), onSelect: () => setMoving({ type: "docs", ids: [d.id] }) },
      { label: "Download", hidden: !c("download"), href: `/api/documents/${d.id}/file?download=1` },
      { label: "Share…", hidden: !c("share") && !c("download"), onSelect: () => setDdlg({ kind: "share", d }) },
      "separator",
      { label: "Archive…", danger: true, hidden: !c("archive"), onSelect: () => setDdlg({ kind: "archive", d }) },
      { label: "Delete permanently…", danger: true, hidden: !session?.user?.is_main_admin, onSelect: () => setDdlg({ kind: "purge", d }) },
    ];
  };

  if (!folders) return <Skeleton lines={8} />;
  if (!folders.length) return <div className="empty"><h2>No folders yet</h2><p>Ask your family administrator to give you access.</p></div>;

  const sortHeader = (key: string, label: string, cls = "") => {
    const active = sort === key || sort === `-${key}`;
    const desc = sort === `-${key}`;
    return (
      <th className={cls} aria-sort={active ? (desc ? "descending" : "ascending") : "none"}>
        <button type="button" onClick={() => chooseSort(active && !desc ? `-${key}` : key)}>{label}{active ? (desc ? " ▾" : " ▴") : ""}</button>
      </th>
    );
  };
  const check = (d: DocRow) => (
    <input type="checkbox" aria-label={`Select ${d.title}`} checked={selected.has(d.id)} onClick={(e) => e.stopPropagation()}
      onChange={(e) => setSelected((s) => { const n = new Set(s); e.target.checked ? n.add(d.id) : n.delete(d.id); return n; })} />
  );
  const rowProps = (d: DocRow) => ({
    onClick: () => openDoc(d.id), draggable: d.caps.includes("organize"),
    onDragStart: (e: React.DragEvent) => startDocDrag(e, d), onDragEnd: endDrag,
  });
  const openBtn = (d: DocRow, cls = "") => (
    <button type="button" className={`doc-open ${cls}`} aria-current={docId === d.id ? "true" : undefined} onClick={(e) => { e.stopPropagation(); openDoc(d.id); }}>{d.title}</button>
  );
  const rowMenu = (d: DocRow) => <span onClick={(e) => e.stopPropagation()} style={{ display: "inline-flex" }}><Menu label={`More actions for ${d.title}`} items={docMenu(d)} /></span>;

  return (
    <div>
      <div className="page-head">
        <h1>Folders</h1>
        <div className="row">
          <Link className="btn" to="/imports/new"><Icon name="folder" /> Import folder</Link>
          {can("upload") && <button className="btn primary" onClick={() => setDialog("upload")}><Icon name="upload" /> Upload</button>}
          <label className="sr-only" htmlFor="doc-sort">Sort by</label>
          <select id="doc-sort" value={sort} onChange={(e) => chooseSort(e.target.value)} style={{ width: "auto" }} title="Sort by">
            {Object.entries(SORT_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <div className="row view-switch" role="group" aria-label="View mode" style={{ gap: 0 }}>
            {DOC_VIEWS.map(([v, label, icon]) => (
              <button key={v} className={`btn ${view === v ? "primary" : ""}`} aria-pressed={view === v} onClick={() => chooseView(v)} aria-label={`${label} view`} title={`${label} view`}><Icon name={icon} /></button>
            ))}
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
          <ul role="tree" aria-label="Folders">{roots.map((r) => <TreeNode key={r.id} node={r} active={folderId || ""} expanded={expanded} level={1} me={me} dnd={dnd} menu={folderMenu}
            toggle={(id, force) => setExpanded((e) => { const n = new Set(e); (force ?? !n.has(id)) ? n.add(id) : n.delete(id); return n; })}
            select={(id) => { setShowTree(false); nav(`/folders/${id}`); }} />)}</ul>
        </section>
        <section className={`list-pane ${extOver ? "drop-target" : ""}`} aria-label="Documents" ref={listRef}
          onDragOver={(e) => {
            if (drag.current || !isExternalFileDrag(e) || !folder) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = can("upload") ? "copy" : "none";
            if (!extOver) setExtOver(true);
          }}
          onDragLeave={(e) => { if (!listRef.current?.contains(e.relatedTarget as Node)) setExtOver(false); }}
          onDrop={(e) => {
            setExtOver(false);
            if (drag.current || !isExternalFileDrag(e) || !folder) return;
            e.preventDefault();
            dropExternal(folder, e);
          }}>
          {extOver && <div className="alert drop-hint" role="status">{can("upload") ? <>Drop files or folders to upload them to <strong>{folder ? folderLabel(folder, me) : ""}</strong>. Folders keep their structure.</> : "You cannot add documents to this folder."}</div>}
          <div className="row between" style={{ paddingRight: ".6rem", flexWrap: "nowrap" }}>
            <nav className="breadcrumb" aria-label="Breadcrumb">
              <button className="btn small ghost" onClick={() => setShowTree(true)} aria-label="Show folders" style={{ padding: "0 .3rem" }}>☰</button>
              {path.filter((p) => p.parent).map((p, i, arr) => (
                <span key={p.id}>{i < arr.length - 1 ? <><Link to={`/folders/${p.id}`}>{p.emoji} {folderLabel(p, me)}</Link> /</> : <strong style={{ color: "var(--ink)" }}>{p.emoji} {folderLabel(p, me)}</strong>}</span>
              ))}
            </nav>
            {folder && <Menu label="Folder actions" items={folderMenu(folder)} />}
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
                onDrop={(e) => { if (!drag.current) return; e.preventDefault(); e.stopPropagation(); setOver(""); dnd.drop(s); }}>{s.emoji} {s.name} <span className="muted">{s.count || ""}</span></Link>)}
            </div>
          )}
          {docs === null ? <div style={{ padding: "1rem" }}><Skeleton /></div> : docsError ? (
            <div className="alert error" style={{ margin: ".6rem" }}>Could not load documents: {docsError} <button className="btn small" onClick={loadDocs}>Try again</button></div>
          ) : docs.length === 0 ? (
            <div className="empty">This folder has no documents{can("upload") ? " yet. Use Upload, or drag files and folders here from your computer." : "."}</div>
          ) : view === "list" ? docs.map((d) => (
            <div key={d.id} className={`doc-card ${docId === d.id ? "active" : ""}`} {...rowProps(d)}>
              {check(d)}
              <FileTypeIcon kind={d.file_kind} label={d.file_label} />
              <div className="grow">{openBtn(d)}<div className="small muted">{d.file_label} · {formatBytes(d.size)} · {formatDate(d.created_at)}</div></div>
              <StateBadge state={d.state} /><AvBadge status={d.av_status} compact />{d.expiry && d.expiry.level !== "ok" && <ExpiryBadge expiry={d.expiry} />}
              {rowMenu(d)}
            </div>
          )) : view === "thumbnails" ? (
            <div className="doc-grid">{docs.map((d) => (
              <div key={d.id} className={`doc-card ${docId === d.id ? "active" : ""}`} {...rowProps(d)}>
                <div className="thumb-wrap">
                  {d.has_thumbnail ? <img className="thumb" src={`/api/documents/${d.id}/thumbnail`} alt="" loading="lazy" draggable={false} /> : <div className="thumb" aria-hidden="true"><FileTypeIcon kind={d.file_kind} size="lg" /></div>}
                  {d.has_thumbnail && <FileTypeIcon kind={d.file_kind} label={d.file_label} size="sm" />}
                </div>
                <div className="row between" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                  {openBtn(d, "small")}
                  {rowMenu(d)}
                </div>
                <ExpiryBadge expiry={d.expiry} />
              </div>
            ))}</div>
          ) : (
            <table className="details-table">
              <thead><tr>
                <th style={{ width: 28 }}><input type="checkbox" aria-label="Select all" checked={docs.length > 0 && docs.every((d) => selected.has(d.id))}
                  onChange={(e) => setSelected(e.target.checked ? new Set(docs.map((d) => d.id)) : new Set())} /></th>
                {sortHeader("name", "Name")}{sortHeader("type", "Type", "opt")}{sortHeader("size", "Size", "opt")}{sortHeader("expiry", "Expiry")}{sortHeader("added", "Added", "opt")}
                <th className="opt">Status</th><th><span className="sr-only">Actions</span></th>
              </tr></thead>
              <tbody>{docs.map((d) => (
                <tr key={d.id} className={docId === d.id ? "active" : ""} {...rowProps(d)}>
                  <td>{check(d)}</td>
                  <td><div className="name-cell"><FileTypeIcon kind={d.file_kind} label={d.file_label} size="sm" />{openBtn(d)}</div></td>
                  <td className="opt">{d.type?.name || d.file_label}</td>
                  <td className="opt">{formatBytes(d.size)}</td>
                  <td>{d.expiry_date ? <>{formatDate(d.expiry_date)} {d.expiry && d.expiry.level !== "ok" && <ExpiryBadge expiry={d.expiry} />}</> : d.expiry?.level === "none" ? <ExpiryBadge expiry={d.expiry} /> : "—"}</td>
                  <td className="opt">{formatDate(d.created_at)}</td>
                  <td className="opt"><StateBadge state={d.state} /><AvBadge status={d.av_status} compact /></td>
                  <td>{rowMenu(d)}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
          {docs && total > docs.length && <p className="small muted" style={{ padding: ".6rem" }}>Showing {docs.length} of {total}. Use search to narrow down.</p>}
        </section>
        <section className="detail-pane" aria-label="Document details">
          {docId ? (
            <>
              <button className="btn small ghost hide-desktop-detail" onClick={() => nav(`/folders/${folderId}`)} style={{ margin: ".5rem" }}>← Back to folder</button>
              <DocumentPanel id={docId} onChanged={refresh} />
            </>
          ) : <div className="empty">Select a document to preview it here.</div>}
        </section>
      </div>
      {dropState && (
        <div className="card drop-progress" role="status" aria-live="polite">
          <div className="row between">
            <strong>{dropState.running ? "Uploading" : "Upload finished"} to {dropState.target}</strong>
            {!dropState.running && <button className="icon-btn" aria-label="Close upload summary" onClick={() => setDropState(null)}><Icon name="x" /></button>}
          </div>
          <div className="progress" style={{ margin: ".5rem 0" }}><div style={{ width: `${dropState.bytes ? Math.round((dropState.sent / dropState.bytes) * 100) : dropState.running ? 0 : 100}%` }} /></div>
          <div className="small">{dropState.done} of {dropState.total} file(s) uploaded{dropState.foldersCreated ? `, ${dropState.foldersCreated} folder(s) created` : ""}{dropState.failed.length ? `, ${dropState.failed.length} not uploaded` : ""}.</div>
          {dropState.failed.length > 0 && <ul>{dropState.failed.slice(0, 50).map((f, i) => <li key={i}><span className="mono">{f.file}</span>: {f.error}</li>)}{dropState.failed.length > 50 && <li>…and {dropState.failed.length - 50} more</li>}</ul>}
        </div>
      )}
      {dialog === "upload" && folderId && <UploadDialog folderId={folderId} onClose={() => setDialog("")} onDone={() => { setDialog(""); refresh(); }} />}
      {fdlg?.kind === "new" && (
        <Modal title={`New folder in ${folderLabel(fdlg.f, me)}`} onClose={() => setFdlg(null)}>
          <form className="stack" onSubmit={async (e) => {
            e.preventDefault();
            try { const f = await api<FolderNode>("folders", { body: { parent: fdlg.f.id, name, emoji: emoji || undefined } }); setFdlg(null); loadFolders(); nav(`/folders/${f.id}`); }
            catch (x: any) { toast(x.message, "error"); }
          }}>
            <div className="field"><label htmlFor="fname">Name</label><input id="fname" type="text" value={name} onChange={(e) => setName(e.target.value)} autoFocus /></div>
            <div className="field"><p style={{ fontWeight: 550, margin: "0 0 .3rem" }}>Icon <span className="muted small">(optional — {fdlg.f.kind === "normal" ? "sub-folders use the standard 📁 icon" : "a suggestion is made from the name"})</span></p><EmojiPicker value={emoji} onPick={(e) => setEmoji(e === emoji ? "" : e)} /></div>
            <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={() => setFdlg(null)}>Cancel</button><button className="btn primary" disabled={!name.trim()}>Create</button></div>
          </form>
        </Modal>
      )}
      {fdlg?.kind === "rename" && (
        <Modal title="Rename folder" onClose={() => setFdlg(null)}>
          <form className="stack" onSubmit={async (e) => {
            e.preventDefault();
            try { await api(`folders/${fdlg.f.id}`, { method: "PATCH", body: { name: name.trim() } }); toast("Folder renamed"); setFdlg(null); loadFolders(); }
            catch (x: any) { toast(x.message, "error"); }
          }}>
            <div className="field"><label htmlFor="fname">Name</label><input id="fname" type="text" value={name} onChange={(e) => setName(e.target.value)} autoFocus maxLength={200} /></div>
            <p className="small muted">Renaming never changes who can see the folder or what is inside it.</p>
            <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={() => setFdlg(null)}>Cancel</button><button className="btn primary" disabled={!name.trim() || name.trim() === fdlg.f.name}>Rename</button></div>
          </form>
        </Modal>
      )}
      {fdlg?.kind === "icon" && (
        <Modal title={`Icon for “${fdlg.f.name}”`} onClose={() => setFdlg(null)}>
          <div className="stack">
            <EmojiPicker value={emoji || fdlg.f.emoji} onPick={(e) => setEmoji(e)} />
            <p className="small muted">Icons are only labels; they never change who can see the folder. {fdlg.f.emoji_is_custom ? "This folder has a chosen icon." : "This folder uses its default icon."}</p>
            <div className="row between">
              <button className="btn" disabled={!fdlg.f.emoji_is_custom} onClick={() => api(`folders/${fdlg.f.id}`, { method: "PATCH", body: { emoji: "" } }).then(() => { toast("Default icon restored"); setFdlg(null); loadFolders(); }).catch((x) => toast(x.message, "error"))}>Reset to default</button>
              <span className="row"><button className="btn" onClick={() => setFdlg(null)}>Cancel</button>
                <button className="btn primary" disabled={!emoji || emoji === fdlg.f.emoji} onClick={() => api(`folders/${fdlg.f.id}`, { method: "PATCH", body: { emoji } }).then(() => { toast("Icon changed"); setFdlg(null); loadFolders(); }).catch((x) => toast(x.message, "error"))}>Save</button></span>
            </div>
          </div>
        </Modal>
      )}
      {moving && (
        <MoveDialog folders={folders} me={me} moving={moving} why={whyFor(moving)} near={moving.type === "folder" ? byId.get(moving.id)?.parent : folderId}
          what={moving.type === "folder" ? `the folder “${byId.get(moving.id)?.name}” and everything in it` : moving.ids.length === 1 ? `“${docs?.find((x) => x.id === moving.ids[0])?.title || "this document"}”` : `${moving.ids.length} documents`}
          onClose={() => setMoving(null)} onMove={(t) => { const d = moving; setMoving(null); moveTo(d, t); }} />
      )}
      {fdlg?.kind === "perms" && <PermissionsDialog target={{ kind: "folders", id: fdlg.f.id, name: fdlg.f.name }} onClose={() => { setFdlg(null); loadFolders(); }} />}
      {fdlg?.kind === "archive" && (
        <Confirm title="Archive folder" danger confirmLabel="Archive" onClose={() => setFdlg(null)}
          message={<p>“{fdlg.f.name}” and everything inside will be hidden from everyone but the main administrator, and public links inside it stop working. Nothing is deleted; the administrator can restore it.</p>}
          onConfirm={async () => { const f = fdlg.f; try { await api(`folders/${f.id}/archive`, { method: "POST" }); toast("Folder archived"); setFdlg(null); if (folderId && (folderId === f.id || descendantIds(folders, f.id).has(folderId))) nav(f.parent ? `/folders/${f.parent}` : "/folders"); refresh(); } catch (x: any) { toast(x.message, "error"); } }} />
      )}
      {ddlg?.kind === "rename" && (
        <Modal title="Rename document" onClose={() => setDdlg(null)}>
          <form className="stack" onSubmit={async (e) => {
            e.preventDefault();
            try { await api(`documents/${ddlg.d.id}`, { method: "PATCH", body: { title: name.trim() } }); toast("Document renamed"); setDdlg(null); loadDocs(); }
            catch (x: any) { toast(x.message, "error"); }
          }}>
            <div className="field"><label htmlFor="dname">Title</label><input id="dname" type="text" value={name} onChange={(e) => setName(e.target.value)} autoFocus maxLength={300} /></div>
            <p className="small muted">Only the title shown in the app changes. The stored file and its versions are not renamed or modified.</p>
            <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={() => setDdlg(null)}>Cancel</button><button className="btn primary" disabled={!name.trim() || name.trim() === ddlg.d.title}>Rename</button></div>
          </form>
        </Modal>
      )}
      {ddlg?.kind === "share" && <ShareDialog doc={ddlg.d} onClose={() => setDdlg(null)} />}
      {ddlg?.kind === "archive" && (
        <Confirm title="Archive document" danger confirmLabel="Archive" onClose={() => setDdlg(null)}
          message={<p>“{ddlg.d.title}” will be hidden from everyone except the main administrator, its public links stop working and reminders stop. The administrator can restore it.</p>}
          onConfirm={async () => { const d = ddlg.d; try { await api(`documents/${d.id}/archive`, { method: "POST" }); toast("Document archived"); setDdlg(null); if (docId === d.id) nav(`/folders/${folderId}`); loadDocs(); loadFolders(); } catch (x: any) { toast(x.message, "error"); } }} />
      )}
      {ddlg?.kind === "purge" && (
        <Confirm title="Delete permanently" danger confirmLabel="Delete permanently" typeToConfirm={ddlg.d.title} onClose={() => setDdlg(null)}
          message={<p>“{ddlg.d.title}”, all its versions, details and share links will be <strong>deleted for good</strong>. This cannot be undone and is recorded in the audit log. To keep a recoverable copy, use <em>Archive</em> instead.</p>}
          onConfirm={async (typed) => {
            const d = ddlg.d;
            try {
              await api(`documents/${d.id}/archive`, { method: "POST" });
              await api(`documents/${d.id}`, { method: "DELETE", body: { confirm: typed } });
              toast("Document deleted permanently"); setDdlg(null); if (docId === d.id) nav(`/folders/${folderId}`); loadDocs(); loadFolders();
            } catch (x: any) { toast(x.message, "error"); }
          }} />
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
