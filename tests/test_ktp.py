"""
Загрузка календарно-тематического планирования.

КТП присылают файлом, и единого формата у него нет: колонки называются как
угодно, заголовок стоит то первой строкой, то пятой, сверху бывает шапка с
грифами. Поэтому проверяется не «разбирает правильный файл», а «справляется
с типичным чужим» и «даёт поправить, если не справился».
"""
from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import Lesson, ThematicPlan, ThematicPlanEntry
from apps.journal.services import ktp
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


def a_workbook(rows) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# Типичный присланный файл: две строки шапки, заголовок третьей, колонки
# названы по-своему, часть строк — названия разделов без темы занятия.
TYPICAL = [
    ["Календарно-тематическое планирование", "", "", "", ""],
    ["Математика, 9 класс, 2026/27", "", "", "", ""],
    ["№ п/п", "Дата проведения", "Тема урока", "Кол-во часов", "Домашнее задание"],
    ["1", dt.datetime(2026, 9, 3), "Признаки делимости", "1", "§1, № 4–8"],
    ["2", dt.datetime(2026, 9, 10), "Наибольший общий делитель", "1", "§2, № 11"],
    ["", "", "", "", ""],
    ["3", "17.09.2026", "Наименьшее общее кратное", "2", "§3"],
]


@pytest.fixture
def private_media(tmp_path, settings):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"
    return settings.PRIVATE_MEDIA_ROOT


# Как выглядит настоящее КТП, присланное центром: заголовок первой строкой,
# номеров занятий нет вовсе, даты не проставлены, а разделы отбиты строкой
# с темой, но без часов — «Причастие 21ч +2К + 2Р.р» это не занятие.
REAL_SHAPE = [
    ["Тема", "Количество часов", "Дата план", "Дата факт", "Примечания"],
    ["Повторение изученного в 5 и 6 классах 6ч +1К+ 2Р.р.", "", "", "", ""],
    ["Синтаксис, синтаксический разбор", 1.0, "", "", ""],
    ["Пунктуация. Пунктуационный разбор.", 1.0, "", "", ""],
    ["Причастие 21ч +2К + 2Р.р", "", "", "", ""],
    ["Причастие как часть речи.", 1.0, "", "", ""],
]


# ─── Разбор ─────────────────────────────────────────────────────────────────

def test_the_real_plan_from_the_centre_is_read_as_it_is():
    """Образец, по которому всё и настраивалось: русский язык, 7 класс."""
    parsed = ktp.parse(REAL_SHAPE)

    assert parsed.header_row == 0
    assert parsed.column_map["topic"] == 0
    assert parsed.column_map["hours"] == 1
    assert parsed.column_map["planned_date"] == 2
    assert parsed.column_map["notes"] == 4


def test_the_topic_column_is_not_also_the_number_column():
    """
    «Тема» — это тема, и заодно номером быть не может.

    Синоним «№» после очистки пунктуации превращался в пустую строку, а
    пустая строка входит в любую — и колонка с номером находилась где
    угодно, в том числе в теме.
    """
    parsed = ktp.parse(REAL_SHAPE)

    assert "number" not in parsed.column_map
    assert parsed.rows[1].number == ""


def test_the_fact_date_is_not_taken_for_the_planned_one():
    """«Дата факт» стоит рядом и по слову «дата» от «Даты план» неотличима."""
    parsed = ktp.parse(REAL_SHAPE)

    assert parsed.column_map["planned_date"] == 2


def test_a_section_heading_is_not_a_lesson():
    """
    «Причастие 21ч +2К + 2Р.р» — надпись над группой строк, а не занятие.

    Отличаем по часам: у занятия они есть, у заголовка раздела нет.
    """
    parsed = ktp.parse(REAL_SHAPE)
    sections = [row.topic for row in parsed.rows if row.is_section]
    lessons = [row.topic for row in parsed.rows if not row.is_section]

    assert sections == [
        "Повторение изученного в 5 и 6 классах 6ч +1К+ 2Р.р.",
        "Причастие 21ч +2К + 2Р.р",
    ]
    assert lessons == [
        "Синтаксис, синтаксический разбор",
        "Пунктуация. Пунктуационный разбор.",
        "Причастие как часть речи.",
    ]


