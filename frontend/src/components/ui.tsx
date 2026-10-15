import { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { Expiry, UserMini } from "../types";
import { useSession } from "../session";
import { HELP, canSee } from "./helpRegistry";

// ---------------------------------------------------------------- icons (inline SVG, no external assets)
const paths: Record<string, string> = {
  sparkle: "M12 3l2.1 5.4L20 10l-5.9 1.6L12 17l-2.1-5.4L4 10l5.9-1.6z",
  home: "M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  folder: "M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  table: "M3 5h18M3 10h18M3 15h18M3 20h18M9 5v15",
  users: "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6M22 19v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8",
  download: "M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2",
  upload: "M12 21V9m0 0l-4 4m4-4l4 4M4 7V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2",
  bell: "M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0",
  archive: "M3 4h18v4H3zM5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zm10 2l-4.3-4.3",
  file: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 13h8M8 17h6",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  db: "M12 8c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3zM4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  share: "M16 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM16 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.6 13.5l6.8 4M15.4 6.5l-6.8 4",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  check: "M5 12l5 5L20 7",
  x: "M18 6L6 18M6 6l12 12",
  menu: "M3 6h18M3 12h18M3 18h18",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01",
  external: "M15 3h6v6M10 14L21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
  plus: "M12 5v14M5 12h14",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  lock: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16v-4M12 8h.01",
  refresh: "M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5",
  more: "M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM12 6a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM12 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  eye: "M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  arrow: "M5 12h14M13 6l6 6-6 6",
  camera: "M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  cloud: "M17.5 19H7a5 5 0 1 1 1-9.9A6 6 0 0 1 19.5 11a4 4 0 0 1-2 8z",
  "cloud-sun": "M8 3v1.5M3.5 7.5H2M4.6 4.6l1 1M12.5 9.1A4 4 0 0 0 5.2 10M17.5 21H9a4 4 0 1 1 .8-7.9A5 5 0 0 1 19.4 15a3 3 0 0 1-1.9 6z",
  rain: "M17.5 15H7a5 5 0 1 1 1-9.9A6 6 0 0 1 19.5 7a4 4 0 0 1-2 8zM8 18l-1 3M12 18l-1 3M16 18l-1 3",
  snow: "M17.5 15H7a5 5 0 1 1 1-9.9A6 6 0 0 1 19.5 7a4 4 0 0 1-2 8zM8 19h.01M12 19h.01M16 19h.01M10 22h.01M14 22h.01",
  storm: "M17.5 15H7a5 5 0 1 1 1-9.9A6 6 0 0 1 19.5 7a4 4 0 0 1-2 8zM13 15l-2 4h3l-2 4",
  fog: "M4 8h16M2 12h20M4 16h16M7 20h10",
  calendar: "M3 5h18v16H3zM3 10h18M8 3v4M16 3v4",
  gift: "M3 8h18v4H3zM5 12v9h14v-9M12 8v13M12 8S10 3 7.5 3a2.5 2.5 0 0 0 0 5M12 8s2-5 4.5-5a2.5 2.5 0 0 1 0 5",
  drag: "M9 5h.01M15 5h.01M9 12h.01M15 12h.01M9 19h.01M15 19h.01",
  left: "M15 18l-6-6 6-6",
  up: "M6 15l6-6 6 6",
  down: "M6 9l6 6 6-6",
  right: "M9 18l6-6-6-6",
  minus: "M5 12h14",
  pin: "M12 21s7-6.2 7-12a7 7 0 0 0-14 0c0 5.8 7 12 7 12zM12 11.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  alert: "M12 3l9.5 17H2.5zM12 10v4M12 17.5h.01",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c2.5 2.8 3.8 5.8 3.8 9s-1.3 6.2-3.8 9c-2.5-2.8-3.8-5.8-3.8-9s1.3-6.2 3.8-9z",
  key: "M15 7a4 4 0 1 1-3.9 5H8v3H5v-3H3V9h8.1A4 4 0 0 1 15 7zM15.5 10.5h.01",
  monitor: "M3 4h18v12H3zM8 20h8M12 16v4",
  offline: "M12 3v10m0 0l-4-4m4 4l4-4M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4M9 18h6",
};
export function Icon({ name, size = 20, className }: { name: string; size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name] || paths.file} />
    </svg>
  );
}

