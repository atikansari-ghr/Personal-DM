import { useEffect, useState } from "react";
import { SORT_LABELS, VIEW_LABELS } from "../docview";
import { Link } from "react-router-dom";
import { api } from "../api";
import { HelpTip, Icon, Skeleton, useToast } from "./ui";
import WidgetListEditor from "./WidgetListEditor";

export interface SettingDef {
  key: string; label: string; description: string; type: string; default: any; section: string; scope: string; editable_by: string;
  choices: string[]; min: number | null; max: number | null; depends_on: string[]; effect: string; restart: boolean; help: string;
  example: string; secret: boolean; value: any; configured: boolean | null; can_edit: boolean; choice_labels?: Record<string, string>; locked_choices?: string[];
}

const CHANNEL_LABELS: Record<string, string> = { in_app: "In-app", email: "Email", telegram: "Telegram" };
const CHOICE_LABELS: Record<string, string> = { green: "Green & White", blue: "Blue & White", mono: "Black & White", three_panel: "Three-panel view", full_page: "Full-page viewer", planned: "Planned (not available)", unavailable: "Unavailable in this release", starttls: "STARTTLS", ssl: "SSL/TLS", none: "None (not recommended)", nfs: "NFS", smb: "SMB / Windows share" };
const KEY_CHOICE_LABELS: Record<string, Record<string, string>> = {
  "nas.type": { none: "Already mounted (Proxmox bind mount)" },
  "backup.frequency": { daily: "Daily", weekly: "Weekly", monthly: "Monthly" },
  "me.doc_view": VIEW_LABELS,
  "me.doc_sort": SORT_LABELS,
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
      return <select id={id} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)}>{def.choices.map((c) => <option key={c} value={c}>{KEY_CHOICE_LABELS[def.key]?.[c] || def.choice_labels?.[c] || CHOICE_LABELS[c] || c}</option>)}</select>;
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
    case "choice_list":
    case "event_list": {
      const cur: string[] = Array.isArray(value) ? value : [];
      const labels = def.choice_labels || {};
      return (
        <fieldset className="event-list" aria-label={def.label} disabled={disabled}>
          {def.choices.map((k) => {
            const locked = (def.locked_choices || []).includes(k);
            return <label key={k} className="check" title={locked ? "Always critical; cannot be turned off" : undefined}><input type="checkbox" checked={locked || cur.includes(k)} disabled={locked} onChange={(e) => onChange(e.target.checked ? [...cur, k] : cur.filter((x) => x !== k))} /> {labels[k] || k}{locked ? " (always)" : ""}</label>;
          })}
        </fieldset>
      );
    }
    case "country_list":
      return <CountryListInput value={Array.isArray(value) ? value : []} names={def.choice_labels || {}} disabled={disabled} onChange={onChange} label={def.label} />;
    case "widget_list":
      return <WidgetListEditor value={Array.isArray(value) ? value : []} choices={def.choices} labels={def.choice_labels || {}} disabled={disabled} onChange={onChange} />;
    default:
      return def.key === "documents.import_roots" || def.key === "documents.member_template"
        ? <textarea id={id} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} placeholder={def.example} rows={def.key === "documents.member_template" ? 8 : 3} />
        : <input id={id} type={def.type === "email" ? "email" : "text"} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} placeholder={def.example} />;
  }
}

const flagOf = (code: string) => code.length === 2 ? String.fromCodePoint(...[...code.toUpperCase()].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)) : "";

/** Searchable country selector: chosen countries as removable chips, and a filtered list to add more. */
export function CountryListInput({ value, names, disabled, onChange, label }: { value: string[]; names: Record<string, string>; disabled?: boolean; onChange: (v: string[]) => void; label: string }) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const matches = needle ? Object.entries(names).filter(([c, n]) => !value.includes(c) && (n.toLowerCase().includes(needle) || c.toLowerCase() === needle)).slice(0, 8) : [];
  return (
    <div className="country-list">
      <div className="row" style={{ gap: ".35rem" }}>
        {value.length === 0 && <span className="small muted">No countries chosen.</span>}
        {value.map((c) => (
          <span key={c} className="chip">{flagOf(c)} {names[c] || c}
            {!disabled && <button type="button" className="chip-x" aria-label={`Remove ${names[c] || c}`} onClick={() => onChange(value.filter((x) => x !== c))}><Icon name="x" size={12} /></button>}
          </span>
        ))}
      </div>
      {!disabled && (
        <div className="country-search">
          <input type="search" role="combobox" aria-expanded={matches.length > 0} aria-controls="country-matches" aria-label={`Add to ${label}`} placeholder="Search countries, e.g. United Arab Emirates" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && matches[0]) { e.preventDefault(); onChange([...value, matches[0][0]]); setQ(""); } }} />
          {matches.length > 0 && (
            <ul id="country-matches" role="listbox" className="country-matches">
              {matches.map(([c, n]) => <li key={c} role="option" aria-selected={false}><button type="button" onClick={() => { onChange([...value, c]); setQ(""); }}>{flagOf(c)} {n} <span className="muted small">{c}</span></button></li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
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
              {d.type !== "secret" && d.key !== "documents.member_template" && d.default !== null && d.default !== undefined && <div className="small muted">Default: {d.type === "widget_list" ? "suggested widgets" : d.type === "country_list" ? (d.default || []).map((c: string) => d.choice_labels?.[c] || c).join(", ") : d.type === "event_list" ? `${(d.default || []).length} security, backup and integrity events` : Array.isArray(d.default) ? d.default.join(", ") || "none" : String(KEY_CHOICE_LABELS[d.key]?.[d.default] || CHOICE_LABELS[d.default] || d.default) || "empty"}</div>}
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
