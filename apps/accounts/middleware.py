"""Истечение сессии по неактивности (ТЗ 8.2) и просмотр от чужого лица."""
from __future__ import annotations

import time

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseForbidden

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


class ImpersonationMiddleware:
    """
    Подменяет request.user на того, чей кабинет смотрят.

    Стоит после определения организации: право на просмотр проверяется по
    роли в ней. Настоящий пользователь остаётся в request.impersonator —
    по нему пишется журнал действий и рисуется полоса наверху экрана,
    чтобы никто не забыл, что смотрит чужими глазами.

    Пока просмотр включён, любой запрос на изменение отклоняется:
    проверять — значит смотреть, а не действовать за человека.
    """

    SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.impersonator = None
        target = self._target(request)
        if target is not None:
            request.impersonator = request.user
            request.user = target
            if request.method not in self.SAFE_METHODS and not self._is_exempt(request):
                return HttpResponseForbidden(
                    "Просмотр от чужого лица — только чтение. "
                    "Чтобы что-то изменить, вернитесь к себе."
                )
        return self.get_response(request)

    @staticmethod
    def _target(request):
        from apps.accounts.impersonation import (
            SESSION_KEY,
            can_impersonate,
            may_be_impersonated,
        )

        user = getattr(request, "user", None)
        target_id = request.session.get(SESSION_KEY)
        organization = getattr(request, "organization", None)
        if not target_id or not can_impersonate(user, organization):
            return None

        from apps.accounts.models import User

        target = User.objects.filter(pk=target_id, is_active=True).first()
        # Право могли отозвать уже после начала просмотра — проверяем каждый
        # раз, а не только при входе.
        if target is None or not may_be_impersonated(target, organization):
            request.session.pop(SESSION_KEY, None)
            return None
        return target

    @staticmethod
    def _is_exempt(request) -> bool:
        """
        Что всё-таки можно нажать: выйти из просмотра, переключиться на
        другого человека и выйти из системы. Иначе полоса наверху вела бы
        к кнопкам, которые не работают.
        """
        from django.urls import Resolver404, resolve

        try:
            match = resolve(request.path)
        except Resolver404:
            return False
        return match.view_name in {
            "accounts:impersonate_start",
            "accounts:impersonate_stop",
            "accounts:logout",
        }
