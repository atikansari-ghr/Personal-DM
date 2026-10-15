import { useEffect, useRef, useState } from "react";
import { api, formatDateTime } from "../../api";
import LoginArt, { LOGIN_PRESETS } from "../../components/LoginArt";
import { AuthWallpaper, paletteStyle, SIGNIN_THEME, SignInPanelPreview, type Device, type LoginBranding, type Palette } from "../Auth";
import { Confirm, HelpTip, Icon, Modal, Skeleton, useToast } from "../../components/ui";
import { useSession } from "../../session";

/** Settings → Overview & sign-in → Sign-in page design (Change Set W): named designs, protected built-ins, a full
 *  preview before anything goes live, explicit Set as Active, Revert, and automatic rotation. Same card and grid as
 *  before; only the content of the section changed. */

interface Design {
  id: number; name: string; builtin: boolean; builtin_key: string | null; template: string; has_wallpaper: boolean; has_logo: boolean;
  focal_x: number; focal_y: number; overlay: number; color_mode: string; analysis: Record<string, any>; overrides: Palette; palette: Palette;
  warnings: string[]; state: string; state_detail: string; active: boolean; previous: boolean; thumbnail: string | null; preview: LoginBranding; updated_at: string | null;
}
interface Rotation {
  enabled: boolean; mode: "sequential" | "random"; pool: number[]; frequency: string; time: string; weekday: string; month_day: number; timezone: string;
  state: "off" | "on" | "needs_attention"; attention: string; current: { id: number; name: string }; last_rotation: { at: string; design: string } | null;
  next_rotation: string | null; describe: string; pool_detail: { id: number; name: string; valid: boolean; reason: string }[];
}
interface Listing { designs: Design[]; active: number; previous: number | null; rotation: Rotation; limits: { wallpaper_mb: number; logo_mb: number } }

const DEVICES: [Device, string][] = [["desktop", "Desktop"], ["tablet", "Tablet"], ["mobile", "Phone"]];
const MODES: [string, string][] = [["auto", "Auto — Match wallpaper"], ["light", "Light"], ["dark", "Dark"], ["custom", "Custom"]];
const SWATCHES: [keyof Palette, string][] = [["bg", "Panel"], ["ink", "Text"], ["muted", "Secondary text"], ["brand", "Button"], ["brand_ink", "Button text"],
  ["input_bg", "Fields"], ["line", "Borders"], ["link", "Links"]];
const WEEKDAYS: [string, string][] = [["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"], ["fri", "Friday"], ["sat", "Saturday"], ["sun", "Sunday"]];

/** The real sign-in composition for one design at one device size: wallpaper (crop, focal point), logo, panel colours,
 *  fields, primary button, Passkey and SSO buttons. */
export function DesignPreview({ b, device, full }: { b: LoginBranding; device: Device; full?: boolean }) {
  return (
    <div className={`login-preview ${device === "mobile" ? "mobile" : device}${full ? " full" : ""}`} data-theme={SIGNIN_THEME} data-device={device}
      style={paletteStyle(b.palette)} aria-label={`Sign-in preview (${device})`}>
      <AuthWallpaper b={b} preview device={device} />
      <SignInPanelPreview b={b} compact={device === "mobile"} />
    </div>
  );
}

function Thumb({ d }: { d: Design }) {
  return (
    <div className="thumb" data-theme={SIGNIN_THEME} style={paletteStyle(d.palette)}>
      {d.has_wallpaper && d.thumbnail ? <div className="auth-wallpaper" style={{ backgroundImage: `url(${d.thumbnail})`, backgroundPosition: `${d.focal_x * 100}% ${d.focal_y * 100}%` }} />
        : <LoginArt design={d.builtin_key || d.template} />}
    </div>
  );
}

