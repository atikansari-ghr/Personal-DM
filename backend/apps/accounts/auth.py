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
        return True


class IsMainAdmin(IsActiveAuthenticated):
    message = "Only the main administrator can do this."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and bool(request.user.is_main_admin)
