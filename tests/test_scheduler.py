"""Конструктор расписания: карточки педагогов в сетку (ТЗ 5.4)."""
from __future__ import annotations

import datetime as dt

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.journal.models import Lesson
from tests.conftest import PASSWORD


@pytest.fixture
def admin_client(client, tenant_a):
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.defaults["HTTP_HOST"] = tenant_a.host
        client.post(
            reverse("accounts:login"),
            {"username": tenant_a.owner_user.email, "password": PASSWORD},
        )
        yield client


def _monday_inside_module(tenant):
    day = tenant.module.starts_on
    monday = day - dt.timedelta(days=day.weekday())
    if monday < tenant.module.starts_on:
        monday += dt.timedelta(days=7)
    return monday


def test_builder_shows_teachers_and_grid(admin_client, tenant_a):
    response = admin_client.get(reverse("cabinet:schedule_builder"))
    body = response.content.decode()

    assert response.status_code == 200
    assert 'data-teacher="' in body
    assert 'data-slot' in body
    assert tenant_a.teacher.user.last_name in body


def test_dropping_a_teacher_creates_a_lesson(admin_client, tenant_a):
    monday = _monday_inside_module(tenant_a)
    response = admin_client.post(
        reverse("cabinet:slot_set"),
        {
            "group": str(tenant_a.group.pk),
            "teacher": str(tenant_a.teacher.pk),
            "subject": str(tenant_a.subject.pk),
            "day": monday.isoformat(),
            "time": "09:30",
            "duration": "40",
        },
    )

    assert response.status_code == 200
    lesson = Lesson.all_objects.get(
        organization=tenant_a.organization, group=tenant_a.group,
        starts_at__date=monday, teacher=tenant_a.teacher,
    )
    local = lesson.starts_at.astimezone(tenant_a.organization.tzinfo)
    assert (local.hour, local.minute) == (9, 30)
    assert tenant_a.subject.name in response.content.decode()


def test_dropping_onto_a_busy_slot_replaces_rather_than_duplicates(admin_client, tenant_a):
    """
    Перетаскивание поверх занятого означает «пусть тут будет вот это».

    Иначе в одной клетке копились бы невидимые дубли.
    """
    monday = _monday_inside_module(tenant_a)
    payload = {
        "group": str(tenant_a.group.pk),
        "teacher": str(tenant_a.teacher.pk),
        "subject": str(tenant_a.subject.pk),
        "day": monday.isoformat(),
        "time": "10:20",
    }
    admin_client.post(reverse("cabinet:slot_set"), payload)
    admin_client.post(reverse("cabinet:slot_set"), payload)

    assert Lesson.all_objects.filter(
        organization=tenant_a.organization, group=tenant_a.group,
        starts_at__date=monday,
    ).count() == 1


def test_teacher_cannot_be_in_two_places_at_once(admin_client, tenant_a):
    """
    Один педагог, две группы, одно время — это ошибка составления.

    Молча создать такое занятие значит подставить педагога в день,
    когда он придёт и обнаружит два класса.
    """
    from apps.journal.models import Group

    other = Group.all_objects.create(
        organization=tenant_a.organization, academic_year=tenant_a.year,
        name="Класс 11", grade_level=11,
    )
    monday = _monday_inside_module(tenant_a)
    base = {
        "teacher": str(tenant_a.teacher.pk),
        "subject": str(tenant_a.subject.pk),
        "day": monday.isoformat(),
        "time": "11:10",
    }
    admin_client.post(reverse("cabinet:slot_set"), {**base, "group": str(tenant_a.group.pk)})
    clash = admin_client.post(reverse("cabinet:slot_set"), {**base, "group": str(other.pk)})

    assert clash.status_code == 409
    assert "уже ведёт" in clash.json()["error"]


def test_slot_outside_any_module_is_refused(admin_client, tenant_a):
    far = tenant_a.module.ends_on + dt.timedelta(days=400)
    response = admin_client.post(
        reverse("cabinet:slot_set"),
        {
            "group": str(tenant_a.group.pk),
            "teacher": str(tenant_a.teacher.pk),
            "subject": str(tenant_a.subject.pk),
            "day": far.isoformat(),
            "time": "09:30",
        },
    )

    assert response.status_code == 400
    assert "модуль" in response.json()["error"]


def test_teacher_with_many_subjects_must_be_told_which_one(admin_client, tenant_a):
    """Угадывать из нескольких предметов нельзя: выйдет химия вместо биологии."""
    from apps.journal.models import Subject

    second = Subject.all_objects.create(
        organization=tenant_a.organization, academic_year=tenant_a.year,
        name="Физика", weekly_hours=2,
    )
    tenant_a.teacher.subjects.add(second)
    monday = _monday_inside_module(tenant_a)

    response = admin_client.post(
        reverse("cabinet:slot_set"),
        {
            "group": str(tenant_a.group.pk),
            "teacher": str(tenant_a.teacher.pk),
            "day": monday.isoformat(),
            "time": "12:00",
        },
    )

    assert response.status_code == 400
    assert "выберите" in response.json()["error"].lower()


