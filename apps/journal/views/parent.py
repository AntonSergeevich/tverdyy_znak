"""
Кабинет родителя.

Главный экран отвечает на три вопроса без прокрутки: как ребёнок учится
сейчас, что на этой неделе, надо ли платить (ТЗ 5.1).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.journal.access import accessible_students, get_student_or_403
from apps.journal.models import (
    Grade,
    Lesson,
    Module,
    ModuleKind,
    ModuleResult,
    Payment,
    Student,
)
from apps.journal.services.grading import get_scale


def current_module(organization, day=None) -> Module | None:
    day = day or timezone.localdate()
    return (
        Module.objects.filter(
            kind=ModuleKind.MODULE, starts_on__lte=day, ends_on__gte=day
        ).select_related("academic_year").first()
        or Module.objects.filter(kind=ModuleKind.MODULE, starts_on__gt=day)
        .select_related("academic_year")
        .order_by("starts_on")
        .first()
    )


def week_lessons(student: Student, day=None):
    day = day or timezone.localdate()
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    return (
        Lesson.objects.filter(
            group__memberships__student=student,
            starts_at__date__gte=start,
            starts_at__date__lte=end,
        )
        .select_related("subject", "group", "teacher", "teacher__user")
        .order_by("starts_at")
        .distinct()
    )


def student_overview(request, student: Student) -> dict:
    organization = request.organization
    module = current_module(organization)
    results = (
        ModuleResult.objects.filter(student=student, module=module)
        .select_related("subject", "module")
        .order_by("subject__position", "subject__name")
        if module
        else ModuleResult.objects.none()
    )
    history = (
        ModuleResult.objects.filter(student=student)
        .select_related("subject", "module")
        .order_by("module__starts_on")
    )
    comments = (
        Grade.objects.filter(student=student)
        .exclude(comment="")
        .select_related("grade_item", "grade_item__subject", "given_by")
        .order_by("-graded_at")[:10]
    )
    payments = Payment.objects.filter(student=student).order_by("-period_start")[:6]

    # Динамика: средний балл за модуль. Считаем здесь, а не в шаблоне —
    # в шаблоне арифметике не место.
    buckets: dict[str, list] = {}
    for result in history:
        buckets.setdefault(str(result.module), []).append(result.total_points)
    dynamics = [
        {
            "label": label,
            "average": (sum(values) / len(values)).quantize(Decimal("0.1")),
        }
        for label, values in buckets.items()
    ]

    return {
        "student": student,
        "module": module,
        "results": list(results),
        "history": list(history),
        "dynamics": dynamics,
        "comments": list(comments),
        "payments": list(payments),
        "week": list(week_lessons(student)),
        "scale": get_scale(organization),
        "days_left": module.days_left if module else None,
    }


@login_required
@role_required("parent", "admin", "owner", "platform_admin")
def parent_home(request):
    organization = request.organization
    children = list(
        accessible_students(request.user, organization).order_by("last_name", "first_name")
    )
    if not children:
        return render(request, "cabinet/parent/empty.html", status=200)

    requested = request.GET.get("child")
    student = next((c for c in children if str(c.pk) == requested), children[0])
    log_audit(action=AuditAction.VIEW_STUDENT, request=request, obj=student, scope="parent_home")

    context = student_overview(request, student)
    context["children"] = children
    return render(request, "cabinet/parent/home.html", context)


@login_required
@role_required("parent", "admin", "owner", "platform_admin")
def parent_child(request, student_id):
    organization = request.organization
    student = get_student_or_403(request.user, organization, student_id)
    log_audit(action=AuditAction.VIEW_STUDENT, request=request, obj=student, scope="parent_child")
    context = student_overview(request, student)
    context["children"] = list(accessible_students(request.user, organization))
    return render(request, "cabinet/parent/home.html", context)