export default function SigninDesigns() {
  const toast = useToast();
  const { refresh } = useSession();
  const [data, setData] = useState<Listing | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [device, setDevice] = useState<Device>("desktop");
  const [full, setFull] = useState(false);
  const [edit, setEdit] = useState<Design | null>(null);
  const [naming, setNaming] = useState<{ title: string; from?: Design; template?: string; rename?: Design } | null>(null);
  const [del, setDel] = useState<Design | null>(null);
  const load = () => api<Listing>("signin-designs").then((r) => { setData(r); setSel((s) => (s && r.designs.some((d) => d.id === s) ? s : r.active)); });
  useEffect(() => { load(); }, []);
  if (!data) return <section className="card"><Skeleton /></section>;
  const d = data.designs.find((x) => x.id === sel) || data.designs.find((x) => x.active)!;
  const run = async (p: Promise<any>, msg: string) => { try { const r = await p; if (r?.designs) setData(r); else await load(); refresh(); toast(msg); } catch (e: any) { toast(e.message, "error"); } };
  return (
    <section className="card stack" id="login-design">
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <h2 style={{ margin: 0 }}>Sign-in page design <HelpTip text="Create as many designs as you like. Exactly one is active; the others are kept for later or for rotation. Built-in designs are protected templates: duplicate one to make it your own." link="/help/login-designs#designs" /></h2>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn small primary" onClick={() => setNaming({ title: "New design", template: "minimal" })}><Icon name="plus" size={16} /> New design</button>
          {data.previous && <button className="btn small" onClick={() => run(api("signin-designs/revert", { method: "POST" }), "Previous design restored")}>Revert to Previous Design</button>}
          <button className="btn small ghost" onClick={() => run(api("signin-designs/reset", { method: "POST" }), "Built-in default design is active")}>Reset to default</button>
        </div>
      </div>
      <p className="small muted">The wallpaper fills the left side of the sign-in page and the sign-in panel stays on the right. Signing in works the same with every design. People see the sign-in page before they sign in, so <strong>do not use private family photos</strong>. A changed design appears the next time the sign-in page is opened; a page that is already open is never interrupted.</p>
      <div className="design-grid" role="group" aria-label="Sign-in designs">
        {data.designs.map((x) => (
          <button key={x.id} type="button" className="design-option" aria-pressed={x.id === d.id} data-design-id={x.id} data-builtin={x.builtin || undefined} onClick={() => setSel(x.id)}>
            <Thumb d={x} />
            <span>{x.name}{x.active && <em className="design-saved">In use</em>}
              {x.builtin && !x.active && <em className="design-tag">Built-in</em>}
              {x.state !== "ok" && <em className="design-tag danger">Needs attention</em>}</span>
          </button>
        ))}
      </div>
      <div className="design-actions row" style={{ gap: 6, flexWrap: "wrap" }} aria-label={`Actions for ${d.name}`}>
        <strong style={{ marginRight: 6 }}>{d.name}</strong>
        {!d.active && <button className="btn small primary" onClick={() => run(api(`signin-designs/${d.id}/activate`, { method: "POST" }), `“${d.name}” is now the sign-in design`)}>Set as Active</button>}
        <button className="btn small" onClick={() => setFull(true)}>Preview Sign-in Page</button>
        <button className="btn small" onClick={() => setNaming({ title: d.builtin ? "Create from template" : "Duplicate design", from: d })}>{d.builtin ? "Create from template" : "Duplicate"}</button>
        {!d.builtin && <button className="btn small" onClick={() => setEdit(d)}>Edit</button>}
        {!d.builtin && <button className="btn small" onClick={() => setNaming({ title: "Rename design", rename: d })}>Rename</button>}
        {!d.builtin && <button className="btn small ghost danger" onClick={() => setDel(d)}>Delete</button>}
        {d.builtin && <span className="small muted">Built-in designs are protected: activate or duplicate them.</span>}
      </div>
      {d.state !== "ok" && <div className="alert warn small" role="status"><strong>Needs attention:</strong> {d.state_detail || "this design cannot be shown."} Replace its wallpaper under Edit.</div>}
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Live sign-in preview{d.active ? "" : " (not active)"}</h3>
        <div className="seg" role="group" aria-label="Preview size">
          {DEVICES.map(([k, l]) => <button key={k} type="button" className={device === k ? "active" : ""} aria-pressed={device === k} onClick={() => setDevice(k)}>{l}</button>)}
        </div>
      </div>
      <DesignPreview b={d.preview} device={device} />
      <p className="small muted">The preview uses the real sign-in components and this design's colours. Nothing goes live until you choose <strong>Set as Active</strong>.</p>
      {full && (
        <Modal title={`Preview: ${d.name}`} onClose={() => setFull(false)} wide>
          <div className="seg" role="group" aria-label="Preview size" style={{ marginBottom: ".6rem" }}>
            {DEVICES.map(([k, l]) => <button key={k} type="button" className={device === k ? "active" : ""} aria-pressed={device === k} onClick={() => setDevice(k)}>{l}</button>)}
          </div>
          <DesignPreview b={d.preview} device={device} full />
          <p className="small muted">{d.active ? "This design is in use." : "Preview only: the sign-in page is not changed."}</p>
        </Modal>
      )}
      {naming && <NameDialog title={naming.title} initial={naming.rename?.name || (naming.from ? `${naming.from.name} (copy)` : "")} withTemplate={!!naming.template}
        onClose={() => setNaming(null)} onSave={async (name, template) => {
          try {
            if (naming.rename) await api(`signin-designs/${naming.rename.id}`, { method: "PATCH", body: { name } });
            else { const r = await api<Design>("signin-designs", { body: { name, template, from: naming.from?.id } }); setSel(r.id); if (naming.template) setEdit(r); }
            setNaming(null); await load(); toast("Saved");
          } catch (e: any) { toast(e.message, "error"); }
        }} />}
      {edit && <DesignEditor design={edit} limits={data.limits} onClose={() => { setEdit(null); load(); refresh(); }} />}
      {del && <Confirm title={`Delete “${del.name}”`} danger confirmLabel="Delete design" message={<div className="stack" style={{ gap: ".4rem" }}>
        {del.active && <p><strong>This design is in use.</strong> The built-in default becomes active first, so the sign-in page is never left without a design.</p>}
        <p>Its wallpaper and logo files are removed from the server unless another saved design uses them.</p></div>}
        onClose={() => setDel(null)} onConfirm={() => { const x = del; setDel(null); run(api(`signin-designs/${x.id}`, { method: "DELETE" }), `“${x.name}” deleted`); }} />}
      <RotationCard designs={data.designs} rotation={data.rotation} onSaved={(r) => setData({ ...data, rotation: r })} />
    </section>
  );
}