def test_clearing_a_graded_lesson_asks_first(admin_client, tenant_a):
    """
    За занятие уже ставили баллы — молча стереть их нельзя.

    Спрашиваем один раз и удаляем только по явному подтверждению.
    """
    from apps.journal.models import GradeItem, GradeItemKind

    monday = _monday_inside_module(tenant_a)
    admin_client.post(
        reverse("cabinet:slot_set"),
        {
            "group": str(tenant_a.group.pk), "teacher": str(tenant_a.teacher.pk),
            "subject": str(tenant_a.subject.pk), "day": monday.isoformat(), "time": "14:10",
        },
    )
    lesson = Lesson.all_objects.get(
        organization=tenant_a.organization, group=tenant_a.group, starts_at__date=monday
    )
    GradeItem.all_objects.create(
        organization=tenant_a.organization, module=lesson.module, subject=lesson.subject,
        group=lesson.group, lesson=lesson, kind=GradeItemKind.LESSON,
        title="Занятие", max_points=5,
    )

    url = reverse("cabinet:slot_clear", args=[lesson.pk])
    asked = admin_client.post(url)
    assert asked.status_code == 409
    assert asked.json()["needs_force"] is True
    assert Lesson.all_objects.filter(pk=lesson.pk).exists()

    confirmed = admin_client.post(url, {"force": "1"})
    assert confirmed.status_code == 200
    assert not Lesson.all_objects.filter(pk=lesson.pk).exists()


def test_week_can_be_repeated_forward(admin_client, tenant_a):
    monday = _monday_inside_module(tenant_a)
    admin_client.post(
        reverse("cabinet:slot_set"),
        {
            "group": str(tenant_a.group.pk), "teacher": str(tenant_a.teacher.pk),
            "subject": str(tenant_a.subject.pk), "day": monday.isoformat(), "time": "09:30",
        },
    )
    response = admin_client.post(
        reverse("cabinet:week_copy") + f"?week={monday.isoformat()}",
        {"group": str(tenant_a.group.pk), "weeks": "2"},
    )

    assert response.status_code == 200
    assert response.json()["created"] == 2
    assert Lesson.all_objects.filter(
        organization=tenant_a.organization, group=tenant_a.group
    ).count() >= 3


def test_scheduler_is_closed_for_teachers(client, tenant_a):
    """Расписание составляет администратор — педагог его только смотрит."""
    client.defaults["HTTP_HOST"] = tenant_a.host
    client.post(
        reverse("accounts:login"),
        {"username": tenant_a.teacher_user.email, "password": PASSWORD},
    )
    response = client.get(reverse("cabinet:schedule_builder"))

    assert response.status_code in (302, 403)


def test_scheduled_lesson_appears_in_teacher_cabinet(admin_client, client, tenant_a):
    """Поставили в конструкторе — педагог видит у себя, без отдельной публикации."""
    monday = _monday_inside_module(tenant_a)
    admin_client.post(
        reverse("cabinet:slot_set"),
        {
            "group": str(tenant_a.group.pk), "teacher": str(tenant_a.teacher.pk),
            "subject": str(tenant_a.subject.pk), "day": monday.isoformat(), "time": "09:30",
        },
    )

    client.defaults["HTTP_HOST"] = tenant_a.host
    client.post(
        reverse("accounts:login"),
        {"username": tenant_a.teacher_user.email, "password": PASSWORD},
    )
    today = dt.date.today()
    this_monday = today - dt.timedelta(days=today.weekday())
    week_offset = (monday - this_monday).days // 7
    body = client.get(reverse("cabinet:schedule"), {"n": week_offset}).content.decode()

    assert tenant_a.subject.name in body


def test_admin_journal_lists_lessons_of_the_day(admin_client, tenant_a):
    day = tenant_a.lesson.starts_at.astimezone(tenant_a.organization.tzinfo).date()
    body = admin_client.get(
        reverse("cabinet:journal"), {"day": day.isoformat()}
    ).content.decode()

    assert tenant_a.subject.name in body
    assert reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk]) in body


def test_cabinet_navigates_without_full_reloads(admin_client, tenant_a):
    """
    Переходы внутри кабинета меняют только содержимое.

    Шапка, тема и открытое меню остаются на месте — иначе каждый пункт
    меню выглядит как перезагрузка страницы.
    """
    body = admin_client.get(reverse("cabinet:dashboard")).content.decode()

    assert 'hx-boost="true"' in body
    assert 'hx-target="#main"' in body
    assert 'hx-select="#main"' in body
    assert 'id="main"' in body


def test_scheduler_script_is_loaded_for_the_whole_cabinet(admin_client, tenant_a):
    """
    Скрипт конструктора живёт вне подменяемой части.

    Если подключать его только на своей странице, при переходе без
    перезагрузки тег просто не приедет, и перетаскивание перестанет
    работать — молча.
    """
    body = admin_client.get(reverse("cabinet:dashboard")).content.decode()
    assert "js/scheduler.js" in body
