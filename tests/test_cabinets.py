"""
Чего не хватало в кабинетах.

Профиль со сменой пароля, свои часы у педагога, отметка об оплате —
вещи, которых просто не было ни на одном экране.
"""
from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

from tests.conftest import PASSWORD

NEW_PASSWORD = "Vesna10Krasnoyarsk"


@pytest.fixture
def logged_in(client, tenant_a):
    def _login(user):
        with override_settings(TWO_FACTOR_ENABLED=False):
            client.defaults["HTTP_HOST"] = tenant_a.host
            client.post(
                reverse("accounts:login"),
                {"username": user.email, "password": PASSWORD},
            )
        return client

    return _login


@pytest.mark.parametrize("who", ["owner_user", "teacher_user"])
def test_profile_shows_login_and_password_form(logged_in, tenant_a, who):
    """Логин человек забывает первым — он должен быть виден в кабинете."""
    body = logged_in(getattr(tenant_a, who)).get(reverse("accounts:profile")).content.decode()

    assert getattr(tenant_a, who).login in body
    assert "Смена пароля" in body
    assert "Текущий пароль" in body


def test_password_can_be_changed(logged_in, tenant_a):
    """
    Пароль раздаёт администратор — сменить чужую выдумку человек
    должен сам, не звоня в центр.
    """
    user = tenant_a.teacher_user
    client = logged_in(user)

    response = client.post(
        reverse("accounts:profile"),
        {
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "new_password_again": NEW_PASSWORD,
        },
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)


def test_password_change_keeps_you_logged_in(logged_in, tenant_a):
    """Смена пароля не должна выкидывать на страницу входа."""
    client = logged_in(tenant_a.teacher_user)
    client.post(
        reverse("accounts:profile"),
        {
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "new_password_again": NEW_PASSWORD,
        },
    )

    with override_settings(TWO_FACTOR_ENABLED=False):
        assert client.get(reverse("accounts:profile")).status_code == 200


def test_wrong_current_password_is_refused(logged_in, tenant_a):
    """Открытую сессию мог оставить кто угодно — старый пароль обязателен."""
    user = tenant_a.teacher_user
    response = logged_in(user).post(
        reverse("accounts:profile"),
        {
            "current_password": "не тот пароль",
            "new_password": NEW_PASSWORD,
            "new_password_again": NEW_PASSWORD,
        },
    )

    assert response.status_code == 200
    assert "не подошёл" in response.content.decode()
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_mismatched_new_passwords_are_refused(logged_in, tenant_a):
    response = logged_in(tenant_a.teacher_user).post(
        reverse("accounts:profile"),
        {
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "new_password_again": NEW_PASSWORD + "x",
        },
    )

    assert "не совпали" in response.content.decode()


