import { useRef, useState } from "react";

/**
 * Pick dashboard widgets with checkboxes and order the chosen ones by dragging (mouse) or with the
 * Move up / Move down buttons (keyboard and touch). The order is saved to the account, so it is the same on
 * every device.
 */
export default function WidgetListEditor({ value, choices, labels, disabled, onChange }: {
  value: string[]; choices: string[]; labels: Record<string, string>; disabled?: boolean; onChange: (v: string[]) => void;
}) {
  const [announce, setAnnounce] = useState("");
  const dragFrom = useRef<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const chosen = value.filter((v) => choices.includes(v));
  const others = choices.filter((c) => !chosen.includes(c));
  const label = (k: string) => labels[k] || k;

  const move = (from: number, to: number) => {
    if (to < 0 || to >= chosen.length || from === to) return;
    const next = [...chosen];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    onChange(next);
    setAnnounce(`${label(item)} moved to position ${to + 1} of ${next.length}.`);
  };

  return (
    <div className="widget-editor">
      <p className="small muted" style={{ margin: "0 0 .3rem" }}>Shown on your dashboard, in this order:</p>
      {chosen.length === 0 && <p className="small">Nothing selected — your dashboard will only show the greeting and upload button.</p>}
      <ol className="widget-list" aria-label="Selected widgets in order">
        {chosen.map((k, i) => (
          <li key={k} className={`widget-item ${over === i ? "drop-ok" : ""}`} draggable={!disabled}
            onDragStart={(e) => { dragFrom.current = i; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", k); }}
            onDragOver={(e) => { if (dragFrom.current !== null) { e.preventDefault(); setOver(i); } }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => { e.preventDefault(); if (dragFrom.current !== null) move(dragFrom.current, i); dragFrom.current = null; setOver(null); }}
            onDragEnd={() => { dragFrom.current = null; setOver(null); }}>
            <span className="drag-handle" aria-hidden="true">⋮⋮</span>
            <label className="check grow"><input type="checkbox" checked disabled={disabled} onChange={() => { onChange(chosen.filter((c) => c !== k)); setAnnounce(`${label(k)} removed.`); }} /> {label(k)}</label>
            <button type="button" className="btn small" disabled={disabled || i === 0} onClick={() => move(i, i - 1)} aria-label={`Move ${label(k)} up`}>↑</button>
            <button type="button" className="btn small" disabled={disabled || i === chosen.length - 1} onClick={() => move(i, i + 1)} aria-label={`Move ${label(k)} down`}>↓</button>
          </li>
        ))}
      </ol>
      {others.length > 0 && (
        <>
          <p className="small muted" style={{ margin: ".6rem 0 .3rem" }}>Not shown:</p>
          <ul className="widget-list" aria-label="Available widgets">
            {others.map((k) => (
              <li key={k} className="widget-item off">
                <label className="check grow"><input type="checkbox" checked={false} disabled={disabled} onChange={() => { onChange([...chosen, k]); setAnnounce(`${label(k)} added at the end.`); }} /> {label(k)}</label>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="sr-only" aria-live="polite">{announce}</p>
    </div>
  );
}
