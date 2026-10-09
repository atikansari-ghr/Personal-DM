import { useState } from "react";
import { api } from "../api";
import { applyThemeAttr, useSession } from "../session";
import { Icon, useToast } from "./ui";

export const THEMES: { id: string; name: string; desc: string }[] = [
  { id: "green", name: "Default Green", desc: "Clean and fresh. The default." },
  { id: "blue", name: "Blue", desc: "Calm and professional." },
  { id: "dark", name: "Dark", desc: "Modern and easy on the eyes at night." },
  { id: "glass_light", name: "Glass Light", desc: "Translucent panels over a soft gradient." },
  { id: "glass_dark", name: "Glass Dark", desc: "Translucent dark panels with depth." },
  { id: "mono", name: "Black & White", desc: "Monochrome, maximum contrast." },
];

/** Theme presets with live previews (each preview renders under its own data-theme with sample, synthetic data). */
export default function ThemeGallery() {
  const { session, refresh } = useSession();
  const toast = useToast();
  const [current, setCurrent] = useState(session?.preferences?.theme || "green");
  const choose = async (id: string) => {
    const prev = current;
    setCurrent(id);
    applyThemeAttr(id);
    try {
      await api("settings", { method: "PUT", body: { values: { "me.theme": id } } });
      toast(`Theme: ${THEMES.find((t) => t.id === id)?.name}. Applies on all your devices.`);
      window.dispatchEvent(new Event("pd:settings-saved"));
      refresh().catch(() => undefined);
    } catch (e: any) {
      setCurrent(prev);
      applyThemeAttr(prev);
      toast(e.message, "error");
    }
  };
  return (
    <section className="card">
      <div className="row between"><h2 style={{ margin: 0 }}>Theme</h2>
        <button type="button" className="btn small" disabled={current === "green"} onClick={() => choose("green")}><Icon name="refresh" size={16} /> Reset to default</button></div>
      <p className="small muted">Your theme follows your account on every device. Other family members choose their own. Themes change colours and surfaces only; badges, warnings and permissions mean the same in every theme.</p>
      <div className="theme-grid" role="radiogroup" aria-label="Theme">
        {THEMES.map((t) => (
          <button key={t.id} type="button" role="radio" aria-checked={current === t.id} className="theme-card" onClick={() => choose(t.id)} data-theme-option={t.id}>
            <div className="theme-preview" data-theme={t.id} aria-hidden="true">
              <div className="tp-nav"><b><img src="/icon.svg" alt="" width={12} height={12} /> Personal DM</b><span className="on">Overview</span><span>Folders</span><span>Offline</span></div>
              <div className="tp-main">
                <div className="tp-card"><div className="tp-row"><i /><em>Sample passport.pdf</em><span className="tp-badge">✓ Valid</span></div>
                  <div className="tp-muted">PDF · 1.2 MB · v2</div></div>
                <div className="tp-card"><div className="tp-row"><em>Expiring soon</em></div><span className="tp-btn">Open</span></div>
              </div>
            </div>
            <span className="theme-name">{t.name}{current === t.id && <span className="badge ok"><Icon name="check" size={12} /> Current</span>}</span>
            <span className="theme-desc">{t.desc}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
