// Same-origin API client: session cookie + CSRF header, JSON errors normalised to ApiError.

export class ApiError extends Error {
  status: number;
  data: any;
  constructor(status: number, data: any) {
    super((data && (data.error || data.detail)) || `Request failed (${status})`);
    this.status = status;
    this.data = data;
  }
}

function csrf(): string {
  const m = document.cookie.match(/(?:^|;\s*)pd_csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

// background: a refresh nobody asked for (polling). It keeps the session alive but does not count as activity for
// Active Sessions (Change Set AB).
type ApiOpts = { method?: string; body?: any; form?: FormData; query?: Record<string, any>; signal?: AbortSignal; background?: boolean };

export function apiUrl(path: string, query?: Record<string, any>): string {
  let url = path.startsWith("/") ? path : `/api/${path}`;
  if (query) {
    const q = new URLSearchParams();
    Object.entries(query).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && q.set(k, String(v)));
    const s = q.toString();
    if (s) url += (url.includes("?") ? "&" : "?") + s;
  }
  return url;
}

// Change Set X: identical GET requests that are in flight at the same time share one network request (several
// components asking for the same data on one screen). Each caller still gets its own copy of the data.
const inflight = new Map<string, Promise<{ status: number; ok: boolean; ct: string; text: string }>>();
// Short-lived copies of data a screen may show again at once (Settings sections). Any change made through the API
// (POST/PUT/PATCH/DELETE) clears them, so what a person just saved is always re-read.
const recent = new Map<string, { at: number; data: any }>();
const listeners = new Set<() => void>();
export function onApiWrite(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }

/** Data for `path` (a GET): the copy from the last `maxAgeMs` if there is one (onCached receives it at once), then
 *  fresh data from the server. Used for screens that are opened again and again, e.g. Settings sections. */
export async function apiFresh<T = any>(path: string, opts: { query?: Record<string, any>; signal?: AbortSignal; maxAgeMs?: number; onCached?: (d: T) => void } = {}): Promise<T> {
  const url = apiUrl(path, opts.query);
  const hit = recent.get(url);
  if (hit && Date.now() - hit.at < (opts.maxAgeMs ?? 10 * 60_000)) opts.onCached?.(structuredClone(hit.data));
  const data = await api<T>(url, { signal: opts.signal });
  recent.set(url, { at: Date.now(), data: structuredClone(data) });
  return data;
}

// Loading problems are reported to the server for Admin → Performance (kind and status only, never the address).
const pending: { kind: string; status?: number }[] = [];
let reportTimer: number | undefined;
export function reportClientError(kind: "api_error" | "network_error" | "chunk_error", status?: number) {
  if (pending.length < 20) pending.push({ kind, status });
  if (reportTimer === undefined) reportTimer = window.setTimeout(() => {
    reportTimer = undefined;
    const errors = pending.splice(0);
    if (errors.length) fetch("/api/perf/client", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify({ errors }) }).catch(() => undefined);
  }, 15_000);
}

export async function api<T = any>(path: string, opts: ApiOpts = {}): Promise<T> {
  const url = apiUrl(path, opts.query);
  const method = opts.method || (opts.body || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-CSRFToken"] = csrf();
  if (opts.background) headers["X-PD-Background"] = "1";
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let r: { status: number; ok: boolean; ct: string; text: string };
  try {
    if (method === "GET" && !opts.signal && !opts.background) {
      let p = inflight.get(url);
      if (!p) {
        p = fetch(url, { method, headers, credentials: "same-origin" })
          .then(async (res) => ({ status: res.status, ok: res.ok, ct: res.headers.get("content-type") || "", text: await res.text() }))
          .finally(() => inflight.delete(url));
        inflight.set(url, p);
      }
      r = await p;
    } else {
      const res = await fetch(url, { method, headers, body, credentials: "same-origin", signal: opts.signal });
      r = { status: res.status, ok: res.ok, ct: res.headers.get("content-type") || "", text: await res.text() };
    }
  } catch (e: any) {
    if (e?.name !== "AbortError" && navigator.onLine) reportClientError("network_error");
    throw e;  // unchanged: callers (offline mode) tell network failures apart from server answers
  }
  if (method !== "GET") { recent.clear(); listeners.forEach((fn) => fn()); }
  if (r.status === 204) return undefined as T;
  let data: any = r.text;
  if (r.ct.includes("json")) { try { data = JSON.parse(r.text); } catch { data = { error: r.text }; } }
  if (!r.ok) {
    if (r.status >= 500) reportClientError("api_error", r.status);
    const res = r;
    const err = new ApiError(res.status, data);
    if (res.status === 403 && data?.code === "password_change_required") window.dispatchEvent(new Event("pd:password-change"));
    if (res.status === 403 && data?.code === "two_factor_setup_required") window.dispatchEvent(new Event("pd:2fa-setup"));
    if (res.status === 401 || (res.status === 403 && /sign in/i.test(err.message))) window.dispatchEvent(new Event("pd:signed-out"));
    throw err;
  }
  return data as T;
}

/** Upload with progress (XHR gives upload progress events; fetch does not). */
export function upload<T = any>(path: string, form: FormData, onProgress?: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path.startsWith("/") ? path : `/api/${path}`);
    xhr.setRequestHeader("X-CSRFToken", csrf());
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onload = () => {
      let data: any = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = { error: xhr.responseText };
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError(xhr.status, data));
    };
    xhr.onerror = () => reject(new ApiError(0, { error: "Network error — check your connection." }));
    xhr.send(form);
  });
}

export function formatBytes(n?: number | null): string {
  if (n === undefined || n === null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v < 10 && i > 0 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

let dateFormat = "d MMM yyyy";
export function setDateFormat(f: string) {
  dateFormat = f || dateFormat;
}
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const d = value.length === 10 ? new Date(value + "T00:00:00") : new Date(value);
  if (isNaN(d.getTime())) return value;
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const y = d.getFullYear();
  switch (dateFormat) {
    case "yyyy-MM-dd":
      return `${y}-${mm}-${dd}`;
    case "dd/MM/yyyy":
      return `${dd}/${mm}/${y}`;
    case "MM/dd/yyyy":
      return `${mm}/${dd}/${y}`;
    default:
      return `${d.getDate()} ${MONTHS[d.getMonth()]} ${y}`;
  }
}
export function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return `${formatDate(value)} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** A post-sign-in destination from ?next=: only an in-app path ("/…"), never another site ("//x", "/\\x", "https:…"). */
export function safeNext(value: string | null | undefined, origin: string = window.location.origin): string {
  const v = (value || "").trim();
  if (!v.startsWith("/") || v.startsWith("//") || v.startsWith("/\\") || /[\\\u0000-\u001f]/.test(v)) return "/";
  try {
    const u = new URL(v, origin);
    return u.origin === origin ? u.pathname + u.search + u.hash : "/";
  } catch {
    return "/";
  }
}
