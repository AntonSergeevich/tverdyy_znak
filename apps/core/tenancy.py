"""
Текущая организация запроса.

Хранится в contextvar, а не в threading.local: contextvar корректно работает
и в Celery-задачах, и в тестах, и не течёт между запросами.

Правило безопасности: если организация не установлена, тенант-менеджер
возвращает ПУСТУЮ выборку, а не все записи. Молчаливая утечка между
организациями — критическая ошибка (ТЗ 9.4), пустой список — заметная,
но безопасная.
"""
from __future__ import annotations

import contextlib
import logging
from contextvars import ContextVar
from typing import TYPE_CHECKING, Iterator, Optional

if TYPE_CHECKING:  # pragma: no cover
    from apps.core.models import Organization

logger = logging.getLogger(__name__)

_current_organization: ContextVar[Optional["Organization"]] = ContextVar(
    "current_organization", default=None
)
# Явный отказ от фильтрации — только для админки, миграций и обслуживания.
_unscoped: ContextVar[bool] = ContextVar("tenant_unscoped", default=False)


class NoActiveOrganization(RuntimeError):
    """Поднимается там, где организация обязана быть определена."""


def get_current_organization() -> Optional["Organization"]:
    return _current_organization.get()


def require_current_organization() -> "Organization":
    org = _current_organization.get()
    if org is None:
        raise NoActiveOrganization(
            "Текущая организация не определена. "
            "Используйте organization_context(org) или OrganizationMiddleware."
        )
    return org


def set_current_organization(organization: Optional["Organization"]):
    return _current_organization.set(organization)


def reset_current_organization(token) -> None:
    _current_organization.reset(token)


def is_unscoped() -> bool:
    return _unscoped.get()


@contextlib.contextmanager
def organization_context(organization: Optional["Organization"]) -> Iterator[None]:
    """Выполнить блок кода от имени организации (Celery, команды, тесты)."""
    token = _current_organization.set(organization)
    try:
        yield
    finally:
        _current_organization.reset(token)


@contextlib.contextmanager
def unscoped() -> Iterator[None]:
    """
    Отключить фильтрацию по организации.

    Допустимо только в админке платформы, миграциях данных и обслуживающих
    командах. В обычных вью использовать запрещено.
    """
    token = _unscoped.set(True)
    try:
        yield
    finally:
        _unscoped.reset(token)
