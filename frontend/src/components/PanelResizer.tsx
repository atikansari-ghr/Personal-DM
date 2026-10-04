import { useEffect, useRef, useState, type CSSProperties, type RefObject } from "react";

// Resizable three-panel layout: widths live in CSS variables (--tree-w, --list-w) that only the desktop grid uses,
// so phone/tablet layouts are unaffected. Widths are remembered per account on this device.
const MIN = { tree: 180, list: 240 };
const MAX = { tree: 520, list: 760 };
const STEP = 24;

export function usePanelWidths(userId: string | undefined) {
  const key = `pd-panels-${userId || "anon"}`;
  const [widths, setWidths] = useState<{ tree?: number; list?: number }>(() => {
    try {
      return JSON.parse(localStorage.getItem(key) || "{}");
    } catch {
      return {};
    }
  });
  const save = (w: { tree?: number; list?: number }) => {
    setWidths(w);
    try {
      localStorage.setItem(key, JSON.stringify(w));
    } catch {
      /* storage unavailable */
    }
  };
  const style = {
    ...(widths.tree ? { "--tree-w": `${widths.tree}px` } : {}),
    ...(widths.list ? { "--list-w": `${widths.list}px` } : {}),
  } as CSSProperties;
  return { widths, save, style, reset: () => save({}) };
}

function useWidth(ref: RefObject<HTMLElement>) {
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const obs = new ResizeObserver(() => setW(ref.current?.offsetWidth || 0));
    obs.observe(ref.current);
    return () => obs.disconnect();
  }, [ref]);
  return w;
}

export function PanelHandles({ treeRef, listRef, widths, save, reset }: {
  treeRef: RefObject<HTMLElement>; listRef: RefObject<HTMLElement>;
  widths: { tree?: number; list?: number }; save: (w: { tree?: number; list?: number }) => void; reset: () => void;
}) {
  const treeW = useWidth(treeRef);
  const listW = useWidth(listRef);
  const drag = useRef<{ which: "tree" | "list"; startX: number; start: number } | null>(null);
  const clamp = (which: "tree" | "list", v: number) => Math.round(Math.min(MAX[which], Math.max(MIN[which], v)));
  const set = (which: "tree" | "list", v: number) => save({ ...widths, tree: widths.tree ?? treeW, list: widths.list ?? listW, [which]: clamp(which, v) });

  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (!drag.current) return;
      set(drag.current.which, drag.current.start + e.clientX - drag.current.startX);
    };
    const up = () => {
      drag.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  });

  const handle = (which: "tree" | "list", left: number, current: number, label: string) => (
    <div
      className="panel-handle"
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuemin={MIN[which]}
      aria-valuemax={MAX[which]}
      aria-valuenow={current}
      tabIndex={0}
      style={{ left: left - 4 }}
      title={`${label} — drag, or use arrow keys. Double-click to reset.`}
      onPointerDown={(e) => {
        drag.current = { which, startX: e.clientX, start: current };
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
      }}
      onDoubleClick={reset}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") { e.preventDefault(); set(which, current - STEP); }
        if (e.key === "ArrowRight") { e.preventDefault(); set(which, current + STEP); }
        if (e.key === "Home") { e.preventDefault(); set(which, MIN[which]); }
        if (e.key === "End") { e.preventDefault(); set(which, MAX[which]); }
      }}
    />
  );
  if (!treeW) return null;
  return (
    <>
      {handle("tree", treeW, widths.tree ?? treeW, "Resize folder tree")}
      {listW > 0 && handle("list", treeW + listW, widths.list ?? listW, "Resize document list")}
    </>
  );
}
