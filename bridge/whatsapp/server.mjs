// Personal Documents Management System - WhatsApp Personal bridge (EXPERIMENTAL, UNOFFICIAL, SELF-HOSTED).
// Not the WhatsApp Business Platform; not supported or endorsed by WhatsApp or Meta.
//
// Notification-only by design:
//   * listens on 127.0.0.1 only and requires the shared token in <config>/whatsapp-bridge.token;
//   * each session is one person's own WhatsApp account linked as a linked device (QR);
//   * the only message a session can send is a text to ITSELF (the "Message yourself" chat): there is no recipient
//     parameter, no composer, no bulk sending, no contact access, no reading of chats, no auto-replies;
//   * session credentials are kept per session in one file encrypted with AES-256-GCM (key derived from the shared
//     token and the session id with HKDF-SHA256); they never leave this process;
//   * reconnects are bounded (no infinite loops); a protocol/library incompatibility exits with code 3, which the
//     systemd unit does not restart (RestartPreventExitStatus=3), so Personal DM shows "Degraded".
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PKG = JSON.parse(fs.readFileSync(path.join(HERE, "package.json"), "utf8"));
const PROTOCOL = 1;
const PORT = Number(process.env.PD_WA_PORT || 8095);
const DATA = process.env.PD_WA_DATA || "/var/lib/personaldocs/whatsapp/sessions";
const TOKEN_FILE = process.env.PD_WA_TOKEN_FILE || "/etc/personaldocs/whatsapp-bridge.token";
const MAX_RETRIES = 5;
const SEND_LIMIT_PER_MIN = 30;

