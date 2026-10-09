// Offline copies scoped by account + device (browser or installed app) + folder/document (Change Set S).
//
// Storage on the device, kept apart on purpose:
//   * the app shell (HTML, scripts, icons)      -> Cache "pd-shell-*", managed by the service worker (no user data);
//   * protected originals                        -> Cache "pd-offline-<account>", keys /offline/<version>;
//   * recognised text (only if the admin allows) -> Cache "pd-offline-text-<account>", keys /offline-text/<document>;
//   * the index (titles, sizes, status)          -> localStorage "pd-offline-index-<account>".
// Nothing is cached merely because it was viewed, and API responses are never cached. The server decides at every
// sync what this device may hold (download permission is re-checked); anything else is deleted here. Policy:
// docs/guides/offline-export.md.
import { useEffect, useState } from "react";
import { api } from "./api";

export type OfflineStatus = "available" | "downloading" | "update_available" | "updating" | "outdated" | "failed" | "locked" | "none";

export interface OfflineItem {
  documentId: string;
  versionId: string;          // version held on this device
  versionNumber?: number;
  latestVersionId?: string;   // newer version on the server (update available)
  title: string;
  name: string;
  mime: string;
  size: number;
  folder?: string;
  path?: string;
  selections?: number[];
  savedAt: string;
  status: OfflineStatus;
  progress?: number;          // 0..100 while downloading/updating
  error?: string;
  text?: string | null;       // hash of the offline text held (null: none)
  stale?: boolean;            // legacy field (pre-Change Set S index)
}

export interface Selection { id: number; kind: "folder" | "document"; folder?: string; document?: string; recursive?: boolean; name: string; available: boolean }

export interface OfflinePolicy {
  enabled: boolean; auto_update: boolean; cache_text: boolean; logout_policy: "user_choice" | "always_clear";
  max_days_without_sync: number; device_quota_mb: number; large_download_mb: number;
}

export interface OfflineState {
  items: Record<string, OfflineItem>;
  selections: Selection[];
  deviceId?: string;
  deviceLabel?: string;
  lastSync?: string;
  lastAttempt?: string;
  lastError?: string;
  allowed: boolean;
  reason?: string;
  policy?: OfflinePolicy;
  syncing?: boolean;
  version: 2;
}

const OUTDATED_DAYS = 7;
const cacheName = (uid: string) => `pd-offline-${uid}`;
const textCacheName = (uid: string) => `pd-offline-text-${uid}`;
const indexKey = (uid: string) => `pd-offline-index-${uid}`;
const keepKey = (uid: string) => `pd-offline-keep-${uid}`;
const deviceKey = (uid: string) => `pd-offline-device-${uid}`;

export const offlineSupported = () => typeof caches !== "undefined" && typeof localStorage !== "undefined";

// ------------------------------------------------------------------ index (small, synchronous)
const empty = (): OfflineState => ({ items: {}, selections: [], allowed: true, version: 2 });

export function readState(uid: string): OfflineState {
  try {
    const raw = JSON.parse(localStorage.getItem(indexKey(uid)) || "null");
    if (!raw) return { ...empty(), deviceId: localStorage.getItem(deviceKey(uid)) || undefined };
    if (Array.isArray(raw)) {
      // Index written before Change Set S: a list of single documents. Keep the copies; the first sync turns them
      // into document selections for this device.
      const items: Record<string, OfflineItem> = {};
      for (const it of raw) items[it.documentId] = { ...it, status: "available", legacy: true } as OfflineItem;
      return { ...empty(), items, deviceId: localStorage.getItem(deviceKey(uid)) || undefined };
    }
    return { ...empty(), ...raw, deviceId: raw.deviceId || localStorage.getItem(deviceKey(uid)) || undefined };
  } catch {
    return empty();
  }
}

const listeners = new Set<() => void>();
function writeState(uid: string, st: OfflineState) {
  try {
    localStorage.setItem(indexKey(uid), JSON.stringify({ ...st, syncing: undefined }));
  } catch { /* storage full or blocked: the in-memory copy still updates the screen */ }
  memory.set(uid, st);
  listeners.forEach((l) => l());
}
const memory = new Map<string, OfflineState>();
function current(uid: string): OfflineState {
  if (!memory.has(uid)) memory.set(uid, readState(uid));
  return memory.get(uid)!;
}
function patch(uid: string, fn: (s: OfflineState) => OfflineState) {
  writeState(uid, fn(current(uid)));
}
function patchItem(uid: string, docId: string, change: Partial<OfflineItem>) {
  patch(uid, (s) => (s.items[docId] ? { ...s, items: { ...s.items, [docId]: { ...s.items[docId], ...change } } } : s));
}

