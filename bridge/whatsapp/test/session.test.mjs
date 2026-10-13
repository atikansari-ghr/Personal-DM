// Linking state machine of the WhatsApp Personal bridge, driven by a fake socket (no network, no WhatsApp).
// Run: cd bridge/whatsapp && node --test test/
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";
import { createManager, LINK_WINDOW_MS, PAIRING_TIMEOUT_MS, VERIFY_TEXT } from "../session.mjs";

const R = { loggedOut: 401, forbidden: 403, timedOut: 408, connectionLost: 408, multideviceMismatch: 411, connectionClosed: 428,
  connectionReplaced: 440, badSession: 500, unavailableService: 503, restartRequired: 515 };
const ID = "a".repeat(32), ID2 = "b".repeat(32);
const QR = "2@FAKE-TEST-QR-NOT-A-REAL-CODE";

function harness({ sendFails = false } = {}) {
  let t = 1_000_000;
  const timers = [];
  const sockets = [];
  const disk = {}; // id -> creds as last flushed
  const meta = {};
  const lib = {
    DisconnectReason: R,
    jidNormalizedUser: (j) => j.replace(/:\d+@/, "@"),
    makeWASocket: (opts) => {
      const sock = { ev: new EventEmitter(), opts, ended: false, sent: [], user: null,
        end() { this.ended = true; }, logout: async () => {},
        sendMessage: async (jid, m) => { if (sendFails) throw Object.assign(new Error("x"), { status: 500 }); sock.sent.push([jid, m.text]); return { key: { id: "m1" } }; } };
      sockets.push(sock);
      return sock;
    },
  };
  const store = {
    authState: (id) => {
      const creds = disk[id] ? { ...disk[id] } : { noiseKey: "k" };
      return { state: { creds, keys: {} }, saveCreds: () => {}, flush: () => { disk[id] = { ...creds }; } };
    },
    hasCreds: (id) => !!disk[id]?.me,
    wipe: (id) => { delete disk[id]; },
    loadMeta: (id) => meta[id] || null,
    saveMeta: (id, m) => { if (m === null) delete meta[id]; else meta[id] = m; },
  };
  const m = createManager({ lib, store, now: () => t,
    setTimer: (fn, ms) => { const h = { fn, at: t + ms, done: false }; timers.push(h); return h; },
    clearTimer: (h) => { if (h) h.done = true; } });
  const advance = (ms) => { t += ms; for (const h of timers) if (!h.done && h.at <= t) { h.done = true; h.fn(); } };
  const last = () => sockets[sockets.length - 1];
  const emit = (sock, u) => sock.ev.emit("connection.update", u);
  const close = (sock, code) => emit(sock, { connection: "close", lastDisconnect: { error: { output: { statusCode: code } } } });
  return { m, sockets, disk, meta, advance, last, emit, close };
}

async function pair(h, id = ID) {
  h.m.link(id);
  const s0 = h.last();
  h.emit(s0, { qr: QR });
  s0.opts.auth.creds.me = { id: "15550000042:7@s.whatsapp.net" }; // what pair-success writes into the credentials
  s0.ev.emit("creds.update", {});
  h.emit(s0, { isNewLogin: true, qr: undefined });
  h.close(s0, R.restartRequired);
  const s1 = h.last();
  h.emit(s1, { connection: "connecting" });
  s1.user = { id: "15550000042:7@s.whatsapp.net" };
  h.emit(s1, { connection: "open" });
  await new Promise((r) => setImmediate(r));
  return { s0, s1 };
}

test("scan -> 515 restartRequired -> new connection with the SAME fresh credentials -> linked and verified", async () => {
  const h = harness();
  h.m.link(ID);
  const s0 = h.last();
  h.emit(s0, { qr: QR });
  let v = h.m.view(ID);
  assert.equal(v.state, "pending"); assert.equal(v.stage, "qr_ready"); assert.equal(v.qr, QR);
  assert.equal(v.link_expires_in_s, LINK_WINDOW_MS / 1000);
  s0.opts.auth.creds.me = { id: "15550000042:7@s.whatsapp.net" };
  h.emit(s0, { isNewLogin: true, qr: undefined });
  v = h.m.view(ID);
  assert.equal(v.stage, "scanned"); assert.equal(v.qr, undefined, "no QR after the scan");
  h.close(s0, R.restartRequired); // what WhatsApp always does right after pair-success (1.0.0 ignored this)
  assert.equal(h.sockets.length, 2, "a new connection is opened");
  assert.ok(h.disk[ID]?.me, "credentials were flushed to disk before the restart");
  const s1 = h.last();
  assert.equal(s1.opts.auth.creds, s0.opts.auth.creds, "the restart reuses the in-memory credentials, not a stale file");
  assert.equal(h.m.view(ID).stage, "connecting");
  h.emit(s1, { qr: "2@SHOULD-BE-IGNORED" });
  assert.equal(h.m.view(ID).qr, undefined, "no QR churn while connecting");
  h.emit(s1, { connection: "connecting" });
  assert.equal(h.m.view(ID).stage, "authenticating");
  s1.user = { id: "15550000042:7@s.whatsapp.net" };
  h.emit(s1, { connection: "open" });
  await new Promise((r) => setImmediate(r));
  v = h.m.view(ID);
  assert.equal(v.state, "connected"); assert.equal(v.verification, "verified"); assert.equal(v.number_hint, "0042");
  assert.deepEqual(s1.sent, [["15550000042@s.whatsapp.net", VERIFY_TEXT]], "one verification message, to the person's own account");
  assert.ok(h.meta[ID].verified_at && h.meta[ID].linked_at);
});

