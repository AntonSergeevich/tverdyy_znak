"""
Интерфейс платежей.

На старте работает только ManualProvider: оплата по реквизитам и QR,
администратор отмечает факт в кабинете. Эквайринг добавляется новым
классом, модель Payment при этом не меняется (ТЗ 7).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone


@dataclass(frozen=True)
class PaymentIntent:
    payment_id: str
    amount: Decimal
    confirmation_url: str | None = None
    payload: dict | None = None


class PaymentProvider(ABC):
    code: str = "abstract"

    @abstractmethod
    def create_intent(self, payment) -> PaymentIntent:
        """Подготовить оплату: ссылка эквайринга или реквизиты."""

    @abstractmethod
    def mark_paid(self, payment, *, actor=None, external_id: str = "") -> None:
        """Зафиксировать оплату."""


class ManualProvider(PaymentProvider):
    """Оплата по реквизитам, отметка администратором."""

    code = "manual"

    def create_intent(self, payment) -> PaymentIntent:
        organization = payment.organization
        purpose = f"{payment.title}, {payment.student.short_name}"
        return PaymentIntent(
            payment_id=str(payment.pk),
            amount=payment.amount,
            payload={
                "receiver": organization.legal_name or organization.name,
                "inn": organization.inn,
                "account": organization.bank_account,
                "bank": organization.bank_name,
                "bik": organization.bank_bik,
                "corr_account": organization.bank_corr_account,
                "purpose": purpose,
                "amount": str(payment.amount),
            },
        )

    def mark_paid(self, payment, *, actor=None, external_id: str = "") -> None:
        payment.status = payment.Status.PAID
        payment.paid_on = timezone.localdate()
        payment.marked_by = actor
        payment.provider = self.code
        payment.external_id = external_id
        payment.save(
            update_fields=[
                "status", "paid_on", "marked_by", "provider", "external_id", "updated_at",
            ]
        )


def get_provider(code: str = "manual") -> PaymentProvider:
    providers = {ManualProvider.code: ManualProvider()}
    return providers.get(code, providers["manual"])
