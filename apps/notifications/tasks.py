"""
Фоновые уведомления (ТЗ 7).

Правила: в задачу передаём только id, задача идемпотентна, у неё есть
ретраи и предел попыток, а все падения видны в Sentry (ТЗ 9.2).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.core.tenancy import organization_context, unscoped
from apps.notifications.models import Notification
from apps.notifications.telegram import TelegramError, send_message

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


def _deliver(notification: Notification) -> None:
    notification.attempts += 1
    try:
        send_message(notification.body, chat_id=notification.recipient or None)
    except TelegramError as exc:
        notification.status = Notification.Status.FAILED
        notification.last_error = str(exc)[:1000]
        notification.save(update_fields=["attempts", "status", "last_error", "updated_at"])
        raise
    notification.status = Notification.Status.SENT
    notification.sent_at = timezone.now()
    notification.last_error = ""
    notification.save(update_fields=["attempts", "status", "sent_at", "last_error", "updated_at"])


@shared_task(bind=True, max_retries=MAX_ATTEMPTS, default_retry_delay=60, acks_late=True)
def notify_new_lead(self, lead_id: str) -> str:
    """Уведомление владельцу о новой заявке. Повторный вызов не создаёт дубль."""
    from apps.site_public.models import Lead

    with unscoped():
        lead = Lead.all_objects.select_related("organization").filter(pk=lead_id).first()
    if lead is None:
        logger.warning("Заявка %s не найдена — уведомление пропущено", lead_id)
        return "missing"

    organization = lead.organization
    with organization_context(organization):
        existing = Notification.objects.filter(
            subject_type="Lead", subject_id=str(lead.pk), kind="new_lead"
        ).first()
        if existing and existing.status == Notification.Status.SENT:
            return "already-sent"

        text = (
            "<b>Новая заявка на диагностику</b>\n"
            f"Имя: {lead.name}\n"
            f"Телефон: {lead.phone_display}\n"
            f"Класс: {lead.grade}\n"
            f"Когда звонить: {lead.get_call_window_display()}\n"
            f"Сегмент: {lead.get_segment_display() or '—'}\n"
            f"Комментарий: {lead.comment or '—'}\n"
            f"Источник: {lead.utm_source or 'прямой заход'} / {lead.utm_medium or '—'}\n"
            f"Страница: {lead.page_path}"
        )
        notification = existing or Notification(
            organization=organization,
            channel=Notification.Channel.TELEGRAM,
            recipient=organization.telegram_chat_id or "",
            kind="new_lead",
            subject_type="Lead",
            subject_id=str(lead.pk),
        )
        notification.body = text
        notification.status = Notification.Status.PENDING
        notification.save()

        try:
            _deliver(notification)
        except TelegramError as exc:
            logger.exception("Не удалось отправить заявку %s в Telegram", lead_id)
            raise self.retry(exc=exc, countdown=min(600, 60 * 2 ** self.request.retries))

        Lead.all_objects.filter(pk=lead.pk).update(notified_at=timezone.now())
    return "sent"


@shared_task(bind=True, max_retries=MAX_ATTEMPTS, default_retry_delay=60, acks_late=True)
def notify_module_result(self, module_result_id: str) -> str:
    """Уведомление родителю об итоге модуля, в первую очередь о незачёте."""
    from apps.journal.models import Level, ModuleResult

    with unscoped():
        result = (
            ModuleResult.all_objects.select_related(
                "organization", "student", "subject", "module"
            )
            .filter(pk=module_result_id)
            .first()
        )
    if result is None:
        return "missing"

    organization = result.organization
    with organization_context(organization):
        recipients = [
            link.parent
            for link in result.student.parent_links.select_related("parent").all()
            if link.parent and (link.parent.user_id or link.parent.phone)
        ]
        if not recipients:
            return "no-recipients"

        headline = (
            "Незачёт по модулю — нужна каникулярная неделя на консультации"
            if result.level == Level.FAILED
            else f"Итог модуля: {result.get_level_display()}"
        )
        text = (
            f"<b>{headline}</b>\n"
            f"Ученик: {result.student.short_name}\n"
            f"Предмет: {result.subject.name}\n"
            f"{result.module}: {result.total_points} баллов из 100"
        )
        notification, _ = Notification.objects.get_or_create(
            subject_type="ModuleResult",
            subject_id=str(result.pk),
            kind="module_result",
            defaults={
                "organization": organization,
                "channel": Notification.Channel.TELEGRAM,
                "recipient": organization.telegram_chat_id or "",
                "body": text,
            },
        )
        if notification.status == Notification.Status.SENT:
            return "already-sent"
        notification.body = text
        notification.save(update_fields=["body", "updated_at"])
        try:
            _deliver(notification)
        except TelegramError as exc:
            raise self.retry(exc=exc, countdown=min(600, 60 * 2 ** self.request.retries))
    return "sent"


@shared_task
def retry_failed_notifications() -> dict:
    """Периодическая пересылка того, что не ушло. Идемпотентна."""
    cutoff = timezone.now() - timedelta(hours=24)
    stats = {"retried": 0, "given_up": 0}
    with unscoped():
        failed = Notification.all_objects.filter(
            status=Notification.Status.FAILED, created_at__gte=cutoff
        ).select_related("organization")[:100]
        for notification in failed:
            if notification.attempts >= MAX_ATTEMPTS:
                stats["given_up"] += 1
                continue
            with organization_context(notification.organization):
                try:
                    _deliver(notification)
                    stats["retried"] += 1
                except TelegramError:
                    logger.warning("Повторная отправка %s не удалась", notification.pk)
    return stats
