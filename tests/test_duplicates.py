"""
Один человек — одна запись.

Учётные записи заводятся из нескольких мест: педагога добавляют в разделе
сотрудников, он же приезжает в расписании из выгрузки, ему же потом выдают
доступ. Ничто из этого не проверяло, нет ли такого человека уже, — и на
публичной странице центра один и тот же педагог оказался дважды.
"""
from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import Membership, Role, User
from apps.core.tenancy import organization_context
from apps.journal.models import Lesson, Teacher
from apps.journal.services.duplicates import find_duplicate, merge_teachers
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


@pytest.fixture
def twin(tenant_a):
    """Второй педагог с тем же именем — тот самый двойник с сайта."""
    from decimal import Decimal

    with organization_context(tenant_a.organization):
        user = User.objects.create_user(
            email="twin@example.org", password=PASSWORD,
            last_name=tenant_a.teacher_user.last_name,
            first_name=tenant_a.teacher_user.first_name,
        )
        Membership.objects.create(
            user=user, organization=tenant_a.organization, role=Role.TEACHER
        )
        return Teacher.objects.create(
            organization=tenant_a.organization, user=user, hourly_rate=Decimal("1000.00")
        )


# ─── Узнать заранее ─────────────────────────────────────────────────────────

def test_the_same_name_is_recognised(tenant_a):
    with organization_context(tenant_a.organization):
        found = find_duplicate(
            organization=tenant_a.organization,
            last_name=tenant_a.teacher_user.last_name,
            first_name=tenant_a.teacher_user.first_name,
        )
    assert found == tenant_a.teacher_user


def test_the_same_email_is_recognised_even_under_another_name(tenant_a):
    """Почта — точнее фамилии: её не пишут по-разному."""
    with organization_context(tenant_a.organization):
        found = find_duplicate(
            organization=tenant_a.organization,
            last_name="Другая", first_name="Совсем",
            email=tenant_a.teacher_user.email.upper(),
        )
    assert found == tenant_a.teacher_user


def test_different_patronymics_are_different_people(tenant_a):
    """Иванов Иван Петрович и Иванов Иван Сергеевич — разные люди."""
    with organization_context(tenant_a.organization):
        tenant_a.teacher_user.middle_name = "Петрович"
        tenant_a.teacher_user.save(update_fields=["middle_name"])
        found = find_duplicate(
            organization=tenant_a.organization,
            last_name=tenant_a.teacher_user.last_name,
            first_name=tenant_a.teacher_user.first_name,
            middle_name="Сергеевич",
        )
    assert found is None


def test_a_namesake_in_another_organization_is_not_a_duplicate(tenant_a, tenant_b):
    with organization_context(tenant_a.organization):
        found = find_duplicate(
            organization=tenant_a.organization,
            last_name=tenant_b.teacher_user.last_name,
            first_name=tenant_b.teacher_user.first_name,
            email=tenant_b.teacher_user.email,
        )
    assert found is None


def test_the_form_stops_before_creating_a_second_one(tenant_a):
    """
    Молча завести второго — значит показать его на сайте дважды и
    разложить занятия по двум карточкам.
    """
    client = sign_in(tenant_a, tenant_a.owner_user)
    before = User.objects.count()

    body = client.post(
        reverse("cabinet:staff_create"),
        {
            "last_name": tenant_a.teacher_user.last_name,
            "first_name": tenant_a.teacher_user.first_name,
            "middle_name": "", "phone": "", "email": "",
            "role": Role.TEACHER,
            "teacher-hourly_rate": "1000", "teacher-public_position": "10",
        },
    ).content.decode()

    assert "уже есть" in body
    assert User.objects.count() == before


def test_a_namesake_can_still_be_added_on_purpose(tenant_a):
    """Однофамильцы бывают. Спрашиваем, но не запрещаем."""
    client = sign_in(tenant_a, tenant_a.owner_user)
    before = User.objects.count()

    client.post(
        reverse("cabinet:staff_create"),
        {
            "last_name": tenant_a.teacher_user.last_name,
            "first_name": tenant_a.teacher_user.first_name,
            "middle_name": "", "phone": "", "email": "",
            "role": Role.TEACHER, "teacher-hourly_rate": "1000", "teacher-public_position": "10",
            "confirm_twin": "1",
        },
    )

    assert User.objects.count() == before + 1


# ─── Свести уже заведённых ──────────────────────────────────────────────────

def test_merging_moves_the_lessons_and_removes_the_twin(tenant_a, twin):
    """
    Занятия переносим, а не удаляем: за ними стоят баллы детей, и терять
    их из-за чужой ошибки при заведении недопустимо.
    """
    with organization_context(tenant_a.organization):
        tenant_a.lesson.teacher = twin
        tenant_a.lesson.save(update_fields=["teacher"])
        twin.subjects.add(tenant_a.subject)

        moved = merge_teachers(keep=tenant_a.teacher, drop=twin)

        tenant_a.lesson.refresh_from_db()
        assert tenant_a.lesson.teacher == tenant_a.teacher
        assert moved["lessons"] == 1
        assert not Teacher.objects.filter(pk=twin.pk).exists()

    twin.user.refresh_from_db()
    assert not twin.user.is_active
    assert not twin.user.memberships.exists()


def test_a_card_cannot_be_merged_with_itself(tenant_a):
    with organization_context(tenant_a.organization):
        with pytest.raises(ValidationError):
            merge_teachers(keep=tenant_a.teacher, drop=tenant_a.teacher)


def test_cards_from_different_organizations_are_never_merged(tenant_a, tenant_b):
    with organization_context(tenant_a.organization):
        with pytest.raises(ValidationError):
            merge_teachers(keep=tenant_a.teacher, drop=tenant_b.teacher)


def test_only_the_owner_may_merge(tenant_a, twin):
    """Действие необратимое и задевает занятия — значит, не всякому."""
    client = sign_in(tenant_a, tenant_a.teacher_user)
    response = client.post(
        reverse("cabinet:staff_merge", args=[tenant_a.teacher_user.pk]),
        {"twin": str(twin.user.pk)},
    )

    assert response.status_code in (403, 404)
    with organization_context(tenant_a.organization):
        assert Teacher.objects.filter(pk=twin.pk).exists()


def test_the_card_offers_to_merge_when_a_twin_exists(tenant_a, twin):
    client = sign_in(tenant_a, tenant_a.owner_user)
    body = client.get(
        reverse("cabinet:staff_card", args=[tenant_a.teacher_user.pk])
    ).content.decode()

    assert "заведён дважды" in body
    assert reverse("cabinet:staff_merge", args=[tenant_a.teacher_user.pk]) in body
