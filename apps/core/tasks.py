"""Фоновые задачи ядра."""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.core.audit import AuditAction, log_audit
from apps.core.models import Organization
from apps.core.tenancy import organization_context

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def purge_expired_personal_data(self) -> dict:
    """
    Удаление данных по истечении срока хранения (ТЗ 8.3).

    Идемпотентна: повторный запуск в тот же день ничего не ломает.
    Мягко удалённые записи старше срока хранения удаляются физически,
    заявки без обработки — по своему сроку.
    """
    from apps.journal.models import Student
    from apps.site_public.models import Lead

    result = {"students": 0, "leads": 0}
    for org in Organization.objects.filter(is_active=True):
        with organization_context(org):
            student_cutoff = timezone.now() - timedelta(days=org.data_retention_days)
            expired_students = Student.all_objects.filter(
                organization=org, deleted_at__isnull=False, deleted_at__lt=student_cutoff
            )
            count = expired_students.count()
            if count:
                expired_students.hard_delete()
                result["students"] += count

            lead_cutoff = timezone.now() - timedelta(days=org.lead_retention_days)
            expired_leads = Lead.all_objects.filter(
                organization=org, created_at__lt=lead_cutoff
            ).exclude(status=Lead.Status.ENROLLED)
            lead_count = expired_leads.count()
            if lead_count:
                expired_leads.hard_delete()
                result["leads"] += lead_count

            if count or lead_count:
                log_audit(
                    action=AuditAction.DATA_PURGED,
                    organization=org,
                    object_type="retention",
                    students=count,
                    leads=lead_count,
                )
    logger.info("Автоудаление по сроку хранения: %s", result)
    return result
