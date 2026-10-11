from django.contrib.auth import logout


class AccountStateMiddleware:
    """Ends sessions for disabled accounts, after a session-epoch bump (password reset, recovery) or a device revoke."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            from .sessions import check

            if not user.is_active or request.session.get("epoch", 0) != user.session_epoch or not check(request):
                logout(request)
        response = self.get_response(request)
        token = getattr(request, "_pd_device_cookie", None)
        if token:  # set at sign-in for a new recognised device (HttpOnly, never readable by scripts)
            from django.conf import settings

            from .sessions import DEVICE_COOKIE, DEVICE_COOKIE_DAYS

            response.set_cookie(DEVICE_COOKIE, token, max_age=DEVICE_COOKIE_DAYS * 86400, httponly=True, samesite="Lax",
                                secure=getattr(settings, "SECURE_COOKIES", False), path="/")
        return response
