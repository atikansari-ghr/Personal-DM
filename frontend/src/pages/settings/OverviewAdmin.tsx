import { useEffect, useState } from "react";
import { api, formatDate } from "../../api";
import SettingsForm from "../../components/SettingsForm";
import { CityDialog } from "../../components/OverviewWidgets";
import LoginArt, { LOGIN_PRESETS } from "../../components/LoginArt";
import { AuthWallpaper, DEFAULT_BRANDING, type LoginBranding } from "../Auth";
import { Confirm, Icon, Modal, Skeleton, useAsync, useToast } from "../../components/ui";
import { useSession } from "../../session";

/** Settings → Overview & sign-in: holiday countries and corrections, weather provider, sign-in page design. */

interface Override { id: number; country: string; country_name: string; flag: string; date: string; name: string; status: string; hidden: boolean; source: string }

function WeatherTools() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const [city, setCity] = useState<any>(undefined);
  const { data: settings } = useAsync(() => api<{ settings: any[] }>("settings"), []);
  const current = city !== undefined ? city : settings?.settings.find((s) => s.key === "weather.default_city")?.value;
  return (
    <div className="row" style={{ marginTop: ".6rem" }}>
      <button className="btn small" disabled={busy} onClick={async () => {
        setBusy(true);
        try { const r = await api<any>("overview/weather/test", { method: "POST" }); toast(`Weather service answered: ${r.city} ${Math.round(r.temperature)}${r.unit} (${r.ms} ms)`); }
        catch (e: any) { toast(e.message, "error"); }
        finally { setBusy(false); }
      }}><Icon name="refresh" size={16} /> Test connection</button>
      <button className="btn small" onClick={() => setPicking(true)}><Icon name="pin" size={16} /> Default city: {current?.name || "not set"}</button>
      {current && <button className="btn small ghost" onClick={async () => { await api("overview/weather/default-city", { method: "PUT", body: { city: null } }); setCity(null); }}>Clear default city</button>}
      <span className="small muted">Save the settings above first; the test uses the saved provider address and key.</span>
      {picking && <CityDialog endpoint="overview/weather/default-city" onClose={() => setPicking(false)} onChosen={(r) => { setCity(r.city); setPicking(false); toast("Default city saved"); }} />}
    </div>
  );
}

