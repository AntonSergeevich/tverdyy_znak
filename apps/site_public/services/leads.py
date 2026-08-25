"""Создание заявки: антиспам, согласие, уведомление в Telegram."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.core.audit import AuditAction, client_ip, log_audit
from apps.core.models import Consent, ConsentType
from apps.site_public.models import Lead

logger = logging.getLogger(__name__)

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0


def check_rate_limit(request) -> RateLimitResult:
    """Не больше LEAD_RATE_LIMIT_PER_HOUR заявок с одного IP в час (ТЗ 4)."""
    ip = client_ip(request) or "unknown"
    key = f"lead-rate:{ip}"
    count = cache.get_or_set(key, 0, timeout=3600)
    if count >= settings.LEAD_RATE_LIMIT_PER_HOUR:
        return RateLimitResult(allowed=False, retry_after_seconds=3600)
    try:
        cache.incr(key)
    except ValueError:  # ключ истёк между get_or_set и incr
        cache.set(key, 1, timeout=3600)
    return RateLimitResult(allowed=True)


def collect_tracking(request) -> dict:
    params = request.GET if request.method == "GET" else request.POST
    data = {key: (params.get(key) or "")[:120] for key in UTM_KEYS}
    data["referrer"] = (request.META.get("HTTP_REFERER") or "")[:500]
    data["page_path"] = (params.get("page_path") or request.path)[:300]
    data["ip"] = client_ip(request)
    data["user_agent"] = (request.META.get("HTTP_USER_AGENT") or "")[:300]
    return data


def create_lead(*, form, request, organization) -> Lead:
    """
    Сохранить заявку, зафиксировать согласие и поставить задачу уведомления.

    Сбой Telegram не должен ломать ответ пользователю: заявка уже в БД,
    отправка идёт в Celery с ретраями (ТЗ 4, 7).
    """
    lead = form.save(commit=False, organization=organization, **collect_tracking(request))
    lead.save()

    Consent.objects.create(
        organization=organization,
        subject_label=f"{lead.name} · {lead.phone_display}",
        consent_type=ConsentType.PDN,
        document_version=lead.policy_version,
        granted_at=lead.consent_at or timezone.now(),
        ip=lead.ip,
        user_agent=lead.user_agent,
    )
    log_audit(
        action=AuditAction.CONSENT_GRANTED, request=request, organization=organization,
        obj=lead, consent_type=ConsentType.PDN.value, version=lead.policy_version,
    )

    enqueue_lead_notification(lead)
    return lead


def enqueue_lead_notification(lead: Lead) -> bool:
    """
    Поставить уведомление в очередь.

    Недоступный брокер не должен ломать ответ пользователю: заявка уже
    в БД, а невыдавшееся уведомление подберёт retry_failed_notifications.
    """
    from apps.notifications.tasks import notify_new_lead

    try:
        notify_new_lead.delay(str(lead.pk))
        return True
    except Exception:  # noqa: BLE001 - брокер может быть недоступен
        logger.exception("Не удалось поставить в очередь уведомление о заявке %s", lead.pk)
        return False
