"""
Места под занятия в сотне баллов модуля.

План модуля откладывает часть сотни на занятия — по умолчанию сорок баллов
на восемь. Раньше это были мёртвые строки: отметить занятие оцениваемым
значило завести девятую работу сверх плана, сотня мгновенно переполнялась,
и «сделать с оцениванием» переставало работать вообще у всех занятий.

Теперь занятие занимает готовое место, а снятое оценивание возвращает его
в план. Когда мест нет и сотня разобрана — баллы занимаются у занятия,
которое ещё впереди и по которому никто ничего не выставлял.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import Grade, GradeItem, GradeItemKind, Lesson
from apps.journal.services.grading import (
    create_default_structure,
    disable_lesson_grading,
    enable_lesson_grading,
    free_lesson_slots,
    points_budget,
    set_grade,
)
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


@pytest.fixture
def planned(tenant_a):
    """Модуль с разложенной сотней: зачёт, две проверочные, контрольная и 8 занятий."""
    with organization_context(tenant_a.organization):
        create_default_structure(tenant_a.module, tenant_a.subject, tenant_a.group)
    return tenant_a


def test_a_graded_lesson_takes_a_reserved_slot_not_a_new_hundredth(planned, tenant_a):
    """
    Двадцать пять баллов на занятия отложены заранее — занятие занимает место, а не
    добавляет работу сверх плана.

    Именно из-за этого сотня и переполнялась: пять мест пустовали, а
    каждое отмеченное занятие заводило девятую работу.
    """
    with organization_context(tenant_a.organization):
        before = points_budget(tenant_a.module, tenant_a.subject, tenant_a.group)
        assert before.remaining == Decimal("0.00")
        assert free_lesson_slots(tenant_a.module, tenant_a.subject, tenant_a.group).count() == 5

        switch = enable_lesson_grading(tenant_a.lesson)

        after = points_budget(tenant_a.module, tenant_a.subject, tenant_a.group)
        assert after.distributed == before.distributed
        assert free_lesson_slots(tenant_a.module, tenant_a.subject, tenant_a.group).count() == 4

    tenant_a.lesson.refresh_from_db()
    assert tenant_a.lesson.is_graded
    assert switch.item.max_points == Decimal("5.00")
    assert "место" in switch.note


def test_removing_grading_returns_the_slot_to_the_plan(planned, tenant_a):
    """Снятое оценивание не должно обеднять сотню: место возвращается в план."""
    with organization_context(tenant_a.organization):
        enable_lesson_grading(tenant_a.lesson)
        assert free_lesson_slots(tenant_a.module, tenant_a.subject, tenant_a.group).count() == 4

        disable_lesson_grading(tenant_a.lesson)

        assert free_lesson_slots(tenant_a.module, tenant_a.subject, tenant_a.group).count() == 5
        assert points_budget(
            tenant_a.module, tenant_a.subject, tenant_a.group
        ).distributed == Decimal("100.00")

    tenant_a.lesson.refresh_from_db()
    assert not tenant_a.lesson.is_graded


def _extra_lesson(tenant, days: int) -> Lesson:
    return Lesson.objects.create(
        organization=tenant.organization, module=tenant.module, subject=tenant.subject,
        group=tenant.group, teacher=tenant.teacher,
        starts_at=tenant.lesson.starts_at + dt.timedelta(days=days),
    )


def test_when_the_slots_run_out_the_points_come_from_a_lesson_ahead(planned, tenant_a):
    """
    Сотня разобрана, свободных мест нет — но занятие впереди ещё ничего не
    получило. Его баллы переходят сюда, оно становится без оценивания.

    Так «сделать с оцениванием» работает всегда: педагог решает не «можно
    ли», а «за счёт чего».
    """
    with organization_context(tenant_a.organization):
        ahead = [_extra_lesson(tenant_a, day) for day in range(1, 8)]
        for lesson in ahead[:5]:
            enable_lesson_grading(lesson)
        assert free_lesson_slots(tenant_a.module, tenant_a.subject, tenant_a.group).count() == 0

        donor = ahead[4]
        switch = enable_lesson_grading(tenant_a.lesson)

        donor.refresh_from_db()
        assert not donor.is_graded
        assert not GradeItem.objects.filter(lesson=donor).exists()
        assert points_budget(
            tenant_a.module, tenant_a.subject, tenant_a.group
        ).distributed == Decimal("100.00")

    assert "взяты у занятия" in switch.note
    assert switch.item.max_points == Decimal("5.00")


def test_points_are_never_taken_from_a_lesson_that_already_has_grades(planned, tenant_a):
    """Выставленное — чужая работа, а не резерв."""
    with organization_context(tenant_a.organization):
        ahead = [_extra_lesson(tenant_a, day) for day in range(1, 8)]
        for lesson in ahead[:5]:
            enable_lesson_grading(lesson)
        for lesson in ahead[:5]:
            set_grade(
                student=tenant_a.student, grade_item=GradeItem.objects.get(lesson=lesson),
                points=Decimal("3"), actor=tenant_a.owner_user,
            )

        with pytest.raises(ValidationError) as exc:
            enable_lesson_grading(tenant_a.lesson)

    assert "занять их не у кого" in str(exc.value)


def test_points_are_never_taken_from_a_lesson_that_has_already_happened(planned, tenant_a):
    """Занимаем только у того, что впереди: прошедшее занятие уже состоялось."""
    with organization_context(tenant_a.organization):
        earlier = Lesson.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group, teacher=tenant_a.teacher,
            starts_at=tenant_a.lesson.starts_at - dt.timedelta(days=1),
        )
        others = [_extra_lesson(tenant_a, day) for day in range(1, 5)]
        enable_lesson_grading(earlier)
        for lesson in others:
            enable_lesson_grading(lesson)
            # Занятия впереди уже с баллами — занимать у них нельзя, и
            # единственным кандидатом остаётся прошедшее.
            set_grade(
                student=tenant_a.student, grade_item=GradeItem.objects.get(lesson=lesson),
                points=Decimal("2"), actor=tenant_a.owner_user,
            )
        assert free_lesson_slots(tenant_a.module, tenant_a.subject, tenant_a.group).count() == 0

        with pytest.raises(ValidationError):
            enable_lesson_grading(tenant_a.lesson)

        earlier.refresh_from_db()
        assert earlier.is_graded


def test_a_leftover_smaller_than_the_usual_maximum_is_still_used(tenant_a):
    """Занятие на три балла честнее, чем отказ."""
    with organization_context(tenant_a.organization):
        GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.CREDIT, title="Зачёт", max_points=Decimal("97.00"),
        )

        switch = enable_lesson_grading(tenant_a.lesson)

    assert switch.item.max_points == Decimal("3.00")
    assert "оставалось" in switch.note


def test_grading_cannot_be_removed_while_the_points_stand(planned, tenant_a):
    """Снять оценивание с занятия, по которому баллы уже стоят, нельзя."""
    with organization_context(tenant_a.organization):
        enable_lesson_grading(tenant_a.lesson)
        set_grade(
            student=tenant_a.student,
            grade_item=GradeItem.objects.get(lesson=tenant_a.lesson),
            points=Decimal("4"), actor=tenant_a.owner_user,
        )

        with pytest.raises(ValidationError):
            disable_lesson_grading(tenant_a.lesson)

    tenant_a.lesson.refresh_from_db()
    assert tenant_a.lesson.is_graded


def test_a_day_block_never_becomes_graded(tenant_a):
    """Утренний круг и обед — не учебный предмет, баллов за них нет."""
    from apps.journal.models import Subject, SubjectKind

    with organization_context(tenant_a.organization):
        block = Subject.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            name="Утренний круг", kind=SubjectKind.ACTIVITY,
        )
        tenant_a.lesson.subject = block
        tenant_a.lesson.save(update_fields=["subject"])

        with pytest.raises(ValidationError):
            enable_lesson_grading(tenant_a.lesson)


def test_the_switch_tells_where_the_points_came_from(planned, tenant_a):
    """Педагог должен видеть, что произошло, а не гадать."""
    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.post(
        reverse("cabinet:lesson_toggle_graded", args=[tenant_a.lesson.pk]),
        {"is_graded": "1"},
    ).content.decode()

    assert "Занято место" in body
    assert "data-dial-open" in body


def test_the_journal_shows_how_many_points_are_available(planned, tenant_a):
    """
    Сколько можно поставить сейчас и сколько у ученика уже есть — оба числа
    на экране: «пять из пяти» без «а всего тридцать семь из ста» — половина
    картинки.
    """
    with organization_context(tenant_a.organization):
        enable_lesson_grading(tenant_a.lesson)
        set_grade(
            student=tenant_a.student,
            grade_item=GradeItem.objects.get(lesson=tenant_a.lesson),
            points=Decimal("4"), actor=tenant_a.owner_user,
        )

    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(
        reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk])
    ).content.decode()

    assert "Сегодня каждому можно поставить до" in body
    assert 'data-module-total="4"' in body
    assert 'data-module-limit="100"' in body
