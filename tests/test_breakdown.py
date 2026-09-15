"""
Из чего сложились баллы.

Ученик видел только итог — «60 из 100» — и не мог узнать, за что именно.
Сумма без слагаемых не объясняет ничего и спорить с ней нечем: непонятно,
где недобрал, что ещё впереди и какую работу пересдавать. Регламент
требует обратного: критерии известны заранее, результат разбирают
с педагогом.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import GradeItem, GradeItemKind
from apps.journal.services.grading import grade_breakdown, set_grade
from apps.journal.services.homework import save_homework
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


@pytest.fixture
def works(tenant_a):
    """Зачёт с баллом, контрольная впереди и домашнее с баллом."""
    with organization_context(tenant_a.organization):
        credit = GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.CREDIT, title="Зачёт по модулю", max_points=25,
            due_date=dt.date(2026, 9, 30),
        )
        ahead = GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.TEST, title="Контрольная работа", max_points=15,
        )
        homework = save_homework(
            lesson=tenant_a.lesson, text="§14, задачи 5–9", max_points=5,
        )
        set_grade(
            student=tenant_a.student, grade_item=credit, points=Decimal("20"),
            comment="логика сильная, оформление хромает",
        )
        set_grade(
            student=tenant_a.student, grade_item=homework.grade_item, points=Decimal("4"),
        )
        return {"credit": credit, "ahead": ahead, "homework": homework}


def test_every_work_is_listed_with_its_points(tenant_a, works):
    with organization_context(tenant_a.organization):
        rows = grade_breakdown(student=tenant_a.student, module=tenant_a.module)[
            tenant_a.subject.id
        ]

    assert rows["earned"] == Decimal("24")
    assert rows["planned"] == Decimal("45")
    graded = {row["item"].title: row["grade"] for row in rows["rows"] if row["is_graded"]}
    assert graded["Зачёт по модулю"].points == Decimal("20")


def test_work_ahead_is_shown_but_is_not_a_zero(tenant_a, works):
    """
    «Контрольная, 15 баллов, ещё не было» объясняет, почему в модуле пока
    двадцать четыре. Без этой строки то же число читается как потеря.
    """
    with organization_context(tenant_a.organization):
        rows = grade_breakdown(student=tenant_a.student, module=tenant_a.module)[
            tenant_a.subject.id
        ]

    ahead = [row for row in rows["rows"] if not row["is_graded"]]
    assert [row["item"].title for row in ahead] == ["Контрольная работа"]
    assert ahead[0]["grade"] is None


def test_a_work_is_named_the_way_the_student_remembers_it(tenant_a, works):
    """
    «Домашняя работа» восемь раз подряд — не ответ на вопрос «за что».
    Занятие вспоминают по теме, домашнее — по тексту задания.
    """
    with organization_context(tenant_a.organization):
        rows = grade_breakdown(student=tenant_a.student, module=tenant_a.module)[
            tenant_a.subject.id
        ]

    names = [row["what"] for row in rows["rows"]]
    assert "§14, задачи 5–9" in names


def test_the_student_sees_it_in_the_cabinet(tenant_a, works):
    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert "§14, задачи 5–9" in body
    assert "логика сильная, оформление хромает" in body
    assert "Зачёт по модулю" in body


def test_the_parent_sees_the_same(tenant_a, works):
    body = sign_in(tenant_a, tenant_a.parent_user).get(
        reverse("cabinet:parent_home")
    ).content.decode()

    assert "§14, задачи 5–9" in body
    assert "логика сильная, оформление хромает" in body


def test_a_total_without_works_behind_it_is_named_aloud(tenant_a, works):
    """
    У перенесённой истории баллов по работам нет вовсе. Показать под
    шестьюдесятью ноль и промолчать — значит сказать ребёнку, что баллы
    пропали.
    """
    from apps.journal.models import ModuleResult

    with organization_context(tenant_a.organization):
        ModuleResult.objects.update_or_create(
            organization=tenant_a.organization, student=tenant_a.student,
            subject=tenant_a.subject, module=tenant_a.module,
            defaults={"total_points": Decimal("60")},
        )

    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert "перенесли из прежнего журнала" in body


def test_matching_numbers_say_nothing_extra(tenant_a, works):
    """Обычный случай — сумма сходится, и объясняться не о чем."""
    from apps.journal.models import ModuleResult

    with organization_context(tenant_a.organization):
        ModuleResult.objects.update_or_create(
            organization=tenant_a.organization, student=tenant_a.student,
            subject=tenant_a.subject, module=tenant_a.module,
            defaults={"total_points": Decimal("24")},
        )

    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert "перенесли из прежнего журнала" not in body


def test_someone_elses_works_do_not_leak(tenant_a, tenant_b, works):
    """Разбивка берётся по группам ученика, а не по всему модулю."""
    with organization_context(tenant_b.organization):
        rows = grade_breakdown(student=tenant_b.student, module=tenant_b.module)

    assert tenant_a.subject.id not in rows
