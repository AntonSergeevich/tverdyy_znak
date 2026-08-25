"""
Проверки прав уровня роли.

Объектные проверки (педагог — только свои группы, родитель — только свои дети)
живут в apps/journal/access.py: они зависят от предметной области.
"""
from __future__ import annotations

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from apps.accounts.models import Role  # noqa: F401  (реэкспорт для удобства импорта)


def user_has_role(user, organization, *roles: str) -> bool:
    if user is None or not user.is_authenticated or organization is None:
        return False
    if user.is_superuser:
        return True
    return user.has_role(organization, *roles)


def role_required(*roles: str):
    """Декоратор вью: доступ только указанным ролям текущей организации."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not user_has_role(request.user, getattr(request, "organization", None), *roles):
                raise PermissionDenied("Недостаточно прав для этого раздела")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


class RoleRequiredMixin:
    """Тот же контроль для class-based вью."""

    allowed_roles: tuple[str, ...] = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not user_has_role(request.user, getattr(request, "organization", None), *self.allowed_roles):
            raise PermissionDenied("Недостаточно прав для этого раздела")
        return super().dispatch(request, *args, **kwargs)
