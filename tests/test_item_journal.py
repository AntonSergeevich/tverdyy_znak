"""
Журнал отдельной работы модуля.

Проверочную, контрольную и зачёт можно было завести в плане модуля —
а выставить за них баллы негде. Выставление жило только у занятия, потом
появилось у домашнего задания, а эти три работы не привязаны ни к тому,
ни к другому. Вместе это 25 + 15 + 10 + 10 — больше половины модуля,
и закрывается модуль как раз зачётом.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import Grade, GradeItem, GradeItemKind
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


@pytest.fixture
def quiz(tenant_a):
    """Проверочная работа — та самая, за которую Дарья не могла поставить баллы."""
    with organization_context(tenant_a.organization):
        return GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.QUIZ, title="Проверочная по причастиям",
            max_points=10, due_date=dt.date(2026, 9, 24),
        )


def test_the_work_has_a_journal_of_its_own(tenant_a, quiz):
    body = sign_in(tenant_a, tenant_a.teacher_user).get(
        reverse("cabinet:item_journal", args=[quiz.pk])
    ).content.decode()

    assert "Проверочная по причастиям" in body
    assert tenant_a.student.short_name in body
    assert reverse("cabinet:item_grade_save", args=[quiz.pk]) in body


def test_points_for_the_work_are_saved(tenant_a, quiz):
    response = sign_in(tenant_a, tenant_a.teacher_user).post(
        reverse("cabinet:item_grade_save", args=[quiz.pk]),
        {"student": str(tenant_a.student.pk), "points": "8", "comment": "разбор верный"},
    )

    assert response.status_code == 200
    with organization_context(tenant_a.organization):
        grade = Grade.objects.get(grade_item=quiz, student=tenant_a.student)
        assert grade.points == 8
        assert grade.comment == "разбор верный"


def test_more_than_the_maximum_is_refused_with_a_reason(tenant_a, quiz):
    """Ошибку показываем в строке, а не общим алертом: htmx не меняет 4xx молча."""
    response = sign_in(tenant_a, tenant_a.teacher_user).post(
        reverse("cabinet:item_grade_save", args=[quiz.pk]),
        {"student": str(tenant_a.student.pk), "points": "12"},
    )

    assert response.status_code == 422
    with organization_context(tenant_a.organization):
        assert not Grade.objects.filter(grade_item=quiz, student=tenant_a.student).exists()


def test_one_point_for_everyone_skips_those_already_graded(tenant_a, quiz):
    """Перезаписать проверенную работу молча — худшее, что сделает «удобная» кнопка."""
    from apps.journal.services.grading import set_grade

    with organization_context(tenant_a.organization):
        set_grade(student=tenant_a.student, grade_item=quiz, points=Decimal("9"))

    sign_in(tenant_a, tenant_a.teacher_user).post(
        reverse("cabinet:item_grade_bulk", args=[quiz.pk]), {"points": "5"},
    )

    with organization_context(tenant_a.organization):
        assert Grade.objects.get(grade_item=quiz, student=tenant_a.student).points == 9


def test_one_point_for_everyone_overwrites_when_asked(tenant_a, quiz):
    sign_in(tenant_a, tenant_a.teacher_user).post(
        reverse("cabinet:item_grade_bulk", args=[quiz.pk]),
        {"points": "7", "overwrite": "1"},
    )

    with organization_context(tenant_a.organization):
        assert Grade.objects.get(grade_item=quiz, student=tenant_a.student).points == 7


def test_the_plan_row_leads_to_the_journal(tenant_a, quiz):
    """Путь к выставлению — с той же строки, где работу завели."""
    body = sign_in(tenant_a, tenant_a.teacher_user).get(
        reverse(
            "cabinet:module_plan",
            args=[tenant_a.module.pk, tenant_a.subject.pk, tenant_a.group.pk],
        )
    ).content.decode()

    assert reverse("cabinet:item_journal", args=[quiz.pk]) in body


def test_the_student_sees_the_points_in_the_breakdown(tenant_a, quiz):
    sign_in(tenant_a, tenant_a.teacher_user).post(
        reverse("cabinet:item_grade_save", args=[quiz.pk]),
        {"student": str(tenant_a.student.pk), "points": "8", "comment": "разбор верный"},
    )

    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert "Проверочная по причастиям" in body
    assert "разбор верный" in body


# ─── Путь от занятия ────────────────────────────────────────────────────────

def test_the_lesson_shows_the_works_of_the_module(tenant_a, quiz):
    """
    «Мы писали словарный диктант на уроке» — значит, и искать будут в уроке.
    План модуля педагог не открывает, и до этого списка проверочная была
    видна только там.
    """
    body = sign_in(tenant_a, tenant_a.teacher_user).get(
        reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk])
    ).content.decode()

    assert "Проверочная по причастиям" in body
    assert reverse("cabinet:item_journal", args=[quiz.pk]) in body


def test_the_lesson_points_at_where_separate_works_live(tenant_a):
    """
    Педагог, который провёл на уроке диктант, смотрит в список учеников,
    видит «без баллов» и решает, что больше ставить негде.
    """
    body = sign_in(tenant_a, tenant_a.teacher_user).get(
        reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk])
    ).content.decode()

    assert "отдельные работы модуля" in body
    assert "Проверочные, контрольная и зачёт" in body


def test_a_work_is_created_from_the_lesson_and_opens_at_once(tenant_a):
    """Завести и сразу выставлять — один шаг там, где педагог уже стоит."""
    from apps.journal.models import GradeItem

    response = sign_in(tenant_a, tenant_a.teacher_user).post(
        reverse("cabinet:lesson_work_add", args=[tenant_a.lesson.pk]),
        {"title": "Словарный диктант", "kind": "quiz", "max_points": "5"},
    )

    with organization_context(tenant_a.organization):
        item = GradeItem.objects.get(title="Словарный диктант")
        assert item.max_points == 5
        assert item.kind == GradeItemKind.QUIZ
        assert item.lesson_id is None
        assert response.status_code == 302
        assert response.headers["Location"] == reverse(
            "cabinet:item_journal", args=[item.pk]
        )


def test_a_work_that_does_not_fit_the_hundred_is_refused_with_a_reason(tenant_a):
    """Сотня модуля не резиновая, и отказ должен объяснять, сколько осталось."""
    from apps.journal.models import GradeItem

    response = sign_in(tenant_a, tenant_a.teacher_user).post(
        reverse("cabinet:lesson_work_add", args=[tenant_a.lesson.pk]),
        {"title": "Слишком дорогая", "kind": "test", "max_points": "200"},
        follow=True,
    )

    with organization_context(tenant_a.organization):
        assert not GradeItem.objects.filter(title="Слишком дорогая").exists()
    assert "лимит" in " ".join(str(m) for m in response.context["messages"]).lower()


def test_work_on_the_lesson_is_not_created_as_a_separate_work(tenant_a):
    """
    За работу на уроке баллы ставятся в самом занятии. Завести её ещё и
    отдельной строкой значило бы дважды занять одно и то же место в сотне.
    """
    from apps.journal.models import GradeItem

    sign_in(tenant_a, tenant_a.teacher_user).post(
        reverse("cabinet:lesson_work_add", args=[tenant_a.lesson.pk]),
        {"title": "Работа на уроке", "kind": "lesson", "max_points": "5"},
    )

    with organization_context(tenant_a.organization):
        assert not GradeItem.objects.filter(title="Работа на уроке").exists()


def test_the_lesson_says_plainly_that_the_check_is_about_homework(tenant_a):
    """«Проверка заданного сегодня» читалась как проверка чего угодно."""
    from apps.journal.services.homework import save_homework

    with organization_context(tenant_a.organization):
        save_homework(lesson=tenant_a.lesson, text="§14")

    body = sign_in(tenant_a, tenant_a.teacher_user).get(
        reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk])
    ).content.decode()

    assert "Проверить домашнее, заданное сегодня" in body


# ─── Права ──────────────────────────────────────────────────────────────────

def test_a_stranger_cannot_grade_someone_elses_work(tenant_a, tenant_b, quiz):
    response = sign_in(tenant_b, tenant_b.teacher_user).post(
        reverse("cabinet:item_grade_save", args=[quiz.pk]),
        {"student": str(tenant_a.student.pk), "points": "8"},
    )

    assert response.status_code in (302, 403, 404)


def test_a_teacher_without_lessons_in_this_pair_is_refused(tenant_a, quiz):
    """
    Право считается по занятиям связки модуль-предмет-группа целиком.
    Педагог, который ведёт этот предмет другой группе, к этой работе
    отношения не имеет.
    """
    from apps.accounts.models import Membership, Role, User
    from apps.journal.models import Group, Lesson, Teacher

    with organization_context(tenant_a.organization):
        other_user = User.objects.create_user(
            email="quiz-stranger@example.org", password=PASSWORD,
            last_name="Соседний", first_name="Педагог",
        )
        Membership.objects.create(
            user=other_user, organization=tenant_a.organization, role=Role.TEACHER
        )
        other_teacher = Teacher.objects.create(
            organization=tenant_a.organization, user=other_user,
        )
        other_group = Group.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            name="Класс 11", grade_level=11,
        )
        # Тот же предмет, но другая группа.
        Lesson.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=other_group, teacher=other_teacher,
            starts_at=tenant_a.lesson.starts_at,
        )

    response = sign_in(tenant_a, other_user).get(
        reverse("cabinet:item_journal", args=[quiz.pk])
    )

    assert response.status_code in (302, 403)


def test_a_student_cannot_grade(tenant_a, quiz):
    response = sign_in(tenant_a, tenant_a.student_user).post(
        reverse("cabinet:item_grade_save", args=[quiz.pk]),
        {"student": str(tenant_a.student.pk), "points": "10"},
    )

    assert response.status_code in (302, 403)
