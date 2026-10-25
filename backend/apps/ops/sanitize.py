"""Server-side sanitisation of maintenance output (Change Set AB).

``redact(text)`` removes secrets before anything is shown or downloaded: passwords, API keys and tokens, session
cookies, database URLs with credentials, OAuth/OIDC secrets, SMTP/NAS credentials, AI provider keys, notification
tokens, backup/recovery keys and private keys. Two layers:

1. **Known values** — every secret this installation actually holds (secret settings, the Django secret key, the
   database password, encrypted integration secrets, AI keys, NAS/destination credentials) is replaced literally,
   whatever text surrounds it.
2. **Patterns** — common secret shapes (``password=…``, ``Authorization: Bearer …``, ``sk-…``, ``ghp_…``,
   ``postgres://user:pass@``, PEM private keys, recovery-key words …), for secrets this installation does not know.

``anonymize(text)`` is only for the optional **Sanitized Support Report**: it additionally replaces IP addresses,
user names, host names, document paths/names and Trusted Zone / network names with stable placeholders. It works on
a copy; application records are never changed. Internal Main Admin security views keep the full-IP policy.
"""
from __future__ import annotations

import ipaddress
import re

REDACTED = "[REDACTED]"

_PATTERNS = [
    # PEM private keys (multi-line)
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED PRIVATE KEY]"),
    # URLs with credentials: scheme://user:password@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)([^/\s:@]+):([^@\s/]+)@"), r"\1\2:" + REDACTED + "@"),
    # HTTP auth headers and bearer tokens
    (re.compile(r"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*(bearer|basic|token)?\s*[^\s,;]+"), r"\1: " + REDACTED),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{6,}"), "Bearer " + REDACTED),
    # cookies: Django session/CSRF and the app's own cookies
    (re.compile(r"(?i)\b(sessionid|csrftoken|pd_session\w*|pd_csrftoken|pd_device)=[^;\s]+"), r"\1=" + REDACTED),
    # key=value / key: value / "key": "value" for secret-looking keys
    (re.compile(r"""(?ix)
        (["']?\b[\w.\-]*(?:password|passwd|pwd|secret|token|api[_\-]?key|apikey|access[_\-]?key|private[_\-]?key|
           client[_\-]?secret|license[_\-]?key|webhook|auth[_\-]?key|recovery[_\-]?key|signing[_\-]?key|
           encryption[_\-]?key|bot[_\-]?token|credentials?)[\w.\-]*["']?)
        (\s*[:=]\s*)
        (?:"[^"]*"|'[^']*'|[^\s,;&]+)"""), r"\1\2" + REDACTED),
    # well-known token formats
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{10,}|github_pat_[A-Za-z0-9_]{20,})"), REDACTED),
    (re.compile(r"\bsk-(?:ant-|or-|proj-)?[A-Za-z0-9_\-]{12,}"), REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), REDACTED),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), REDACTED),
    (re.compile(r"\b\d{6,12}:AA[A-Za-z0-9_\-]{30,}\b"), REDACTED),  # Telegram bot token
    (re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+"), "https://discord.com/api/webhooks/" + REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    # Fernet keys / long base64 secrets on their own
    (re.compile(r"\b[A-Za-z0-9_\-]{43}=(?![A-Za-z0-9])"), REDACTED),
]


def known_secrets() -> list[str]:
    """Every secret value this installation holds, longest first. Values shorter than 6 characters are skipped (they
    would mangle ordinary words)."""
    out: set[str] = set()

    def add(v):
        if isinstance(v, str) and len(v.strip()) >= 6:
            out.add(v.strip())

    try:
        from django.conf import settings

        add(getattr(settings, "SECRET_KEY", ""))
        db = settings.DATABASES.get("default", {})
        add(db.get("PASSWORD", ""))
    except Exception:  # noqa: BLE001 - sanitising must never fail
        pass
    try:
        from apps.core import config
        from apps.core.registry import SETTINGS

        for s in SETTINGS:
            if s.secret:
                try:
                    add(config.get(s.key))
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass
    try:
        from apps.ai.models import AIProfile
        from apps.core import crypto

        for enc in AIProfile.objects.exclude(api_key_enc="").values_list("api_key_enc", flat=True):
            try:
                add(crypto.decrypt(enc))
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    try:
        from apps.core import crypto

        add(crypto.key_path().read_text())
    except Exception:  # noqa: BLE001
        pass
    try:
        from apps.ops.models import BackupDestination

        for cfg in BackupDestination.objects.values_list("config", flat=True):
            for k, v in (cfg or {}).items():
                if any(w in k.lower() for w in ("pass", "secret", "key", "token")):
                    add(v)
    except Exception:  # noqa: BLE001
        pass
    return sorted(out, key=len, reverse=True)


