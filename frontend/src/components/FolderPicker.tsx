import { useMemo, useState } from "react";
import type { FolderNode } from "../types";
import { Avatar } from "./ui";

/** Display name of a folder; the signed-in person's own area reads "My Documents — <name>". */
export function folderLabel(f: FolderNode, meId?: string | null): string {
  if (f.kind === "personal_root" && meId && f.owner === meId) return `My Documents — ${f.owner_user?.display_name || f.name}`;
  return f.name;
}

/** Children map with the signed-in person's own area first. */
export function folderChildren(folders: FolderNode[], meId?: string | null): Map<string | null, FolderNode[]> {
  const ids = new Set(folders.map((f) => f.id));
  const m = new Map<string | null, FolderNode[]>();
  for (const f of folders) {
    const key = f.parent && ids.has(f.parent) ? f.parent : null;
    m.set(key, [...(m.get(key) || []), f]);
  }
  const mine = (f: FolderNode) => (f.kind === "personal_root" && f.owner === meId ? 0 : 1);
  m.forEach((list) => list.sort((a, b) => mine(a) - mine(b)));
  return m;
}

export function descendantIds(folders: FolderNode[], id: string): Set<string> {
  const out = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const f of folders) if (f.parent && out.has(f.parent) && !out.has(f.id)) { out.add(f.id); grew = true; }
  }
  return out;
}

export function FolderIcon({ f }: { f: FolderNode }) {
  if (f.kind === "personal_root" && f.owner_user) return <Avatar user={f.owner_user} size="sm" />;
  return <span aria-hidden="true">{f.emoji || "📁"}</span>;
}

/**
 * Accessible folder-tree picker used by "Move to…" and the import destination. ``reason`` returns why a folder
 * cannot be chosen (shown, not hidden, so the tree keeps its shape), or "" when it can.
 */
export default function FolderPicker({ folders, value, onChange, reason, meId, label = "Destination folder", near }: {
  folders: FolderNode[]; value: string; onChange: (id: string) => void; reason: (f: FolderNode) => string; meId?: string | null; label?: string;
  near?: string | null; // a folder to open the tree at (e.g. where the items are now)
}) {
  const children = useMemo(() => folderChildren(folders, meId), [folders, meId]);
  const byId = useMemo(() => new Map(folders.map((f) => [f.id, f])), [folders]);
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<Set<string>>(() => {
    const s = new Set<string>((children.get(null) || []).map((r) => r.id));
    for (const start of [value, near]) {
      if (!start) continue;
      s.add(start); // show the folder's own sub-folders too
      for (let n = byId.get(start); n?.parent; n = byId.get(n.parent)) s.add(n.parent);
    }
    return s;
  });
  const q = filter.trim().toLowerCase();
  const matches = useMemo(() => {
    if (!q) return null;
    const keep = new Set<string>();
    for (const f of folders) {
      if (folderLabel(f, meId).toLowerCase().includes(q)) for (let n: FolderNode | undefined = f; n; n = n.parent ? byId.get(n.parent) : undefined) keep.add(n.id);
    }
    return keep;
  }, [q, folders]);

  const pathOf = (id: string) => {
    const out: string[] = [];
    for (let n = byId.get(id); n; n = n.parent ? byId.get(n.parent) : undefined) out.unshift(folderLabel(n, meId));
    return out.join(" / ");
  };

  const render = (parent: string | null, level: number): JSX.Element | null => {
    const list = (children.get(parent) || []).filter((f) => !matches || matches.has(f.id));
    if (!list.length) return null;
    return (
      <ul role={level === 1 ? "tree" : "group"} aria-label={level === 1 ? label : undefined} className="picker-list">
        {list.map((f) => {
          const why = f.path_only ? "You cannot open this folder" : reason(f);
          const kids = (children.get(f.id) || []).length > 0;
          const expanded = !!matches || open.has(f.id);
          return (
            <li key={f.id} role="treeitem" aria-level={level} aria-selected={value === f.id} aria-expanded={kids ? expanded : undefined}>
              <div className={`picker-row ${value === f.id ? "selected" : ""} ${why ? "disabled" : ""}`}>
                <button type="button" className="caret" tabIndex={-1} aria-hidden="true" style={{ visibility: kids ? "visible" : "hidden" }}
                  onClick={() => setOpen((s) => { const n = new Set(s); n.has(f.id) ? n.delete(f.id) : n.add(f.id); return n; })}>{expanded ? "▾" : "▸"}</button>
                <button type="button" className="picker-pick" disabled={!!why} aria-disabled={!!why} title={why || pathOf(f.id)}
                  onClick={() => onChange(f.id)}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowRight" && kids) setOpen((s) => new Set(s).add(f.id));
                    if (e.key === "ArrowLeft") setOpen((s) => { const n = new Set(s); n.delete(f.id); return n; });
                  }}>
                  <FolderIcon f={f} /> <span>{folderLabel(f, meId)}</span>
                  {why && <span className="sr-only"> — {why}</span>}
                </button>
              </div>
              {expanded && render(f.id, level + 1)}
            </li>
          );
        })}
      </ul>
    );
  };

  return (
    <div className="folder-picker">
      <input type="search" placeholder="Find a folder…" aria-label="Find a folder" value={filter} onChange={(e) => setFilter(e.target.value)} />
      <div className="picker-tree">{render(null, 1) || <p className="small muted">No folders match.</p>}</div>
      <p className="small" aria-live="polite">{value ? <>Selected: <strong>{pathOf(value)}</strong></> : "No folder selected yet."}</p>
    </div>
  );
}
