import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import NotificationCard, { CATEGORY_LABEL, SEVERITY_LABEL, type Note } from "../components/NotificationCard";
import { Skeleton, useToast } from "../components/ui";

/** Notification Center: the person's own notifications with category, severity and unread filters, read/unread,
 *  actions and incremental loading. Critical events stay here after any banner disappears. */
export default function NotificationsPage() {
  const toast = useToast();
  const [items, setItems] = useState<(Note & { id: number })[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [unread, setUnread] = useState(0);
  const [status, setStatus] = useState("all");
  const [category, setCategory] = useState("");
  const [severity, setSeverity] = useState("");
  const query = (before?: number) => ({ ...(status === "unread" ? { status: "unread" } : {}), ...(category ? { category } : {}), ...(severity ? { severity } : {}), ...(before ? { before } : {}), limit: 30 });
  const load = async (more = false) => {
    const r = await api<{ notifications: any[]; next: number | null; unread: number }>("notifications", { query: query(more ? next || undefined : undefined) });
    setItems((cur) => (more && cur ? [...cur, ...r.notifications] : r.notifications));
    setNext(r.next);
    setUnread(r.unread);
    window.dispatchEvent(new CustomEvent("pd-notifications", { detail: r.unread }));
  };
  useEffect(() => { setItems(null); load(); }, [status, category, severity]);
  const mark = async (ids: number[] | undefined, makeUnread = false) => {
    await api("notifications/read", { body: { ...(ids ? { ids } : {}), ...(makeUnread ? { unread: true } : {}) } });
    load();
  };
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Notifications</h1><p className="muted">{unread ? `${unread} unread` : "All caught up"}</p></div>
        <div className="row"><Link className="btn" to="/settings/account?tab=notifications">Notification settings</Link>{unread > 0 && <button className="btn" onClick={() => mark(undefined)}>Mark all read</button>}</div>
      </div>
      <div className="row note-filters" role="group" aria-label="Filter notifications">
        <div className="seg" role="radiogroup" aria-label="Show">
          {[["all", "All"], ["unread", "Unread"]].map(([k, l]) => <button key={k} type="button" role="radio" aria-checked={status === k} className={status === k ? "active" : ""} onClick={() => setStatus(k)}>{l}</button>)}
        </div>
        <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)}><option value="">All categories</option>{Object.entries(CATEGORY_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <select aria-label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)}><option value="">All severities</option>{Object.entries(SEVERITY_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
      </div>
      {items === null ? <Skeleton lines={6} /> : items.length === 0 ? <div className="empty">No notifications{status === "unread" || category || severity ? " match these filters" : ""}.</div> : (
        <div className="note-list">
          {items.map((n) => (
            <NotificationCard key={n.id} n={n} onOpen={() => !n.read && mark([n.id])} onToggleRead={() => mark([n.id], !!n.read)}
              onAction={async (a) => {
                try { const r = await api<any>(`notifications/${n.id}/action`, { body: { action: a.key } }); toast(r.until ? `Reminders paused until ${r.until}` : "Done"); load(); }
                catch (e: any) { toast(e.message, "error"); }
              }} />
          ))}
          {next && <button className="btn" onClick={() => load(true)}>Load more</button>}
        </div>
      )}
    </div>
  );
}