function OverrideDialog({ o, countries, onClose, onSaved }: { o: Partial<Override>; countries: { code: string; name: string; flag: string }[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<Partial<Override>>({ status: "confirmed", hidden: false, ...o });
  const [err, setErr] = useState("");
  return (
    <Modal title={o.id ? "Edit holiday correction" : "Add holiday correction"} onClose={onClose}>
      <form className="stack" onSubmit={async (e) => {
        e.preventDefault();
        try { await api(o.id ? `overview/holiday-overrides/${o.id}` : "overview/holiday-overrides", { method: o.id ? "PATCH" : "POST", body: f }); onSaved(); }
        catch (x: any) { setErr(x.message); }
      }}>
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="field"><label htmlFor="ho-c">Country</label>
          <select id="ho-c" value={f.country || ""} onChange={(e) => setF({ ...f, country: e.target.value })} required>
            <option value="">Choose…</option>{countries.map((c) => <option key={c.code} value={c.code}>{c.flag} {c.name}</option>)}
          </select></div>
        <div className="field"><label htmlFor="ho-d">Date</label><input id="ho-d" type="date" value={f.date || ""} onChange={(e) => setF({ ...f, date: e.target.value })} required style={{ maxWidth: 200 }} /></div>
        <label className="check"><input type="checkbox" checked={!!f.hidden} onChange={(e) => setF({ ...f, hidden: e.target.checked })} /> Hide the library's holiday on this date (for example when the official date moved)</label>
        {!f.hidden && <>
          <div className="field"><label htmlFor="ho-n">Holiday name</label><input id="ho-n" value={f.name || ""} onChange={(e) => setF({ ...f, name: e.target.value })} maxLength={120} /></div>
          <div className="field"><label htmlFor="ho-s">Status</label>
            <select id="ho-s" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} style={{ maxWidth: 240 }}>
              <option value="confirmed">Confirmed (officially announced)</option><option value="provisional">Provisional (expected)</option>
            </select></div>
        </>}
        <div className="field"><label htmlFor="ho-src">Source</label><input id="ho-src" value={f.source || ""} onChange={(e) => setF({ ...f, source: e.target.value })} placeholder="e.g. official announcement, 2026-03-18" maxLength={200} /></div>
        <div className="row" style={{ justifyContent: "flex-end" }}><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary">Save correction</button></div>
      </form>
    </Modal>
  );
}

function HolidayCorrections() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<{ overrides: Override[] }>("overview/holiday-overrides"), []);
  const { data: c } = useAsync(() => api<{ countries: { code: string; name: string; flag: string }[]; selected: string[] }>("overview/countries"), []);
  const [edit, setEdit] = useState<Partial<Override> | null>(null);
  const [del, setDel] = useState<Override | null>(null);
  const { data: upcoming } = useAsync(() => api<{ holidays: any[] }>("overview/holidays", { query: { count: 10 } }), [data]);
  if (!data || !c) return <Skeleton />;
  const ordered = [...c.countries.filter((x) => c.selected.includes(x.code)), ...c.countries.filter((x) => !c.selected.includes(x.code))];
  return (
    <section className="card">
      <h2>Holiday corrections</h2>
      <p className="small muted">Holidays come from the bundled holidays library. Islamic holidays are calculated in advance and shown as <span className="badge soon">Provisional</span> until you confirm the announced date here. Corrections never change the library itself.</p>
      {upcoming && upcoming.holidays.length > 0 && (
        <table className="responsive" style={{ marginBottom: ".8rem" }}>
          <thead><tr><th>Upcoming</th><th>Country</th><th>Status</th><th /></tr></thead>
          <tbody>{upcoming.holidays.map((h: any, i: number) => (
            <tr key={i}><td>{h.name}<div className="small muted">{formatDate(h.date)}{h.end && h.end !== h.date ? ` – ${formatDate(h.end)}` : ""}</div></td><td>{h.flag} {h.country_name}</td>
              <td><span className={`badge ${h.status === "provisional" ? "soon" : "ok"}`}>{h.status === "provisional" ? "Provisional" : "Confirmed"}</span><div className="small muted">{h.source}</div></td>
              <td>{!h.override && <button className="btn small ghost" onClick={() => setEdit({ country: h.country, date: h.date, name: h.name, status: "confirmed" })}>Confirm or correct…</button>}</td></tr>
          ))}</tbody>
        </table>
      )}
      {data.overrides.length > 0 && (
        <table className="responsive">
          <thead><tr><th>Date</th><th>Country</th><th>Correction</th><th>Source</th><th /></tr></thead>
          <tbody>{data.overrides.map((o) => (
            <tr key={o.id}><td>{formatDate(o.date)}</td><td>{o.flag} {o.country_name}</td><td>{o.hidden ? <em>Hidden</em> : <>{o.name} <span className={`badge ${o.status === "provisional" ? "soon" : "ok"}`}>{o.status}</span></>}</td><td className="small">{o.source}</td>
              <td className="row"><button className="btn small ghost" onClick={() => setEdit(o)}>Edit</button><button className="btn small ghost danger" onClick={() => setDel(o)}>Delete</button></td></tr>
          ))}</tbody>
        </table>
      )}
      <div className="row" style={{ marginTop: ".6rem" }}><button className="btn small" onClick={() => setEdit({})}><Icon name="plus" size={16} /> Add correction</button></div>
      {edit && <OverrideDialog o={edit} countries={ordered} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); toast("Correction saved"); }} />}
      {del && <Confirm title="Delete correction" danger confirmLabel="Delete" message={<p>The library's holiday data applies again for {del.country_name} on {formatDate(del.date)}.</p>}
        onClose={() => setDel(null)} onConfirm={async () => { await api(`overview/holiday-overrides/${del.id}`, { method: "DELETE" }); setDel(null); reload(); }} />}
    </section>
  );
}

