// Personal Documents Management System - WhatsApp Personal bridge (EXPERIMENTAL, UNOFFICIAL, SELF-HOSTED).
// Not the WhatsApp Business Platform; not supported or endorsed by WhatsApp or Meta.
//
// Notification-only by design:
//   * listens on 127.0.0.1 only and requires the shared token in <config>/whatsapp-bridge.token;
//   * one process, many isolated sessions: each is one person's own WhatsApp account linked as a linked device;
//   * the only message a session can send is a text to ITSELF (the "Message yourself" chat): there is no recipient
//     parameter, no composer, no bulk sending, no contact access, no reading of chats, no auto-replies;
//   * session credentials are kept per session in one file encrypted with AES-256-GCM (key derived from the shared
//     token and the session id with HKDF-SHA256); they never leave this process and are never logged;
//   * the linking state machine (session.mjs) follows WhatsApp's pairing flow, including the mandatory restart
//     after the scan; temporary outages reconnect with the stored session and a capped back-off.
import crypto from "node:crypto";
import dns from "node:dns";
import fs from "node:fs";
import http from "node:http";
import https from "node:https";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createManager } from "./session.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PKG = JSON.parse(fs.readFileSync(path.join(HERE, "package.json"), "utf8"));
const PROTOCOL = 1; // HTTP contract with Personal DM (unchanged; 1.1.0 only adds fields and /diagnostics)
const PORT = Number(process.env.PD_WA_PORT || 8095);
const DATA = process.env.PD_WA_DATA || "/var/lib/personaldocs/whatsapp/sessions";
const TOKEN_FILE = process.env.PD_WA_TOKEN_FILE || "/etc/personaldocs/whatsapp-bridge.token";
const STARTED = Date.now();

let baileys;
try {
  baileys = await import("@whiskeysockets/baileys");
} catch (e) {
  console.error("whatsapp-bridge: the pinned WhatsApp library is missing or incompatible:", e?.message);
  process.exit(3);
}
const makeWASocket = baileys.makeWASocket || baileys.default;
const { initAuthCreds, BufferJSON, DisconnectReason, jidNormalizedUser, Browsers, proto } = baileys;
if (typeof makeWASocket !== "function" || typeof initAuthCreds !== "function" || !DisconnectReason?.restartRequired) {
  console.error("whatsapp-bridge: unexpected library API; refusing to start");
  process.exit(3);
}
const LIB_VERSION = (() => {
  try {
    return JSON.parse(fs.readFileSync(path.join(HERE, "node_modules/@whiskeysockets/baileys/package.json"), "utf8")).version;
  } catch { return "unknown"; }
})();

const token = (() => { try { return fs.readFileSync(TOKEN_FILE, "utf8").trim(); } catch { return ""; } })();
if (!token && !process.argv.includes("--selftest")) {
  console.error(`whatsapp-bridge: ${TOKEN_FILE} is missing (run: sudo personaldocs whatsapp-bridge install)`);
  process.exit(2);
}
fs.mkdirSync(DATA, { recursive: true, mode: 0o700 });

// ------------------------------------------------------------------ encrypted per-session store (format unchanged since 1.0.0)
const validId = (id) => /^[a-f0-9]{32}$/.test(id || "");
const keyFor = (id) => Buffer.from(crypto.hkdfSync("sha256", Buffer.from(token || "selftest"), Buffer.alloc(0), Buffer.from(`pd-wa-session:${id}`), 32));
const fileFor = (id) => path.join(DATA, `${id}.enc`);
const metaFor = (id) => path.join(DATA, `${id}.meta.json`);

function load(id) {
  try {
    const raw = fs.readFileSync(fileFor(id));
    const iv = raw.subarray(0, 12), tag = raw.subarray(12, 28), ct = raw.subarray(28);
    const d = crypto.createDecipheriv("aes-256-gcm", keyFor(id), iv);
    d.setAuthTag(tag);
    return JSON.parse(Buffer.concat([d.update(ct), d.final()]).toString("utf8"), BufferJSON.reviver);
  } catch { return null; }
}
function save(id, data) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv("aes-256-gcm", keyFor(id), iv);
  const ct = Buffer.concat([c.update(JSON.stringify(data, BufferJSON.replacer), "utf8"), c.final()]);
  const tmp = fileFor(id) + ".tmp";
  fs.writeFileSync(tmp, Buffer.concat([iv, c.getAuthTag(), ct]), { mode: 0o600 });
  fs.renameSync(tmp, fileFor(id));
}

