import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, formatBytes, formatDate, formatDateTime } from "../api";
import UploadDialog from "../components/UploadDialog";
import { Avatar, ExpiryBadge, Icon, Skeleton, StateBadge, useAsync } from "../components/ui";
import { useSession } from "../session";
import FileTypeIcon from "../components/FileTypeIcon";
import type { DocRow, User } from "../types";

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

const ALL_WIDGETS = ["documents", "members", "expiring", "storage", "review", "family", "saved_views", "recent", "upcoming", "review_queue", "backup"];
const STATS = ["documents", "members", "expiring", "storage", "review"];
const HALF = ["recent", "upcoming"];
// i starts a pair when it is half-width and the run of consecutive half-width items before it has even length
const pairStart = (order: string[], i: number) => {
  let n = 0;
  for (let j = i - 1; j >= 0 && HALF.includes(order[j]); j--) n++;
  return n % 2 === 0 && HALF.includes(order[i + 1]);
};

export default function Dashboard() {
  const { session } = useSession();
  const { data, loading, error, reload } = useAsync(() => api<any>("dashboard"), []);
  const [uploading, setUploading] = useState(false);
  const pref = session?.preferences?.dashboard_widgets;
  const widgets: string[] = Array.isArray(pref) ? pref : ALL_WIDGETS;
  if (loading && !data) return <Skeleton lines={6} />;
  if (error) return <div className="alert error">{error}</div>;
  const s = data.stats;
  const statDefs: Record<string, [string, string, any, string]> = {
    documents: ["file", "Documents", s.documents.toLocaleString(), ""],
    members: ["users", "Family members", s.members, ""],
    expiring: ["clock", "Expiring in 90 days", s.expiring_90, s.expiring_90 ? "warn" : ""],
    storage: ["db", "Storage used", formatBytes(s.storage_bytes), ""],
    review: ["eye", "Needs review", s.needs_review, s.needs_review ? "warn" : ""],
  };
  const statKeys = widgets.filter((w) => STATS.includes(w));
  const sections: Record<string, () => JSX.Element | null> = {
    stats: () => statKeys.length ? (
      <div className="grid stats wide" key="stats">
        {statKeys.map((k) => { const [icon, label, value, cls] = statDefs[k]; return <div className="card stat" key={k}><Icon name={icon} size={34} /><div><div className="muted small">{label}</div><div className={`num ${cls}`}>{value}</div></div></div>; })}
      </div>
    ) : null,
    family: () => data.members.length > 0 ? (
      <section aria-labelledby="fam" className="wide" key="family">
        <h2 id="fam">Family library</h2>
        <div className="members">
          {data.members.map((m: User) => (
            <Link key={m.id} to={`/search?owner=${m.id}`} className="member">
              <Avatar user={m} />
              <div style={{ fontWeight: 650 }}>{m.display_name}</div>
              <div className="muted small">{m.is_main_admin ? "Administrator" : m.role_label || "Family member"}{m.is_head ? " · Family head" : ""}</div>
            </Link>
          ))}
        </div>
      </section>
    ) : null,
    saved_views: () => data.saved_views.length > 0 ? (
      <div className="row wide" key="saved_views">
        {data.saved_views.map((v: any) => <Link key={v.id} className="btn" to={`/search?${new URLSearchParams(v.query).toString()}`}><Icon name="list" size={16} /> {v.name} <span className="badge neutral">{v.count}</span></Link>)}
      </div>
    ) : null,
    recent: () => (
      <section className="card" key="recent">
        <h2>Recent documents <Link to="/search" className="small">View all ›</Link></h2>
        <DocTable docs={data.recent} empty="No documents yet. Upload your first one." />
      </section>
    ),
    upcoming: () => (
      <section className="card" key="upcoming">
        <h2>Upcoming expiries <Link to="/search?expiring_days=90" className="small">View all ›</Link></h2>
        {data.expiring.length === 0 ? <div className="empty">Nothing expires in the next 90 days.</div> : data.expiring.map((d: DocRow) => (
          <Link key={d.id} to={`/documents/${d.id}`} className="list-item" style={{ textDecoration: "none", color: "inherit" }}>
            <FileTypeIcon kind={d.file_kind} label={d.file_label} size="sm" />
            <div className="grow"><div style={{ fontWeight: 600 }}>{d.owner.display_name} · {d.type?.name || d.title}</div><div className="muted small">{formatDate(d.expiry_date)}</div></div>
            <ExpiryBadge expiry={d.expiry} />
          </Link>
        ))}
      </section>
    ),
    review_queue: () => data.review.length > 0 ? (
      <section className="card wide" key="review_queue"><h2>Review queue</h2><p className="muted small">Suggested details need your confirmation before they rename documents or schedule reminders.</p><DocTable docs={data.review} empty="" /></section>
    ) : null,
    backup: () => data.admin ? (
      <div className="card row between wide" key="backup">
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
  // the counters form one row, placed where the first chosen counter is in the list
  const order: string[] = [];
  widgets.forEach((w) => { const key = STATS.includes(w) ? "stats" : w; if (sections[key] && !order.includes(key)) order.push(key); });
  return (
    <div className="stack" style={{ display: "flex", flexDirection: "column", gap: "1.2rem" }}>
      <div className="page-head">
        <div><h1>{greeting()}, {session?.user?.display_name}</h1><p className="muted" style={{ fontSize: "1.1rem" }}>Your family documents, in one place.</p></div>
        <div className="row">
          <Link className="btn ghost small" to="/settings/account?tab=appearance">Customise</Link>
          <button className="btn primary" onClick={() => setUploading(true)}><Icon name="upload" /> Upload documents</button>
        </div>
      </div>
      <div className="dash-grid">{order.map((k, i) => {
        // Recent documents and Upcoming expiries sit side by side when they are next to each other in the chosen
        // order; otherwise they take the full width so the order is kept without gaps.
        const half = HALF.includes(k) && (HALF.includes(order[i - 1]) && pairStart(order, i - 1) || HALF.includes(order[i + 1]) && pairStart(order, i));
        const el = sections[k]();
        return el ? <div key={k} className={half ? "" : "wide"}>{el}</div> : null;
      })}</div>
      {uploading && <UploadDialog onClose={() => setUploading(false)} onDone={() => { setUploading(false); reload(); }} />}
    </div>
  );
}
