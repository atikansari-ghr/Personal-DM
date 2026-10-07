import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, formatBytes, formatDate, formatDateTime } from "../api";
import UploadDialog from "../components/UploadDialog";
import { Avatar, Icon, Modal, Skeleton, StateBadge, useAsync, useToast } from "../components/ui";
import { useSession } from "../session";
import FileTypeIcon from "../components/FileTypeIcon";
import { ActivityWidget, CalendarWidget, DateWidget, DocList, HolidaysWidget, SummaryWidget, WeatherWidget } from "../components/OverviewWidgets";
import { HealthSummary } from "./settings/SecurityCenter";
import type { DocRow, User, WidgetCfg } from "../types";

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
  activity: "Recent activity", review_queue: "Review queue", backup: "Backup status", family: "Family library",
  saved_views: "Saved views", documents: "Documents (count)", members: "Family members (count)",
  expiring: "Expiring in 90 days (count)", storage: "Storage used", review: "Needs review (count)",
  security: "Security Health",
};
export const DEFAULT_WIDGETS = ["date", "weather", "summary", "calendar", "holidays", "upcoming", "shared", "recent", "activity", "review_queue", "backup", "security"];
const STYLE_LABELS: Record<string, string> = { rect: "Rectangular", compact: "Compact rectangular", circle: "Circular", compact_circle: "Compact circular" };
const WIDGET_ICON: Record<string, string> = {
  date: "calendar", weather: "cloud-sun", summary: "grid", calendar: "calendar", holidays: "gift", upcoming: "clock", shared: "share",
  recent: "file", activity: "list", review_queue: "eye", backup: "db", family: "users", saved_views: "list",
  documents: "file", members: "users", expiring: "clock", storage: "db", review: "eye", security: "shield",
};
const LINKS: Record<string, [string, string]> = {
  upcoming: ["/search?expiring_days=90", "View all"], recent: ["/search", "View all"], shared: ["/shared", "View all"],
  holidays: ["", ""], review_queue: ["/ocr-review", "Open"], security: ["/settings/security", "Open"],
};
type Limits = Record<string, { min: number; default: number; max: number; circle: boolean; options: string[] }>;

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
  const [uploading, setUploading] = useState(false);
  const pref = session?.preferences?.dashboard_widgets;
  const saved: string[] = Array.isArray(pref) ? pref : DEFAULT_WIDGETS;
  const savedLayout: Record<string, WidgetCfg> = session?.preferences?.overview_layout || {};
  const [editing, setEditing] = useState(false);
  const [order, setOrder] = useState<string[]>(saved);
  const [layout, setLayout] = useState<Record<string, WidgetCfg>>(savedLayout);
  const [dragging, setDragging] = useState<string | null>(null);
  const [settingsFor, setSettingsFor] = useState<string | null>(null);
  const [adding, setAdding] = useState("");
  useEffect(() => { if (!editing) { setOrder(saved); setLayout(savedLayout); } }, [JSON.stringify(saved), JSON.stringify(savedLayout), editing]);
  if (loading && !data) return <Skeleton lines={6} />;
  if (error) return <div className="alert error">{error}</div>;
  const limits: Limits = data.layout_limits || {};
  const lim = (id: string) => limits[id] || { min: 1, default: 2, max: 4, circle: false, options: [] };
  const cfgOf = (id: string): Required<Pick<WidgetCfg, "w" | "style">> & WidgetCfg => {
    const c = layout[id] || {};
    const l = lim(id);
    const style = c.style && (!c.style.endsWith("circle") || l.circle) ? c.style : "rect";
    return { ...c, w: Math.max(l.min, Math.min(l.max, c.w || l.default)), style };
  };
  const setCfg = (id: string, patch: Partial<WidgetCfg>) => setLayout((x) => ({ ...x, [id]: { ...cfgOf(id), ...x[id], ...patch } }));
  const move = (id: string, delta: number) => setOrder((o) => {
    const i = o.indexOf(id), j = i + delta;
    if (i < 0 || j < 0 || j >= o.length) return o;
    const n = [...o];
    [n[i], n[j]] = [n[j], n[i]];
    return n;
  });
  const dropOn = (target: string) => {
    if (!dragging || dragging === target) return;
    setOrder((o) => { const n = o.filter((x) => x !== dragging); n.splice(n.indexOf(target), 0, dragging); return n; });
    setDragging(null);
  };
  const save = async () => {
    try {
      await api("settings", { method: "PUT", body: { values: { "me.dashboard_widgets": order, "me.overview_layout": Object.fromEntries(order.map((id) => [id, cfgOf(id)])) } } });
      await refresh();
      setEditing(false);
      toast("Overview saved on all your devices");
    } catch (e: any) { toast(e.message, "error"); }
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
    backup: () => data.admin ? (
      <div className="row between">
        <div className="row">
          <Icon name={data.admin.backup.last_success && !data.admin.backup.last_error ? "check" : "info"} />
          <strong>{data.admin.backup.last_success ? (data.admin.backup.last_error ? "Last backup failed" : "Last backup successful") : "No backup yet"}</strong>
          <span className="muted">{data.admin.backup.last_success ? formatDateTime(data.admin.backup.last_success) : "Configure a NAS destination in Settings → Storage & backup."}</span>
          {data.admin.failed_jobs > 0 && <span className="badge danger">{data.admin.failed_jobs} failed jobs</span>}
        </div>
        <Link to="/settings/storage" className="small">View activity ›</Link>
      </div>
    ) : null,
  };
  const shown = order.filter((id) => body[id]);
  const hidden = Object.keys(WIDGET_LABELS).filter((id) => !shown.includes(id) && body[id] && (id !== "backup" || data.admin) && (id !== "security" || data.security_health !== undefined));
  return (
    <div className="stack" style={{ display: "flex", flexDirection: "column", gap: "1.2rem" }}>
      <div className="page-head">
        <div><h1>{greeting()}, {session?.user?.display_name}</h1><p className="muted" style={{ fontSize: "1.1rem" }}>Your family documents, in one place.</p></div>
        {!editing && <div className="row">
          <button className="btn ghost small" onClick={() => setEditing(true)}><Icon name="grid" size={16} /> Customize Overview</button>
          <button className="btn primary" onClick={() => setUploading(true)}><Icon name="upload" /> Upload documents</button>
        </div>}
      </div>
      {editing && (
        <div className="card ov-editbar" role="region" aria-label="Edit layout">
          <div className="grow"><strong>Edit layout</strong><div className="small muted">Drag widgets or use the arrow buttons to reorder. Changes apply when you save.</div></div>
          <div className="row">
            <select aria-label="Add widget" value={adding} onChange={(e) => { const id = e.target.value; if (id) { setOrder((o) => [...o, id]); setAdding(""); } }} disabled={!hidden.length}>
              <option value="">{hidden.length ? "Add widget…" : "All widgets are shown"}</option>
              {hidden.map((id) => <option key={id} value={id}>{WIDGET_LABELS[id]}</option>)}
            </select>
            <button className="btn small" onClick={() => { setOrder(DEFAULT_WIDGETS); setLayout({}); }}>Reset to default</button>
            <button className="btn small" onClick={() => setEditing(false)}>Cancel</button>
            <button className="btn small primary" onClick={save}>Save layout</button>
          </div>
        </div>
      )}
      <div className={`ov-grid${editing ? " editing" : ""}`}>
        {shown.map((id, i) => {
          const c = cfgOf(id);
          const l = lim(id);
          const el = body[id](c);
          if (!el && !editing) return null;
          const isCircle = c.style.endsWith("circle");
          const link = LINKS[id];
          return (
            <section key={id} aria-label={WIDGET_LABELS[id]} data-widget={id}
              className={`ov-cell w${c.w} ov-${c.style}${dragging === id ? " dragging" : ""}`}
              draggable={editing} onDragStart={(e) => { setDragging(id); e.dataTransfer.effectAllowed = "move"; }} onDragEnd={() => setDragging(null)}
              onDragOver={(e) => { if (editing && dragging) e.preventDefault(); }} onDrop={(e) => { e.preventDefault(); dropOn(id); }}>
              {editing && (
                <div className="ov-tools">
                  <span className="drag-handle" title="Drag to move" aria-hidden="true"><Icon name="drag" size={16} /></span>
                  <strong className="grow small">{WIDGET_LABELS[id]}</strong>
                  <button className="btn small ghost icon-only" aria-label={`Move ${WIDGET_LABELS[id]} earlier`} disabled={i === 0} onClick={() => move(id, -1)}><Icon name="left" size={14} /></button>
                  <button className="btn small ghost icon-only" aria-label={`Move ${WIDGET_LABELS[id]} later`} disabled={i === shown.length - 1} onClick={() => move(id, 1)}><Icon name="right" size={14} /></button>
                  <button className="btn small ghost icon-only" aria-label={`Make ${WIDGET_LABELS[id]} narrower`} disabled={c.w <= l.min} onClick={() => setCfg(id, { w: c.w - 1 })}><Icon name="minus" size={14} /></button>
                  <button className="btn small ghost icon-only" aria-label={`Make ${WIDGET_LABELS[id]} wider`} disabled={c.w >= l.max} onClick={() => setCfg(id, { w: c.w + 1 })}><Icon name="plus" size={14} /></button>
                  <select aria-label={`${WIDGET_LABELS[id]} style`} value={c.style} onChange={(e) => setCfg(id, { style: e.target.value as any })}>
                    {Object.entries(STYLE_LABELS).filter(([k]) => l.circle || !k.endsWith("circle")).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                  {l.options.length > 0 && <button className="btn small ghost icon-only" aria-label={`${WIDGET_LABELS[id]} settings`} onClick={() => setSettingsFor(id)}><Icon name="settings" size={14} /></button>}
                  <button className="btn small ghost icon-only" aria-label={`Remove ${WIDGET_LABELS[id]}`} onClick={() => setOrder((o) => o.filter((x) => x !== id))}><Icon name="x" size={14} /></button>
                </div>
              )}
              <div className={`ov-card card${isCircle ? " circle" : ""}`}>
                {!isCircle && id !== "date" && (
                  <h2 className="ov-title"><Icon name={WIDGET_ICON[id] || "file"} size={18} /> {WIDGET_LABELS[id].replace(/ \(count\)$/, "")}
                    {link && link[0] && <Link to={link[0]} className="small">{link[1]} ›</Link>}</h2>
                )}
                {el || <div className="ov-empty small">Nothing to show right now.</div>}
              </div>
            </section>
          );
        })}
      </div>
      {shown.length === 0 && <div className="empty">Your Overview is empty. Choose Customize Overview to add widgets.</div>}
      {settingsFor && <WidgetSettingsDialog id={settingsFor} cfg={cfgOf(settingsFor)} countries={data.holiday_countries} onClose={() => setSettingsFor(null)}
        onSave={(st) => { setCfg(settingsFor, { settings: st }); setSettingsFor(null); }} />}
      {uploading && <UploadDialog onClose={() => setUploading(false)} onDone={() => { setUploading(false); reload(); }} />}
    </div>
  );
}
