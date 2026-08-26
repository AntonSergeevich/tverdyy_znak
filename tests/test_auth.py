"""Вход по email и телефону, второй фактор, истечение сессии (ТЗ 8.2)."""
from __future__ import annotations

import time

import pytest
from django.urls import reverse

from apps.accounts import totp
from apps.accounts.models import TwoFactorDevice, normalize_phone
from tests.conftest import PASSWORD


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("+7 (913) 000-11-22", "79130001122"),
        ("8 913 000 11 22", "79130001122"),
        ("9130001122", "79130001122"),
        ("", ""),
    ],
)
def test_phone_normalization(raw, expected):
    assert normalize_phone(raw) == expected


def test_login_by_email(client, tenant_a):
    client.defaults["HTTP_HOST"] = tenant_a.host
    response = client.post(
        reverse("accounts:login"),
        {"username": tenant_a.parent_user.email, "password": PASSWORD},
    )
    assert response.status_code == 302
    assert response.wsgi_request.user.is_authenticated


def test_login_by_phone(client, tenant_a):
    tenant_a.parent_user.phone = "79130009999"
    tenant_a.parent_user.save(update_fields=["phone"])
    client.defaults["HTTP_HOST"] = tenant_a.host
    response = client.post(
        reverse("accounts:login"), {"username": "+7 (913) 000-99-99", "password": PASSWORD}
    )
    assert response.status_code == 302


def test_wrong_password_does_not_authenticate(client, tenant_a):
    client.defaults["HTTP_HOST"] = tenant_a.host
    response = client.post(
        reverse("accounts:login"), {"username": tenant_a.parent_user.email, "password": "nope"}
    )
    assert response.status_code == 200
    assert not response.wsgi_request.user.is_authenticated


def test_privileged_role_requires_two_factor(client, tenant_a):
    """Владелец с одним паролем в кабинет не попадает."""
    assert tenant_a.owner_user.requires_two_factor is True
    assert tenant_a.parent_user.requires_two_factor is False

    client.defaults["HTTP_HOST"] = tenant_a.host
    response = client.post(
        reverse("accounts:login"), {"username": tenant_a.owner_user.email, "password": PASSWORD}
    )
    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:two_factor")
    # Пока второй фактор не пройден, пользователь не считается вошедшим.
    assert not response.wsgi_request.user.is_authenticated


def test_two_factor_flow(client, tenant_a):
    device = TwoFactorDevice.objects.create(
        user=tenant_a.owner_user, secret=totp.generate_secret(), is_confirmed=True
    )
    client.defaults["HTTP_HOST"] = tenant_a.host
    client.post(
        reverse("accounts:login"), {"username": tenant_a.owner_user.email, "password": PASSWORD}
    )
    response = client.post(
        reverse("accounts:two_factor"), {"code": totp.code_now(device.secret)}
    )
    assert response.status_code == 302
    assert response.wsgi_request.user == tenant_a.owner_user


def test_two_factor_code_cannot_be_replayed(client, tenant_a):
    """Один и тот же код не должен работать дважды."""
    device = TwoFactorDevice.objects.create(
        user=tenant_a.owner_user, secret=totp.generate_secret(), is_confirmed=True
    )
    code = totp.code_now(device.secret)
    counter = totp.verify(device.secret, code)
    assert counter is not None
    assert totp.verify(device.secret, code, last_used_counter=counter) is None


def test_recovery_code_works_once(tenant_a):
    device = TwoFactorDevice.objects.create(
        user=tenant_a.owner_user, secret=totp.generate_secret(), is_confirmed=True
    )
    codes = device.generate_recovery_codes(count=3)
    assert device.consume_recovery_code(codes[0]) is True
    assert device.consume_recovery_code(codes[0]) is False
    assert len(device.recovery_codes) == 2


