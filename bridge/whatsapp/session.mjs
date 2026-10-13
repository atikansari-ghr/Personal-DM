// Personal DM WhatsApp Personal bridge - session manager (EXPERIMENTAL, UNOFFICIAL, SELF-HOSTED).
//
// One bridge process, many isolated sessions (one per Personal DM person). This module holds the linking state
// machine and is kept free of HTTP and file-system details so it can be tested with a fake socket
// (bridge/whatsapp/test/session.test.mjs).
//
// Root cause of the 1.0.0 pairing failure ("the phone scans the QR, stays on Connecting, then fails"):
// after a successful scan WhatsApp sends pair-success and then closes the stream with 515 restartRequired; the
// client must open a NEW connection with the freshly issued credentials. 1.0.0 treated every close before the
// first "open" as an expired QR and returned without reconnecting, and its credentials were written to disk with
// a 500 ms delay but reloaded from disk on restart, so even a restart would have started from unregistered
// credentials. Here the 515 restart reuses the same in-memory credentials (flushed first), and the pairing is
// followed through every stage.

export const LINK_WINDOW_MS = 5 * 60 * 1000; // a link attempt stays valid for 5 minutes
export const PAIRING_TIMEOUT_MS = 90 * 1000; // scanned but never opened -> definitive failure
export const MAX_BACKOFF_MS = 5 * 60 * 1000;
export const SEND_LIMIT_PER_MIN = 30;
export const LINKS_PER_HOUR = 6;
export const VERIFY_TEXT = "✅ Personal DM: WhatsApp Personal is linked. Your notifications will arrive in this chat. " +
  "(Experimental, unofficial, self-hosted; notification-only.)";

// Pairing stages shown to the person, in order.
export const STAGES = ["qr_ready", "scanned", "connecting", "authenticating", "saving_session", "sending_verification"];

/**
 * @param {object} deps
 *   lib: { makeWASocket, DisconnectReason, jidNormalizedUser, Browsers? }
 *   store: { authState(id) -> { state, saveCreds, flush, hasCreds }, wipe(id), loadMeta(id), saveMeta(id, meta) }
 *   now(): ms clock; setTimer/clearTimer: timers (injectable for tests)
 */