function LoginDesign() {
  const toast = useToast();
  const { refresh } = useSession();
  const [b, setB] = useState<LoginBranding | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [removing, setRemoving] = useState(false);
  const load = () => api<LoginBranding>("branding").then(setB);
  useEffect(() => { load(); const h = () => load(); window.addEventListener("pd:settings-saved", h); return () => window.removeEventListener("pd:settings-saved", h); }, []);
  if (!b) return <Skeleton />;
  const choose = async (design: string) => {
    try { await api("settings", { method: "PUT", body: { values: { "login.design": design } } }); await load(); refresh(); toast("Sign-in design saved"); }
    catch (e: any) { toast(e.message, "error"); }
  };
  const upload = async (kind: "wallpaper" | "logo", f: File) => {
    const form = new FormData();
    form.append("file", f);
    try { setB(await api<LoginBranding>(`branding/${kind}`, { form })); refresh(); setPreview(null); setFile(null); toast(kind === "logo" ? "Logo saved" : "Custom wallpaper saved and selected"); }
    catch (e: any) { toast(e.message, "error"); }
  };
  const shown: LoginBranding = preview ? { ...b, design: "custom", wallpaper: preview } : b;
  return (
    <section className="card stack">
      <h2>Sign-in page design</h2>
      <p className="small muted">The wallpaper fills the left side of the sign-in page and the sign-in panel stays on the right. Signing in works the same with every design. People see the sign-in page before they sign in, so <strong>do not use private family photos</strong>.</p>
      <div className="design-grid" role="group" aria-label="Sign-in designs">
        {LOGIN_PRESETS.map(([k, label]) => (
          <button key={k} type="button" className="design-option" aria-pressed={b.design === k} onClick={() => choose(k)}>
            <div className="thumb"><LoginArt design={k} /></div><span>{label}{k === "minimal" ? " (default)" : ""}</span>
          </button>
        ))}
        {b.has_wallpaper && (
          <button type="button" className="design-option" aria-pressed={b.design === "custom"} onClick={() => choose("custom")}>
            <div className="thumb"><div className="auth-wallpaper" style={{ backgroundImage: `url(/api/branding/wallpaper?t=${Date.now() >> 16})` }} /></div><span>Custom wallpaper</span>
          </button>
        )}
      </div>
      <div className="row">
        <label className="btn small"><Icon name="upload" size={16} /> {b.has_wallpaper ? "Replace custom wallpaper…" : "Upload custom wallpaper…"}
          <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFile(f); setPreview(URL.createObjectURL(f)); } e.target.value = ""; }} /></label>
        {b.has_wallpaper && <button className="btn small ghost danger" onClick={() => setRemoving(true)}>Remove custom wallpaper</button>}
        <label className="btn small"><Icon name="upload" size={16} /> {b.logo ? "Replace logo…" : "Upload logo…"}
          <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload("logo", f); e.target.value = ""; }} /></label>
        {b.logo && <button className="btn small ghost" onClick={async () => { setB(await api<LoginBranding>("branding/logo", { method: "DELETE" })); refresh(); }}>Remove logo</button>}
        <button className="btn small ghost" onClick={async () => {
          await api("settings", { method: "PUT", body: { values: { "login.design": "minimal", "login.title": DEFAULT_BRANDING.title, "login.tagline": DEFAULT_BRANDING.tagline, "login.overlay": 0, "login.position": "center" } } });
          await load(); refresh(); window.dispatchEvent(new Event("pd:settings-saved")); toast("Sign-in page reset to the default design");
        }}>Reset to default</button>
      </div>
      <p className="small muted">Wallpaper: JPEG, PNG or WebP, at least 800 × 500 pixels, up to 10 MB. It is re-encoded on the server without its metadata (such as location) and stored only on this server. Logo: up to 2 MB.</p>
      {preview && (
        <div className="alert">
          <strong>Preview of the new wallpaper.</strong> Adjust the position and overlay below after saving.
          <div className="row" style={{ marginTop: ".4rem" }}><button className="btn small primary" onClick={() => file && upload("wallpaper", file)}>Use this wallpaper</button><button className="btn small" onClick={() => { setPreview(null); setFile(null); }}>Cancel</button></div>
        </div>
      )}
      <div className="login-preview" aria-label="Preview">
        <AuthWallpaper b={shown} preview />
        <div className="fake-form" aria-hidden="true"><strong>Sign in</strong><div /><div /><div className="btnlike" /></div>
      </div>
      {removing && <Confirm title="Remove custom wallpaper" danger confirmLabel="Remove" message={<p>The wallpaper file is deleted from the server. If it is in use, the sign-in page returns to the Minimal design.</p>}
        onClose={() => setRemoving(false)} onConfirm={async () => { setB(await api<LoginBranding>("branding/wallpaper", { method: "DELETE" })); setRemoving(false); refresh(); }} />}
    </section>
  );
}

export default function OverviewAdminPanel() {
  return (
    <div className="stack">
      <SettingsForm section="overview" title="Overview widgets">
        <WeatherTools />
      </SettingsForm>
      <HolidayCorrections />
      <LoginDesign />
      <SettingsForm keys={["login.title", "login.tagline", "login.overlay", "login.position"]} title="Sign-in page text and wallpaper" />
    </div>
  );
}
