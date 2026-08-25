"""
Общие фикстуры.

Ключевая идея: в тестах всегда есть ДВЕ организации с одинаковым набором
данных. Любая проверка доступа автоматически проверяется и на утечку
между арендаторами.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Membership, Role, User
from apps.core.models import Organization, OrganizationDomain
from apps.core.tenancy import organization_context
from apps.journal.models import (
    AcademicYear,
    GradingScale,
    Group,
    GroupMembership,
    Lesson,
    Module,
    ModuleKind,
    Parent,
    Student,
    StudentParent,
    Subject,
    Teacher,
)

PASSWORD = "test-parol-12345"


class Tenant:
    """Готовая организация со всем набором сущностей для тестов."""

    def __init__(self, org, host, **objects):
        self.organization = org
        self.host = host
        for name, value in objects.items():
            setattr(self, name, value)


def _build_tenant(slug: str, host: str, suffix: str) -> Tenant:
    # Логины строим по латинскому slug: email с кириллицей невалиден.
    organization = Organization.objects.create(
        name=f"Центр {suffix}", slug=slug, timezone="Asia/Krasnoyarsk"
    )
    OrganizationDomain.objects.create(organization=organization, host=host, is_primary=True)

    with organization_context(organization):
        year = AcademicYear.objects.create(
            organization=organization, title="2026/27",
            starts_on=dt.date(2026, 9, 1), ends_on=dt.date(2027, 5, 21), is_current=True,
        )
        GradingScale.objects.create(organization=organization, academic_year=None)
        subject = Subject.objects.create(
            organization=organization, academic_year=year, name="Математика", weekly_hours=6
        )
        module = Module.objects.create(
            organization=organization, academic_year=year, kind=ModuleKind.MODULE,
            number=1, starts_on=dt.date(2026, 9, 1), ends_on=dt.date(2026, 10, 2),
        )
        group = Group.objects.create(
            organization=organization, academic_year=year, name=f"Класс {suffix}", grade_level=9
        )

        owner_user = User.objects.create_user(
            email=f"owner-{slug}@example.org", password=PASSWORD,
            last_name="Владелец", first_name=suffix,
        )
        Membership.objects.create(user=owner_user, organization=organization, role=Role.OWNER)

        teacher_user = User.objects.create_user(
            email=f"teacher-{slug}@example.org", password=PASSWORD,
            last_name="Педагог", first_name=suffix,
        )
        Membership.objects.create(user=teacher_user, organization=organization, role=Role.TEACHER)
        teacher = Teacher.objects.create(
            organization=organization, user=teacher_user, hourly_rate=Decimal("1000.00")
        )
        teacher.subjects.add(subject)

        parent_user = User.objects.create_user(
            email=f"parent-{slug}@example.org", password=PASSWORD,
            last_name="Родитель", first_name=suffix,
        )
        Membership.objects.create(user=parent_user, organization=organization, role=Role.PARENT)
        parent = Parent.objects.create(
            organization=organization, user=parent_user, last_name="Родитель", first_name=suffix
        )

        student_user = User.objects.create_user(
            email=f"student-{slug}@example.org", password=PASSWORD,
            last_name="Ученик", first_name=suffix,
        )
        Membership.objects.create(user=student_user, organization=organization, role=Role.STUDENT)
        student = Student.objects.create(
            organization=organization, last_name=f"Ученик{suffix}", first_name=suffix,
            grade_level=9, user=student_user, enrolled_on=dt.date(2026, 9, 1),
            birth_date=dt.date(2010, 3, 14),
        )
        GroupMembership.objects.create(organization=organization, group=group, student=student)
        StudentParent.objects.create(organization=organization, student=student, parent=parent)

        lesson = Lesson.objects.create(
            organization=organization, module=module, subject=subject, group=group,
            teacher=teacher, starts_at=timezone.now(), topic="Тема", is_graded=False,
        )

    return Tenant(
        organization, host,
        year=year, subject=subject, module=module, group=group, lesson=lesson,
        owner_user=owner_user, teacher_user=teacher_user, teacher=teacher,
        parent_user=parent_user, parent=parent, student_user=student_user, student=student,
    )


@pytest.fixture
def tenant_a(db) -> Tenant:
    return _build_tenant("centr-a", "a.example.com", "А")


@pytest.fixture
def tenant_b(db) -> Tenant:
    return _build_tenant("centr-b", "b.example.com", "Б")


@pytest.fixture
def client_a(client, tenant_a):
    client.defaults["HTTP_HOST"] = tenant_a.host
    return client


def login(client, tenant: Tenant, user) -> None:
    client.defaults["HTTP_HOST"] = tenant.host
    assert client.login(username=user.email, password=PASSWORD)