def test_short_password_is_refused(logged_in, tenant_a):
    """Требования к паролю те же, что и везде в проекте."""
    user = tenant_a.teacher_user
    response = logged_in(user).post(
        reverse("accounts:profile"),
        {"current_password": PASSWORD, "new_password": "abc", "new_password_again": "abc"},
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_profile_is_closed_for_strangers(client, tenant_a):
    client.defaults["HTTP_HOST"] = tenant_a.host
    response = client.get(reverse("accounts:profile"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response["Location"]


def test_cabinet_header_links_to_the_profile(logged_in, tenant_a):
    """Без ссылки в шапке страницу не найдёт никто."""
    body = logged_in(tenant_a.owner_user).get(reverse("cabinet:home"), follow=True).content.decode()

    assert reverse("accounts:profile") in body


def test_profile_offers_two_factor_setup(logged_in, tenant_a):
    """Настройку второго фактора раньше нельзя было найти из кабинета."""
    body = logged_in(tenant_a.teacher_user).get(reverse("accounts:profile")).content.decode()

    assert reverse("accounts:two_factor_setup") in body


def test_teacher_sees_own_hours_and_pay(logged_in, tenant_a):
    """
    Свои часы педагог должен видеть сам.

    Раньше эти цифры были только в разделе ФОТ у владельца, и сойтись
    они могли лишь в день выплаты.
    """
    from decimal import Decimal

    teacher = tenant_a.teacher
    teacher.hourly_rate = Decimal("1000.00")
    teacher.save(update_fields=["hourly_rate", "updated_at"])

    response = logged_in(tenant_a.teacher_user).get(reverse("cabinet:teacher_hours"))

    assert response.status_code == 200
    assert "Академических часов" in response.content.decode()


def test_teacher_hours_are_only_your_own(logged_in, tenant_a):
    """Чужая ставка — не его дело: страница считает только свои занятия."""
    from decimal import Decimal

    from apps.accounts.models import Membership, Role, User
    from apps.journal.models import Lesson, Teacher

    other_user = User.objects.create_user(
        email="other-teacher@example.org", password=PASSWORD, last_name="Чужой"
    )
    Membership.objects.create(
        user=other_user, organization=tenant_a.organization, role=Role.TEACHER
    )
    other = Teacher.all_objects.create(
        organization=tenant_a.organization, user=other_user,
        hourly_rate=Decimal("9999.00"),
    )
    Lesson.all_objects.create(
        organization=tenant_a.organization, module=tenant_a.module,
        subject=tenant_a.subject, group=tenant_a.group, teacher=other,
        starts_at=tenant_a.lesson.starts_at, duration_minutes=40,
    )

    body = logged_in(tenant_a.teacher_user).get(
        reverse("cabinet:teacher_hours")
    ).content.decode()

    assert "9999" not in body


def test_teacher_menu_offers_hours(logged_in, tenant_a):
    body = logged_in(tenant_a.teacher_user).get(
        reverse("cabinet:teacher_today")
    ).content.decode()

    assert reverse("cabinet:teacher_hours") in body


def test_hours_are_closed_for_parents(logged_in, tenant_a):
    """Чужой ФОТ родителю не показываем."""
    response = logged_in(tenant_a.parent_user).get(reverse("cabinet:teacher_hours"))

    assert response.status_code in (302, 403)


def test_admin_can_mark_a_payment_paid(logged_in, tenant_a):
    """
    Начисление надо уметь закрыть.

    Кнопки не было вовсе: администратор мог выставить оплату, но не
    отметить её — у родителя она висела бы «предстоит» и после денег.
    """
    from datetime import date
    from decimal import Decimal

    from apps.journal.models import Payment

    payment = Payment.all_objects.create(
        organization=tenant_a.organization, student=tenant_a.student,
        title="Обучение, сентябрь", period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30), amount=Decimal("25000.00"),
    )
    client = logged_in(tenant_a.owner_user)

    card = client.get(
        reverse("cabinet:student_card", args=[tenant_a.student.pk])
    ).content.decode()
    assert reverse("cabinet:payment_mark_paid", args=[payment.pk]) in card

    response = client.post(reverse("cabinet:payment_mark_paid", args=[payment.pk]))

    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID


def test_owner_can_unbind_a_lost_authenticator(logged_in, tenant_a):
    """
    Телефон меняют и теряют.

    Раньше отвязать приложение можно было только командой на сервере, а
    до тех пор аккаунт оставался запертым.
    """
    from apps.accounts.models import TwoFactorDevice

    TwoFactorDevice.objects.create(
        user=tenant_a.teacher_user, secret="ABCDEFGHIJKLMNOP", is_confirmed=True
    )
    client = logged_in(tenant_a.owner_user)

    card = client.get(
        reverse("cabinet:staff_card", args=[tenant_a.teacher_user.pk])
    ).content.decode()
    assert reverse("cabinet:two_factor_reset", args=[tenant_a.teacher_user.pk]) in card

    response = client.post(
        reverse("cabinet:two_factor_reset", args=[tenant_a.teacher_user.pk])
    )

    assert response.status_code == 302
    assert not TwoFactorDevice.objects.filter(user=tenant_a.teacher_user).exists()


def test_unbinding_is_written_to_the_audit_log(logged_in, tenant_a):
    from apps.accounts.models import TwoFactorDevice
    from apps.core.models import AuditAction, AuditLog

    TwoFactorDevice.objects.create(
        user=tenant_a.teacher_user, secret="ABCDEFGHIJKLMNOP", is_confirmed=True
    )
    logged_in(tenant_a.owner_user).post(
        reverse("cabinet:two_factor_reset", args=[tenant_a.teacher_user.pk])
    )

    assert AuditLog.objects.filter(action=AuditAction.TWO_FACTOR_RESET).exists()


def test_unbinding_is_closed_for_teachers(logged_in, tenant_a):
    response = logged_in(tenant_a.teacher_user).post(
        reverse("cabinet:two_factor_reset", args=[tenant_a.owner_user.pk])
    )

    assert response.status_code in (302, 403)