def redact(text: str, *, secrets: list[str] | None = None) -> str:
    if not text:
        return ""
    for value in (known_secrets() if secrets is None else secrets):
        text = text.replace(value, REDACTED)
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text


def redact_obj(value, *, secrets: list[str] | None = None):
    """Redact every string inside a JSON-like structure (details, results)."""
    secrets = known_secrets() if secrets is None else secrets
    if isinstance(value, str):
        return redact(value, secrets=secrets)
    if isinstance(value, list):
        return [redact_obj(v, secrets=secrets) for v in value]
    if isinstance(value, dict):
        return {k: (REDACTED if isinstance(k, str) and re.search(r"(?i)password|secret|token|api_?key", k) and isinstance(v, str) and v
                    else redact_obj(v, secrets=secrets)) for k, v in value.items()}
    return value


# ------------------------------------------------------------------ support-report anonymisation

_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IPV6 = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])")
_UNC = re.compile(r"(?:\\\\|//)[A-Za-z0-9._\-]+[\\/][^\s'\"]+")
_FILE = re.compile(r"(?<![\w/])(?:/[\w.\-]+)+/([\w .\-]+\.(?:pdf|jpe?g|png|tiff?|webp|heic|docx?|xlsx?|odt|txt|eml|msg|dcm))\b", re.I)


class _Mapper:
    def __init__(self, prefix: str):
        self.prefix, self.seen = prefix, {}

    def __call__(self, value: str) -> str:
        if value not in self.seen:
            self.seen[value] = f"{self.prefix}-{len(self.seen) + 1}"
        return self.seen[value]


def anonymize(text: str, *, names: list[str] | None = None, hosts: list[str] | None = None,
              zones: list[str] | None = None) -> str:
    """The Sanitized Support Report: redacted, then IP addresses, user names, host names, document paths/names and
    network names replaced by stable placeholders (ip-1, user-1, host-1, file-1.pdf, zone-1). Loopback addresses
    stay (they reveal nothing and help the reader)."""
    text = redact(text)
    names = _defaults_names() if names is None else names
    hosts = _defaults_hosts() if hosts is None else hosts
    zones = _defaults_zones() if zones is None else zones
    for kind, values in (("zone", zones), ("host", hosts), ("user", names)):
        m = _Mapper(kind)
        for v in sorted({v for v in values if v and len(v) >= 3}, key=len, reverse=True):
            text = re.sub(rf"(?<![\w]){re.escape(v)}(?![\w])", m(v), text, flags=re.I)
    ip_map = _Mapper("ip")

    def ip_sub(mt):
        try:
            ip = ipaddress.ip_address(mt.group(0))
        except ValueError:
            return mt.group(0)
        return mt.group(0) if ip.is_loopback or ip.is_unspecified else ip_map(str(ip))

    text = _IPV4.sub(ip_sub, text)
    text = _IPV6.sub(ip_sub, text)
    text = _UNC.sub("//nas-share/[path]", text)
    files = _Mapper("file")
    text = _FILE.sub(lambda mt: f"[path]/{files(mt.group(1))}.{mt.group(1).rsplit('.', 1)[-1].lower()}", text)
    return text


def _defaults_names() -> list[str]:
    try:
        from apps.accounts.models import User

        out = []
        for username, display, full in User.objects.values_list("username", "display_name", "full_name"):
            out += [username, display, full]
        return out
    except Exception:  # noqa: BLE001
        return []


def _defaults_hosts() -> list[str]:
    import socket
    from urllib.parse import urlparse

    out = []
    try:
        out.append(socket.gethostname())
    except OSError:
        pass
    try:
        from django.conf import settings

        out.append(urlparse(settings.PUBLIC_ORIGIN).hostname or "")
    except Exception:  # noqa: BLE001
        pass
    return out


def _defaults_zones() -> list[str]:
    try:
        from apps.security.models import TrustedZone

        return list(TrustedZone.objects.values_list("name", flat=True))
    except Exception:  # noqa: BLE001
        return []
