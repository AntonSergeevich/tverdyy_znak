"""Права по ролям и объектный доступ (ТЗ 3.2, 9.5)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Membership, Role, User
from apps.core.tenancy import organization_context
from apps.journal.models import (
    Group,
    GroupMembership,
    Lesson,
    Student,
    Teacher,
)
from tests.conftest import PASSWORD, login


def test_anonymous_is_redirected_to_login(client, tenant_a):
    client.defaults["HTTP_HOST"] = tenant_a.host
    response = client.get(reverse("cabinet:dashboard"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response["Location"]


@pytest.mark.parametrize(
    "user_attr, url_name, allowed",
    [
        ("owner_user", "cabinet:dashboard", True),
        ("teacher_user", "cabinet:dashboard", False),
        ("parent_user", "cabinet:dashboard", False),
        ("student_user", "cabinet:dashboard", False),
        ("teacher_user", "cabinet:teacher_today", True),
        ("parent_user", "cabinet:teacher_today", False),
        ("student_user", "cabinet:teacher_today", False),
        ("parent_user", "cabinet:parent_home", True),
        ("teacher_user", "cabinet:parent_home", False),
        ("student_user", "cabinet:student_home", True),
        ("parent_user", "cabinet:student_home", False),
        ("owner_user", "cabinet:payroll", True),
        ("teacher_user", "cabinet:payroll", False),
    ],
)
def test_role_matrix(client, tenant_a, user_attr, url_name, allowed):
    login(client, tenant_a, getattr(tenant_a, user_attr))
    response = client.get(reverse(url_name))
    if allowed:
        assert response.status_code == 200
    else:
        assert response.status_code == 403


def test_teacher_cannot_open_other_teachers_lesson(client, tenant_a):
    """Подстановка id чужого занятия не должна открывать журнал."""
    with organization_context(tenant_a.organization):
        other_user = User.objects.create_user(
            email="other-teacher@example.org", password=PASSWORD,
            last_name="Другой", first_name="Педагог",
        )
        Membership.objects.create(
            user=other_user, organization=tenant_a.organization, role=Role.TEACHER
        )
        Teacher.objects.create(organization=tenant_a.organization, user=other_user)

    login(client, tenant_a, other_user)
    response = client.get(reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk]))
    assert response.status_code == 403


def test_parent_cannot_open_other_child(client, tenant_a):
    with organization_context(tenant_a.organization):
        stranger = Student.objects.create(
            organization=tenant_a.organization, last_name="Чужой", first_name="Ребёнок",
            grade_level=10,
        )
    login(client, tenant_a, tenant_a.parent_user)
    response = client.get(reverse("cabinet:parent_child", args=[stranger.pk]))
    assert response.status_code == 403


def test_student_sees_only_own_data(client, tenant_a):
    with organization_context(tenant_a.organization):
        stranger = Student.objects.create(
            organization=tenant_a.organization, last_name="Соседний", first_name="Ученик",
            grade_level=9,
        )
    login(client, tenant_a, tenant_a.student_user)
    body = client.get(reverse("cabinet:student_home")).content.decode()
    assert tenant_a.student.first_name in body
    assert stranger.last_name not in body


def test_teacher_can_grade_only_own_lesson(client, tenant_a):
    """Проверяем именно POST: чтение и запись должны быть закрыты одинаково."""
    with organization_context(tenant_a.organization):
        other_group = Group.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year, name="Чужая группа"
        )
        foreign_lesson = Lesson.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=other_group, teacher=None,
            starts_at=timezone.now(), is_graded=True,
        )
    login(client, tenant_a, tenant_a.teacher_user)
    response = client.post(
        reverse("cabinet:grade_save", args=[foreign_lesson.pk]),
        {"student": str(tenant_a.student.pk), "points": "3"},
    )
    assert response.status_code == 403


def test_membership_in_other_organization_gives_no_access(client, tenant_a, tenant_b):
    """Роль владельца в организации Б не открывает панель организации А."""
    login(client, tenant_b, tenant_b.owner_user)
    client.defaults["HTTP_HOST"] = tenant_a.host
    response = client.get(reverse("cabinet:dashboard"))
    assert response.status_code in (302, 403)