const store = {
  authState(id) {
    const stored = load(id) || { creds: initAuthCreds(), keys: {} };
    let timer = null;
    const persist = () => { clearTimeout(timer); timer = setTimeout(() => save(id, stored), 500); };
    return {
      state: {
        creds: stored.creds,
        keys: {
          get: async (type, ids) => Object.fromEntries(ids.map((k) => [k, stored.keys[type]?.[k]]).filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, type === "app-state-sync-key" && v ? proto.Message.AppStateSyncKeyData.fromObject(v) : v])),
          set: async (data) => {
            for (const type of Object.keys(data)) {
              stored.keys[type] = stored.keys[type] || {};
              for (const k of Object.keys(data[type])) {
                if (data[type][k] == null) delete stored.keys[type][k];
                else stored.keys[type][k] = data[type][k];
              }
            }
            persist();
          },
        },
      },
      saveCreds: async () => persist(),
      flush: () => { clearTimeout(timer); save(id, stored); },
    };
  },
  hasCreds: (id) => !!load(id)?.creds?.me,
  wipe: (id) => { try { fs.unlinkSync(fileFor(id)); } catch { /* already gone */ } },
  loadMeta: (id) => { try { return JSON.parse(fs.readFileSync(metaFor(id), "utf8")); } catch { return null; } },
  saveMeta: (id, meta) => {
    try {
      if (meta === null) fs.unlinkSync(metaFor(id));
      else fs.writeFileSync(metaFor(id), JSON.stringify(meta), { mode: 0o600 }); // states and times only, no secrets
    } catch { /* best effort */ }
  },
};

const silent = { level: "silent", child() { return silent; }, trace() {}, debug() {}, info() {}, warn() {}, error() {}, fatal() {} };
const manager = createManager({
  lib: { makeWASocket, DisconnectReason, jidNormalizedUser },
  store,
  socketOptions: {
    logger: silent, printQRInTerminal: false,
    // a standard desktop browser identity (WhatsApp shows "Chrome (Ubuntu)" under Linked devices)
    browser: Browsers?.ubuntu ? Browsers.ubuntu("Chrome") : ["Ubuntu", "Chrome", "22.04.4"],
    syncFullHistory: false, markOnlineOnConnect: false, shouldSyncHistoryMessage: () => false, getMessage: async () => undefined,
    generateHighQualityLinkPreview: false, fireInitQueries: false,
  },
});

// ------------------------------------------------------------------ diagnostics (safe: no QR, keys, numbers or addresses)
const withTimeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), ms))]);
async function diagnostics() {
  const out = { version: PKG.version, protocol: PROTOCOL, library: `@whiskeysockets/baileys@${LIB_VERSION}`, node: process.versions.node,
    uptime_s: Math.round((Date.now() - STARTED) / 1000) };
  try { await withTimeout(dns.promises.lookup("web.whatsapp.com"), 5000); out.dns = { ok: true }; }
  catch (e) { out.dns = { ok: false, error: e.code || e.message }; }
  try {
    const t0 = Date.now();
    const date = await withTimeout(new Promise((resolve, reject) => {
      const req = https.request({ method: "HEAD", host: "web.whatsapp.com", path: "/", timeout: 6000 }, (res) => { res.resume(); resolve(res.headers.date); });
      req.on("error", reject); req.on("timeout", () => req.destroy(new Error("timeout"))); req.end();
    }), 8000);
    out.network = { ok: true, ms: Date.now() - t0, note: "HTTPS to web.whatsapp.com (the WebSocket uses the same host and port 443)" };
    const skew = date ? Math.round((Date.now() - Date.parse(date)) / 1000) : null;
    out.clock = skew === null ? { ok: null } : { ok: Math.abs(skew) < 60, skew_s: skew };
  } catch (e) {
    out.network = { ok: false, error: e.code || e.message };
    out.clock = { ok: null };
  }
  try {
    const probe = path.join(DATA, `.write-test-${process.pid}`);
    fs.writeFileSync(probe, "ok", { mode: 0o600 }); fs.unlinkSync(probe);
    out.storage = { ok: true };
  } catch (e) { out.storage = { ok: false, error: e.code || "not writable" }; }
  out.sessions = manager.diagnostics();
  out.events = manager.events.slice(-50);
  return out;
}