export function createManager({ lib, store, now = () => Date.now(), setTimer = setTimeout, clearTimer = clearTimeout, socketOptions = {} }) {
  const { makeWASocket, DisconnectReason: R, jidNormalizedUser } = lib;
  const sessions = new Map();
  const events = []; // sanitized ring buffer: state names and status codes only, never QR, keys or numbers

  const note = (id, what, extra = {}) => {
    events.push({ at: new Date(now()).toISOString(), session: id.slice(0, 6), what, ...extra });
    if (events.length > 200) events.shift();
  };
  const clearTimers = (s) => { for (const k of ["linkTimer", "pairTimer", "retryTimer"]) { if (s[k]) clearTimer(s[k]); s[k] = null; } };
  const endSock = (s) => { const sock = s.sock; s.sock = null; s.gen += 1; try { sock?.end?.(undefined); } catch { /* closed */ } };
  const persistMeta = (s) => store.saveMeta(s.id, { verified_at: s.verifiedAt, linked_at: s.linkedAt, last_pairing_at: s.lastPairingAt,
    failure_stage: s.failureStage, error_code: s.errorCode });

  function session(id) {
    let s = sessions.get(id);
    if (!s) {
      const meta = store.loadMeta(id) || {};
      s = { id, gen: 0, sock: null, auth: null, state: "not_linked", stage: null, qr: null, qrAt: null, jid: null, paired: false,
        linkUntil: null, retries: 0, nextRetryAt: null, sent: [], links: [], verify: meta.verified_at ? "verified" : null,
        verifiedAt: meta.verified_at || null, linkedAt: meta.linked_at || null, lastPairingAt: meta.last_pairing_at || null,
        failureStage: meta.failure_stage || null, errorCode: meta.error_code ?? null, pairingRestarts: 0,
        linkTimer: null, pairTimer: null, retryTimer: null };
      sessions.set(id, s);
    }
    return s;
  }

  function openSocket(s) {
    endSock(s);
    const gen = s.gen;
    const auth = s.auth;
    const sock = makeWASocket({ auth: auth.state, ...socketOptions });
    s.sock = sock;
    sock.ev.on("creds.update", (...a) => { if (gen === s.gen) auth.saveCreds(...a); });
    sock.ev.on("connection.update", (u) => { if (gen === s.gen) onUpdate(s, sock, u); });
    // Deliberately no handler for incoming messages: the bridge never reads chats.
    return sock;
  }

  function onUpdate(s, sock, u) {
    if (u.qr && !s.paired && s.state !== "connected") {
      s.qr = u.qr; s.qrAt = now(); s.state = "pending"; s.stage = "qr_ready";
    }
    if (u.isNewLogin) { // pair-success: the phone accepted the QR code
      s.paired = true; s.qr = null; s.stage = "scanned"; s.state = "pending";
      clearTimer(s.linkTimer); s.linkTimer = null;
      s.pairTimer = setTimer(() => pairingFailed(s, "connecting", "timeout"), PAIRING_TIMEOUT_MS);
      note(s.id, "scanned");
    }
    if (u.connection === "connecting" && s.paired && s.stage === "connecting") s.stage = "authenticating";
    if (u.connection === "open") return onOpen(s, sock);
    if (u.connection === "close") return onClose(s, u.lastDisconnect?.error?.output?.statusCode);
  }

  function onOpen(s, sock) {
    clearTimers(s);
    const fresh = s.paired;
    s.qr = null; s.retries = 0; s.nextRetryAt = null; s.pairingRestarts = 0;
    s.jid = jidNormalizedUser(sock.user?.id || "");
    s.stage = "saving_session";
    s.auth.flush(); // credentials are on disk before anything else happens
    s.failureStage = null; s.errorCode = null;
    if (fresh) {
      s.paired = false; s.linkedAt = new Date(now()).toISOString(); s.verify = "pending"; s.verifiedAt = null;
      persistMeta(s);
      note(s.id, "linked");
      return verify(s);
    }
    s.state = "connected"; s.stage = null;
    note(s.id, "connected");
  }

  function onClose(s, code) {
    if (s.state === "link_expired" || s.state === "pairing_failed" || s.state === "not_linked") return;
    if (s.paired && !s.jid) {
      // between the scan and the first "open": only a definitive answer from WhatsApp is a failure
      if (code === R.restartRequired) {
        s.stage = "connecting";
        s.auth.flush();
        note(s.id, "restart after pairing", { code });
        openSocket(s);
        return;
      }
      if (code === R.loggedOut || code === R.forbidden || code === R.badSession || code === R.multideviceMismatch) {
        return pairingFailed(s, s.stage || "authenticating", code);
      }
      if (s.pairingRestarts < 3) { // transient during pairing: continue with the same credentials
        s.pairingRestarts += 1;
        note(s.id, "pairing reconnect", { code });
        openSocket(s);
        return;
      }
      return pairingFailed(s, s.stage || "connecting", code);
    }
    if (!s.jid) {
      // QR phase (nothing scanned yet). WhatsApp issues a handful of short-lived codes per connection; while the
      // 5-minute link window is open a new connection continues the same attempt.
      if (code === R.multideviceMismatch || code === 405) return incompatible(s, code);
      if (s.linkUntil && now() < s.linkUntil) {
        s.qr = null;
        s.retries += 1;
        if (s.retries > 12) return pairingFailed(s, "qr_ready", code);
        note(s.id, "new QR connection", { code });
        openSocket(s);
        return;
      }
      return linkExpired(s);
    }
    // a linked session
    s.state = "disconnected";
    if (code === R.loggedOut || code === R.forbidden || code === R.badSession) {
      clearTimers(s); endSock(s);
      s.state = "reconnect_required"; s.failureStage = "session"; s.errorCode = code ?? null; s.jid = null; s.verify = null;
      store.wipe(s.id); persistMeta(s);
      note(s.id, "authentication revoked", { code });
      return;
    }
    if (code === R.multideviceMismatch || code === 405) return incompatible(s, code);
    if (code === R.connectionReplaced) {
      clearTimers(s); endSock(s);
      note(s.id, "connection replaced", { code });
      return; // another connection took over: no automatic fight, the person presses Reconnect
    }
    if (code === R.restartRequired) { note(s.id, "restart", { code }); openSocket(s); return; }
    // temporary: reconnect with the stored session, controlled exponential back-off, never a new QR
    const delay = Math.min(MAX_BACKOFF_MS, 2000 * 2 ** Math.min(s.retries, 10));
    s.retries += 1;
    s.nextRetryAt = now() + delay;
    note(s.id, "temporary disconnection", { code, retry_in_s: Math.round(delay / 1000) });
    clearTimer(s.retryTimer);
    s.retryTimer = setTimer(() => { s.retryTimer = null; resume(s.id); }, delay);
  }

  function pairingFailed(s, stage, code) {
    clearTimers(s); endSock(s);
    s.state = "pairing_failed"; s.failureStage = stage; s.errorCode = code ?? null; s.qr = null; s.paired = false; s.jid = null;
    store.wipe(s.id); persistMeta(s);
    note(s.id, "pairing failed", { stage, code: code ?? null });
  }
  function linkExpired(s) {
    clearTimers(s); endSock(s);
    s.state = "link_expired"; s.qr = null; s.paired = false;
    store.wipe(s.id);
    note(s.id, "link window expired");
  }
  function incompatible(s, code) {
    clearTimers(s); endSock(s);
    s.state = "incompatible"; s.errorCode = code ?? null; s.qr = null;
    persistMeta(s);
    note(s.id, "protocol incompatibility", { code });
  }

  async function verify(s) {
    s.state = "pending"; s.stage = "sending_verification";
    try {
      await sendRaw(s, VERIFY_TEXT);
      s.verify = "verified"; s.verifiedAt = new Date(now()).toISOString();
      note(s.id, "verified");
    } catch (e) {
      s.verify = "failed";
      note(s.id, "verification failed", { error: String(e?.status || "send") });
    }
    s.state = "connected"; s.stage = null;
    persistMeta(s);
  }

  async function sendRaw(s, text) {
    if (!s.sock || !s.jid) throw Object.assign(new Error("not connected"), { status: 409 });
    const msg = await s.sock.sendMessage(s.jid, { text: String(text).slice(0, 3500) }); // to itself only
    return msg?.key?.id || "";
  }

  // ---------------------------------------------------------------- public API
  function link(id, { force = false } = {}) {
    const s = session(id);
    const t = now();
    const active = s.state === "pending" && (s.paired || (s.linkUntil && t < s.linkUntil));
    if (active && !force) return view(id); // the running attempt stays valid: no new QR every few seconds
    if (active && force && !s.paired) {
      const left = Math.ceil((s.linkUntil - t) / 1000);
      throw Object.assign(new Error(`The current QR code is still valid for ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}.`), { status: 409 });
    }
    if (s.state === "connected" && !force) return view(id);
    s.links = s.links.filter((x) => t - x < 3600000);
    if (s.links.length >= LINKS_PER_HOUR) throw Object.assign(new Error("Too many link attempts; try again later."), { status: 429 });
    s.links.push(t);
    clearTimers(s); endSock(s);
    store.wipe(id); // a new link always starts from fresh, unregistered credentials
    s.auth = store.authState(id);
    Object.assign(s, { state: "pending", stage: "qr_ready", qr: null, qrAt: null, jid: null, paired: false, retries: 0, pairingRestarts: 0,
      linkUntil: t + LINK_WINDOW_MS, lastPairingAt: new Date(t).toISOString(), failureStage: null, errorCode: null, verify: null,
      verifiedAt: null, nextRetryAt: null });
    persistMeta(s);
    s.linkTimer = setTimer(() => { if (s.state === "pending" && !s.paired) linkExpired(s); }, LINK_WINDOW_MS);
    note(id, "link started");
    openSocket(s);
    return view(id);
  }

  function resume(id) { // a stored session (restart of the bridge, temporary outage, Reconnect)
    const s = session(id);
    if (!store.hasCreds(id)) { if (s.state === "disconnected") s.state = "reconnect_required"; return view(id); }
    s.auth = store.authState(id);
    s.jid = s.jid || "stored";
    if (s.state !== "connected") s.state = "disconnected";
    openSocket(s);
    return view(id);
  }

  async function send(id, text) {
    const s = sessions.get(id);
    if (!s || s.state !== "connected") throw Object.assign(new Error("not connected"), { status: 409 });
    const t = now();
    s.sent = s.sent.filter((x) => t - x < 60000);
    if (s.sent.length >= SEND_LIMIT_PER_MIN) throw Object.assign(new Error("rate limited"), { status: 429 });
    s.sent.push(t);
    const ref = await sendRaw(s, text);
    if (s.verify !== "verified") { s.verify = "verified"; s.verifiedAt = new Date(t).toISOString(); persistMeta(s); }
    return ref;
  }

  async function unlink(id) {
    const s = sessions.get(id);
    if (s) {
      clearTimers(s);
      try { await s.sock?.logout?.(); } catch { /* already gone */ }
      endSock(s);
      sessions.delete(id);
    }
    store.wipe(id); store.saveMeta(id, null);
    note(id, "unlinked");
  }

  function view(id) {
    const s = sessions.get(id);
    if (!s) return { state: store.hasCreds(id) ? "disconnected" : "not_linked" };
    const t = now();
    const out = { state: s.state, stage: s.state === "pending" ? s.stage : null, verification: s.state === "connected" ? (s.verify || "pending") : null,
      number_hint: s.jid && s.jid !== "stored" ? s.jid.split("@")[0].split(":")[0].slice(-4) : "",
      failure_stage: s.failureStage, error_code: s.errorCode, verified_at: s.verifiedAt, last_pairing_at: s.lastPairingAt };
    if (s.state === "pending" && s.stage === "qr_ready") {
      out.qr = s.qr; // only while waiting for the scan; never logged or stored
      out.link_expires_in_s = s.linkUntil ? Math.max(0, Math.round((s.linkUntil - t) / 1000)) : null;
    }
    if (s.state === "disconnected" && s.nextRetryAt) out.next_retry_in_s = Math.max(0, Math.round((s.nextRetryAt - t) / 1000));
    return out;
  }

  function diagnostics() { // per-session state without secrets: no QR payload, no numbers, no keys
    const t = now();
    return [...sessions.values()].map((s) => ({ session: s.id, state: s.state, stage: s.state === "pending" ? s.stage : null,
      qr_age_s: s.qrAt && s.state === "pending" && s.stage === "qr_ready" ? Math.round((t - s.qrAt) / 1000) : null,
      link_expires_in_s: s.state === "pending" && s.linkUntil && !s.paired ? Math.max(0, Math.round((s.linkUntil - t) / 1000)) : null,
      last_pairing_at: s.lastPairingAt, failure_stage: s.failureStage, error_code: s.errorCode, retries: s.retries,
      verification: s.state === "connected" ? (s.verify || "pending") : null }));
  }

  function shutdown() { for (const s of sessions.values()) { clearTimers(s); try { s.auth?.flush(); } catch { /* closing */ } endSock(s); } }

  return { link, resume, send, unlink, view, diagnostics, events, shutdown, sessions, counts: () => {
    const c = {};
    for (const s of sessions.values()) c[s.state] = (c[s.state] || 0) + 1;
    return c;
  } };
}
