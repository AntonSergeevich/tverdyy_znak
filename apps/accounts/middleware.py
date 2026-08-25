"""Истечение сессии по неактивности (ТЗ 8.2)."""
from __future__ import annotations

import time

from django.conf import settings
from django.contrib.auth import logout

from apps.accounts.models import PRIVILEGED_ROLES

LAST_SEEN_KEY = "_last_seen_at"


class SessionIdleTimeoutMiddleware:
    """
    Для привилегированных ролей окно неактивности короче.

    Работает поверх стандартной сессии: срок жизни cookie задаёт верхнюю
    границу, а этот middleware — паузу между действиями.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            now = time.time()
            last_seen = request.session.get(LAST_SEEN_KEY)
            timeout = self._timeout_for(request, user)
            if last_seen and now - last_seen > timeout:
                logout(request)
            else:
                request.session[LAST_SEEN_KEY] = now
        return self.get_response(request)

    @staticmethod
    def _timeout_for(request, user) -> int:
        organization = getattr(request, "organization", None)
        privileged = user.is_superuser or (
            organization is not None and user.has_role(organization, *PRIVILEGED_ROLES)
        )
        return (
            settings.SESSION_IDLE_TIMEOUT_STAFF if privileged else settings.SESSION_IDLE_TIMEOUT
        )
