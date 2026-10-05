import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { HelpTip, Icon, Skeleton, useToast } from "./ui";
import WidgetListEditor from "./WidgetListEditor";

export interface SettingDef {
  key: string; label: string; description: string; type: string; default: any; section: string; scope: string; editable_by: string;
  choices: string[]; min: number | null; max: number | null; depends_on: string[]; effect: string; restart: boolean; help: string;
  example: string; secret: boolean; value: any; configured: boolean | null; can_edit: boolean; choice_labels?: Record<string, string>;
}

const CHANNEL_LABELS: Record<string, string> = { in_app: "In-app", email: "Email", telegram: "Telegram" };
const CHOICE_LABELS: Record<string, string> = { green: "Green & White", blue: "Blue & White", mono: "Black & White", three_panel: "Three-panel view", full_page: "Full-page viewer", planned: "Planned (not available)", unavailable: "Unavailable in this release", starttls: "STARTTLS", ssl: "SSL/TLS", none: "None (not recommended)", nfs: "NFS", smb: "SMB / Windows share" };
const KEY_CHOICE_LABELS: Record<string, Record<string, string>> = {
  "nas.type": { none: "Already mounted (Proxmox bind mount)" },
  "backup.frequency": { daily: "Daily", weekly: "Weekly", monthly: "Monthly" },
  "backup.weekday": { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" },
};
// Fields that only make sense for a particular value of another field (hidden otherwise, values kept).
const SHOW_IF: Record<string, [string, any[]]> = {
  "backup.weekday": ["backup.frequency", ["weekly"]],
  "backup.month_day": ["backup.frequency", ["monthly"]],
};

export function helpHref(help: string) {
  const [slug, anchor] = help.split("#");
  return `/help/${slug}${anchor ? `#${anchor}` : ""}`;
}

function Input({ def, value, onChange }: { def: SettingDef; value: any; onChange: (v: any) => void }) {
  const id = `s-${def.key}`;
  const disabled = !def.can_edit;
  switch (def.type) {
    case "bool":
      return <label className="switch"><input id={id} type="checkbox" checked={!!value} disabled={disabled} onChange={(e) => onChange(e.target.checked)} aria-label={def.label} /><span /></label>;
    case "choice":
      return <select id={id} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)}>{def.choices.map((c) => <option key={c} value={c}>{KEY_CHOICE_LABELS[def.key]?.[c] || CHOICE_LABELS[c] || c}</option>)}</select>;
    case "int":
      return <input id={id} type="number" min={def.min ?? undefined} max={def.max ?? undefined} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} style={{ maxWidth: 160 }} />;
    case "time":
      return <input id={id} type="time" value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} style={{ maxWidth: 160 }} />;
    case "secret":
      return (
        <div>
          <input id={id} type="password" autoComplete="new-password" placeholder={def.configured ? "•••••••• (stored — leave empty to keep)" : "Not set"} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
          {def.configured && def.can_edit && <button type="button" className="btn small ghost" onClick={() => onChange({ clear: true })}>Clear stored value</button>}
        </div>
      );
    case "int_list": {
      const opts = [90, 60, 30, 14, 7, 1, 0];
      const cur: number[] = Array.isArray(value) ? value : [];
      return (
        <div>
          <div className="row">{opts.map((d) => <label key={d} className="check"><input type="checkbox" disabled={disabled} checked={cur.includes(d)} onChange={(e) => onChange(e.target.checked ? [...cur, d] : cur.filter((x) => x !== d))} /> {d === 0 ? "On expiry" : `${d} days`}</label>)}</div>
          <input type="text" aria-label={`${def.label} (custom list)`} disabled={disabled} value={cur.join(", ")} onChange={(e) => onChange(e.target.value.split(/[ ,]+/).filter(Boolean).map(Number))} style={{ marginTop: ".4rem", maxWidth: 260 }} />
        </div>
      );
    }
    case "channel_list": {
      const cur: string[] = Array.isArray(value) ? value : [];
      return <div className="row">{Object.entries(CHANNEL_LABELS).map(([k, l]) => <label key={k} className="check"><input type="checkbox" disabled={disabled} checked={cur.includes(k)} onChange={(e) => onChange(e.target.checked ? [...cur, k] : cur.filter((x) => x !== k))} /> {l}</label>)}</div>;
    }
    case "event_list": {
      const cur: string[] = Array.isArray(value) ? value : [];
      const labels = def.choice_labels || {};
      return (
        <fieldset className="event-list" aria-label={def.label} disabled={disabled}>
          {def.choices.map((k) => <label key={k} className="check"><input type="checkbox" checked={cur.includes(k)} onChange={(e) => onChange(e.target.checked ? [...cur, k] : cur.filter((x) => x !== k))} /> {labels[k] || k}</label>)}
        </fieldset>
      );
    }
    case "widget_list":
      return <WidgetListEditor value={Array.isArray(value) ? value : []} choices={def.choices} labels={def.choice_labels || {}} disabled={disabled} onChange={onChange} />;
    default:
      return def.key === "documents.import_roots" || def.key === "documents.member_template"
        ? <textarea id={id} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} placeholder={def.example} rows={def.key === "documents.member_template" ? 8 : 3} />
        : <input id={id} type={def.type === "email" ? "email" : "text"} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} placeholder={def.example} />;
  }
}

