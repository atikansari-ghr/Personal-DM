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
