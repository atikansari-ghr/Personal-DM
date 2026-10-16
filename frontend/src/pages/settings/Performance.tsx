import { useEffect, useState } from "react";
import { api, formatDateTime } from "../../api";
import SettingsForm from "../../components/SettingsForm";
import { HelpTip, Skeleton } from "../../components/ui";
import { useSession } from "../../session";

/** Admin → Performance (Change Set X): how fast the app answers, what runs in the background, how busy the server
 *  is, and whether background work is being held back. Aggregated measurements only (no document data, no
 *  secrets). Refreshes every 30 seconds while open. */

type Row = { name: string; count: number; avg_ms: number; max_ms: number; avg_queries: number; avg_db_ms: number; errors: number };
type Point = { at: string; avg: number; max: number | null };
type State = "ok" | "warn" | "info";

const num = (v: number, digits = 1) => (Math.round(v * 10 ** digits) / 10 ** digits).toLocaleString();
const periodLabel = (h: number) => (h === 1 ? "last hour" : h === 24 ? "last 24 hours" : "last 7 days");
const ago = (s: number | null | undefined) => (s == null ? "not reporting" : s < 90 ? `${s} s ago` : `${Math.round(s / 60)} min ago`);

/** One current measurement: value, a short explanation, and whether it needs attention (same limits as the
 *  warnings the server sends, and the throttling defaults). */
function Tile({ label, value, note, state = "info", id }: { label: string; value: string; note?: string; state?: State; id?: string }) {
  return (
    <div className="stat perf-tile" data-state={state} data-metric={id}>
      <span className="small muted">{label}</span>
      <span className="num">{value}</span>
      {note && <span className="small muted">{note}</span>}
    </div>
  );
}

/** A trend with its numbers: latest value, lowest–highest in the period, a chart scaled to the highest value, the
 *  time span, and the value and time of the point under the pointer. */