test("a failed verification keeps the authenticated session (Linked - Test Failed)", async () => {
  const h = harness({ sendFails: true });
  await pair(h);
  const v = h.m.view(ID);
  assert.equal(v.state, "connected"); assert.equal(v.verification, "failed");
  assert.ok(h.disk[ID]?.me, "session not destroyed");
});

test("QR phase: a closed QR connection continues the same 5-minute attempt; then Link expired", () => {
  const h = harness();
  h.m.link(ID);
  h.emit(h.last(), { qr: QR });
  h.advance(160_000);
  h.close(h.last(), R.timedOut); // WhatsApp issues only a few codes per connection
  assert.equal(h.sockets.length, 2);
  assert.equal(h.m.view(ID).state, "pending");
  assert.equal(h.m.view(ID).link_expires_in_s, 140);
  h.advance(LINK_WINDOW_MS);
  const v = h.m.view(ID);
  assert.equal(v.state, "link_expired"); assert.equal(v.qr, undefined);
  assert.ok(h.last().ended);
});

test("the running link attempt is not regenerated; a new QR is refused until the window ends or the attempt failed", () => {
  const h = harness();
  h.m.link(ID);
  h.emit(h.last(), { qr: QR });
  h.m.link(ID);
  assert.equal(h.sockets.length, 1, "pressing Link again keeps the valid code");
  assert.throws(() => h.m.link(ID, { force: true }), (e) => e.status === 409 && /still valid for 5:00/.test(e.message));
  h.advance(LINK_WINDOW_MS + 1);
  assert.equal(h.m.view(ID).state, "link_expired");
  h.m.link(ID, { force: true });
  assert.equal(h.sockets.length, 2);
});

test("a definitive failure after the scan ends the attempt and allows a new QR at once", () => {
  const h = harness();
  h.m.link(ID);
  const s0 = h.last();
  h.emit(s0, { qr: QR });
  h.emit(s0, { isNewLogin: true });
  h.close(s0, R.loggedOut);
  const v = h.m.view(ID);
  assert.equal(v.state, "pairing_failed"); assert.equal(v.failure_stage, "scanned"); assert.equal(v.error_code, 401);
  assert.equal(h.disk[ID], undefined, "partial credentials removed");
  h.m.link(ID, { force: true });
  assert.equal(h.m.view(ID).stage, "qr_ready");
});

test("a pending connection is not a failure: transient closes during pairing continue; only the timeout fails", () => {
  const h = harness();
  h.m.link(ID);
  const s0 = h.last();
  h.emit(s0, { isNewLogin: true });
  h.close(s0, R.connectionClosed);
  assert.equal(h.m.view(ID).state, "pending");
  assert.equal(h.sockets.length, 2);
  h.advance(PAIRING_TIMEOUT_MS + 1);
  assert.equal(h.m.view(ID).state, "pairing_failed");
  assert.equal(h.m.view(ID).failure_stage, "connecting");
});

test("linked session: temporary outage reconnects with the stored session (no QR); revoked -> Relink Required", async () => {
  const h = harness();
  await pair(h);
  const n = h.sockets.length;
  h.close(h.last(), R.connectionLost);
  let v = h.m.view(ID);
  assert.equal(v.state, "disconnected"); assert.ok(v.next_retry_in_s > 0); assert.equal(v.qr, undefined);
  h.advance(2_500);
  assert.equal(h.sockets.length, n + 1, "reconnected after the back-off");
  h.close(h.last(), R.connectionLost);
  assert.equal(h.m.view(ID).next_retry_in_s, 4, "exponential back-off");
  h.advance(5_000);
  h.close(h.last(), R.loggedOut);
  v = h.m.view(ID);
  assert.equal(v.state, "reconnect_required");
  assert.equal(h.disk[ID], undefined);
  const before = h.sockets.length;
  h.advance(60 * 60 * 1000);
  assert.equal(h.sockets.length, before, "no futile retries after revocation");
});

test("protocol incompatibility stops retries and is reported", async () => {
  const h = harness();
  await pair(h);
  h.close(h.last(), R.multideviceMismatch);
  assert.equal(h.m.view(ID).state, "incompatible");
});

test("sessions are isolated; diagnostics and events never contain the QR code or the number", async () => {
  const h = harness();
  await pair(h, ID);
  h.m.link(ID2);
  h.emit(h.last(), { qr: QR });
  await h.m.unlink(ID2);
  assert.equal(h.m.view(ID2).state, "not_linked");
  assert.equal(h.m.view(ID).state, "connected");
  const text = JSON.stringify({ d: h.m.diagnostics(), e: h.m.events });
  assert.ok(!text.includes("FAKE-TEST-QR") && !text.includes("15550000042"));
});

test("sending is rate limited and only to the session's own account", async () => {
  const h = harness();
  const { s1 } = await pair(h);
  for (let i = 0; i < 30; i++) await h.m.send(ID, "x"); // 30 a minute; the verification message is not counted
  await assert.rejects(h.m.send(ID, "x"), (e) => e.status === 429);
  assert.ok(s1.sent.every(([jid]) => jid === "15550000042@s.whatsapp.net"));
});
