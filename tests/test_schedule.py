"""Расписание в кабинете и загрузка недельной сетки (ТЗ 5.2, 5.3)."""
from __future__ import annotations

import datetime as dt

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone

from apps.journal.models import Lesson
from tests.conftest import PASSWORD


def _login(client, tenant, user):
    client.defaults["HTTP_HOST"] = tenant.host
    client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})


def test_schedule_page_shows_own_lessons(client, tenant_a):
    _login(client, tenant_a, tenant_a.student_user)
    response = client.get(reverse("cabinet:schedule"))

    assert response.status_code == 200
    body = response.content.decode()
    assert tenant_a.subject.name in body
    assert "Расписание" in body


def test_schedule_page_hides_other_tenant(client, tenant_a, tenant_b):
    """Ученик одной организации не видит занятий другой — даже на общей странице."""
    _login(client, tenant_a, tenant_a.student_user)
    body = client.get(reverse("cabinet:schedule")).content.decode()

    assert tenant_b.group.name not in body


def test_schedule_page_shows_empty_week_without_crashing(client, tenant_a):
    _login(client, tenant_a, tenant_a.student_user)
    response = client.get(reverse("cabinet:schedule"), {"n": "40"})

    assert response.status_code == 200
    assert "занятий пока нет" in response.content.decode()


def test_schedule_week_offset_is_bounded(client, tenant_a):
    """Мусор в параметре недели не должен ронять страницу."""
    _login(client, tenant_a, tenant_a.student_user)

    assert client.get(reverse("cabinet:schedule"), {"n": "нет"}).status_code == 200
    assert client.get(reverse("cabinet:schedule"), {"n": "99999"}).status_code == 200


def test_schedule_link_to_source_file_appears_when_set(client, tenant_a):
    tenant_a.organization.schedule_url = "https://docs.yandex.ru/view/d/example"
    tenant_a.organization.save(update_fields=["schedule_url"])

    _login(client, tenant_a, tenant_a.parent_user)
    body = client.get(reverse("cabinet:schedule"), {"n": "40"}).content.decode()

    assert "https://docs.yandex.ru/view/d/example" in body


def _write_grid(tmp_path, tenant, rows):
    path = tmp_path / "grid.csv"
    lines = ["day,time,subject,group,teacher,room,duration"] + rows
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def grid(tmp_path, tenant_a):
    return _write_grid(
        tmp_path, tenant_a,
        [f"пн,09:00,{tenant_a.subject.name},{tenant_a.group.name},,каб. 2,45"],
    )


def test_import_schedule_expands_week_over_module(grid, tenant_a):
    """Одна строка сетки — занятие на каждый понедельник модуля."""
    call_command("import_schedule", str(grid), "--organization", tenant_a.organization.slug,
                 "--module", tenant_a.module.number)

    lessons = Lesson.all_objects.filter(
        organization=tenant_a.organization, module=tenant_a.module, room="каб. 2"
    )
    assert lessons.count() > 1
    for lesson in lessons:
        local = lesson.starts_at.astimezone(tenant_a.organization.tzinfo)
        assert local.weekday() == 0
        assert (local.hour, local.minute) == (9, 0)
        assert tenant_a.module.starts_on <= local.date() <= tenant_a.module.ends_on


def test_import_schedule_keeps_local_time_of_the_centre(grid, tenant_a):
    """
    09:00 в сетке — это 09:00 в Красноярске, а не на сервере.

    Сервер живёт в UTC, и без явного часового пояса организации занятия
    уезжали бы на семь часов вперёд.
    """
    call_command("import_schedule", str(grid), "--organization", tenant_a.organization.slug,
                 "--module", tenant_a.module.number)

    lesson = Lesson.all_objects.filter(
        organization=tenant_a.organization, module=tenant_a.module, room="каб. 2"
    ).first()
    local = lesson.starts_at.astimezone(tenant_a.organization.tzinfo)
    assert (local.hour, local.minute) == (9, 0)


def test_import_schedule_is_idempotent(grid, tenant_a):
    args = (str(grid),)
    kwargs = {"organization": tenant_a.organization.slug, "module": tenant_a.module.number}
    call_command("import_schedule", *args, **kwargs)
    first = Lesson.all_objects.filter(organization=tenant_a.organization).count()
    call_command("import_schedule", *args, **kwargs)

    assert Lesson.all_objects.filter(organization=tenant_a.organization).count() == first


def test_import_schedule_dry_run_writes_nothing(grid, tenant_a):
    before = Lesson.all_objects.filter(organization=tenant_a.organization).count()
    call_command("import_schedule", str(grid), "--organization", tenant_a.organization.slug,
                 "--module", tenant_a.module.number, "--dry-run")

    assert Lesson.all_objects.filter(organization=tenant_a.organization).count() == before


def test_import_schedule_reports_missing_columns(tmp_path, tenant_a):
    path = tmp_path / "bad.csv"
    path.write_text("день,время\nпн,09:00", encoding="utf-8")

    with pytest.raises(CommandError, match="нет колонок"):
        call_command("import_schedule", str(path), "--organization", tenant_a.organization.slug)


def test_import_schedule_rejects_unknown_weekday(tmp_path, tenant_a):
    path = _write_grid(tmp_path, tenant_a,
                       [f"вторая,09:00,{tenant_a.subject.name},{tenant_a.group.name},,,45"])

    with pytest.raises(CommandError, match="день недели"):
        call_command("import_schedule", str(path), "--organization", tenant_a.organization.slug,
                     "--module", tenant_a.module.number)


def test_import_schedule_skips_unknown_subject_without_creating_it(tmp_path, tenant_a, capsys):
    """
    Опечатка в названии предмета не заводит новый предмет.

    Иначе в журнале рядом с «Алгеброй» появилась бы «алгебра ».
    """
    path = _write_grid(tmp_path, tenant_a,
                       [f"пн,09:00,Астрология,{tenant_a.group.name},,,45"])
    call_command("import_schedule", str(path), "--organization", tenant_a.organization.slug,
                 "--module", tenant_a.module.number)

    from apps.journal.models import Subject

    assert not Subject.all_objects.filter(name__iexact="Астрология").exists()
    assert "не найден" in capsys.readouterr().err


def test_example_grid_matches_expected_columns():
    """Образец в docs не должен разъехаться с тем, что читает команда."""
    from pathlib import Path

    from apps.journal.management.commands.import_schedule import (
        OPTIONAL_COLUMNS,
        REQUIRED_COLUMNS,
    )

    header = Path("docs/schedule.example.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == REQUIRED_COLUMNS + OPTIONAL_COLUMNS
