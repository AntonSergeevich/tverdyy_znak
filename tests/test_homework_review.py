"""
Жизненный цикл домашнего задания.

Раньше отметка «сделал» была тупиком: ученик нажимал кнопку, карточка
оставалась висеть на месте, педагог видел один счётчик и не знал, кто
именно отметился, а ответа о проверке не приходило вовсе. Для заданий
без баллов — а таких большинство — обратной связи не было никакой.

Теперь задание проходит через четыре состояния:

    задано → сделал → проверено: зачтено
                       ↘ нужно доделать → (снова сделал)

Здесь проверяется, что оно по ним действительно ходит, что «Сделать» не
теряет несданное и что чужого никто не проверит.
"""
from __future__ import annotations

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import Homework, HomeworkMark, HomeworkVerdict, Lesson
from apps.journal.services import homework as service
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


@pytest.fixture
def homework(tenant_a):
    with organization_context(tenant_a.organization):
        return Homework.objects.create(
            organization=tenant_a.organization, lesson=tenant_a.lesson,
            text="§12, задачи 3–7", due_date=dt.date(2026, 9, 10),
        )


# ─── Состояния ──────────────────────────────────────────────────────────────

def test_the_task_walks_through_its_states(tenant_a, homework):
    student = tenant_a.student
    with organization_context(tenant_a.organization):
        board = service.homework_board(student, module=tenant_a.lesson.module)
        assert homework in board["todo"], "задано — значит, в «Сделать»"

        service.mark_done(homework=homework, student=student, done=True)
        board = service.homework_board(student, module=tenant_a.lesson.module)
        assert board["todo"] == [] and homework in board["review"]

        service.review(
            homework=homework, student=student,
            verdict=HomeworkVerdict.ACCEPTED, comment="молодец",
        )
        board = service.homework_board(student, module=tenant_a.lesson.module)
        assert board["review"] == [] and homework in board["checked"]


def test_sent_back_it_returns_to_the_student(tenant_a, homework):
    """
    «Нужно доделать» — это снова дело ученика, а не архив: иначе
    возвращённое задание оседало бы в «Проверено» и о нём забывали.
    """
    student = tenant_a.student
    with organization_context(tenant_a.organization):
        service.mark_done(homework=homework, student=student, done=True)
        service.review(
            homework=homework, student=student,
            verdict=HomeworkVerdict.REDO, comment="второй пример переделай",
        )

        board = service.homework_board(student, module=tenant_a.lesson.module)
        assert homework in board["todo"]
        assert board["todo"][0].mark.comment == "второй пример переделай"

        # Доделал и отправил заново — проверка снимается, слова педагога
        # остаются: по ним и доделывали.
        service.mark_done(homework=homework, student=student, done=True)
        board = service.homework_board(student, module=tenant_a.lesson.module)
        assert homework in board["review"]
        assert board["review"][0].mark.comment == "второй пример переделай"


def test_a_checked_task_cannot_be_unmarked(tenant_a, homework):
    """Иначе «проверено» ничего не значит, а педагог смотрит одно и то же дважды."""
    student = tenant_a.student
    with organization_context(tenant_a.organization):
        service.mark_done(homework=homework, student=student, done=True)
        service.review(homework=homework, student=student, verdict=HomeworkVerdict.ACCEPTED)

        with pytest.raises(ValidationError):
            service.mark_done(homework=homework, student=student, done=False)


def test_the_teacher_checks_a_notebook_of_someone_who_never_pressed(tenant_a, homework):
    """Работу приносят в тетради: отсутствие нажатия — не отсутствие работы."""
    student = tenant_a.student
    with organization_context(tenant_a.organization):
        service.review(homework=homework, student=student, verdict=HomeworkVerdict.ACCEPTED)
        mark = HomeworkMark.objects.get(homework=homework, student=student)

        assert mark.is_checked and mark.is_accepted
        assert not mark.is_done


def test_a_misclick_can_be_undone(tenant_a, homework):
    """Промах по чужой строке иначе остался бы навсегда."""
    student = tenant_a.student
    with organization_context(tenant_a.organization):
        service.review(homework=homework, student=student, verdict=HomeworkVerdict.REDO)
        service.review(homework=homework, student=student, verdict="")

        # Ни отметки ученика, ни проверки — строке незачем существовать.
        assert not HomeworkMark.objects.filter(homework=homework, student=student).exists()


