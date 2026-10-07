/// <reference lib="webworker" />
// Service worker: caches only the static app shell. API responses, documents, previews and public share
// pages are NEVER put into runtime caches. Explicit offline copies are managed by the page (offline.ts).
// It also receives files shared from the OS share sheet (Web Share Target, where supported).
const sw = self as unknown as ServiceWorkerGlobalScope;
const SHELL = "pd-shell-v1";
const INBOX = "pd-share-inbox";

sw.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", "/manifest.webmanifest", "/icon.svg", "/theme-hint.js"])).then(() => sw.skipWaiting()));
});

sw.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith("pd-shell-") && k !== SHELL).map((k) => caches.delete(k)))).then(() => sw.clients.claim()),
  );
});

sw.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== sw.location.origin) return;
  if (event.request.method === "POST" && url.pathname === "/upload-shared") {
    event.respondWith(receiveShare(event.request));
    return;
  }
  if (event.request.method !== "GET") return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/s/") || url.pathname.startsWith("/offline/")) return; // never cached
  if (url.pathname.startsWith("/static/")) {
    // hashed, immutable build assets: cache-first
    event.respondWith(
      caches.open(SHELL).then(async (c) => {
        const hit = await c.match(event.request);
        if (hit) return hit;
        const res = await fetch(event.request);
        if (res.ok) c.put(event.request, res.clone());
        return res;
      }),
    );
    return;
  }
  if (event.request.mode === "navigate") {
    // network-first for the SPA shell; fall back to the cached shell when offline
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          if (res.ok) caches.open(SHELL).then((c) => c.put("/", res.clone()));
          return res;
        })
        .catch(async () => (await caches.match("/")) || Response.error()),
    );
  }
});

async function receiveShare(request: Request): Promise<Response> {
  const form = await request.formData();
  const cache = await caches.open(INBOX);
  const files = form.getAll("files").filter((f): f is File => f instanceof File);
  let i = 0;
  for (const f of files.slice(0, 20)) {
    await cache.put(`/share-inbox/${Date.now()}-${i++}`, new Response(f, { headers: { "Content-Type": f.type || "application/octet-stream", "X-Filename": encodeURIComponent(f.name) } }));
  }
  return Response.redirect("/upload-shared?received=" + files.length, 303);
}

// ------------------------------------------------------------------ Web Push (Change Set O)
// The server sends only a short title/body and an application path; nothing sensitive is shown on the lock screen.
sw.addEventListener("push", (event) => {
  let data: { title?: string; body?: string; url?: string; tag?: string; severity?: string } = {};
  try { data = event.data?.json() ?? {}; } catch { data = { body: event.data?.text() }; }
  const title = data.title || "Personal Documents";
  event.waitUntil(sw.registration.showNotification(title, {
    body: data.body || "Open the app to read the notification.",
    icon: "/icon-192.png", badge: "/icon-192.png", tag: data.tag || undefined,
    requireInteraction: data.severity === "critical",
    data: { url: typeof data.url === "string" && data.url.startsWith("/") && !data.url.startsWith("//") ? data.url : "/notifications" },
  }));
});

sw.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const path: string = event.notification.data?.url || "/notifications";
  const target = new URL(path, sw.location.origin);
  if (target.origin !== sw.location.origin) return; // only pages of this app; sign-in and permissions apply there
  event.waitUntil((async () => {
    const wins = await sw.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) {
      if (new URL(w.url).origin === sw.location.origin && "focus" in w) {
        await (w as WindowClient).navigate(target.href).catch(() => undefined);
        return (w as WindowClient).focus();
      }
    }
    return sw.clients.openWindow(target.href);
  })());
});