function NameDialog({ title, initial, withTemplate, onClose, onSave }: { title: string; initial: string; withTemplate: boolean; onClose: () => void; onSave: (name: string, template: string) => void }) {
  const [name, setName] = useState(initial);
  const [template, setTemplate] = useState("minimal");
  return (
    <Modal title={title} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSave(name, template); }}>
        <div className="field"><label htmlFor="design-name">Name</label><input id="design-name" value={name} maxLength={80} autoFocus onChange={(e) => setName(e.target.value)} /></div>
        {withTemplate && <div className="field"><label htmlFor="design-template">Start from</label>
          <select id="design-template" value={template} onChange={(e) => setTemplate(e.target.value)}>{LOGIN_PRESETS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <span className="hint">The built-in artwork is shown until you add a wallpaper.</span></div>}
        <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!name.trim()}>Save</button></div>
      </form>
    </Modal>
  );
}

/** Editing a custom design: wallpaper (original kept, derivatives made on the server), logo, focal point, overlay and
 *  colours. Saved changes apply to this design only; it goes live only when it is (or becomes) the active design. */
function DesignEditor({ design, limits, onClose }: { design: Design; limits: Listing["limits"]; onClose: () => void }) {
  const toast = useToast();
  const [d, setD] = useState(design);
  const [device, setDevice] = useState<Device>("desktop");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ focal_x: design.focal_x, focal_y: design.focal_y, overlay: design.overlay, color_mode: design.color_mode, overrides: { ...design.overrides } });
  const imgRef = useRef<HTMLDivElement>(null);
  const save = async (extra: Record<string, any> = {}) => {
    setBusy(true);
    try { setD(await api<Design>(`signin-designs/${d.id}`, { method: "PATCH", body: { ...draft, ...extra } })); toast("Design saved"); }
    catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  };
  const upload = async (kind: "wallpaper" | "logo", f: File | null) => {
    setBusy(true);
    try {
      const r = f ? await api<Design>(`signin-designs/${d.id}/${kind}`, { form: (() => { const fd = new FormData(); fd.append("file", f); return fd; })() })
        : await api<Design>(`signin-designs/${d.id}/${kind}`, { method: "DELETE" });
      setD(r); setDraft((x) => ({ ...x, focal_x: r.focal_x, focal_y: r.focal_y })); toast(f ? (kind === "wallpaper" ? "Wallpaper processed for Desktop, Tablet and Phone" : "Logo saved") : "Removed");
    } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  };
  const pickFocal = (e: React.MouseEvent) => {
    const r = imgRef.current!.getBoundingClientRect();
    setDraft((x) => ({ ...x, focal_x: Math.round(((e.clientX - r.left) / r.width) * 100) / 100, focal_y: Math.round(((e.clientY - r.top) / r.height) * 100) / 100 }));
  };
  const shown: LoginBranding = { ...d.preview, overlay: draft.overlay, focal: [draft.focal_x, draft.focal_y],
    palette: draft.color_mode === "custom" ? { ...d.palette, ...draft.overrides } : d.palette };
  const original = d.has_wallpaper ? `/api/branding/design/${d.id}/original?v=${(d.updated_at || "").slice(-8)}` : null;
  return (
    <Modal title={`Edit “${d.name}”`} onClose={onClose} wide>
      <div className="stack">
        {d.active && <div className="alert info small" role="status">This design is in use: saved changes appear the next time the sign-in page is opened.</div>}
        <div className="design-editor">
          <div className="stack">
            <h3>Wallpaper</h3>
            {original ? (
              <div ref={imgRef} className="focal-picker" role="button" tabIndex={0} aria-label="Click the part of the wallpaper that must stay visible" onClick={pickFocal}
                style={{ backgroundImage: `url(${original})` }}>
                <span className="focal-dot" style={{ left: `${draft.focal_x * 100}%`, top: `${draft.focal_y * 100}%` }} aria-hidden="true" />
              </div>
            ) : <p className="small muted">No wallpaper yet: the {design.template} artwork is shown.</p>}
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              <label className="btn small"><Icon name="upload" size={16} /> {d.has_wallpaper ? "Replace wallpaper…" : "Upload wallpaper…"}
                <input type="file" accept="image/jpeg,image/png,image/webp" hidden disabled={busy} onChange={(e) => { upload("wallpaper", e.target.files?.[0] || null); e.target.value = ""; }} /></label>
              {d.has_wallpaper && <button className="btn small ghost" disabled={busy} onClick={() => upload("wallpaper", null)}>Remove wallpaper</button>}
              <label className="btn small"><Icon name="upload" size={16} /> {d.has_logo ? "Replace logo…" : "Upload logo…"}
                <input type="file" accept="image/jpeg,image/png,image/webp" hidden disabled={busy} onChange={(e) => { upload("logo", e.target.files?.[0] || null); e.target.value = ""; }} /></label>
              {d.has_logo && <button className="btn small ghost" disabled={busy} onClick={() => upload("logo", null)}>Remove logo</button>}
            </div>
            <p className="small muted">JPEG, PNG or WebP, at least 800 × 500 pixels, up to {limits.wallpaper_mb} MB (logo {limits.logo_mb} MB). The original is kept; Desktop, Tablet and Phone versions are cropped around the focal point, never stretched. Location data in the photo is removed.</p>
            {d.has_wallpaper && <div className="form-grid">
              <div className="field"><label htmlFor="fx">Focal point — across ({Math.round(draft.focal_x * 100)} %)</label><input id="fx" type="range" min={0} max={1} step={0.01} value={draft.focal_x} onChange={(e) => setDraft({ ...draft, focal_x: Number(e.target.value) })} /></div>
              <div className="field"><label htmlFor="fy">Focal point — down ({Math.round(draft.focal_y * 100)} %)</label><input id="fy" type="range" min={0} max={1} step={0.01} value={draft.focal_y} onChange={(e) => setDraft({ ...draft, focal_y: Number(e.target.value) })} /></div>
            </div>}
            <div className="field"><label htmlFor="ov">Wallpaper overlay ({draft.overlay} %)</label><input id="ov" type="range" min={0} max={80} step={5} value={draft.overlay} onChange={(e) => setDraft({ ...draft, overlay: Number(e.target.value) })} /></div>
            <h3>Colours <HelpTip text="Auto picks readable panel, text and button colours from the part of the wallpaper next to the sign-in panel. Readability always wins over an exact colour match." link="/help/login-designs#colours" /></h3>
            <div className="field"><label htmlFor="cm">Colour mode</label>
              <select id="cm" value={draft.color_mode} onChange={(e) => setDraft({ ...draft, color_mode: e.target.value })}>{MODES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
            {Object.keys(d.palette || {}).length > 0 ? (
              <div className="palette-grid" aria-label="Palette">
                {SWATCHES.map(([k, label]) => (
                  <label key={k} className="swatch">
                    <input type="color" disabled={draft.color_mode !== "custom"} value={(draft.overrides as any)[k] || (d.palette as any)[k] || "#ffffff"} aria-label={label}
                      onChange={(e) => setDraft({ ...draft, overrides: { ...draft.overrides, [k]: e.target.value } })} />
                    <span className="small">{label}</span>
                  </label>
                ))}
              </div>
            ) : <p className="small muted">Built-in colours are used until a wallpaper is added.</p>}
            {draft.color_mode === "custom" && <p className="small muted">Custom: your colours are kept when the wallpaper is replaced.</p>}
            {d.warnings.map((w) => <div key={w} className="alert warn small">{w}</div>)}
            <div className="row" style={{ justifyContent: "flex-end", gap: 6 }}><button className="btn" onClick={onClose}>Close</button><button className="btn primary" disabled={busy} onClick={() => save()}>Save design</button></div>
          </div>
          <div className="stack">
            <div className="seg" role="group" aria-label="Preview size">
              {DEVICES.map(([k, l]) => <button key={k} type="button" className={device === k ? "active" : ""} aria-pressed={device === k} onClick={() => setDevice(k)}>{l}</button>)}
            </div>
            <DesignPreview b={shown} device={device} />
            <p className="small muted">Preview of unsaved focal point, overlay and colours. Save to keep them.</p>
          </div>
        </div>
      </div>
    </Modal>
  );
}