/** React hook: this account's offline state on this device; re-renders on every change. */
export function useOffline(uid: string | undefined): OfflineState {
  const [, setTick] = useState(0);
  useEffect(() => {
    const l = () => setTick((t) => t + 1);
    listeners.add(l);
    const onStorage = (e: StorageEvent) => { if (uid && e.key === indexKey(uid)) { memory.delete(uid); l(); } };
    window.addEventListener("storage", onStorage);
    return () => { listeners.delete(l); window.removeEventListener("storage", onStorage); };
  }, [uid]);
  return uid ? current(uid) : empty();
}

export function listOffline(uid: string): OfflineItem[] {
  return Object.values(current(uid).items).sort((a, b) => a.title.localeCompare(b.title));
}

/** Status shown for a document: never by colour alone (each status has a label and an icon). */
export function statusOf(st: OfflineState, docId: string): OfflineStatus {
  const it = st.items[docId];
  if (!it) return "none";
  if (isLocked(st)) return "locked";
  if (it.status === "available" && st.lastSync && Date.now() - Date.parse(st.lastSync) > OUTDATED_DAYS * 86400e3) return "outdated";
  return it.status;
}

export function isLocked(st: OfflineState): boolean {
  const days = st.policy?.max_days_without_sync ?? 0;
  return !!(days && st.lastSync && Date.now() - Date.parse(st.lastSync) > days * 86400e3);
}

export const STATUS_LABEL: Record<OfflineStatus, string> = {
  available: "Available offline",
  downloading: "Downloading",
  update_available: "Update available",
  updating: "Updating",
  outdated: "Outdated — not checked for a week",
  failed: "Offline copy failed",
  locked: "Locked — connect to unlock",
  none: "Not available offline",
};

export function folderSelection(st: OfflineState, folderId: string): Selection | undefined {
  return st.selections.find((s) => s.kind === "folder" && s.folder === folderId);
}
export function documentSelection(st: OfflineState, docId: string): Selection | undefined {
  return st.selections.find((s) => s.kind === "document" && s.document === docId);
}

// ------------------------------------------------------------------ storage information
export async function storageInfo(): Promise<{ usage?: number; quota?: number; persisted?: boolean }> {
  if (!navigator.storage?.estimate) return {};
  const est = await navigator.storage.estimate();
  const persisted = navigator.storage.persisted ? await navigator.storage.persisted() : undefined;
  return { usage: est.usage, quota: est.quota, persisted };
}

export async function requestPersistence(): Promise<boolean> {
  try {
    return navigator.storage?.persist ? await navigator.storage.persist() : false;
  } catch {
    return false;
  }
}

// ------------------------------------------------------------------ device registration
function deviceLabel(): { label: string; platform: string; installed: boolean } {
  const ua = navigator.userAgent;
  const os = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) ? "iPad"
    : /Android/.test(ua) ? "Android" : /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "Mac" : /Linux/.test(ua) ? "Linux" : "Device";
  const br = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Browser";
  const installed = window.matchMedia?.("(display-mode: standalone)").matches || (navigator as any).standalone === true;
  return { label: installed ? `${os} app` : `${br} on ${os}`, platform: `${br} on ${os}`, installed };
}

async function ensureDevice(uid: string): Promise<string> {
  const st = current(uid);
  const d = deviceLabel();
  const r = await api<{ device: { id: string; label: string }; allowed: boolean; reason: string; policy: OfflinePolicy }>("offline/devices", {
    body: { device_id: st.deviceId, label: d.label, platform: d.platform, installed_app: d.installed },
  });
  try { localStorage.setItem(deviceKey(uid), r.device.id); } catch { /* ignore */ }
  patch(uid, (s) => ({ ...s, deviceId: r.device.id, deviceLabel: r.device.label, allowed: r.allowed, reason: r.reason, policy: r.policy }));
  return r.device.id;
}

// ------------------------------------------------------------------ choosing what to keep
export async function estimate(target: { folder?: string; document?: string; recursive?: boolean }) {
  return api<{ documents: number; subfolders: number; bytes: number; blocked: number; not_downloadable: number; quota_bytes: number; large_bytes: number }>(
    "offline/estimate", { query: { folder: target.folder, document: target.document, recursive: target.recursive === false ? "0" : "1" } });
}

