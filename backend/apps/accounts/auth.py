from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission


class CsrfSessionAuthentication(SessionAuthentication):
    """Session auth with CSRF enforced for unsafe methods (DRF default behaviour)."""


class IsActiveAuthenticated(BasePermission):
    message = "Sign in required."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        if user.must_change_password and not getattr(view, "allow_password_change_pending", False):
            raise PermissionDenied({"detail": "You must set a new password before continuing.", "code": "password_change_required"})
        if not getattr(view, "allow_2fa_setup_pending", False):
            from .passkeys import has_second_factor, requires_2fa

            if requires_2fa(user) and not has_second_factor(user):
                raise PermissionDenied({"detail": "Set up two-step verification (passkey or authenticator app) to continue.",
                                        "code": "two_factor_setup_required"})
        return True


class IsMainAdmin(IsActiveAuthenticated):
    message = "Only the main administrator can do this."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and bool(request.user.is_main_admin)


class IsAdministrator(IsActiveAuthenticated):
    """Main administrator or an account with the Administrator role (security and operations area)."""

    message = "Only administrators can do this."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and bool(request.user.is_main_admin or request.user.is_admin)
