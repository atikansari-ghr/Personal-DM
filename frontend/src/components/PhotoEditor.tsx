import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { UserMini } from "../types";
import { Avatar, useToast } from "./ui";

/** Upload / crop / replace / remove a profile photo. The server validates, strips metadata and re-encodes. */
export default function PhotoEditor({ user, endpoint, onChanged }: { user: UserMini; endpoint: string; onChanged: () => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const [px, setPx] = useState(0.5);
  const [py, setPy] = useState(0.5);
  const [busy, setBusy] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!file) { setImg(null); return; }
    if (file.size > 5 * 1024 * 1024) { toast("The image is larger than 5 MB.", "error"); setFile(null); return; }
    const url = URL.createObjectURL(file);
    const im = new Image();
    im.onload = () => { setImg(im); setZoom(1); setPx(0.5); setPy(0.5); };
    im.onerror = () => { toast("This file is not a supported image (JPEG, PNG or WebP).", "error"); setFile(null); };
    im.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const crop = () => {
    if (!img) return null;
    const w = img.naturalWidth, h = img.naturalHeight, side = Math.min(w, h);
    const s = Math.max(16, Math.round(side * zoom));
    const left = Math.round(px * (w - s)), top = Math.round(py * (h - s));
    return { left, top, s, w, h, side };
  };

  useEffect(() => {
    const c = crop();
    const ctx = canvas.current?.getContext("2d");
    if (!c || !ctx || !img) return;
    ctx.clearRect(0, 0, 192, 192);
    ctx.save();
    ctx.beginPath(); ctx.arc(96, 96, 96, 0, Math.PI * 2); ctx.clip();
    ctx.drawImage(img, c.left, c.top, c.s, c.s, 0, 0, 192, 192);
    ctx.restore();
  }, [img, zoom, px, py]);

  const save = async () => {
    const c = crop();
    if (!file || !c) return;
    const form = new FormData();
    form.append("file", file);
    form.append("crop_x", String(c.left / c.w));
    form.append("crop_y", String(c.top / c.h));
    form.append("crop_size", String(c.s / c.side));
    setBusy(true);
    try {
      await api(endpoint, { form });
      toast("Profile photo saved");
      setFile(null);
      onChanged();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try { await api(endpoint, { method: "DELETE" }); toast("Profile photo removed"); onChanged(); } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <div className="stack">
      {!img ? (
        <div className="row">
          <Avatar user={user} size="lg" />
          <div className="stack" style={{ gap: ".4rem" }}>
            <label className="btn">{user.photo_version ? "Replace photo" : "Upload photo"}<input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(e) => setFile(e.target.files?.[0] || null)} /></label>
            {user.photo_version && <button type="button" className="btn ghost" disabled={busy} onClick={remove}>Remove photo</button>}
            <span className="small muted">JPEG, PNG or WebP, up to 5 MB. Location and camera details are removed. Without a photo your initials are shown.</span>
          </div>
        </div>
      ) : (
        <div className="row" style={{ alignItems: "flex-start", gap: "1.2rem" }}>
          <canvas ref={canvas} width={192} height={192} role="img" aria-label="Cropped photo preview" style={{ borderRadius: "50%", background: "var(--brand-soft)", width: 160, height: 160 }} />
          <div className="stack" style={{ minWidth: 220, flex: 1 }}>
            <div className="field"><label htmlFor="ph-zoom">Zoom</label><input id="ph-zoom" type="range" min={0.3} max={1} step={0.01} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} style={{ direction: "rtl" }} /></div>
            <div className="field"><label htmlFor="ph-x">Horizontal position</label><input id="ph-x" type="range" min={0} max={1} step={0.01} value={px} onChange={(e) => setPx(Number(e.target.value))} /></div>
            <div className="field"><label htmlFor="ph-y">Vertical position</label><input id="ph-y" type="range" min={0} max={1} step={0.01} value={py} onChange={(e) => setPy(Number(e.target.value))} /></div>
            <div className="row">
              <button type="button" className="btn primary" disabled={busy} onClick={save}>Save photo</button>
              <button type="button" className="btn ghost" onClick={() => setFile(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