// ---------------------------------------------------------------- avatar / badges
export function Avatar({ user, size }: { user?: UserMini | null; size?: "sm" | "lg" }) {
  const [failed, setFailed] = useState("");
  if (!user) return null;
  const v = user.photo_version;
  if (v && failed !== v) {
    // Served only to signed-in family members; falls back to initials when not visible/available.
    return <img className={`avatar photo ${size || ""}`} src={`/api/users/${user.id}/photo?size=${size === "lg" ? "full" : "thumb"}&v=${v}`} alt="" aria-hidden="true" onError={() => setFailed(v)} />;
  }
  return (
    <span className={`avatar ${size || ""}`} style={{ background: user.avatar_color }} aria-hidden="true">
      {user.initials}
    </span>
  );
}
export function ExpiryBadge({ expiry }: { expiry: Expiry | null }) {
  if (!expiry) return null;
  if (expiry.level === "none") return <span className="badge neutral" title="Confirmed as having no expiry date">No expiry</span>;
  const text = expiry.level === "expired" ? "Expired" : expiry.level === "soon" ? `${expiry.days} days left` : "Valid";
  return (
    <span className={`badge ${expiry.level === "ok" ? "ok" : expiry.level}`}>
      <Icon name={expiry.level === "ok" ? "check" : "clock"} size={13} />
      {text}
    </span>
  );
}
const STATE_LABEL: Record<string, [string, string]> = {
  queued: ["Queued", "neutral"],
  processing: ["Processing", "neutral"],
  needs_review: ["Needs review", "soon"],
  ready: ["Ready", "ok"],
  failed: ["Failed", "danger"],
  unsupported: ["No preview", "neutral"],
};
export function StateBadge({ state }: { state: string }) {
  const [label, cls] = STATE_LABEL[state] || [state, "neutral"];
  if (state === "ready") return null;
  return <span className={`badge ${cls}`}>{label}</span>;
}

// ---------------------------------------------------------------- tooltip (hover, focus and tap)
// One tooltip for the whole application (Change Set V). Rendered in a portal on <body> with a fixed position that is
// measured on open, so no card, table, sidebar, dialog or scroll container can clip it. It opens above the trigger
// and flips below when there is no room, shifts sideways to stay 8 px inside the viewport, follows scrolling and
// resizing, and never changes the layout of the page. Hover and keyboard focus show it; a tap toggles it and a tap
// elsewhere or Escape closes it. Text comes from the help registry (id) or from the caller (text).
let readableGuides: Promise<Set<string>> | null = null;
function useReadableGuides(): Set<string> | null {
  const [set, setSet] = useState<Set<string> | null>(null);
  useEffect(() => {
    readableGuides = readableGuides || fetch("/api/help", { credentials: "same-origin" }).then((r) => (r.ok ? r.json() : { guides: [] }))
      .then((d) => new Set<string>((d.guides || []).map((g: any) => g.slug))).catch(() => new Set<string>());
    let live = true;
    readableGuides.then((x) => { if (live) setSet(x); });
    return () => { live = false; };
  }, []);
  return set;
}

