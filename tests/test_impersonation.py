"""
Просмотр кабинета от чужого лица.

За этими экранами персональные данные детей, поэтому тестов здесь больше
про то, чего делать нельзя, чем про то, что можно.
"""
from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.impersonation import SESSION_KEY
from apps.accounts.models import Membership, Role
from tests.conftest import PASSWORD


@pytest.fixture
def platform_admin(tenant_a):
    """Тот, кто сопровождает платформу, — не владелец центра."""
    from apps.accounts.models import User

    user = User.objects.create_user(
        email="dev@example.org", password=PASSWORD,
        last_name="Разработчик", first_name="Антон",
    )
    Membership.objects.create(
        user=user, organization=tenant_a.organization, role=Role.PLATFORM_ADMIN
    )
    return user


@pytest.fixture
def sign_in(client, tenant_a):
    def _login(user):
        with override_settings(TWO_FACTOR_ENABLED=False):
            client.defaults["HTTP_HOST"] = tenant_a.host
            client.post(
                reverse("accounts:login"),
                {"username": user.email, "password": PASSWORD},
            )
        return client

    return _login


def _start(client, user):
    return client.post(reverse("accounts:impersonate_start", args=[user.pk]))


def test_platform_admin_sees_the_student_cabinet(sign_in, tenant_a, platform_admin):
    """Ради этого всё и затевалось: посмотреть, что видит ученик."""
    client = sign_in(platform_admin)

    started = _start(client, tenant_a.student_user)
    assert started.status_code == 302

    body = client.get(reverse("cabinet:student_home")).content.decode()
    assert tenant_a.student.first_name in body
    # Полоса наверху — на каждом экране, забыть о просмотре нельзя.
    assert "Вы смотрите кабинет" in body


def test_owner_cannot_impersonate(sign_in, tenant_a):
    """
    Владелец центра — не сопровождение платформы.

    Читать кабинет ребёнка от его имени ей незачем, и права такого нет.
    """
    client = sign_in(tenant_a.owner_user)

    response = _start(client, tenant_a.student_user)

    assert response.status_code == 403
    assert SESSION_KEY not in client.session


def test_teacher_cannot_impersonate(sign_in, tenant_a):
    response = _start(sign_in(tenant_a.teacher_user), tenant_a.student_user)

    assert response.status_code in (302, 403)


def test_privileged_accounts_cannot_be_impersonated(sign_in, tenant_a, platform_admin):
    """
    Иначе просмотр от лица владельца — это способ им стать.
    """
    response = _start(sign_in(platform_admin), tenant_a.owner_user)

    assert response.status_code == 403


def test_impersonation_is_read_only(sign_in, tenant_a, platform_admin):
    """
    Проверка — это чтение.

    Выставить балл, отправить форму, что-то удалить от чужого имени
    нельзя: в журнале осталась бы работа, которой человек не делал.
    """
    client = sign_in(platform_admin)
    _start(client, tenant_a.student_user)

    response = client.post(
        reverse("cabinet:goal_create"), {"title": "Цель", "visibility": "open"}
    )

    assert response.status_code == 403
    from apps.journal.models import Goal

    assert not Goal.all_objects.filter(title="Цель").exists()


def test_hidden_goals_stay_hidden(sign_in, tenant_a, platform_admin):
    """
    Ребёнку в интерфейсе обещано, что скрытые цели не видит никто.

    «Проверка» — не повод нарушить обещание: у смотрящего чужими глазами
    их не видно, хотя сам ученик их видит.
    """
    from apps.journal.models import Goal, GoalVisibility

    Goal.all_objects.create(
        organization=tenant_a.organization, student=tenant_a.student,
        title="Личное, никому", visibility=GoalVisibility.HIDDEN,
        created_by=tenant_a.student_user,
    )
    Goal.all_objects.create(
        organization=tenant_a.organization, student=tenant_a.student,
        title="Открытая цель", visibility=GoalVisibility.OPEN,
        created_by=tenant_a.student_user,
    )

    client = sign_in(platform_admin)
    _start(client, tenant_a.student_user)
    body = client.get(reverse("cabinet:student_home")).content.decode()

    assert "Открытая цель" in body
    assert "Личное, никому" not in body


