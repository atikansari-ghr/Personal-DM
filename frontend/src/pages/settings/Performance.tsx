import { Fragment, useEffect, useState } from "react";
import { api, formatDateTime } from "../../api";
import SettingsForm from "../../components/SettingsForm";
import { HelpTip, Skeleton } from "../../components/ui";
import { useSession } from "../../session";

/** Admin → Performance (Change Set X): how fast the app answers, what runs in the background, how busy the server
 *  is, and whether background work is being held back. Aggregated measurements only (no document data, no
 *  secrets). Refreshes every 30 seconds while open. */

type Row = { name: string; count: number; avg_ms: number; max_ms: number; avg_queries: number; avg_db_ms: number; errors: number };
type Point = { at: string; avg: number; max: number | null };

const SYS: [string, string, (v: any) => string][] = [
  ["cpu_percent", "CPU in use", (v) => `${v}%`],
  ["mem_available_percent", "Memory available", (v) => `${v}%`],
  ["swap_used_percent", "Swap in use", (v) => `${v}%`],
  ["load1", "Load (1 min)", (v) => Number(v).toFixed(2)],
  ["storage_latency_ms", "Storage write (4 KB)", (v) => `${v} ms`],
  ["psi_io", "Disk pressure", (v) => `${v}%`],
  ["db_connections", "Database connections", (v) => String(v)],
  ["jobs_queued", "Jobs waiting", (v) => String(v)],
  ["jobs_running", "Jobs running", (v) => String(v)],
];

