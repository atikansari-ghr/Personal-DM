import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, formatBytes, formatDate, formatDateTime } from "../api";
import UploadDialog from "../components/UploadDialog";
import { Avatar, Confirm, HelpTip, Icon, Modal, Skeleton, StateBadge, useAsync, useToast } from "../components/ui";
import { useSession } from "../session";
import FileTypeIcon from "../components/FileTypeIcon";
import { ActivityWidget, CalendarWidget, DateWidget, DocList, HolidaysWidget, SummaryWidget, WeatherWidget } from "../components/OverviewWidgets";
import { HealthSummary } from "./settings/SecurityCenter";
import { HealthBadge } from "../components/HealthBadge";
import { SessionsTile } from "./settings/ActiveSessions";
import type { DocRow, OvGroup, User, WidgetCfg } from "../types";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export function DocTable({ docs, empty }: { docs: DocRow[]; empty: string }) {
  const nav = useNavigate();
  if (!docs.length) return <div className="empty">{empty}</div>;
  return (
    <table className="responsive">
      <thead><tr><th>Document</th><th className="hide-mobile">Owner</th><th>Added</th></tr></thead>
      <tbody>
        {docs.map((d) => (
          <tr key={d.id} className="clickable" tabIndex={0} onClick={() => nav(`/documents/${d.id}`)} onKeyDown={(e) => e.key === "Enter" && nav(`/documents/${d.id}`)}>
            <td>
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <FileTypeIcon kind={d.file_kind} label={d.file_label} size="sm" />
                <div className="grow"><div style={{ fontWeight: 600 }}>{d.title}</div><div className="muted small">{d.type?.name || d.file_label}</div></div>
                <StateBadge state={d.state} />
              </div>
            </td>
            <td className="hide-mobile"><div className="row"><Avatar user={d.owner} size="sm" /> {d.owner.display_name}</div></td>
            <td>{formatDate(d.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Mirrors apps.core.registry.WIDGETS / DEFAULT_WIDGETS.
export const WIDGET_LABELS: Record<string, string> = {
  date: "Today (Gregorian + Hijri)", weather: "Weather", summary: "Documents summary", calendar: "Month calendar",
  holidays: "Upcoming holidays", upcoming: "Expiring soon", shared: "Shared with me", recent: "Recent documents",
  activity: "Recent activity", review_queue: "Review queue", backup: "Backup & Recovery Health", my_recovery: "My Recovery", family: "Family library",
  saved_views: "Saved views", documents: "Documents (count)", members: "Family members (count)",
  expiring: "Expiring in 90 days (count)", storage: "Storage used", review: "Needs review (count)",
  security: "Security Health", sessions: "Active Sessions",
};
export const DEFAULT_WIDGETS = ["date", "weather", "summary", "calendar", "holidays", "upcoming", "shared", "recent", "activity", "review_queue", "backup", "my_recovery", "security", "sessions"];
const STYLE_LABELS: Record<string, string> = { rect: "Rectangular", compact: "Compact rectangular", circle: "Circular", compact_circle: "Compact circular" };
const WIDGET_ICON: Record<string, string> = {
  date: "calendar", weather: "cloud-sun", summary: "grid", calendar: "calendar", holidays: "gift", upcoming: "clock", shared: "share",
  recent: "file", activity: "list", review_queue: "eye", backup: "db", my_recovery: "refresh", family: "users", saved_views: "list",
  documents: "file", members: "users", expiring: "clock", storage: "db", review: "eye", security: "shield", sessions: "users",
};
const LINKS: Record<string, [string, string]> = {
  upcoming: ["/search?expiring_days=90", "View all"], recent: ["/search", "View all"], shared: ["/shared", "View all"],
  holidays: ["", ""], review_queue: ["/ocr-review", "Open"], security: ["/settings/security", "Open"],
  sessions: ["/settings/security?view=sessions", "View all"],
};
type Limits = Record<string, { min: number; default: number; max: number; circle: boolean; options: string[]; cols_min: number; cols_max: number; h_min: number; h_max: number }>;
interface LayoutPayload { groups: OvGroup[]; known: string[]; layout: Record<string, WidgetCfg>; limits: Limits; customized: boolean }
const ROW_PX = 90, GAP_PX = 16;  // a height row; matches the 1rem grid gap

function WidgetSettingsDialog({ id, cfg, countries, onClose, onSave }: { id: string; cfg: WidgetCfg; countries: { code: string; name: string; flag: string }[]; onClose: () => void; onSave: (s: Record<string, any>) => void }) {
  const [s, setS] = useState<Record<string, any>>({ ...(cfg.settings || {}) });
  const chosen: string[] = s.countries || [];
  return (
    <Modal title={`${WIDGET_LABELS[id]} settings`} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSave(s); }}>
        {id === "date" && <>
          <label className="check"><input type="checkbox" checked={s.show_hijri !== false} onChange={(e) => setS({ ...s, show_hijri: e.target.checked })} /> Show the Hijri date</label>
          <label className="check"><input type="checkbox" checked={!!s.arabic_month} onChange={(e) => setS({ ...s, arabic_month: e.target.checked })} /> Also show the Hijri month in Arabic</label>
        </>}
        {(id === "holidays" || id === "calendar") && (
          <fieldset className="field"><legend>Countries</legend>
            <p className="small muted">Leave all unticked to follow the installation's holiday countries.</p>
            {countries.length === 0 && <p className="small">The administrator has not chosen any holiday countries.</p>}
            {countries.map((c) => <label key={c.code} className="check"><input type="checkbox" checked={chosen.includes(c.code)} onChange={(e) => setS({ ...s, countries: e.target.checked ? [...chosen, c.code] : chosen.filter((x) => x !== c.code) })} /> {c.flag} {c.name}</label>)}
          </fieldset>
        )}
        {["holidays", "recent", "shared", "activity"].includes(id) && (
          <div className="field"><label htmlFor="ws-count">Items to show</label><input id="ws-count" type="number" min={1} max={20} value={s.count || 6} onChange={(e) => setS({ ...s, count: Number(e.target.value) })} style={{ maxWidth: 120 }} /></div>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary">Apply</button></div>
      </form>
    </Modal>
  );
}

export default function Dashboard() {
  const { session, refresh } = useSession();
  const toast = useToast();
  const { data, loading, error, reload } = useAsync(() => api<any>("dashboard"), []);
  // Change Set AA: the person's own layout — groups of tiles, sizes and styles — kept on the server
  const lay = useAsync(() => api<LayoutPayload>("dashboard/layout"), []);
  const [uploading, setUploading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [groups, setGroups] = useState<OvGroup[]>([]);
  const [layout, setLayout] = useState<Record<string, WidgetCfg>>({});
  const [known, setKnown] = useState<string[]>([]);
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropGroup, setDropGroup] = useState<string | null>(null);
  const [settingsFor, setSettingsFor] = useState<string | null>(null);
  const [adding, setAdding] = useState("");
  const [newGroup, setNewGroup] = useState("");
  const [removing, setRemoving] = useState<OvGroup | null>(null);
  const [resetting, setResetting] = useState(false);
  const [saving, setSaving] = useState(false);
  const apply = (p: LayoutPayload) => { setGroups(p.groups); setLayout(p.layout || {}); setKnown(p.known || []); };
  useEffect(() => { if (lay.data && !editing) apply(lay.data); }, [lay.data, editing]);
  if ((loading && !data) || (!lay.data && !lay.error)) return <Skeleton lines={6} />;
  if (error) return <div className="alert error">{error}</div>;
  const limits: Limits = lay.data?.limits || data.layout_limits || {};
  const lim = (id: string) => limits[id] || { min: 1, default: 2, max: 4, circle: false, options: [], cols_min: 2, cols_max: 12, h_min: 1, h_max: 8 };
  const cfgOf = (id: string) => {
    const c = layout[id] || {};
    const l = lim(id);
    const style = c.style && (!c.style.endsWith("circle") || l.circle) ? c.style : "rect";
    const cols = Math.max(l.cols_min, Math.min(l.cols_max, c.cols || (c.w || l.default) * 3));
    const h = c.h ? Math.max(l.h_min, Math.min(l.h_max, c.h)) : 0;
    return { ...c, cols, h, w: Math.max(l.min, Math.min(l.max, Math.round(cols / 3) || 1)), style };
  };
  const setCfg = (id: string, patch: Partial<WidgetCfg>) => setLayout((x) => ({ ...x, [id]: { ...cfgOf(id), ...x[id], ...patch } }));
  const persist = async (gs: OvGroup[], lo: Record<string, WidgetCfg>, msg?: string) => {
    setSaving(true);
    try {
      const all = gs.flatMap((g) => g.widgets);
      const r = await api<LayoutPayload>("dashboard/layout", { method: "PUT", body: { groups: gs, known: Array.from(new Set([...known, ...all])), layout: Object.fromEntries(all.map((id) => [id, { ...lo[id], ...cfgOf(id), ...(lo[id] || {}) }])) } });
      lay.reload();
      apply(r);
      refresh();
      if (msg) toast(msg);
      return true;
    } catch (e: any) { toast(e.message, "error"); return false; } finally { setSaving(false); }
  };
  const save = async () => { if (await persist(groups, layout, "Layout saved on all your devices")) setEditing(false); };
  const shownIds = groups.flatMap((g) => g.widgets);
  const moveWithin = (id: string, delta: number) => setGroups((gs) => gs.map((g) => {
    const i = g.widgets.indexOf(id), j = i + delta;
    if (i < 0 || j < 0 || j >= g.widgets.length) return g;
    const w = [...g.widgets];
    [w[i], w[j]] = [w[j], w[i]];
    return { ...g, widgets: w };
  }));
  const moveTo = (id: string, gid: string, before?: string) => setGroups((gs) => gs.map((g) => {
    const w = g.widgets.filter((x) => x !== id);
    if (g.id !== gid) return { ...g, widgets: w };
    const at = before && w.includes(before) ? w.indexOf(before) : w.length;
    w.splice(at, 0, id);
    return { ...g, widgets: w };
  }));
  const moveGroup = (gid: string, delta: number) => setGroups((gs) => {
    const i = gs.findIndex((g) => g.id === gid), j = i + delta;
    if (i < 0 || j < 0 || j >= gs.length) return gs;
    const n = [...gs];
    [n[i], n[j]] = [n[j], n[i]];
    return n;
  });
  const addGroup = () => {
    const name = newGroup.trim().replace(/\s+/g, " ");
    if (!name || name.length > 40 || /[<>]/.test(name)) { toast("A group name needs 1 to 40 characters (no < or >).", "error"); return; }
    if (groups.some((g) => g.name.toLowerCase() === name.toLowerCase())) { toast(`There is already a group called “${name}”.`, "error"); return; }
    const base = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30) || "group";
    let id = base, n = 2;
    while (groups.some((g) => g.id === id)) id = `${base}-${n++}`;
    setGroups([...groups, { id, name, collapsed: false, widgets: [] }]);
    setNewGroup("");
  };
  const toggleCollapse = (g: OvGroup) => {
    const next = groups.map((x) => (x.id === g.id ? { ...x, collapsed: !x.collapsed } : x));
    setGroups(next);
    if (!editing) persist(next, layout);  // a collapsed group stays collapsed on every device
  };
  const startResize = (id: string, e: React.PointerEvent<HTMLElement>) => {
    const cell = (e.currentTarget as HTMLElement).closest(".ov-cell") as HTMLElement | null;
    const grid = cell?.parentElement;
    if (!cell || !grid) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const c = cfgOf(id), l = lim(id);
    const colW = grid.clientWidth / 12, rowH = ROW_PX + GAP_PX;
    const x0 = e.clientX, y0 = e.clientY;
    const h0 = c.h || Math.max(l.h_min, Math.round((cell.offsetHeight + GAP_PX) / rowH));
    const target = e.currentTarget as HTMLElement;
    const move = (ev: PointerEvent) => {
      const cols = Math.max(l.cols_min, Math.min(l.cols_max, c.cols + Math.round((ev.clientX - x0) / colW)));
      const h = Math.max(l.h_min, Math.min(l.h_max, h0 + Math.round((ev.clientY - y0) / rowH)));
      setCfg(id, { cols, h });
    };
    const up = () => { target.removeEventListener("pointermove", move); target.removeEventListener("pointerup", up); target.removeEventListener("pointercancel", up); };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  };
  const s = data.stats;
  const counter = (icon: string, label: string, value: any, cls = "") => (style: string) => (
    <div className={style.endsWith("circle") ? "ov-circle-body" : "stat"}><Icon name={icon} size={style.endsWith("circle") ? 26 : 34} /><div><div className="muted small">{label}</div><div className={`num ${cls}`}>{value}</div></div></div>
  );
  const body: Record<string, (c: ReturnType<typeof cfgOf>) => JSX.Element | null> = {
    date: (c) => <DateWidget data={data} style={c.style} settings={c.settings || {}} w={c.w} />,
    weather: (c) => <WeatherWidget data={data} style={c.style} settings={c.settings || {}} w={c.w} />,
    summary: (c) => <SummaryWidget data={data} style={c.style} settings={{}} w={c.w} />,
    calendar: (c) => <CalendarWidget data={data} style={c.style} settings={c.settings || {}} w={c.w} />,
    holidays: (c) => <HolidaysWidget data={data} style={c.style} settings={c.settings || {}} w={c.w} />,
    upcoming: () => <DocList docs={data.expiring} expiry empty="Nothing expires in the next 90 days." />,
    shared: (c) => <DocList docs={data.shared} count={c.settings?.count} empty="Nothing has been shared with you yet." />,
    recent: (c) => <DocList docs={data.recent} count={c.settings?.count} empty="No documents yet. Upload your first one." />,
    activity: (c) => <ActivityWidget data={data} style={c.style} settings={c.settings || {}} w={c.w} />,
    documents: (c) => counter("file", "Documents", s.documents.toLocaleString())(c.style),
    members: (c) => counter("users", "Family members", s.members)(c.style),
    expiring: (c) => counter("clock", "Expiring in 90 days", s.expiring_90, s.expiring_90 ? "warn" : "")(c.style),
    storage: (c) => counter("db", "Storage used", formatBytes(s.storage_bytes))(c.style),
    review: (c) => counter("eye", "Needs review", s.needs_review, s.needs_review ? "warn" : "")(c.style),
    family: () => data.members.length > 0 ? (
      <div className="members">
        {data.members.map((m: User) => (
          <Link key={m.id} to={`/search?owner=${m.id}`} className="member">
            <Avatar user={m} />
            <div style={{ fontWeight: 650 }}>{m.display_name}</div>
            <div className="muted small">{m.is_main_admin ? "Administrator" : m.role_label || "Family member"}{m.is_head ? " · Family head" : ""}</div>
          </Link>
        ))}
      </div>
    ) : <div className="ov-empty small">No family members yet. The administrator can add them in Settings → Family &amp; access.</div>,
    saved_views: () => data.saved_views.length > 0 ? (
      <div className="row">{data.saved_views.map((v: any) => <Link key={v.id} className="btn" to={`/search?${new URLSearchParams(v.query).toString()}`}><Icon name="list" size={16} /> {v.name} <span className="badge neutral">{v.count}</span></Link>)}</div>
    ) : <div className="ov-empty small">Mark a saved view “Show on Overview” to see it here.</div>,
    review_queue: () => data.review.length > 0 ? <DocTable docs={data.review} empty="" /> : (editing ? <div className="ov-empty small">Nothing waits for review.</div> : null),
    security: () => data.security_health ? <HealthSummary h={data.security_health} compact /> : null,
    sessions: (c) => data.active_sessions_tile ? <SessionsTile cols={c.cols} /> : null,
    backup: () => data.admin ? (data.admin.backup_health ? (
      <div className="stack backup-widget" data-health={data.admin.backup_health.state}>
        <div className="row between"><HealthBadge state={data.admin.backup_health.state} label={data.admin.backup_health.label} />
          <span className="small muted">{data.admin.backup_health.latest_verified ? `${data.admin.backup_health.latest_verified.kind === "full" ? "Full" : "Incremental"} · ${formatDateTime(data.admin.backup_health.latest_verified.created_at)}` : "No verified recovery point yet"}</span></div>
        <div className="small">Latest Full: {data.admin.backup_health.latest_full ? formatDateTime(data.admin.backup_health.latest_full.created_at) : "—"} · Destinations: {data.admin.backup_health.destinations.filter((d: any) => d.health === "healthy").length}/{data.admin.backup_health.destinations.length} healthy · Readiness: {data.admin.backup_health.readiness.label} · {data.admin.backup_health.validation.label.replace("Recovery Validation: ", "Validation: ")}</div>
        {data.admin.backup_health.warnings.slice(0, 3).map((w: string) => <div key={w} className="small"><Icon name="alert" size={14} /> {w}</div>)}
        <div className="row small" style={{ gap: 12 }}><Link to="/settings/backup">Backups</Link><Link to="/recovery">Recovery Explorer</Link>{data.admin.failed_jobs > 0 && <span className="badge danger">{data.admin.failed_jobs} failed jobs</span>}</div>
      </div>
    ) : <div className="ov-empty small">Backup health is unavailable.</div>) : null,
    my_recovery: () => data.my_recovery ? (
      <div className="stack">
        <div className="row"><Icon name={data.my_recovery.protected ? "check" : "alert"} /><strong>{data.my_recovery.protected ? "Your documents are protected" : "Not protected yet"}</strong></div>
        <span className="small muted">{data.my_recovery.last_successful_backup ? `Last successful backup ${formatDateTime(data.my_recovery.last_successful_backup)} · ${data.my_recovery.points_available} recovery point(s)` : data.my_recovery.message}</span>
        <Link to="/recovery" className="small">Recovery Explorer ›</Link>
      </div>
    ) : null,
  };
  const hidden = Object.keys(WIDGET_LABELS).filter((id) => !shownIds.includes(id) && body[id] && (id !== "backup" || data.admin) && (id !== "security" || data.security_health !== undefined) && (id !== "sessions" || !!data.active_sessions_tile));
  const single = groups.length === 1 && groups[0].id === "general";
  const tile = (id: string, g: OvGroup, i: number) => {
    const c = cfgOf(id);
    const l = lim(id);
    const el = body[id](c);
    if (!el && !editing) return null;
    const isCircle = c.style.endsWith("circle");
    const link = LINKS[id];
    return (
      <section key={id} aria-label={WIDGET_LABELS[id]} data-widget={id} data-cols={c.cols} data-h={c.h || undefined}
        className={`ov-cell c${c.cols} ov-${c.style}${c.h ? " fixed-h" : ""}${dragging === id ? " dragging" : ""}`}
        style={c.h ? ({ "--tile-h": `${c.h * ROW_PX + (c.h - 1) * GAP_PX}px` } as React.CSSProperties) : undefined}
        draggable={editing} onDragStart={(e) => { setDragging(id); e.dataTransfer.effectAllowed = "move"; }} onDragEnd={() => { setDragging(null); setDropGroup(null); }}
        onDragOver={(e) => { if (editing && dragging) e.preventDefault(); }} onDrop={(e) => { e.preventDefault(); e.stopPropagation(); if (dragging && dragging !== id) moveTo(dragging, g.id, id); setDragging(null); setDropGroup(null); }}>
        {editing && (
          <div className="ov-tools">
            <span className="drag-handle" title="Drag to move" aria-hidden="true"><Icon name="drag" size={16} /></span>
            <strong className="grow small">{WIDGET_LABELS[id]}</strong>
            <button className="btn small ghost icon-only" aria-label={`Move ${WIDGET_LABELS[id]} earlier`} disabled={i === 0} onClick={() => moveWithin(id, -1)}><Icon name="left" size={14} /></button>
            <button className="btn small ghost icon-only" aria-label={`Move ${WIDGET_LABELS[id]} later`} disabled={i === g.widgets.length - 1} onClick={() => moveWithin(id, 1)}><Icon name="right" size={14} /></button>
            <button className="btn small ghost icon-only" aria-label={`Make ${WIDGET_LABELS[id]} narrower`} disabled={c.cols <= l.cols_min} onClick={() => setCfg(id, { cols: c.cols - 1 })}><Icon name="minus" size={14} /></button>
            <button className="btn small ghost icon-only" aria-label={`Make ${WIDGET_LABELS[id]} wider`} disabled={c.cols >= l.cols_max} onClick={() => setCfg(id, { cols: c.cols + 1 })}><Icon name="plus" size={14} /></button>
            <select aria-label={`${WIDGET_LABELS[id]} height`} value={c.h || 0} onChange={(e) => setCfg(id, { h: Number(e.target.value) || undefined })}>
              <option value={0}>Height: fit content</option>
              {Array.from({ length: l.h_max - l.h_min + 1 }, (_x, k) => l.h_min + k).map((h) => <option key={h} value={h}>Height: {h} row{h > 1 ? "s" : ""}</option>)}
            </select>
            <select aria-label={`${WIDGET_LABELS[id]} style`} value={c.style} onChange={(e) => setCfg(id, { style: e.target.value as any })}>
              {Object.entries(STYLE_LABELS).filter(([k]) => l.circle || !k.endsWith("circle")).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            {!single && <select aria-label={`Group of ${WIDGET_LABELS[id]}`} value={g.id} onChange={(e) => moveTo(id, e.target.value)}>
              {groups.map((x) => <option key={x.id} value={x.id}>Group: {x.name}</option>)}</select>}
            {l.options.length > 0 && <button className="btn small ghost icon-only" aria-label={`${WIDGET_LABELS[id]} settings`} onClick={() => setSettingsFor(id)}><Icon name="settings" size={14} /></button>}
            <button className="btn small ghost icon-only" aria-label={`Remove ${WIDGET_LABELS[id]}`} onClick={() => setGroups((gs) => gs.map((x) => ({ ...x, widgets: x.widgets.filter((w) => w !== id) })))}><Icon name="x" size={14} /></button>
          </div>
        )}
        <div className={`ov-card card${isCircle ? " circle" : ""}`}>
          {!isCircle && id !== "date" && (
            <h2 className="ov-title"><Icon name={WIDGET_ICON[id] || "file"} size={18} /> {WIDGET_LABELS[id].replace(/ \(count\)$/, "")}
              {link && link[0] && <Link to={link[0]} className="small">{link[1]} ›</Link>}</h2>
          )}
          {el || <div className="ov-empty small">Nothing to show right now.</div>}
        </div>
        {editing && <span className="ov-resize" role="presentation" title={`Drag to resize ${WIDGET_LABELS[id]}`} data-resize={id}
          onPointerDown={(e) => startResize(id, e)}><Icon name="drag" size={12} /></span>}
      </section>
    );
  };
  return (
    <div className="stack" style={{ display: "flex", flexDirection: "column", gap: "1.2rem" }}>
      <div className="page-head">
        <div><h1>{greeting()}, {session?.user?.display_name}</h1><p className="muted" style={{ fontSize: "1.1rem" }}>Your family documents, in one place.</p></div>
        {!editing && <div className="row">
          <button className="btn ghost small" onClick={() => setEditing(true)} data-edit-layout><Icon name="grid" size={16} /> Edit Layout</button>
          <button className="btn primary" onClick={() => setUploading(true)}><Icon name="upload" /> Upload documents</button>
        </div>}
      </div>
      {editing && (
        <div className="card ov-editbar" role="region" aria-label="Edit layout">
          <div className="grow"><strong>Edit Layout <HelpTip id="dashboard.edit" /></strong><div className="small muted">Drag tiles, resize them with the corner handle or the size controls, and arrange them in groups. Changes apply when you save.</div></div>
          <div className="row">
            <select aria-label="Add widget" value={adding} onChange={(e) => { const id = e.target.value; if (id) { setGroups((gs) => gs.map((g) => (g.id === "general" ? { ...g, widgets: [...g.widgets, id] } : g))); setAdding(""); } }} disabled={!hidden.length}>
              <option value="">{hidden.length ? "Add widget…" : "All widgets are shown"}</option>
              {hidden.map((id) => <option key={id} value={id}>{WIDGET_LABELS[id]}</option>)}
            </select>
            <form className="row" style={{ gap: ".3rem" }} onSubmit={(e) => { e.preventDefault(); addGroup(); }}>
              <input type="text" aria-label="New group name" placeholder="New group, e.g. Renewals" maxLength={40} value={newGroup} onChange={(e) => setNewGroup(e.target.value)} style={{ width: "13rem" }} />
              <button className="btn small" disabled={!newGroup.trim()}><Icon name="plus" size={14} /> Add group</button>
              <HelpTip id="dashboard.groups" />
            </form>
            <button className="btn small" onClick={() => setResetting(true)}>Reset Layout…</button>
            <button className="btn small" onClick={() => { setEditing(false); if (lay.data) apply(lay.data); }}>Cancel</button>
            <button className="btn small primary" onClick={save} disabled={saving}>Save layout</button>
          </div>
        </div>
      )}
      {groups.map((g, gi) => {
        const visible = g.widgets.filter((id) => body[id]);
        if (!editing && !visible.some((id) => body[id](cfgOf(id))) && g.id === "general" && !single) return null;
        return (
          <div key={g.id} className={`ov-group${dropGroup === g.id ? " drop-target" : ""}`} data-group={g.id}
            onDragOver={(e) => { if (editing && dragging) { e.preventDefault(); setDropGroup(g.id); } }}
            onDrop={(e) => { e.preventDefault(); if (dragging) moveTo(dragging, g.id); setDragging(null); setDropGroup(null); }}>
            {(!single || editing) && (
              <div className="ov-group-head">
                <button className="btn small ghost icon-only" aria-expanded={!g.collapsed} aria-label={`${g.collapsed ? "Expand" : "Collapse"} ${g.name}`} onClick={() => toggleCollapse(g)}><Icon name={g.collapsed ? "right" : "down"} size={14} /></button>
                {editing ? <input type="text" aria-label={`Name of group ${g.name}`} value={g.name} maxLength={40} onChange={(e) => setGroups((gs) => gs.map((x) => (x.id === g.id ? { ...x, name: e.target.value } : x)))} />
                  : <h2>{g.name}</h2>}
                {g.collapsed && <span className="small muted">{visible.length} tile{visible.length === 1 ? "" : "s"}</span>}
                {editing && <>
                  <button className="btn small ghost icon-only" aria-label={`Move group ${g.name} up`} disabled={gi === 0} onClick={() => moveGroup(g.id, -1)}><Icon name="up" size={14} /></button>
                  <button className="btn small ghost icon-only" aria-label={`Move group ${g.name} down`} disabled={gi === groups.length - 1} onClick={() => moveGroup(g.id, 1)}><Icon name="down" size={14} /></button>
                  {g.id !== "general" ? <button className="btn small ghost" onClick={() => (g.widgets.length ? setRemoving(g) : setGroups(groups.filter((x) => x.id !== g.id)))}>Remove group…</button>
                    : <span className="small muted">Default group</span>}
                </>}
              </div>
            )}
            {!g.collapsed && (
              <div className={`ov-grid${editing ? " editing" : ""}`}>
                {visible.map((id, i) => tile(id, g, i))}
                {editing && visible.length === 0 && <div className="ov-group-empty small muted">Drag tiles here, or choose this group in a tile's Group list.</div>}
              </div>
            )}
          </div>
        );
      })}
      {shownIds.length === 0 && <div className="empty">Your Overview is empty. Choose Edit Layout to add widgets.</div>}
      {settingsFor && <WidgetSettingsDialog id={settingsFor} cfg={cfgOf(settingsFor)} countries={data.holiday_countries} onClose={() => setSettingsFor(null)}
        onSave={(st) => { setCfg(settingsFor, { settings: st }); setSettingsFor(null); }} />}
      {removing && <RemoveGroupDialog group={removing} groups={groups} onClose={() => setRemoving(null)} onConfirm={(dest) => {
        setGroups((gs) => gs.filter((x) => x.id !== removing.id).map((x) => (x.id === dest ? { ...x, widgets: [...x.widgets, ...removing.widgets] } : x)));
        setRemoving(null);
      }} />}
      {resetting && <Confirm title="Reset Layout" confirmLabel="Reset my layout" onClose={() => setResetting(false)}
        message={<p>Your Overview goes back to the default tiles, sizes and groups. Only your own layout changes; documents and settings are not touched. <HelpTip id="dashboard.reset" /></p>}
        onConfirm={async () => { try { const r = await api<LayoutPayload>("dashboard/layout/reset", { method: "POST" }); apply(r); lay.reload(); refresh(); setResetting(false); setEditing(false); toast("Layout reset to the default"); } catch (e: any) { toast(e.message, "error"); } }} />}
      {uploading && <UploadDialog onClose={() => setUploading(false)} onDone={() => { setUploading(false); reload(); }} />}
    </div>
  );
}

/** Removing a group never removes its tiles: they move to the group chosen here (General by default). */
function RemoveGroupDialog({ group, groups, onClose, onConfirm }: { group: OvGroup; groups: OvGroup[]; onClose: () => void; onConfirm: (dest: string) => void }) {
  const [dest, setDest] = useState("general");
  return (
    <Modal title={`Remove group “${group.name}”`} onClose={onClose}>
      <div className="stack">
        <p>{group.widgets.length} tile{group.widgets.length === 1 ? "" : "s"} in this group will move to the group you choose. No tile is removed.</p>
        <div className="field"><label htmlFor="rg-dest">Move its tiles to</label>
          <select id="rg-dest" value={dest} onChange={(e) => setDest(e.target.value)}>{groups.filter((g) => g.id !== group.id).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select></div>
        <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" onClick={() => onConfirm(dest)}>Move tiles and remove group</button></div>
      </div>
    </Modal>
  );
}
