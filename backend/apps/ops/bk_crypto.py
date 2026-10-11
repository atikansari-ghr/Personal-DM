"""Encryption of recovery packages. Established primitives only (``cryptography``): AES-256-GCM, HKDF-SHA256, scrypt.

Key hierarchy (ADR 0020):
    Recovery Key (256-bit random, one per generation, shown to the main administrator)
      └─ KEK  = HKDF-SHA256(recovery key, info="personaldocs-backup-kek-v1")
           └─ wraps a random 256-bit data key (DEK) per recovery point  (AES-GCM, AAD = point id)
                └─ file key = HKDF-SHA256(DEK, info="pdbk-file:" + file name)   (one key per file)

Files are encrypted as a stream of 1 MiB chunks with the STREAM construction (Hoang et al., 2015): the nonce of a chunk
is a 7-byte random prefix, a 4-byte big-endian counter and a 1-byte "last chunk" flag. Reordering, truncation or
appending chunks therefore fails authentication. Nothing is compressed before encryption (original representations
are kept; pg_dump runs with ``-Z0``).

File format: b"PDBK2\\n" + 7-byte nonce prefix + chunks (ciphertext + 16-byte tag each). A plain-text length that is
a multiple of the chunk size ends with an empty final chunk, so a full-size chunk is never the last one.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import BinaryIO, Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"PDBK2\n"
CHUNK = 1024 * 1024
TAG = 16
KEY_PREFIX = "PDRK1"


class DecryptError(Exception):
    """Wrong key, corrupted or truncated data. Never contains plain text."""


# ------------------------------------------------------------------ recovery key text form

def new_recovery_key() -> bytes:
    return secrets.token_bytes(32)


def format_key(raw: bytes) -> str:
    """PDRK1-XXXX-XXXX-… (base32, groups of four, easy to read aloud and type)."""
    b32 = base64.b32encode(raw).decode().rstrip("=")
    return KEY_PREFIX + "-" + "-".join(b32[i:i + 4] for i in range(0, len(b32), 4))


def parse_key(text: str) -> bytes:
    t = "".join(ch for ch in (text or "").upper() if ch.isalnum())
    if t.startswith(KEY_PREFIX):
        t = t[len(KEY_PREFIX):]
    try:
        raw = base64.b32decode(t + "=" * (-len(t) % 8))
    except Exception as exc:  # noqa: BLE001
        raise DecryptError("This is not a Backup Recovery Key (expected PDRK1-…).") from exc
    if len(raw) != 32:
        raise DecryptError("This is not a Backup Recovery Key (wrong length).")
    return raw


def fingerprint(raw: bytes) -> str:
    """Non-secret identifier: lets a person check they hold the right key without revealing it."""
    return hashlib.sha256(b"pdrk-fingerprint:" + raw).hexdigest()[:12]


# ------------------------------------------------------------------ key derivation and wrapping

def _hkdf(key: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(key)


def kek(recovery_key: bytes) -> bytes:
    return _hkdf(recovery_key, b"personaldocs-backup-kek-v1")


def wrap_dek(recovery_key: bytes, dek: bytes, point_id: str) -> dict:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(kek(recovery_key)).encrypt(nonce, dek, point_id.encode())
    return {"alg": "AES-256-GCM/HKDF-SHA256", "nonce": base64.b64encode(nonce).decode(), "wrapped": base64.b64encode(ct).decode()}


def unwrap_dek(recovery_key: bytes, wrapped: dict, point_id: str) -> bytes:
    try:
        return AESGCM(kek(recovery_key)).decrypt(base64.b64decode(wrapped["nonce"]), base64.b64decode(wrapped["wrapped"]),
                                                 point_id.encode())
    except (InvalidTag, KeyError, ValueError) as exc:
        raise DecryptError("The Recovery Key does not open this backup (wrong key or key generation).") from exc


def file_key(dek: bytes, name: str) -> bytes:
    return _hkdf(dek, b"pdbk-file:" + name.encode())


# ------------------------------------------------------------------ streaming encryption

def _nonce(prefix: bytes, counter: int, last: bool) -> bytes:
    return prefix + counter.to_bytes(4, "big") + (b"\x01" if last else b"\x00")


def encrypt_stream(chunks: Iterator[bytes], out: BinaryIO, key: bytes, aad: bytes) -> tuple[int, str, int]:
    """Encrypt an iterator of plain-text blocks into ``out``. Returns (plain bytes, plain sha256, cipher bytes).
    Memory use is bounded by one chunk."""
    aes = AESGCM(key)
    prefix = secrets.token_bytes(7)
    out.write(MAGIC + prefix)
    written = len(MAGIC) + 7
    h = hashlib.sha256()
    total = 0
    counter = 0
    buf = b""
    for block in chunks:
        if not block:
            continue
        h.update(block)
        total += len(block)
        buf += block
        while len(buf) > CHUNK:  # keep at least one byte back so the true last chunk is flagged
            ct = aes.encrypt(_nonce(prefix, counter, False), buf[:CHUNK], aad)
            out.write(ct)
            written += len(ct)
            buf = buf[CHUNK:]
            counter += 1
    if len(buf) == CHUNK:
        ct = aes.encrypt(_nonce(prefix, counter, False), buf, aad)
        out.write(ct)
        written += len(ct)
        buf = b""
        counter += 1
    ct = aes.encrypt(_nonce(prefix, counter, True), buf, aad)
    out.write(ct)
    written += len(ct)
    return total, h.hexdigest(), written


def decrypt_stream(src: BinaryIO, key: bytes, aad: bytes) -> Iterator[bytes]:
    """Yield authenticated plain-text chunks. Raises DecryptError on any tampering, truncation or wrong key."""
    head = src.read(len(MAGIC) + 7)
    if len(head) != len(MAGIC) + 7 or not head.startswith(MAGIC):
        raise DecryptError("Not an encrypted recovery-package file (bad header).")
    prefix = head[len(MAGIC):]
    aes = AESGCM(key)
    counter = 0
    block = src.read(CHUNK + TAG)
    while True:
        nxt = src.read(CHUNK + TAG) if len(block) == CHUNK + TAG else b""
        last = len(block) < CHUNK + TAG
        if len(block) < TAG:
            raise DecryptError("The file is truncated.")
        try:
            pt = aes.decrypt(_nonce(prefix, counter, last), block, aad)
        except InvalidTag as exc:
            raise DecryptError("Authentication failed: the file was changed, truncated, or the key is wrong.") from exc
        yield pt
        if last:
            if src.read(1):
                raise DecryptError("Unexpected data after the final chunk.")
            return
        counter += 1
        block = nxt


def iter_file(path: Path, chunk: int = CHUNK) -> Iterator[bytes]:
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                return
            yield b


def encrypt_file(src: Path, dst: Path, dek: bytes, name: str) -> tuple[int, str, int]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as out:
        return encrypt_stream(iter_file(src), out, file_key(dek, name), name.encode())


def encrypt_bytes_to(data: bytes, dst: Path, dek: bytes, name: str) -> tuple[int, str, int]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as out:
        return encrypt_stream(iter([data]), out, file_key(dek, name), name.encode())


def decrypt_to(src: BinaryIO, dst: Path, dek: bytes, name: str) -> str:
    """Decrypt into ``dst`` (written to a temp name, renamed only after the whole file authenticated)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    h = hashlib.sha256()
    try:
        with open(tmp, "wb") as out:
            for pt in decrypt_stream(src, file_key(dek, name), name.encode()):
                h.update(pt)
                out.write(pt)
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            tmp.unlink()
    return h.hexdigest()