export async function makeAvailable(uid: string, target: { folder?: string; document?: string; recursive?: boolean }) {
  if (!offlineSupported()) throw new Error("This browser does not support offline storage.");
  const device = await ensureDevice(uid);
  await api("offline/selections", { body: { device, ...target } });
  await requestPersistence();
  return { sync: syncNow(uid) };  // the download continues in the background; statuses show progress
}

/** Remove a folder's or a document's offline selection; copies not covered by another selection are deleted. */
export async function removeSelection(uid: string, sel: Selection) {
  await api(`offline/selections/${sel.id}`, { method: "DELETE" });
  patch(uid, (s) => ({ ...s, selections: s.selections.filter((x) => x.id !== sel.id) }));
  return syncNow(uid);
}

/** Update one document (or every outdated one) now, even when automatic updates are off. */
export async function updateNow(uid: string, docId?: string) {
  return syncNow(uid, { force: docId ? [docId] : "all" });
}

// ------------------------------------------------------------------ sync
let running: Promise<SyncResult> | null = null;
export interface SyncResult { downloaded: number; updated: number; removed: number; failed: number; wiped: boolean; error?: string }

export function syncNow(uid: string, opts: { force?: string[] | "all" } = {}): Promise<SyncResult> {
  if (running) return running.then(() => syncNow(uid, opts));
  running = doSync(uid, opts).finally(() => { running = null; });
  return running;
}

async function doSync(uid: string, opts: { force?: string[] | "all" }): Promise<SyncResult> {
  const out: SyncResult = { downloaded: 0, updated: 0, removed: 0, failed: 0, wiped: false };
  if (!offlineSupported() || !navigator.onLine) return out;
  patch(uid, (s) => ({ ...s, syncing: true, lastAttempt: new Date().toISOString() }));
  try {
    let st = current(uid);
    const device = st.deviceId || (await ensureDevice(uid));
    // copies saved before Change Set S become document selections of this device
    const legacy = Object.values(st.items).filter((i: any) => i.legacy);
    for (const it of legacy) {
      await api("offline/selections", { body: { device, document: it.documentId } }).catch(() => undefined);
      patchItem(uid, it.documentId, { legacy: undefined } as any);
    }
    st = current(uid);
    const have = Object.values(st.items).map((i) => ({ document: i.documentId, version: i.versionId, text: i.text ?? null }));
    const bytes = Object.values(st.items).reduce((n, i) => n + (i.size || 0), 0);
    const failures = Object.values(st.items).filter((i) => i.status === "failed").length;
    const res = await api<{ known_device: boolean; allowed: boolean; reason: string; wipe: boolean; policy: OfflinePolicy; selections: Selection[];
      items: { document: string; version: string; version_number: number; title: string; name: string; mime: string; size: number; folder: string; path: string; selections: number[]; text: string | null }[];
      remove: string[]; server_time: string }>("offline/sync", { body: { device, have, report: { items: have.length, bytes, failures } } });
    if (res.wipe || !res.known_device) {
      await clearAll(uid, { keepDevice: res.known_device });
      out.wiped = true;
      out.removed = have.length;
      patch(uid, (s) => ({ ...s, allowed: res.allowed, reason: res.reason, policy: res.policy, selections: [], lastSync: res.server_time }));
      if (!res.known_device && res.allowed !== false) { /* registered again on the next selection */ }
      return out;
    }
    patch(uid, (s) => ({ ...s, allowed: res.allowed, reason: res.reason, policy: res.policy, selections: res.selections }));
    for (const docId of res.remove) {
      await deleteCopy(uid, docId);
      out.removed++;
    }
    const force = opts.force;
    for (const it of res.items) {
      const local = current(uid).items[it.document];
      const meta = { title: it.title, name: it.name, mime: it.mime, folder: it.folder, path: it.path, selections: it.selections, versionNumber: it.version_number };
      if (!local || local.status === "failed" && local.versionId === it.version && !(await hasBlob(uid, it.version))) {
        const ok = await download(uid, it, "downloading", meta);
        ok ? out.downloaded++ : out.failed++;
      } else if (local.versionId !== it.version) {
        const forced = force === "all" || (Array.isArray(force) && force.includes(it.document));
        if (res.policy.auto_update || forced) {
          const ok = await download(uid, it, "updating", meta);
          ok ? out.updated++ : out.failed++;
        } else {
          patchItem(uid, it.document, { ...meta, status: "update_available", latestVersionId: it.version });
        }
      } else {
        patchItem(uid, it.document, { ...meta, status: "available", latestVersionId: undefined, error: undefined, size: it.size });
      }
      await syncText(uid, it.document, it.text, res.policy.cache_text);
    }
    patch(uid, (s) => ({ ...s, lastSync: res.server_time, lastError: undefined }));
    // tell the server what this device holds now (counts and bytes only), for Offline & PWA and "Your other devices"
    const held = Object.values(current(uid).items);
    api(`offline/devices/${device}`, { method: "PATCH", body: { report: { items: held.length, bytes: held.reduce((n, i) => n + (i.size || 0), 0),
      failures: held.filter((i) => i.status === "failed").length } } }).catch(() => undefined);
  } catch (e: any) {
    out.error = e?.message || "Sync failed";
    patch(uid, (s) => ({ ...s, lastError: out.error }));
  } finally {
    patch(uid, (s) => ({ ...s, syncing: false }));
  }
  return out;
}

