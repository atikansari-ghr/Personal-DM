import { useState } from "react";
import { Link } from "react-router-dom";
import { formatDateTime } from "../api";
import { Icon } from "./ui";

/** One structured notification (Change Set O): icon, severity and category (as text, never colour alone), title,
 *  summary, time, unread state, actions and expandable details. Used by the Notification Center, the in-app
 *  banners and the administrator's template preview. */

export interface NoteDetail { label: string; value: string; icon: string; emphasis?: boolean }
export interface NoteAction { key: string; label: string; path: string; primary?: boolean; in_app?: boolean }
export interface Note {
  id?: number; event?: string; category: string; severity: string; icon: string; title: string; summary?: string;
  created_at?: string; read?: boolean; test?: boolean; details?: NoteDetail[]; actions?: NoteAction[]; guidance?: string[]; mandatory?: string[]; footer?: string;
  items?: string[]; items_label?: string; more?: number; link?: string; icon_label?: string;
}

export const SEVERITY_LABEL: Record<string, string> = { critical: "Critical", warning: "Warning", success: "Success", info: "Information" };
export const CATEGORY_LABEL: Record<string, string> = {
  documents: "Documents", expiry: "Expiry & renewal", ocr: "OCR & Local AI", security: "Security", system: "System", sharing: "Sharing & access",
};

export default function NotificationCard({ n, onOpen, onToggleRead, onAction, preview }: {
  n: Note; onOpen?: () => void; onToggleRead?: () => void; onAction?: (a: NoteAction) => void; preview?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const hasMore = (n.details?.length || 0) + (n.guidance?.length || 0) + (n.items?.length || 0) > 0;
  const sev = SEVERITY_LABEL[n.severity] ? n.severity : "info";
  const actions = (n.actions || []).filter((a) => a.path || a.in_app);
  return (
    <article className={`note-card sev-${sev} ${n.read === false ? "unread" : ""}`} aria-label={`${SEVERITY_LABEL[sev]}: ${n.title}`}>
      <div className="note-icon" aria-hidden="true"><Icon name={n.icon || "bell"} size={20} /></div>
      <div className="note-body">
        <div className="note-meta small">
          <span className={`sev-badge sev-${sev}`}>{SEVERITY_LABEL[sev]}</span>
          <span className="muted">{CATEGORY_LABEL[n.category] || n.category}</span>
          {n.test && <span className="badge neutral">TEST</span>}
          {n.created_at && <time className="muted" dateTime={n.created_at}>{formatDateTime(n.created_at)}</time>}
          {n.read === false && <span className="unread-dot" aria-label="Unread" role="img" />}
        </div>
        <h3 className="note-title" dir="auto">{n.title}</h3>
        {n.summary && <p className="note-summary" dir="auto">{n.summary}</p>}
        {!!n.mandatory?.length && <div className="note-mandatory small" role="note">{n.mandatory.map((m, i) => <p key={i} dir="auto"><Icon name="alert" size={14} /> {m}</p>)}</div>}
        {hasMore && (
          <>
            <button type="button" className="btn ghost small note-more" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide details" : "Show details"}</button>
            {open && (
              <div className="note-details">
                {!!n.details?.length && <dl>{n.details.map((d, i) => <div key={i} className={d.emphasis ? "em" : ""}><dt><Icon name={d.icon} size={14} /> {d.label}</dt><dd dir="auto">{d.value}</dd></div>)}</dl>}
                {!!n.items?.length && <><div className="small strong">{n.items_label || "Files"}</div><ol className="small">{n.items.map((x, i) => <li key={i} dir="auto">{x}</li>)}</ol>{!!n.more && <div className="small muted">… and {n.more} more</div>}</>}
                {!!n.guidance?.length && <ul className="small note-guidance">{n.guidance.map((g, i) => <li key={i}>{g}</li>)}</ul>}
                {n.footer && <p className="small muted" dir="auto">{n.footer}</p>}
              </div>
            )}
          </>
        )}
        {(actions.length > 0 || onToggleRead) && (
          <div className="note-actions row">
            {actions.map((a) => a.in_app
              ? <button key={a.key} type="button" className="btn small" disabled={preview} onClick={() => onAction?.(a)}>{a.label}</button>
              : preview ? <span key={a.key} className={`btn small ${a.primary ? "primary" : ""}`}>{a.label}</span>
                : <Link key={a.key} className={`btn small ${a.primary ? "primary" : ""}`} to={a.path} onClick={onOpen}>{a.label}</Link>)}
            {onToggleRead && <button type="button" className="btn ghost small" onClick={onToggleRead}>{n.read ? "Mark unread" : "Mark read"}</button>}
          </div>
        )}
      </div>
    </article>
  );
}
