"""Публичная форма заявки: согласие, антиспам, уведомление (ТЗ 4)."""
from __future__ import annotations

import time

import pytest
from django.core.cache import cache
from django.utils import timezone
from django.urls import reverse

from apps.core.models import Consent, ConsentType
from apps.core.tenancy import organization_context
from apps.site_public.models import Lead

VALID = {
    "name": "Ольга",
    "phone": "+7 (913) 000-11-22",
    "grade": "9",
    "call_window": "12-15",
    "comment": "Ребёнок ушёл на самообразование",
    "form_rendered_at": "1",
}


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_landing_renders(client_a, tenant_a):
    response = client_a.get(reverse("public:landing"))
    assert response.status_code == 200
    body = response.content.decode()
    # Заголовок правится в админке, поэтому проверяем значение из модели.
    assert tenant_a.organization.hero_title in body
    assert "100-балльная шкала" in body.replace("100-БАЛЛЬНАЯ ШКАЛА", "100-балльная шкала")


def test_lead_requires_explicit_consent(client_a, tenant_a):
    """Автосогласие по факту нажатия кнопки не допускается."""
    response = client_a.post(reverse("public:lead_create"), VALID)
    assert response.status_code == 422
    with organization_context(tenant_a.organization):
        assert Lead.objects.count() == 0


def test_lead_created_with_consent(client_a, tenant_a):
    response = client_a.post(
        reverse("public:lead_create"),
        {**VALID, "consent": "on", "utm_source": "yandex", "utm_campaign": "start"},
    )
    assert response.status_code == 302
    assert response["Location"] == reverse("public:thanks")

    with organization_context(tenant_a.organization):
        lead = Lead.objects.get()
        assert lead.phone == "79130001122"
        assert lead.grade == 9
        assert lead.consent_at is not None
        assert lead.policy_version
        assert lead.utm_source == "yandex"
        # Факт согласия логируется отдельной записью с версией текста (ТЗ 8.3).
        consent = Consent.objects.get()
        assert consent.consent_type == ConsentType.PDN
        assert consent.document_version == lead.policy_version


def test_honeypot_blocks_bot(client_a, tenant_a):
    response = client_a.post(
        reverse("public:lead_create"), {**VALID, "consent": "on", "company_site": "spam.example"}
    )
    assert response.status_code == 422
    with organization_context(tenant_a.organization):
        assert Lead.objects.count() == 0


def test_too_fast_submission_is_rejected(client_a, tenant_a):
    payload = {**VALID, "consent": "on", "form_rendered_at": str(int(time.time()))}
    response = client_a.post(reverse("public:lead_create"), payload)
    assert response.status_code == 422
    with organization_context(tenant_a.organization):
        assert Lead.objects.count() == 0


def test_rate_limit_per_ip(client_a, tenant_a, settings):
    settings.LEAD_RATE_LIMIT_PER_HOUR = 2
    for _ in range(2):
        assert client_a.post(
            reverse("public:lead_create"), {**VALID, "consent": "on"}
        ).status_code == 302
    blocked = client_a.post(reverse("public:lead_create"), {**VALID, "consent": "on"})
    assert blocked.status_code == 422
    with organization_context(tenant_a.organization):
        assert Lead.objects.count() == 2


def test_invalid_phone_is_rejected(client_a):
    response = client_a.post(
        reverse("public:lead_create"), {**VALID, "phone": "12345", "consent": "on"}
    )
    assert response.status_code == 422
    assert "телефон" in response.content.decode().lower()


def test_htmx_submission_returns_redirect_header(client_a):
    response = client_a.post(
        reverse("public:lead_create"), {**VALID, "consent": "on"}, HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 204
    assert response["HX-Redirect"] == reverse("public:thanks")


def test_thanks_page_is_separate_url(client_a):
    response = client_a.get(reverse("public:thanks"))
    assert response.status_code == 200
    assert "noindex" in response.content.decode()


def test_lead_notification_is_queued(client_a, tenant_a, settings):
    """Заявка ставит задачу уведомления; сбой Telegram не ломает ответ."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.TG_BOT_TOKEN = ""
    response = client_a.post(reverse("public:lead_create"), {**VALID, "consent": "on"})
    assert response.status_code == 302

    from apps.notifications.models import Notification

    with organization_context(tenant_a.organization):
        notification = Notification.objects.filter(kind="new_lead").first()
        assert notification is not None
        assert notification.status == Notification.Status.FAILED
        assert "TG_BOT_TOKEN" in notification.last_error


def test_spam_lead_can_be_removed_from_the_funnel(client, tenant_a):
    """
    Спам и ошибочные отправки не должны копиться в воронке.

    Удаление мягкое: в заявке лежит согласие на обработку данных с датой
    и версией текста — именно им подтверждается законность обработки,
    и стирать его насовсем нельзя.
    """
    from django.test import override_settings
    from django.urls import reverse

    from apps.site_public.models import Lead
    from tests.conftest import PASSWORD

    lead = Lead.all_objects.create(
        organization=tenant_a.organization, name="Спамер", phone="79990000000",
        grade=9, consent_at=timezone.now(), policy_version="1",
    )
    client.defaults["HTTP_HOST"] = tenant_a.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(
            reverse("accounts:login"),
            {"username": tenant_a.owner_user.email, "password": PASSWORD},
        )
        response = client.post(reverse("cabinet:lead_delete", args=[lead.pk]))

    lead.refresh_from_db()
    assert response.status_code == 200
    assert lead.deleted_at is not None
    # Согласие на месте: удалили строку из списка, а не доказательство.
    assert lead.consent_at is not None


def test_deleted_lead_can_be_brought_back(client, tenant_a):
    from django.test import override_settings
    from django.urls import reverse

    from apps.site_public.models import Lead
    from tests.conftest import PASSWORD

    lead = Lead.all_objects.create(
        organization=tenant_a.organization, name="Ошиблись", phone="79990000001",
        grade=10, consent_at=timezone.now(), policy_version="1",
    )
    client.defaults["HTTP_HOST"] = tenant_a.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(
            reverse("accounts:login"),
            {"username": tenant_a.owner_user.email, "password": PASSWORD},
        )
        client.post(reverse("cabinet:lead_delete", args=[lead.pk]))
        client.post(reverse("cabinet:lead_restore", args=[lead.pk]))

    lead.refresh_from_db()
    assert lead.deleted_at is None