async function hasBlob(uid: string, versionId: string) {
  return !!(await (await caches.open(cacheName(uid))).match(`/offline/${versionId}`));
}

async function download(uid: string, it: { document: string; version: string; size: number; title: string }, phase: "downloading" | "updating",
  meta: Partial<OfflineItem>): Promise<boolean> {
  const prev = current(uid).items[it.document];
  const base: OfflineItem = prev ? { ...prev, ...meta } : { documentId: it.document, versionId: it.version, size: it.size, savedAt: "", title: it.title, name: "", mime: "", ...meta, status: phase } as OfflineItem;
  patch(uid, (s) => ({ ...s, items: { ...s.items, [it.document]: { ...base, status: phase, progress: 0, error: undefined } } }));
  try {
    const info = await storageInfo();
    if (info.quota !== undefined && info.usage !== undefined && info.quota - info.usage < it.size * 1.1)
      throw new Error("Not enough browser storage on this device.");
    const res = await fetch(`/api/documents/${it.document}/file?download=1&version=${it.version}`, { credentials: "same-origin" });
    if (!res.ok) throw new Error(res.status === 403 || res.status === 404 ? "No longer permitted." : res.status === 409 ? "Blocked by the antivirus." : `Download failed (${res.status}).`);
    const total = Number(res.headers.get("Content-Length")) || it.size || 0;
    let blob: Blob;
    if (res.body && total) {
      const reader = res.body.getReader();
      const chunks: BlobPart[] = [];
      let got = 0, lastPct = -1;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        got += value.length;
        const pct = Math.min(99, Math.floor((got / total) * 100));
        if (pct >= lastPct + 5) { lastPct = pct; patchItem(uid, it.document, { progress: pct }); }
      }
      blob = new Blob(chunks);
    } else {
      blob = await res.blob();
    }
    const cache = await caches.open(cacheName(uid));
    await cache.put(`/offline/${it.version}`, new Response(blob, { headers: { "Content-Type": base.mime || "application/octet-stream" } }));
    if (prev && prev.versionId !== it.version) await cache.delete(`/offline/${prev.versionId}`);
    patch(uid, (s) => ({ ...s, items: { ...s.items, [it.document]: { ...base, versionId: it.version, latestVersionId: undefined, size: blob.size || it.size,
      savedAt: new Date().toISOString(), status: "available", progress: undefined, error: undefined } } }));
    api("offline/audit", { body: { action: prev ? "update" : "save", documents: [it.document] } }).catch(() => undefined);
    return true;
  } catch (e: any) {
    const msg = e?.name === "QuotaExceededError" ? "Browser storage is full. Remove some offline copies first." : e?.message || "Download failed.";
    // an older copy stays usable when an update fails
    const keepOld = prev && prev.versionId !== it.version && (await hasBlob(uid, prev.versionId).catch(() => false));
    patch(uid, (s) => ({ ...s, items: { ...s.items, [it.document]: { ...base, versionId: keepOld ? prev!.versionId : it.version,
      latestVersionId: keepOld ? it.version : undefined, status: "failed", progress: undefined, error: msg } } }));
    return false;
  }
}

