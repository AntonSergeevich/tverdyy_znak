"""
Раздел «Сотрудники» — один на всех, кто работает в центре.

Педагоги и администраторы жили в разных списках, хотя действие одно:
завести человека, выдать доступ, поправить данные. Главное, чего не
хватало: сделать педагога ещё и владельцем было попросту негде.
"""
from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import Membership, Role
from apps.journal.models import Teacher
from tests.conftest import PASSWORD


@pytest.fixture
def owner_client(client, tenant_a):
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.defaults["HTTP_HOST"] = tenant_a.host
        client.post(
            reverse("accounts:login"),
            {"username": tenant_a.owner_user.email, "password": PASSWORD},
        )
        yield client


def _card_payload(person, roles, **extra):
    """Карточка отправляется целиком — форма одна, полей в ней много."""
    payload = {
        "last_name": person.last_name,
        "first_name": person.first_name,
        "middle_name": person.middle_name,
        "phone": person.phone,
        "email": person.email,
        "roles": roles,
        "teacher-hourly_rate": "1000",
        "teacher-public_position": "100",
    }
    payload.update(extra)
    return payload


def test_teacher_can_be_made_an_owner(owner_client, tenant_a):
    """
    Ровно то, ради чего раздел объединялся.

    Наставник, который ведёт занятия и при этом руководит центром, — это
    один человек. Раньше сделать его владельцем было негде: в карточке
    педагога ролей не было, а в «Сотрудниках» его вовсе не было видно.
    """
    person = tenant_a.teacher_user

    response = owner_client.post(
        reverse("cabinet:staff_card", args=[person.pk]),
        _card_payload(person, ["owner", "teacher"]),
    )

    assert response.status_code == 302
    roles = set(
        Membership.objects.filter(
            organization=tenant_a.organization, user=person, is_active=True
        ).values_list("role", flat=True)
    )
    assert roles == {Role.OWNER, Role.TEACHER}
    # Карточка педагога на месте: на неё ссылаются занятия и баллы.
    assert Teacher.all_objects.filter(user=person).exists()


def test_removing_the_teacher_role_keeps_the_lessons(owner_client, tenant_a):
    """
    Роль сняли — карточка педагога осталась.

    На неё ссылаются занятия и выставленные баллы, и удалять её вместе с
    ролью значило бы стирать историю центра.
    """
    person = tenant_a.teacher_user
    Membership.objects.create(
        user=person, organization=tenant_a.organization, role=Role.ADMIN
    )

    owner_client.post(
        reverse("cabinet:staff_card", args=[person.pk]),
        _card_payload(person, ["admin"]),
    )

    assert not Membership.objects.filter(
        organization=tenant_a.organization, user=person,
        role=Role.TEACHER, is_active=True,
    ).exists()
    assert Teacher.all_objects.filter(user=person).exists()
    from apps.journal.models import Lesson

    assert Lesson.all_objects.filter(teacher__user=person).exists()


def test_the_last_owner_cannot_be_demoted(owner_client, tenant_a):
    """Организация без владельца — запертая дверь без ключа."""
    person = tenant_a.owner_user

    response = owner_client.post(
        reverse("cabinet:staff_card", args=[person.pk]),
        _card_payload(person, ["admin"]),
    )

    assert response.status_code == 200
    assert "последний владелец" in response.content.decode().lower()
    assert Membership.objects.filter(
        organization=tenant_a.organization, user=person, role=Role.OWNER, is_active=True
    ).exists()


def test_you_cannot_strip_your_own_rights(owner_client, tenant_a):
    """Снять права с самого себя — верный способ запереть за собой дверь."""
    from apps.journal.services import onboarding

    # Второй владелец, чтобы дело было не в «последнем».
    onboarding.issue_account(
        organization=tenant_a.organization, role=Role.OWNER,
        last_name="Второй", first_name="Владелец",
    )
    person = tenant_a.owner_user

    response = owner_client.post(
        reverse("cabinet:staff_card", args=[person.pk]),
        _card_payload(person, ["teacher"]),
    )

    assert response.status_code == 200
    assert "с самого себя" in response.content.decode()


def test_a_person_with_two_roles_is_listed_once(owner_client, tenant_a):
    """В списке человек один, даже если ролей у него две."""
    person = tenant_a.teacher_user
    Membership.objects.create(
        user=person, organization=tenant_a.organization, role=Role.ADMIN
    )

    body = owner_client.get(reverse("cabinet:staff")).content.decode()

    assert body.count(reverse("cabinet:staff_card", args=[person.pk])) == 2  # имя и «Изменить»
    assert "администратор" in body


def test_the_list_holds_teachers_and_owners_together(owner_client, tenant_a):
    body = owner_client.get(reverse("cabinet:staff")).content.decode()

    assert "Владельцы" in body
    assert "Педагоги" in body
    assert tenant_a.teacher_user.last_name in body
    assert tenant_a.owner_user.last_name in body


def test_access_button_turns_into_new_password(owner_client, tenant_a):
    """
    «Новый пароль» появляется только после того, как доступ выдан.

    У педагогов, перенесённых с сайта, учётной записи фактически нет —
    предлагать им новый пароль значило бы предлагать ключ от запертой двери.
    """
    person = tenant_a.teacher_user
    person.is_active = False
    person.save(update_fields=["is_active"])

    before = owner_client.get(reverse("cabinet:staff")).content.decode()
    assert "Выдать доступ" in before

    owner_client.post(reverse("cabinet:password_reset", args=[person.pk]))
    after = owner_client.get(reverse("cabinet:staff")).content.decode()

    assert "Новый пароль" in after


