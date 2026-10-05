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

export async function api<T = any>(path: string, opts: { method?: string; body?: any; form?: FormData; query?: Record<string, any> } = {}): Promise<T> {
  let url = path.startsWith("/") ? path : `/api/${path}`;
  if (opts.query) {
    const q = new URLSearchParams();
    Object.entries(opts.query).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && q.set(k, String(v)));
    const s = q.toString();
    if (s) url += (url.includes("?") ? "&" : "?") + s;
  }
  const method = opts.method || (opts.body || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-CSRFToken"] = csrf();
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(url, { method, headers, body, credentials: "same-origin" });
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
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