let baileys;
try {
  baileys = await import("@whiskeysockets/baileys");
} catch (e) {
  console.error("whatsapp-bridge: the pinned WhatsApp library is missing or incompatible:", e?.message);
  process.exit(3);
}
const { default: makeWASocket, initAuthCreds, BufferJSON, DisconnectReason, jidNormalizedUser, Browsers } = baileys;
if (typeof makeWASocket !== "function" || typeof initAuthCreds !== "function") {
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

// ------------------------------------------------------------------ encrypted per-session store
const validId = (id) => /^[a-f0-9]{32}$/.test(id || "");
const keyFor = (id) => Buffer.from(crypto.hkdfSync("sha256", Buffer.from(token || "selftest"), Buffer.alloc(0), Buffer.from(`pd-wa-session:${id}`), 32));
const fileFor = (id) => path.join(DATA, `${id}.enc`);

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
function wipe(id) { try { fs.unlinkSync(fileFor(id)); } catch { /* already gone */ } }

function authState(id) {
  const stored = load(id) || { creds: initAuthCreds(), keys: {} };
  let timer = null;
  const persist = () => { clearTimeout(timer); timer = setTimeout(() => save(id, stored), 500); };
  return {
    state: {
      creds: stored.creds,
      keys: {
        get: async (type, ids) => Object.fromEntries(ids.map((k) => [k, stored.keys[type]?.[k]]).filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, type === "app-state-sync-key" && v ? baileys.proto?.Message?.AppStateSyncKeyData?.fromObject?.(v) ?? v : v])),
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
}

// ------------------------------------------------------------------ sessions
const sessions = new Map(); // id -> { sock, state, qr, jid, retries, sent: [timestamps] }
const silent = { level: "silent", child() { return silent; }, trace() {}, debug() {}, info() {}, warn() {}, error() {}, fatal() {} };

async function start(id) {
  const prev = sessions.get(id);
  if (prev?.sock) { try { prev.sock.end(undefined); } catch { /* closed */ } }
  const auth = authState(id);
  const s = { state: "pending", qr: null, jid: null, retries: prev?.retries || 0, sent: prev?.sent || [], auth };
  sessions.set(id, s);
  const sock = makeWASocket({
    auth: auth.state, logger: silent, printQRInTerminal: false, browser: Browsers?.appropriate ? Browsers.appropriate("Personal DM") : ["Personal DM", "Chrome", "1.0"],
    syncFullHistory: false, markOnlineOnConnect: false, shouldSyncHistoryMessage: () => false, getMessage: async () => undefined,
    generateHighQualityLinkPreview: false,
  });
  s.sock = sock;
  sock.ev.on("creds.update", auth.saveCreds);
  sock.ev.on("connection.update", (u) => {
    if (u.qr) { s.qr = u.qr; s.state = "pending"; }
    if (u.connection === "open") {
      s.state = "connected"; s.qr = null; s.retries = 0;
      s.jid = jidNormalizedUser(sock.user?.id || "");
      auth.flush();
    }
    if (u.connection === "close") {
      const code = u.lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut || code === 401) {
        s.state = "reconnect_required"; s.qr = null; wipe(id); return;
      }
      if (code === DisconnectReason.badSession || code === 500) { s.state = "degraded"; return; }
      if (s.state === "pending" && !s.jid) return; // QR expired: the person presses Link again
      if (s.retries < MAX_RETRIES) {
        s.retries += 1;
        s.state = "disconnected";
        setTimeout(() => start(id).catch(() => { s.state = "degraded"; }), Math.min(60000, 2000 * 2 ** s.retries));
      } else {
        s.state = "degraded"; // bounded: no infinite reconnect loop
      }
    }
  });
  // Deliberately no handler for incoming messages: the bridge never reads chats.
  return s;
}

function view(id) {
  const s = sessions.get(id);
  if (!s) return { state: fs.existsSync(fileFor(id)) ? "disconnected" : "not_linked" };
  return { state: s.state, qr: s.state === "pending" ? s.qr : null, number_hint: s.jid ? s.jid.split("@")[0].slice(-4) : "" };
}

async function sendSelf(id, text) {
  const s = sessions.get(id);
  if (!s || s.state !== "connected" || !s.jid) throw Object.assign(new Error("not connected"), { status: 409 });
  const now = Date.now();
  s.sent = s.sent.filter((t) => now - t < 60000);
  if (s.sent.length >= SEND_LIMIT_PER_MIN) throw Object.assign(new Error("rate limited"), { status: 429 });
  s.sent.push(now);
  const msg = await s.sock.sendMessage(s.jid, { text: String(text).slice(0, 3500) }); // to itself only
  return msg?.key?.id || "";
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
      const counts = {};
      for (const s of sessions.values()) counts[s.state] = (counts[s.state] || 0) + 1;
      return json(res, 200, { ok: true, version: PKG.version, protocol: PROTOCOL, library: `@whiskeysockets/baileys@${LIB_VERSION}`, sessions: counts });
    }
    if (parts[0] !== "sessions") return json(res, 404, { error: "not found" });
    if (req.method === "POST" && parts.length === 1) {
      const { session } = await body(req);
      if (!validId(session)) return json(res, 400, { error: "invalid session id" });
      await start(session);
      return json(res, 200, view(session));
    }
    const id = parts[1];
    if (!validId(id)) return json(res, 400, { error: "invalid session id" });
    if (req.method === "GET" && parts.length === 2) return json(res, 200, view(id));
    if (req.method === "POST" && parts[2] === "send") {
      const { text } = await body(req);
      if (!text) return json(res, 400, { error: "text required" });
      return json(res, 200, { id: await sendSelf(id, text) });
    }
    if (req.method === "POST" && parts[2] === "reconnect") {
      if (!fs.existsSync(fileFor(id))) return json(res, 200, { state: "reconnect_required" });
      const s = await start(id);
      await new Promise((r) => setTimeout(r, 4000));
      return json(res, 200, view(id) || { state: s.state });
    }
    if (req.method === "DELETE" && parts.length === 2) {
      const s = sessions.get(id);
      if (s?.sock) { try { await s.sock.logout(); } catch { /* already gone */ } }
      sessions.delete(id);
      wipe(id);
      return json(res, 200, { state: "not_linked" });
    }
    return json(res, 404, { error: "not found" });
  } catch (e) {
    return json(res, e.status || 500, { error: e.status ? e.message : "bridge error" });
  }
});

if (process.argv.includes("--selftest")) {
  // Offline self-test: library loads, encryption round-trips, no network needed.
  const id = crypto.randomBytes(16).toString("hex");
  save(id, { creds: initAuthCreds(), keys: { a: { b: 1 } } });
  const back = load(id);
  wipe(id);
  const ok = back?.keys?.a?.b === 1 && !!back?.creds?.noiseKey;
  console.log(JSON.stringify({ ok, version: PKG.version, protocol: PROTOCOL, library: LIB_VERSION }));
  process.exit(ok ? 0 : 1);
}

// Resume linked sessions on start (bounded retries per session).
for (const f of fs.readdirSync(DATA)) {
  const id = f.replace(/\.enc$/, "");
  if (validId(id)) start(id).catch(() => {});
}
server.listen(PORT, "127.0.0.1", () => console.log(`whatsapp-bridge ${PKG.version} (protocol ${PROTOCOL}) on 127.0.0.1:${PORT}`));
process.on("SIGTERM", () => { for (const s of sessions.values()) { try { s.auth.flush(); s.sock?.end(undefined); } catch { /* closing */ } } process.exit(0); });
