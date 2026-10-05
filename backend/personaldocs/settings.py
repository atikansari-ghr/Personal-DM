"""Django settings for Personal Documents.

All deployment-specific values come from environment variables, normally loaded by
systemd from /etc/personaldocs/personaldocs.env. Nothing secret lives in the repository.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"PD_{name}", default)


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DEBUG", False)

# Data/config locations (production defaults; overridden in development via env)
DATA_DIR = Path(env("DATA_DIR", "/var/lib/personaldocs"))
CONFIG_DIR = Path(env("CONFIG_DIR", "/etc/personaldocs"))
STORAGE_DIR = DATA_DIR / "storage"
ORIGINALS_DIR = STORAGE_DIR / "originals"
DERIVATIVES_DIR = STORAGE_DIR / "derivatives"
STAGING_DIR = DATA_DIR / "staging"
TMP_DIR = DATA_DIR / "tmp"
EXPORT_TMP_DIR = DATA_DIR / "exports"

_secret = env("SECRET_KEY")
if not _secret:
    key_file = CONFIG_DIR / "secret_key"
    if key_file.exists():
        _secret = key_file.read_text().strip()
if not _secret:
    if DEBUG or env_bool("TESTING"):
        _secret = "dev-insecure-secret-key-not-for-production"
    else:
        raise RuntimeError("PD_SECRET_KEY or /etc/personaldocs/secret_key is required")
SECRET_KEY = _secret

ALLOWED_HOSTS = [h.strip() for h in (env("ALLOWED_HOSTS", "localhost,127.0.0.1") or "").split(",") if h.strip()]
PUBLIC_ORIGIN = (env("PUBLIC_ORIGIN", "http://localhost:8000") or "").rstrip("/")
CSRF_TRUSTED_ORIGINS = [PUBLIC_ORIGIN] + [
    o.strip() for o in (env("CSRF_TRUSTED_ORIGINS", "") or "").split(",") if o.strip()
]

# Optional direct access from the home network over plain HTTP (opt-in, e.g. http://192.168.10.195:8000;
# `personaldocs local-access on`). The public HTTPS address keeps Secure cookies; see LocalAccessCookieMiddleware.
LOCAL_ORIGINS = []
for _o in (env("LOCAL_ORIGINS", "") or "").split(","):
    _o = _o.strip().rstrip("/")
    _u = urlsplit(_o)
    if _u.scheme in ("http", "https") and _u.hostname:
        LOCAL_ORIGINS.append(_o)
        if _u.hostname not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_u.hostname)
        CSRF_TRUSTED_ORIGINS.append(_o)
LOCAL_HOSTS = {urlsplit(o).netloc for o in LOCAL_ORIGINS}

# Reverse proxy (NPM / Pangolin) support. Only enable when the app is reachable solely via the proxy.
if env_bool("BEHIND_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
TRUSTED_PROXY_IPS = [i.strip() for i in (env("TRUSTED_PROXY_IPS", "127.0.0.1") or "").split(",") if i.strip()]
# Privacy-safe access log for Traffic analytics (GoAccess). Empty disables it.
ACCESS_LOG = env("ACCESS_LOG", "") or ""

SECURE_COOKIES = PUBLIC_ORIGIN.startswith("https://")
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_NAME = "pd_session"
CSRF_COOKIE_NAME = "pd_csrftoken"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "SAMEORIGIN"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "apps.core",
    "apps.accounts",
    "apps.library",
    "apps.notify",
    "apps.mailimport",
    "apps.ops",
    "apps.security",
    "apps.ai",
]

MIDDLEWARE = [
    "apps.security.traffic.AccessLogMiddleware",  # outermost: logs the final status (incl. policy denials)
    "apps.core.middleware.LocalAccessCookieMiddleware",  # adjusts the final response
    "apps.security.middleware.AccessPolicyMiddleware",  # country/IP policy, before sessions and authentication
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.AccountStateMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "personaldocs.urls"
WSGI_APPLICATION = "personaldocs.wsgi.application"

FRONTEND_DIST = Path(env("FRONTEND_DIST", str(REPO_DIR / "frontend" / "dist")))

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "personaldocs"),
        "USER": env("DB_USER", "personaldocs"),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "127.0.0.1"),
        "PORT": env("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "ATOMIC_REQUESTS": False,
    }
}

AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"  # stored timestamps are UTC; the installation display timezone is an app setting
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [d for d in [FRONTEND_DIST / "assets"] if d.exists()]
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.exists() else None

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_TEMP_DIR = str(TMP_DIR) if TMP_DIR.exists() else None
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000
DATA_UPLOAD_MAX_NUMBER_FILES = 500

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.auth.CsrfSessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["apps.accounts.auth.IsActiveAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "EXCEPTION_HANDLER": "apps.core.api.exception_handler",
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

# Processing tools (paths configurable so Debian packages or alternatives can be used)
OCRMYPDF_CMD = (env("OCRMYPDF_CMD", "ocrmypdf") or "ocrmypdf").split()
TESSERACT_CMD = env("TESSERACT_CMD", "tesseract")
SOFFICE_CMD = env("SOFFICE_CMD", "soffice")
PDFTOPPM_CMD = env("PDFTOPPM_CMD", "pdftoppm")
VERAPDF_CMD = env("VERAPDF_CMD", "verapdf")
PG_DUMP_CMD = env("PG_DUMP_CMD", "pg_dump")
PG_RESTORE_CMD = env("PG_RESTORE_CMD", "pg_restore")
PROCESS_MEMORY_LIMIT_MB = int(env("PROCESS_MEMORY_LIMIT_MB", "1536") or 1536)

APP_VERSION = (REPO_DIR / "VERSION").read_text().strip() if (REPO_DIR / "VERSION").exists() else "0.0.0"
DOCS_DIR = REPO_DIR / "docs"

EMAIL_BACKEND = "apps.notify.mailer.RegistryEmailBackend"

LOG_DIR = Path(env("LOG_DIR", str(DATA_DIR / "logs")))
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact": {"()": "apps.core.logging.RedactFilter"}},
    "formatters": {
        "json": {"()": "apps.core.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json", "filters": ["redact"]},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"level": "WARNING"},
        "django.db.backends": {"level": "WARNING"},
    },
}
