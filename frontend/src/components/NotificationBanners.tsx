import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../api";
import { Icon } from "./ui";
import { SEVERITY_LABEL, type Note } from "./NotificationCard";

/** Compact, severity-aware banners for notifications that arrived since the person last looked. They only point to
 *  the Notification Center / the event's page; dismissing a banner never deletes or reads the notification. */
const KEY = (uid: string) => `pd-note-seen-${uid}`;

export default function NotificationBanners({ userId, onUnread }: { userId: string; onUnread: (n: number) => void }) {
  const loc = useLocation();
  const [shown, setShown] = useState<(Note & { id: number })[]>([]);
  const first = useRef(true);
  const read = (): number => { try { return Number(localStorage.getItem(KEY(userId)) || 0); } catch { return 0; } };
  const write = (id: number) => { try { localStorage.setItem(KEY(userId), String(id)); } catch { /* private mode */ } };
  const poll = async () => {
    try {
      const r = await api<{ notifications: (Note & { id: number })[]; unread: number }>("notifications", { query: { status: "unread", limit: 5 } });
      onUnread(r.unread);
      const seen = read();
      const dayAgo = Date.now() - 24 * 3600 * 1000;
      const fresh = r.notifications.filter((n) => n.id > seen && (!first.current || (["critical", "warning"].includes(n.severity) && Date.parse(n.created_at || "") > dayAgo)))
        .filter((n) => n.severity !== "info").slice(0, 3);
      if (r.notifications.length) write(Math.max(seen, ...r.notifications.map((n) => n.id)));
      first.current = false;
      if (fresh.length) setShown((cur) => [...fresh, ...cur.filter((c) => !fresh.some((f) => f.id === c.id))].slice(0, 3));
    } catch { /* offline: nothing to show */ }
  };
  useEffect(() => { poll(); }, [loc.pathname]);
  useEffect(() => { const t = window.setInterval(poll, 60000); return () => window.clearInterval(t); }, []);
  useEffect(() => { if (loc.pathname === "/notifications") setShown([]); }, [loc.pathname]);
  if (!shown.length) return null;
  return (
    <div className="note-banners" role="region" aria-label="New notifications">
      {shown.map((n) => {
        const primary = (n.actions || []).find((a) => a.primary && a.path);
        return (
          <div key={n.id} className={`note-banner sev-${n.severity}`} role={n.severity === "critical" ? "alert" : "status"}>
            <span className="note-banner-icon" aria-hidden="true"><Icon name={n.icon || "bell"} size={18} /></span>
            <span className="grow">{n.test && <span className="badge neutral" style={{ marginRight: ".3rem" }}>TEST</span>}<strong>{SEVERITY_LABEL[n.severity] || "Notice"}:</strong> <span dir="auto">{n.title}</span>{n.summary && <span className="hide-mobile muted"> — {n.summary}</span>}</span>
            <Link className="btn small" to={primary?.path || "/notifications"} onClick={() => setShown((s) => s.filter((x) => x.id !== n.id))}>{primary ? "View" : "Open"}</Link>
            <button type="button" className="icon-btn" aria-label="Dismiss banner" onClick={() => setShown((s) => s.filter((x) => x.id !== n.id))}><Icon name="x" size={16} /></button>
          </div>
        );
      })}
    </div>
  );
}
