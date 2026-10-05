import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Icon } from "./ui";

// Zoom steps in percent. 100% = the document's real size (PDF points at 96 dpi; image pixels 1:1).
export const ZOOM_STEPS = [25, 33, 50, 67, 75, 90, 100, 110, 125, 150, 175, 200, 250, 300, 400];
export const MIN_ZOOM = ZOOM_STEPS[0];
export const MAX_ZOOM = ZOOM_STEPS[ZOOM_STEPS.length - 1];
const CSS_PER_PT = 96 / 72;
const GAP = 12; // px between PDF pages and around the content
const MAX_CANVAS_PIXELS = 16_000_000; // iOS Safari refuses larger canvases

export type FitMode = "width" | "page" | "custom";
export interface Size { w: number; h: number }

export const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

/** Next zoom step from the current (possibly fitted, non-step) zoom. */
export function stepZoom(current: number, dir: 1 | -1): number {
  if (dir > 0) return ZOOM_STEPS.find((s) => s > current + 0.5) ?? MAX_ZOOM;
  return [...ZOOM_STEPS].reverse().find((s) => s < current - 0.5) ?? MIN_ZOOM;
}

/** Zoom (percent) that fits ``page`` into the available ``box``. */
export function fitZoom(mode: "width" | "page", page: Size, box: Size): number {
  const availW = Math.max(40, box.w - 2 * GAP);
  const availH = Math.max(40, box.h - 2 * GAP);
  const byWidth = (availW / page.w) * 100;
  if (mode === "width") return clampZoom(byWidth);
  return clampZoom(Math.min(byWidth, (availH / page.h) * 100));
}

type Props = {
  kind: "pdf" | "image";
  src: string; // authenticated same-origin URL; never handed to another site
  title: string;
  downloadHref?: string;
  onUseBrowserViewer?: () => void;
  compact?: boolean;
};

