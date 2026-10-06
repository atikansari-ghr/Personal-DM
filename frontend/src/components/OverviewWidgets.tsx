import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatBytes, formatDate, formatDateTime } from "../api";
import { useSession } from "../session";
import FileTypeIcon from "./FileTypeIcon";
import { Avatar, ExpiryBadge, Icon, Modal, Skeleton } from "./ui";
import type { DocRow } from "../types";

/** Overview widgets: date (Gregorian + Hijri), weather, documents summary, month calendar and upcoming holidays. */

export interface Holiday { date: string; end?: string; country: string; country_name: string; flag: string; name: string; status: string; observed: boolean; source: string; days_away?: number }
export interface WidgetProps { data: any; style: string; settings: Record<string, any>; w: number }

const compact = (style: string) => style.startsWith("compact");
const circle = (style: string) => style.endsWith("circle");
const pad2 = (n: number) => String(n).padStart(2, "0");
const parseISO = (s: string) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };

export function DateWidget({ data, style, settings }: WidgetProps) {
  const t = data.today;
  const d = parseISO(t.date);
  const showHijri = settings.show_hijri !== false;
  const h = t.hijri || {};
  const hijri = h.day ? `${h.day} ${h.month_name} ${h.year} AH` : "";
  if (circle(style)) {
    return (
      <div className="ov-circle-body" aria-label={`Today ${formatDate(t.date)}${hijri ? `, ${hijri}` : ""}`}>
        <div className="small muted">{d.toLocaleDateString(undefined, { weekday: "short" })}</div>
        <div className="ov-big">{d.getDate()}</div>
        <div className="small">{d.toLocaleDateString(undefined, { month: "short", year: "numeric" })}</div>
        {showHijri && h.day && <div className="small muted">{h.day} {h.month_name}</div>}
      </div>
    );
  }
  return (
    <div className="ov-date">
      <div className="ov-date-day" aria-hidden="true"><span>{d.toLocaleDateString(undefined, { month: "short" })}</span><strong>{d.getDate()}</strong></div>
      <div className="grow">
        <div className="ov-label">Today</div>
        <div className="ov-date-main">{d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</div>
        {showHijri && hijri && <div className="ov-hijri">{hijri}{settings.arabic_month && <span lang="ar" dir="rtl"> · {h.month_name_ar}</span>}</div>}
        {!compact(style) && <div className="small muted">{t.timezone}{showHijri ? ` · Hijri: ${t.hijri_calendar}${t.hijri_adjust ? ` (${t.hijri_adjust > 0 ? "+" : ""}${t.hijri_adjust} day)` : ""}` : ""}</div>}
      </div>
    </div>
  );
}

export function WeatherIcon({ name, size = 28 }: { name: string; size?: number }) {
  return <span className={`ov-wx ov-wx-${name}`}><Icon name={name || "cloud"} size={size} /></span>;
}

export function CityDialog({ onClose, onChosen, endpoint = "overview/weather" }: { onClose: () => void; onChosen: (w: any) => void; endpoint?: string }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<any[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const search = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try { setResults((await api<{ cities: any[] }>(`overview/weather/cities?q=${encodeURIComponent(q)}`)).cities); }
    catch (x: any) { setErr(x.message); }
    finally { setBusy(false); }
  };
  return (
    <Modal title="Choose your city" onClose={onClose}>
      <form className="row" onSubmit={search}>
        <input className="grow" type="search" aria-label="City name" placeholder="City name, e.g. Riyadh" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
        <button className="btn primary" disabled={busy || q.trim().length < 2}>Search</button>
      </form>
      {err && <div className="alert error" role="alert" style={{ marginTop: ".6rem" }}>{err}</div>}
      {results && results.length === 0 && <p className="muted small">No city found. Check the spelling or try a nearby larger city.</p>}
      {results && results.length > 0 && (
        <ul className="plain-list" style={{ marginTop: ".6rem" }}>
          {results.map((c, i) => (
            <li key={i}><button type="button" className="list-item btn-reset" onClick={async () => onChosen(await api(endpoint, { method: "PUT", body: { city: c } }))}>
              <Icon name="pin" size={16} /> <span className="grow"><strong>{c.name}</strong> <span className="muted small">{[c.admin1, c.country].filter(Boolean).join(", ")}</span></span>
            </button></li>
          ))}
        </ul>
      )}
      <p className="small muted">Only the chosen city's coordinates are sent to the weather service. Your documents and name are never sent.</p>
    </Modal>
  );
}

export function WeatherWidget({ data, style }: WidgetProps) {
  const { session } = useSession();
  const [w, setW] = useState<any>(null);
  const [picking, setPicking] = useState(false);
  const load = () => api<any>("overview/weather").then(setW).catch((e) => setW({ status: "unavailable", error: e.message }));
  useEffect(() => { if (data.weather_enabled) load(); }, [data.weather_enabled]);
  if (!data.weather_enabled) {
    return <div className="ov-empty small"><WeatherIcon name="cloud-sun" /> {session?.user?.is_main_admin ? <span>Weather is off. <Link to="/settings/overview">Turn it on in Settings</Link>.</span> : "Weather is not set up on this installation."}</div>;
  }
  if (!w) return <Skeleton lines={2} />;
  const picker = picking && <CityDialog onClose={() => setPicking(false)} onChosen={(x) => { setW(x); setPicking(false); }} />;
  if (w.status === "no_city") return <div className="ov-empty"><button className="btn small" onClick={() => setPicking(true)}><Icon name="pin" size={16} /> Choose your city</button>{picker}</div>;
  if (w.status !== "ok") {
    return <div className="ov-empty small" role="status"><WeatherIcon name="cloud" /> Weather unavailable{w.city ? ` for ${w.city.name}` : ""}. <button className="btn small ghost" onClick={load}>Try again</button>{picker}</div>;
  }
  const temp = `${Math.round(w.temperature)}${w.unit}`;
  if (circle(style)) {
    return (
      <div className="ov-circle-body" aria-label={`${w.city.name}: ${temp}, ${w.label}`}>
        <WeatherIcon name={w.icon} size={30} />
        <div className="ov-big">{temp}</div>
        <div className="small">{w.city.name}</div>
        {w.stale && <div className="small muted">Not current</div>}
      </div>
    );
  }
  return (
    <div className="ov-weather">
      <div className="row between" style={{ flexWrap: "nowrap" }}>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <WeatherIcon name={w.icon} size={compact(style) ? 30 : 40} />
          <div>
            <div className="ov-big">{temp}</div>
            <div className="small">{w.label}</div>
          </div>
        </div>
        <button className="btn small ghost ov-city" onClick={() => setPicking(true)} title="Change city"><Icon name="pin" size={14} /> {w.city.name}</button>
      </div>
      {!compact(style) && w.days?.length > 0 && (
        <div className="ov-forecast" aria-label="Forecast">
          {w.days.map((d: any) => (
            <div key={d.date} title={d.label}>
              <div className="small muted">{parseISO(d.date).toLocaleDateString(undefined, { weekday: "short" })}</div>
              <Icon name={d.icon} size={18} />
              <div className="small"><strong>{Math.round(d.max)}°</strong> <span className="muted">{Math.round(d.min)}°</span></div>
            </div>
          ))}
        </div>
      )}
      {w.stale && <div className="small muted" role="status">Showing the last forecast from {formatDateTime(w.fetched_at)}; the weather service is not answering.</div>}
      {picker}
    </div>
  );
}

export function SummaryWidget({ data, style }: WidgetProps) {
  const s = data.stats;
  const tiles: [string, string, any, string, string][] = [
    ["file", "Documents", s.documents.toLocaleString(), "", "/search"],
    ["clock", "Expiring soon", s.expiring_90, s.expiring_90 ? "warn" : "", "/search?expiring_days=90"],
    ["x", "Expired", s.expired, s.expired ? "danger" : "", "/search?expired=1"],
    ["eye", "Needs review", s.needs_review, s.needs_review ? "warn" : "", "/search?state=needs_review"],
    ["share", "Shared with me", s.shared, "", "/shared"],
    ["db", "Storage used", formatBytes(s.storage_bytes), "", "/settings/account"],
  ];
  return (
    <div className={`ov-tiles${compact(style) ? " compact" : ""}`}>
      {tiles.map(([icon, label, value, cls, to]) => (
        <Link key={label} to={to} className={`ov-tile ${cls}`}>
          <Icon name={icon} size={compact(style) ? 18 : 22} />
          <div><div className={`ov-num ${cls}`}>{value}</div><div className="small muted">{label}</div></div>
        </Link>
      ))}
    </div>
  );
}

const DOT_CLASSES = ["c0", "c1", "c2", "c3", "c4", "c5"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function holidayRange(h: Holiday) {
  return h.end && h.end !== h.date ? `${formatDate(h.date)} – ${formatDate(h.end)}` : formatDate(h.date);
}

export function ProvisionalBadge({ h }: { h: Holiday }) {
  return h.status === "provisional"
    ? <span className="badge soon" title="Calculated date. It may move by a day after the official moon-sighting announcement.">Provisional</span>
    : null;
}

export function CalendarWidget({ data, style, settings }: WidgetProps) {
  const today = data.today.date.slice(0, 7);
  const [month, setMonth] = useState(today);
  const [cal, setCal] = useState<any>(null);
  const [picked, setPicked] = useState<string>(data.today.date);
  const countries: string[] | undefined = settings.countries?.length ? settings.countries : undefined;
  useEffect(() => {
    api<any>(`overview/calendar?month=${month}${countries ? `&countries=${countries.join(",")}` : ""}`).then(setCal).catch(() => setCal(null));
  }, [month, countries?.join()]);
  const shift = (n: number) => { const [y, m] = month.split("-").map(Number); const d = new Date(y, m - 1 + n, 1); setMonth(`${d.getFullYear()}-${pad2(d.getMonth() + 1)}`); };
  if (!cal) return <Skeleton lines={5} />;
  const lead = (cal.first_weekday + 1) % 7; // Sunday-first grid; Python weekday(): Monday = 0
  const order = cal.countries.map((c: any) => c.code);
  const day = cal.days.find((d: any) => d.date === picked);
  return (
    <div className={`ov-cal${compact(style) ? " compact" : ""}`}>
      <div className="row between" style={{ flexWrap: "nowrap" }}>
        <div><strong>{cal.label}</strong>{cal.hijri_label && <div className="small muted">{cal.hijri_label}</div>}</div>
        <div className="row" style={{ flexWrap: "nowrap", gap: ".2rem" }}>
          <button className="btn small ghost icon-only" aria-label="Previous month" onClick={() => shift(-1)}><Icon name="left" size={16} /></button>
          <button className="btn small ghost" onClick={() => { setMonth(today); setPicked(data.today.date); }}>Today</button>
          <button className="btn small ghost icon-only" aria-label="Next month" onClick={() => shift(1)}><Icon name="right" size={16} /></button>
        </div>
      </div>
      <div className="ov-cal-grid" role="group" aria-label={`${cal.label} calendar`}>
        {WEEKDAYS.map((w) => <div key={w} className="ov-cal-wd" aria-hidden="true">{w.slice(0, compact(style) ? 1 : 3)}</div>)}
        {Array.from({ length: lead }).map((_, i) => <div key={`e${i}`} />)}
        {cal.days.map((d: any) => {
          const isToday = d.date === cal.today;
          const names = d.holidays.map((h: Holiday) => `${h.flag} ${h.name}${h.status === "provisional" ? " (provisional)" : ""}`).join(", ");
          return (
            <button key={d.date} type="button" aria-pressed={picked === d.date} aria-current={isToday ? "date" : undefined}
              className={`ov-cal-day${isToday ? " today" : ""}${picked === d.date ? " picked" : ""}${d.holidays.length ? " has-hol" : ""}`}
              aria-label={`${formatDate(d.date)}${names ? `: ${names}` : ""}`} title={names || undefined} onClick={() => setPicked(d.date)}>
              <span>{d.day}</span>
              {!compact(style) && d.hijri && <small className="ov-cal-hijri">{d.hijri}</small>}
              {d.holidays.length > 0 && <span className="ov-dots">{[...new Set(d.holidays.map((h: Holiday) => h.country))].map((c: any) => <i key={c} className={DOT_CLASSES[order.indexOf(c) % DOT_CLASSES.length]} />)}</span>}
            </button>
          );
        })}
      </div>
      {cal.countries.length > 0 && (
        <div className="ov-legend small">{cal.countries.map((c: any, i: number) => <span key={c.code}><i className={DOT_CLASSES[i % DOT_CLASSES.length]} /> {c.flag} {c.name}</span>)}</div>
      )}
      {day && day.holidays.length > 0 && (
        <div className="ov-cal-detail" aria-live="polite">
          {day.holidays.map((h: Holiday, i: number) => <div key={i} className="row small"><span>{h.flag}</span><strong>{h.name}</strong><span className="muted">{h.country_name}</span><ProvisionalBadge h={h} /></div>)}
        </div>
      )}
    </div>
  );
}

export function HolidaysWidget({ data, style, settings }: WidgetProps) {
  const custom = settings.countries?.length || settings.count;
  const [list, setList] = useState<Holiday[] | null>(custom ? null : data.holidays);
  useEffect(() => {
    if (!custom) { setList(data.holidays); return; }
    api<{ holidays: Holiday[] }>(`overview/holidays?count=${settings.count || 6}${settings.countries?.length ? `&countries=${settings.countries.join(",")}` : ""}`).then((r) => setList(r.holidays)).catch(() => setList([]));
  }, [data, settings.count, settings.countries?.join()]);
  if (!list) return <Skeleton lines={3} />;
  if (!data.holiday_countries.length && !settings.countries?.length) return <div className="ov-empty small">No holiday countries are chosen.</div>;
  if (!list.length) return <div className="ov-empty small">No public holidays in the next four months.</div>;
  return (
    <ul className={`ov-hols plain-list${compact(style) ? " compact" : ""}`}>
      {list.map((h, i) => (
        <li key={i}>
          <span className="ov-flag" aria-label={h.country_name} title={h.country_name}>{h.flag}</span>
          <div className="grow"><div className="ov-hol-name">{h.name}</div>{!compact(style) && <div className="small muted">{holidayRange(h)} · {h.country_name}</div>}</div>
          <ProvisionalBadge h={h} />
          <span className="badge neutral">{h.days_away === 0 ? "Today" : h.days_away === 1 ? "Tomorrow" : `${h.days_away} days`}</span>
        </li>
      ))}
    </ul>
  );
}

export function DocList({ docs, empty, count, expiry }: { docs: DocRow[]; empty: string; count?: number; expiry?: boolean }) {
  if (!docs.length) return <div className="ov-empty small">{empty}</div>;
  return (
    <ul className="plain-list ov-docs">
      {docs.slice(0, count || 6).map((d) => (
        <li key={d.id}>
          <Link to={`/documents/${d.id}`} className="list-item" style={{ textDecoration: "none", color: "inherit" }}>
            <FileTypeIcon kind={d.file_kind} label={d.file_label} size="sm" />
            <div className="grow" style={{ minWidth: 0 }}>
              <div className="ov-doc-title">{d.title}</div>
              <div className="muted small">{d.owner.display_name} · {expiry ? formatDate(d.expiry_date) : d.type?.name || d.file_label}</div>
            </div>
            {expiry ? <ExpiryBadge expiry={d.expiry} /> : <Avatar user={d.owner} size="sm" />}
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function ActivityWidget({ data, settings }: WidgetProps) {
  if (!data.activity.length) return <div className="ov-empty small">No recent activity.</div>;
  return (
    <ul className="plain-list ov-activity">
      {data.activity.slice(0, settings.count || 6).map((a: any, i: number) => (
        <li key={i}><span className="small"><strong>{a.actor}</strong> {a.verb} <Link to={`/documents/${a.document.id}`}>{a.document.title}</Link></span><span className="small muted">{formatDateTime(a.at)}</span></li>
      ))}
    </ul>
  );
}

