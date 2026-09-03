"""
Кабинет ученика — отдельный вход, а не раздел родительского (ТЗ 5.2).

Приватность здесь не косметика: без неё механика скрытых личных целей
не работает.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import models
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import role_required
from apps.journal.models import (
    Goal,
    GoalKind,
    GoalStatus,
    GoalStep,
    GoalVisibility,
    GradeItemKind,
    Grade,
    GradeItem,
    Hero,
    Homework,
    ModuleResult,
    MoodEntry,
    Student,
)
from apps.journal.services.goals import path_of, set_steps, toggle_step
from apps.journal.services.grading import get_scale
from apps.journal.services.homework import homework_board, mark_done
from apps.journal.views.parent import current_module, day_lessons


def _with_path(goals):
    """
    Цели вместе с их путём.

    Шаги подтягиваем разом: у цели их единицы, но целей может быть
    несколько, и запрос на каждую — тот самый N+1. Отметки на дорожке
    расставляем здесь же: шаблон не должен считать проценты.
    """
    goals = list(goals.prefetch_related("steps"))
    for goal in goals:
        steps = list(goal.steps.all())
        goal.step_list = steps
        goal.path = path_of(goal)
        for index, step in enumerate(steps, start=1):
            # Целое число процентов, а не дробь: в русской локали шаблон
            # печатает 33.3 как «33,3», и такой left в CSS не работает —
            # все отметки слипались в начале дорожки.
            step.offset = int(round(index * 100 / len(steps)))
    return goals


def _own_student(request) -> Student:
    student = Student.objects.filter(user=request.user).first()
    if student is None:
        raise PermissionDenied("К этой учётной записи не привязан профиль ученика.")
    return student


def _goals_for(request, student, *, status: str = GoalStatus.ACTIVE):
    """Цели ученика — с оглядкой на то, кто на них смотрит."""
    goals = Goal.objects.filter(student=student, status=status)
    if getattr(request, "impersonator", None) is not None:
        goals = Goal.objects.visible_to_others().filter(student=student, status=status)
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
    board = homework_board(student, module=module)
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
            "board": board,
            "today_lessons": list(day_lessons(student)),
            "scale": get_scale(organization),
            # Свои цели ученик видит целиком, включая скрытые. Но если
            # кабинет смотрят чужими глазами — только открытые: ребёнку
            # обещано, что скрытые не видит никто, и «проверка» не повод
            # это обещание нарушить.
            **_goals_context(request, student),
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
    return _goals_block(request, student)


@login_required
@role_required("student")
@require_http_methods(["POST"])
def goal_toggle(request, goal_id):
    student = _own_student(request)
    goal = get_object_or_404(Goal.objects.filter(student=student), pk=goal_id)
    goal.status = GoalStatus.DONE if goal.status == GoalStatus.ACTIVE else GoalStatus.ACTIVE
    goal.save(update_fields=["status", "updated_at"])
    return _goals_block(request, student)


def _goals_block(request, student):
    """
    Ответ на любое действие с целями: блок целей целиком.

    Целиком — потому что в нём меняется не только список: выбранный спутник
    отмечен здесь же, и подменять один список значило оставлять отметку
    «текущий» на прежнем месте.
    """
    return render(
        request,
        "cabinet/student/partials/goals.html",
        _goals_context(request, student),
    )


def _goals_context(request, student) -> dict:
    """Активные цели, достигнутые и спутник — один набор для всех ответов."""
    return {
        "student": student,
        "goals": _with_path(_goals_for(request, student)),
        # Достигнутое не исчезает: список сделанного — и есть ответ на
        # вопрос «двигаюсь ли я вообще», которого одна активная цель не даёт.
        "done_goals": _with_path(
            _goals_for(request, student, status=GoalStatus.DONE)
        ),
        "heroes": Hero.choices,
    }


@login_required
@role_required("student")
@require_http_methods(["POST"])
def goal_steps_save(request, goal_id):
    """
    Разложить цель на шаги.

    По шагу в строке — так быстрее всего записать то, что уже сложилось
    в голове. Отметки о выполнении переживают правку: ученик уточняет
    формулировку, а не начинает путь заново.
    """
    student = _own_student(request)
    goal = get_object_or_404(Goal.objects.filter(student=student), pk=goal_id)
    error = ""
    try:
        set_steps(goal=goal, titles=(request.POST.get("steps") or "").splitlines())
    except ValidationError as exc:
        error = "; ".join(exc.messages)

    response = _goals_block(request, student)
    if error:
        response.status_code = 422
    return response


@login_required
@role_required("student")
@require_http_methods(["POST"])
def goal_step_toggle(request, step_id):
    """
    Отметить шаг сделанным. И снять отметку — тоже сам.

    Никто, кроме ученика, шаги не отмечает: путь его, и цена отметки в том,
    что она правдива.
    """
    student = _own_student(request)
    step = get_object_or_404(GoalStep.objects.filter(goal__student=student), pk=step_id)
    toggle_step(step)
    return _goals_block(request, student)


@login_required
@role_required("student")
@require_http_methods(["POST"])
def hero_choose(request):
    """Сменить спутника. Мелочь, но выбранное своей рукой держится дольше."""
    student = _own_student(request)
    value = request.POST.get("hero")
    if value in dict(Hero.choices):
        student.hero = value
        student.save(update_fields=["hero", "updated_at"])
    return _goals_block(request, student)


@login_required
@role_required("student")
@require_http_methods(["POST"])
def homework_mark(request, homework_id):
    """
    Отметка «сделал» — ставит и снимает сам ученик.

    Отвечаем всей доской, а не одной карточкой: нажатие переносит задание
    из «Сделать» в «На проверке», а перенос между разделами подменой
    одной карточки не изобразить — она осталась бы стоять там же,
    и выглядело бы это ровно как раньше, когда кнопка ничего не делала.
    """
    student = _own_student(request)
    homework = get_object_or_404(
        Homework.objects.filter(lesson__group__memberships__student=student).distinct(),
        pk=homework_id,
    )
    error = ""
    try:
        mark_done(
            homework=homework, student=student, done=request.POST.get("done") == "1"
        )
    except ValidationError as exc:
        error = "; ".join(exc.messages)

    return render(
        request,
        "cabinet/student/partials/homework_board.html",
        {
            "board": homework_board(student, module=current_module(request.organization)),
            "error": error,
        },
    )


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
