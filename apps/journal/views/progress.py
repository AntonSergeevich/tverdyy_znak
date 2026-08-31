"""
Путь ученика: баллы по модулям и состояние по дням.

Отметки «как день» ученик ставил в пустоту: их не видел никто — ни
наставник, ни педагог. Показатель, который никто не смотрит, бесполезен
вдвойне: ребёнок тратит на него внимание, а ответа не получает.

Здесь эти отметки наконец видны — и рядом с тем, что происходило в те же
дни: баллами по модулям и целями. Смысл не в контроле, а в разговоре: две
тяжёлые недели подряд у ровного по баллам ученика — это повод спросить, а
не повод вызвать родителей.

Скрытые цели сюда не попадают — ни при каких обстоятельствах. Это
обещание, данное ребёнку, и режим «наставник посмотрит» его не отменяет.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.journal.access import accessible_students, get_student_or_403
from apps.journal.models import (
    AcademicYear,
    Goal,
    GoalStatus,
    GoalVisibility,
    Module,
    ModuleKind,
    ModuleResult,
    MoodEntry,
)
from apps.journal.services.goals import path_of
from apps.journal.services.grading import get_scale

MOOD_DAYS = 21
ZERO = Decimal("0.00")


def _year_modules() -> list[Module]:
    """
    Модули текущего года — вехи пути.

    Каникулярные недели сюда не идут: на них назначают консультации тем,
    кто добирает баллы, но путём они не являются, а в ряду вех создают
    пустые кружки без смысла.
    """
    year = (
        AcademicYear.objects.filter(is_current=True).first()
        or AcademicYear.objects.order_by("-starts_on").first()
    )
    if year is None:
        return []
    return list(
        Module.objects.filter(academic_year=year, kind=ModuleKind.MODULE).order_by("starts_on")
    )


def _mood_ribbon(entries, *, days: int = MOOD_DAYS) -> list[dict]:
    """
    Лента настроения за последние дни: по клетке на день, пропуски видны.

    Пропуск — это тоже сведение: штрафов за него нет, но полоса из пробелов
    говорит не меньше, чем полоса из «тяжело».
    """
    today = timezone.localdate()
    by_day = {entry.day: entry for entry in entries}
    ribbon = []
    for shift in range(days - 1, -1, -1):
        day = today - dt.timedelta(days=shift)
        entry = by_day.get(day)
        ribbon.append(
            {
                "day": day,
                "value": entry.value if entry else None,
                "label": entry.get_value_display() if entry else "не отмечено",
                "note": entry.note if entry else "",
            }
        )
    return ribbon


def _module_track(student, modules) -> list[dict]:
    """Баллы по модулям — вехами на пути, в порядке учебного года."""
    rows = (
        ModuleResult.objects.filter(student=student, module__in=modules)
        .values("module_id")
        .annotate(total=Sum("total_points"), planned=Sum("planned_points"))
    )
    by_module = {row["module_id"]: row for row in rows}
    today = timezone.localdate()

    track = []
    for module in modules:
        row = by_module.get(module.id)
        total = (row or {}).get("total") or ZERO
        planned = (row or {}).get("planned") or ZERO
        track.append(
            {
                "module": module,
                "total": total,
                "planned": planned,
                "percent": int(round(total * 100 / planned)) if planned else 0,
                "is_current": module.starts_on <= today <= module.ends_on,
                "is_future": module.starts_on > today,
            }
        )
    return track


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
def progress_list(request):
    """Все свои ученики разом: путь по модулям и лента состояния."""
    organization = request.organization
    students = list(
        accessible_students(request.user, organization).order_by("last_name", "first_name")
    )
    modules = _year_modules()

    moods = MoodEntry.objects.filter(
        student__in=students, day__gte=timezone.localdate() - dt.timedelta(days=MOOD_DAYS)
    ).order_by("day")
    by_student: dict = {}
    for entry in moods:
        by_student.setdefault(entry.student_id, []).append(entry)

    rows = [
        {
            "student": student,
            "track": _module_track(student, modules),
            "ribbon": _mood_ribbon(by_student.get(student.id, [])),
        }
        for student in students
    ]

    return render(
        request,
        "cabinet/manage/progress.html",
        {
            "rows": rows,
            "modules": modules,
            "mood_days": MOOD_DAYS,
            "mood_choices": MoodEntry.Scale.choices,
            "scale": get_scale(organization),
        },
    )


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
def progress_student(request, student_id):
    """Один ученик подробно: модули, предметы, состояние, открытые цели."""
    organization = request.organization
    student = get_student_or_403(request.user, organization, student_id)
    modules = _year_modules()

    log_audit(action=AuditAction.VIEW_STUDENT, request=request, obj=student, scope="progress")

    results = (
        ModuleResult.objects.filter(student=student)
        .select_related("subject", "module")
        .order_by("module__starts_on", "subject__position")
    )
    by_module: dict = {}
    for result in results:
        by_module.setdefault(result.module_id, []).append(result)

    track = _module_track(student, modules)
    for row in track:
        row["results"] = by_module.get(row["module"].id, [])

    entries = list(
        MoodEntry.objects.filter(
            student=student, day__gte=timezone.localdate() - dt.timedelta(days=MOOD_DAYS)
        ).order_by("day")
    )

    # Только открытые цели. Скрытые не видит никто, и «наставнику можно» —
    # это ровно то исключение, из-за которого механика перестала бы работать.
    goals = list(
        Goal.objects.filter(
            student=student, status=GoalStatus.ACTIVE, visibility=GoalVisibility.OPEN
        ).prefetch_related("steps")
    )
    for goal in goals:
        goal.step_list = list(goal.steps.all())
        goal.path = path_of(goal)

    return render(
        request,
        "cabinet/manage/progress_student.html",
        {
            "student": student,
            "track": track,
            "ribbon": _mood_ribbon(entries),
            "entries": list(reversed(entries)),
            "goals": goals,
            "mood_days": MOOD_DAYS,
            "scale": get_scale(organization),
        },
    )
