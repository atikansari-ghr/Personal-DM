"""Backup destinations behind one small interface (Local folder, NAS share, S3-compatible, Google Drive, OneDrive).

Every provider stores a recovery-point copy under ``<point id>/g<generation>/<file>`` and only ever receives
encrypted files. Credentials are kept encrypted (``BackupDestination.secret_enc``) and are never returned by the API,
logged or put into notifications. A provider never reports success it did not observe: missing credentials raise
``DestError("auth_required")``; a full disk raises ``DestError("insufficient_storage")``.
"""
from __future__ import annotations

import datetime as dt
import errno
import hashlib
import hmac
import json
import os
import shutil
import urllib.parse
from pathlib import Path
from typing import BinaryIO, Iterator

import requests

from apps.core import crypto

MARKER = ".personaldocs-backup-target"
TIMEOUT = 60
UPLOAD_CHUNK = 10 * 320 * 1024  # OneDrive requires multiples of 320 KiB; Google accepts any multiple of 256 KiB


class DestError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code  # unavailable | auth_required | insufficient_storage | failed


def secrets_of(dest) -> dict:
    if not dest.secret_enc:
        return {}
    try:
        return json.loads(crypto.decrypt(dest.secret_enc))
    except Exception as exc:  # noqa: BLE001
        raise DestError("auth_required", "Stored credentials cannot be decrypted; enter them again.") from exc


def set_secrets(dest, values: dict) -> None:
    clean = {k: v for k, v in (values or {}).items() if v not in (None, "")}
    dest.secret_enc = crypto.encrypt(json.dumps(clean)) if clean else ""


class Provider:
    kind = ""

    def __init__(self, dest, override_secrets: dict | None = None):
        self.dest = dest
        self.cfg = dict(dest.config or {}) if dest is not None else {}
        self._secrets = override_secrets

    @property
    def secrets(self) -> dict:
        if self._secrets is None:
            self._secrets = secrets_of(self.dest)
        return self._secrets

    # interface ------------------------------------------------------------
    def test(self) -> dict:  # {"ok": bool, "free": int|None, "total": int|None, "detail": str}
        raise NotImplementedError

    def put(self, rel: str, local: Path) -> int:
        raise NotImplementedError

    def open(self, rel: str) -> BinaryIO:
        raise NotImplementedError

    def list_points(self) -> list[str]:
        raise NotImplementedError

    def delete_prefix(self, prefix: str) -> None:
        raise NotImplementedError

    def space(self) -> tuple[int | None, int | None]:
        return None, None


# ------------------------------------------------------------------ local folder / NAS share