export default function DocViewer({ kind, src, title, downloadHref, onUseBrowserViewer, compact }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<Size>({ w: 0, h: 0 });
  const [pages, setPages] = useState<Size[] | null>(null); // natural sizes in CSS px at 100%
  const [error, setError] = useState("");
  const [mode, setMode] = useState<FitMode>("width");
  const [custom, setCustom] = useState(100);
  const [current, setCurrent] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const pdfRef = useRef<any>(null);

  // ---- load
  useEffect(() => {
    let cancelled = false;
    setPages(null);
    setError("");
    setCurrent(0);
    if (kind === "image") {
      const img = new Image();
      img.onload = () => !cancelled && setPages([{ w: img.naturalWidth || 1, h: img.naturalHeight || 1 }]);
      img.onerror = () => !cancelled && setError("The image could not be displayed. It may be damaged or in a format this browser cannot show.");
      img.src = src;
      return () => { cancelled = true; };
    }
    (async () => {
      try {
        const res = await fetch(src, { credentials: "same-origin" });
        if (!res.ok) throw new Error(res.status === 404 ? "The preview is not available." : `The preview could not be loaded (${res.status}).`);
        const data = await res.arrayBuffer();
        const { openPdf } = await import("../pdfjs");
        const pdf = await openPdf(data);
        if (cancelled) { pdf.destroy(); return; }
        pdfRef.current?.destroy?.();
        pdfRef.current = pdf;
        const sizes: Size[] = [];
        for (let i = 1; i <= pdf.numPages; i++) {
          const vp = (await pdf.getPage(i)).getViewport({ scale: 1 });
          sizes.push({ w: vp.width * CSS_PER_PT, h: vp.height * CSS_PER_PT });
        }
        if (!cancelled) setPages(sizes);
      } catch (e: any) {
        if (!cancelled) setError(e?.name === "InvalidPDFException" ? "This PDF is damaged and cannot be displayed." : e?.message || "The preview could not be displayed.");
      }
    })();
    return () => { cancelled = true; };
  }, [kind, src]);
  useEffect(() => () => { pdfRef.current?.destroy?.(); pdfRef.current = null; }, []);

  // ---- available space (re-fits after resize, rotation, panels opening/closing, full screen)
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setBox({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, [pages, error]);

  const ref = pages?.[current] || pages?.[0];
  const widest: Size | undefined = pages ? { w: Math.max(...pages.map((p) => p.w)), h: ref!.h } : undefined;
  const zoom = !widest || !box.w ? custom : mode === "width" ? fitZoom("width", widest, box) : mode === "page" ? fitZoom("page", ref!, box) : custom;
  const z = zoom / 100;

  const setZoom = useCallback((value: number) => { setCustom(clampZoom(Math.round(value))); setMode("custom"); }, []);
  const zoomIn = () => setZoom(stepZoom(zoom, 1));
  const zoomOut = () => setZoom(stepZoom(zoom, -1));
  const reset = () => setZoom(100);
  const fit = (m: "width" | "page") => { setMode(m); };

  // keep the current page in view when the scale changes
  const pageTop = (i: number) => (pages || []).slice(0, i).reduce((t, p) => t + p.h * z + GAP, GAP);
  const lastZoom = useRef(zoom);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !pages || kind !== "pdf" || lastZoom.current === zoom) return;
    lastZoom.current = zoom;
    el.scrollTop = pageTop(current) - GAP;
  }, [zoom]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el || !pages || kind !== "pdf") return;
    const mid = el.scrollTop + el.clientHeight / 3;
    let i = 0;
    while (i < pages.length - 1 && pageTop(i + 1) <= mid) i++;
    if (i !== current) setCurrent(i);
  };
  const goTo = (i: number) => {
    if (!pages) return;
    const n = Math.min(pages.length - 1, Math.max(0, i));
    setCurrent(n);
    scrollRef.current?.scrollTo({ top: pageTop(n) - GAP });
  };

  // ---- keyboard and trackpad pinch (ctrl + wheel)
  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.target as HTMLElement).closest("input,select,textarea")) return;
    const mod = e.ctrlKey || e.metaKey;
    if (e.key === "+" || e.key === "=") { e.preventDefault(); zoomIn(); }
    else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoomOut(); }
    else if (e.key === "0" && (mod || !e.altKey)) { e.preventDefault(); reset(); }
    else if (!mod && (e.key === "w" || e.key === "W")) fit("width");
    else if (!mod && (e.key === "p" || e.key === "P")) fit("page");
    else if (kind === "pdf" && e.key === "PageDown" && mode === "page") { e.preventDefault(); goTo(current + 1); }
    else if (kind === "pdf" && e.key === "PageUp" && mode === "page") { e.preventDefault(); goTo(current - 1); }
  };
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault(); // zoom the document, not the whole app
      setCustom((c) => clampZoom(Math.round((mode === "custom" ? c : zoom) * (e.deltaY < 0 ? 1.1 : 1 / 1.1))));
      setMode("custom");
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [mode, zoom, pages]);

  // ---- full screen
  useEffect(() => {
    const on = () => setFullscreen(document.fullscreenElement === wrapRef.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  const canFullscreen = typeof document !== "undefined" && !!document.fullscreenEnabled;
  const toggleFullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    else wrapRef.current?.requestFullscreen().catch(() => undefined);
  };

  if (error) {
    return (
      <div className="viewer-error" role="alert">
        <Icon name="file" size={36} />
        <p>{error}</p>
        <div className="row" style={{ justifyContent: "center" }}>
          {downloadHref && <a className="btn" href={downloadHref}><Icon name="download" /> Download</a>}
          {kind === "pdf" && onUseBrowserViewer && <button className="btn ghost" onClick={onUseBrowserViewer}>Use the browser's PDF viewer</button>}
        </div>
      </div>
    );
  }

  return (
    <div className={`viewer ${compact ? "compact" : ""} ${fullscreen ? "fullscreen" : ""}`} ref={wrapRef} tabIndex={0} onKeyDown={onKeyDown}
      role="region" aria-label={`Document viewer: ${title}`} aria-describedby="viewer-keys">
      <div className="viewer-toolbar" role="toolbar" aria-label="Viewer controls">
        <button className="btn small" onClick={zoomOut} disabled={zoom <= MIN_ZOOM} aria-label="Zoom out" title="Zoom out (−)"><span aria-hidden="true">−</span></button>
        <output className="zoom-value" aria-live="polite" aria-label="Zoom level">{Math.round(zoom)}%</output>
        <button className="btn small" onClick={zoomIn} disabled={zoom >= MAX_ZOOM} aria-label="Zoom in" title="Zoom in (+)"><span aria-hidden="true">+</span></button>
        <span className="sep" aria-hidden="true" />
        <button className="btn small" aria-pressed={mode === "page"} onClick={() => fit("page")} title="Fit to page (P)">Fit page</button>
        <button className="btn small" aria-pressed={mode === "width"} onClick={() => fit("width")} title="Fit to width (W)">Fit width</button>
        <button className="btn small" aria-pressed={mode === "custom" && Math.round(zoom) === 100} onClick={reset} title="Actual size (0)">100%</button>
        {kind === "pdf" && pages && pages.length > 1 && (
          <span className="row page-nav" style={{ gap: ".25rem" }}>
            <span className="sep" aria-hidden="true" />
            <button className="btn small" onClick={() => goTo(current - 1)} disabled={current === 0} aria-label="Previous page">‹</button>
            <span className="small" aria-live="polite">Page {current + 1} / {pages.length}</span>
            <button className="btn small" onClick={() => goTo(current + 1)} disabled={current >= pages.length - 1} aria-label="Next page">›</button>
          </span>
        )}
        <span className="grow" />
        {canFullscreen && <button className="btn small" onClick={toggleFullscreen} aria-pressed={fullscreen}>{fullscreen ? "Exit full screen" : "Full screen"}</button>}
        {downloadHref && <a className="btn small" href={downloadHref} aria-label="Download"><Icon name="download" size={16} /></a>}
      </div>
      <p id="viewer-keys" className="sr-only">Keys: plus and minus zoom, 0 actual size, W fit width, P fit page.</p>
      <div className="viewer-scroll" ref={scrollRef} onScroll={onScroll} tabIndex={0} aria-label={`${title} — scroll to read; use the toolbar to zoom`}>
        {!pages ? <div className="empty"><Icon name="refresh" /> Loading preview…</div> : kind === "image" ? (
          <div className="viewer-stage" style={{ padding: GAP }}>
            <img src={src} alt={`Preview of ${title}`} draggable={false}
              style={{ width: pages[0].w * z, height: pages[0].h * z }} />
          </div>
        ) : (
          <div className="viewer-stage" style={{ padding: `${GAP}px ${GAP}px 0` }}>
            {pages.map((p, i) => <PdfPage key={i} pdf={pdfRef} index={i} size={p} zoom={z} root={scrollRef} label={`Page ${i + 1} of ${pages.length}`} />)}
          </div>
        )}
      </div>
    </div>
  );
}

function PdfPage({ pdf, index, size, zoom, root, label }: { pdf: React.MutableRefObject<any>; index: number; size: Size; zoom: number; root: React.RefObject<HTMLDivElement>; label: string }) {
  const holder = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = useState(index < 2);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = holder.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => entries.forEach((e) => e.isIntersecting && setVisible(true)), { root: root.current, rootMargin: "600px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || !pdf.current) return;
    let task: any = null;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const page = await pdf.current.getPage(index + 1);
        if (cancelled) return;
        const dpr = window.devicePixelRatio || 1;
        let scale = zoom * CSS_PER_PT * dpr;
        const base = page.getViewport({ scale: 1 });
        if (base.width * base.height * scale * scale > MAX_CANVAS_PIXELS) scale = Math.sqrt(MAX_CANVAS_PIXELS / (base.width * base.height));
        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current!;
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        task = page.render({ canvasContext: canvas.getContext("2d")!, canvas, viewport } as any);
        await task.promise;
        setFailed(false);
      } catch (e: any) {
        if (!cancelled && e?.name !== "RenderingCancelledException") setFailed(true);
      }
    }, 60); // debounce while zooming quickly
    return () => { cancelled = true; window.clearTimeout(timer); task?.cancel?.(); };
  }, [visible, zoom, index]);

  return (
    <div className="pdf-page" ref={holder} style={{ width: size.w * zoom, height: size.h * zoom, marginBottom: GAP }} role="img" aria-label={label}>
      <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />
      {failed && <span className="pdf-page-error">This page could not be drawn.</span>}
    </div>
  );
}
