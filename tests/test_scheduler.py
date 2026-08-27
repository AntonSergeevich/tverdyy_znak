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


def test_dropping_onto_a_busy_slot_does_not_duplicate(admin_client, tenant_a):
    """
    Повторное перетаскивание в ту же клетку не плодит занятия.

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


def test_bulk_grading_fills_everyone_at_once(admin_client, tenant_a):
    """
    После занятия у большинства класса балл одинаковый.

    Вводить его по одному — двадцать кликов ради одного числа.
    """
    from decimal import Decimal

    from apps.journal.models import Grade, GradeItem, GradeItemKind

    item = GradeItem.all_objects.create(
        organization=tenant_a.organization, module=tenant_a.module,
        subject=tenant_a.subject, group=tenant_a.group, lesson=tenant_a.lesson,
        kind=GradeItemKind.LESSON, title="Занятие", max_points=Decimal("5.00"),
    )
    tenant_a.lesson.is_graded = True
    tenant_a.lesson.save(update_fields=["is_graded"])

    admin_client.post(
        reverse("cabinet:grade_bulk", args=[tenant_a.lesson.pk]), {"points": "4"}
    )

    grades = Grade.all_objects.filter(grade_item=item)
    assert grades.count() == 1
    assert grades.first().points == Decimal("4.00")


def test_bulk_grading_does_not_overwrite_existing_marks_by_default(admin_client, tenant_a):
    """
    Перезаписать уже выставленное молча — худшее, что может сделать
    «удобная» кнопка. Для этого есть отдельная галочка.
    """
    from decimal import Decimal

    from apps.journal.models import Grade, GradeItem, GradeItemKind

    item = GradeItem.all_objects.create(
        organization=tenant_a.organization, module=tenant_a.module,
        subject=tenant_a.subject, group=tenant_a.group, lesson=tenant_a.lesson,
        kind=GradeItemKind.LESSON, title="Занятие", max_points=Decimal("5.00"),
    )
    tenant_a.lesson.is_graded = True
    tenant_a.lesson.save(update_fields=["is_graded"])

    url = reverse("cabinet:grade_bulk", args=[tenant_a.lesson.pk])
    admin_client.post(url, {"points": "2"})
    admin_client.post(url, {"points": "5"})
    assert Grade.all_objects.get(grade_item=item).points == Decimal("2.00")

    admin_client.post(url, {"points": "5", "overwrite": "1"})
    assert Grade.all_objects.get(grade_item=item).points == Decimal("5.00")


def test_menu_marks_the_current_section(admin_client, tenant_a):
    """
    Подсветка пункта жила в шаблонах и при переходе без перезагрузки
    не переставлялась: шапка ведь не менялась.
    """
    students = admin_client.get(reverse("cabinet:students")).content.decode()
    marked = students[students.index('id="site-nav"'):students.index("</nav>")]
    assert 'aria-current="page"' in marked
    assert "Ученики</a>" in marked.split('aria-current="page"')[1][:40]


def test_menu_keeps_the_section_on_nested_pages(admin_client, tenant_a):
    """Карточка ученика — это всё ещё раздел «Ученики»."""
    body = admin_client.get(
        reverse("cabinet:student_card", args=[tenant_a.student.pk])
    ).content.decode()
    nav = body[body.index('id="site-nav"'):body.index("</nav>")]

    assert 'aria-current="page"' in nav
    assert "Ученики</a>" in nav.split('aria-current="page"')[1][:40]


def test_menu_depends_on_role(client, tenant_a):
    """Пункта, которого у роли нет, не должно быть даже ссылкой."""
    client.defaults["HTTP_HOST"] = tenant_a.host
    client.post(
        reverse("accounts:login"),
        {"username": tenant_a.parent_user.email, "password": PASSWORD},
    )
    body = client.get(reverse("cabinet:parent_home")).content.decode()
    nav = body[body.index('id="site-nav"'):body.index("</nav>")]

    assert "Мой ребёнок" in nav
    assert "Сотрудники" not in nav
    assert "ФОТ" not in nav


def test_logout_is_not_boosted(admin_client, tenant_a):
    """
    Выход уводит из кабинета, а boost подменил бы только содержимое
    и оставил шапку кабинета на публичной странице.
    """
    body = admin_client.get(reverse("cabinet:dashboard")).content.decode()
    logout = body[: body.index("/vyhod/")]

    # Атрибут стоит именно на форме выхода, а не где-то ещё на странице.
    assert logout.rstrip().endswith('<form method="post" action="')
    assert 'hx-boost="false"' in body[body.index("/vyhod/"):body.index("/vyhod/") + 200]


def _mentor(tenant):
    """
    Наставник без предметов.

    Утренний круг и рефлексию ведёт человек, за которым не закреплён
    «свой» предмет, — как Алина Алимовна в центре.
    """
    from apps.accounts.models import Membership, Role, User
    from apps.journal.models import Teacher

    user = User.objects.create_user(
        email="mentor@example.org", password=PASSWORD,
        first_name="Алина", last_name="Наставникова",
    )
    Membership.objects.create(
        user=user, organization=tenant.organization, role=Role.TEACHER
    )
    return Teacher.all_objects.create(organization=tenant.organization, user=user)


def _put_lesson(admin_client, tenant, monday, time):
    admin_client.post(
        reverse("cabinet:slot_set"),
        {
            "group": str(tenant.group.pk), "teacher": str(tenant.teacher.pk),
            "subject": str(tenant.subject.pk), "day": monday.isoformat(), "time": time,
        },
    )
    # Ищем по созданию, а не по времени: starts_at лежит в UTC, а сетка
    # рисуется в часовом поясе центра — сравнение по __time врало бы.
    return Lesson.all_objects.filter(
        organization=tenant.organization, group=tenant.group,
        starts_at__date__gte=monday,
    ).latest("created_at")


def test_mentor_without_subjects_takes_over_an_existing_lesson(admin_client, tenant_a):
    """
    Наставника ставят на уже назначенное занятие.

    У утреннего круга нет «своего» предмета, но есть тот, кто его ведёт.
    Раньше карточку такого педагога вообще некуда было перетащить.
    """
    monday = _monday_inside_module(tenant_a)
    lesson = _put_lesson(admin_client, tenant_a, monday, "09:30")
    mentor = _mentor(tenant_a)

    response = admin_client.post(
        reverse("cabinet:slot_set"),
        {
            "group": str(tenant_a.group.pk), "teacher": str(mentor.pk),
            "day": monday.isoformat(), "time": "09:30",
        },
    )

    lesson.refresh_from_db()
    assert response.status_code == 200
    assert lesson.teacher_id == mentor.pk
    # Предмет не тронут: перетаскивание назначало педагога, а не меняло урок.
    assert lesson.subject_id == tenant_a.subject.pk
    assert Lesson.all_objects.filter(
        organization=tenant_a.organization, group=tenant_a.group, starts_at__date=monday
    ).count() == 1


def test_mentor_on_an_empty_cell_is_told_what_to_do(admin_client, tenant_a):
    """Отказ должен объяснять, что делать, а не сообщать «нет предметов»."""
    monday = _monday_inside_module(tenant_a)
    mentor = _mentor(tenant_a)

    response = admin_client.post(
        reverse("cabinet:slot_set"),
        {
            "group": str(tenant_a.group.pk), "teacher": str(mentor.pk),
            "day": monday.isoformat(), "time": "15:00",
        },
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert "не заданы предметы" in error
    assert "карточку" in error


def test_assigning_a_teacher_keeps_the_grades(admin_client, tenant_a):
    """
    Смена педагога у занятия не должна стирать выставленные баллы.

    Раньше клетка пересоздавалась — вместе с занятием исчезала работа
    учеников за него.
    """
    from apps.journal.models import GradeItem, GradeItemKind

    monday = _monday_inside_module(tenant_a)
    lesson = _put_lesson(admin_client, tenant_a, monday, "12:00")
    item = GradeItem.all_objects.create(
        organization=tenant_a.organization, module=lesson.module,
        subject=lesson.subject, group=lesson.group, lesson=lesson,
        kind=GradeItemKind.LESSON, title="Занятие", max_points=5,
    )
    mentor = _mentor(tenant_a)

    admin_client.post(
        reverse("cabinet:slot_set"),
        {
            "group": str(tenant_a.group.pk), "teacher": str(mentor.pk),
            "day": monday.isoformat(), "time": "12:00",
        },
    )

    assert GradeItem.all_objects.filter(pk=item.pk).exists()


def test_assigning_a_busy_teacher_is_refused(admin_client, tenant_a):
    """Занятость проверяется и при назначении, не только при создании."""
    from apps.journal.models import Group

    monday = _monday_inside_module(tenant_a)
    other = Group.all_objects.create(
        organization=tenant_a.organization, academic_year=tenant_a.year,
        name="Класс 11", grade_level=11,
    )
    busy_at = _put_lesson(admin_client, tenant_a, monday, "10:20").starts_at
    mentor = _mentor(tenant_a)
    # Наставник занят в это же время у другой группы.
    Lesson.all_objects.create(
        organization=tenant_a.organization, module=tenant_a.module,
        subject=tenant_a.subject, group=other, teacher=mentor,
        starts_at=busy_at,
        duration_minutes=40,
    )

    response = admin_client.post(
        reverse("cabinet:slot_set"),
        {
            "group": str(tenant_a.group.pk), "teacher": str(mentor.pk),
            "day": monday.isoformat(), "time": "10:20",
        },
    )

    assert response.status_code == 409
    assert "уже ведёт" in response.json()["error"]


def test_week_can_be_cleared(admin_client, tenant_a):
    """Полная перестройка расписания не должна начинаться с сорока крестиков."""
    monday = _monday_inside_module(tenant_a)
    _put_lesson(admin_client, tenant_a, monday, "09:30")
    _put_lesson(admin_client, tenant_a, monday, "10:20")

    response = admin_client.post(
        reverse("cabinet:week_clear") + f"?week={monday.isoformat()}",
        {"group": str(tenant_a.group.pk)},
    )

    assert response.status_code == 200
    assert response.json()["removed"] == 2
    assert not Lesson.all_objects.filter(
        organization=tenant_a.organization, group=tenant_a.group,
        starts_at__date__gte=monday, starts_at__date__lte=monday + dt.timedelta(days=6),
    ).exists()


def test_clearing_a_week_with_grades_asks_first(admin_client, tenant_a):
    """Расписание переставить не жалко, работу учеников — жалко."""
    from apps.journal.models import GradeItem, GradeItemKind

    monday = _monday_inside_module(tenant_a)
    lesson = _put_lesson(admin_client, tenant_a, monday, "09:30")
    GradeItem.all_objects.create(
        organization=tenant_a.organization, module=lesson.module,
        subject=lesson.subject, group=lesson.group, lesson=lesson,
        kind=GradeItemKind.LESSON, title="Занятие", max_points=5,
    )
    url = reverse("cabinet:week_clear") + f"?week={monday.isoformat()}"

    asked = admin_client.post(url, {"group": str(tenant_a.group.pk)})
    assert asked.status_code == 409
    assert asked.json()["needs_force"] is True
    assert Lesson.all_objects.filter(pk=lesson.pk).exists()

    confirmed = admin_client.post(url, {"group": str(tenant_a.group.pk), "force": "1"})
    assert confirmed.status_code == 200
    assert not Lesson.all_objects.filter(pk=lesson.pk).exists()


def test_week_clear_is_closed_for_teachers(client, tenant_a):
    """Стереть неделю может только тот, кто её составляет."""
    client.defaults["HTTP_HOST"] = tenant_a.host
    client.post(
        reverse("accounts:login"),
        {"username": tenant_a.teacher_user.email, "password": PASSWORD},
    )
    response = client.post(
        reverse("cabinet:week_clear"), {"group": str(tenant_a.group.pk)}
    )

    assert response.status_code in (302, 403)
