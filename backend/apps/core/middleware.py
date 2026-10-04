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

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.CSP)
        response.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=(self)")
        path = request.path
        if path.startswith("/api/") or path.startswith("/s/"):
            # Sensitive data must never land in shared/browser caches.
            response["Cache-Control"] = "no-store, private"
            response["Pragma"] = "no-cache"
        return response