def test_without_an_hours_column_nothing_becomes_a_section():
    """Иначе разделами оказался бы весь план целиком."""
    parsed = ktp.parse([["Тема"], ["Первая"], ["Вторая"]])

    assert not any(row.is_section for row in parsed.rows)


def test_sections_are_not_laid_out_over_lessons(tenant_a):
    """Раскладывать заголовок раздела по расписанию нечего."""
    with organization_context(tenant_a.organization):
        plan = ThematicPlan.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            subject=tenant_a.subject, group=tenant_a.group,
        )
        ktp.save_entries(plan, ktp.parse(REAL_SHAPE))
        tenant_a.lesson.topic = ""
        tenant_a.lesson.save(update_fields=["topic"])

        ktp.attach_to_lessons(plan)
        tenant_a.lesson.refresh_from_db()

    assert tenant_a.lesson.topic == "Синтаксис, синтаксический разбор"




def test_the_header_is_found_below_the_letterhead():
    """Сверху у КТП обычно шапка с грифами — заголовок не в первой строке."""
    parsed = ktp.parse(TYPICAL)

    assert parsed.header_row == 2
    assert parsed.column_map["topic"] == 2
    assert parsed.column_map["planned_date"] == 1
    assert parsed.column_map["homework"] == 4


def test_the_columns_are_read_by_their_meaning_not_their_place():
    """«Тема урока», «Содержание», «Раздел/тема» — одно и то же."""
    table = [
        ["Содержание", "Ч.", "№ занятия"],
        ["Векторы на плоскости", "2", "1"],
    ]
    parsed = ktp.parse(table)

    assert parsed.rows[0].topic == "Векторы на плоскости"
    assert parsed.rows[0].hours == Decimal("2")
    assert parsed.rows[0].number == "1"


def test_empty_rows_are_skipped_not_counted():
    """Пустая строка внутри таблицы — разделитель раздела, а не занятие."""
    parsed = ktp.parse(TYPICAL)

    assert len(parsed.rows) == 3
    assert [row.topic for row in parsed.rows][0] == "Признаки делимости"


def test_dates_come_in_both_shapes():
    """В одной и той же таблице дата бывает и датой, и строкой."""
    parsed = ktp.parse(TYPICAL)

    assert parsed.rows[0].planned_date == dt.date(2026, 9, 3)
    assert parsed.rows[2].planned_date == dt.date(2026, 9, 17)


def test_a_date_without_a_year_is_left_alone():
    """«12.09» без года — не дата: подставить год наугад хуже, чем не подставить."""
    assert ktp.parse_date("12.09") is None


def test_a_file_we_cannot_read_says_so_plainly():
    with pytest.raises(ValidationError):
        ktp.read_table(io.BytesIO(b"%PDF-1.4"), filename="plan.pdf")


def test_a_table_without_topics_does_not_pretend_to_have_parsed():
    parsed = ktp.parse([["Кабинет", "Оборудование"], ["12", "проектор"]])

    assert parsed.rows == []
    assert parsed.warnings


def test_the_mapping_can_be_corrected_by_hand():
    """
    Угадать чужую таблицу с первого раза нельзя.

    Поэтому разметку можно задать снаружи — и файл перечитается по ней.
    """
    table = [
        ["Первая", "Вторая"],
        ["не тема", "вот тема"],
    ]
    guessed = ktp.parse(table)
    assert not guessed.rows

    fixed = ktp.parse(table, header_row=0, column_map={"topic": 1})
    assert [row.topic for row in fixed.rows] == ["вот тема"]


def test_csv_is_read_too():
    payload = "№;Тема урока;Часов\n1;Пропорции;1\n".encode("utf-8")
    table = ktp.read_table(io.BytesIO(payload), filename="ktp.csv")

    assert ktp.parse(table).rows[0].topic == "Пропорции"


def test_excel_is_read_too():
    table = ktp.read_table(io.BytesIO(a_workbook(TYPICAL)), filename="ktp.xlsx")

    assert ktp.parse(table).rows[0].topic == "Признаки делимости"


