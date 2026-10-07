"""Security center: Internet Ready (HTTPS) checks, the manual Basic Internet Security Test, OS security updates,
firewall monitoring, the Security Health score, security-record retention/purge and Storage Health.

None of this proves the system is free of vulnerabilities. The security test is a *baseline* of the application and
this host only: it never scans other devices on the network, and it runs only when an administrator starts it.
Critical/High findings are shown prominently but do not block anything (warning-only policy).
Firewall rules are only *read*; nothing here can change them. Cleanup never touches original documents.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from apps.core import audit, config, jobs

from .models import HealthState, OsUpdateRun, SecurityTestRun

log = logging.getLogger("personaldocs.security")

SEVERITIES = ("critical", "high", "medium", "low", "info")


def _internet() -> bool:
    return config.get("security.deployment") == "internet"


# ------------------------------------------------------------------ HTTPS / Internet Ready

def _get(url: str, **kw):
    kw.setdefault("timeout", 10)
    kw.setdefault("allow_redirects", False)
    return requests.get(url, **kw)


def https_checks() -> dict:
    """Checks of the externally configured address (PUBLIC_ORIGIN). Never contacts any other host."""
    origin = settings.PUBLIC_ORIGIN
    parts = urlsplit(origin)
    checks = []

    def add(key, name, ok, detail="", remediation=""):
        checks.append({"key": key, "name": name, "ok": bool(ok), "detail": detail, "remediation": remediation})

    add("https_origin", "Public address uses HTTPS", parts.scheme == "https", origin,
        "Set PD_PUBLIC_ORIGIN to the https:// address of your reverse proxy (sudo personaldocs configure).")
    resp = None
    if parts.scheme == "https":
        try:
            resp = _get(f"{origin}/api/session")
            add("tls_valid", "Valid TLS certificate", True, f"HTTP {resp.status_code}")
        except requests.exceptions.SSLError as exc:
            add("tls_valid", "Valid TLS certificate", False, str(exc)[:200],
                "Issue a certificate for this hostname in Nginx Proxy Manager / Pangolin (Let's Encrypt).")
        except requests.RequestException as exc:
            add("tls_valid", "Valid TLS certificate", False, f"Not reachable: {exc.__class__.__name__}",
                "Check DNS and that the reverse proxy forwards to this server.")
        try:
            r = _get(f"http://{parts.netloc}/api/session")
            loc = r.headers.get("Location", "")
            add("http_redirect", "HTTP redirects to HTTPS", r.status_code in (301, 302, 307, 308) and loc.startswith("https://"),
                f"HTTP {r.status_code} {loc[:80]}", "Enable 'Force SSL' on the proxy host.")
        except requests.RequestException as exc:
            add("http_redirect", "HTTP redirects to HTTPS", False, f"Plain HTTP not reachable ({exc.__class__.__name__}); "
                "make sure port 80 redirects to HTTPS.", "Enable 'Force SSL' on the proxy host.")
    else:
        add("tls_valid", "Valid TLS certificate", False, "The public address is plain HTTP.", "Publish the site through HTTPS.")
        add("http_redirect", "HTTP redirects to HTTPS", False, "The public address is plain HTTP.", "Enable 'Force SSL' on the proxy.")
    cookie_hdr = resp.headers.get("Set-Cookie", "") if resp is not None else ""
    add("secure_cookies", "Secure session and CSRF cookies", settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE
        and (not cookie_hdr or "secure" in cookie_hdr.lower()), "Cookies are marked Secure and HttpOnly" if settings.SESSION_COOKIE_SECURE
        else "Cookies are not marked Secure (HTTP origin).", "Use an https:// PD_PUBLIC_ORIGIN; cookies become Secure automatically.")
    if resp is not None:
        h = {k.lower(): v for k, v in resp.headers.items()}
        missing = [n for n, ok in (("X-Content-Type-Options", h.get("x-content-type-options") == "nosniff"),
                                   ("Referrer-Policy", "referrer-policy" in h),
                                   ("Content-Security-Policy or X-Frame-Options", "content-security-policy" in h or "x-frame-options" in h))
                   if not ok]
        add("headers", "Security headers", not missing, "Missing: " + ", ".join(missing) if missing else "Present",
            "Do not strip the application's headers in the proxy configuration.")
        hsts = h.get("strict-transport-security", "")
        m = re.search(r"max-age=(\d+)", hsts)
        add("hsts", "HSTS (Strict-Transport-Security)", bool(m and int(m.group(1)) >= 15552000), hsts or "Not sent",
            "Keep PD_HSTS_SECONDS at its default (one year) and make the proxy send X-Forwarded-Proto: https.")
    else:
        add("headers", "Security headers", False, "The HTTPS address could not be checked.", "Fix the HTTPS checks above first.")
        add("hsts", "HSTS (Strict-Transport-Security)", False, "The HTTPS address could not be checked.", "Fix the HTTPS checks above first.")
    all_ok = all(c["ok"] for c in checks)
    result = {"deployment": config.get("security.deployment"), "origin": origin, "checks": checks, "https_ok": all_ok,
              "internet_ready": _internet() and all_ok, "checked_at": timezone.now().isoformat()}
    HealthState.put("https", **result)
    return result


def https_state() -> dict:
    st = HealthState.get("https")
    st["deployment"] = config.get("security.deployment")
    st["internet_ready"] = bool(_internet() and st.get("https_ok"))
    return st


# ------------------------------------------------------------------ Basic Internet Security Test

class _Findings:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, category, check, status, severity="info", detail="", remediation="", key=None):
        """status: pass | warn | fail | info. severity applies to warn/fail."""
        self.items.append({"id": key or re.sub(r"[^a-z0-9]+", "-", f"{category}-{check}".lower()).strip("-")[:80],
                           "category": category, "check": check, "status": status,
                           "severity": severity if status in ("warn", "fail") else "info", "detail": str(detail)[:400],
                           "remediation": remediation})


def _check_https(f: _Findings):
    res = https_checks()
    sev = "critical" if _internet() else "low"
    for c in res["checks"]:
        if c["ok"]:
            f.add("HTTPS & TLS", c["name"], "pass", detail=c["detail"], key=f"https-{c['key']}")
        else:
            severity = "high" if _internet() and c["key"] in ("hsts", "headers", "http_redirect") else sev
            f.add("HTTPS & TLS", c["name"], "fail" if _internet() else "warn", severity, c["detail"], c["remediation"],
                  key=f"https-{c['key']}")
    if not _internet():
        f.add("HTTPS & TLS", "Deployment exposure", "info", detail="LAN-only deployment: not reported as Internet Ready.",
              key="https-lan")


def _check_framework(f: _Findings):
    cat = "Framework & configuration"
    if settings.DEBUG:
        f.add(cat, "Debug mode off", "fail", "critical" if _internet() else "high", "DEBUG is on: error pages reveal internals.",
              "Remove PD_DEBUG from /etc/personaldocs/personaldocs.env and restart.")
    else:
        f.add(cat, "Debug mode off", "pass")
    if "*" in settings.ALLOWED_HOSTS:
        f.add(cat, "Allowed host names restricted", "fail", "high", "ALLOWED_HOSTS contains '*'.", "List only your hostnames.")
    else:
        f.add(cat, "Allowed host names restricted", "pass", detail=", ".join(settings.ALLOWED_HOSTS)[:200])
    if len(settings.SECRET_KEY) < 40:
        f.add(cat, "Strong secret key", "fail", "high", "The Django secret key is short.", "sudo personaldocs repair creates a strong key.")
    else:
        f.add(cat, "Strong secret key", "pass")
    from django.core.management import call_command

    out = io.StringIO()
    try:
        call_command("check", deploy=True, stdout=out, stderr=out)
    except Exception as exc:  # noqa: BLE001 - check() raises when it finds errors; the text is still useful
        out.write(str(exc))
    ignore = {"security.W008", "security.W018", "security.W009", "security.W004", "security.W016", "security.W012",
              "security.W019"}  # SAMEORIGIN framing is needed by the built-in PDF viewer
    warnings = [ln.strip() for ln in out.getvalue().splitlines() if re.search(r"\(security\.[WE]\d+\)", ln)
                and not any(i in ln for i in ignore)]
    if warnings:
        for w in warnings[:10]:
            f.add(cat, "Django deployment check", "warn", "low", w[:300], "See the Django deployment checklist.",
                  key=f"django-{re.search(r'security\.[WE]\d+', w).group(0)}")
    else:
        f.add(cat, "Django deployment check", "pass", detail="manage.py check --deploy: no unexpected warnings")


def _origin_base() -> str:
    return settings.PUBLIC_ORIGIN


def _check_access_control(f: _Findings):
    cat = "Authentication & access control"
    from apps.library.models import Document

    base = _origin_base()
    doc = Document.objects.order_by("created_at").first()
    probes = ["/api/documents", "/api/settings", "/api/family/members", "/api/security/antivirus", "/api/audit"]
    if doc:
        probes += [f"/api/documents/{doc.id}", f"/api/documents/{doc.id}/file?download=1"]
    leaked = []
    reachable = True
    for path in probes:
        try:
            r = _get(base + path)
        except requests.RequestException:
            reachable = False
            break
        if r.status_code < 300:
            leaked.append(f"{path} → HTTP {r.status_code}")
    if not reachable:
        f.add(cat, "Protected pages require sign-in", "warn", "medium", f"{base} was not reachable from the server.",
              "Check PD_PUBLIC_ORIGIN and the proxy, then run the test again.")
    elif leaked:
        f.add(cat, "Protected pages require sign-in", "fail", "critical", "; ".join(leaked)[:400], "Report this as a bug immediately.")
    else:
        f.add(cat, "Protected pages require sign-in", "pass", detail=f"{len(probes)} protected addresses refused anonymous access")
    # authorization smoke test: a member must not open another member's private document (real view, in process)
    from rest_framework.test import APIRequestFactory, force_authenticate

    from apps.accounts.models import User
    from apps.library import permissions as P
    from apps.library import views as lv

    members = list(User.objects.filter(is_active=True, is_main_admin=False, is_admin=False)[:5])
    tested, problems = 0, []
    for m in members:
        ctx = P.AccessContext.build(m)
        other = Document.objects.filter(archived_at__isnull=True).exclude(owner=m).order_by("created_at")[:20]
        for d in other:
            if ctx.doc_caps(d):
                continue  # legitimately shared with this member
            req = APIRequestFactory().get(f"/api/documents/{d.id}")
            force_authenticate(req, user=m)
            resp = lv.document_view(req, pk=d.id)
            tested += 1
            if resp.status_code < 400:
                problems.append(f"{m.username} opened a private document ({resp.status_code})")
            break
    if problems:
        f.add(cat, "Members cannot open other members' private documents", "fail", "critical", "; ".join(problems),
              "Report this as a bug immediately.")
    elif tested:
        f.add(cat, "Members cannot open other members' private documents", "pass", detail=f"{tested} member/document pair(s) tried")
    else:
        f.add(cat, "Members cannot open other members' private documents", "info", detail="Not enough members/documents to test.")
    from apps.accounts.passkeys import has_second_factor

    admins_2fa = all(has_second_factor(u) for u in User.objects.filter(Q(is_main_admin=True) | Q(is_admin=True), is_active=True))
    if admins_2fa:
        f.add(cat, "Administrators use two-step verification", "pass")
    else:
        f.add(cat, "Administrators use two-step verification", "warn", "high" if _internet() else "medium",
              "At least one administrator signs in with a password only.", "Add a passkey or authenticator app (My account → Security).")
    if int(config.get("security.escalation_failures") or 0) == 0:
        f.add(cat, "Repeated failed sign-ins are blocked", "warn", "medium", "Automatic blocking is off.",
              "Set 'Failed sign-ins before automatic block' in Settings → Security & access.")
    else:
        f.add(cat, "Repeated failed sign-ins are blocked", "pass")


def _check_web_baseline(f: _Findings):
    cat = "Web baseline (OWASP-style)"
    base = _origin_base()
    try:
        for path in ("/.env", "/.git/config", "/backend/personaldocs/settings.py", "/static/../../../etc/passwd", "/admin/"):
            r = _get(base + path)
            body = r.text[:2000] if r.status_code == 200 else ""
            exposed = r.status_code == 200 and any(s in body for s in ("SECRET", "[core]", "root:x:", "DATABASES", "Django administration"))
            if exposed:
                f.add(cat, f"No sensitive file at {path}", "fail", "critical", f"HTTP 200 with sensitive content at {path}",
                      "Block the path in the proxy and report the issue.", key=f"web-path-{path}")
        f.add(cat, "No sensitive files exposed", "pass", detail=".env, .git, settings, path traversal, admin probed", key="web-paths")
        r = _get(base + "/api/auth/google/start?mode=login&next=https://evil.example.org/")
        loc = r.headers.get("Location", "")
        if "evil.example.org" in urlsplit(loc).netloc:
            f.add(cat, "No open redirect", "fail", "high", f"Redirects to {loc[:100]}", "Report the issue.")
        else:
            f.add(cat, "No open redirect", "pass")
        r = requests.request("TRACE", base + "/api/session", timeout=10)
        if r.status_code == 200 and "TRACE" in r.text[:200]:
            f.add(cat, "HTTP TRACE disabled", "fail", "low", "TRACE is echoed.", "Disable TRACE in the proxy.")
        else:
            f.add(cat, "HTTP TRACE disabled", "pass")
        r = _get(base + "/api/session", headers={"Origin": "https://evil.example.org"})
        acao = r.headers.get("Access-Control-Allow-Origin", "")
        if acao in ("*", "https://evil.example.org"):
            f.add(cat, "No permissive CORS", "fail", "high", f"Access-Control-Allow-Origin: {acao}", "Remove CORS headers in the proxy.")
        else:
            f.add(cat, "No permissive CORS", "pass")
        server = r.headers.get("Server", "")
        if re.search(r"\d+\.\d+", server):
            f.add(cat, "Server version not disclosed", "warn", "low", f"Server: {server[:60]}", "Hide server tokens in the proxy.")
        else:
            f.add(cat, "Server version not disclosed", "pass")
    except requests.RequestException as exc:
        f.add(cat, "Web baseline reachable", "warn", "medium", f"{base} not reachable ({exc.__class__.__name__})",
              "Check PD_PUBLIC_ORIGIN and the proxy, then run the test again.")


def _check_uploads(f: _Findings):
    cat = "Upload security"
    from . import antivirus

    h = antivirus.health(refresh=True)
    if h.get("status") == "disabled":
        f.add(cat, "Antivirus scanning of uploads", "warn", "high" if _internet() else "medium", "ClamAV scanning is turned off.",
              "Turn on Settings → Security → Antivirus.")
    elif h.get("status") == "unavailable":
        f.add(cat, "Antivirus scanning of uploads", "fail", "high", h.get("error", ""), "sudo personaldocs repair; check clamav-daemon.")
    elif h.get("critically_stale"):
        f.add(cat, "Antivirus scanning of uploads", "fail", "high", f"Signatures {h.get('signature_age_days')} days old.",
              "Use Update now; check clamav-freshclam.")
    else:
        f.add(cat, "Antivirus scanning of uploads", "pass", detail=f"{h.get('engine', '')} signatures {h.get('signatures')}")
    f.add(cat, "File types decided by content, originals stored outside the web root", "pass",
          detail="Uploads are identified by their content and served only through authorised downloads with CSP sandbox.")


def _tool(name: str) -> str | None:
    cand = Path(sys.executable).parent / name
    return str(cand) if cand.exists() else shutil.which(name)


def _check_dependencies(f: _Findings):
    cat = "Dependencies"
    root = Path(settings.BASE_DIR).parent
    pa = _tool("pip-audit")
    req = root / "backend" / "requirements.txt"
    if pa and req.exists():
        try:
            p = subprocess.run([pa, "-r", str(req), "--format", "json", "--progress-spinner", "off"], capture_output=True,
                               text=True, timeout=300)
            data = json.loads(p.stdout or "{}")
            vulns = [(d["name"], d["version"], v) for d in data.get("dependencies", []) for v in d.get("vulns", [])]
            if vulns:
                for name, ver, v in vulns[:20]:
                    fix = ", ".join(v.get("fix_versions") or []) or "no fixed version yet"
                    f.add(cat, f"Python package {name}", "fail", "high", f"{name} {ver}: {v.get('id')} (fix: {fix})",
                          "Upgrade Personal DM (sudo personaldocs upgrade) once a release includes the fix.", key=f"pip-{name}-{v.get('id')}")
            else:
                f.add(cat, "Python dependencies (pip-audit)", "pass", detail=f"{len(data.get('dependencies', []))} packages checked")
        except (subprocess.SubprocessError, ValueError, OSError) as exc:
            f.add(cat, "Python dependencies (pip-audit)", "warn", "low", f"pip-audit failed: {exc.__class__.__name__}",
                  "The audit needs Internet access to the vulnerability database.")
    else:
        f.add(cat, "Python dependencies (pip-audit)", "warn", "low", "pip-audit is not installed.",
              "sudo personaldocs repair --with-security-tools")
    npm = shutil.which("npm")
    lock = root / "frontend" / "package-lock.json"
    if npm and lock.exists():
        try:
            p = subprocess.run([npm, "audit", "--omit=dev", "--json"], capture_output=True, text=True, timeout=180,
                               cwd=str(lock.parent))
            meta = json.loads(p.stdout or "{}").get("metadata", {}).get("vulnerabilities", {})
            bad = {k: meta.get(k, 0) for k in ("critical", "high", "moderate", "low") if meta.get(k)}
            if bad:
                sev = "critical" if bad.get("critical") else "high" if bad.get("high") else "medium" if bad.get("moderate") else "low"
                f.add(cat, "JavaScript dependencies (npm audit)", "fail" if sev in ("critical", "high") else "warn", sev,
                      ", ".join(f"{v} {k}" for k, v in bad.items()), "Upgrade Personal DM once a release includes the fix.")
            else:
                f.add(cat, "JavaScript dependencies (npm audit)", "pass")
        except (subprocess.SubprocessError, ValueError, OSError) as exc:
            f.add(cat, "JavaScript dependencies (npm audit)", "warn", "low", f"npm audit failed: {exc.__class__.__name__}")
    else:
        f.add(cat, "JavaScript dependencies (npm audit)", "warn", "low", "npm is not available on the server.",
              "Run npm audit in the source repository (CI does this for every release).")


SECRET_RX = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|"
                       r"xox[baprs]-[0-9A-Za-z-]{10,}|sk-[A-Za-z0-9]{32,}")


def _check_secrets(f: _Findings):
    cat = "Secrets & file permissions"
    root = Path(settings.BASE_DIR).parent
    hits, scanned = [], 0
    skip = {".venv", "node_modules", ".git", "__pycache__", "tests"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                if p.stat().st_size > 2_000_000:
                    continue
                text = p.read_text(errors="ignore")
            except OSError:
                continue
            scanned += 1
            for i, ln in enumerate(text.splitlines(), 1):
                if SECRET_RX.search(ln):
                    hits.append(f"{p.relative_to(root)}:{i}")  # never the secret itself
                    break
            if scanned > 20000:
                break
    if hits:
        f.add(cat, "No secrets in the application files", "fail", "high", "Possible secrets at: " + ", ".join(hits[:10]),
              "Remove the file, rotate the credential and upgrade from a clean release.")
    else:
        f.add(cat, "No secrets in the application files", "pass", detail=f"{scanned} files scanned")
    from apps.core import crypto

    loose = []
    for p in (crypto.key_path(), Path(settings.CONFIG_DIR) / "secret_key", Path(settings.CONFIG_DIR) / "personaldocs.env"):
        try:
            if p.exists() and p.stat().st_mode & (stat.S_IROTH | stat.S_IWOTH):
                loose.append(str(p))
        except OSError:
            pass
    for d in (Path(settings.DATA_DIR), Path(settings.ORIGINALS_DIR)):
        try:
            if d.exists() and d.stat().st_mode & stat.S_IRWXO:
                loose.append(str(d))
        except OSError:
            pass
    if loose:
        f.add(cat, "Keys and documents not readable by other users", "fail", "high", ", ".join(loose),
              "sudo personaldocs repair resets the permissions.")
    else:
        f.add(cat, "Keys and documents not readable by other users", "pass")


def _check_host(f: _Findings, inspect: dict, updates: dict):
    cat = "Host"
    from apps.ops import host

    if not inspect:
        f.add(cat, "Host checks", "warn", "medium", "The host helper is not installed or has not reported yet." if not host.installed()
              else "No host inspection result yet.", "sudo personaldocs repair installs the host helper.", key="host-missing")
    else:
        fw = inspect.get("firewall") or {}
        if fw.get("active"):
            f.add(cat, "Firewall active", "pass", detail=f"{fw.get('tool')}: {fw.get('rules', 0)} rule(s)", key="host-firewall")
        else:
            f.add(cat, "Firewall active", "fail" if _internet() else "warn", "high" if _internet() else "medium",
                  fw.get("summary") or "No active firewall.", "Enable ufw on the host and allow only SSH and the app port "
                  "(see the security center guide). Personal DM never changes firewall rules itself.", key="host-firewall")
        for s in inspect.get("exposed_local_only") or []:
            f.add(cat, f"{s['process'] or 'Service'} not exposed on port {s['port']}", "fail", "high",
                  f"Listening on {s['address']}:{s['port']}", "Bind it to localhost only.", key=f"host-exposed-{s['port']}")
        unexpected = [s for s in inspect.get("unexpected") or [] if s["port"] not in (5432, 3310)]
        if unexpected:
            f.add(cat, "No unexpected listening services", "warn", "medium",
                  ", ".join(f"{s['process'] or '?'} {s['address']}:{s['port']}" for s in unexpected[:10]),
                  "Stop services you do not need, or block them in the firewall.", key="host-unexpected")
        else:
            f.add(cat, "No unexpected listening services", "pass", key="host-unexpected")
        if inspect.get("reboot_required"):
            f.add(cat, "No reboot pending", "warn", "medium", "Updated packages need a reboot.", "Use Reboot server when convenient.",
                  key="host-reboot")
        else:
            f.add(cat, "No reboot pending", "pass", key="host-reboot")
    if updates.get("state") == "done":
        n = len(updates.get("pending") or [])
        if n:
            f.add(cat, "Debian security updates installed", "fail" if _internet() else "warn", "high" if _internet() else "medium",
                  f"{n} security update(s) pending", "Install them under Security → OS security updates.", key="host-updates")
        else:
            f.add(cat, "Debian security updates installed", "pass", key="host-updates")
    else:
        f.add(cat, "Debian security updates installed", "warn", "low", "Updates were not checked yet.",
              "Use Check for updates under Security → OS security updates.", key="host-updates")
    unit = Path("/etc/systemd/system/personaldocs-web.service")
    if unit.exists():
        hardened = "NoNewPrivileges=yes" in unit.read_text(errors="ignore")
        f.add(cat, "Service hardening", "pass" if hardened else "warn", "low", "NoNewPrivileges set" if hardened else
              "NoNewPrivileges missing", "sudo personaldocs repair reinstalls the service units.", key="host-units")


def summarize(findings: list[dict]) -> tuple[str, dict]:
    counts = {s: 0 for s in SEVERITIES}
    for x in findings:
        if x["status"] in ("warn", "fail"):
            counts[x["severity"]] += 1
    status = SecurityTestRun.PASSED
    if any(x["status"] == "fail" and x["severity"] in ("critical", "high") for x in findings):
        status = SecurityTestRun.FAILED
    elif any(x["status"] in ("warn", "fail") for x in findings):
        status = SecurityTestRun.WARNING
    return status, {"counts": counts, "checks": len(findings), "passed": sum(1 for x in findings if x["status"] == "pass")}


def run_security_test(run: SecurityTestRun) -> SecurityTestRun:
    f = _Findings()
    from apps.ops import host

    for step in (_check_https, _check_framework, _check_access_control, _check_web_baseline, _check_uploads,
                 _check_dependencies, _check_secrets):
        try:
            step(f)
        except Exception as exc:  # noqa: BLE001 - one failing category must not hide the others
            log.exception("security test step failed")
            f.add(step.__name__.replace("_check_", "").replace("_", " ").title(), "Check could not run", "warn", "low",
                  exc.__class__.__name__)
    _check_host(f, host.status("inspect") if host.status("inspect").get("state") == "done" else {}, host.status("check_updates"))
    status, summary = summarize(f.items)
    prev = SecurityTestRun.objects.filter(finished_at__isnull=False).exclude(pk=run.pk).order_by("-started_at").first()
    if prev:
        before = {x["id"] for x in prev.findings if x["status"] in ("warn", "fail")}
        now_bad = {x["id"] for x in f.items if x["status"] in ("warn", "fail")}
        summary["compared_to"] = prev.id
        summary["new"] = sorted(now_bad - before)
        summary["resolved"] = sorted(before - now_bad)
        for x in f.items:
            x["resolution"] = ("new" if x["id"] in now_bad - before else "persisting") if x["status"] in ("warn", "fail") else \
                ("resolved" if x["id"] in before else "")
    run.findings, run.summary, run.status, run.finished_at = f.items, summary, status, timezone.now()
    run.deployment = config.get("security.deployment")
    run.save()
    audit.record("security.test_finished", actor=run.started_by, target_type="security_test", target_id=str(run.id),
                 status=status, **{k: v for k, v in summary["counts"].items() if v})
    if status == SecurityTestRun.FAILED:
        from apps.notify import events

        for admin in events._admins():
            events.notify(admin, "security.operations", kind="security.operations", key=f"sectest:{run.id}",
                          title="Security test found Critical/High issues",
                          lines=[f"{summary['counts']['critical']} critical, {summary['counts']['high']} high finding(s).",
                                 "Deployment is not blocked, but the issues stay listed until they are resolved."],
                          link="/settings/security?view=test")
    return run


def start_security_test(actor) -> SecurityTestRun:
    if SecurityTestRun.objects.filter(status=SecurityTestRun.RUNNING, started_at__gt=timezone.now() - timedelta(hours=1)).exists():
        raise ValueError("A security test is already running.")
    run = SecurityTestRun.objects.create(started_by=actor, deployment=config.get("security.deployment"))
    audit.record("security.test_started", actor=actor, target_type="security_test", target_id=str(run.id))
    jobs.enqueue("security_test", {"run_id": run.id}, max_attempts=1, idempotency_key=f"sectest:{run.id}")
    from apps.ops import host

    if host.installed() and not host.running("inspect"):
        try:
            host.request("inspect", actor=actor)
        except host.HostError:
            pass
    return run


@jobs.handler("security_test")
def _job_security_test(job):
    run = SecurityTestRun.objects.filter(pk=job.payload["run_id"]).first()
    if run is None:
        return {"skipped": "missing"}
    try:
        run_security_test(run)
    except Exception as exc:  # noqa: BLE001
        run.status, run.finished_at = SecurityTestRun.ERROR, timezone.now()
        run.summary = {"error": exc.__class__.__name__}
        run.save()
        raise
    return {"status": run.status}


# ------------------------------------------------------------------ OS security updates and reboot

def pre_update_backup(actor=None) -> dict:
    """Database dump + settings snapshot before OS updates (an application backup, not a Proxmox/LXC snapshot)."""
    from apps.ops import backup

    dest = Path(settings.DATA_DIR) / "pre-update-backups" / timezone.now().strftime("%Y%m%d-%H%M%S")
    try:
        dest.mkdir(parents=True, exist_ok=False)
        os.chmod(dest.parent, 0o700)
        backup._dump_db(dest / "database.pgdump")
        (dest / "settings.json").write_text(json.dumps(config.snapshot_global(), indent=1, default=str))
    except Exception as exc:  # noqa: BLE001 - any failure blocks the update unless overridden
        shutil.rmtree(dest, ignore_errors=True)
        return {"ok": False, "detail": str(exc)[:300]}
    old = sorted(dest.parent.iterdir())[:-3]  # keep the newest three
    for p in old:
        shutil.rmtree(p, ignore_errors=True)
    return {"ok": True, "detail": str(dest)}


def sync_os_runs() -> None:
    """Copy finished helper results into OsUpdateRun rows (called when the page is viewed)."""
    from apps.ops import host

    for run in OsUpdateRun.objects.filter(status__in=("requested", "running")):
        st = host.status(run.action)
        if st.get("id") != run.request_id:
            continue
        if st.get("state") in ("done", "failed", "ignored", "rebooting"):
            run.status = st["state"]
            run.finished_at = timezone.now() if st["state"] != "rebooting" else None
            run.packages = [p["package"] for p in st.get("pending", [])] or st.get("installed", []) or run.packages
            run.log_name = st.get("log", "")[:80]
            run.reboot_required = st.get("reboot_required")
            run.error = (st.get("error") or "")[:500]
            run.save()
            if run.action == "install_updates":
                audit.record("security.os_updates_finished", target_type="os_update", target_id=str(run.id), status=run.status,
                             packages=len(run.packages))
        elif st.get("state") == "running" and run.status != "running":
            OsUpdateRun.objects.filter(pk=run.pk).update(status="running")
    # a reboot is complete once the host booted after it was requested
    for run in OsUpdateRun.objects.filter(action="reboot", status__in=("rebooting", "requested")):
        boot = boot_time()
        if boot and boot > run.requested_at:
            run.status, run.finished_at = "done", boot
            run.error = ""
            run.save()
            HealthState.put("post_reboot", run=run.id, checked_at=timezone.now().isoformat(), services=service_health())


def boot_time():
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        return timezone.now() - timedelta(seconds=uptime)
    except (OSError, ValueError):
        return None


def service_health() -> dict:
    from apps.notify.models import SchedulerRun

    from . import antivirus

    out = {"database": True}
    for name in ("worker_heartbeat", "scheduler_heartbeat"):
        row = SchedulerRun.objects.filter(name=name).first()
        out[name.replace("_heartbeat", "")] = bool(row and row.last_run_at and timezone.now() - row.last_run_at < timedelta(minutes=5))
    out["antivirus"] = antivirus.health(refresh=True).get("status") if config.get("antivirus.enabled") else "disabled"
    return out


def reboot_preflight() -> dict:
    from django.contrib.sessions.models import Session

    from apps.core.models import Job

    active_sessions = Session.objects.filter(expire_date__gt=timezone.now()).count()
    running = list(Job.objects.filter(status="running").values_list("kind", flat=True))
    queued = Job.objects.filter(status="queued").count()
    return {"active_sessions": active_sessions, "running_jobs": running, "queued_jobs": queued,
            "warnings": [w for w in (
                f"{active_sessions} signed-in session(s) will be interrupted." if active_sessions else "",
                f"Background work in progress: {', '.join(sorted(set(running)))} (OCR, antivirus or Local AI). The worker "
                "finishes its current job before the reboot." if running else "",
                f"{queued} queued job(s) continue after the reboot." if queued else "") if w]}


# ------------------------------------------------------------------ Security Health score

WEIGHTS = {"antivirus": 20, "https": 20, "security_test": 20, "os_updates": 15, "firewall": 10, "reboot": 10, "authentik": 5}


def security_health() -> dict:
    """Score 0–100 from the weighted components below, plus forcing conditions that set At Risk regardless of it."""
    from apps.library.models import DocumentVersion
    from apps.ops import host

    from . import antivirus

    comp, forced = {}, []

    def put(key, points, status, detail, link):
        comp[key] = {"points": points, "max": WEIGHTS[key], "status": status, "detail": detail, "link": link}

    av = antivirus.health()
    av_link = "/settings/security?view=antivirus"
    if av.get("status") == "disabled":
        put("antivirus", 0, "bad", "Antivirus scanning is off", av_link)
    elif av.get("status") == "unavailable":
        put("antivirus", 0, "bad", "ClamAV is unavailable", av_link)
    elif av.get("critically_stale"):
        put("antivirus", 5, "bad", f"Signatures {av.get('signature_age_days')} days old", av_link)
        forced.append("Antivirus definitions are critically out of date.")
    elif av.get("stale"):
        put("antivirus", 12, "warn", f"Signatures {av.get('signature_age_days')} days old", av_link)
    else:
        put("antivirus", 20, "ok", f"Signatures {av.get('signatures') or '?'}", av_link)
    threats = DocumentVersion.objects.filter(av_status__in=("threat", "quarantined")).count()
    if threats:
        forced.append(f"{threats} file(s) with detected malware in quarantine.")

    hs = https_state()
    link = "/settings/security?view=test"
    if _internet():
        if hs.get("https_ok"):
            put("https", 20, "ok", "Internet Ready: HTTPS checks passed", link)
        else:
            put("https", 0, "bad", "Internet-facing but HTTPS checks failed or not run", link)
            forced.append("HTTPS/TLS is not valid on an Internet-facing deployment.")
    else:
        put("https", 15, "warn" if not hs.get("https_ok") else "ok", "LAN only (not Internet Ready)", link)

    last = SecurityTestRun.objects.exclude(status=SecurityTestRun.RUNNING).first()
    if last is None:
        put("security_test", 5, "warn", "No security test run yet", link)
    else:
        crit = any(x["status"] == "fail" and x["severity"] == "critical" for x in last.findings)
        age = (timezone.now() - last.started_at).days
        if crit:
            put("security_test", 0, "bad", "Unresolved Critical findings", link)
            forced.append("The latest security test has unresolved Critical findings.")
        elif last.status == SecurityTestRun.FAILED:
            put("security_test", 5, "bad", "High findings in the latest test", link)
        elif last.status == SecurityTestRun.WARNING:
            put("security_test", 12, "warn", f"Warnings ({age} days ago)", link)
        else:
            put("security_test", 20 if age <= 90 else 10, "ok" if age <= 90 else "warn", f"Passed {age} days ago", link)

    upd = host.status("check_updates")
    ulink = "/settings/security?view=updates"
    if upd.get("state") != "done":
        put("os_updates", 7, "warn", "Not checked yet", ulink)
    elif upd.get("pending"):
        put("os_updates", 5, "bad", f"{len(upd['pending'])} security update(s) pending", ulink)
    else:
        put("os_updates", 15, "ok", "No pending security updates", ulink)

    insp = host.status("inspect")
    flink = "/settings/security?view=firewall"
    fw = insp.get("firewall") if insp.get("state") == "done" else None
    if fw is None:
        put("firewall", 5, "warn", "Not checked yet", flink)
    elif fw.get("active"):
        put("firewall", 10, "ok", f"{fw.get('tool')} active", flink)
    else:
        put("firewall", 0 if _internet() else 5, "bad" if _internet() else "warn", "Firewall not active", flink)
        if _internet():
            forced.append("The firewall is disabled on an Internet-facing deployment.")

    rr = host.reboot_required()
    if rr is None:
        put("reboot", 8, "warn", "Unknown", ulink)
    elif rr:
        put("reboot", 3, "warn", "Reboot required", ulink)
    else:
        put("reboot", 10, "ok", "No reboot needed", ulink)

    alink = "/settings/authentication"
    if not config.get("authentik.enabled"):
        put("authentik", 5, "ok", "Not used (local sign-in)", alink)
    else:
        from apps.accounts import authentik

        try:
            authentik.discovery()
            put("authentik", 5, "ok", "Reachable", alink)
        except authentik.OIDCError as exc:
            put("authentik", 1, "warn", f"Not reachable: {str(exc)[:80]} (local sign-in still works)", alink)

    score = sum(c["points"] for c in comp.values())
    band = "Healthy" if score >= 90 else "Attention" if score >= 70 else "At Risk"
    return {"score": score, "band": band, "status": "At Risk" if forced else band, "forced": forced, "components": comp,
            "weights": WEIGHTS, "internet_ready": hs.get("internet_ready", False), "deployment": config.get("security.deployment")}


# ------------------------------------------------------------------ security records: retention and purge

PURGE_CATEGORIES = {
    "antivirus": "Antivirus events",
    "authentication": "Sign-in records and authentik events",
    "security_tests": "Security-test history",
    "os_updates": "OS update and reboot records (with their logs)",
    "alerts": "Security alerts and policy events",
}


def _querysets(category: str, before):
    from apps.core.models import AuditEvent
    from apps.library.models import DocumentVersion

    from .models import LoginEvent

    protected_audit = Q(action="security.log_purge")
    if category == "antivirus":
        quarantined = [str(v) for v in DocumentVersion.objects.filter(av_status__in=("quarantined", "threat")).values_list("id", flat=True)]
        qs = AuditEvent.objects.filter(action__startswith="antivirus.", at__lt=before)
        protected = qs.filter(target_id__in=quarantined)
        return [(qs.exclude(target_id__in=quarantined), 300)], protected.count()
    if category == "authentication":
        return [(LoginEvent.objects.filter(at__lt=before), 250),
                (AuditEvent.objects.filter(Q(action__startswith="auth.authentik"), at__lt=before), 300)], 0
    if category == "security_tests":
        latest = SecurityTestRun.objects.order_by("-started_at").values_list("id", flat=True).first()
        qs = SecurityTestRun.objects.filter(started_at__lt=before)
        return [(qs.exclude(pk=latest), 6000)], qs.filter(pk=latest).count()
    if category == "os_updates":
        return [(OsUpdateRun.objects.filter(requested_at__lt=before), 600),
                (AuditEvent.objects.filter(action__startswith="host.", at__lt=before), 300)], 0
    if category == "alerts":
        qs = AuditEvent.objects.filter(Q(action__startswith="security.") | Q(action__startswith="settings.access"), at__lt=before)
        return [(qs.exclude(protected_audit), 300)], qs.filter(protected_audit).count()
    raise ValueError("Unknown category")


def _host_logs(before) -> list[Path]:
    d = Path(settings.DATA_DIR) / "host" / "logs"
    if not d.exists():
        return []
    ts = before.timestamp()
    return [p for p in d.iterdir() if p.is_file() and p.stat().st_mtime < ts]


def purge_preview(categories: list[str], older_than_days: int) -> dict:
    before = timezone.now() - timedelta(days=older_than_days)
    out = {"before": before.isoformat(), "older_than_days": older_than_days, "categories": [], "total_records": 0,
           "estimated_bytes": 0, "protected": 0,
           "below_retention": older_than_days < int(config.get("security.log_retention_days"))}
    for c in categories:
        sets, protected = _querysets(c, before)
        count = sum(qs.count() for qs, _ in sets)
        est = sum(qs.count() * size for qs, size in sets)
        files = _host_logs(before) if c == "os_updates" else []
        est += sum(p.stat().st_size for p in files)
        out["categories"].append({"key": c, "label": PURGE_CATEGORIES[c], "records": count, "files": len(files),
                                  "estimated_bytes": est, "protected": protected})
        out["total_records"] += count
        out["estimated_bytes"] += est
        out["protected"] += protected
    out["protected_note"] = ("Kept: the record of every purge, records about files still in quarantine and the latest "
                             "security test. Original documents are never touched.")
    return out


def purge(categories: list[str], older_than_days: int, *, actor, request=None) -> dict:
    preview = purge_preview(categories, older_than_days)
    before = timezone.now() - timedelta(days=older_than_days)
    removed = {}
    for c in categories:
        sets, _ = _querysets(c, before)
        removed[c] = sum(qs.delete()[0] for qs, _ in sets)
        if c == "os_updates":
            for p in _host_logs(before):
                p.unlink(missing_ok=True)
    # recorded after the deletion, so the same purge can never erase its own record
    audit.record("security.log_purge", request=request, actor=actor, older_than_days=older_than_days,
                 categories=categories, **{f"removed_{k}": v for k, v in removed.items()},
                 estimated_bytes=preview["estimated_bytes"])
    return {"removed": removed, "preview": preview}


def apply_retention() -> dict:
    days = max(365, int(config.get("security.log_retention_days")))
    before = timezone.now() - timedelta(days=days)
    out = {}
    for c in ("antivirus", "security_tests", "os_updates", "alerts"):
        sets, _ = _querysets(c, before)
        out[c] = sum(qs.delete()[0] for qs, _ in sets)
    for p in _host_logs(before):
        p.unlink(missing_ok=True)
    return out


# ------------------------------------------------------------------ Storage Health

def _dir_size(path: Path, classify=None) -> tuple[int, dict]:
    total, parts = 0, {}
    if not path.exists():
        return 0, parts
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                size = (Path(dirpath) / name).lstat().st_size
            except OSError:
                continue
            total += size
            if classify:
                k = classify(name)
                parts[k] = parts.get(k, 0) + size
    return total, parts


def _derivative_kind(name: str) -> str:
    return "ocr" if "searchable" in name or name.endswith(".hocr") or "ocr" in name else "previews"


def storage_health(refresh: bool = False) -> dict:
    cached = HealthState.get("storage")
    if not refresh and cached.get("checked_at") and \
            timezone.now() - datetime.fromisoformat(cached["checked_at"]) < timedelta(minutes=10):
        return cached
    data_dir = Path(settings.DATA_DIR)
    du = shutil.disk_usage(data_dir if data_dir.exists() else Path("/"))
    originals, _ = _dir_size(Path(settings.ORIGINALS_DIR))
    deriv_total, deriv = _dir_size(Path(settings.DERIVATIVES_DIR), _derivative_kind)
    quarantine, _ = _dir_size(data_dir / "quarantine")
    tmp = sum(_dir_size(Path(p))[0] for p in (settings.TMP_DIR, settings.STAGING_DIR, settings.EXPORT_TMP_DIR))
    logs = _dir_size(data_dir / "host" / "logs")[0] + _dir_size(Path("/var/log/personaldocs"))[0]
    if settings.ACCESS_LOG and Path(settings.ACCESS_LOG).exists():
        logs += Path(settings.ACCESS_LOG).stat().st_size
    backups = _dir_size(data_dir / "pre-update-backups")[0]
    try:
        from apps.ops.backup import last_backup_status

        backups_remote = (last_backup_status() or {}).get("bytes")
    except Exception:  # noqa: BLE001
        backups_remote = None
    db_bytes = None
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())")
            db_bytes = cur.fetchone()[0]
    pct = round(du.used / du.total * 100, 1) if du.total else 0
    warn, crit = int(config.get("storage.warn_percent")), int(config.get("storage.critical_percent"))
    status = "critical" if pct >= crit else "warning" if pct >= warn else "ok"
    data = {"total": du.total, "used": du.used, "free": du.free, "percent": pct, "status": status,
            "thresholds": {"warning": warn, "critical": crit},
            "categories": [
                {"key": "documents", "label": "Documents (originals)", "bytes": originals},
                {"key": "previews", "label": "Previews and thumbnails", "bytes": deriv.get("previews", 0)},
                {"key": "ocr", "label": "OCR data (searchable copies)", "bytes": deriv.get("ocr", 0)},
                {"key": "database", "label": "Database (metadata, text, logs)", "bytes": db_bytes},
                {"key": "logs", "label": "Security and application log files", "bytes": logs},
                {"key": "quarantine", "label": "Antivirus quarantine", "bytes": quarantine},
                {"key": "backups", "label": "Local pre-update backups", "bytes": backups},
                {"key": "temporary", "label": "Temporary files and caches", "bytes": tmp},
            ], "last_backup_bytes": backups_remote, "data_dir": str(data_dir), "checked_at": timezone.now().isoformat()}
    HealthState.put("storage", **data)
    return data


def storage_alerts() -> str:
    h = storage_health(refresh=True)
    if h["status"] in ("warning", "critical"):
        from apps.notify import events

        day = timezone.localdate().isoformat()
        for admin in events._admins():
            events.notify(admin, "security.operations", kind="security.operations", key=f"storage:{h['status']}:{day}",
                          title=f"Storage {h['status']}: {h['percent']}% used",
                          lines=[f"{h['free'] // (1024 ** 3)} GB free. Review Storage Health for safe cleanup options.",
                                 "Original documents are never deleted automatically."],
                          link="/settings/security?view=storage")
    return h["status"]


def _orphan_derivatives() -> list[Path]:
    from apps.library.models import DocumentVersion

    root = Path(settings.DERIVATIVES_DIR)
    if not root.exists():
        return []
    known = {str(v) for v in DocumentVersion.objects.values_list("id", flat=True)}
    out = []
    for p in root.rglob("*"):
        if p.is_dir() and re.fullmatch(r"[0-9a-f-]{36}", p.name) and p.name not in known:
            out.append(p)
    return out


def _old_tmp(hours: int = 24) -> list[Path]:
    cutoff = timezone.now().timestamp() - hours * 3600
    out = []
    for d in (settings.TMP_DIR, settings.STAGING_DIR, settings.EXPORT_TMP_DIR):
        d = Path(d)
        if d.exists():
            out += [p for p in d.iterdir() if p.stat().st_mtime < cutoff]
    return out


def _size(p: Path) -> int:
    return _dir_size(p)[0] if p.is_dir() else (p.stat().st_size if p.exists() else 0)


CLEANUP_KINDS = {
    "temporary": "Temporary files older than 24 hours",
    "orphan_previews": "Previews/OCR copies of files that no longer exist (regenerable)",
    "expired_security_records": "Security records older than the retention period",
}


def cleanup_analysis() -> dict:
    retention = int(config.get("security.log_retention_days"))
    sec = purge_preview(list(PURGE_CATEGORIES), retention)
    items = [
        {"key": "temporary", "label": CLEANUP_KINDS["temporary"], "count": len(_old_tmp()), "bytes": sum(_size(p) for p in _old_tmp())},
        {"key": "orphan_previews", "label": CLEANUP_KINDS["orphan_previews"], "count": len(_orphan_derivatives()),
         "bytes": sum(_size(p) for p in _orphan_derivatives())},
        {"key": "expired_security_records", "label": CLEANUP_KINDS["expired_security_records"], "count": sec["total_records"],
         "bytes": sec["estimated_bytes"]},
    ]
    return {"items": items, "total_bytes": sum(i["bytes"] for i in items),
            "never": ["Original documents", "Quarantined files (use the quarantine review instead)", "Backups on the NAS "
                      "(pruned only by the backup retention setting)"]}


def cleanup(kinds: list[str], *, actor, request=None) -> dict:
    """Removes only regenerable or expired data. Original documents and quarantine are never touched."""
    out = {}
    if "temporary" in kinds:
        files = _old_tmp()
        out["temporary"] = sum(_size(p) for p in files)
        for p in files:
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    if "orphan_previews" in kinds:
        dirs = _orphan_derivatives()
        out["orphan_previews"] = sum(_size(p) for p in dirs)
        for p in dirs:
            shutil.rmtree(p, ignore_errors=True)
    if "expired_security_records" in kinds:
        out["expired_security_records"] = apply_retention()
    audit.record("storage.cleanup", request=request, actor=actor, kinds=kinds)
    HealthState.objects.filter(key="storage").delete()
    return out
