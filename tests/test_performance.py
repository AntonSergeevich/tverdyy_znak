"""
Защита от N+1 (ТЗ 9.1).

Журнал группы не должен делать по запросу на ученика. Границы намеренно
с запасом: тест ловит регрессию на порядок, а не колебания в один запрос.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import organization_context
from apps.journal.models import (
    GroupMembership,
    Lesson,
    Module,
    ModuleKind,
    Student,
    Subject,
)
from apps.journal.services.grading import create_default_structure, set_grade
from tests.conftest import login


@pytest.fixture
def big_group(tenant_a):
    """15 учеников, 6 предметов, 6 модулей — размер, близкий к боевому."""
    with organization_context(tenant_a.organization):
        for index in range(15):
            student = Student.objects.create(
                organization=tenant_a.organization, last_name=f"Ученик{index:02d}",
                first_name="Тест", grade_level=9,
            )
            GroupMembership.objects.create(
                organization=tenant_a.organization, group=tenant_a.group, student=student
            )
        for index in range(5):
            Subject.objects.create(
                organization=tenant_a.organization, academic_year=tenant_a.year,
                name=f"Предмет {index}", weekly_hours=2, position=index,
            )
        for index in range(2, 7):
            Module.objects.create(
                organization=tenant_a.organization, academic_year=tenant_a.year,
                kind=ModuleKind.MODULE, number=index,
                starts_on=dt.date(2026, 9, 1) + dt.timedelta(days=40 * index),
                ends_on=dt.date(2026, 9, 30) + dt.timedelta(days=40 * index),
            )
    return tenant_a


def test_lesson_journal_does_not_grow_with_group_size(client, big_group, django_capture_on_commit_callbacks):
    """
    Главная проверка на N+1: число запросов не должно зависеть от числа учеников.

    Сравниваем journal на группе из 16 человек и на той же группе, выросшей
    вдвое. Если запросов станет больше — где-то появился запрос на ученика.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    tenant = big_group
    with organization_context(tenant.organization):
        items = create_default_structure(tenant.module, tenant.subject, tenant.group)
        lesson_item = next(i for i in items if i.kind == "lesson")
        lesson_item.lesson = tenant.lesson
        lesson_item.save(update_fields=["lesson"])
        tenant.lesson.is_graded = True
        tenant.lesson.save(update_fields=["is_graded"])

    login(client, tenant, tenant.teacher_user)
    url = reverse("cabinet:lesson_journal", args=[tenant.lesson.pk])

    with CaptureQueriesContext(connection) as small:
        response = client.get(url)
    assert response.status_code == 200
    assert response.content.decode().count("journal-row") >= 16

    with organization_context(tenant.organization):
        for index in range(16, 32):
            student = Student.objects.create(
                organization=tenant.organization, last_name=f"Ученик{index:02d}",
                first_name="Тест", grade_level=9,
            )
            GroupMembership.objects.create(
                organization=tenant.organization, group=tenant.group, student=student
            )

    with CaptureQueriesContext(connection) as large:
        response = client.get(url)
    assert response.status_code == 200
    assert response.content.decode().count("journal-row") >= 32
    assert len(large) == len(small), (
        f"Число запросов выросло с {len(small)} до {len(large)} при удвоении группы — это N+1"
    )


def test_parent_home_query_count(client, big_group, django_assert_max_num_queries):
    tenant = big_group
    with organization_context(tenant.organization):
        items = create_default_structure(tenant.module, tenant.subject, tenant.group)
        for item in items:
            set_grade(student=tenant.student, grade_item=item, points=item.max_points)

    login(client, tenant, tenant.parent_user)
    with django_assert_max_num_queries(30):
        response = client.get(reverse("cabinet:parent_home"))
    assert response.status_code == 200


def test_teacher_today_query_count(client, big_group, django_assert_max_num_queries):
    tenant = big_group
    with organization_context(tenant.organization):
        for index in range(8):
            Lesson.objects.create(
                organization=tenant.organization, module=tenant.module,
                subject=tenant.subject, group=tenant.group, teacher=tenant.teacher,
                starts_at=timezone.now() + dt.timedelta(minutes=index * 60),
            )
    login(client, tenant, tenant.teacher_user)
    with django_assert_max_num_queries(25):
        response = client.get(reverse("cabinet:teacher_today"))
    assert response.status_code == 200