class LocalProvider(Provider):
    kind = "local"

    def root(self) -> Path:
        raw = (self.cfg.get("path") or "").strip()
        if not raw or not raw.startswith("/"):
            raise DestError("failed", "Enter an absolute folder path such as /srv/backups/personaldocs.")
        return Path(raw)

    def check(self, create: bool = False) -> Path:
        root = self.root()
        if not root.is_dir():
            # Created only by "Test destination" (on setup). A folder that disappears later (USB stick removed,
            # mount lost) is reported as unavailable instead of silently re-created on the local disk.
            if self.kind == "local" and create:
                try:
                    root.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    raise DestError("unavailable", f"Cannot create {root}: {exc.strerror}") from exc
            else:
                raise DestError("unavailable", f"{root} is not reachable. Is the share mounted?")
        if not os.access(root, os.W_OK):
            raise DestError("unavailable", f"The service account cannot write to {root}.")
        return root

    def test(self) -> dict:
        root = self.check(create=True)
        free, total = self.space()
        return {"ok": True, "free": free, "total": total, "detail": f"Writable folder {root}"}

    def space(self):
        try:
            u = shutil.disk_usage(self.root())
            return u.free, u.total
        except OSError:
            return None, None

    def put(self, rel: str, local: Path) -> int:
        root = self.check()
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".upload")
        try:
            try:
                os.link(local, tmp)  # same file system: no extra space, the staging file is write-once
            except OSError:
                shutil.copyfile(local, tmp)
            os.replace(tmp, dst)
        except OSError as exc:
            if tmp.exists():
                tmp.unlink()
            if exc.errno in (errno.ENOSPC, errno.EDQUOT):
                raise DestError("insufficient_storage", f"No space left on {root}.") from exc
            raise DestError("unavailable", f"Writing to {root} failed: {exc.strerror}") from exc
        return dst.stat().st_size

    def open(self, rel: str) -> BinaryIO:
        p = self.root() / rel
        try:
            return open(p, "rb")
        except FileNotFoundError as exc:
            raise DestError("failed", f"Missing file {rel}") from exc
        except OSError as exc:
            raise DestError("unavailable", f"Cannot read {rel}: {exc.strerror}") from exc

    def list_points(self) -> list[str]:
        root = self.root()
        if not root.is_dir():
            raise DestError("unavailable", f"{root} is not reachable.")
        return sorted(p.name for p in root.iterdir() if p.is_dir() and len(p.name) == 36 and p.name.count("-") == 4)

    def delete_prefix(self, prefix: str) -> None:
        target = (self.root() / prefix).resolve()
        if not str(target).startswith(str(self.root().resolve()) + os.sep):
            raise DestError("failed", "Refusing to delete outside the destination.")
        shutil.rmtree(target, ignore_errors=True)


class NasProvider(LocalProvider):
    """A NFS/SMB share: mounted by Personal DM from the destination's own settings (Backup & Recovery →
    Destinations → NAS), or mounted by the administrator/Proxmox ("Already mounted")."""

    kind = "nas"

    def check(self, create: bool = False) -> Path:
        root = self.root()
        if not root.is_dir():
            raise DestError("unavailable", f"{root} is not reachable. Is the NAS share mounted?")
        if self.cfg.get("require_mount", True):
            mount = root.resolve()
            while not os.path.ismount(mount) and mount != mount.parent:
                mount = mount.parent
            if mount == Path("/"):
                raise DestError("unavailable", f"{root} is not on a mounted share. Mount the NAS share, or turn off "
                                               "'Require mounted share' if the folder is intentionally local.")
        if not (root / MARKER).exists():
            raise DestError("unavailable", f"The marker file {MARKER} is missing in {root}. It protects against writing "
                                           "into an empty mount point; create it once after mounting the share.")
        if not os.access(root, os.W_OK):
            raise DestError("unavailable", f"The service account cannot write to {root}.")
        return root


