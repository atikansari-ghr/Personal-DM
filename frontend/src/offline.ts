// Explicit, opt-in offline copies. Partitioned per account; nothing is cached merely because it was viewed.
// Policy (documented in docs/guides/offline-export.md): copies are removed on sign-out unless the user chose
// "keep on this device"; they are only listed for the account that saved them; on reconnect the server is asked
// which copies are still permitted and revoked ones are deleted.
import { api } from "./api";

export interface OfflineItem {
  documentId: string;
  versionId: string;
  title: string;
  name: string;
  mime: string;
  size: number;
  savedAt: string;
  stale?: boolean;
}

const cacheName = (uid: string) => `pd-offline-${uid}`;
const indexKey = (uid: string) => `pd-offline-index-${uid}`;
const keepKey = (uid: string) => `pd-offline-keep-${uid}`;

export const offlineSupported = () => typeof caches !== "undefined";

export function listOffline(uid: string): OfflineItem[] {
  try {
    return JSON.parse(localStorage.getItem(indexKey(uid)) || "[]");
  } catch {
    return [];
  }
}
function writeIndex(uid: string, items: OfflineItem[]) {
  localStorage.setItem(indexKey(uid), JSON.stringify(items));
}

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

export async function saveOffline(uid: string, doc: { id: string; title: string; version_id: string | null }, version: { id: string; original_name: string; mime: string; size: number }) {
  if (!offlineSupported()) throw new Error("This browser does not support offline storage.");
  const info = await storageInfo();
  if (info.quota !== undefined && info.usage !== undefined && info.quota - info.usage < version.size * 1.1)
    throw new Error("Not enough browser storage on this device for this file.");
  await requestPersistence();
  const res = await fetch(`/api/documents/${doc.id}/file?download=1&version=${version.id}`, { credentials: "same-origin" });
  if (!res.ok) throw new Error(res.status === 403 ? "You do not have download permission." : "Download failed.");
  const cache = await caches.open(cacheName(uid));
  try {
    await cache.put(`/offline/${version.id}`, new Response(await res.blob(), { headers: { "Content-Type": version.mime || "application/octet-stream" } }));
  } catch (e: any) {
    if (e?.name === "QuotaExceededError") throw new Error("Browser storage is full. Remove some offline files first.");
    throw e;
  }
  const items = listOffline(uid).filter((i) => i.documentId !== doc.id);
  items.push({ documentId: doc.id, versionId: version.id, title: doc.title, name: version.original_name, mime: version.mime, size: version.size, savedAt: new Date().toISOString() });
  writeIndex(uid, items);
  api("offline/audit", { body: { action: "save", documents: [doc.id] } }).catch(() => undefined);
}

export async function removeOffline(uid: string, documentId: string) {
  const items = listOffline(uid);
  const item = items.find((i) => i.documentId === documentId);
  if (item && offlineSupported()) await (await caches.open(cacheName(uid))).delete(`/offline/${item.versionId}`);
  writeIndex(uid, items.filter((i) => i.documentId !== documentId));
  api("offline/audit", { body: { action: "remove", documents: [documentId] } }).catch(() => undefined);
}

export async function openOffline(uid: string, item: OfflineItem): Promise<string | null> {
  if (!offlineSupported()) return null;
  const res = await (await caches.open(cacheName(uid))).match(`/offline/${item.versionId}`);
  return res ? URL.createObjectURL(await res.blob()) : null;
}

/** Ask the server which copies are still permitted; delete revoked ones, flag stale ones. */
export async function revalidate(uid: string): Promise<{ revoked: number; stale: number }> {
  const items = listOffline(uid);
  if (!items.length) return { revoked: 0, stale: 0 };
  const res = await api<{ allowed: string[]; stale: string[]; revoked: string[] }>("offline/validate", { body: { versions: items.map((i) => i.versionId) } });
  for (const vid of res.revoked) {
    const it = items.find((i) => i.versionId === vid);
    if (it) await removeOffline(uid, it.documentId);
  }
  const kept = listOffline(uid).map((i) => ({ ...i, stale: res.stale.includes(i.versionId) }));
  writeIndex(uid, kept);
  return { revoked: res.revoked.length, stale: res.stale.length };
}

export const keepAfterSignOut = (uid: string) => localStorage.getItem(keepKey(uid)) === "1";
export const setKeepAfterSignOut = (uid: string, keep: boolean) => localStorage.setItem(keepKey(uid), keep ? "1" : "0");

/** Called on sign-out: removes this account's offline copies unless the user chose to keep them on this device. */
export async function onSignOut(uid: string) {
  if (keepAfterSignOut(uid)) return;
  if (offlineSupported()) await caches.delete(cacheName(uid));
  localStorage.removeItem(indexKey(uid));
}
