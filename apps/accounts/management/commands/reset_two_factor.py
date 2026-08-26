"""
Сброс второго фактора одному человеку.

Нужен, когда телефон потерян или сменился: без этого привилегированный
аккаунт остаётся запертым навсегда. Выключать TWO_FACTOR_ENABLED целиком
ради одного человека нельзя — это снимает защиту со всех.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import TwoFactorDevice
from apps.core.audit import AuditAction, log_audit


class Command(BaseCommand):
    help = (
        "Отключить TOTP-устройство пользователя, чтобы он подключил новое "
        "при следующем входе. Аргумент — email или телефон."
    )

    def add_arguments(self, parser):
        parser.add_argument("login", help="email или телефон пользователя")

    def handle(self, *args, **options):
        User = get_user_model()
        login = options["login"].strip()
        user = (
            User.objects.filter(email__iexact=login).first()
            or User.objects.filter(phone=login).first()
        )
        if user is None:
            raise CommandError(f"Пользователь «{login}» не найден.")

        deleted, _ = TwoFactorDevice.objects.filter(user=user).delete()
        if not deleted:
            self.stdout.write(f"У {user} второго фактора и не было — подключит при входе.")
            return

        log_audit(action=AuditAction.TWO_FACTOR_RESET, obj=user, login=login)
        self.stdout.write(
            self.style.SUCCESS(
                f"Второй фактор у {user} сброшен. При следующем входе "
                "откроется страница подключения — пусть отсканирует новый QR."
            )
        )
