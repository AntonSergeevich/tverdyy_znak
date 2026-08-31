"""
Работа с занятием: провалиться в него, поставить баллы, задать домашнее.

Педагог заполняет журнал с телефона в руке, сразу после занятия. Всё, что
здесь проверяется, — про этот момент: попасть в занятие из расписания в
одно касание, поставить балл без клавиатуры, задать домашнее «как в
прошлый раз» и приложить снимок листа, если переписывать его долго.
"""
from __future__ import annotations

import datetime as dt
import io
import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import GradeItem, GradeItemKind, Homework, HomeworkMark, Lesson
from apps.journal.services.suggestions import (
    previous_homework,
    previous_lesson,
    recent_topics,
)
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


def a_photo(name: str = "list.png") -> SimpleUploadedFile:
    """Настоящий PNG: ImageField проверяет содержимое, а не расширение."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), (240, 200, 160)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


# ─── Из расписания — в занятие ──────────────────────────────────────────────

def test_teacher_opens_the_lesson_from_the_schedule(tenant_a):
    """
    Расписание было тупиком: занятия видно, а нажать не на что.

    Педагогу оттуда нужен ровно один переход — в журнал занятия.
    """
    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(reverse("cabinet:schedule")).content.decode()

    assert reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk]) in body


def test_the_student_has_nowhere_to_fall_through(tenant_a):
    """Журнал занятия не для ученика: ссылка, ведущая в отказ, хуже её отсутствия."""
    client = sign_in(tenant_a, tenant_a.student_user)
    body = client.get(reverse("cabinet:schedule")).content.decode()

    assert reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk]) not in body
    assert tenant_a.subject.name in body


def test_a_stranger_cannot_open_the_lesson_by_its_id(tenant_a, tenant_b):
    """Подстановка чужого id — первое, что пробуют."""
    client = sign_in(tenant_b, tenant_b.teacher_user)
    response = client.get(reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk]))

    assert response.status_code in (403, 404)


# ─── Баллы без клавиатуры ───────────────────────────────────────────────────

@pytest.fixture
def graded_lesson(tenant_a):
    with organization_context(tenant_a.organization):
        lesson = tenant_a.lesson
        lesson.is_graded = True
        lesson.save(update_fields=["is_graded"])
        GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group, lesson=lesson,
            kind=GradeItemKind.LESSON, title="Занятие", max_points=Decimal("10.00"),
        )
    lesson.refresh_from_db()
    return lesson


def test_points_are_set_by_the_dial_not_the_keyboard(tenant_a, graded_lesson):
    """
    Балл выбирают дугой во весь экран, а не набирают в поле.

    Клавиатура на телефоне закрывает пол-списка, поэтому в строке остаётся
    только крупная отметка, а шкала живёт в панели.
    """
    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(
        reverse("cabinet:lesson_journal", args=[graded_lesson.pk])
    ).content.decode()

    assert "grade-dial" in body
    assert "data-dial-open" in body
    # Максимум занятия уезжает в разметку машинным числом: с запятой
    # разбор в браузере сломается молча.
    assert 'data-max="10"' in body


def test_the_dial_writes_into_the_same_field_the_journal_sends(tenant_a, graded_lesson):
    """
    Панель ничего не отправляет сама — она вписывает балл в обычное поле.

    Иначе пришлось бы заводить второй путь сохранения, и очередь на случай
    обрыва сети знала бы только про один из них.
    """
    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(
        reverse("cabinet:lesson_journal", args=[graded_lesson.pk])
    ).content.decode()

    row = re.search(r'<div class="journal-row".*?</div>\s*</div>', body, re.S)
    assert row is not None
    assert 'name="points"' in row.group(0)
    assert reverse("cabinet:grade_save", args=[graded_lesson.pk]) in row.group(0)


def test_a_grade_carries_one_student_and_not_the_whole_list():
    """
    Список учеников не должен быть формой.

    htmx на любом запросе, кроме GET, прикладывает к нему всю ближайшую
    форму целиком. Пока строки лежали внутри <form>, отправка балла одному
    ученику увозила поля всех сразу, и сервер брал из них последнее — балл
    доставался не тому, кому его ставили.
    """
    import pathlib as _pathlib
    import re as _re

    template = (
        _pathlib.Path(__file__).resolve().parent.parent
        / "templates" / "cabinet" / "teacher" / "partials" / "journal_body.html"
    ).read_text(encoding="utf-8")

    opening = _re.search(r'<(\w+)[^>]*class="journal-list"', template)
    assert opening is not None
    assert opening.group(1) != "form"


def test_the_children_are_listed_even_without_grading(tenant_a):
    """
    Список детей виден всегда, а не только у занятий «с оцениванием».

    Оценивание включено у единиц занятий, и без списка экран выглядел так,
    будто учеников в системе нет вовсе.
    """
    client = sign_in(tenant_a, tenant_a.teacher_user)
    assert not tenant_a.lesson.is_graded

    body = client.get(
        reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk])
    ).content.decode()

    assert tenant_a.student.short_name in body
    assert "без оценивания" in body


def test_grading_is_switched_in_exactly_one_place(tenant_a):
    """
    Переключатель оценивания один на весь экран.

    Их было два — кнопка в шапке и такая же под списком, — и оба вдобавок
    назывались состоянием, а не действием: «Занятие с оцениванием»
    читается как подпись, а не как «сделать таким».
    """
    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(
        reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk])
    ).content.decode()

    assert body.count(reverse("cabinet:lesson_toggle_graded", args=[tenant_a.lesson.pk])) == 1
    assert "Сделать с оцениванием" in body


def test_an_empty_group_says_what_is_missing(tenant_a):
    """
    Пустая группа — это «состав ещё не заполнили», а не поломка.

    И к личным кабинетам это отношения не имеет: ученик попадает в список
    сразу, вход ему можно выдать позже.
    """
    from apps.journal.models import GroupMembership

    with organization_context(tenant_a.organization):
        GroupMembership.objects.filter(group=tenant_a.group).delete()

    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(
        reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk])
    ).content.decode()

    assert "Учеников в этой группе пока нет" in body
    assert tenant_a.group.name in body


def test_turning_grading_on_brings_the_circles_at_once(tenant_a):
    """
    Включили оценивание — круги для баллов должны появиться сразу.

    Меняются два места экрана одним запросом, и список приезжает отдельным
    куском: между ним и шапкой лежат тема и домашнее задание, где может
    быть недописанное.
    """
    client = sign_in(tenant_a, tenant_a.teacher_user)
    response = client.post(
        reverse("cabinet:lesson_toggle_graded", args=[tenant_a.lesson.pk]),
        {"is_graded": "1"},
    )
    body = response.content.decode()

    assert 'id="journal-body"' in body
    assert 'hx-swap-oob="true"' in body
    assert "data-dial-open" in body


def test_a_full_module_says_where_to_free_the_points(tenant_a):
    """
    Отказать можно только тогда, когда занять баллы действительно не у кого:
    сотня разобрана, а все занятия впереди либо без оценивания, либо уже
    с выставленными баллами. Тогда отказ говорит не только «нельзя», но и
    «вот где освободить».
    """
    from apps.journal.models import GradeItem, GradeItemKind

    with organization_context(tenant_a.organization):
        GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.CREDIT, title="Зачёт", max_points=Decimal("100.00"),
        )

    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.post(
        reverse("cabinet:lesson_toggle_graded", args=[tenant_a.lesson.pk]),
        {"is_graded": "1"},
    ).content.decode()

    assert "занять их не у кого" in body
    assert reverse(
        "cabinet:module_plan",
        args=[tenant_a.module.pk, tenant_a.subject.pk, tenant_a.group.pk],
    ) in body

    tenant_a.lesson.refresh_from_db()
    assert not tenant_a.lesson.is_graded


# ─── Подсказки «как в прошлый раз» ──────────────────────────────────────────

@pytest.fixture
def two_lessons(tenant_a):
    """Занятие неделю назад и занятие сегодня — по одному предмету и группе."""
    with organization_context(tenant_a.organization):
        earlier = Lesson.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group, teacher=tenant_a.teacher,
            starts_at=tenant_a.lesson.starts_at - dt.timedelta(days=7),
            topic="Признаки делимости",
        )
    return earlier, tenant_a.lesson


def test_the_previous_topic_is_offered(tenant_a, two_lessons):
    earlier, current = two_lessons
    with organization_context(tenant_a.organization):
        assert previous_lesson(current) == earlier
        assert "Признаки делимости" in recent_topics(
            subject=tenant_a.subject, group=tenant_a.group, exclude_lesson=current
        )


def test_the_previous_homework_is_offered(tenant_a, two_lessons):
    earlier, current = two_lessons
    with organization_context(tenant_a.organization):
        Homework.objects.create(
            organization=tenant_a.organization, lesson=earlier, text="§12, задачи 3–7"
        )
        assert previous_homework(current).text == "§12, задачи 3–7"

    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(reverse("cabinet:lesson_journal", args=[current.pk])).content.decode()
    assert "В прошлый раз" in body
    assert "§12, задачи 3–7" in body


def test_the_suggestion_does_not_reach_across_organizations(tenant_a, tenant_b):
    """Чужая тема не должна подсказываться — это чужой учебный план."""
    with organization_context(tenant_b.organization):
        tenant_b.lesson.topic = "Секретная тема Б"
        tenant_b.lesson.save(update_fields=["topic"])

    with organization_context(tenant_a.organization):
        assert "Секретная тема Б" not in recent_topics(
            subject=tenant_a.subject, group=tenant_a.group
        )


# ─── Фото листа с задачами ──────────────────────────────────────────────────

@pytest.fixture
def private_media(tmp_path, settings):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"
    return settings.PRIVATE_MEDIA_ROOT


def test_the_photo_is_saved_outside_the_public_media(tenant_a, private_media, settings):
    """
    Снимок страницы с задачами — не публичный файл.

    На нём бывает и фамилия, и почерк ребёнка, поэтому он лежит вне
    MEDIA_ROOT, и его не отдаёт веб-сервер напрямую.
    """
    client = sign_in(tenant_a, tenant_a.teacher_user)
    response = client.post(
        reverse("cabinet:lesson_homework_save", args=[tenant_a.lesson.pk]),
        {"text": "Лист с задачами", "photo": a_photo()},
    )
    assert response.status_code == 200

    with organization_context(tenant_a.organization):
        homework = Homework.objects.get(lesson=tenant_a.lesson)
    assert homework.photo
    saved = Path(private_media) / homework.photo.name
    assert saved.exists()
    assert str(settings.MEDIA_ROOT) not in str(saved)


def test_the_photo_opens_only_for_those_who_may_see_the_lesson(
    tenant_a, tenant_b, private_media
):
    client = sign_in(tenant_a, tenant_a.teacher_user)
    client.post(
        reverse("cabinet:lesson_homework_save", args=[tenant_a.lesson.pk]),
        {"text": "Лист с задачами", "photo": a_photo()},
    )
    url = reverse("cabinet:homework_photo", args=[tenant_a.lesson.pk])

    assert client.get(url).status_code == 200

    stranger = sign_in(tenant_b, tenant_b.teacher_user)
    assert stranger.get(url).status_code in (403, 404)


def test_the_child_and_the_parent_see_the_photo(tenant_a, private_media):
    """
    Снимок нужен прежде всего тем, кому задание задали.

    Проверка прав здесь общая — «доступно ли занятие», — а не список ролей:
    выставлять баллы, чтобы посмотреть своё же домашнее, не требуется.
    """
    teacher = sign_in(tenant_a, tenant_a.teacher_user)
    teacher.post(
        reverse("cabinet:lesson_homework_save", args=[tenant_a.lesson.pk]),
        {"text": "Лист с задачами", "photo": a_photo()},
    )
    url = reverse("cabinet:homework_photo", args=[tenant_a.lesson.pk])

    assert sign_in(tenant_a, tenant_a.student_user).get(url).status_code == 200
    assert sign_in(tenant_a, tenant_a.parent_user).get(url).status_code == 200


def test_removing_the_task_removes_its_photo(tenant_a, private_media):
    """Убрали задание — файл не должен остаться лежать в хранилище навсегда."""
    client = sign_in(tenant_a, tenant_a.teacher_user)
    client.post(
        reverse("cabinet:lesson_homework_save", args=[tenant_a.lesson.pk]),
        {"text": "Лист с задачами", "photo": a_photo()},
    )
    with organization_context(tenant_a.organization):
        saved = Path(private_media) / Homework.objects.get(lesson=tenant_a.lesson).photo.name
    assert saved.exists()

    client.post(reverse("cabinet:lesson_homework_save", args=[tenant_a.lesson.pk]), {"text": ""})

    with organization_context(tenant_a.organization):
        assert not Homework.objects.filter(lesson=tenant_a.lesson).exists()
    assert not saved.exists()


# ─── Отметка ученика «сделал» ───────────────────────────────────────────────

@pytest.fixture
def homework(tenant_a):
    with organization_context(tenant_a.organization):
        return Homework.objects.create(
            organization=tenant_a.organization, lesson=tenant_a.lesson, text="§12"
        )


def test_the_student_marks_the_task_done_and_can_change_their_mind(tenant_a, homework):
    """
    Отметку ставит и снимает сам ученик.

    Это не заявка на проверку: задание перестаёт висеть на виду, а педагог
    видит, сколько человек готовились. Передумать можно тем же касанием.
    """
    client = sign_in(tenant_a, tenant_a.student_user)
    url = reverse("cabinet:homework_mark", args=[homework.pk])

    client.post(url, {"done": "1"})
    with organization_context(tenant_a.organization):
        assert HomeworkMark.objects.filter(homework=homework, student=tenant_a.student).exists()

    client.post(url, {"done": "0"})
    with organization_context(tenant_a.organization):
        assert not HomeworkMark.objects.filter(homework=homework).exists()


def test_marking_twice_does_not_double_the_row(tenant_a, homework):
    client = sign_in(tenant_a, tenant_a.student_user)
    url = reverse("cabinet:homework_mark", args=[homework.pk])
    client.post(url, {"done": "1"})
    client.post(url, {"done": "1"})

    with organization_context(tenant_a.organization):
        assert HomeworkMark.objects.filter(homework=homework).count() == 1


def test_a_student_cannot_mark_someone_elses_task(tenant_a, tenant_b, homework):
    client = sign_in(tenant_b, tenant_b.student_user)
    response = client.post(
        reverse("cabinet:homework_mark", args=[homework.pk]), {"done": "1"}
    )

    assert response.status_code in (403, 404)
    with organization_context(tenant_a.organization):
        assert not HomeworkMark.objects.filter(homework=homework).exists()


def test_the_student_sees_the_button_and_the_teacher_sees_the_count(tenant_a, homework):
    student = sign_in(tenant_a, tenant_a.student_user)
    body = student.get(reverse("cabinet:student_home")).content.decode()
    assert "Сделал" in body

    student.post(reverse("cabinet:homework_mark", args=[homework.pk]), {"done": "1"})

    teacher = sign_in(tenant_a, tenant_a.teacher_user)
    body = teacher.get(
        reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk])
    ).content.decode()
    assert "Отметили «сделал»: 1" in body


# ─── Планирование модуля ────────────────────────────────────────────────────

def test_someone_elses_lesson_is_shown_but_not_editable(tenant_a):
    """
    В планировании видны все занятия предмета, в том числе чужие: иначе не
    понять, где в модуле дыра.

    Но поле для чужой темы показывать нельзя — набранное в нём молча не
    сохранилось бы, и понять почему было бы неоткуда.
    """
    from apps.accounts.models import Membership, Role, User
    from apps.journal.models import Teacher

    with organization_context(tenant_a.organization):
        other_user = User.objects.create_user(
            email="other-teacher@example.org", password=PASSWORD,
            last_name="Соседний", first_name="Педагог",
        )
        Membership.objects.create(
            user=other_user, organization=tenant_a.organization, role=Role.TEACHER
        )
        other = Teacher.objects.create(
            organization=tenant_a.organization, user=other_user, hourly_rate=Decimal("1000.00")
        )
        theirs = Lesson.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group, teacher=other,
            starts_at=tenant_a.lesson.starts_at + dt.timedelta(days=1),
            topic="Чужая тема",
        )

    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(
        reverse(
            "cabinet:module_plan",
            args=[tenant_a.module.pk, tenant_a.subject.pk, tenant_a.group.pk],
        )
    ).content.decode()

    assert "Чужая тема" in body
    assert reverse("cabinet:lesson_topic_save", args=[theirs.pk]) not in body
    assert reverse("cabinet:lesson_topic_save", args=[tenant_a.lesson.pk]) in body


# ─── Правка работ модуля ────────────────────────────────────────────────────

def test_a_work_of_the_module_can_be_edited_not_only_deleted(tenant_a):
    """
    Раньше строку можно было только удалить и завести заново — то есть
    потерять и название, и дату.
    """
    from apps.journal.models import GradeItem, GradeItemKind

    with organization_context(tenant_a.organization):
        item = GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.QUIZ, title="Проверочная", max_points=Decimal("10.00"),
        )

    client = sign_in(tenant_a, tenant_a.teacher_user)
    client.post(
        reverse(
            "cabinet:module_plan_action",
            args=[tenant_a.module.pk, tenant_a.subject.pk, tenant_a.group.pk],
        ),
        {
            "action": "edit_item", "item": str(item.pk),
            "title": "Проверочная по причастиям", "kind": GradeItemKind.QUIZ,
            "max_points": "12", "due_date": "2026-09-18",
        },
    )

    item.refresh_from_db()
    assert item.title == "Проверочная по причастиям"
    assert item.max_points == Decimal("12.00")
    assert str(item.due_date) == "2026-09-18"


def test_a_work_cannot_be_cut_below_a_grade_already_given(tenant_a):
    """
    Иначе балл ученика окажется выше максимума, и итог модуля станет
    враньём.
    """
    from apps.journal.models import GradeItem, GradeItemKind
    from apps.journal.services.grading import set_grade

    with organization_context(tenant_a.organization):
        item = GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.QUIZ, title="Проверочная", max_points=Decimal("10.00"),
        )
        set_grade(
            student=tenant_a.student, grade_item=item,
            points=Decimal("9"), actor=tenant_a.owner_user,
        )

    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.post(
        reverse(
            "cabinet:module_plan_action",
            args=[tenant_a.module.pk, tenant_a.subject.pk, tenant_a.group.pk],
        ),
        {
            "action": "edit_item", "item": str(item.pk), "title": "Проверочная",
            "kind": GradeItemKind.QUIZ, "max_points": "5",
        },
    ).content.decode()

    assert "уже стоит балл" in body
    item.refresh_from_db()
    assert item.max_points == Decimal("10.00")


def test_the_schedule_shows_which_lesson_carries_points(tenant_a):
    """
    Два урока подряд по одному предмету выглядели одинаково, и понять, за
    какой из них идёт балл, было неоткуда.

    Метка — точка, а не надпись: в узкой колонке дня «без баллов» занимало
    больше места, чем само занятие, и вылезало за край. Что значит цвет,
    сказано один раз сверху.
    """
    from apps.journal.services.grading import enable_lesson_grading

    with organization_context(tenant_a.organization):
        enable_lesson_grading(tenant_a.lesson)

    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(reverse("cabinet:schedule")).content.decode()

    assert "week__dot--graded" in body
    assert "week__legend" in body
    # Надписи у каждого занятия быть не должно — только точка и расшифровка.
    assert body.count("без оценивания") == 1
