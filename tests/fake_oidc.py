"""A minimal OpenID Connect provider (authentik-shaped) for tests: discovery, JWKS and token endpoints on 127.0.0.1.

The test plays the browser/user part: it reads the authorization redirect, calls ``authorize`` with the claims the
"user" should have, and passes the returned code to the app's callback. The token endpoint checks the client
secret (HTTP Basic), the redirect URI and the PKCE verifier like a real provider."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

CLIENT_ID, CLIENT_SECRET = "pdm-test-client", "test-secret-not-real"


class FakeOIDC:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "test-key-1"
        self.codes: dict[str, dict] = {}
        self.token_requests = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    @property
    def issuer(self) -> str:
        return f"{self.base}/application/o/personal-dm/"

    def discovery(self) -> dict:
        return {"issuer": self.issuer, "authorization_endpoint": f"{self.base}/application/o/authorize/",
                "token_endpoint": f"{self.base}/application/o/token/", "jwks_uri": f"{self.base}/application/o/personal-dm/jwks/",
                "userinfo_endpoint": f"{self.base}/application/o/userinfo/", "code_challenge_methods_supported": ["plain", "S256"],
                "response_types_supported": ["code"], "id_token_signing_alg_values_supported": ["RS256"]}

    def jwks(self) -> dict:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def id_token(self, claims: dict, nonce: str, **override) -> str:
        now = int(time.time())
        body = {"iss": self.issuer, "aud": CLIENT_ID, "iat": now, "exp": now + 300, "nonce": nonce, **claims, **override}
        return jwt.encode(body, self.key, algorithm="RS256", headers={"kid": self.kid})

    def authorize(self, authorize_url: str, claims: dict, **override) -> tuple[str, str]:
        """What authentik does after the user signs in: returns (code, state)."""
        q = {k: v[0] for k, v in parse_qs(urlparse(authorize_url).query).items()}
        assert q["client_id"] == CLIENT_ID and q["response_type"] == "code" and q["code_challenge_method"] == "S256"
        code = secrets.token_urlsafe(16)
        self.codes[code] = {"claims": claims, "nonce": q["nonce"], "challenge": q["code_challenge"],
                            "redirect_uri": q["redirect_uri"], "override": override}
        return code, q["state"]

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = urlparse(self.path).path
                if path.endswith("/.well-known/openid-configuration"):
                    return self._json(200, fake.discovery())
                if path.endswith("/jwks/"):
                    return self._json(200, fake.jwks())
                return self._json(404, {"error": "not_found"})

            def do_POST(self):
                fake.token_requests += 1
                length = int(self.headers.get("Content-Length", 0))
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
                auth = self.headers.get("Authorization", "")
                expected = "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
                if auth != expected:
                    return self._json(401, {"error": "invalid_client"})
                entry = fake.codes.pop(form.get("code", ""), None)
                if entry is None:
                    return self._json(400, {"error": "invalid_grant"})
                challenge = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                if challenge != entry["challenge"] or form.get("redirect_uri") != entry["redirect_uri"]:
                    return self._json(400, {"error": "invalid_grant"})
                return self._json(200, {"access_token": "at-" + secrets.token_hex(8), "token_type": "Bearer",
                                        "id_token": fake.id_token(entry["claims"], entry["nonce"], **entry["override"])})

        return H
