"""Расчёт баллов, уровней и валидация 100-балльного лимита (ТЗ 3.4, 9.5)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.tenancy import organization_context
from apps.journal.models import (
    GradeItem,
    GradeItemKind,
    Level,
    ModuleResult,
)
from apps.journal.services.grading import (
    create_default_structure,
    get_scale,
    points_budget,
    recalculate_module_result,
    set_grade,
)


@pytest.fixture
def structure(tenant_a):
    with organization_context(tenant_a.organization):
        items = create_default_structure(tenant_a.module, tenant_a.subject, tenant_a.group)
    return items


def test_default_structure_gives_exactly_100(tenant_a, structure):
    total = sum((item.max_points for item in structure), Decimal("0"))
    assert total == Decimal("100.00")
    assert sum(1 for i in structure if i.kind == GradeItemKind.CREDIT) == 1
    assert sum(1 for i in structure if i.kind == GradeItemKind.QUIZ) == 2
    assert sum(1 for i in structure if i.kind == GradeItemKind.LESSON) == 8


def test_budget_reports_remaining(tenant_a, structure):
    with organization_context(tenant_a.organization):
        budget = points_budget(tenant_a.module, tenant_a.subject, tenant_a.group)
    assert budget.limit == Decimal("100.00")
    assert budget.distributed == Decimal("100.00")
    assert budget.remaining == Decimal("0.00")


def test_cannot_exceed_100_points(tenant_a, structure):
    """Лимит модуля — жёсткий, и ошибка объясняет, сколько осталось."""
    with organization_context(tenant_a.organization):
        extra = GradeItem(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.QUIZ, title="Лишняя", max_points=Decimal("5.00"),
        )
        with pytest.raises(ValidationError) as exc:
            extra.full_clean(exclude=["lesson"])
    message = " ".join(exc.value.message_dict["max_points"])
    assert "осталось 0" in message
    assert "100" in message


def test_lesson_item_cannot_exceed_lesson_limit(tenant_a):
    with organization_context(tenant_a.organization):
        item = GradeItem(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.LESSON, max_points=Decimal("9.00"),
        )
        with pytest.raises(ValidationError) as exc:
            item.full_clean(exclude=["lesson"])
    assert "за одно занятие" in " ".join(exc.value.message_dict["max_points"]).lower()


def test_grade_cannot_exceed_item_max(tenant_a, structure):
    credit = next(i for i in structure if i.kind == GradeItemKind.CREDIT)
    with organization_context(tenant_a.organization):
        with pytest.raises(ValidationError):
            set_grade(student=tenant_a.student, grade_item=credit, points=Decimal("26"))


@pytest.mark.parametrize(
    "share, expected_level, passed",
    [
        (Decimal("0.50"), Level.FAILED, False),
        (Decimal("0.60"), Level.BASE, True),
        (Decimal("0.75"), Level.ELEVATED, True),
        (Decimal("0.95"), Level.ADVANCED, True),
    ],
)
def test_levels_by_thresholds(tenant_a, structure, share, expected_level, passed):
    """Пороги берутся из GradingScale, а не зашиты в код."""
    with organization_context(tenant_a.organization):
        for item in structure:
            set_grade(
                student=tenant_a.student, grade_item=item,
                points=(item.max_points * share).quantize(Decimal("0.01")),
            )
        result = ModuleResult.objects.get(
            student=tenant_a.student, subject=tenant_a.subject, module=tenant_a.module
        )
    assert result.total_points == (Decimal("100.00") * share).quantize(Decimal("0.01"))
    assert result.level == expected_level
    assert result.is_passed is passed


def test_thresholds_are_editable_per_organization(tenant_a, structure):
    """Владелец правит пороги без разработчика — уровень пересчитывается по ним."""
    with organization_context(tenant_a.organization):
        scale = get_scale(tenant_a.organization)
        scale.advanced_from = Decimal("70.00")
        scale.save()

        credit = next(i for i in structure if i.kind == GradeItemKind.CREDIT)
        set_grade(student=tenant_a.student, grade_item=credit, points=Decimal("25"))
        test_item = next(i for i in structure if i.kind == GradeItemKind.TEST)
        set_grade(student=tenant_a.student, grade_item=test_item, points=Decimal("15"))
        for item in [i for i in structure if i.kind == GradeItemKind.QUIZ]:
            set_grade(student=tenant_a.student, grade_item=item, points=Decimal("10"))
        for item in [i for i in structure if i.kind == GradeItemKind.LESSON][:2]:
            set_grade(student=tenant_a.student, grade_item=item, points=Decimal("5"))

        result = ModuleResult.objects.get(
            student=tenant_a.student, subject=tenant_a.subject, module=tenant_a.module
        )
    assert result.total_points == Decimal("70.00")
    assert result.level == Level.ADVANCED


def test_removing_grade_recalculates(tenant_a, structure):
    credit = next(i for i in structure if i.kind == GradeItemKind.CREDIT)
    with organization_context(tenant_a.organization):
        set_grade(student=tenant_a.student, grade_item=credit, points=Decimal("25"))
        set_grade(student=tenant_a.student, grade_item=credit, points=None)
        result = ModuleResult.objects.get(
            student=tenant_a.student, subject=tenant_a.subject, module=tenant_a.module
        )
    assert result.total_points == Decimal("0.00")
    assert result.level == Level.FAILED


def test_cannot_grade_non_graded_lesson(tenant_a):
    """Балл за занятие без оценивания выставить нельзя."""
    with organization_context(tenant_a.organization):
        item = GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group, lesson=tenant_a.lesson,
            kind=GradeItemKind.LESSON, max_points=Decimal("5.00"),
        )
        with pytest.raises(ValidationError):
            set_grade(student=tenant_a.student, grade_item=item, points=Decimal("3"))


def test_backdating_blocked_beyond_limit_but_owner_may(tenant_a, structure):
    """Задним числом дальше настроенного срока — только владелец (ТЗ 3.4)."""
    credit = next(i for i in structure if i.kind == GradeItemKind.CREDIT)
    with organization_context(tenant_a.organization):
        credit.due_date = dt.date.today() - dt.timedelta(days=40)
        credit.save(update_fields=["due_date"])

        with pytest.raises(PermissionDenied):
            set_grade(
                student=tenant_a.student, grade_item=credit,
                points=Decimal("20"), actor=tenant_a.teacher_user,
            )

        grade = set_grade(
            student=tenant_a.student, grade_item=credit,
            points=Decimal("20"), actor=tenant_a.owner_user,
        )
    assert grade.points == Decimal("20")


def test_points_are_decimal_not_float(tenant_a, structure):
    credit = next(i for i in structure if i.kind == GradeItemKind.CREDIT)
    with organization_context(tenant_a.organization):
        grade = set_grade(student=tenant_a.student, grade_item=credit, points=Decimal("12.35"))
        grade.refresh_from_db()
    assert isinstance(grade.points, Decimal)
    assert grade.points == Decimal("12.35")


def test_recalculation_is_idempotent(tenant_a, structure):
    credit = next(i for i in structure if i.kind == GradeItemKind.CREDIT)
    with organization_context(tenant_a.organization):
        set_grade(student=tenant_a.student, grade_item=credit, points=Decimal("25"))
        first = recalculate_module_result(
            student=tenant_a.student, subject=tenant_a.subject, module=tenant_a.module
        )
        second = recalculate_module_result(
            student=tenant_a.student, subject=tenant_a.subject, module=tenant_a.module
        )
    assert first.pk == second.pk
    assert second.total_points == Decimal("25.00")
    assert ModuleResult.all_objects.filter(student=tenant_a.student).count() == 1