# ------------------------------------------------------------------ S3-compatible object storage (SigV4)

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sigv4_headers(method: str, url: str, *, region: str, service: str, access_key: str, secret_key: str,
                  payload_hash: str, now: dt.datetime | None = None, extra: dict | None = None,
                  session_token: str = "") -> dict:
    """AWS Signature Version 4 (the documented algorithm; no custom cryptography)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    amz = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    u = urllib.parse.urlsplit(url)
    headers = {"host": u.netloc, "x-amz-date": amz, **{k.lower(): v for k, v in (extra or {}).items()}}
    if service == "s3":
        headers["x-amz-content-sha256"] = payload_hash
    if session_token:
        headers["x-amz-security-token"] = session_token
    query = sorted(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
    cq = "&".join(f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}" for k, v in query)
    signed = sorted(headers)
    canonical = "\n".join([method, urllib.parse.quote(u.path or "/", safe="/-_.~"), cq,
                           "".join(f"{h}:{' '.join(str(headers[h]).split())}\n" for h in signed),
                           ";".join(signed), payload_hash])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope, _sha(canonical.encode())])
    k = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret_key).encode(), day), region), service), "aws4_request")
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={';'.join(signed)}, Signature={sig}"
    return headers


class S3Provider(Provider):
    kind = "s3"

    def _base(self) -> tuple[str, str]:
        endpoint = (self.cfg.get("endpoint") or "").rstrip("/")
        bucket = self.cfg.get("bucket") or ""
        if not endpoint.startswith(("https://", "http://")) or not bucket:
            raise DestError("failed", "Enter the S3 endpoint (https://…) and bucket.")
        prefix = (self.cfg.get("prefix") or "personaldocs").strip("/")
        return f"{endpoint}/{bucket}", prefix

    def _req(self, method: str, key: str = "", *, query: str = "", data=None, payload_hash: str = "UNSIGNED-PAYLOAD",
             headers: dict | None = None, stream: bool = False):
        s = self.secrets
        if not s.get("access_key") or not s.get("secret_key"):
            raise DestError("auth_required", "S3 access key and secret key are required.")
        base, prefix = self._base()
        path = "/".join(x for x in (prefix, key) if x)
        url = f"{base}/{urllib.parse.quote(path, safe='/-_.~')}" + (f"?{query}" if query else "")
        h = sigv4_headers(method, url, region=self.cfg.get("region") or "us-east-1", service="s3",
                          access_key=s["access_key"], secret_key=s["secret_key"], payload_hash=payload_hash, extra=headers,
                          session_token=s.get("session_token", ""))
        try:
            r = requests.request(method, url, headers=h, data=data, timeout=TIMEOUT, stream=stream)
        except requests.RequestException as exc:
            raise DestError("unavailable", f"S3 endpoint unreachable: {exc.__class__.__name__}") from exc
        if r.status_code in (401, 403):
            raise DestError("auth_required", f"S3 refused the credentials (HTTP {r.status_code}).")
        if r.status_code == 507 or b"QuotaExceeded" in (r.content[:500] if not stream else b""):
            raise DestError("insufficient_storage", "The S3 bucket quota is exhausted.")
        return r

    def test(self) -> dict:
        r = self._req("GET", "", query="list-type=2&max-keys=1")
        if r.status_code >= 300:
            raise DestError("unavailable", f"S3 bucket check failed (HTTP {r.status_code}).")
        return {"ok": True, "free": None, "total": None, "detail": "Bucket reachable with the given credentials"}

    def put(self, rel: str, local: Path) -> int:
        size = local.stat().st_size
        with open(local, "rb") as fh:
            r = self._req("PUT", rel, data=fh, headers={"content-length": str(size)})
        if r.status_code >= 300:
            raise DestError("failed", f"Upload failed (HTTP {r.status_code}).")
        return size

    def open(self, rel: str) -> BinaryIO:
        r = self._req("GET", rel, stream=True)
        if r.status_code == 404:
            raise DestError("failed", f"Missing object {rel}")
        if r.status_code >= 300:
            raise DestError("unavailable", f"Download failed (HTTP {r.status_code}).")
        r.raw.decode_content = True
        return r.raw

    def _list(self, prefix: str, delimiter: str = "") -> tuple[list[str], list[str]]:
        import xml.etree.ElementTree as ET

        _base, root = self._base()
        keys, prefixes, token = [], [], ""
        while True:
            q = {"list-type": "2", "prefix": f"{root}/{prefix}".lstrip("/")}
            if delimiter:
                q["delimiter"] = delimiter
            if token:
                q["continuation-token"] = token
            r = self._req("GET", "", query=urllib.parse.urlencode(sorted(q.items())))
            if r.status_code >= 300:
                raise DestError("unavailable", f"Listing failed (HTTP {r.status_code}).")
            tree = ET.fromstring(r.content)
            ns = tree.tag.split("}")[0] + "}" if tree.tag.startswith("{") else ""
            keys += [e.text for e in tree.iter(f"{ns}Key")]
            prefixes += [e.text for e in tree.iter(f"{ns}Prefix") if e.text and e.text.endswith("/")]
            nxt = tree.find(f"{ns}NextContinuationToken")
            if nxt is None or not nxt.text:
                break
            token = nxt.text
        return keys, prefixes

    def list_points(self) -> list[str]:
        _keys, prefixes = self._list("", "/")
        _base, root = self._base()
        out = [p[len(root) + 1:].strip("/") for p in prefixes if p.startswith(root + "/")]
        return sorted(p for p in out if len(p) == 36)

    def delete_prefix(self, prefix: str) -> None:
        keys, _ = self._list(prefix.rstrip("/") + "/")
        _base, root = self._base()
        for k in keys:
            self._req("DELETE", k[len(root) + 1:])


# ------------------------------------------------------------------ OAuth helpers (Google Drive / OneDrive)

class _OAuthProvider(Provider):
    token_url = ""

    def _token(self) -> str:
        s = self.secrets
        if s.get("access_token") and not s.get("refresh_token"):
            return s["access_token"]  # temporary bootstrap authorisation (disaster recovery); never stored
        if not (s.get("refresh_token") and s.get("client_id")):
            raise DestError("auth_required", "Authorisation is missing: enter the client id, client secret and refresh token.")
        try:
            r = requests.post(self.token_url, data={"grant_type": "refresh_token", "refresh_token": s["refresh_token"],
                                                    "client_id": s["client_id"], "client_secret": s.get("client_secret", ""),
                                                    **self._token_extra()}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise DestError("unavailable", f"Token service unreachable: {exc.__class__.__name__}") from exc
        if r.status_code >= 400:
            raise DestError("auth_required", "The refresh token was rejected (expired or revoked). Authorise again.")
        return r.json()["access_token"]

    def _token_extra(self) -> dict:
        return {}

    def _call(self, method, url, *, token=None, **kw):
        token = token or self._token()
        headers = {"Authorization": f"Bearer {token}", **kw.pop("headers", {})}
        try:
            r = requests.request(method, url, headers=headers, timeout=kw.pop("timeout", TIMEOUT), **kw)
        except requests.RequestException as exc:
            raise DestError("unavailable", f"{self.kind} unreachable: {exc.__class__.__name__}") from exc
        if r.status_code == 401:
            raise DestError("auth_required", "Authorisation expired or was revoked. Authorise again.")
        if r.status_code in (403, 507) and b"quota" in r.content[:2000].lower():
            raise DestError("insufficient_storage", "The cloud storage quota is exhausted.")
        return r


class GoogleDriveProvider(_OAuthProvider):
    """Google Drive (OAuth 2.0, scope drive.file): files live in one folder chosen by its id."""

    kind = "gdrive"
    token_url = "https://oauth2.googleapis.com/token"
    API = "https://www.googleapis.com/drive/v3"
    UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"

    def _folder(self) -> str:
        fid = self.cfg.get("folder_id") or ""
        if not fid:
            raise DestError("failed", "Enter the Google Drive folder id.")
        return fid

    def _find(self, name: str, parent: str, token: str) -> str | None:
        q = f"name = '{name}' and '{parent}' in parents and trashed = false"
        r = self._call("GET", f"{self.API}/files", token=token, params={"q": q, "fields": "files(id)", "pageSize": 10})
        files = r.json().get("files", []) if r.status_code < 300 else []
        return files[0]["id"] if files else None

    def _ensure_path(self, parts: list[str], token: str) -> str:
        parent = self._folder()
        for p in parts:
            fid = self._find(p, parent, token)
            if fid is None:
                r = self._call("POST", f"{self.API}/files", token=token, json={"name": p, "parents": [parent],
                                                                                 "mimeType": "application/vnd.google-apps.folder"})
                if r.status_code >= 300:
                    raise DestError("failed", f"Cannot create folder (HTTP {r.status_code}).")
                fid = r.json()["id"]
            parent = fid
        return parent

    def test(self) -> dict:
        token = self._token()
        r = self._call("GET", f"{self.API}/files/{self._folder()}", token=token, params={"fields": "id,name"})
        if r.status_code >= 300:
            raise DestError("unavailable", f"Folder not accessible (HTTP {r.status_code}).")
        free, total = self.space(token)
        return {"ok": True, "free": free, "total": total, "detail": "Google Drive folder reachable"}

    def space(self, token=None):
        try:
            r = self._call("GET", f"{self.API}/about", token=token, params={"fields": "storageQuota"})
            q = r.json().get("storageQuota", {})
            if q.get("limit"):
                return int(q["limit"]) - int(q.get("usage", 0)), int(q["limit"])
        except (DestError, ValueError):
            pass
        return None, None

    def put(self, rel: str, local: Path) -> int:
        token = self._token()
        *dirs, name = rel.split("/")
        parent = self._ensure_path(dirs, token)
        size = local.stat().st_size
        r = self._call("POST", f"{self.UPLOAD}?uploadType=resumable", token=token,
                       json={"name": name, "parents": [parent]}, headers={"X-Upload-Content-Length": str(size)})
        if r.status_code >= 300 or "Location" not in r.headers:
            raise DestError("failed", f"Upload session refused (HTTP {r.status_code}).")
        _chunked_upload(self, r.headers["Location"], local, size, token, auth=True)
        return size

    def _file_id(self, rel: str, token: str) -> str:
        *dirs, name = rel.split("/")
        parent = self._folder()
        for p in dirs:
            parent = self._find(p, parent, token)
            if parent is None:
                raise DestError("failed", f"Missing file {rel}")
        fid = self._find(name, parent, token)
        if fid is None:
            raise DestError("failed", f"Missing file {rel}")
        return fid

    def open(self, rel: str) -> BinaryIO:
        token = self._token()
        r = self._call("GET", f"{self.API}/files/{self._file_id(rel, token)}", token=token, params={"alt": "media"}, stream=True)
        if r.status_code >= 300:
            raise DestError("unavailable", f"Download failed (HTTP {r.status_code}).")
        return r.raw

    def list_points(self) -> list[str]:
        token = self._token()
        r = self._call("GET", f"{self.API}/files", token=token, params={
            "q": f"'{self._folder()}' in parents and trashed = false and mimeType = 'application/vnd.google-apps.folder'",
            "fields": "files(name)", "pageSize": 1000})
        if r.status_code >= 300:
            raise DestError("unavailable", f"Listing failed (HTTP {r.status_code}).")
        return sorted(f["name"] for f in r.json().get("files", []) if len(f["name"]) == 36)

    def delete_prefix(self, prefix: str) -> None:
        token = self._token()
        parts = prefix.strip("/").split("/")
        parent = self._folder()
        for p in parts:
            parent = self._find(p, parent, token)
            if parent is None:
                return
        self._call("DELETE", f"{self.API}/files/{parent}", token=token)


class OneDriveProvider(_OAuthProvider):
    """Microsoft OneDrive (Microsoft Graph, OAuth 2.0 offline_access + Files.ReadWrite)."""

    kind = "onedrive"
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    API = "https://graph.microsoft.com/v1.0/me/drive"

    def _token_extra(self) -> dict:
        return {"scope": "offline_access Files.ReadWrite"}

    def _path(self, rel: str = "") -> str:
        root = (self.cfg.get("folder") or "Apps/PersonalDocs").strip("/")
        return urllib.parse.quote("/".join(x for x in (root, rel.strip("/")) if x))

    def test(self) -> dict:
        token = self._token()
        r = self._call("GET", self.API, token=token)
        if r.status_code >= 300:
            raise DestError("unavailable", f"OneDrive not accessible (HTTP {r.status_code}).")
        q = r.json().get("quota", {})
        free, total = q.get("remaining"), q.get("total")
        return {"ok": True, "free": free, "total": total, "detail": "OneDrive reachable"}

    def space(self):
        try:
            q = self._call("GET", self.API).json().get("quota", {})
            return q.get("remaining"), q.get("total")
        except (DestError, ValueError):
            return None, None

    def put(self, rel: str, local: Path) -> int:
        token = self._token()
        size = local.stat().st_size
        r = self._call("POST", f"{self.API}/root:/{self._path(rel)}:/createUploadSession", token=token,
                       json={"item": {"@microsoft.graph.conflictBehavior": "replace"}})
        if r.status_code >= 300:
            raise DestError("failed", f"Upload session refused (HTTP {r.status_code}).")
        _chunked_upload(self, r.json()["uploadUrl"], local, size, token, auth=False)
        return size

    def open(self, rel: str) -> BinaryIO:
        r = self._call("GET", f"{self.API}/root:/{self._path(rel)}:/content", stream=True)
        if r.status_code == 404:
            raise DestError("failed", f"Missing file {rel}")
        if r.status_code >= 300:
            raise DestError("unavailable", f"Download failed (HTTP {r.status_code}).")
        return r.raw

    def list_points(self) -> list[str]:
        r = self._call("GET", f"{self.API}/root:/{self._path()}:/children", params={"$top": 1000})
        if r.status_code == 404:
            return []
        if r.status_code >= 300:
            raise DestError("unavailable", f"Listing failed (HTTP {r.status_code}).")
        return sorted(i["name"] for i in r.json().get("value", []) if "folder" in i and len(i["name"]) == 36)

    def delete_prefix(self, prefix: str) -> None:
        self._call("DELETE", f"{self.API}/root:/{self._path(prefix)}")


def _chunked_upload(provider, url: str, local: Path, size: int, token: str, *, auth: bool) -> None:
    """Resumable upload in bounded chunks (never the whole file in memory)."""
    with open(local, "rb") as fh:
        start = 0
        if size == 0:
            headers = {"Content-Range": "bytes */0"}
            r = provider._call("PUT", url, token=token, data=b"", headers=headers) if auth else requests.put(url, data=b"", headers=headers, timeout=TIMEOUT)
            return
        while start < size:
            chunk = fh.read(UPLOAD_CHUNK)
            end = start + len(chunk) - 1
            headers = {"Content-Length": str(len(chunk)), "Content-Range": f"bytes {start}-{end}/{size}"}
            try:
                r = provider._call("PUT", url, token=token, data=chunk, headers=headers) if auth else \
                    requests.put(url, data=chunk, headers=headers, timeout=TIMEOUT)
            except requests.RequestException as exc:
                raise DestError("unavailable", f"Upload interrupted: {exc.__class__.__name__}") from exc
            if r.status_code not in (200, 201, 202, 308):
                if r.status_code == 507:
                    raise DestError("insufficient_storage", "The cloud storage quota is exhausted.")
                raise DestError("failed", f"Upload failed (HTTP {r.status_code}).")
            start = end + 1


PROVIDERS = {"local": LocalProvider, "nas": NasProvider, "s3": S3Provider, "gdrive": GoogleDriveProvider, "onedrive": OneDriveProvider}
LABELS = {"local": "Local folder", "nas": "NAS share (NFS/SMB)", "s3": "S3-compatible storage", "gdrive": "Google Drive",
          "onedrive": "Microsoft OneDrive"}
CONFIG_FIELDS = {"local": ("path", "warn_pct", "crit_pct"), "nas": ("path", "require_mount", "connection", "warn_pct", "crit_pct"), "s3": ("endpoint", "region", "bucket", "prefix"),
                 "gdrive": ("folder_id",), "onedrive": ("folder",)}
SECRET_FIELDS = {"local": (), "nas": (), "s3": ("access_key", "secret_key", "session_token"),
                 "gdrive": ("client_id", "client_secret", "refresh_token"), "onedrive": ("client_id", "client_secret", "refresh_token")}


def provider(dest, override_secrets: dict | None = None) -> Provider:
    cls = PROVIDERS.get(dest.kind)
    if cls is None:
        raise DestError("failed", f"Unknown destination type {dest.kind}.")
    return cls(dest, override_secrets)


def iter_stream(fh: BinaryIO, chunk: int = 1024 * 1024) -> Iterator[bytes]:
    while True:
        b = fh.read(chunk)
        if not b:
            return
        yield b
