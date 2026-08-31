"""Мелкие фильтры представления. Логики расчётов здесь нет — только вывод."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

LEVEL_CLASSES = {
    "failed": "level--failed",
    "base": "level--base",
    "elevated": "level--elevated",
    "advanced": "level--advanced",
}


@register.filter
def level_class(value: str) -> str:
    return LEVEL_CLASSES.get(value, "")


@register.filter
def points(value) -> str:
    """5.00 → «5», 4.50 → «4,5». Читается быстрее, чем хвост нулей."""
    if value in (None, ""):
        return "—"
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError):
        return str(value)
    if number == number.to_integral():
        return str(int(number))
    return f"{number.normalize():f}".replace(".", ",")


@register.filter
def machine_number(value) -> str:
    """
    Число для машины, а не для человека: «7.5», всегда с точкой.

    В атрибутах — max у поля, data-* для скриптов — запятая ломает разбор,
    а `floatformat` в русской локали даёт именно запятую.
    """
    if value in (None, ""):
        return ""
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError):
        return ""
    if number == number.to_integral():
        return str(int(number))
    return f"{number.normalize():f}"


@register.filter
def percent_of(value, total) -> int:
    try:
        value = Decimal(value or 0)
        total = Decimal(total or 0)
    except (InvalidOperation, TypeError):
        return 0
    if total <= 0:
        return 0
    return max(0, min(100, int(value / total * 100)))


@register.filter
def money(value) -> str:
    try:
        number = Decimal(value or 0)
    except (InvalidOperation, TypeError):
        return str(value)
    return f"{number:,.0f}".replace(",", " ")


@register.filter
def get_item(mapping, key):
    if hasattr(mapping, "get"):
        return mapping.get(key)
    return None
