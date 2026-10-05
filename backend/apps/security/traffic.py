"""Traffic analytics: privacy-safe access log + GoAccess (or built-in) summary for administrators.

The access log (COMBINED format, PD_ACCESS_LOG) records the real client IP (trusted-proxy logic), method,
path *without query string*, status, size and user agent. Share-link tokens are masked and referrers are
never written, so bearer tokens cannot leak into logs. GoAccess, when installed and enabled, turns the log
into a JSON report under <data>/goaccess/; otherwise an equivalent built-in summary is computed. The data is
only served to the main administrator through the authenticated API; no GoAccess endpoint is exposed.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone as dt_tz
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from . import netutil

log = logging.getLogger("personaldocs.security")
_access = logging.getLogger("personaldocs.access")
_access.propagate = False
_configured = {"path": None}

TOKEN_PATH = re.compile(r"^/s/[^/]+")
LINE = re.compile(r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+) [^"]*" (\d{3}) (\d+|-) "[^"]*" "([^"]*)"')
BOT = re.compile(r"bot|crawler|spider|curl|wget|python|scan|nikto|zgrab|masscan|httpclient|go-http", re.I)


def access_log_path() -> Path | None:
    value = getattr(settings, "ACCESS_LOG", "")
    return Path(value) if value else None


def _logger():
    path = access_log_path()
    if path is None:
        return None
    if _configured["path"] != str(path):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.WatchedFileHandler(path)
        except OSError:
            return None
        handler.setFormatter(logging.Formatter("%(message)s"))
        for h in list(_access.handlers):
            _access.removeHandler(h)
        _access.addHandler(handler)
        _access.setLevel(logging.INFO)
        _configured["path"] = str(path)
    return _access


def safe_path(path: str) -> str:
    path = path.split("?", 1)[0][:300]
    return TOKEN_PATH.sub("/s/[token]", path).replace('"', "%22").replace(" ", "%20")


class AccessLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        logger = _logger()
        if logger is not None:
            try:
                size = len(response.content) if not getattr(response, "streaming", False) and hasattr(response, "content") else 0
                ua = (request.META.get("HTTP_USER_AGENT") or "-").replace('"', "'")[:300]
                stamp = datetime.now(dt_tz.utc).strftime("%d/%b/%Y:%H:%M:%S +0000")
                logger.info('%s - - [%s] "%s %s HTTP/1.1" %s %s "-" "%s"', netutil.client_ip(request) or "-", stamp,
                            request.method, safe_path(request.path), response.status_code, size, ua)
            except Exception:  # noqa: BLE001 - logging must never break a response
                pass
        return response


def report_dir() -> Path:
    return Path(settings.DATA_DIR) / "goaccess"


def goaccess_binary() -> str | None:
    return shutil.which("goaccess")


def _empty(source: str) -> dict:
    return {"source": source, "generated_at": timezone.now().isoformat(), "requests": 0, "visitors": 0, "bandwidth": 0,
            "statuses": {}, "errors": {"401": 0, "403": 0, "404": 0}, "top_ips": [], "countries": [], "endpoints": [],
            "user_agents": [], "bots": 0, "per_day": [], "blocked": []}


def builtin_summary(path: Path, days: int = 7) -> dict:
    from . import geoip

    out = _empty("built-in")
    since = datetime.now(dt_tz.utc) - timedelta(days=days)
    ips, countries, endpoints, agents, statuses, per_day, visitors = Counter(), Counter(), Counter(), Counter(), Counter(), Counter(), set()
    bandwidth = requests = bots = 0
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for line in fh:
            m = LINE.match(line)
            if not m:
                continue
            ip, stamp, _method, url, status, size, ua = m.groups()
            try:
                at = datetime.strptime(stamp, "%d/%b/%Y:%H:%M:%S %z")
            except ValueError:
                continue
            if at < since:
                continue
            requests += 1
            bandwidth += int(size) if size.isdigit() else 0
            ips[ip] += 1
            endpoints[url] += 1
            agents[ua[:120]] += 1
            statuses[status] += 1
            per_day[at.date().isoformat()] += 1
            visitors.add((ip, at.date(), ua))
            if BOT.search(ua):
                bots += 1
    for ip, n in ips.items():
        geo = geoip.lookup(ip)
        countries[geo[1] if geo else "Unknown"] += n
    out.update(requests=requests, visitors=len(visitors), bandwidth=bandwidth, bots=bots,
               statuses=dict(sorted(statuses.items())),
               errors={k: statuses.get(k, 0) for k in ("401", "403", "404")},
               top_ips=[{"ip": i, "requests": n} for i, n in ips.most_common(10)],
               countries=[{"country": c, "requests": n} for c, n in countries.most_common(15)],
               endpoints=[{"path": p, "requests": n} for p, n in endpoints.most_common(15)],
               user_agents=[{"agent": a, "requests": n} for a, n in agents.most_common(10)],
               per_day=[{"day": d, "requests": n} for d, n in sorted(per_day.items())])
    return out


def _from_goaccess(data: dict) -> dict:
    out = _empty("goaccess")
    general = data.get("general") or {}
    out["requests"] = int(general.get("total_requests") or 0)
    out["visitors"] = int(general.get("unique_visitors") or 0)
    out["bandwidth"] = int(general.get("bandwidth") or 0)

    def items(section):
        return (data.get(section) or {}).get("data") or []

    def hits(row):
        h = row.get("hits")
        return int(h.get("count", 0) if isinstance(h, dict) else (h or 0))

    out["top_ips"] = [{"ip": r.get("data"), "requests": hits(r)} for r in items("hosts")[:10]]
    out["endpoints"] = [{"path": r.get("data"), "requests": hits(r)} for r in items("requests")[:15]]
    out["user_agents"] = [{"agent": r.get("data"), "requests": hits(r)} for r in items("browsers")[:10]]
    out["per_day"] = [{"day": r.get("data"), "requests": hits(r)} for r in items("visitors")]
    countries = []
    for cont in items("geolocation"):
        for c in cont.get("items") or []:
            countries.append({"country": re.sub(r"^[A-Z]{2} ", "", c.get("data") or ""), "requests": hits(c)})
    out["countries"] = sorted(countries, key=lambda x: -x["requests"])[:15]
    statuses = {}
    for group in items("status_codes"):
        for c in group.get("items") or []:
            code = (c.get("data") or "")[:3]
            if code.isdigit():
                statuses[code] = statuses.get(code, 0) + hits(c)
    out["statuses"] = dict(sorted(statuses.items()))
    out["errors"] = {k: statuses.get(k, 0) for k in ("401", "403", "404")}
    return out


def build_report() -> dict:
    """Write <data>/goaccess/summary.json (and the GoAccess JSON/HTML reports when GoAccess is installed)."""
    from . import geoip

    path = access_log_path()
    report_dir().mkdir(parents=True, exist_ok=True)
    binary = goaccess_binary()
    summary = None
    error = ""
    if path is not None and path.exists() and binary:
        cmd = [binary, str(path), "--log-format=COMBINED", "--no-progress", "--real-os",
               "-o", str(report_dir() / "report.json"), "-o", str(report_dir() / "report.html")]
        if geoip.db_path().exists():
            cmd.append(f"--geoip-database={geoip.db_path()}")
        try:
            subprocess.run(cmd, capture_output=True, timeout=300, check=True)
            summary = _from_goaccess(json.loads((report_dir() / "report.json").read_text()))
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            error = f"GoAccess failed ({exc.__class__.__name__}); built-in summary shown."
            log.warning("goaccess report failed: %s", exc)
    if summary is None:
        summary = builtin_summary(path) if path is not None else _empty("built-in")
    summary["error"] = error
    tmp = report_dir() / "summary.tmp"
    tmp.write_text(json.dumps(summary))
    os.replace(tmp, report_dir() / "summary.json")
    return {"source": summary["source"], "requests": summary["requests"]}


def read_summary() -> dict | None:
    try:
        return json.loads((report_dir() / "summary.json").read_text())
    except (OSError, ValueError):
        return None


def blocked_stats(days: int = 7) -> list[dict]:
    from django.db.models import Sum

    from .models import BlockedStat

    since = timezone.localdate() - timedelta(days=days)
    rows = BlockedStat.objects.filter(day__gte=since).values("reason", "country").annotate(total=Sum("count")).order_by("-total")
    return [{"reason": r["reason"], "country": r["country"], "requests": r["total"]} for r in rows[:20]]


def status() -> dict:
    path = access_log_path()
    summary = read_summary()
    return {"goaccess_installed": bool(goaccess_binary()), "access_log": str(path) if path else "",
            "access_log_exists": bool(path and path.exists()), "last_report": summary.get("generated_at") if summary else None,
            "source": summary.get("source") if summary else None, "error": summary.get("error") if summary else ""}
