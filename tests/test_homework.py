"""
Тема занятия и домашнее задание в журнале педагога.

Тему раньше можно было вписать только в планировании модуля — отдельным
экраном, куда ради одной строки никто не пойдёт. Домашнего задания в
привычном виде не было вовсе: на баллы его завести было можно, а
«прочитать параграф» — некуда.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.journal.models import GradeItem, GradeItemKind, Homework, Lesson
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    """
    Свежий клиент под конкретным человеком.

    Тот же клиент второй раз не войдёт: уже вошедшего страница входа
    просто перебрасывает дальше, и тест молча остаётся прежней ролью.
    """
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(
            reverse("accounts:login"),
            {"username": user.email, "password": PASSWORD},
        )
    return client


@pytest.fixture
def teacher_client(db, tenant_a):
    with override_settings(TWO_FACTOR_ENABLED=False):
        yield sign_in(tenant_a, tenant_a.teacher_user)


def _url(name, lesson):
    return reverse(name, args=[lesson.pk])


# ─── Тема ───────────────────────────────────────────────────────────────────

def test_the_topic_can_be_written_in_the_lesson_itself(teacher_client, tenant_a):
    """Ради одной строки уходить в планирование модуля никто не станет."""
    lesson = tenant_a.lesson
    body = teacher_client.get(_url("cabinet:lesson_journal", lesson)).content.decode()

    assert 'name="topic"' in body
    assert _url("cabinet:lesson_topic_save", lesson) in body


def test_the_topic_saves_without_a_button(teacher_client, tenant_a):
    """
    Тему дописывают между делом.

    Кнопка «сохранить» здесь только повод забыть на неё нажать, поэтому
    поле отправляется само, через паузу после последнего нажатия.
    """
    lesson = tenant_a.lesson
    body = teacher_client.get(_url("cabinet:lesson_journal", lesson)).content.decode()
    form = body.split('id="lesson-topic"')[1].split("</form>")[0]

    # Кнопки в форме нет — она есть только для тех, у кого не поднялись
    # скрипты, и лежит внутри noscript.
    assert form.count("<button") == form.count("<noscript>")

    response = teacher_client.post(
        _url("cabinet:lesson_topic_save", lesson),
        {"topic": "Квадратные уравнения", "view": "journal"},
    )

    lesson.refresh_from_db()
    assert response.status_code == 200
    assert lesson.topic == "Квадратные уравнения"
    assert response.json()["saved"] is True


def test_the_topic_still_saves_from_the_module_plan(teacher_client, tenant_a):
    """Старый путь никуда не делся — на него ссылается планирование."""
    lesson = tenant_a.lesson
    response = teacher_client.post(
        _url("cabinet:lesson_topic_save", lesson), {"topic": "Тема из плана"}
    )

    lesson.refresh_from_db()
    assert response.status_code == 200
    assert lesson.topic == "Тема из плана"
    assert "lesson-topic" not in response.content.decode()


# ─── Домашнее задание ───────────────────────────────────────────────────────

def test_homework_can_be_given_without_points(teacher_client, tenant_a):
    """
    «Прочитать параграф» — тоже домашнее задание.

    Раньше завести его было некуда: элемент оценивания требует баллов, а
    баллы за это никто не ставит.
    """
    lesson = tenant_a.lesson
    response = teacher_client.post(
        _url("cabinet:lesson_homework_save", lesson),
        {"text": "§12, задачи 3–7 письменно", "due_date": "", "max_points": ""},
    )

    homework = Homework.all_objects.get(lesson=lesson)
    assert response.status_code == 200
    assert homework.text == "§12, задачи 3–7 письменно"
    assert homework.grade_item is None
    assert homework.created_by_id == tenant_a.teacher_user.pk


def test_homework_keeps_a_due_date(teacher_client, tenant_a):
    lesson = tenant_a.lesson
    teacher_client.post(
        _url("cabinet:lesson_homework_save", lesson),
        {"text": "Эссе на страницу", "due_date": "2026-10-01", "max_points": ""},
    )

    assert Homework.all_objects.get(lesson=lesson).due_date == dt.date(2026, 10, 1)


def test_graded_homework_lands_in_the_module_points(teacher_client, tenant_a):
    """
    Баллы за домашнее живут там же, где все остальные.

    Иначе получилось бы два источника правды и сотня, которая не сходится.
    """
    lesson = tenant_a.lesson
    teacher_client.post(
        _url("cabinet:lesson_homework_save", lesson),
        {"text": "Контрольные задачи", "due_date": "", "max_points": "5"},
    )

    homework = Homework.all_objects.get(lesson=lesson)
    assert homework.grade_item is not None
    assert homework.grade_item.kind == GradeItemKind.HOMEWORK
    assert homework.grade_item.max_points == Decimal("5")
    assert homework.grade_item.title.startswith("Контрольные")


def test_points_beyond_the_hundred_are_refused(teacher_client, tenant_a):
    """
    Сотня на модуль не резиновая.

    Отказ показывает, сколько осталось, и оставляет введённое на экране —
    переписывать заново незачем.
    """
    lesson = tenant_a.lesson
    response = teacher_client.post(
        _url("cabinet:lesson_homework_save", lesson),
        {"text": "Всё сразу", "due_date": "", "max_points": "500"},
    )
    body = response.content.decode()

    assert "не помещается" in body.lower()
    assert "Всё сразу" in body
    assert not Homework.all_objects.filter(lesson=lesson).exists()


def test_dropping_the_points_drops_the_grade_item(teacher_client, tenant_a):
    """Передумали оценивать — оценивание уходит, задание остаётся."""
    lesson = tenant_a.lesson
    teacher_client.post(
        _url("cabinet:lesson_homework_save", lesson),
        {"text": "Задание", "due_date": "", "max_points": "4"},
    )
    item_id = Homework.all_objects.get(lesson=lesson).grade_item_id

    teacher_client.post(
        _url("cabinet:lesson_homework_save", lesson),
        {"text": "Задание", "due_date": "", "max_points": ""},
    )

    homework = Homework.all_objects.get(lesson=lesson)
    assert homework.grade_item is None
    assert not GradeItem.all_objects.filter(pk=item_id).exists()


def test_empty_text_removes_the_homework(teacher_client, tenant_a):
    """Убрать случайно заданное должно быть так же просто, как задать."""
    lesson = tenant_a.lesson
    teacher_client.post(
        _url("cabinet:lesson_homework_save", lesson),
        {"text": "Ошибся", "due_date": "", "max_points": "3"},
    )
    item_id = Homework.all_objects.get(lesson=lesson).grade_item_id

    response = teacher_client.post(
        _url("cabinet:lesson_homework_save", lesson),
        {"text": "   ", "due_date": "", "max_points": ""},
    )

    assert response.status_code == 200
    assert "убрано" in response.content.decode()
    assert not Homework.all_objects.filter(lesson=lesson).exists()
    assert not GradeItem.all_objects.filter(pk=item_id).exists()


def test_a_stranger_cannot_touch_someone_elses_lesson(db, tenant_a, tenant_b):
    """Занятие чужого центра — не его дело."""
    response = sign_in(tenant_a, tenant_a.teacher_user).post(
        _url("cabinet:lesson_homework_save", tenant_b.lesson), {"text": "Своё"}
    )

    assert response.status_code in (403, 404)
    assert not Homework.all_objects.filter(lesson=tenant_b.lesson).exists()


# ─── Кого это касается ──────────────────────────────────────────────────────

def _give_homework(teacher_client, tenant, text="Читать главу 4"):
    teacher_client.post(
        _url("cabinet:lesson_homework_save", tenant.lesson),
        {"text": text, "due_date": "", "max_points": ""},
    )


def test_the_student_sees_what_was_set(teacher_client, tenant_a):
    _give_homework(teacher_client, tenant_a)

    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert "Читать главу 4" in body


def test_the_parent_sees_it_too(teacher_client, tenant_a):
    """Родитель спрашивает «что задано» чаще, чем «сколько баллов»."""
    _give_homework(teacher_client, tenant_a)

    body = sign_in(tenant_a, tenant_a.parent_user).get(
        reverse("cabinet:parent_home")
    ).content.decode()

    assert "Что задано" in body
    assert "Читать главу 4" in body


def test_homework_does_not_leak_between_centres(teacher_client, tenant_a, tenant_b):
    _give_homework(teacher_client, tenant_a, "Только для А")

    body = sign_in(tenant_b, tenant_b.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert "Только для А" not in body


def test_an_overdue_task_stays_visible(teacher_client, tenant_a):
    """
    Убирать задолженность с глаз значит делать вид, что её нет.

    Просроченное задание остаётся на экране и помечается.
    """
    from django.utils import timezone

    yesterday = timezone.localdate() - dt.timedelta(days=1)
    teacher_client.post(
        _url("cabinet:lesson_homework_save", tenant_a.lesson),
        {"text": "Просроченное", "due_date": yesterday.isoformat(), "max_points": ""},
    )

    body = sign_in(tenant_a, tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert "Просроченное" in body
    assert "homework-card--late" in body


# ─── Как это устроено на экране ─────────────────────────────────────────────
#
# Оба поля один раз уже сломались на одном и том же: кабинет перехватывает
# отправку любых форм и подменяет ими середину страницы. Форму, которая
# обновляет свой кусочек, он перехватывал раньше нашего кода — и вместо
# обновления страница уезжала на адрес сохранения.

import pathlib

TOPIC = pathlib.Path(
    "templates/cabinet/teacher/partials/lesson_topic.html"
).read_text(encoding="utf-8")
HOMEWORK = pathlib.Path(
    "templates/cabinet/teacher/partials/lesson_homework_form.html"
).read_text(encoding="utf-8")
LESSON_JS = pathlib.Path("static/js/lesson_meta.js").read_text(encoding="utf-8")


def test_both_forms_opt_out_of_boosting():
    """Иначе кабинет перехватит отправку раньше и уведёт страницу."""
    assert 'hx-boost="false"' in TOPIC
    assert 'hx-boost="false"' in HOMEWORK


def test_both_forms_work_without_scripts():
    """
    Без скриптов формы остаются формами.

    Это не про изящество: связь в центре не идеальна, и потерять
    записанную тему из-за неподнявшегося скрипта нельзя.
    """
    for markup in (TOPIC, HOMEWORK):
        assert 'method="post"' in markup
        assert "action=" in markup
    assert "<noscript>" in TOPIC


def test_the_topic_field_is_not_replaced_while_typing():
    """
    Подменить поле во время набора значит оборвать его на полуслове:
    теряется курсор, а на телефоне закрывается клавиатура.
    """
    assert "data-state" in TOPIC
    # Сохранение меняет только отметку, самого поля не касается.
    assert "innerHTML" not in TOPIC
    assert "JsonResponse" in pathlib.Path(
        "apps/journal/views/teacher.py"
    ).read_text(encoding="utf-8")


def test_typing_pause_before_saving():
    """Сохраняем не на каждую букву, а когда клавиатура замолчала."""
    assert "TYPING_PAUSE" in LESSON_JS
    assert "setTimeout" in LESSON_JS


def test_the_homework_listener_survives_the_swap():
    """
    После сохранения форма приезжает новая.

    Слушатель на старой уехал бы вместе с ней, и второе сохранение подряд
    уже не сработало бы — поэтому слушаем обёртку.
    """
    assert "data-homework]" in LESSON_JS
    handler = LESSON_JS.split("function initHomework()")[1]
    assert "holder.addEventListener('submit'" in handler
