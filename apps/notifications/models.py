"""Журнал отправленных уведомлений: молча падающих задач быть не должно (ТЗ 9.2)."""
from __future__ import annotations

import uuid

from django.db import models

from apps.core.models import TenantModel


class Notification(TenantModel):
    class Channel(models.TextChoices):
        TELEGRAM = "telegram", "Telegram"
        EMAIL = "email", "Email"

    class Status(models.TextChoices):
        PENDING = "pending", "в очереди"
        SENT = "sent", "отправлено"
        FAILED = "failed", "не отправлено"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.CharField("канал", max_length=20, choices=Channel.choices)
    recipient = models.CharField("получатель", max_length=200)
    kind = models.CharField("тип", max_length=60)
    subject_type = models.CharField("тип объекта", max_length=60, blank=True)
    subject_id = models.CharField("id объекта", max_length=64, blank=True)
    body = models.TextField("текст")
    status = models.CharField(
        "статус", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveSmallIntegerField("попыток", default=0)
    last_error = models.TextField("последняя ошибка", blank=True)
    sent_at = models.DateTimeField("отправлено", null=True, blank=True)

    class Meta:
        verbose_name = "уведомление"
        verbose_name_plural = "уведомления"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status", "-created_at"]),
            models.Index(fields=["subject_type", "subject_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_channel_display()} → {self.recipient} ({self.get_status_display()})"