async function syncText(uid: string, docId: string, hash: string | null, allowed: boolean) {
  const local = current(uid).items[docId];
  if (!local) return;
  if (!allowed || !hash) {
    // never create the text cache just to delete from it (caches.open creates an empty bucket)
    if (local.text && (await caches.has(textCacheName(uid)))) await (await caches.open(textCacheName(uid))).delete(`/offline-text/${docId}`);
    if (local.text) patchItem(uid, docId, { text: null });
    return;
  }
  const cache = await caches.open(textCacheName(uid));
  if (local.text === hash) return;
  try {
    const r = await api<{ text: string }>(`documents/${docId}/text`, { query: { version: local.versionId } });
    await cache.put(`/offline-text/${docId}`, new Response(r.text || "", { headers: { "Content-Type": "text/plain; charset=utf-8" } }));
    patchItem(uid, docId, { text: hash });
  } catch { /* text is optional; the original stays available */ }
}

async function deleteCopy(uid: string, docId: string) {
  const it = current(uid).items[docId];
  if (it && offlineSupported()) {
    if (await caches.has(cacheName(uid))) await (await caches.open(cacheName(uid))).delete(`/offline/${it.versionId}`);
    if (await caches.has(textCacheName(uid))) await (await caches.open(textCacheName(uid))).delete(`/offline-text/${docId}`);
  }
  patch(uid, (s) => { const items = { ...s.items }; delete items[docId]; return { ...s, items }; });
  api("offline/audit", { body: { action: "remove", documents: [docId] } }).catch(() => undefined);
}

// ------------------------------------------------------------------ reading copies
export async function openOffline(uid: string, item: OfflineItem): Promise<string | null> {
  if (!offlineSupported() || isLocked(current(uid))) return null;
  const res = await (await caches.open(cacheName(uid))).match(`/offline/${item.versionId}`);
  return res ? URL.createObjectURL(await res.blob()) : null;
}

export async function offlineText(uid: string, docId: string): Promise<string | null> {
  if (!offlineSupported() || isLocked(current(uid))) return null;
  const res = await (await caches.open(textCacheName(uid))).match(`/offline-text/${docId}`);
  return res ? res.text() : null;
}

// ------------------------------------------------------------------ sign-out and clean-up
export const keepAfterSignOut = (uid: string) => { try { return localStorage.getItem(keepKey(uid)) === "1"; } catch { return false; } };
export const setKeepAfterSignOut = (uid: string, keep: boolean) => { try { localStorage.setItem(keepKey(uid), keep ? "1" : "0"); } catch { /* ignore */ } };

async function clearAll(uid: string, { keepDevice = true } = {}) {
  if (offlineSupported()) {
    await caches.delete(cacheName(uid));
    await caches.delete(textCacheName(uid));
  }
  const deviceId = keepDevice ? current(uid).deviceId : undefined;
  try {
    localStorage.removeItem(indexKey(uid));
    if (!keepDevice) localStorage.removeItem(deviceKey(uid));
  } catch { /* ignore */ }
  memory.set(uid, { ...empty(), deviceId });
  listeners.forEach((l) => l());
}

/** Called on sign-out. Follows the administrator's policy: always remove, or remove unless the person chose to
 *  keep their copies on this device. The device registration (an id, not a secret) is kept so the same device is
 *  recognised after signing in again. */
export async function onSignOut(uid: string) {
  // let a running sync finish first, so it cannot write copies back after they were removed
  if (running) await running.catch(() => undefined);
  const policy = current(uid).policy;
  if (policy?.logout_policy !== "always_clear" && keepAfterSignOut(uid)) return;
  await clearAll(uid);
}

/** Remove every offline copy of this account on this device and forget the device on the server. */
export async function forgetThisDevice(uid: string) {
  const id = current(uid).deviceId;
  if (id) await api(`offline/devices/${id}`, { method: "DELETE" }).catch(() => undefined);
  await clearAll(uid, { keepDevice: false });
}

/** Background sync: on start, when the connection returns and every 15 minutes while the app is visible. */
export function startAutoSync(uid: string): () => void {
  const st = current(uid);
  const hasAny = () => !!(current(uid).deviceId || Object.keys(current(uid).items).length);
  const run = () => { if (navigator.onLine && document.visibilityState === "visible" && hasAny()) syncNow(uid).catch(() => undefined); };
  if (st.deviceId || Object.keys(st.items).length) run();
  window.addEventListener("online", run);
  const t = window.setInterval(run, 15 * 60 * 1000);
  return () => { window.removeEventListener("online", run); window.clearInterval(t); };
}