def test_student_still_sees_own_hidden_goals(sign_in, tenant_a):
    from apps.journal.models import Goal, GoalVisibility

    Goal.all_objects.create(
        organization=tenant_a.organization, student=tenant_a.student,
        title="Личное, никому", visibility=GoalVisibility.HIDDEN,
        created_by=tenant_a.student_user,
    )
    body = sign_in(tenant_a.student_user).get(
        reverse("cabinet:student_home")
    ).content.decode()

    assert "Личное, никому" in body


def test_returning_to_yourself_works(sign_in, tenant_a, platform_admin):
    client = sign_in(platform_admin)
    _start(client, tenant_a.student_user)

    response = client.post(reverse("accounts:impersonate_stop"))

    assert response.status_code == 302
    assert SESSION_KEY not in client.session
    body = client.get(reverse("cabinet:dashboard")).content.decode()
    assert "Вы смотрите кабинет" not in body


def test_both_ends_are_written_to_the_audit_log(sign_in, tenant_a, platform_admin):
    """Кто и в чей кабинет заходил — должно остаться в журнале действий."""
    from apps.core.models import AuditLog

    client = sign_in(platform_admin)
    _start(client, tenant_a.student_user)
    client.post(reverse("accounts:impersonate_stop"))

    changes = [
        row.extra.get("change")
        for row in AuditLog.objects.filter(actor=platform_admin)
    ]
    assert "impersonation_started" in changes
    assert "impersonation_stopped" in changes


def test_audit_records_the_real_person_not_the_mask(sign_in, tenant_a, platform_admin):
    """
    Записи о просмотре пишутся на того, кто смотрит.

    Ради этого просмотр и нужен вместо «зайти чужим паролем»: иначе в
    журнале осталось бы, что заходил сам ученик.
    """
    from apps.core.models import AuditLog

    client = sign_in(platform_admin)
    _start(client, tenant_a.student_user)

    entry = AuditLog.objects.filter(extra__change="impersonation_started").first()
    assert entry is not None
    assert entry.actor_id == platform_admin.pk


def test_the_picker_lists_people_but_not_privileged_ones(sign_in, tenant_a, platform_admin):
    body = sign_in(platform_admin).get(
        reverse("accounts:impersonate_list")
    ).content.decode()

    assert tenant_a.student_user.login in body
    assert tenant_a.parent_user.login in body
    assert tenant_a.owner_user.login not in body


def test_menu_offers_the_picker_only_to_platform_admins(sign_in, tenant_a, platform_admin):
    admin_body = sign_in(platform_admin).get(
        reverse("cabinet:dashboard")
    ).content.decode()
    assert reverse("accounts:impersonate_list") in admin_body


def test_owner_menu_has_no_picker(sign_in, tenant_a):
    body = sign_in(tenant_a.owner_user).get(reverse("cabinet:dashboard")).content.decode()

    assert reverse("accounts:impersonate_list") not in body


def test_you_can_switch_straight_to_another_cabinet(sign_in, tenant_a, platform_admin):
    """
    Полоса наверху ведёт к списку — значит, список должен открываться.

    Пока просмотр включён, request.user — это тот, чьими глазами смотрят,
    и проверять право по нему нельзя: маска сама себе прав не даёт.
    """
    client = sign_in(platform_admin)
    _start(client, tenant_a.student_user)

    assert client.get(reverse("accounts:impersonate_list")).status_code == 200

    switched = _start(client, tenant_a.parent_user)
    assert switched.status_code == 302
    assert client.session[SESSION_KEY] == str(tenant_a.parent_user.pk)


def test_a_person_from_another_centre_cannot_be_viewed(sign_in, tenant_a, tenant_b,
                                                       platform_admin):
    """
    Членство в этой организации обязательно.

    Иначе подделанный номер в сессии открыл бы кабинет ребёнка из чужого
    центра — мимо всей арендной изоляции.
    """
    client = sign_in(platform_admin)
    session = client.session
    session[SESSION_KEY] = str(tenant_b.student_user.pk)
    session.save()

    body = client.get(reverse("cabinet:dashboard")).content.decode()

    assert "Вы смотрите кабинет" not in body
    assert SESSION_KEY not in client.session
