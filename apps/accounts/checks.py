"""Проверки конфигурации, которые должны мешать выкатить небезопасное."""
from __future__ import annotations

from django.conf import settings
from django.core.checks import Warning, register


@register(deploy=True)
def two_factor_enabled(app_configs, **kwargs):
    """
    Напоминание, если второй фактор выключен на проде.

    Выключать его допустимо только на время приёмки, пока в базе нет
    персональных данных учеников. Легко забыть вернуть — поэтому
    `manage.py check --deploy` про это говорит.
    """
    if settings.TWO_FACTOR_ENABLED:
        return []
    return [
        Warning(
            "Второй фактор выключен: TWO_FACTOR_ENABLED=False.",
            hint=(
                "Допустимо только на время приёмки. Как только в базе появятся "
                "ученики, верните TWO_FACTOR_ENABLED=True в .env и перезапустите web."
            ),
            id="accounts.W001",
        )
    ]