/** Automatic design rotation: a pool of at least two valid designs, Sequential (drag to order) or Random, on a
 *  daily, weekly or monthly schedule in the installation timezone. */
function RotationCard({ designs, rotation, onSaved }: { designs: Design[]; rotation: Rotation; onSaved: (r: Rotation) => void }) {
  const toast = useToast();
  const [r, setR] = useState(rotation);
  const [dragging, setDragging] = useState<number | null>(null);
  const [preview, setPreview] = useState<any>(null);
  useEffect(() => setR(rotation), [rotation]);
  const name = (id: number) => designs.find((d) => d.id === id)?.name || `#${id} (deleted)`;
  const toggle = (id: number) => setR({ ...r, pool: r.pool.includes(id) ? r.pool.filter((x) => x !== id) : [...r.pool, id] });
  const move = (i: number, j: number) => { if (j < 0 || j >= r.pool.length) return; const p = [...r.pool]; const [x] = p.splice(i, 1); p.splice(j, 0, x); setR({ ...r, pool: p }); };
  const save = () => api<Rotation>("signin-designs/rotation", { method: "PUT", body: r }).then((x) => { onSaved(x); setR(x); toast("Rotation saved"); }).catch((e) => toast(e.message, "error"));
  const badge = { on: ["ok", "On"], off: ["neutral", "Off"], needs_attention: ["warn", "Rotation Needs Attention"] }[rotation.state] || ["neutral", rotation.state];
  return (
    <div className="stack rotation-card" id="design-rotation" style={{ borderTop: "1px solid var(--line)", paddingTop: "1rem" }}>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Automatic Design Rotation <span className={`badge ${badge[0]}`} data-rotation-state={rotation.state}>{badge[1]}</span></h3>
        <button className="btn small" onClick={() => api("signin-designs/rotation/preview").then(setPreview)}>Preview Rotation</button>
      </div>
      {rotation.attention && <div className="alert warn small" role="status">{rotation.attention}</div>}
      <dl className="dest-facts small">
        <dt>Rotation Status</dt><dd>{badge[1]}</dd>
        <dt>Rotation Mode</dt><dd>{rotation.mode === "random" ? "Random" : "Sequential"}</dd>
        <dt>Current Design</dt><dd>{rotation.current.name}</dd>
        <dt>Last Rotation</dt><dd>{rotation.last_rotation ? `${formatDateTime(rotation.last_rotation.at)} · ${rotation.last_rotation.design}` : "Not yet"}</dd>
        <dt>Next Rotation</dt><dd>{rotation.next_rotation ? formatDateTime(rotation.next_rotation) : "—"}</dd>
        <dt>Timezone</dt><dd>{rotation.timezone} (installation)</dd>
      </dl>
      <label className="check"><input type="checkbox" checked={r.enabled} onChange={(e) => setR({ ...r, enabled: e.target.checked })} /> Rotate the sign-in design automatically</label>
      <div className="form-grid">
        <div className="field"><label htmlFor="rot-mode">Mode</label><select id="rot-mode" value={r.mode} onChange={(e) => setR({ ...r, mode: e.target.value as Rotation["mode"] })}><option value="sequential">Sequential — in the order below</option><option value="random">Random</option></select></div>
        <div className="field"><label htmlFor="rot-freq">Frequency</label><select id="rot-freq" value={r.frequency} onChange={(e) => setR({ ...r, frequency: e.target.value })}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></div>
        {r.frequency === "weekly" && <div className="field"><label htmlFor="rot-wd">Weekday</label><select id="rot-wd" value={r.weekday} onChange={(e) => setR({ ...r, weekday: e.target.value })}>{WEEKDAYS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>}
        {r.frequency === "monthly" && <div className="field"><label htmlFor="rot-md">Day of the month</label><input id="rot-md" type="number" min={1} max={31} value={r.month_day} onChange={(e) => setR({ ...r, month_day: Number(e.target.value) })} />
          {r.month_day > 28 && <span className="hint">In shorter months it runs on the last day of the month.</span>}</div>}
        <div className="field"><label htmlFor="rot-time">Time ({rotation.timezone})</label><input id="rot-time" type="time" value={r.time} onChange={(e) => setR({ ...r, time: e.target.value })} /></div>
      </div>
      <div className="field"><span className="label-like">Rotation pool (at least 2 valid designs{r.mode === "sequential" ? "; drag to set the order" : ""})</span>
        <ol className="plain rotation-pool" aria-label="Rotation pool">
          {r.pool.map((id, i) => {
            const det = rotation.pool_detail.find((p) => p.id === id);
            return (
              <li key={id} draggable onDragStart={() => setDragging(i)} onDragOver={(e) => e.preventDefault()} onDrop={() => { if (dragging !== null) move(dragging, i); setDragging(null); }}
                className="row" data-pool-id={id} style={{ gap: 6 }}>
                <span aria-hidden="true" className="drag-handle">⋮⋮</span><span>{i + 1}. {name(id)}</span>
                {det && !det.valid && <span className="badge danger">Unavailable — skipped</span>}
                <button type="button" className="icon-btn" aria-label={`Move ${name(id)} up`} onClick={() => move(i, i - 1)}><Icon name="up" size={16} /></button>
                <button type="button" className="icon-btn" aria-label={`Move ${name(id)} down`} onClick={() => move(i, i + 1)}><Icon name="down" size={16} /></button>
                <button type="button" className="btn small ghost" onClick={() => toggle(id)}>Remove</button>
              </li>
            );
          })}
        </ol>
        <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
          {designs.filter((d) => !r.pool.includes(d.id)).map((d) => <button key={d.id} type="button" className="btn small" onClick={() => toggle(d.id)}><Icon name="plus" size={14} /> {d.name}</button>)}
        </div>
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn primary" onClick={save}>Save rotation</button></div>
      <p className="small muted">Choosing Set as Active by hand does not turn rotation off; the next scheduled rotation continues as usual. After the server was off, missed rotations are not replayed: the right design is worked out once. Routine rotations are recorded in the activity log only; you are notified only when something needs attention.</p>
      {preview && <RotationPreview data={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

function RotationPreview({ data, onClose }: { data: any; onClose: () => void }) {
  const [device, setDevice] = useState<Device>("desktop");
  const [i, setI] = useState(0);
  const order: LoginBranding[] = data.order || [];
  const cur = order[i];
  return (
    <Modal title="Preview Rotation" onClose={onClose} wide>
      <div className="stack">
        <p className="small">{data.status.describe} · {data.status.timezone} · Next Rotation: {data.status.next_rotation ? formatDateTime(data.status.next_rotation) : "—"}. Nothing changes until the scheduled moment.</p>
        {data.random_note && <div className="alert info small">{data.random_note}</div>}
        {data.invalid.map((x: any) => <div key={x.id} className="alert warn small">{x.name}: unavailable ({x.reason}); it will be skipped.</div>)}
        {data.previous && data.next && <p className="small">Sequential: previous <strong>{data.previous.design_name}</strong> · next <strong>{data.next.design_name}</strong>.</p>}
        {order.length > 0 ? (
          <>
            <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
              <div className="row" style={{ gap: 6 }}>
                <button className="btn small" onClick={() => setI((i - 1 + order.length) % order.length)}>Previous</button>
                <strong>{i + 1} / {order.length}: {cur.design_name}</strong>
                <button className="btn small" onClick={() => setI((i + 1) % order.length)}>Next</button>
              </div>
              <div className="seg" role="group" aria-label="Preview size">{DEVICES.map(([k, l]) => <button key={k} type="button" className={device === k ? "active" : ""} aria-pressed={device === k} onClick={() => setDevice(k)}>{l}</button>)}</div>
            </div>
            <DesignPreview b={cur} device={device} full />
          </>
        ) : <p className="muted">The pool has no valid design.</p>}
      </div>
    </Modal>
  );
}
