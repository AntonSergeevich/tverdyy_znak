"""
Подсказки «как в прошлый раз».

Педагог ведёт один и тот же предмет у одной и той же группы неделями,
и половина того, что он печатает, уже когда-то было напечатано. Тема
идёт по учебнику подряд, домашнее задание — того же вида. Поэтому и
тему, и задание предлагаем из прошлого: не подставляем молча, а даём
взять одним касанием.
"""
from __future__ import annotations

from apps.journal.models import Homework, Lesson

TOPIC_LIMIT = 15


def recent_topics(*, subject, group=None, exclude_lesson=None, limit: int = TOPIC_LIMIT) -> list[str]:
    """Темы прошлых занятий по предмету — свежие сверху, без повторов."""
    lessons = (
        Lesson.objects.filter(subject=subject)
        .exclude(topic="")
        .order_by("-starts_at")
    )
    if group is not None:
        lessons = lessons.filter(group=group)
    if exclude_lesson is not None:
        lessons = lessons.exclude(pk=exclude_lesson.pk)

    seen: list[str] = []
    for topic in lessons.values_list("topic", flat=True)[: limit * 4]:
        if topic not in seen:
            seen.append(topic)
        if len(seen) >= limit:
            break
    return seen


def previous_lesson(lesson: Lesson) -> Lesson | None:
    """Предыдущее занятие по тому же предмету у той же группы."""
    return (
        Lesson.objects.filter(
            subject=lesson.subject, group=lesson.group, starts_at__lt=lesson.starts_at
        )
        .order_by("-starts_at")
        .first()
    )


def previous_homework(lesson: Lesson) -> Homework | None:
    """
    Чем задавали в прошлый раз по этому же предмету у этой же группы.

    Не последнее по времени создания, а последнее по занятию: журнал
    заполняют задним числом, и «прошлый раз» — это прошлый урок, а не
    последняя запись в базе.
    """
    return (
        Homework.objects.filter(
            lesson__subject=lesson.subject,
            lesson__group=lesson.group,
            lesson__starts_at__lt=lesson.starts_at,
        )
        .select_related("lesson", "grade_item")
        .order_by("-lesson__starts_at")
        .first()
    )