# ─── Загрузка через кабинет ─────────────────────────────────────────────────

def test_the_uploaded_file_is_kept_whole(tenant_a, private_media):
    """
    Исходник хранится целиком и вне MEDIA_ROOT.

    Разбор можно повторять сколько угодно, а вот заново просить прислать
    файл — нельзя.
    """
    client = sign_in(tenant_a, tenant_a.owner_user)
    response = client.post(
        reverse("cabinet:ktp_upload"),
        {
            "subject": tenant_a.subject.pk,
            "title": "КТП, 9 класс",
            "source": SimpleUploadedFile(
                "ktp.xlsx", a_workbook(TYPICAL),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )
    assert response.status_code == 302

    with organization_context(tenant_a.organization):
        plan = ThematicPlan.objects.get()
        assert plan.source_name == "ktp.xlsx"
        assert plan.entries.count() == 3
        assert plan.column_map["topic"] == 2

    assert client.get(reverse("cabinet:ktp_source", args=[plan.pk])).status_code == 200


def test_rereading_replaces_the_rows_instead_of_adding_to_them(tenant_a, private_media):
    """Перечитывают, когда прошлый разбор оказался неверным. Дописать к неверному — хуже."""
    client = sign_in(tenant_a, tenant_a.owner_user)
    client.post(
        reverse("cabinet:ktp_upload"),
        {
            "subject": tenant_a.subject.pk,
            "source": SimpleUploadedFile("ktp.xlsx", a_workbook(TYPICAL)),
        },
    )
    with organization_context(tenant_a.organization):
        plan = ThematicPlan.objects.get()

    client.post(
        reverse("cabinet:ktp_remap", args=[plan.pk]),
        {"header_row": 2, "column_topic": 2, "column_planned_date": 1},
    )

    with organization_context(tenant_a.organization):
        assert ThematicPlanEntry.objects.filter(plan=plan).count() == 3


def test_a_stranger_cannot_reach_the_plan(tenant_a, tenant_b, private_media):
    client = sign_in(tenant_a, tenant_a.owner_user)
    client.post(
        reverse("cabinet:ktp_upload"),
        {"subject": tenant_a.subject.pk,
         "source": SimpleUploadedFile("ktp.xlsx", a_workbook(TYPICAL))},
    )
    with organization_context(tenant_a.organization):
        plan = ThematicPlan.objects.get()

    stranger = sign_in(tenant_b, tenant_b.owner_user)
    assert stranger.get(reverse("cabinet:ktp_detail", args=[plan.pk])).status_code == 404


# ─── Раскладка по расписанию ────────────────────────────────────────────────

@pytest.fixture
def plan_with_rows(tenant_a):
    with organization_context(tenant_a.organization):
        plan = ThematicPlan.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            subject=tenant_a.subject, group=tenant_a.group, title="КТП",
        )
        for position, topic in enumerate(["Первая тема", "Вторая тема", "Третья тема"], start=1):
            ThematicPlanEntry.objects.create(
                organization=tenant_a.organization, plan=plan, position=position, topic=topic
            )
    return plan


def test_topics_are_laid_out_over_the_lessons_in_order(tenant_a, plan_with_rows):
    with organization_context(tenant_a.organization):
        tenant_a.lesson.topic = ""
        tenant_a.lesson.save(update_fields=["topic"])
        second = Lesson.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group, teacher=tenant_a.teacher,
            starts_at=tenant_a.lesson.starts_at + dt.timedelta(days=7),
        )

        result = ktp.attach_to_lessons(plan_with_rows)

        tenant_a.lesson.refresh_from_db()
        second.refresh_from_db()

    assert tenant_a.lesson.topic == "Первая тема"
    assert second.topic == "Вторая тема"
    # Третьей строке занятия не нашлось — это не ошибка, а «ещё не поставили».
    assert result["unmatched"] == 1


def test_a_topic_written_by_hand_is_not_overwritten(tenant_a, plan_with_rows):
    """Тема, которую педагог дописал руками, точнее плановой."""
    with organization_context(tenant_a.organization):
        tenant_a.lesson.topic = "Своя тема"
        tenant_a.lesson.save(update_fields=["topic"])

        ktp.attach_to_lessons(plan_with_rows)
        tenant_a.lesson.refresh_from_db()
        assert tenant_a.lesson.topic == "Своя тема"

        ktp.attach_to_lessons(plan_with_rows, overwrite=True)
        tenant_a.lesson.refresh_from_db()
        assert tenant_a.lesson.topic == "Первая тема"