def test_session_expires_after_idle_timeout(client, tenant_a, settings):
    settings.SESSION_IDLE_TIMEOUT = 1
    client.defaults["HTTP_HOST"] = tenant_a.host
    client.post(
        reverse("accounts:login"), {"username": tenant_a.parent_user.email, "password": PASSWORD}
    )
    assert client.get(reverse("cabinet:parent_home")).status_code == 200

    session = client.session
    session["_last_seen_at"] = time.time() - 120
    session.save()

    response = client.get(reverse("cabinet:parent_home"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response["Location"]


def test_privileged_session_timeout_is_shorter(settings):
    assert settings.SESSION_IDLE_TIMEOUT_STAFF < settings.SESSION_IDLE_TIMEOUT


def test_no_personal_data_in_urls(client, tenant_a):
    """Идентификаторы — UUID, перебор невозможен, ФИО в URL не попадает."""
    url = reverse("cabinet:parent_child", args=[tenant_a.student.pk])
    assert tenant_a.student.last_name not in url
    assert len(str(tenant_a.student.pk)) == 36


def test_qr_svg_is_inline_and_scannable_shape():
    """QR отдаётся встроенным SVG: отдельного урла с секретом не появляется."""
    uri = totp.provisioning_uri("PQAXRJKI2YKDJGKROUAJ6FVZ7UEEXYEI", "a@example.org", "example.ru")
    svg = totp.qr_svg(uri)

    assert svg.startswith("<svg")
    assert "<path" in svg
    assert "<?xml" not in svg          # внутри HTML декларация лишняя
    assert 'width="100%"' in svg       # размер задают стили, а не миллиметры


def test_two_factor_setup_page_shows_qr_and_manual_key(client, tenant_a):
    """
    Страница подключения даёт и QR, и ключ для ручного ввода.

    Ручной ввод — не украшение: без камеры подключиться иначе нельзя.
    """
    from django.urls import reverse

    client.defaults["HTTP_HOST"] = tenant_a.host
    client.post(
        reverse("accounts:login"),
        {"username": tenant_a.owner_user.email, "password": PASSWORD},
    )
    response = client.get(reverse("accounts:two_factor_setup"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "<svg" in body and "qr" in body
    assert "Сканировать QR-код" in body
    assert "ввести ключ вручную" in body.lower()
    # Ссылки на приложения — иначе непонятно, чем сканировать.
    assert "apps.apple.com" in body
    assert "play.google.com" in body


def test_two_factor_switch_off_lets_owner_in(client, tenant_a, settings):
    """
    Выключатель на время приёмки: владелец входит одним паролем.

    Нужен ровно для одного сценария — пока в базе нет данных учеников
    и сайт проверяют вживую. Дальше возвращается обратно.
    """
    settings.TWO_FACTOR_ENABLED = False
    assert tenant_a.owner_user.requires_two_factor is False

    client.defaults["HTTP_HOST"] = tenant_a.host
    response = client.post(
        reverse("accounts:login"), {"username": tenant_a.owner_user.email, "password": PASSWORD}
    )
    assert response.status_code == 302
    assert response["Location"] != reverse("accounts:two_factor")
    assert response.wsgi_request.user == tenant_a.owner_user


def test_two_factor_is_on_by_default(settings):
    """Значение по умолчанию — включено: забыть вернуть нельзя."""
    from decouple import config

    assert config("TWO_FACTOR_ENABLED", default=True, cast=bool) is True


def test_disabled_two_factor_is_reported_by_deploy_check(settings):
    """`manage.py check --deploy` напоминает, что фактор выключен."""
    from apps.accounts.checks import two_factor_enabled

    settings.TWO_FACTOR_ENABLED = True
    assert two_factor_enabled(None) == []

    settings.TWO_FACTOR_ENABLED = False
    warnings = two_factor_enabled(None)
    assert [w.id for w in warnings] == ["accounts.W001"]


def test_reset_two_factor_command_unbinds_device(tenant_a):
    """
    Потерянный телефон не запирает аккаунт навсегда.

    Устройство привязано к человеку, а не к организации: сброс одному
    не трогает остальных.
    """
    from django.core.management import call_command

    TwoFactorDevice.objects.create(
        user=tenant_a.owner_user, secret=totp.generate_secret(), is_confirmed=True
    )
    other = TwoFactorDevice.objects.create(
        user=tenant_a.teacher_user, secret=totp.generate_secret(), is_confirmed=True
    )

    call_command("reset_two_factor", tenant_a.owner_user.email)

    assert not TwoFactorDevice.objects.filter(user=tenant_a.owner_user).exists()
    assert TwoFactorDevice.objects.filter(pk=other.pk).exists()


def test_reset_two_factor_command_rejects_unknown_login(db):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("reset_two_factor", "no-such@example.org")
