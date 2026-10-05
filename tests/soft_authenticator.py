"""A software WebAuthn authenticator (ES256, 'none' attestation) for tests.

Produces genuine registration and assertion responses that py_webauthn verifies cryptographically, so the
server-side passkey code is tested against the real protocol rather than mocks.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SoftAuthenticator:
    def __init__(self, origin: str, rp_id: str, *, discoverable: bool = True, uv: bool = True):
        self.origin, self.rp_id = origin, rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(32)
        self.sign_count = 0
        self.discoverable, self.uv = discoverable, uv
        self.user_handle = b""

    def _cose(self) -> bytes:
        nums = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})

    def _flags(self, attested: bool) -> int:
        return 0x01 | (0x04 if self.uv else 0) | (0x40 if attested else 0)

    def register(self, options: dict, origin: str | None = None) -> dict:
        self.user_handle = unb64u(options["user"]["id"])
        client = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": origin or self.origin,
                             "crossOrigin": False}).encode()
        auth_data = (hashlib.sha256(self.rp_id.encode()).digest() + bytes([self._flags(True)]) + struct.pack(">I", self.sign_count)
                     + b"\x00" * 16 + struct.pack(">H", len(self.cred_id)) + self.cred_id + self._cose())
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(client), "attestationObject": b64u(att), "transports": ["internal", "hybrid"]},
                "clientExtensionResults": {"credProps": {"rk": self.discoverable}}}

    def assert_(self, options: dict, origin: str | None = None, rp_id: str | None = None) -> dict:
        self.sign_count += 1
        client = json.dumps({"type": "webauthn.get", "challenge": options["challenge"], "origin": origin or self.origin,
                             "crossOrigin": False}).encode()
        auth_data = hashlib.sha256((rp_id or self.rp_id).encode()).digest() + bytes([self._flags(False)]) + struct.pack(">I", self.sign_count)
        sig = self.key.sign(auth_data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(client), "authenticatorData": b64u(auth_data), "signature": b64u(sig),
                             "userHandle": b64u(self.user_handle)}, "clientExtensionResults": {}}