export function HelpTip({ id, text, link }: { id?: string; text?: string; link?: string }) {
  const entry = id ? HELP[id] : undefined;
  if (id && !entry && import.meta.env.DEV) console.error(`HelpTip: unknown help id "${id}"`);
  const session = useSession()?.session;
  const readable = useReadableGuides();
  const body = entry?.text || text || "";
  const rawLink = entry?.link || link;
  const slug = rawLink?.startsWith("/help/") ? rawLink.slice(6).split("#")[0] : null;
  const showLink = !!rawLink && canSee(session, entry?.audience || "all") && (!slug || !!readable?.has(slug));
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; place: "top" | "bottom"; arrow: number } | null>(null);
  const tipId = useId();
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLSpanElement>(null);
  const place = useCallback(() => {
    const b = btn.current?.getBoundingClientRect();
    const p = pop.current;
    if (!b || !p) return;
    const w = p.offsetWidth, h = p.offsetHeight, gap = 8, vw = document.documentElement.clientWidth, vh = window.innerHeight;
    const above = b.top - gap - h >= 8;
    const below = b.bottom + gap + h <= vh - 8;
    const where: "top" | "bottom" = above || !below ? (above ? "top" : (b.top > vh - b.bottom ? "top" : "bottom")) : "bottom";
    const center = b.left + b.width / 2;
    const left = Math.min(Math.max(8, center - w / 2), Math.max(8, vw - w - 8));
    const top = where === "top" ? Math.max(8, b.top - gap - h) : Math.min(vh - h - 8, b.bottom + gap);
    setPos({ top, left, place: where, arrow: Math.min(Math.max(12, center - left), w - 12) });
  }, []);
  useLayoutEffect(() => { if (open) place(); else setPos(null); }, [open, body, showLink, place]);
  useEffect(() => {
    if (!open) return;
    let raf = 0;
    const follow = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(place); };
    const outside = (e: PointerEvent) => { if (!btn.current?.contains(e.target as Node) && !pop.current?.contains(e.target as Node)) { setOpen(false); setPinned(false); } };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); setPinned(false); btn.current?.focus(); } };
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", esc);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("scroll", follow, true); window.removeEventListener("resize", follow);
      document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", esc); };
  }, [open, place]);
  if (!body) return null;
  return (
    <span className="tip" onMouseEnter={() => setOpen(true)} onMouseLeave={() => { if (!pinned) setOpen(false); }}>
      <button ref={btn} type="button" className="tip-btn" aria-describedby={open ? tipId : undefined} aria-expanded={open} aria-label="More information"
        onFocus={() => setOpen(true)} onBlur={(e) => { if (!pinned && !pop.current?.contains(e.relatedTarget as Node)) setOpen(false); }}
        onClick={() => { setPinned((p) => !p); setOpen((o) => !(o && pinned)); }}>
        <Icon name="info" size={16} />
      </button>
      {open && createPortal(
        <span ref={pop} role="tooltip" id={tipId} className={`tip-pop ${pos?.place || "top"}`} data-tip={id || ""}
          style={{ top: pos?.top ?? -9999, left: pos?.left ?? -9999, visibility: pos ? "visible" : "hidden", ["--tip-arrow" as string]: `${pos?.arrow ?? 0}px` }}
          onMouseEnter={() => setOpen(true)} onMouseLeave={() => { if (!pinned) setOpen(false); }}>
          {body}
          {showLink && <>{" "}<a href={rawLink}>Learn more</a></>}
        </span>, document.body)}
    </span>
  );
}

