"""
Кабинет ученика — отдельный вход, а не раздел родительского (ТЗ 5.2).

Приватность здесь не косметика: без неё механика скрытых личных целей
не работает.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import role_required
from apps.journal.models import (
    Goal,
    GoalKind,
    GoalStatus,
    GoalVisibility,
    GradeItemKind,
    Grade,
    GradeItem,
    ModuleResult,
    MoodEntry,
    Student,
)
from apps.journal.services.grading import get_scale
from apps.journal.views.parent import current_module, week_lessons


def _own_student(request) -> Student:
    student = Student.objects.filter(user=request.user).first()
    if student is None:
        raise PermissionDenied("К этой учётной записи не привязан профиль ученика.")
    return student


def _goals_for(request, student):
    """Цели ученика — с оглядкой на то, кто на них смотрит."""
    goals = Goal.objects.filter(student=student, status=GoalStatus.ACTIVE)
    if getattr(request, "impersonator", None) is not None:
        goals = Goal.objects.visible_to_others().filter(
            student=student, status=GoalStatus.ACTIVE
        )
    return goals.select_related("subject", "module")


@login_required
@role_required("student")
def student_home(request):
    organization = request.organization
    student = _own_student(request)
    module = current_module(organization)

    results = (
        ModuleResult.objects.filter(student=student, module=module)
        .select_related("subject", "module")
        .order_by("subject__position")
        if module
        else ModuleResult.objects.none()
    )
    homework = (
        GradeItem.objects.filter(
            kind=GradeItemKind.HOMEWORK,
            group__memberships__student=student,
            due_date__gte=timezone.localdate() - timedelta(days=7),
        )
        .select_related("subject")
        .order_by("due_date")
        .distinct()[:10]
    )
    today_mood = MoodEntry.objects.filter(student=student, day=timezone.localdate()).first()
    yesterday = timezone.localdate() - timedelta(days=1)
    yesterday_mood = MoodEntry.objects.filter(student=student, day=yesterday).first()

    return render(
        request,
        "cabinet/student/home.html",
        {
            "student": student,
            "module": module,
            "results": list(results),
            "homework": list(homework),
            "week": list(week_lessons(student)),
            "scale": get_scale(organization),
            # Свои цели ученик видит целиком, включая скрытые. Но если
            # кабинет смотрят чужими глазами — только открытые: ребёнку
            # обещано, что скрытые не видит никто, и «проверка» не повод
            # это обещание нарушить.
            "goals": list(_goals_for(request, student)),
            "today_mood": today_mood,
            "yesterday_mood": yesterday_mood,
            "yesterday": yesterday,
            "mood_choices": MoodEntry.Scale.choices,
        },
    )


@login_required
@role_required("student")
@require_http_methods(["POST"])
def goal_create(request):
    student = _own_student(request)
    visibility = (
        GoalVisibility.HIDDEN
        if request.POST.get("visibility") == GoalVisibility.HIDDEN
        else GoalVisibility.OPEN
    )
    title = (request.POST.get("title") or "").strip()
    if title:
        Goal.objects.create(
            organization=request.organization,
            student=student,
            kind=GoalKind.PERSONAL,
            visibility=visibility,
            title=title[:250],
            description=(request.POST.get("description") or "").strip(),
            created_by=request.user,
        )
    goals = Goal.objects.filter(student=student, status=GoalStatus.ACTIVE).select_related("subject")
    return render(request, "cabinet/student/partials/goals.html", {"goals": list(goals)})


@login_required
@role_required("student")
@require_http_methods(["POST"])
def goal_toggle(request, goal_id):
    student = _own_student(request)
    goal = get_object_or_404(Goal.objects.filter(student=student), pk=goal_id)
    goal.status = GoalStatus.DONE if goal.status == GoalStatus.ACTIVE else GoalStatus.ACTIVE
    goal.save(update_fields=["status", "updated_at"])
    goals = Goal.objects.filter(student=student, status=GoalStatus.ACTIVE).select_related("subject")
    return render(request, "cabinet/student/partials/goals.html", {"goals": list(goals)})


@login_required
@role_required("student")
@require_http_methods(["POST"])
def mood_save(request):
    """
    Отметка состояния. Разрешено за сегодня и за вчера, штрафов за пропуск нет.

    Агрегат по группе наружу не выводится — это внутренний инструмент (ТЗ 6).
    """
    student = _own_student(request)
    today = timezone.localdate()
    day = today
    if request.POST.get("day") == "yesterday":
        day = today - timedelta(days=1)

    try:
        value = int(request.POST.get("value", ""))
    except ValueError:
        value = 0
    if value in dict(MoodEntry.Scale.choices):
        MoodEntry.objects.update_or_create(
            organization=request.organization,
            student=student,
            day=day,
            defaults={"value": value, "note": (request.POST.get("note") or "").strip()},
        )

    return render(
        request,
        "cabinet/student/partials/mood.html",
        {
            "today_mood": MoodEntry.objects.filter(student=student, day=today).first(),
            "yesterday_mood": MoodEntry.objects.filter(
                student=student, day=today - timedelta(days=1)
            ).first(),
            "yesterday": today - timedelta(days=1),
            "mood_choices": MoodEntry.Scale.choices,
            "saved": True,
        },
    )
