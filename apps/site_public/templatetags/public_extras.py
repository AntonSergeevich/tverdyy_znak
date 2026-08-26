"""
Фильтры для публичных страниц.

Встроенный `pluralize` знает только две формы и на трёх молча возвращает
пустую строку — получалось «33 урок» и «9 педагог». Своё склонение
короче, чем каждый раз переписывать фразу так, чтобы обойтись без него.
"""
from __future__ import annotations

from django import template

register = template.Library()


@register.filter
def plural(value, forms: str) -> str:
    """
    Русское склонение: {{ n|plural:"урок,урока,уроков" }}.

    Формы в порядке «1, 2, 5». Правило обычное: 11–14 всегда последняя
    форма, дальше решает последняя цифра.
    """
    try:
        number = abs(int(value))
    except (TypeError, ValueError):
        return ""

    parts = [part.strip() for part in str(forms).split(",")]
    if len(parts) != 3:
        return ""

    if 11 <= number % 100 <= 14:
        return parts[2]
    last = number % 10
    if last == 1:
        return parts[0]
    if 2 <= last <= 4:
        return parts[1]
    return parts[2]