function Spark({ points, label }: { points: Point[]; label: string }) {
  if (!points || points.length < 2) return <span className="small muted">Not enough data yet</span>;
  const w = 220, h = 36, vals = points.map((p) => p.avg), max = Math.max(...vals, 1);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${(i / (vals.length - 1)) * w},${h - (v / max) * (h - 4) - 2}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${label}: ${vals.length} points, latest ${vals[vals.length - 1]}`}>
      <path d={d} fill="none" stroke="var(--brand)" strokeWidth="2" />
    </svg>
  );
}

function Table({ rows, kind }: { rows: Row[]; kind: "api" | "job" }) {
  if (!rows.length) return <p className="small muted">Nothing recorded in this period.</p>;
  return (
    <div className="table-scroll">
      <table className="table small perf-table">
        <thead><tr><th scope="col">{kind === "api" ? "Request" : "Job"}</th><th scope="col">Count</th><th scope="col">Average</th><th scope="col">Slowest</th>
          {kind === "api" && <th scope="col">Queries</th>}<th scope="col">{kind === "api" ? "Server errors" : "Failed"}</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.name}><td><code>{r.name}</code></td><td>{r.count}</td><td>{r.avg_ms} ms</td><td>{r.max_ms} ms</td>
            {kind === "api" && <td>{r.avg_queries}</td>}<td>{r.errors || "—"}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export default function PerformancePanel() {
  const { session } = useSession();
  const mainAdmin = !!session?.user?.is_main_admin;
  const [hours, setHours] = useState(24);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let ctl = new AbortController();
    const load = () => api<any>("admin/performance", { query: { hours }, signal: ctl.signal }).then((d) => { setData(d); setError(""); })
      .catch((e) => { if (e?.name !== "AbortError") setError(e.message); });
    load();
    const t = window.setInterval(() => { ctl.abort(); ctl = new AbortController(); load(); }, 30_000);
    return () => { window.clearInterval(t); ctl.abort(); };
  }, [hours]);
  if (error) return <div className="alert error">Could not load performance data: {error}</div>;
  if (!data) return <section className="card"><Skeleton /></section>;
  const th = data.throttle || {};
  const sys = data.system || {};
  return (
    <div className="stack" id="performance">
      <section className="card stack">
        <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <h2 style={{ margin: 0 }}>Performance <HelpTip text="How fast Personal DM answers, what runs in the background and how busy the server is. Measurements are summaries kept for a limited time; they contain no document data or secrets." link="/help/performance#dashboard" /></h2>
          <div className="row" style={{ gap: 6 }}>
            <label className="small" htmlFor="perf-hours">Period</label>
            <select id="perf-hours" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
              <option value={1}>Last hour</option><option value={24}>Last 24 hours</option><option value={168}>Last 7 days</option>
            </select>
            {mainAdmin && <a className="btn small" href={`/api/admin/performance/report?hours=${hours}`} download>Download Diagnostic Report</a>}
          </div>
        </div>
        <div className={`alert ${th.active ? "warn" : "ok"} small`} role="status" data-throttle={th.active ? "active" : "normal"}>
          {th.active ? <><strong>Background processing throttled</strong> since {th.since ? formatDateTime(th.since) : "—"}: {th.reason || "heavy load"}. Non-urgent work (OCR, library scans, AI, reports) waits until the load is normal; nothing running is stopped.</>
            : <><strong>Background processing normal.</strong> {th.checked_at ? `Checked ${formatDateTime(th.checked_at)}.` : ""}</>}
        </div>
        {data.warnings?.length > 0 && <div className="alert warn small"><strong>Warnings</strong><ul style={{ margin: ".3rem 0 0" }}>{data.warnings.map((w: string) => <li key={w}>{w}</li>)}</ul></div>}
        <dl className="dest-facts small perf-system">
          {SYS.filter(([k]) => sys[k] !== null && sys[k] !== undefined).map(([k, l, f]) => <Fragment key={k}><dt>{l}</dt><dd>{f(sys[k])}</dd></Fragment>)}
          <dt>Requests ({hours} h)</dt><dd>{data.requests.total} · average {data.requests.avg_ms} ms · {data.requests.errors} server errors</dd>
          <dt>Worker</dt><dd>{data.workers.worker?.age_seconds != null ? `reported ${data.workers.worker.age_seconds} s ago` : "not reporting"}</dd>
          <dt>Scheduler</dt><dd>{data.workers.scheduler?.age_seconds != null ? `reported ${data.workers.scheduler.age_seconds} s ago` : "not reporting"}</dd>
          <dt>Version</dt><dd>{data.version}</dd>
        </dl>
        <div className="row perf-trends" style={{ gap: 24, flexWrap: "wrap" }}>
          <div><div className="small muted">Average response time</div><Spark points={data.trend.api_avg_ms} label="Average response time" /></div>
          <div><div className="small muted">CPU in use</div><Spark points={data.trend.cpu_percent} label="CPU in use" /></div>
          <div><div className="small muted">Memory available</div><Spark points={data.trend.mem_available_percent} label="Memory available" /></div>
          <div><div className="small muted">Jobs waiting</div><Spark points={data.trend.jobs_queued} label="Jobs waiting" /></div>
        </div>
      </section>
      <section className="card stack">
        <h3 style={{ margin: 0 }}>Slowest requests</h3>
        <Table rows={data.requests.slowest} kind="api" />
        <details><summary>All requests ({data.requests.by_route.length})</summary><Table rows={data.requests.by_route} kind="api" /></details>
      </section>
      <section className="card stack">
        <h3 style={{ margin: 0 }}>Background jobs</h3>
        <Table rows={data.jobs} kind="job" />
      </section>
      <section className="card stack">
        <h3 style={{ margin: 0 }}>Caches and loading errors</h3>
        <p className="small muted">{data.cache.note}</p>
        <ul className="small">
          <li>Settings read once per request: {data.cache.settings_snapshot.hits} reused, {data.cache.settings_snapshot.misses} loaded.</li>
          {Object.entries(data.cache.shared || {}).map(([k, v]: any) => <li key={k}>{k}: {v.hits} hits, {v.misses} misses ({Math.round(v.hit_rate * 100)}%).</li>)}
          <li>Loading errors reported by browsers: {data.client_errors.reduce((a: number, r: Row) => a + r.count, 0) || "none"}.</li>
        </ul>
      </section>
      <section className="card stack">
        <h3 style={{ margin: 0 }}>Recent performance events</h3>
        {data.events.length ? <ul className="small perf-events">{data.events.map((e: any, i: number) => <li key={i}>{formatDateTime(e.at)} — {e.message}</li>)}</ul>
          : <p className="small muted">No slow requests or throttling recorded.</p>}
      </section>
      {mainAdmin && <SettingsForm section="performance" title="Performance settings" />}
    </div>
  );
}
