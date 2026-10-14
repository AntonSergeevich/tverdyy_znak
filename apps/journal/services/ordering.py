"""
Порядок, выставленный перетаскиванием.

Список приходит целиком — в том виде, в каком его оставили на экране.
Записываем шаг в десять, чтобы новый элемент с порядком по умолчанию не
вклинивался между соседями случайно.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction


def apply_order(queryset, raw: str, field: str = "position") -> int:
    ids = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if not ids or len(ids) != len(set(ids)):
        raise ValidationError("Порядок не разобрать — обновите страницу.")
    try:
        found = {str(obj.pk): obj for obj in queryset.filter(pk__in=ids)}
    except (ValidationError, ValueError) as exc:
        raise ValidationError("Порядок не разобрать — обновите страницу.") from exc
    # Чужое или уже удалённое в списке — значит, экран устарел. Молча
    # переставлять половину не будем.
    if len(found) != len(ids):
        raise ValidationError("Список успел измениться — обновите страницу и повторите.")
    with transaction.atomic():
        changed = []
        for index, pk in enumerate(ids, start=1):
            obj = found[pk]
            setattr(obj, field, index * 10)
            changed.append(obj)
        queryset.bulk_update(changed, [field])
    return len(changed)
