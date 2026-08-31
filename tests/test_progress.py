"""
Прогресс учеников: куда наконец попадают отметки «как день».

Ученик ставил их в пустоту: не видел никто — ни наставник, ни педагог.
Показатель, который никто не смотрит, бесполезен вдвойне: ребёнок тратит на
него внимание, а ответа не получает.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import organization_context
from apps.journal.models import (
    Goal,
    GoalKind,
    GoalVisibility,
    ModuleResult,
    MoodEntry,
)
from apps.journal.services.goals import set_steps
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


@pytest.fixture
def marked_days(tenant_a):
    today = timezone.localdate()
    with organization_context(tenant_a.organization):
        for shift, value in enumerate([5, 4, 2, 1, 3], start=1):
            MoodEntry.objects.create(
                organization=tenant_a.organization, student=tenant_a.student,
                day=today - dt.timedelta(days=shift), value=value,
                note="было тяжело" if value == 1 else "",
            )
    return tenant_a


def test_the_mood_marks_are_finally_seen_by_someone(tenant_a, marked_days):
    """Ради этого раздел и появился: отметки перестали уходить в пустоту."""
    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(reverse("cabinet:progress_list")).content.decode()

    assert tenant_a.student.short_name in body
    assert "mood-cell--1" in body
    assert "mood-cell--5" in body


def test_a_missed_day_is_shown_as_a_gap_not_hidden(tenant_a, marked_days):
    """Полоса из пробелов говорит не меньше, чем полоса из «тяжело»."""
    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(
        reverse("cabinet:progress_student", args=[tenant_a.student.pk])
    ).content.decode()

    assert "не отмечено" in body
    assert "было тяжело" in body


def test_the_module_track_shows_points_out_of_planned(tenant_a):
    with organization_context(tenant_a.organization):
        ModuleResult.objects.create(
            organization=tenant_a.organization, student=tenant_a.student,
            subject=tenant_a.subject, module=tenant_a.module,
            total_points=Decimal("62.00"), planned_points=Decimal("100.00"),
        )

    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(
        reverse("cabinet:progress_student", args=[tenant_a.student.pk])
    ).content.decode()

    assert "62" in body
    assert "progress-track__dot" in body


def test_open_goals_are_shown_hidden_ones_never(tenant_a):
    with organization_context(tenant_a.organization):
        shown = Goal.objects.create(
            organization=tenant_a.organization, student=tenant_a.student,
            kind=GoalKind.PERSONAL, title="Подтянуть алгебру",
        )
        set_steps(goal=shown, titles=["Прорешать задачи"])
        Goal.objects.create(
            organization=tenant_a.organization, student=tenant_a.student,
            kind=GoalKind.PERSONAL, title="Совсем личное",
            visibility=GoalVisibility.HIDDEN,
        )

    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(
        reverse("cabinet:progress_student", args=[tenant_a.student.pk])
    ).content.decode()

    assert "Подтянуть алгебру" in body
    assert "Прорешать задачи" in body
    assert "Совсем личное" not in body


def test_a_teacher_sees_only_their_own_students(tenant_a, tenant_b, marked_days):
    """Чужая организация — чужие дети, и заглянуть в них нельзя."""
    stranger = sign_in(tenant_b, tenant_b.teacher_user)

    listing = stranger.get(reverse("cabinet:progress_list")).content.decode()
    assert tenant_a.student.short_name not in listing

    card = stranger.get(reverse("cabinet:progress_student", args=[tenant_a.student.pk]))
    assert card.status_code in (403, 404)


def test_the_student_cannot_look_at_the_others(tenant_a):
    client = sign_in(tenant_a, tenant_a.student_user)
    assert client.get(reverse("cabinet:progress_list")).status_code in (403, 404)


def test_the_section_is_in_the_menu_for_those_who_lead_children(tenant_a):
    teacher = sign_in(tenant_a, tenant_a.teacher_user)
    assert reverse("cabinet:progress_list") in teacher.get(
        reverse("cabinet:teacher_today")
    ).content.decode()
