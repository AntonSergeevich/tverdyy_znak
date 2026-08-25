"""
Сервис журналирования доступа к персональным данным (ТЗ 8.4).

Пишет и в БД (AuditLog), и в отдельный файл-журнал, который ротируется
независимо от основных логов приложения.
"""
from __future__ import annotations

import logging
from typing import Any

from apps.core.models import AuditAction, AuditLog

logger = logging.getLogger("apps.core.audit")


def client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def log_audit(
    *,
    action: str,
    request=None,
    organization=None,
    actor=None,
    obj: Any = None,
    object_type: str = "",
    object_id: str = "",
    **extra,
) -> AuditLog:
    if request is not None:
        organization = organization or getattr(request, "organization", None)
        if actor is None:
            candidate = getattr(request, "user", None)
            actor = candidate if getattr(candidate, "is_authenticated", False) else None

    if obj is not None:
        object_type = object_type or obj.__class__.__name__
        object_id = object_id or str(getattr(obj, "pk", ""))

    entry = AuditLog.objects.create(
        organization=organization,
        actor=actor,
        actor_label=str(actor) if actor else "аноним",
        action=action,
        object_type=object_type,
        object_id=object_id,
        ip=client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
        extra=extra or {},
    )
    logger.info(
        "org=%s actor=%s action=%s object=%s:%s ip=%s extra=%s",
        getattr(organization, "slug", "-"),
        entry.actor_label,
        action,
        object_type or "-",
        object_id or "-",
        entry.ip or "-",
        extra or {},
    )
    return entry


__all__ = ["AuditAction", "log_audit", "client_ip"]
