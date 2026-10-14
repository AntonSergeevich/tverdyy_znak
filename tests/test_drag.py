"""
Перетаскивание: доска заявок, порядок предметов, работ и строк КТП,
ученик в группу. Сам жест — в браузере; здесь то, что он отправляет.
"""
from __future__ import annotations

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import (
    GradeItem,
    GradeItemKind,
    Group,
    GroupKind,
    GroupMembership,
    Subject,
    ThematicPlan,
    ThematicPlanEntry,
)
from apps.site_public.models import Lead
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def sign_in(tenant, user):
    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


@pytest.fixture
def lead(tenant_a):
    with organization_context(tenant_a.organization):
        return Lead.objects.create(
            organization=tenant_a.organization, name="Ольга", phone="79130001122",
            grade=9, call_window=Lead.CallWindow.DAY,
            consent_at="2026-08-01T10:00:00Z", policy_version="2026-08-01",
        )


def test_leads_open_as_a_board_by_stage(tenant_a, lead):
    body = sign_in(tenant_a, tenant_a.owner_user).get(reverse("cabinet:leads")).content.decode()

    for value, _label in Lead.Status.choices:
        assert f'data-lead-column="{value}"' in body
    assert f'id="lead-card-{lead.pk}"' in body
    # Список остаётся — для фильтра по этапу и удалённых.
    listed = sign_in(tenant_a, tenant_a.owner_user).get(
        reverse("cabinet:leads"), {"vid": "spisok"}
    ).content.decode()
    assert f'id="lead-{lead.pk}"' in listed


def test_a_card_moved_to_the_next_stage_comes_back_as_a_card(tenant_a, lead):
    response = sign_in(tenant_a, tenant_a.owner_user).post(
        reverse("cabinet:lead_status", args=[lead.pk]),
        {"status": Lead.Status.DIAGNOSTIC_SCHEDULED, "view": "card"},
    )

    assert response.status_code == 200
    assert 'data-lead-status="diagnostic_scheduled"' in response.content.decode()
    lead.refresh_from_db()
    assert lead.status == Lead.Status.DIAGNOSTIC_SCHEDULED


def test_a_card_dropped_into_decline_asks_for_the_reason(tenant_a, lead):
    owner = sign_in(tenant_a, tenant_a.owner_user)

    refused = owner.post(
        reverse("cabinet:lead_status", args=[lead.pk]), {"status": "declined", "view": "card"}
    )
    assert refused.status_code == 422
    assert 'name="decline_reason"' in refused.content.decode()
    lead.refresh_from_db()
    assert lead.status == Lead.Status.NEW

    owner.post(
        reverse("cabinet:lead_status", args=[lead.pk]),
        {"status": "declined", "decline_reason": "дорого", "view": "card"},
    )
    # Перенос на доске приносит только этап — причину не стирает.
    owner.post(
        reverse("cabinet:lead_status", args=[lead.pk]), {"status": "declined", "view": "card"}
    )
    lead.refresh_from_db()
    assert (lead.status, lead.decline_reason) == (Lead.Status.DECLINED, "дорого")


def test_subjects_take_the_order_they_were_dragged_into(tenant_a):
    with organization_context(tenant_a.organization):
        second = Subject.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year, name="Физика"
        )
        ids = [str(second.pk), str(tenant_a.subject.pk)]

    response = sign_in(tenant_a, tenant_a.owner_user).post(
        reverse("cabinet:subjects_reorder"), {"order": ",".join(ids)}
    )

    assert response.status_code == 204
    with organization_context(tenant_a.organization):
        second.refresh_from_db()
        tenant_a.subject.refresh_from_db()
    assert second.position < tenant_a.subject.position


def test_an_order_with_someone_elses_subject_is_refused(tenant_a, tenant_b):
    response = sign_in(tenant_a, tenant_a.owner_user).post(
        reverse("cabinet:subjects_reorder"),
        {"order": f"{tenant_a.subject.pk},{tenant_b.subject.pk}"},
    )

    assert response.status_code == 400
    with organization_context(tenant_b.organization):
        tenant_b.subject.refresh_from_db()
        assert tenant_b.subject.position == 100


def test_works_of_the_module_are_reordered(tenant_a):
    with organization_context(tenant_a.organization):
        first, second = (
            GradeItem.objects.create(
                organization=tenant_a.organization, module=tenant_a.module,
                subject=tenant_a.subject, group=tenant_a.group,
                kind=GradeItemKind.QUIZ, title=title, max_points=5,
            )
            for title in ("Диктант", "Тест")
        )

    response = sign_in(tenant_a, tenant_a.teacher_user).post(
        reverse("cabinet:works_reorder", args=[tenant_a.module.pk, tenant_a.subject.pk, tenant_a.group.pk]),
        {"order": f"{second.pk},{first.pk}"},
    )

    assert response.status_code == 204
    with organization_context(tenant_a.organization):
        assert list(
            GradeItem.objects.filter(pk__in=[first.pk, second.pk]).order_by("position")
        ) == [second, first]


def test_ktp_rows_are_put_in_order(tenant_a):
    with organization_context(tenant_a.organization):
        plan = ThematicPlan.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            subject=tenant_a.subject, group=tenant_a.group, title="КТП",
        )
        rows = [
            ThematicPlanEntry.objects.create(
                organization=tenant_a.organization, plan=plan, position=index, topic=topic
            )
            for index, topic in enumerate(["Вторая", "Первая"], start=1)
        ]

    response = sign_in(tenant_a, tenant_a.teacher_user).post(
        reverse("cabinet:ktp_reorder", args=[plan.pk]),
        {"order": f"{rows[1].pk},{rows[0].pk}"},
    )

    assert response.status_code == 204
    with organization_context(tenant_a.organization):
        assert [e.topic for e in plan.entries.order_by("position")] == ["Первая", "Вторая"]


def test_group_card_offers_dragging_a_student_into_the_group(tenant_a):
    with organization_context(tenant_a.organization):
        course = Group.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            name="ОГЭ: русский язык", kind=GroupKind.COURSE,
        )
    owner = sign_in(tenant_a, tenant_a.owner_user)
    body = owner.get(reverse("cabinet:group_card", args=[course.pk])).content.decode()

    assert "data-drop-zone data-drop-refresh" in body
    assert f'"students": "{tenant_a.student.pk}"' in body

    owner.post(
        reverse("cabinet:group_members_add", args=[course.pk]),
        {"students": str(tenant_a.student.pk)},
    )
    with organization_context(tenant_a.organization):
        assert GroupMembership.objects.filter(group=course, student=tenant_a.student).exists()