def test_accept_all_touches_only_those_who_marked_and_are_unchecked(tenant_a, homework):
    """
    «Зачесть всем» не должно закрывать тех, кто ничего не сдавал, и не
    должно перебивать уже поставленное «нужно доделать»: одно нажатие
    отменило бы работу, которую педагог только что сделал руками.
    """
    from apps.journal.models import Student

    with organization_context(tenant_a.organization):
        marked = tenant_a.student
        sent_back = Student.objects.create(
            organization=tenant_a.organization, last_name="Вернули", first_name="Ему",
            grade_level=9, enrolled_on=dt.date(2026, 9, 1),
        )
        silent = Student.objects.create(
            organization=tenant_a.organization, last_name="Молчит", first_name="Он",
            grade_level=9, enrolled_on=dt.date(2026, 9, 1),
        )

        service.mark_done(homework=homework, student=marked, done=True)
        service.mark_done(homework=homework, student=sent_back, done=True)
        service.review(homework=homework, student=sent_back, verdict=HomeworkVerdict.REDO)

        changed = service.accept_marked(homework=homework)

        assert changed == 1
        assert HomeworkMark.objects.get(homework=homework, student=marked).is_accepted
        assert HomeworkMark.objects.get(homework=homework, student=sent_back).needs_redo
        assert not HomeworkMark.objects.filter(homework=homework, student=silent).exists()


# ─── Списки в кабинете ──────────────────────────────────────────────────────

def test_unfinished_work_is_never_silently_cut(tenant_a):
    """
    Старый список обрезался по десятому и молчал об этом, а через неделю
    после срока несданное исчезало совсем. Задолженность не растворяется.
    """
    with organization_context(tenant_a.organization):
        lesson = tenant_a.lesson
        for number in range(14):
            extra = Lesson.objects.create(
                organization=tenant_a.organization, module=lesson.module,
                subject=lesson.subject, group=lesson.group, teacher=lesson.teacher,
                starts_at=lesson.starts_at + dt.timedelta(days=number + 1),
            )
            Homework.objects.create(
                organization=tenant_a.organization, lesson=extra, text=f"задание {number}"
            )

        board = service.homework_board(tenant_a.student, module=lesson.module)

        assert len(board["todo"]) == 14


def test_the_student_sees_what_the_teacher_wrote(tenant_a, homework):
    """
    Комментарий раньше видел только родитель, отдельным списком, из
    которого нельзя было понять, к чему он относится.
    """
    with organization_context(tenant_a.organization):
        service.mark_done(homework=homework, student=tenant_a.student, done=True)
        service.review(
            homework=homework, student=tenant_a.student,
            verdict=HomeworkVerdict.ACCEPTED, comment="аккуратно оформлено",
        )

    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert "аккуратно оформлено" in body
    assert "Зачтено" in body


def test_the_parent_sees_the_same_but_cannot_press(tenant_a, homework):
    """Родителю важно, сделано или нет; отмечать за ребёнка он не должен."""
    body = sign_in(tenant_a, tenant_a.parent_user).get(
        reverse("cabinet:parent_home")
    ).content.decode()

    assert "§12, задачи 3–7" in body
    assert reverse("cabinet:homework_mark", args=[homework.pk]) not in body


# ─── Права ──────────────────────────────────────────────────────────────────

def test_a_student_cannot_check_their_own_homework(tenant_a, homework):
    response = sign_in(tenant_a, tenant_a.student_user).post(
        reverse("cabinet:homework_review", args=[homework.pk, tenant_a.student.pk]),
        {"verdict": "accepted"},
    )

    assert response.status_code in (302, 403)


def test_a_stranger_cannot_check_someone_elses_group(tenant_a, tenant_b, homework):
    """Задание чужой организации не должно даже находиться."""
    response = sign_in(tenant_b, tenant_b.teacher_user).post(
        reverse("cabinet:homework_review", args=[homework.pk, tenant_a.student.pk]),
        {"verdict": "accepted"},
    )

    assert response.status_code in (302, 403, 404)