// ---------------------------------------------------------------- modal
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("input,select,textarea,button:not(.modal-close)");
    (first || ref.current)?.focus();
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("keydown", key);
      prev?.focus();
    };
  }, [onClose]);
  // rendered at the end of <body>: an ancestor with a transform or filter would otherwise clip the fixed overlay
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} ref={ref} tabIndex={-1}>
        <div className="modal-head">
          <h2 style={{ margin: 0 }}>{title}</h2>
          <button className="icon-btn modal-close" onClick={onClose} aria-label="Close">
            <Icon name="x" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function Confirm({ title, message, confirmLabel, danger, typeToConfirm, onConfirm, onClose }: {
  title: string; message: ReactNode; confirmLabel: string; danger?: boolean; typeToConfirm?: string;
  onConfirm: (typed: string) => void | Promise<void>; onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose}>
      <div className="stack">
        <div>{message}</div>
        {typeToConfirm && (
          <div className="field">
            <label htmlFor="confirm-typed">Type <strong>{typeToConfirm}</strong> to confirm</label>
            <input id="confirm-typed" type="text" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </div>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className={`btn ${danger ? "danger" : "primary"}`} disabled={busy || (!!typeToConfirm && typed !== typeToConfirm)}
            onClick={async () => { setBusy(true); try { await onConfirm(typed); } finally { setBusy(false); } }}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- toasts
const ToastCtx = createContext<(msg: string, kind?: "ok" | "error") => void>(() => undefined);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; msg: string; kind: string }[]>([]);
  const push = useCallback((msg: string, kind: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((i) => [...i, { id, msg, kind }]);
    setTimeout(() => setItems((i) => i.filter((t) => t.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

// ---------------------------------------------------------------- emoji picker
export const EMOJI_CHOICES = ["📁", "✈️", "🛂", "🛃", "🏠", "🎓", "🩺", "🏦", "🛡️", "🚗", "📜", "🪪", "🧾", "🖼️", "📝", "👪", "👤", "💼", "🏥", "💳",
  "📦", "🔑", "⚖️", "🕌", "🧳", "🏫", "📚", "🧒", "💍", "🗂️", "📅", "⭐"];
const EMOJI_NAMES: Record<string, string> = { "📁": "folder", "✈️": "travel", "🛂": "passport", "🛃": "visa", "🏠": "house", "🎓": "education", "🩺": "medical",
  "🏦": "bank", "🛡️": "insurance", "🚗": "vehicle", "📜": "certificate", "🪪": "identity card", "🧾": "receipt", "🖼️": "photos", "📝": "forms", "👪": "family", "👤": "person" };
export function EmojiPicker({ value, onPick }: { value: string; onPick: (e: string) => void }) {
  return (
    <div className="emoji-grid" role="group" aria-label="Choose an emoji">
      {EMOJI_CHOICES.map((e) => (
        <button key={e} type="button" aria-pressed={value === e} aria-label={EMOJI_NAMES[e] || e} onClick={() => onPick(e)}>{e}</button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- copy button
export function CopyButton({ getValue, label }: { getValue: () => Promise<string> | string; label: string }) {
  const [done, setDone] = useState(false);
  const toast = useToast();
  return (
    <button className="icon-btn" aria-label={`Copy ${label}`} title={`Copy ${label}`} onClick={async () => {
      try {
        const v = await getValue();
        await navigator.clipboard.writeText(v);
        setDone(true);
        toast(`${label} copied`);
        setTimeout(() => setDone(false), 1500);
      } catch {
        toast("Could not copy — your browser blocked clipboard access.", "error");
      }
    }}>
      <Icon name={done ? "check" : "copy"} size={18} />
    </button>
  );
}

// ---------------------------------------------------------------- safe markdown (escapes all HTML; only http(s)/relative links)
function esc(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9 -]/g, "").trim().replace(/ /g, "-");
}
function imgSrc(src: string): string | null {
  if (/^\.\.\/images\/[A-Za-z0-9/_.-]+\.(png|webp|svg|jpg)$/.test(src)) return `/api/help/asset/${src.slice("../images/".length)}`;
  if (/^\/api\/help\/asset\/[A-Za-z0-9/_.-]+$/.test(src)) return src;
  return null;
}
function inline(s: string) {
  let out = esc(s);
  out = out.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_m, alt, src) => {
    const u = imgSrc(String(src));
    return u ? `<img class="doc-shot" src="${u}" alt="${alt}" loading="lazy" decoding="async">` : alt;
  });
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, text, href) => {
    const h = String(href);
    if (!/^(https?:\/\/|\/|#|[a-z0-9-]+\.md(#[a-z0-9-]+)?$)/i.test(h)) return text;
    const target = h.endsWith(".md") || h.includes(".md#") ? `/help/${h.replace(/\.md/, "")}` : h;
    const ext = /^https?:/.test(h) ? ' target="_blank" rel="noopener noreferrer"' : "";
    return `<a href="${target}"${ext}>${text}</a>`;
  });
  return out;
}
export function renderMarkdown(md: string): string {
  const lines = md.replace(/<!--[\s\S]*?-->/g, "").split("\n");
  const html: string[] = [];
  let inCode = false, inList: "" | "ul" | "ol" = "", table: string[] = [];
  const flushTable = () => {
    if (!table.length) return;
    const rows = table.filter((r) => !/^\|?[\s:|-]+\|?$/.test(r.trim()));
    html.push("<table>" + rows.map((r, i) => "<tr>" + r.trim().replace(/^\||\|$/g, "").split("|").map((c) => (i === 0 ? `<th>${inline(c.trim())}</th>` : `<td>${inline(c.trim())}</td>`)).join("") + "</tr>").join("") + "</table>");
    table = [];
  };
  const closeList = () => { if (inList) { html.push(`</${inList}>`); inList = ""; } };
  let quote: string[] = [];
  // GitHub alert syntax (> [!NOTE] / [!TIP] / [!IMPORTANT] / [!WARNING] / [!CAUTION]) becomes a callout. A first bold
  // word "Experimental", "Privacy" or "Expected result" picks that style, so the same file reads well on GitHub.
  const flushQuote = () => {
    if (!quote.length) return;
    const first = quote[0].match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$/i);
    const body = first ? quote.slice(1) : quote;
    let kind = first ? ({ NOTE: "info", TIP: "tip", IMPORTANT: "result", WARNING: "warning", CAUTION: "critical" } as Record<string, string>)[first[1].toUpperCase()] : "alert";
    const lead = body.join(" ").match(/^\*\*(Experimental|Privacy|Expected result)\b/i);
    if (lead) kind = ({ experimental: "experimental", privacy: "privacy", "expected result": "result" } as Record<string, string>)[lead[1].toLowerCase()];
    const label = ({ info: "Info", tip: "Tip", result: "Expected result", warning: "Warning", critical: "Critical", experimental: "Experimental", privacy: "Privacy", alert: "" } as Record<string, string>)[kind];
    const paras = body.join("\n").split(/\n\s*\n/).map((p) => p.split("\n").map((l) => l.replace(/^\s*[-*]\s+/, "• ")).join("<br>"));
    html.push(`<div class="callout ${kind}" role="note">${label && !lead ? `<strong class="callout-label">${label}</strong>` : ""}${paras.map((p) => `<p>${inline(p).replace(/&lt;br&gt;/g, "<br>")}</p>`).join("")}</div>`);
    quote = [];
  };
  for (const line of lines) {
    if (line.startsWith("```")) {
      closeList(); flushTable();
      html.push(inCode ? "</code></pre>" : "<pre><code>");
      inCode = !inCode;
      continue;
    }
    if (inCode) { html.push(esc(line) + "\n"); continue; }
    if (line.trim().startsWith("|")) { closeList(); table.push(line); continue; } else flushTable();
    const h = line.match(/^(#{1,4})\s+(.*?)(\s*\{#([a-z0-9-]+)\})?$/);
    if (h) { closeList(); const id = h[4] || slug(h[2]); html.push(`<h${h[1].length} id="${id}">${inline(h[2])}</h${h[1].length}>`); continue; }
    const ul = line.match(/^\s*[-*]\s+(.*)/), ol = line.match(/^\s*\d+\.\s+(.*)/);
    if (ul || ol) {
      const kind = ul ? "ul" : "ol";
      if (inList !== kind) { closeList(); html.push(`<${kind}>`); inList = kind; }
      html.push(`<li>${inline((ul || ol)![1])}</li>`);
      continue;
    }
    if (line.startsWith(">")) { closeList(); quote.push(line.replace(/^>\s?/, "")); continue; } else flushQuote();
    closeList();
    if (line.trim()) html.push(`<p>${inline(line)}</p>`);
  }
  closeList(); flushTable(); flushQuote();
  return html.join("\n");
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="stack" role="status" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }).map((_, i) => <div key={i} className="skeleton" style={{ height: 18, width: `${90 - i * 12}%` }} />)}
    </div>
  );
}

export function useAsync<T>(fn: () => Promise<T>, deps: any[]): { data: T | null; error: string; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn().then((d) => { if (alive) { setData(d); setError(""); } }).catch((e) => alive && setError(e.message || "Something went wrong")).finally(() => alive && setLoading(false));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}