function Trend({ title, points, unit, digits = 1, hours }: { title: string; points?: Point[]; unit: string; digits?: number; hours: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const fmt = (v: number) => `${num(v, digits)}${unit}`;
  // axis ends: the time of day for a day or less, the date for a week
  const short = (at: string) => new Date(at).toLocaleString(undefined, hours <= 24 ? { hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short" });
  if (!points || points.length < 2) {
    return (
      <div className="perf-trend" data-points={points?.length || 0}>
        <span className="small muted perf-trend-title">{title}</span>
        <span className="perf-trend-value">{points?.length === 1 ? fmt(points[0].avg) : "—"}</span>
        <p className="small muted perf-trend-empty">Not enough data yet. Measurements are summarised every 10 minutes.</p>
      </div>
    );
  }
  const vals = points.map((p) => p.avg);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  // headroom so the highest point is not drawn on the edge; a percentage never goes above 100
  const top = hi > 0 ? (unit === "%" ? Math.min(100, hi * 1.1) : hi * 1.1) : 1;
  const W = 300, H = 72;
  const x = (i: number) => (i / (vals.length - 1)) * W;
  const y = (v: number) => H - 2 - (v / top) * (H - 6);
  const line = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${W},${H} L0,${H} Z`;
  const shown = hover ?? vals.length - 1;
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setHover(Math.max(0, Math.min(vals.length - 1, Math.round(((e.clientX - r.left) / r.width) * (vals.length - 1)))));
  };
  return (
    <div className="perf-trend" data-points={vals.length}>
      <span className="small muted perf-trend-title">{title}</span>
      <div className="perf-trend-head">
        <span className="perf-trend-value" aria-live="polite">{fmt(vals[shown])}</span>
        <span className="small muted">{hover == null ? "latest" : formatDateTime(points[shown].at)}</span>
      </div>
      <span className="small muted">Low {fmt(lo)} · High {fmt(hi)}</span>
      <div className="perf-trend-chart">
        <span className="perf-trend-ymax small muted" aria-hidden="true">{fmt(top)}</span>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" onMouseMove={onMove} onMouseLeave={() => setHover(null)}
          aria-label={`${title} over the period: latest ${fmt(vals[vals.length - 1])}, low ${fmt(lo)}, high ${fmt(hi)}, ${vals.length} summaries`}>
          <line x1="0" y1={H - 0.5} x2={W} y2={H - 0.5} className="perf-axis" />
          <path d={area} className="perf-area" />
          <path d={line} className="perf-line" vectorEffect="non-scaling-stroke" />
          {hover != null && <line x1={x(hover)} y1="0" x2={x(hover)} y2={H} className="perf-cursor" vectorEffect="non-scaling-stroke" />}
        </svg>
      </div>
      <div className="perf-trend-axis small muted" aria-hidden="true">
        <span>{short(points[0].at)}</span><span>{short(points[points.length - 1].at)}</span>
      </div>
    </div>
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
  const has = (k: string) => sys[k] !== null && sys[k] !== undefined;
  const beat = (b: any): State => (b?.age_seconds == null || b.age_seconds > 180 ? "warn" : "ok");
  const tr = data.trend || {};
  return (
    <div className="stack" id="performance">
      <section className="card stack">
        <div className="perf-head">
          <h2 style={{ margin: 0 }}>Performance <HelpTip text="How fast Personal DM answers, what runs in the background and how busy the server is. Measurements are summaries kept for a limited time; they contain no document data or secrets." link="/help/performance#dashboard" /></h2>
          <div className="perf-toolbar">
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
        <h3 className="perf-subhead">Server now <span className="small muted">{data.sampled_at ? `measured ${formatDateTime(data.sampled_at)}` : "waiting for the first measurement"}</span></h3>
        <div className="stat-grid perf-tiles">
          {has("cpu_percent") && <Tile id="cpu" label="CPU in use" value={`${num(sys.cpu_percent)}%`} state={sys.cpu_percent >= 90 ? "warn" : "ok"}
            note={sys.cpus ? `${sys.cpus} CPU${sys.cpus > 1 ? "s" : ""}` : undefined} />}
          {has("mem_available_percent") && <Tile id="memory" label="Memory available" value={`${num(sys.mem_available_percent)}%`}
            state={sys.mem_available_percent < 15 ? "warn" : "ok"} note={sys.mem_total_mb ? `of ${num(sys.mem_total_mb / 1024)} GB` : undefined} />}
          {has("swap_used_percent") && <Tile id="swap" label="Swap in use" value={`${num(sys.swap_used_percent)}%`} state={sys.swap_used_percent > 30 ? "warn" : "ok"} />}
          {has("load1") && <Tile id="load" label="Load (1 min)" value={num(sys.load1, 2)} state={sys.cpus && sys.load1 > sys.cpus * 1.5 ? "warn" : "ok"}
            note={sys.cpus ? `${num(sys.load1 / sys.cpus, 2)} per CPU` : undefined} />}
          {has("storage_latency_ms") && <Tile id="storage" label="Storage write (4 KB)" value={`${num(sys.storage_latency_ms)} ms`}
            state={sys.storage_latency_ms > 200 ? "warn" : "ok"} note="slow above 200 ms" />}
          {has("psi_io") && <Tile id="disk" label="Disk pressure" value={`${num(sys.psi_io)}%`} state={sys.psi_io > 40 ? "warn" : "ok"} note="time waiting for the disk" />}
          {has("db_connections") && <Tile id="db" label="Database connections" value={String(sys.db_connections)}
            state={sys.db_max_connections && sys.db_connections > 0.8 * sys.db_max_connections ? "warn" : "ok"}
            note={sys.db_max_connections ? `of ${sys.db_max_connections}` : undefined} />}
          {has("jobs_queued") && <Tile id="queue" label="Background jobs" value={`${sys.jobs_queued} waiting`} state={sys.jobs_queued > 50 ? "warn" : "ok"}
            note={has("jobs_running") ? `${sys.jobs_running} running` : undefined} />}
        </div>
        <h3 className="perf-subhead">Requests and services <span className="small muted">{periodLabel(hours)}</span></h3>
        <div className="stat-grid perf-tiles">
          <Tile id="requests" label="Requests" value={data.requests.total.toLocaleString()} note={`average ${num(data.requests.avg_ms)} ms`} />
          <Tile id="errors" label="Server errors" value={String(data.requests.errors)} state={data.requests.errors ? "warn" : "ok"} />
          <Tile id="worker" label="Worker" value={ago(data.workers.worker?.age_seconds)} state={beat(data.workers.worker)} note="runs background jobs" />
          <Tile id="scheduler" label="Scheduler" value={ago(data.workers.scheduler?.age_seconds)} state={beat(data.workers.scheduler)} note="measures the server every minute" />
          <Tile id="web" label="Web service" value={`${data.workers.web_workers || "2"} × ${data.workers.web_threads || "4"}`} note="processes × threads" />
          <Tile id="version" label="Version" value={data.version || "—"} />
        </div>
        <h3 className="perf-subhead">Trends <span className="small muted">{periodLabel(hours)}, 10-minute summaries · point at a chart for a value</span></h3>
        <div className="perf-trends">
          <Trend title="Average response time" points={tr.api_avg_ms} unit=" ms" hours={hours} />
          <Trend title="Requests per 10 minutes" points={tr.api_requests} unit="" digits={0} hours={hours} />
          <Trend title="CPU in use" points={tr.cpu_percent} unit="%" hours={hours} />
          <Trend title="Memory available" points={tr.mem_available_percent} unit="%" hours={hours} />
          <Trend title="Background jobs waiting" points={tr.jobs_queued} unit="" digits={0} hours={hours} />
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