// ------------------------------------------------------------------ HTTP API (loopback only)
const json = (res, status, body) => { res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" }); res.end(JSON.stringify(body)); };
const authorised = (req) => {
  const got = Buffer.from((req.headers.authorization || "").replace(/^Bearer /, ""));
  const want = Buffer.from(token);
  return token && got.length === want.length && crypto.timingSafeEqual(got, want);
};
async function body(req) {
  let raw = "";
  for await (const chunk of req) { raw += chunk; if (raw.length > 16384) throw Object.assign(new Error("too large"), { status: 413 }); }
  return raw ? JSON.parse(raw) : {};
}

const server = http.createServer(async (req, res) => {
  try {
    if (!authorised(req)) return json(res, 401, { error: "unauthorised" });
    const url = new URL(req.url, "http://127.0.0.1");
    const parts = url.pathname.split("/").filter(Boolean);
    if (req.method === "GET" && url.pathname === "/health") {
      return json(res, 200, { ok: true, version: PKG.version, protocol: PROTOCOL, library: `@whiskeysockets/baileys@${LIB_VERSION}`, sessions: manager.counts() });
    }
    if (req.method === "GET" && url.pathname === "/diagnostics") return json(res, 200, await diagnostics());
    if (req.method === "POST" && url.pathname === "/admin/restart") {
      json(res, 200, { restarting: true });
      setTimeout(() => { manager.shutdown(); process.exit(75); }, 300); // systemd restarts the unit (Restart=on-failure)
      return;
    }
    if (parts[0] !== "sessions") return json(res, 404, { error: "not found" });
    if (req.method === "POST" && parts.length === 1) {
      const { session, force } = await body(req);
      if (!validId(session)) return json(res, 400, { error: "invalid session id" });
      return json(res, 200, manager.link(session, { force: !!force }));
    }
    const id = parts[1];
    if (!validId(id)) return json(res, 400, { error: "invalid session id" });
    if (req.method === "GET" && parts.length === 2) return json(res, 200, manager.view(id));
    if (req.method === "POST" && parts[2] === "send") {
      const b = await body(req);
      if ("to" in b) return json(res, 400, { error: "no recipient parameter" }); // a session can only message itself
      if (!b.text) return json(res, 400, { error: "text required" });
      return json(res, 200, { id: await manager.send(id, b.text) });
    }
    if (req.method === "POST" && parts[2] === "reconnect") {
      if (!store.hasCreds(id)) return json(res, 200, { state: "reconnect_required" });
      manager.resume(id);
      await new Promise((r) => setTimeout(r, 4000));
      return json(res, 200, manager.view(id));
    }
    if (req.method === "DELETE" && parts.length === 2) {
      await manager.unlink(id);
      return json(res, 200, { state: "not_linked" });
    }
    return json(res, 404, { error: "not found" });
  } catch (e) {
    return json(res, e.status || 500, { error: e.status ? e.message : "bridge error" });
  }
});

if (process.argv.includes("--selftest")) {
  // Offline self-test: library loads, encryption round-trips, the state machine module loads; no network needed.
  const id = crypto.randomBytes(16).toString("hex");
  save(id, { creds: initAuthCreds(), keys: { a: { b: 1 } } });
  const back = load(id);
  store.wipe(id);
  const ok = back?.keys?.a?.b === 1 && !!back?.creds?.noiseKey && typeof createManager === "function";
  console.log(JSON.stringify({ ok, version: PKG.version, protocol: PROTOCOL, library: LIB_VERSION }));
  process.exit(ok ? 0 : 1);
}

// Resume linked sessions on start (temporary failures retry with a capped back-off; revoked ones become Relink Required).
for (const f of fs.readdirSync(DATA)) {
  const m = f.match(/^([a-f0-9]{32})\.enc$/);
  if (m && store.hasCreds(m[1])) { try { manager.resume(m[1]); } catch { /* reported in diagnostics */ } }
}
server.listen(PORT, "127.0.0.1", () => console.log(`whatsapp-bridge ${PKG.version} (protocol ${PROTOCOL}, ${LIB_VERSION}) on 127.0.0.1:${PORT}`));
process.on("SIGTERM", () => { manager.shutdown(); process.exit(0); });
