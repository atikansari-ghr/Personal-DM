import { useEffect, useRef, useState } from "react";

/** Drag-and-drop ordering of a vertical list (table rows or list items) without a library.
 *
 *  - Mouse and touch: press the handle and drag; the list reorders live as the pointer passes a neighbour's middle,
 *    and the new order is committed once on release.
 *  - Keyboard (accessible alternative): focus the handle and press ↑ / ↓; each step is committed and announced.
 *  Items keep their identity (`id`), so only the order changes. */
export function useSortable<T>(items: T[], idOf: (t: T) => number | string, labelOf: (t: T) => string,
  onCommit: (next: T[]) => void | Promise<void>) {
  const [order, setOrder] = useState<T[]>(items);
  const [dragId, setDragId] = useState<number | string | null>(null);
  const [announce, setAnnounce] = useState("");
  const rows = useRef(new Map<number | string, HTMLElement>());
  const start = useRef<string>("");
  const sig = items.map(idOf).join(",");
  useEffect(() => { if (dragId === null) setOrder(items); }, [sig, dragId === null]);  // eslint-disable-line react-hooks/exhaustive-deps

  const commit = (next: T[]) => {
    if (next.map(idOf).join(",") !== sig) onCommit(next);
  };
  const moveTo = (list: T[], id: number | string, to: number) => {
    const from = list.findIndex((x) => idOf(x) === id);
    if (from < 0 || to < 0 || to >= list.length || to === from) return list;
    const next = [...list];
    const [it] = next.splice(from, 1);
    next.splice(to, 0, it);
    return next;
  };

  const handleProps = (item: T) => {
    const id = idOf(item);
    return {
      role: "button" as const,
      tabIndex: 0,
      "aria-roledescription": "sortable",
      "aria-label": `Reorder ${labelOf(item)}. Drag, or press the up and down arrow keys.`,
      className: "drag-handle sortable-handle",
      style: { touchAction: "none" as const, cursor: dragId === id ? "grabbing" : "grab" },
      onPointerDown: (e: React.PointerEvent<HTMLElement>) => {
        if (e.button !== 0) return;
        e.preventDefault();
        (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
        start.current = order.map(idOf).join(",");
        setDragId(id);
      },
      onPointerMove: (e: React.PointerEvent<HTMLElement>) => {
        if (dragId !== id) return;
        setOrder((list) => {
          const idx = list.findIndex((x) => idOf(x) === id);
          const above = idx > 0 ? rows.current.get(idOf(list[idx - 1]))?.getBoundingClientRect() : undefined;
          const below = idx < list.length - 1 ? rows.current.get(idOf(list[idx + 1]))?.getBoundingClientRect() : undefined;
          if (above && e.clientY < above.top + above.height / 2) return moveTo(list, id, idx - 1);
          if (below && e.clientY > below.top + below.height / 2) return moveTo(list, id, idx + 1);
          return list;
        });
      },
      onPointerUp: () => {
        if (dragId !== id) return;
        setDragId(null);
        if (order.map(idOf).join(",") !== start.current) {
          setAnnounce(`${labelOf(item)} moved to position ${order.findIndex((x) => idOf(x) === id) + 1} of ${order.length}.`);
          commit(order);
        }
      },
      onPointerCancel: () => { setDragId(null); setOrder(items); },
      onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => {
        if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
        e.preventDefault();
        const idx = order.findIndex((x) => idOf(x) === id);
        const next = moveTo(order, id, idx + (e.key === "ArrowUp" ? -1 : 1));
        if (next === order) return;
        setOrder(next);
        setAnnounce(`${labelOf(item)} moved to position ${next.findIndex((x) => idOf(x) === id) + 1} of ${next.length}.`);
        commit(next);
      },
    };
  };
  const rowProps = (item: T) => {
    const id = idOf(item);
    return {
      ref: (el: HTMLElement | null) => { if (el) rows.current.set(id, el); else rows.current.delete(id); },
      "data-dragging": dragId === id ? "1" : undefined,
      "data-sort-id": String(id),
    };
  };
  const live = <span className="sr-only" role="status" aria-live="polite">{announce}</span>;
  return { order, handleProps, rowProps, live, dragging: dragId !== null };
}
