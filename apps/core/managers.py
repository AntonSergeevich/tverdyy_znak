"""Менеджеры: автоматическая фильтрация по организации и мягкое удаление."""
from __future__ import annotations

import logging

from django.db import models
from django.utils import timezone

from apps.core.tenancy import get_current_organization, is_unscoped

logger = logging.getLogger(__name__)


class TenantQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)

    def delete(self):
        """Мягкое удаление по умолчанию (ТЗ 9.5)."""
        if not hasattr(self.model, "deleted_at"):
            return super().delete()
        return self.update(deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """
    Дефолтный менеджер доменных моделей.

    Всегда добавляет фильтр по текущей организации. Если организация
    не определена и явно не запрошен unscoped-режим — возвращает пустую
    выборку: лучше пусто, чем чужое.
    """

    def __init__(self, *args, exclude_soft_deleted: bool = True, **kwargs):
        self.exclude_soft_deleted = exclude_soft_deleted
        super().__init__(*args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        if self.exclude_soft_deleted and hasattr(self.model, "deleted_at"):
            qs = qs.filter(deleted_at__isnull=True)
        if is_unscoped():
            return qs
        organization = get_current_organization()
        if organization is None:
            logger.debug(
                "Запрос к %s без активной организации — выборка пуста",
                self.model.__name__,
            )
            return qs.none()
        return qs.filter(organization=organization)


class AllObjectsManager(models.Manager.from_queryset(TenantQuerySet)):
    """Без фильтра по организации и без скрытия удалённых. Только админка и миграции."""
