"""Справочник предметов и выдача доступа педагогу."""
from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.journal.models import Subject, SubjectKind
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


def test_admin_can_add_a_subject(admin_client, tenant_a):
    """
    Появится робототехника — её заводят в кабинете, а не ждут выката.
    """
    admin_client.post(
        reverse("cabinet:subject_create"),
        {"name": "Робототехника", "short_name": "Роб.", "kind": SubjectKind.ACADEMIC,
         "weekly_hours": "2", "position": "150"},
    )

    subject = Subject.all_objects.get(
        organization=tenant_a.organization, name="Робототехника"
    )
    assert subject.weekly_hours == 2
    assert subject.academic_year == tenant_a.year


def test_duplicate_subject_is_refused(admin_client, tenant_a):
    response = admin_client.post(
        reverse("cabinet:subject_create"),
        {"name": tenant_a.subject.name.lower(), "short_name": "", "kind": SubjectKind.ACADEMIC,
         "weekly_hours": "1", "position": "100"},
    )

    assert response.status_code == 200
    assert "уже есть" in response.content.decode()
    assert Subject.all_objects.filter(
        organization=tenant_a.organization, name__iexact=tenant_a.subject.name
    ).count() == 1


def test_unused_subject_can_be_deleted(admin_client, tenant_a):
    spare = Subject.all_objects.create(
        organization=tenant_a.organization, academic_year=tenant_a.year,
        name="Лишний предмет", weekly_hours=1,
    )
    admin_client.post(
        reverse("cabinet:subject_delete", args=[spare.pk]), {"confirm": "Лишний предмет"}
    )

    assert not Subject.all_objects.filter(pk=spare.pk).exists()


def test_subject_with_lessons_is_protected(admin_client, tenant_a):
    """
    Вместе с предметом ушла бы часть журнала.

    Занятия и баллы важнее удобства уборки справочника: такой предмет
    убирают из расписания, а запись о прошлом остаётся.
    """
    url = reverse("cabinet:subject_delete", args=[tenant_a.subject.pk])
    page = admin_client.get(url)
    assert "Удалить не получится" in page.content.decode()

    admin_client.post(url, {"confirm": tenant_a.subject.name})
    assert Subject.all_objects.filter(pk=tenant_a.subject.pk).exists()


def test_teacher_can_hold_a_day_block_subject(admin_client, tenant_a):
    """
    Профориентацию тоже кто-то ведёт.

    Раньше выбор предметов у педагога ограничивался учебными, и
    профориентолога нельзя было отметить ни за чем.
    """
    from apps.journal.forms import teachable_subjects
    from apps.core.tenancy import organization_context

    career = Subject.all_objects.create(
        organization=tenant_a.organization, academic_year=tenant_a.year,
        name="Профориентация", kind=SubjectKind.ACTIVITY, weekly_hours=0,
    )
    lunch = Subject.all_objects.create(
        organization=tenant_a.organization, academic_year=tenant_a.year,
        name="Обед", kind=SubjectKind.ACTIVITY, weekly_hours=0,
    )

    with organization_context(tenant_a.organization):
        options = list(teachable_subjects())

    assert career in options
    # За обедом человека нет — единственный блок, который в список не идёт.
    assert lunch not in options


def test_teacher_without_access_gets_it_from_the_card(admin_client, tenant_a):
    """
    Педагоги, перенесённые с сайта, заведены выключенными.

    Кнопка должна и выдать пароль, и включить запись — иначе получится
    пароль от запертой двери.
    """
    user = tenant_a.teacher.user
    user.is_active = False
    user.set_unusable_password()
    user.save()

    response = admin_client.post(
        reverse("cabinet:password_reset", args=[user.pk]), follow=True
    )
    user.refresh_from_db()

    assert response.status_code == 200
    assert user.is_active is True
    assert user.has_usable_password()


def test_staff_list_offers_access_button(admin_client, tenant_a):
    user = tenant_a.teacher.user
    user.is_active = False
    user.save(update_fields=["is_active"])

    body = admin_client.get(reverse("cabinet:staff")).content.decode()

    assert "Выдать доступ" in body
    assert reverse("cabinet:password_reset", args=[user.pk]) in body
