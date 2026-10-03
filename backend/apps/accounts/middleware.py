from django.contrib.auth import logout


class AccountStateMiddleware:
    """Ends sessions for disabled accounts or after a session-epoch bump (password reset, recovery)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            if not user.is_active or request.session.get("epoch", 0) != user.session_epoch:
                logout(request)
        return self.get_response(request)