def test_a_planned_date_wins_over_the_order(tenant_a, plan_with_rows):
    """Дата в плане точнее порядка: по ней и раскладываем, если день однозначен."""
    with organization_context(tenant_a.organization):
        later = Lesson.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group, teacher=tenant_a.teacher,
            starts_at=tenant_a.lesson.starts_at + dt.timedelta(days=14),
        )
        entry = plan_with_rows.entries.order_by("position").last()
        entry.planned_date = later.local_date
        entry.save(update_fields=["planned_date"])

        ktp.attach_to_lessons(plan_with_rows)
        later.refresh_from_db()

    assert later.topic == "Третья тема"


def test_the_plan_does_not_reach_another_organizations_lessons(tenant_a, tenant_b, plan_with_rows):
    with organization_context(tenant_b.organization):
        before = tenant_b.lesson.topic

    with organization_context(tenant_a.organization):
        ktp.attach_to_lessons(plan_with_rows)

    with organization_context(tenant_b.organization):
        tenant_b.lesson.refresh_from_db()
        assert tenant_b.lesson.topic == before


# ─── Тема занятия и план ────────────────────────────────────────────────────

@pytest.fixture
def attached_plan(tenant_a):
    """План, разложенный по расписанию: у занятия есть своя строка КТП."""
    with organization_context(tenant_a.organization):
        tenant_a.lesson.topic = ""
        tenant_a.lesson.save(update_fields=["topic"])
        plan = ThematicPlan.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            subject=tenant_a.subject, group=tenant_a.group, title="КТП",
        )
        ThematicPlanEntry.objects.create(
            organization=tenant_a.organization, plan=plan, position=1,
            topic="Причастный оборот", lesson=tenant_a.lesson,
        )
    return plan


def test_the_topic_is_pulled_from_the_plan_into_the_lesson(tenant_a, attached_plan):
    """План для того и составляли, чтобы не сочинять тему заново."""
    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(
        reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk])
    ).content.decode()

    assert "Причастный оборот" in body
    assert "Тема из КТП" in body


def test_correcting_the_topic_corrects_the_plan(tenant_a, attached_plan):
    """
    Держать в плане одно, а в журнале другое значит завести два разных плана.

    Поэтому правка идёт и туда — от занятия к плану: занятие конкретнее,
    оно уже состоялось.
    """
    client = sign_in(tenant_a, tenant_a.teacher_user)
    response = client.post(
        reverse("cabinet:lesson_topic_save", args=[tenant_a.lesson.pk]),
        {"topic": "Причастный оборот и запятые", "view": "journal"},
    )

    assert response.json()["in_plan"] is True
    with organization_context(tenant_a.organization):
        assert attached_plan.entries.get().topic == "Причастный оборот и запятые"


def test_an_erased_topic_does_not_erase_the_plan(tenant_a, attached_plan):
    """Пустое поле — это чаще «ещё не заполнил», а не «убрать из плана»."""
    client = sign_in(tenant_a, tenant_a.teacher_user)
    client.post(
        reverse("cabinet:lesson_topic_save", args=[tenant_a.lesson.pk]),
        {"topic": "", "view": "journal"},
    )

    with organization_context(tenant_a.organization):
        assert attached_plan.entries.get().topic == "Причастный оборот"


def test_a_section_heading_is_never_the_lessons_topic(tenant_a):
    """Заголовок раздела к занятию не привязывается и темой стать не может."""
    with organization_context(tenant_a.organization):
        plan = ThematicPlan.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            subject=tenant_a.subject, group=tenant_a.group,
        )
        ThematicPlanEntry.objects.create(
            organization=tenant_a.organization, plan=plan, position=1,
            topic="Причастие 21ч", lesson=tenant_a.lesson, is_section=True,
        )
        assert ktp.entry_for(tenant_a.lesson) is None