def test_admin_cannot_change_roles(client, tenant_a):
    """Роли меняет владелец — иначе администратор дорастает до владельца сам."""
    from apps.journal.services import onboarding

    _, credentials = onboarding.issue_account(
        organization=tenant_a.organization, role=Role.ADMIN,
        last_name="Админов", first_name="Пётр",
    )
    client.defaults["HTTP_HOST"] = tenant_a.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(
            reverse("accounts:login"),
            {"username": credentials.login, "password": credentials.password},
        )
        person = tenant_a.teacher_user
        body = client.get(
            reverse("cabinet:staff_card", args=[person.pk])
        ).content.decode()
        client.post(
            reverse("cabinet:staff_card", args=[person.pk]),
            _card_payload(person, ["owner"]),
        )

    assert "Роли меняет владелец" in body
    assert not Membership.objects.filter(
        organization=tenant_a.organization, user=person, role=Role.OWNER, is_active=True
    ).exists()


def test_admin_cannot_open_the_owners_card(client, tenant_a):
    """Иначе роль администратора — способ добраться до владельца."""
    from apps.journal.services import onboarding

    _, credentials = onboarding.issue_account(
        organization=tenant_a.organization, role=Role.ADMIN,
        last_name="Админов", first_name="Пётр",
    )
    client.defaults["HTTP_HOST"] = tenant_a.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(
            reverse("accounts:login"),
            {"username": credentials.login, "password": credentials.password},
        )
        response = client.get(
            reverse("cabinet:staff_card", args=[tenant_a.owner_user.pk])
        )

    assert response.status_code == 403


def test_teacher_details_are_edited_in_the_same_card(owner_client, tenant_a):
    """Ставка, предметы и текст для сайта — там же, где имя и роли."""
    person = tenant_a.teacher_user

    owner_client.post(
        reverse("cabinet:staff_card", args=[person.pk]),
        _card_payload(
            person, ["teacher"],
            **{
                "teacher-hourly_rate": "1500",
                "teacher-experience": "Стаж 12 лет",
                "teacher-subjects": [str(tenant_a.subject.pk)],
            },
        ),
    )

    teacher = Teacher.all_objects.get(user=person)
    assert teacher.hourly_rate == 1500
    assert teacher.experience == "Стаж 12 лет"


def test_creating_a_teacher_fills_the_card_at_once(owner_client, tenant_a):
    """Заводить человека дважды — в журнале и для сайта — больше не нужно."""
    owner_client.post(
        reverse("cabinet:staff_create"),
        {
            "last_name": "Крылова", "first_name": "Ольга", "middle_name": "",
            "phone": "", "email": "", "role": "teacher",
            "teacher-hourly_rate": "1300", "teacher-public_position": "100",
            "teacher-experience": "Стаж 8 лет",
            "teacher-subjects": [str(tenant_a.subject.pk)],
        },
    )

    teacher = Teacher.all_objects.get(user__last_name="Крылова")
    assert teacher.hourly_rate == 1300
    assert teacher.experience == "Стаж 8 лет"


def test_a_person_without_roles_is_refused(owner_client, tenant_a):
    """Без роли человек не попадёт никуда — это не «сохранить пустым»."""
    person = tenant_a.teacher_user

    response = owner_client.post(
        reverse("cabinet:staff_card", args=[person.pk]),
        _card_payload(person, []),
    )

    assert response.status_code == 200
    assert "Хотя бы одна роль" in response.content.decode()


def test_removing_a_staff_member_keeps_the_history(owner_client, tenant_a):
    person = tenant_a.teacher_user

    response = owner_client.post(
        reverse("cabinet:staff_remove", args=[person.pk]),
        {"confirm": person.last_name},
    )

    assert response.status_code == 302
    person.refresh_from_db()
    assert person.is_active is False
    from apps.journal.models import Lesson

    assert Lesson.all_objects.filter(teacher__user=person).exists()


def test_the_old_teachers_page_is_gone(owner_client, tenant_a):
    """Два меню с одной функцией — то, что и просили убрать."""
    from django.urls import NoReverseMatch

    body = owner_client.get(reverse("cabinet:dashboard")).content.decode()
    assert ">Педагоги<" not in body
    assert ">Сотрудники<" in body

    with pytest.raises(NoReverseMatch):
        reverse("cabinet:teachers")


def test_an_owner_card_saves_without_the_teacher_block(owner_client, tenant_a):
    """
    Ставка за час владельцу ни к чему.

    Педагогический блок стоит в той же форме, и если разбирать его всегда,
    правка обычной карточки упрётся в незаполненное поле, которого этот
    человек в глаза не видел.
    """
    from apps.journal.services import onboarding

    person, _ = onboarding.issue_account(
        organization=tenant_a.organization, role=Role.ADMIN,
        last_name="Новикова", first_name="Ольга",
    )

    response = owner_client.post(
        reverse("cabinet:staff_card", args=[person.pk]),
        {
            "last_name": "Новикова", "first_name": "Ольга", "middle_name": "",
            "phone": "", "email": "", "roles": ["admin"],
            # Педагогические поля пустые — человек не педагог.
            "teacher-hourly_rate": "", "teacher-public_position": "",
        },
    )

    assert response.status_code == 302
    person.refresh_from_db()
    assert person.first_name == "Ольга"
    assert not Teacher.all_objects.filter(user=person).exists()
