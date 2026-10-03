"""Encryption for integration secrets (SMTP/Telegram/Google/IMAP credentials).

The Fernet key lives in CONFIG_DIR/encryption.key (mode 0600, owned by the service user) outside
the Git checkout and the database, so a database dump alone does not reveal secrets. Backups may
include the key (setting backup.include_keys) so restores remain decryptable; see backup guide.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def key_path() -> Path:
    return Path(settings.CONFIG_DIR) / "encryption.key"


def ensure_key() -> Path:
    path = key_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(Fernet.generate_key())
    return path


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    path = key_path()
    if not path.exists():
        ensure_key()
    return Fernet(path.read_bytes().strip())


def reset_cache() -> None:
    _fernet.cache_clear()


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # wrong/missing key after a restore
        raise RuntimeError("Cannot decrypt stored secret: encryption key does not match") from exc


def token_urlsafe(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """One-way hash for bearer tokens (share links, reset tokens). Keyed with SECRET_KEY."""
    return hmac.new(settings.SECRET_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()