export default function SettingsForm({ section, keys, title, children }: { section?: string; keys?: string[]; title?: string; children?: React.ReactNode }) {
  const toast = useToast();
  const [defs, setDefs] = useState<SettingDef[] | null>(null);
  const [draft, setDraft] = useState<Record<string, any>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const load = () => api<{ settings: SettingDef[] }>("settings").then((r) => {
    setDefs(r.settings.filter((s) => (keys ? keys.includes(s.key) : s.section === section)));
    setDraft({});
    setErrors({});
  });
  useEffect(() => { load(); }, [section, keys?.join()]);
  if (!defs) return <Skeleton />;
  if (!defs.length) return null;
  const dirty = Object.keys(draft).length > 0;
  const save = async () => {
    const values = Object.fromEntries(Object.entries(draft).filter(([k, v]) => !(defs.find((d) => d.key === k)?.secret && v === "")));
    try {
      await api("settings", { method: "PUT", body: { values } });
      toast("Settings saved");
      if (values["me.theme"]) document.documentElement.dataset.theme = values["me.theme"];
      if (values["me.theme"]) try { localStorage.setItem("pd-theme", values["me.theme"]); } catch { /* ignore */ }
      load();
      window.dispatchEvent(new Event("pd:settings-saved"));
    } catch (e: any) {
      setErrors(e.data?.fields || {});
      toast(e.message, "error");
    }
  };
  return (
    <section className="card">
      {title && <h2>{title}</h2>}
      {defs.map((d) => {
        const cond = SHOW_IF[d.key];
        if (cond) {
          const other = defs.find((x) => x.key === cond[0]);
          const current = cond[0] in draft ? draft[cond[0]] : other?.value;
          if (other && !cond[1].includes(current)) return null;
        }
        const value = d.key in draft ? draft[d.key] : d.secret ? "" : d.value;
        return (
          <div className="setting-row" key={d.key}>
            <div>
              <label htmlFor={`s-${d.key}`} style={{ display: "inline" }}>{d.label}</label>
              <HelpTip text={`${d.description}${d.example ? ` Example: ${d.example}.` : ""}`} link={helpHref(d.help)} />
              <p className="small muted" style={{ margin: ".2rem 0 0" }}>{d.description}</p>
              <div className="setting-meta">
                {d.effect && <span>{d.effect} </span>}
                {d.restart && <span className="badge neutral">Worker restart needed</span>}
                {!d.can_edit && <span><Icon name="lock" size={12} /> Set by the administrator. </span>}
                <Link to={helpHref(d.help)}>Learn more</Link>
              </div>
            </div>
            <div>
              <Input def={d} value={value} onChange={(v) => setDraft({ ...draft, [d.key]: v })} />
              {errors[d.key] && <div className="error-text small" role="alert">{errors[d.key]}</div>}
              {d.type !== "secret" && d.key !== "documents.member_template" && d.default !== null && d.default !== undefined && <div className="small muted">Default: {d.type === "widget_list" ? "all widgets" : d.type === "event_list" ? `${(d.default || []).length} security, backup and integrity events` : Array.isArray(d.default) ? d.default.join(", ") || "none" : String(KEY_CHOICE_LABELS[d.key]?.[d.default] || CHOICE_LABELS[d.default] || d.default) || "empty"}</div>}
            </div>
          </div>
        );
      })}
      {children}
      {defs.some((d) => d.can_edit) && (
        <div className="row" style={{ justifyContent: "flex-end", marginTop: ".8rem" }}>
          <button className="btn" disabled={!dirty} onClick={() => { setDraft({}); setErrors({}); }}>Discard changes</button>
          <button className="btn primary" disabled={!dirty} onClick={save}>Save settings</button>
        </div>
      )}
    </section>
  );
}
