from django.conf import settings


class LocalAccessCookieMiddleware:
    """Lets sign-in work on an opted-in plain-HTTP home-network address (PD_LOCAL_ORIGINS).

    Browsers drop cookies marked Secure on http:// pages, so for requests to exactly such an address (and only
    when the request itself is not HTTPS) the session and CSRF cookies are sent without the Secure flag. The
    public HTTPS address is unaffected. The Cross-Origin-Opener-Policy header is dropped there too, because
    browsers ignore it on non-HTTPS pages and log an error. Listed first in MIDDLEWARE so it sees the final response.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        hosts = getattr(settings, "LOCAL_HOSTS", ())
        if hosts and not request.is_secure() and request.META.get("HTTP_HOST", "") in hosts:
            for name in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
                if name in response.cookies:
                    response.cookies[name]["secure"] = ""
            if "Cross-Origin-Opener-Policy" in response:
                del response["Cross-Origin-Opener-Policy"]
        return response


class SecurityHeadersMiddleware:
    """Adds a strict CSP and disables caching of API/file responses."""

    CSP = (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src 'self' blob:; "
        "object-src 'none'; base-uri 'self'; form-action 'self' https://accounts.google.com; "
        "frame-ancestors 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    _tiles = {"at": 0.0, "origin": "", "key": None}

    @classmethod
    def tile_origin(cls) -> str:
        """Origin of the configured map tile server (map data and the availability probe).

        Every worker process re-reads the map settings (one small query) and recomputes the origin when they changed,
        so a new provider is allowed by every worker at once (Change Set V: a per-process one-minute cache let other
        workers keep sending the old Content-Security-Policy, which blocked the new provider)."""
        import time

        try:
            from .models import AppSetting

            key = tuple(AppSetting.objects.filter(key__startswith="security.map_").order_by("key").values_list("key", "value"))
        except Exception:  # noqa: BLE001 - before migrations / without a database
            return ""
        if key != cls._tiles["key"] or time.monotonic() - cls._tiles["at"] > 300:
            try:
                from apps.security import mapprov

                origin = mapprov.tile_origin()
            except Exception:  # noqa: BLE001
                origin = ""
            cls._tiles.update(at=time.monotonic(), origin=origin, key=key)
        return cls._tiles["origin"]

    def __call__(self, request):
        response = self.get_response(request)
        tiles = self.tile_origin()
        # images and the one-tile availability probe (fetch) may reach the configured tile server only
        csp = (self.CSP.replace("img-src 'self' data: blob:", f"img-src 'self' data: blob: {tiles}") + f"; connect-src 'self' {tiles}") if tiles else self.CSP
        response.setdefault("Content-Security-Policy", csp)
        response.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=(self)")
        path = request.path
        if path.startswith("/api/") or path.startswith("/s/"):
            # Sensitive data must never land in shared/browser caches.
            response["Cache-Control"] = "no-store, private"
            response["Pragma"] = "no-cache"
        return response


class RecoveryInProgressMiddleware:
    """While a full-system recovery runs (marker written by ``personaldocs recover``), the instance never presents
    itself as healthy or usable: every request gets 503 until recovery, validation and the report are finished."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from pathlib import Path

        from django.conf import settings
        from django.http import HttpResponse, JsonResponse

        if (Path(settings.DATA_DIR) / "recovery-in-progress").exists():
            if request.path.startswith("/api/"):
                return JsonResponse({"error": "Recovery in progress. The application opens when the recovery has finished.",
                                     "code": "recovery_in_progress"}, status=503, headers={"Retry-After": "60"})
            return HttpResponse("Personal Documents Management System: recovery in progress. Please try again later.",
                                status=503, content_type="text/plain", headers={"Retry-After": "60"})
        return self.get_response(request)
