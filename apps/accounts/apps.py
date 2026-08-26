from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    verbose_name = "Пользователи и роли"

    def ready(self):
        from apps.accounts import checks  # noqa: F401  — регистрирует проверки
