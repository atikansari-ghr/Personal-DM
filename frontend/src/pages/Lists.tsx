import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, formatDate, formatDateTime } from "../api";
import DocumentPanel from "../components/DocumentPanel";
import { Avatar, Confirm, ExpiryBadge, Icon, Modal, Skeleton, StateBadge, useAsync, useToast } from "../components/ui";
import { useSession } from "../session";
import type { DocRow, Meta, User } from "../types";

function Snippet({ text }: { text: string }) {
  // highlights come back as «…» markers; render them safely as <mark>
  const parts = text.split(/(«[^»]*»)/g);
  return <span className="small muted">{parts.map((p, i) => (p.startsWith("«") ? <mark key={i}>{p.slice(1, -1)}</mark> : <span key={i}>{p}</span>))}</span>;
}

export function DocList({ docs }: { docs: DocRow[] }) {
  return (
    <div className="card" style={{ padding: 0 }}>
      {docs.map((d) => (
        <Link key={d.id} to={`/documents/${d.id}`} className="list-item" style={{ color: "inherit", textDecoration: "none", padding: ".8rem 1rem" }}>
          <span className="doc-icon"><Icon name="file" size={18} /></span>
          <div className="grow">
            <div style={{ fontWeight: 600 }}>{d.title}</div>
            <div className="small muted">{d.owner.display_name} · {d.type?.name || (d.format || "").toUpperCase()} · added {formatDate(d.created_at)}</div>
            {d.snippet && <Snippet text={d.snippet} />}
          </div>
          <StateBadge state={d.state} />
          <ExpiryBadge expiry={d.expiry} />
        </Link>
      ))}
    </div>
  );
}

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [members, setMembers] = useState<User[]>([]);
  const q = params.get("q") || "";
  const filters = ["owner", "type", "tag", "state", "expiring_days", "expired"].reduce((acc, k) => ({ ...acc, [k]: params.get(k) || "" }), {} as Record<string, string>);
  const [offset, setOffset] = useState(0);
  const { data, loading } = useAsync(() => api<{ documents: DocRow[]; total: number }>("documents", { query: { q, ...filters, offset, limit: 50 } }), [params.toString(), offset]);
  useEffect(() => { api<Meta>("metadata").then(setMeta); api<{ members: User[] }>("family/members").then((r) => setMembers(r.members)); }, []);
  const set = (k: string, v: string) => { const n = new URLSearchParams(params); v ? n.set(k, v) : n.delete(k); setOffset(0); setParams(n); };
  return (
    <div className="stack">
      <div className="page-head"><h1>{q ? `Results for “${q}”` : "All documents"}</h1>
        <button className="btn" onClick={async () => {
          const name = prompt("Name this saved view");
          if (!name) return;
          await api("views", { body: { name, query: { q, ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) }, show_in_sidebar: true } });
          toast("Saved view added to the sidebar");
        }}><Icon name="plus" /> Save view</button>
      </div>
      <div className="row card" style={{ padding: ".7rem" }}>
        <select aria-label="Owner" value={filters.owner} onChange={(e) => set("owner", e.target.value)} style={{ maxWidth: 200 }}><option value="">Any owner</option>{members.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}</select>
        <select aria-label="Type" value={filters.type} onChange={(e) => set("type", e.target.value)} style={{ maxWidth: 200 }}><option value="">Any type</option>{meta?.types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
        <select aria-label="Tag" value={filters.tag} onChange={(e) => set("tag", e.target.value)} style={{ maxWidth: 180 }}><option value="">Any tag</option>{meta?.tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
        <select aria-label="Status" value={filters.state} onChange={(e) => set("state", e.target.value)} style={{ maxWidth: 180 }}><option value="">Any status</option><option value="needs_review">Needs review</option><option value="failed">Failed</option><option value="unsupported">No preview</option></select>
        <select aria-label="Expiry" value={filters.expiring_days || (filters.expired ? "expired" : "")} onChange={(e) => { const n = new URLSearchParams(params); n.delete("expired"); n.delete("expiring_days"); if (e.target.value === "expired") n.set("expired", "1"); else if (e.target.value) n.set("expiring_days", e.target.value); setParams(n); }} style={{ maxWidth: 200 }}>
          <option value="">Any expiry</option><option value="30">Expires within 30 days</option><option value="90">Expires within 90 days</option><option value="expired">Expired</option>
        </select>
      </div>
      {loading && !data ? <Skeleton lines={6} /> : data && data.documents.length === 0 ? <div className="empty">No documents match.</div> : data && (
        <>
          <p className="muted small">{data.total} document{data.total === 1 ? "" : "s"}</p>
          <DocList docs={data.documents} />
          <div className="row">
            {offset > 0 && <button className="btn" onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button>}
            {offset + 50 < data.total && <button className="btn" onClick={() => setOffset(offset + 50)}>Next</button>}
          </div>
        </>
      )}
    </div>
  );
}

