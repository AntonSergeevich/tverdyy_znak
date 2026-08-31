"""
Сервисный слой оценивания (ТЗ 3.4).

Вью здесь только вызывают функции: бизнес-логика во вью не живёт (ТЗ 9.1).
Пересчёт итога — явным вызовом, а не сигналом: сигналы трудно отлаживать.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.audit import AuditAction, log_audit
from apps.journal.models import (
    Grade,
    GradeItem,
    GradeItemKind,
    GradingScale,
    Level,
    Module,
    ModuleResult,
    Student,
    Subject,
)

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


# ─── Шкала ──────────────────────────────────────────────────────────────────
def get_scale(organization, academic_year=None) -> GradingScale:
    """Шкала организации: сначала привязанная к году, потом общая."""
    qs = GradingScale.all_objects.filter(organization=organization)
    scale = None
    if academic_year is not None:
        scale = qs.filter(academic_year=academic_year, is_default=True).first()
    scale = scale or qs.filter(academic_year__isnull=True, is_default=True).first() or qs.first()
    if scale is None:
        scale = GradingScale.all_objects.create(organization=organization)
    return scale


# ─── Планирование модуля: лимит 100 баллов ──────────────────────────────────
@dataclass(frozen=True)
class PointsBudget:
    limit: Decimal
    distributed: Decimal

    @property
    def remaining(self) -> Decimal:
        return self.limit - self.distributed


def points_budget(module, subject, group, *, exclude_item_id=None) -> PointsBudget:
    """Сколько из 100 баллов уже распределено по связке модуль-предмет-группа."""
    organization = module.organization
    scale = get_scale(organization, module.academic_year)
    qs = GradeItem.all_objects.filter(
        organization=organization, module=module, subject=subject, group=group
    )
    if exclude_item_id:
        qs = qs.exclude(pk=exclude_item_id)
    distributed = qs.aggregate(total=Sum("max_points"))["total"] or ZERO
    return PointsBudget(limit=scale.module_max_points, distributed=distributed)


def validate_grade_item(item: GradeItem) -> None:
    """
    Сумма максимумов элементов модуля не может превышать лимит.

    Сообщение объясняет, сколько уже распределено и сколько осталось —
    так требует ТЗ, и это единственное, что реально помогает педагогу.
    """
    if item.max_points is None or item.module_id is None:
        return
    if item.max_points <= 0:
        raise ValidationError({"max_points": "Максимум баллов должен быть больше нуля."})

    budget = points_budget(item.module, item.subject, item.group, exclude_item_id=item.pk)
    if item.max_points > budget.remaining:
        raise ValidationError(
            {
                "max_points": (
                    f"Не помещается в лимит модуля. Распределено "
                    f"{_fmt(budget.distributed)} из {_fmt(budget.limit)}, "
                    f"осталось {_fmt(budget.remaining)}, а вы ставите {_fmt(item.max_points)}."
                )
            }
        )

    if item.kind == GradeItemKind.LESSON:
        lesson_limit = item.organization.lesson_max_points
        if item.max_points > lesson_limit:
            raise ValidationError(
                {"max_points": f"За одно занятие нельзя дать больше {_fmt(lesson_limit)} баллов."}
            )
    if item.lesson_id and not item.lesson.is_graded:
        raise ValidationError(
            {"lesson": "Занятие отмечено как без оценивания — балл за него выставить нельзя."}
        )


def _fmt(value: Decimal) -> str:
    value = Decimal(value or 0)
    return f"{value.normalize():f}" if value == value.to_integral() else f"{value:.2f}"


@transaction.atomic
def create_default_structure(module, subject, group, *, actor=None) -> list[GradeItem]:
    """
    Разложить 100 баллов по умолчанию: зачёт 25, две проверочные по 10,
    контрольная 15, остальные 40 — по занятиям с оцениванием (ТЗ 3.4).
    """
    from apps.journal.models import DEFAULT_STRUCTURE

    if not subject.is_graded:
        raise ValidationError(
            f"«{subject.name}» — блок дня, а не учебный предмет: баллы по нему не выставляются."
        )

    if GradeItem.all_objects.filter(
        organization=module.organization, module=module, subject=subject, group=group
    ).exists():
        raise ValidationError("Структура для этого модуля уже создана.")

    created: list[GradeItem] = []
    position = 0
    for kind, spec in DEFAULT_STRUCTURE.items():
        for index in range(spec["count"]):
            position += 10
            created.append(
                GradeItem(
                    organization=module.organization,
                    module=module,
                    subject=subject,
                    group=group,
                    kind=kind,
                    title=_default_title(kind, index, spec["count"]),
                    max_points=spec["max_points"],
                    position=position,
                )
            )
    total = sum((item.max_points for item in created), ZERO)
    limit = get_scale(module.organization, module.academic_year).module_max_points
    if total > limit:  # pragma: no cover - защита от кривой правки констант
        raise ValidationError(f"Структура по умолчанию даёт {_fmt(total)} баллов при лимите {_fmt(limit)}.")

    GradeItem.all_objects.bulk_create(created)
    logger.info("Создана структура оценивания: %s элементов, %s баллов", len(created), total)
    return created


def _default_title(kind, index: int, count: int) -> str:
    labels = {
        GradeItemKind.CREDIT: "Зачёт по модулю",
        GradeItemKind.TEST: "Контрольная работа",
        GradeItemKind.QUIZ: "Проверочная работа",
        GradeItemKind.HOMEWORK: "Домашняя работа",
        GradeItemKind.LESSON: "Занятие с оцениванием",
    }
    base = labels.get(kind, "Работа")
    return base if count == 1 else f"{base} {index + 1}"


# ─── Занятие с оцениванием: место в плане модуля ────────────────────────────

@dataclass(frozen=True)
class GradingSwitch:
    """Что вышло из переключения оценивания и откуда взялись баллы."""

    item: GradeItem | None
    note: str = ""
    released: str = ""


def free_lesson_slots(module, subject, group):
    """
    Свободные места «Занятие с оцениванием» в плане модуля.

    План заранее откладывает часть сотни на занятия — по умолчанию сорок
    баллов на восемь занятий. Это и есть места: отметить занятие
    оцениваемым значит занять одно из них, а не добавить сверх плана.
    """
    return (
        GradeItem.objects.filter(
            module=module, subject=subject, group=group,
            kind=GradeItemKind.LESSON, lesson__isnull=True,
        )
        .order_by("position", "created_at")
    )


def _borrowable(lesson):
    """
    У каких занятий можно занять баллы: у тех, что ещё впереди и без оценок.

    Занятие, которое уже прошло и по которому баллы стоят, не трогаем ни
    при каких условиях: выставленное — это чужая работа, а не резерв.
    """
    return (
        GradeItem.objects.filter(
            module=lesson.module, subject=lesson.subject, group=lesson.group,
            kind=GradeItemKind.LESSON, lesson__isnull=False,
            lesson__starts_at__gt=lesson.starts_at,
        )
        .exclude(lesson=lesson)
        .exclude(grades__isnull=False)
        .select_related("lesson")
        .order_by("-lesson__starts_at")
    )


@transaction.atomic
def enable_lesson_grading(lesson, *, actor=None) -> GradingSwitch:
    """
    Сделать занятие оцениваемым.

    Порядок такой:

    1. Есть свободное место в плане — занимаем его. Ничего не прибавляется:
       баллы на занятия отложены заранее, место просто перестаёт пустовать.
    2. Мест нет, но в сотне есть остаток — заводим новую работу.
    3. Ни того ни другого — занимаем баллы у занятия, которое ещё впереди и
       по которому баллов никто не ставил. Оно становится без оценивания, а
       его баллы переходят сюда. Так «сделать с оцениванием» работает даже
       тогда, когда сотня разобрана целиком: педагог решает не «можно ли»,
       а «за счёт чего».
    4. Остался хвостик меньше обычного максимума — заводим работу на него:
       занятие на три балла честнее, чем отказ.

    Выставленные баллы неприкосновенны: у занятия, по которому уже стоят
    оценки, не занимают ничего.
    """
    existing = GradeItem.objects.filter(lesson=lesson).first()
    if existing is not None:
        if not lesson.is_graded:
            lesson.is_graded = True
            lesson.save(update_fields=["is_graded", "updated_at"])
        return GradingSwitch(item=existing)

    if not lesson.subject.is_graded:
        raise ValidationError(
            f"«{lesson.subject.name}» — блок дня, а не учебный предмет: "
            "баллы по нему не выставляются."
        )

    organization = lesson.organization
    default_points = organization.lesson_max_points
    note = ""
    released = ""

    slot = free_lesson_slots(lesson.module, lesson.subject, lesson.group).first()
    if slot is not None:
        item = slot
        note = f"Занято место «{slot.title}» из плана модуля."
    else:
        budget = points_budget(lesson.module, lesson.subject, lesson.group)
        points = min(default_points, budget.remaining)
        if points <= ZERO:
            donor = _borrowable(lesson).first()
            if donor is None:
                raise ValidationError(
                    {
                        "max_points": (
                            "Сотня баллов модуля разобрана целиком, и занять их не у кого: "
                            "все занятия впереди либо без оценивания, либо по ним уже "
                            "выставлены баллы. Освободите баллы в плане модуля."
                        )
                    }
                )
            points = min(default_points, donor.max_points)
            released = (
                f"Баллы взяты у занятия {timezone.localtime(donor.lesson.starts_at):%d.%m} "
                f"— оно стало без оценивания."
            )
            donor_lesson = donor.lesson
            donor.delete()
            donor_lesson.is_graded = False
            donor_lesson.save(update_fields=["is_graded", "updated_at"])
            note = released
        else:
            if points < default_points:
                note = f"В модуле оставалось {_fmt(points)} — занятие заведено на них."
        item = GradeItem(
            organization=organization, module=lesson.module, subject=lesson.subject,
            group=lesson.group, kind=GradeItemKind.LESSON,
            title="Занятие с оцениванием", max_points=points,
        )

    item.lesson = lesson
    item.due_date = lesson.local_date
    lesson.is_graded = True

    validate_grade_item(item)
    item.save()
    lesson.save(update_fields=["is_graded", "updated_at"])
    logger.info("Занятие %s стало оцениваемым на %s баллов", lesson.pk, _fmt(item.max_points))
    return GradingSwitch(item=item, note=note, released=released)


@transaction.atomic
def disable_lesson_grading(lesson) -> GradingSwitch:
    """
    Снять оценивание с занятия.

    Баллы не пропадают, а возвращаются в план модуля свободным местом:
    сотня разложена один раз, и снятое оценивание не должно её обеднять.
    Занятие с выставленными баллами не снимается — сначала уберите баллы.
    """
    item = GradeItem.objects.filter(lesson=lesson).first()
    if item is not None:
        if Grade.objects.filter(grade_item=item).exists():
            raise ValidationError(
                {"lesson": "Сначала удалите выставленные баллы за это занятие."}
            )
        item.lesson = None
        item.due_date = None
        item.title = item.title or "Занятие с оцениванием"
        item.save(update_fields=["lesson", "due_date", "title", "updated_at"])

    lesson.is_graded = False
    lesson.save(update_fields=["is_graded", "updated_at"])
    return GradingSwitch(
        item=None,
        note="Баллы вернулись в план модуля свободным местом." if item else "",
    )


def student_module_points(*, students, module, subject) -> dict:
    """
    Сколько баллов у каждого ученика в модуле — одним запросом.

    Нужно там, где ставят балл: «пять из пяти» без «а всего у него
    тридцать семь из ста» — половина картинки.
    """
    rows = (
        Grade.objects.filter(
            student__in=students, grade_item__module=module, grade_item__subject=subject
        )
        .values("student_id")
        .annotate(total=Sum("points"))
    )
    return {row["student_id"]: row["total"] or ZERO for row in rows}


# ─── Выставление балла ──────────────────────────────────────────────────────
def _can_backdate(user, organization) -> bool:
    return bool(user and (user.is_superuser or user.has_role(organization, Role.OWNER)))


def check_grade_allowed(*, grade_item: GradeItem, points: Decimal, actor, when=None) -> None:
    organization = grade_item.organization
    if points is None:
        raise ValidationError({"points": "Укажите балл."})
    points = Decimal(points)
    if points < 0:
        raise ValidationError({"points": "Балл не может быть отрицательным."})
    if points > grade_item.max_points:
        raise ValidationError(
            {"points": f"Максимум за эту работу — {_fmt(grade_item.max_points)} баллов."}
        )
    if grade_item.lesson_id and not grade_item.lesson.is_graded:
        raise ValidationError(
            {"points": "Это занятие без оценивания. Сначала отметьте его как оцениваемое."}
        )

    reference_date = grade_item.due_date or (
        grade_item.lesson.local_date if grade_item.lesson_id else None
    )
    if reference_date is not None:
        days_late = (timezone.localdate() - reference_date).days
        limit = organization.grade_backdate_days
        if days_late > limit and not _can_backdate(actor, organization):
            raise PermissionDenied(
                f"Выставить балл задним числом можно в течение {limit} дней. "
                f"С даты работы прошло {days_late}. Обратитесь к владельцу организации."
            )


@transaction.atomic
def set_grade(
    *,
    student: Student,
    grade_item: GradeItem,
    points: Decimal | None,
    actor=None,
    comment: str = "",
    request=None,
) -> Grade | None:
    """
    Выставить или изменить балл и пересчитать итог модуля.

    points=None удаляет балл (мягко). Возвращает Grade или None.
    """
    organization = grade_item.organization
    if student.organization_id != organization.id:
        raise PermissionDenied("Ученик из другой организации.")

    if points is None or points == "":
        grade = Grade.all_objects.filter(
            organization=organization, student=student, grade_item=grade_item,
            deleted_at__isnull=True,
        ).first()
        if grade is not None:
            grade.delete()
            log_audit(
                action=AuditAction.GRADE_DELETED, request=request, organization=organization,
                actor=actor, obj=grade, student=str(student.pk), item=str(grade_item.pk),
            )
        recalculate_module_result(
            student=student, subject=grade_item.subject, module=grade_item.module
        )
        return None

    points = Decimal(points)
    check_grade_allowed(grade_item=grade_item, points=points, actor=actor)

    grade = (
        Grade.all_objects.select_for_update()
        .filter(
            organization=organization, student=student, grade_item=grade_item,
            deleted_at__isnull=True,
        )
        .first()
    )
    created = grade is None
    if created:
        grade = Grade(organization=organization, student=student, grade_item=grade_item)
    grade.points = points
    grade.comment = comment or ""
    grade.given_by = actor
    grade.graded_at = timezone.now()
    grade.deleted_at = None
    grade.save()
    recalculate_module_result(student=student, subject=grade_item.subject, module=grade_item.module)
    log_audit(
        action=AuditAction.GRADE_CHANGED, request=request, organization=organization, actor=actor,
        obj=grade, student=str(student.pk), item=str(grade_item.pk), points=str(points),
        created=created,
    )
    return grade


@transaction.atomic
def recalculate_module_result(*, student: Student, subject: Subject, module: Module) -> ModuleResult:
    """
    Пересчёт итога модуля.

    Блокируем строку результата (select_for_update): два педагога могут
    выставлять баллы по разным предметам одновременно, и сумма не должна
    ломаться (ТЗ 3.4, 9.1).
    """
    organization = module.organization
    scale = get_scale(organization, module.academic_year)

    result, _ = ModuleResult.all_objects.get_or_create(
        organization=organization, student=student, subject=subject, module=module
    )
    # Повторный select уже под блокировкой.
    result = ModuleResult.all_objects.select_for_update().get(pk=result.pk)

    total = (
        Grade.all_objects.filter(
            organization=organization,
            student=student,
            deleted_at__isnull=True,
            grade_item__module=module,
            grade_item__subject=subject,
        ).aggregate(total=Sum("points"))["total"]
        or ZERO
    )
    planned = (
        GradeItem.all_objects.filter(
            organization=organization, module=module, subject=subject,
            group__memberships__student=student,
        )
        .distinct()
        .aggregate(total=Sum("max_points"))["total"]
        or ZERO
    )

    result.total_points = total
    result.planned_points = planned
    result.level = scale.level_for(total)
    result.is_passed = scale.is_passed(total)
    result.gap_to_next_level = _gap_to_next(scale, total)
    result.computed_at = timezone.now()
    result.save(
        update_fields=[
            "total_points", "planned_points", "level", "is_passed",
            "gap_to_next_level", "computed_at", "updated_at",
        ]
    )
    return result


def _gap_to_next(scale: GradingScale, total: Decimal) -> Decimal | None:
    for threshold in (scale.base_from, scale.elevated_from, scale.advanced_from):
        if total < threshold:
            return threshold - total
    return None


def recalculate_for_items(items: Iterable[GradeItem]) -> None:
    """Пересчёт после массового изменения структуры модуля."""
    seen = set()
    for item in items:
        key = (item.module_id, item.subject_id, item.group_id)
        if key in seen:
            continue
        seen.add(key)
        students = Student.all_objects.filter(
            organization=item.organization, group_memberships__group_id=item.group_id,
            deleted_at__isnull=True,
        ).distinct()
        for student in students:
            recalculate_module_result(student=student, subject=item.subject, module=item.module)


LEVEL_LABELS = {
    Level.FAILED: "незачёт",
    Level.BASE: "базовый",
    Level.ELEVATED: "повышенный",
    Level.ADVANCED: "продвинутый",
}
