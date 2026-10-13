"""In-process fake of bridge/whatsapp/server.mjs (same HTTP API) for automated tests. No WhatsApp traffic.

Linking is simulated: POST /sessions returns a pending state with an obviously fake QR string; ``FakeBridge.connect``
marks a session connected (what scanning the QR with the phone would do)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeBridge:
    def __init__(self, token: str, port: int = 0):
        self.token = token
        self.sessions: dict[str, dict] = {}
        self.sent: list[tuple[str, str]] = []  # (session, text) - always to the session's own account
        self.fail_sends = False
        self.version = "1.1.0"
        self.protocol = 1
        self.down = False
        self.restarts = 0
        self.links = 0  # test-only: /health fails as if the service had stopped
        bridge = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _auth(self):
                return self.headers.get("Authorization") == f"Bearer {bridge.token}"

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def do_GET(self):
                if not self._auth():
                    return self._json(401, {"error": "unauthorised"})
                if self.path == "/diagnostics":
                    return self._json(200, {"version": bridge.version, "protocol": bridge.protocol, "library": "fake",
                                            "dns": {"ok": True}, "network": {"ok": True, "ms": 1}, "clock": {"ok": True, "skew_s": 0},
                                            "storage": {"ok": True},
                                            "sessions": [{"session": k, "state": v["state"], "stage": v.get("stage"),
                                                          "verification": v.get("verification")} for k, v in bridge.sessions.items()],
                                            "events": [{"at": "2026-10-13T00:00:00Z", "session": k[:6], "what": "link started"}
                                                       for k in bridge.sessions]})
                if self.path == "/health":
                    if bridge.down:
                        return self._json(503, {"error": "bridge stopped (test)"})
                    return self._json(200, {"ok": True, "version": bridge.version, "protocol": bridge.protocol, "library": "fake", "sessions": {}})
                sid = self.path.split("/")[2]
                s = bridge.sessions.get(sid)
                if not s:
                    return self._json(200, {"state": "not_linked"})
                out = {"state": s["state"], "number_hint": s.get("hint", ""), "stage": s.get("stage"),
                       "verification": s.get("verification"), "error_code": s.get("error_code"), "failure_stage": s.get("failure_stage")}
                if s["state"] == "pending" and s.get("stage") == "qr_ready":
                    out.update(qr="FAKE-QR-NOT-A-REAL-WHATSAPP-CODE", link_expires_in_s=287)
                return self._json(200, out)

            def do_POST(self):
                if not self._auth():
                    return self._json(401, {"error": "unauthorised"})
                parts = [p for p in self.path.split("/") if p]
                b = self._body()
                if len(parts) == 3 and parts[:2] == ["_test", "connect"]:  # test-only: what scanning the QR would do
                    for sid in ([k for k, v in bridge.sessions.items() if v["state"] == "pending"] if parts[2] == "pending" else [parts[2]]):
                        bridge.connect(sid)
                    return self._json(200, {"state": "connected"})
                if parts == ["_test", "health"]:  # test-only: simulate a stopped / restarted service
                    bridge.down = not b.get("up", True)
                    return self._json(200, {"down": bridge.down})
                if parts == ["_test", "stage"]:  # test-only: move a session (or every pending one) through the pairing stages
                    sids = [k for k, v in bridge.sessions.items() if v["state"] == "pending"] if b["session"] == "pending" else [b["session"]]
                    for sid in sids:
                        bridge.sessions[sid].update(state=b.get("state", "pending"), stage=b.get("stage"),
                                                    error_code=b.get("error_code"), failure_stage=b.get("failure_stage"))
                    return self._json(200, {"ok": True, "sessions": len(sids)})
                if parts == ["admin", "restart"]:
                    bridge.restarts += 1
                    return self._json(200, {"restarting": True})
                if parts == ["sessions"]:
                    cur = bridge.sessions.get(b["session"])
                    if cur and cur["state"] == "pending" and b.get("force") and cur.get("stage") == "qr_ready":
                        return self._json(409, {"error": "The current QR code is still valid for 4:47."})
                    if cur and cur["state"] in ("pending", "connected") and not b.get("force"):
                        return self._json(200, {"state": cur["state"], "stage": cur.get("stage")})
                    bridge.sessions[b["session"]] = {"state": "pending", "stage": "qr_ready"}
                    bridge.links += 1
                    return self._json(200, {"state": "pending", "stage": "qr_ready"})
                sid = parts[1]
                s = bridge.sessions.get(sid)
                if parts[2] == "send":
                    if "to" in b:  # the real bridge has no recipient parameter either
                        return self._json(400, {"error": "no recipient parameter"})
                    if not s or s["state"] != "connected" or bridge.fail_sends:
                        return self._json(409, {"error": "not connected"})
                    bridge.sent.append((sid, b["text"]))
                    s["verification"] = "verified"
                    return self._json(200, {"id": f"fake-{len(bridge.sent)}"})
                if parts[2] == "reconnect":
                    if not s or s.get("revoked"):
                        return self._json(200, {"state": "reconnect_required"})
                    s["state"] = "connected"
                    return self._json(200, {"state": "connected"})
                return self._json(404, {"error": "not found"})

            def do_DELETE(self):
                if not self._auth():
                    return self._json(401, {"error": "unauthorised"})
                bridge.sessions.pop(self.path.split("/")[2], None)
                return self._json(200, {"state": "not_linked"})

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        except OSError:  # the requested port is taken: any free one
            self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def connect(self, sid: str, hint: str = "0042", verification: str = "verified"):
        """What scanning the QR does with bridge 1.1.0: pairing completes and the verification message is sent."""
        self.sessions[sid] = {"state": "connected", "hint": hint, "verification": verification}

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()


if __name__ == "__main__":  # standalone for the browser tests: python tests/fake_whatsapp_bridge.py TOKEN PORTFILE [PORT]
    import signal
    import sys

    fb = FakeBridge(sys.argv[1], int(sys.argv[3]) if len(sys.argv) > 3 else 0)
    with open(sys.argv[2], "w") as fh:
        fh.write(str(fb.port))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    fb.server.serve_forever()