def decrypt_bytes(src: BinaryIO, dek: bytes, name: str, limit: int = 512 * 1024 * 1024) -> bytes:
    out = bytearray()
    for pt in decrypt_stream(src, file_key(dek, name), name.encode()):
        out += pt
        if len(out) > limit:
            raise DecryptError("Component larger than expected.")
    return bytes(out)


def digest_and_verify(src: BinaryIO, dek: bytes, name: str) -> tuple[str, int]:
    """Authenticate a whole file without keeping plain text: (plain sha256, plain size)."""
    h = hashlib.sha256()
    n = 0
    for pt in decrypt_stream(src, file_key(dek, name), name.encode()):
        h.update(pt)
        n += len(pt)
    return h.hexdigest(), n


# ------------------------------------------------------------------ Emergency Recovery Package

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
MIN_PASSPHRASE = 12


def seal_emergency(recovery_key: bytes, passphrase: str, meta: dict) -> dict:
    """Recovery Key sealed with a passphrase the main administrator chooses (scrypt + AES-256-GCM)."""
    if len(passphrase or "") < MIN_PASSPHRASE:
        raise ValueError(f"Choose a passphrase of at least {MIN_PASSPHRASE} characters.")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    k = Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).derive(passphrase.encode())
    body = json.dumps({"recovery_key": format_key(recovery_key), **meta}).encode()
    aad = json.dumps(meta, sort_keys=True).encode()
    return {"format": "personaldocs-emergency-recovery-package-1", **meta,
            "kdf": {"name": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "salt": base64.b64encode(salt).decode()},
            "cipher": {"name": "AES-256-GCM", "nonce": base64.b64encode(nonce).decode()},
            "sealed": base64.b64encode(AESGCM(k).encrypt(nonce, body, aad)).decode()}


def open_emergency(package: dict, passphrase: str) -> bytes:
    try:
        meta = {k: package[k] for k in ("installation", "generation", "created_at", "fingerprint")}
        kd = package["kdf"]
        k = Scrypt(salt=base64.b64decode(kd["salt"]), length=32, n=int(kd["n"]), r=int(kd["r"]), p=int(kd["p"])).derive(passphrase.encode())
        body = AESGCM(k).decrypt(base64.b64decode(package["cipher"]["nonce"]), base64.b64decode(package["sealed"]),
                                 json.dumps(meta, sort_keys=True).encode())
        return parse_key(json.loads(body)["recovery_key"])
    except (InvalidTag, KeyError, ValueError, TypeError) as exc:
        raise DecryptError("The passphrase is wrong or the Emergency Recovery Package is damaged.") from exc
