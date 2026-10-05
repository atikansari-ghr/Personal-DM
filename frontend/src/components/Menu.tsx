import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./ui";

/**
 * Overflow ("⋮") menu rendered in a portal on top of every panel, so it is never clipped by a scrolling list,
 * the tree or the breadcrumb bar. It is positioned from its trigger and kept inside the viewport (it opens
 * upwards or to the left when there is no room). Keyboard: Enter/Space/ArrowDown open it, arrows and Home/End
 * move, Escape or Tab closes and returns focus to the trigger. Clicking outside closes it, and opening another
 * menu closes this one.
 */
export type MenuItem =
  | { label: string; onSelect?: () => void; href?: string; danger?: boolean; hidden?: boolean; icon?: string }
  | "separator";

let closeOpenMenu: (() => void) | null = null;

export default function Menu({ label, items, className = "icon-btn", trigger, minWidth = 220 }: {
  label: string; items: MenuItem[]; className?: string; trigger?: ReactNode; minWidth?: number;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; maxHeight: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const visible = items.filter((i) => i === "separator" || !i.hidden);
  // drop separators at the edges or next to each other (their neighbours may be hidden)
  const shown = visible.filter((i, n) => i !== "separator" || (n > 0 && n < visible.length - 1 && visible[n - 1] !== "separator"));

  const close = (focus = true) => {
    setOpen(false);
    setPos(null);
    if (closeOpenMenu === closer.current) closeOpenMenu = null;
    if (focus) btn.current?.focus();
  };
  const closer = useRef<() => void>(() => close(false));
  closer.current = () => close(false);

  const show = () => {
    closeOpenMenu?.();
    closeOpenMenu = closer.current;
    setOpen(true);
  };

  useLayoutEffect(() => {
    if (!open || !btn.current || !menu.current) return;
    const r = btn.current.getBoundingClientRect();
    const m = menu.current.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight, gap = 4, pad = 8;
    const below = vh - r.bottom - pad, above = r.top - pad;
    const up = m.height > below && above > below;
    const maxHeight = Math.max(120, (up ? above : below) - gap);
    const h = Math.min(m.height, maxHeight);
    const top = up ? r.top - gap - h : r.bottom + gap;
    let left = r.right - m.width; // right-aligned with the trigger by default
    if (left < pad) left = Math.min(r.left, vw - m.width - pad);
    left = Math.max(pad, Math.min(left, vw - m.width - pad));
    setPos({ top: Math.max(pad, top), left, maxHeight });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    const outside = (e: MouseEvent | TouchEvent) => {
      const t = e.target as Node;
      if (!menu.current?.contains(t) && !btn.current?.contains(t)) close(false);
    };
    const away = () => close(false);
    document.addEventListener("mousedown", outside);
    document.addEventListener("touchstart", outside);
    window.addEventListener("resize", away);
    window.addEventListener("scroll", away, true);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("touchstart", outside);
      window.removeEventListener("resize", away);
      window.removeEventListener("scroll", away, true);
    };
  }, [open]);
  useEffect(() => () => { if (closeOpenMenu === closer.current) closeOpenMenu = null; }, []);

  const onMenuKey = (e: React.KeyboardEvent) => {
    e.stopPropagation();
    const els = [...(menu.current?.querySelectorAll<HTMLElement>("[role=menuitem]") || [])];
    const i = els.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "Tab") close(false);
    else if (e.key === "ArrowDown") { e.preventDefault(); els[(i + 1) % els.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); els[(i - 1 + els.length) % els.length]?.focus(); }
    else if (e.key === "Home") { e.preventDefault(); els[0]?.focus(); }
    else if (e.key === "End") { e.preventDefault(); els[els.length - 1]?.focus(); }
  };

  if (!shown.length) return null;
  return (
    <>
      <button ref={btn} type="button" className={className} aria-label={label} title={label} aria-haspopup="menu" aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); open ? close(false) : show(); }}
        onKeyDown={(e) => { if (e.key === "ArrowDown" && !open) { e.preventDefault(); e.stopPropagation(); show(); } }}>
        {trigger || <Icon name="more" />}
      </button>
      {open && createPortal(
        <div ref={menu} className="menu-pop" role="menu" aria-label={label} onKeyDown={onMenuKey} onClick={(e) => e.stopPropagation()}
          style={{ minWidth, top: pos?.top ?? -9999, left: pos?.left ?? -9999, maxHeight: pos?.maxHeight, visibility: pos ? "visible" : "hidden" }}>
          {shown.map((it, n) => it === "separator" ? <div key={`s${n}`} role="separator" className="menu-sep" /> : it.href ? (
            <a key={it.label} role="menuitem" tabIndex={-1} href={it.href} className={it.danger ? "danger" : ""} onClick={() => close(false)}>{it.icon && <Icon name={it.icon} size={16} />}{it.label}</a>
          ) : (
            <button key={it.label} type="button" role="menuitem" tabIndex={-1} className={it.danger ? "danger" : ""} onClick={() => { close(false); it.onSelect?.(); }}>{it.icon && <Icon name={it.icon} size={16} />}{it.label}</button>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
}
