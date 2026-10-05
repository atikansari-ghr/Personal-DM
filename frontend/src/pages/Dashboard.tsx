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

export default function Dashboard() {
  const { session } = useSession();
  const { data, loading, error, reload } = useAsync(() => api<any>("dashboard"), []);
  const [uploading, setUploading] = useState(false);
  const widgets = (session?.preferences?.dashboard_widgets || "documents,members,expiring,storage").split(",");
  if (loading && !data) return <Skeleton lines={6} />;
  if (error) return <div className="alert error">{error}</div>;
  const s = data.stats;
  const stats = [
    ["documents", "file", "Documents", s.documents.toLocaleString(), ""],
    ["members", "users", "Family members", s.members, ""],
    ["expiring", "clock", "Expiring in 90 days", s.expiring_90, s.expiring_90 ? "warn" : ""],
    ["storage", "db", "Storage used", formatBytes(s.storage_bytes), ""],
    ["review", "eye", "Needs review", s.needs_review, s.needs_review ? "warn" : ""],
  ].filter(([k]) => widgets.includes(k as string) || (k === "review" && s.needs_review));
  return (
    <div className="stack" style={{ display: "flex", flexDirection: "column", gap: "1.2rem" }}>
      <div className="page-head">
        <div><h1>{greeting()}, {session?.user?.display_name}</h1><p className="muted" style={{ fontSize: "1.1rem" }}>Your family documents, in one place.</p></div>
        <button className="btn primary" onClick={() => setUploading(true)}><Icon name="upload" /> Upload documents</button>
      </div>
      <div className="grid stats">
        {stats.map(([k, icon, label, value, cls]) => (
          <div className="card stat" key={k as string}><Icon name={icon as string} size={34} /><div><div className="muted small">{label}</div><div className={`num ${cls}`}>{value}</div></div></div>
        ))}
      </div>
      {data.members.length > 0 && (
        <section aria-labelledby="fam">
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
      )}
      {data.saved_views.length > 0 && (
        <div className="row">
          {data.saved_views.map((v: any) => <Link key={v.id} className="btn" to={`/search?${new URLSearchParams(v.query).toString()}`}><Icon name="list" size={16} /> {v.name} <span className="badge neutral">{v.count}</span></Link>)}
        </div>
      )}
      <div className="grid two-col">
        <section className="card">
          <h2>Recent documents <Link to="/search" className="small">View all ›</Link></h2>
          <DocTable docs={data.recent} empty="No documents yet. Upload your first one." />
        </section>
        <section className="card">
          <h2>Upcoming expiries <Link to="/search?expiring_days=90" className="small">View all ›</Link></h2>
          {data.expiring.length === 0 ? <div className="empty">Nothing expires in the next 90 days.</div> : data.expiring.map((d: DocRow) => (
            <Link key={d.id} to={`/documents/${d.id}`} className="list-item" style={{ textDecoration: "none", color: "inherit" }}>
              <FileTypeIcon kind={d.file_kind} label={d.file_label} size="sm" />
              <div className="grow"><div style={{ fontWeight: 600 }}>{d.owner.display_name} · {d.type?.name || d.title}</div><div className="muted small">{formatDate(d.expiry_date)}</div></div>
              <ExpiryBadge expiry={d.expiry} />
            </Link>
          ))}
        </section>
      </div>
      {data.review.length > 0 && (
        <section className="card"><h2>Review queue</h2><p className="muted small">Suggested details need your confirmation before they rename documents or schedule reminders.</p><DocTable docs={data.review} empty="" /></section>
      )}
      {data.admin && (
        <div className={`card row between ${data.admin.backup.last_error ? "" : ""}`}>
          <div className="row">
            <Icon name={data.admin.backup.last_success && !data.admin.backup.last_error ? "check" : "info"} />
            <strong>{data.admin.backup.last_success ? (data.admin.backup.last_error ? "Last backup failed" : "Last backup successful") : "No backup yet"}</strong>
            <span className="muted">{data.admin.backup.last_success ? formatDateTime(data.admin.backup.last_success) : "Configure a NAS destination in Settings → Storage & backup."}</span>
            {data.admin.failed_jobs > 0 && <span className="badge danger">{data.admin.failed_jobs} failed jobs</span>}
          </div>
          <Link to="/settings/storage" className="small">View activity ›</Link>
        </div>
      )}
      {uploading && <UploadDialog onClose={() => setUploading(false)} onDone={() => { setUploading(false); reload(); }} />}
    </div>
  );
}
