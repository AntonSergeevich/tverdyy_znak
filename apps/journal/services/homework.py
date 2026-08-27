"""
Домашнее задание к занятию.

Задают его почти каждый раз, а на баллы идёт малая часть — поэтому текст
задания живёт отдельно от оценивания. Когда задание всё-таки на оценку,
к нему привязывается обычный элемент оценивания, и баллы попадают в те же
сто баллов модуля, что и всё остальное.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from django.db import models, transaction
from django.utils import timezone

from apps.journal.models import GradeItem, GradeItemKind, Homework
from apps.journal.services.grading import validate_grade_item

# Заголовок оценивания — начало текста задания: в списке «Задания модуля»
# должно быть видно, о чём речь, а не «Домашняя работа» восемь раз подряд.
TITLE_LIMIT = 120


def parse_points(raw) -> Decimal | None:
    """Баллы из формы. Пусто и ноль — значит, задание без оценки."""
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


def parse_date(raw) -> dt.date | None:
    try:
        return dt.date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


@transaction.atomic
def save_homework(*, lesson, text: str, due_date=None, max_points=None, actor=None):
    """
    Записать задание к занятию.

    Пустой текст означает «задания нет» — запись удаляется вместе с
    оцениванием, если оно было. Иначе педагогу пришлось бы отдельно
    искать, как убрать случайно заданное.

    Возвращает домашнее задание или None, если его убрали.
    """
    text = (text or "").strip()
    existing = Homework.objects.filter(lesson=lesson).first()

    if not text:
        if existing is not None:
            item = existing.grade_item
            existing.delete()
            if item is not None:
                item.delete()
        return None

    homework = existing or Homework(organization=lesson.organization, lesson=lesson)
    homework.text = text
    homework.due_date = due_date
    if homework.created_by_id is None:
        homework.created_by = actor

    item = homework.grade_item
    if max_points is None:
        homework.grade_item = None
        homework.save()
        if item is not None:
            item.delete()
        return homework

    if item is None:
        item = GradeItem(
            organization=lesson.organization, module=lesson.module,
            subject=lesson.subject, group=lesson.group,
            kind=GradeItemKind.HOMEWORK,
        )
    item.title = text[:TITLE_LIMIT]
    item.max_points = max_points
    item.due_date = due_date or lesson.local_date
    # Проверка та же, что и везде: сотня на модуль не резиновая. Ошибка
    # уходит наверх — задание не сохранится молча без баллов.
    validate_grade_item(item)
    item.save()

    homework.grade_item = item
    homework.save()
    return homework


def upcoming_homework(student, *, limit: int = 10) -> list[Homework]:
    """
    Что задано: ближайшие задания и те, чей срок прошёл на днях.

    Заданное неделю назад ещё показываем — его могли не сдать, а убирать
    задолженность с глаз значит делать вид, что её нет.
    """
    since = timezone.localdate() - dt.timedelta(days=7)
    return list(
        Homework.objects.filter(lesson__group__memberships__student=student)
        .filter(
            models.Q(due_date__gte=since)
            | models.Q(due_date__isnull=True, lesson__starts_at__date__gte=since)
        )
        .select_related("lesson", "lesson__subject", "grade_item")
        .order_by("due_date", "lesson__starts_at")
        .distinct()[:limit]
    )
