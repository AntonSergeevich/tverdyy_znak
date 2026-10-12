"""
Итоги прошлых модулей в кабинете ученика.

Жалоба Алины: «сменился модуль, и у ребят не отображаются баллы за
предыдущий». Кабинет показывал только текущий модуль — данные были на
месте, а смотреть их было негде. Хуже всего в каникулярную неделю: тогда
по регламенту добирают незачёты, и надо видеть, по какому предмету и
сколько не хватило.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import organization_context
from apps.journal.models import GradeItem, GradeItemKind, Module, ModuleKind
from apps.journal.services.grading import past_modules, set_grade
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


def _module_with_grade(tenant, *, number, starts, ends, title, points):
    """Модуль с одной работой и баллом за неё у ученика фикстуры."""
    with organization_context(tenant.organization):
        module = Module.objects.create(
            organization=tenant.organization, academic_year=tenant.year,
            kind=ModuleKind.MODULE, number=number, starts_on=starts, ends_on=ends,
        )
        item = GradeItem.objects.create(
            organization=tenant.organization, module=module, subject=tenant.subject,
            group=tenant.group, kind=GradeItemKind.CREDIT, title=title, max_points=25,
        )
        set_grade(student=tenant.student, grade_item=item, points=Decimal(points))
        return module


@pytest.fixture
def finished_module(tenant_a):
    today = timezone.localdate()
    return _module_with_grade(
        tenant_a, number=90, starts=today - dt.timedelta(days=80),
        ends=today - dt.timedelta(days=40), title="Зачёт прошлого модуля", points="18",
    )


def test_the_student_still_sees_the_finished_module(tenant_a, finished_module):
    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert "Прошлые модули" in body
    assert "Зачёт прошлого модуля" in body
    assert "18" in body


def test_the_current_module_is_not_counted_as_past(tenant_a, finished_module):
    """Текущий модуль остаётся наверху и в «прошлые» не попадает дважды."""
    with organization_context(tenant_a.organization):
        item = GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.QUIZ, title="Проверочная текущего", max_points=10,
        )
        set_grade(student=tenant_a.student, grade_item=item, points=Decimal("7"))
        past = past_modules(student=tenant_a.student, current=tenant_a.module)

    assert [entry["module"].pk for entry in past] == [finished_module.pk]


def test_in_the_vacation_week_the_just_finished_module_is_not_lost(tenant_a):
    """
    В каникулярную неделю «текущим» уже считается следующий модуль. Только
    что закончившийся должен попасть в прошлые, а не провалиться между
    двумя блоками.
    """
    today = timezone.localdate()
    with organization_context(tenant_a.organization):
        # Текущий модуль фикстуры начинается после каникул.
        Module.objects.filter(pk=tenant_a.module.pk).update(
            starts_on=today + dt.timedelta(days=3), ends_on=today + dt.timedelta(days=40)
        )
    finished = _module_with_grade(
        tenant_a, number=91, starts=today - dt.timedelta(days=35),
        ends=today - dt.timedelta(days=3), title="Зачёт перед каникулами", points="20",
    )

    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert "Зачёт перед каникулами" in body
    with organization_context(tenant_a.organization):
        tenant_a.module.refresh_from_db()
        past = past_modules(student=tenant_a.student, current=tenant_a.module)
    assert past[0]["module"].pk == finished.pk


def test_a_failed_subject_is_named_in_the_summary(tenant_a, finished_module):
    """Меньше 50 — незачёт: на каникулах его добирают, и это должно быть видно сразу."""
    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert f"Незачёт: {tenant_a.subject.name}" in body


def test_the_latest_past_module_is_open_while_the_new_one_is_empty(tenant_a, finished_module):
    """Первое, что видит ребёнок после смены модуля, — не пустота, а свои итоги."""
    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert '<details class="past-module" open>' in body


def test_the_past_module_is_folded_once_the_new_one_has_points(tenant_a, finished_module):
    with organization_context(tenant_a.organization):
        item = GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.QUIZ, title="Проверочная текущего", max_points=10,
        )
        set_grade(student=tenant_a.student, grade_item=item, points=Decimal("7"))

    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert '<details class="past-module">' in body
    assert '<details class="past-module" open>' not in body


def test_another_student_does_not_see_these_results(tenant_a, tenant_b, finished_module):
    with organization_context(tenant_b.organization):
        assert past_modules(student=tenant_b.student, current=tenant_b.module) == []


@pytest.mark.django_db
def test_a_new_organization_gets_the_scale_of_the_regulation():
    """
    Зачёт и базовый уровень — от 50, продвинутый — от 70, высокий — от 85.

    Команда создания организации зашивала прежние 60/60/70/80. Миграция
    0010 перевела на регламент шкалы, созданные до неё, а новые всё равно
    заводились по-старому — и ребёнок с 55 баллами получал «незачёт».
    """
    from django.core.management import call_command

    from apps.core.models import Organization
    from apps.journal.models import GradingScale

    call_command("bootstrap_organization", "--slug", "novyy-tsentr", "--name", "Новый центр")

    organization = Organization.objects.get(slug="novyy-tsentr")
    scale = GradingScale.all_objects.get(organization=organization, academic_year=None)
    assert (scale.pass_from, scale.base_from, scale.elevated_from, scale.advanced_from) == (
        Decimal("50"), Decimal("50"), Decimal("70"), Decimal("85"),
    )
    assert scale.is_passed(Decimal("50"))
    assert not scale.is_passed(Decimal("49.9"))
