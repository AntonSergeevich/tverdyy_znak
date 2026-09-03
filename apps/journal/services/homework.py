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
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.journal.models import (
    GradeItem,
    GradeItemKind,
    Homework,
    HomeworkFile,
    HomeworkMark,
    HomeworkVerdict,
    Student,
)
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
    оцениванием и вложениями, если они были. Иначе педагогу пришлось бы
    отдельно искать, как убрать случайно заданное.

    Возвращает домашнее задание или None, если его убрали.
    """
    text = (text or "").strip()
    existing = Homework.objects.filter(lesson=lesson).first()

    if not text:
        if existing is not None:
            item = existing.grade_item
            for attachment in existing.files.all():
                attachment.file.delete(save=False)
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
        # Самоподготовка тоже занимает готовое место в плане модуля, а не
        # добавляет работу сверх сотни: по регламенту на неё отложено 15
        # баллов, не больше 5 за одну работу. Свободного места нет —
        # заводим новую работу, и тогда её проверит лимит модуля.
        from apps.journal.services.grading import free_slots

        item = free_slots(
            lesson.module, lesson.subject, lesson.group, GradeItemKind.HOMEWORK
        ).first()
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


# ─── Состояние задания у ученика ────────────────────────────────────────────
#
# Задание живёт по кругу, а не «задано и забыто»:
#
#     задано → сделал → проверено: зачтено
#                        ↘ нужно доделать → (снова сделал)
#
# Из этого следует раскладка кабинета: «Сделать» — то, что ещё на ученике,
# включая возвращённое на доработку; «На проверке» — то, что уже не на нём;
# «Проверено» — закрытое, и его можно свернуть.

# Насколько далеко назад смотрим, если модуля нет (лето, каникулы, ещё не
# завели расписание). В обычное время границей служит модуль.
FALLBACK_DAYS = 30

# Сколько закрытых заданий показываем. Это архив, а не список дел: он
# свёрнут, и бесконечно листать его незачем.
DONE_LIMIT = 20


def _visible_homework(student, module=None):
    """Задания группы ученика за текущий модуль — общая основа для всех корзин."""
    items = (
        Homework.objects.filter(lesson__group__memberships__student=student)
        .select_related("lesson", "lesson__subject", "grade_item")
        .prefetch_related("files")
    )
    if module is not None:
        return items.filter(lesson__module=module).distinct()
    since = timezone.localdate() - dt.timedelta(days=FALLBACK_DAYS)
    return items.filter(lesson__starts_at__date__gte=since).distinct()


def homework_board(student, *, module=None) -> dict:
    """
    Задания ученика, разложенные по состоянию.

    Раньше здесь был один список: ближайшие задания и просроченные за
    неделю, обрезанные по десятому. Обрезание было молчаливым — ребёнок
    видел десять и не знал, что есть ещё, — а через неделю после срока
    несданное исчезало совсем. Задолженность не должна растворяться
    сама, поэтому «Сделать» теперь не обрезается вовсе.

    Границей служит модуль, и это не техническое ограничение: по
    регламенту домашнее досдаётся не позднее последнего дня зачётной
    недели. Дальше баллы за модуль закрыты, и держать это в списке дел
    значило бы предлагать сделать то, что уже ничего не изменит.
    """
    items = list(_visible_homework(student, module).order_by("due_date", "lesson__starts_at"))
    marks = {
        mark.homework_id: mark
        for mark in HomeworkMark.objects.filter(student=student, homework__in=items)
    }

    todo, review, checked = [], [], []
    for item in items:
        item.mark = marks.get(item.id)
        if item.mark is None or not item.mark.is_checked:
            (review if item.mark and item.mark.is_done else todo).append(item)
        elif item.mark.needs_redo:
            # Вернули на доработку — снова дело ученика, а не архив.
            todo.append(item)
        else:
            checked.append(item)

    checked.sort(key=lambda item: item.mark.checked_at, reverse=True)
    return {
        "todo": todo,
        "review": review,
        "checked": checked[:DONE_LIMIT],
        "checked_total": len(checked),
    }


def upcoming_homework(student, *, module=None) -> list[Homework]:
    """Всё, что ещё на ученике: не сдано или возвращено на доработку."""
    return homework_board(student, module=module)["todo"]


@transaction.atomic
def mark_done(*, homework: Homework, student, done: bool) -> HomeworkMark | None:
    """
    Отметка ученика «сделал». Возвращает состояние после переклика.

    Ставит и снимает сам ученик, пока задание не проверено: передумать он
    имеет полное право. После проверки снять нельзя — иначе «проверено»
    перестало бы что-либо значить, и педагог проверял бы одно и то же
    по второму разу.

    Повторное «сделал» после возврата на доработку снимает проверку:
    работа ушла заново, и педагогу её снова смотреть. Комментарий при
    этом остаётся — по нему и доделывали.
    """
    mark = HomeworkMark.objects.filter(homework=homework, student=student).first()

    if done:
        if mark is None:
            mark = HomeworkMark(
                organization=homework.organization, homework=homework, student=student
            )
        mark.done_at = timezone.now()
        mark.checked_at = None
        mark.checked_by = None
        mark.verdict = ""
        mark.save()
        return mark

    if mark is None:
        return None
    if mark.is_checked:
        raise ValidationError(
            "Задание уже проверено — отметку снять нельзя. "
            "Если что-то не так, скажите педагогу."
        )
    mark.delete()
    return None


@transaction.atomic
def review(*, homework: Homework, student, verdict: str, comment: str = "", actor=None):
    """
    Проверка педагога: зачтено или нужно доделать.

    Строка заводится и для того, кто кнопку «сделал» не нажимал: работу
    приносят в тетради, и отсутствие нажатия — не отсутствие работы.

    Пустой вердикт снимает проверку. Это не тонкость: промах пальцем по
    строке чужого ученика иначе остался бы навсегда, а исправить его было
    бы негде.
    """
    mark = HomeworkMark.objects.filter(homework=homework, student=student).first()
    if mark is None:
        mark = HomeworkMark(
            organization=homework.organization, homework=homework, student=student
        )

    if not verdict:
        if mark.pk is None:
            return None
        mark.checked_at = None
        mark.checked_by = None
        mark.verdict = ""
        if not mark.is_done:
            # Ни отметки ученика, ни проверки — строке незачем существовать.
            mark.delete()
            return None
        mark.save()
        return mark

    if verdict not in HomeworkVerdict.values:
        raise ValidationError("Итог проверки может быть только «зачтено» или «доделать».")

    mark.verdict = verdict
    mark.comment = (comment or "").strip()
    mark.checked_at = timezone.now()
    mark.checked_by = actor
    mark.save()
    return mark


@transaction.atomic
def accept_marked(*, homework: Homework, actor=None) -> int:
    """
    Зачесть всем, кто отметил «сделал» и ещё не проверен.

    Трогаем только отметившихся и только непроверенных: «зачесть всем» не
    должно молча закрывать тех, кто ничего не сдавал, и не должно
    перебивать уже поставленное «нужно доделать» — иначе одно нажатие
    отменяет работу, которую педагог только что сделал руками.

    Возвращает, сколько строк изменилось.
    """
    return HomeworkMark.objects.filter(
        homework=homework, done_at__isnull=False, checked_at__isnull=True
    ).update(
        verdict=HomeworkVerdict.ACCEPTED,
        checked_at=timezone.now(),
        checked_by=actor,
        updated_at=timezone.now(),
    )


def review_rows(homework: Homework) -> list[dict]:
    """
    Ученики группы и состояние их домашнего — без запроса на строку.

    Порядок тот же, что в журнале баллов: педагог смотрит на один и тот же
    список фамилий на обоих экранах, и переучиваться ему не приходится.
    """
    students = list(
        Student.objects.filter(group_memberships__group=homework.lesson.group_id)
        .order_by("last_name", "first_name")
        .distinct()
    )
    marks = {
        mark.student_id: mark
        for mark in HomeworkMark.objects.filter(homework=homework, student__in=students)
    }
    return [{"student": student, "mark": marks.get(student.id)} for student in students]


def review_counts(homework: Homework) -> dict:
    """Сколько отметилось, сколько ждёт проверки, сколько закрыто."""
    marks = HomeworkMark.objects.filter(homework=homework)
    checked = marks.filter(checked_at__isnull=False)
    return {
        "done": marks.filter(done_at__isnull=False).count(),
        "waiting": marks.filter(done_at__isnull=False, checked_at__isnull=True).count(),
        "accepted": checked.filter(verdict=HomeworkVerdict.ACCEPTED).count(),
        "redo": checked.filter(verdict=HomeworkVerdict.REDO).count(),
    }


def done_by(homework: Homework, student) -> bool:
    return HomeworkMark.objects.filter(
        homework=homework, student=student, done_at__isnull=False
    ).exists()


# ─── Вложения ───────────────────────────────────────────────────────────────

def check_attachment(uploaded, *, already: int = 0) -> None:
    """
    Можно ли принять этот файл.

    Проверяем расширение, а не то, что браузер назвал типом: тип приходит
    от клиента и ничего не гарантирует. Список закрытый и намеренно
    скучный — всё, в чём педагоги действительно присылают задания, и
    ничего исполняемого.
    """
    name = (getattr(uploaded, "name", "") or "").strip()
    if not name:
        raise ValidationError("У файла нет имени — попробуйте выбрать его заново.")

    suffix = Path(name).suffix.lower()
    if suffix not in HomeworkFile.ALLOWED_SUFFIXES:
        raise ValidationError(
            f"«{name}» приложить нельзя. Подойдут документы (Word, PDF, RTF, ODT, txt), "
            "таблицы (Excel, CSV), презентации и картинки."
        )
    if uploaded.size > HomeworkFile.MAX_SIZE:
        limit = HomeworkFile.MAX_SIZE // (1024 * 1024)
        raise ValidationError(
            f"«{name}» тяжелее {limit} МБ. Большой файл лучше положить на диск "
            "и дать ссылку в тексте задания."
        )
    if already >= HomeworkFile.MAX_PER_HOMEWORK:
        raise ValidationError(
            f"К одному заданию можно приложить не больше {HomeworkFile.MAX_PER_HOMEWORK} файлов."
        )


@transaction.atomic
def attach_files(*, homework: Homework, uploads, actor=None) -> list[HomeworkFile]:
    """
    Приложить файлы к заданию.

    Проверяем все до единого и только потом сохраняем: принять три файла
    из пяти и промолчать о двух отвергнутых — худшее, что здесь можно
    сделать, потому что заметят это уже ученики.
    """
    uploads = [item for item in (uploads or []) if item]
    if not uploads:
        return []

    already = homework.files.count()
    for index, uploaded in enumerate(uploads):
        check_attachment(uploaded, already=already + index)

    saved = []
    for uploaded in uploads:
        attachment = HomeworkFile(
            organization=homework.organization, homework=homework,
            name=uploaded.name[:250], size=uploaded.size, uploaded_by=actor,
        )
        attachment.file = uploaded
        attachment.save()
        saved.append(attachment)
    return saved


def remove_file(attachment: HomeworkFile) -> None:
    """Убрать вложение вместе с файлом: иначе хранилище растёт мусором."""
    attachment.file.delete(save=False)
    attachment.delete()
