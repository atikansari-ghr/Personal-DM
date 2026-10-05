"""Local GeoIP: country lookup from a MaxMind-format database on this server (no lookup APIs).

The database (GeoLite2-Country by default) lives in <data>/geoip/. Updates download into a temporary file,
are opened and test-queried, and only then replace the current file atomically, so a failed or corrupt
download never disturbs lookups or the access policy. Status (last success/failure) is kept in state.json.
Geolocation is approximate: mobile carriers, VPNs and corporate networks often resolve elsewhere.
"""
from __future__ import annotations

import io
import json
import logging
import os
import tarfile
import tempfile
from datetime import datetime, timezone as dt_tz
from pathlib import Path

from django.conf import settings

from . import netutil

log = logging.getLogger("personaldocs.geoip")

DB_NAME = "country.mmdb"
COUNTRY_NAMES_FALLBACK: dict[str, str] = {}
_reader = {"path": None, "mtime": None, "obj": None}


class GeoIPError(Exception):
    pass


def geoip_dir() -> Path:
    return Path(settings.DATA_DIR) / "geoip"


def db_path() -> Path:
    return geoip_dir() / DB_NAME


def _state_path() -> Path:
    return geoip_dir() / "state.json"


def read_state() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _write_state(**changes) -> None:
    state = read_state()
    state.update(changes)
    geoip_dir().mkdir(parents=True, exist_ok=True)
    tmp = _state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, _state_path())


def _open():
    import maxminddb

    path = db_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _reader.update(path=None, mtime=None, obj=None)
        return None
    if _reader["obj"] is None or _reader["mtime"] != mtime or _reader["path"] != str(path):
        try:
            _reader.update(path=str(path), mtime=mtime, obj=maxminddb.open_database(str(path)))
        except Exception as exc:  # noqa: BLE001 - a broken file must not break requests
            log.warning("cannot open GeoIP database: %s", exc)
            _reader.update(path=None, mtime=None, obj=None)
            return None
    return _reader["obj"]


def lookup(ip) -> tuple[str, str] | None:
    """(ISO country code, English name) or None when unknown/private/no database."""
    if isinstance(ip, str):
        ip = netutil.parse_ip(ip)
    if ip is None or netutil.is_internal(ip):
        return None
    reader = _open()
    if reader is None:
        return None
    try:
        rec = reader.get(str(ip))
    except Exception:  # noqa: BLE001
        return None
    if not rec:
        return None
    country = rec.get("country") or rec.get("registered_country") or {}
    code = (country.get("iso_code") or "").upper()
    if not code:
        return None
    return code, (country.get("names") or {}).get("en", code)


def status() -> dict:
    state = read_state()
    path = db_path()
    info = {"installed": path.exists(), "path": str(path), "build_date": None, "database_type": None,
            "last_success": state.get("last_success"), "last_attempt": state.get("last_attempt"),
            "last_error": state.get("last_error"), "next_update": state.get("next_update")}
    reader = _open()
    if reader is not None:
        meta = reader.metadata()
        info["build_date"] = datetime.fromtimestamp(meta.build_epoch, dt_tz.utc).date().isoformat()
        info["database_type"] = meta.database_type
    elif info["installed"]:
        info["last_error"] = info["last_error"] or "The database file exists but cannot be opened."
    return info


def _validate_file(path: Path) -> str:
    import maxminddb

    try:
        with maxminddb.open_database(str(path)) as r:
            r.get("8.8.8.8")
            dbtype = r.metadata().database_type
    except Exception as exc:  # noqa: BLE001
        raise GeoIPError(f"Downloaded file is not a valid GeoIP database ({exc.__class__.__name__}).") from exc
    if "Country" not in dbtype and "City" not in dbtype:
        raise GeoIPError(f"Unexpected database type {dbtype}; use a Country or City database.")
    return dbtype


def install_file(src: Path) -> dict:
    """Validate and atomically install a database file (manual upload or downloaded)."""
    dbtype = _validate_file(src)
    geoip_dir().mkdir(parents=True, exist_ok=True)
    dst = db_path()
    tmp = dst.with_suffix(".new")
    with open(src, "rb") as fin, open(tmp, "wb") as fout:
        fout.write(fin.read())
    os.chmod(tmp, 0o640)
    os.replace(tmp, dst)
    now = datetime.now(dt_tz.utc).isoformat()
    _write_state(last_success=now, last_attempt=now, last_error="")
    return {"database_type": dbtype}


def update_from_maxmind(account_id: str, license_key: str, edition: str = "GeoLite2-Country", http=None) -> dict:
    """Download the current database from MaxMind. The license key goes in an Authorization header only."""
    import requests

    now = datetime.now(dt_tz.utc).isoformat()
    if not account_id or not license_key:
        _write_state(last_attempt=now, last_error="MaxMind account ID and license key are not configured.")
        raise GeoIPError("MaxMind account ID and license key are not configured.")
    url = f"https://download.maxmind.com/geoip/databases/{edition}/download?suffix=tar.gz"
    http = http or requests
    try:
        resp = http.get(url, auth=(account_id, license_key), timeout=60)
        if resp.status_code in (401, 403):
            raise GeoIPError("MaxMind rejected the account ID / license key.")
        if resp.status_code != 200:
            raise GeoIPError(f"MaxMind download failed (HTTP {resp.status_code}).")
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
            member = next((m for m in tar.getmembers() if m.isfile() and m.name.endswith(".mmdb")), None)
            if member is None:
                raise GeoIPError("The download did not contain a .mmdb database.")
            data = tar.extractfile(member).read()
        geoip_dir().mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=geoip_dir(), suffix=".mmdb", delete=False) as fh:
            fh.write(data)
            tmp = Path(fh.name)
        try:
            result = install_file(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        return result
    except GeoIPError as exc:
        _write_state(last_attempt=now, last_error=str(exc))
        raise
    except Exception as exc:  # noqa: BLE001 - network, tar or filesystem problem
        msg = f"GeoIP update failed: {exc.__class__.__name__}"
        _write_state(last_attempt=now, last_error=msg)
        raise GeoIPError(msg) from exc
