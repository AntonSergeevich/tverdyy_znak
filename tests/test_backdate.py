"""
Баллы задним числом: руководитель открывает их одному педагогу.

Алина: «историк баллы не выставил за прошлый модуль, и система не даёт,
потому что 14 дней. Можешь открыть?» Срок — защита от правки оценок
задним числом, раздвигать его всем нельзя. Открываем одному педагогу,
за один модуль и на несколько дней, и закрывается это само.
"""
from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import organization_context
from apps.journal.models import (
    BackdateGrant,
    Grade,
    GradeItem,
    GradeItemKind,
    Lesson,
    Module,
    ModuleKind,
)
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def sign_in(tenant, user):
    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


@pytest.fixture
def last_module(tenant_a):
    """Прошлый модуль и контрольная в нём — давно, за пределами 14 дней."""
    today = timezone.localdate()
    with organization_context(tenant_a.organization):
        module = Module.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            kind=ModuleKind.MODULE, number=0,
            starts_on=today - dt.timedelta(days=58), ends_on=today - dt.timedelta(days=23),
        )
        # Педагог вёл этот предмет в том модуле — иначе работа ему не видна вовсе.
        Lesson.objects.create(
            organization=tenant_a.organization, module=module, subject=tenant_a.subject,
            group=tenant_a.group, teacher=tenant_a.teacher,
            starts_at=timezone.now() - dt.timedelta(days=30),
        )
        work = GradeItem.objects.create(
            organization=tenant_a.organization, module=module, subject=tenant_a.subject,
            group=tenant_a.group, kind=GradeItemKind.TEST, title="Контрольная",
            max_points=15, due_date=today - dt.timedelta(days=30),
        )
    return module, work


def _grade(client, tenant, work, points="12"):
    return client.post(
        reverse("cabinet:item_grade_save", args=[work.pk]),
        {"student": str(tenant.student.pk), "points": points},
    )


def _has_grade(tenant, work):
    with organization_context(tenant.organization):
        return Grade.objects.filter(grade_item=work, student=tenant.student).exists()


def test_late_points_are_refused_until_the_owner_opens_them(tenant_a, last_module):
    module, work = last_module
    teacher = sign_in(tenant_a, tenant_a.teacher_user)

    assert _grade(teacher, tenant_a, work).status_code != 200
    assert not _has_grade(tenant_a, work)

    owner = sign_in(tenant_a, tenant_a.owner_user)
    response = owner.post(
        reverse("cabinet:backdate_open", args=[tenant_a.teacher_user.pk]),
        {"module": str(module.pk), "days": "3"},
    )
    assert response.status_code == 302

    assert _grade(teacher, tenant_a, work).status_code == 200
    assert _has_grade(tenant_a, work)


def test_opening_is_limited_to_its_module(tenant_a, last_module):
    module, work = last_module
    today = timezone.localdate()
    with organization_context(tenant_a.organization):
        older = Module.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            kind=ModuleKind.MODULE, number=9,
            starts_on=today - dt.timedelta(days=59), ends_on=today - dt.timedelta(days=59),
        )
        BackdateGrant.objects.create(
            organization=tenant_a.organization, user=tenant_a.teacher_user, module=older,
            until=timezone.now() + dt.timedelta(days=3),
        )

    assert _grade(sign_in(tenant_a, tenant_a.teacher_user), tenant_a, work).status_code != 200


def test_opening_closes_by_itself_and_by_hand(tenant_a, last_module):
    module, work = last_module
    with organization_context(tenant_a.organization):
        expired = BackdateGrant.objects.create(
            organization=tenant_a.organization, user=tenant_a.teacher_user, module=module,
            until=timezone.now() - dt.timedelta(minutes=1),
        )
    teacher = sign_in(tenant_a, tenant_a.teacher_user)
    assert _grade(teacher, tenant_a, work).status_code != 200

    with organization_context(tenant_a.organization):
        expired.until = timezone.now() + dt.timedelta(days=1)
        expired.save()
    sign_in(tenant_a, tenant_a.owner_user).post(reverse("cabinet:backdate_close", args=[expired.pk]))

    assert _grade(teacher, tenant_a, work).status_code != 200
    assert not _has_grade(tenant_a, work)


def test_only_the_owner_opens_it(tenant_a, last_module):
    module, _work = last_module
    teacher = sign_in(tenant_a, tenant_a.teacher_user)

    response = teacher.post(
        reverse("cabinet:backdate_open", args=[tenant_a.teacher_user.pk]),
        {"module": str(module.pk), "days": "7"},
    )

    assert response.status_code == 403
    with organization_context(tenant_a.organization):
        assert not BackdateGrant.objects.exists()


def test_owner_sees_the_switch_and_teacher_sees_the_news(tenant_a, last_module):
    module, _work = last_module
    owner = sign_in(tenant_a, tenant_a.owner_user)
    card = owner.get(reverse("cabinet:staff_card", args=[tenant_a.teacher_user.pk])).content.decode()
    assert "Баллы задним числом" in card
    assert reverse("cabinet:backdate_open", args=[tenant_a.teacher_user.pk]) in card

    owner.post(
        reverse("cabinet:backdate_open", args=[tenant_a.teacher_user.pk]),
        {"module": str(module.pk), "days": "3"},
    )
    today = sign_in(tenant_a, tenant_a.teacher_user).get(reverse("cabinet:teacher_today")).content.decode()
    assert "выставление баллов задним числом" in today
    assert "?n=-" in today