export function SharedPage() {
  const { session } = useSession();
  const { data, loading } = useAsync(() => api<{ documents: DocRow[]; total: number }>("documents", { query: { limit: 200 } }), []);
  if (loading || !data) return <Skeleton />;
  const shared = data.documents.filter((d) => d.owner.id !== session?.user?.id);
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Shared with me</h1><p className="muted">Documents owned by other family members that you can view.</p></div></div>
      {shared.length === 0 ? <div className="empty">Nothing has been shared with you yet.</div> : <DocList docs={shared} />}
    </div>
  );
}

export function DocumentPage() {
  const { id } = useParams();
  const nav = useNavigate();
  return (
    <div>
      <button className="btn small ghost" onClick={() => nav(-1)} style={{ marginBottom: ".6rem" }}>← Back</button>
      <div className="card"><DocumentPanel id={id!} full /></div>
    </div>
  );
}

export function NotificationsPage() {
  const { data, loading, reload } = useAsync(() => api<{ notifications: any[]; unread: number }>("notifications"), []);
  if (loading || !data) return <Skeleton />;
  return (
    <div className="stack">
      <div className="page-head"><h1>Notifications</h1>
        <div className="row"><Link className="btn" to="/settings/account?tab=notifications">Notification settings</Link>{data.unread > 0 && <button className="btn" onClick={() => api("notifications/read", { body: {} }).then(reload)}>Mark all read</button>}</div>
      </div>
      {data.notifications.length === 0 ? <div className="empty">No notifications.</div> : (
        <div className="card" style={{ padding: 0 }}>
          {data.notifications.map((n) => (
            <div key={n.id} className="list-item" style={{ padding: ".8rem 1rem", background: n.read ? "transparent" : "var(--brand-softer)" }}>
              <Icon name={n.kind === "expiry" ? "clock" : "bell"} />
              <div className="grow">
                <div style={{ fontWeight: n.read ? 500 : 700 }}>{n.title} {!n.read && <span className="sr-only">(unread)</span>}</div>
                <div className="small muted">{formatDateTime(n.created_at)}</div>
              </div>
              {n.link && <Link className="btn small" to={n.link} onClick={() => api("notifications/read", { body: { ids: [n.id] } })}>Open</Link>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ArchivePage() {
  const toast = useToast();
  const [confirm, setConfirm] = useState<DocRow | null>(null);
  const { data, loading, reload } = useAsync(() => api<{ documents: DocRow[]; total: number }>("documents", { query: { archived: 1, limit: 200 } }), []);
  const [preview, setPreview] = useState<string | null>(null);
  if (loading || !data) return <Skeleton />;
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Archive</h1><p className="muted">Archived documents are kept indefinitely and hidden from everyone else. Restore them or delete permanently.</p></div></div>
      {data.documents.length === 0 ? <div className="empty">The archive is empty.</div> : (
        <table className="responsive card"><thead><tr><th>Document</th><th>Owner</th><th /></tr></thead><tbody>
          {data.documents.map((d) => (
            <tr key={d.id}><td><button className="btn ghost small" onClick={() => setPreview(d.id)}>{d.title}</button></td><td><div className="row"><Avatar user={d.owner} size="sm" />{d.owner.display_name}</div></td>
              <td className="row"><button className="btn small" onClick={() => api(`documents/${d.id}/restore`, { method: "POST" }).then(() => { toast("Restored"); reload(); }).catch((e) => toast(e.message, "error"))}>Restore</button>
                <button className="btn small danger" onClick={() => setConfirm(d)}>Delete permanently</button></td></tr>
          ))}
        </tbody></table>
      )}
      {preview && <Modal title="Archived document" wide onClose={() => setPreview(null)}><DocumentPanel id={preview} full /></Modal>}
      {confirm && (
        <Confirm title="Delete permanently" danger confirmLabel="Delete forever" typeToConfirm={confirm.title} onClose={() => setConfirm(null)}
          message={<><p>This removes all versions, previews and search data for this document from the server. It cannot be undone.</p><p className="small muted">Copies in existing backups, downloads or offline devices are not affected and follow their own retention.</p></>}
          onConfirm={async (typed) => { await api(`documents/${confirm.id}`, { method: "DELETE", body: { confirm: typed } }); toast("Deleted permanently"); setConfirm(null); reload(); }} />
      )}
    </div>
  );
}
