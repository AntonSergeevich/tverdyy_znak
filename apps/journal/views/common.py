"""Общий вход в кабинет: маршрутизация по роли."""
from __future__ import annotations

import datetime as dt
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.accounts.models import ORG_MANAGER_ROLES, Role
from apps.journal.access import accessible_lessons


@login_required
def home(request):
    organization = request.organization
    user = request.user
    if user.is_superuser or user.has_role(organization, *ORG_MANAGER_ROLES, Role.PLATFORM_ADMIN):
        return redirect("cabinet:dashboard")
    if user.has_role(organization, Role.TEACHER):
        return redirect("cabinet:teacher_today")
    if user.has_role(organization, Role.PARENT):
        return redirect("cabinet:parent_home")
    if user.has_role(organization, Role.STUDENT):
        return redirect("cabinet:student_home")
    return render(request, "cabinet/no_role.html", status=403)


@login_required
def schedule(request):
    """
    Расписание на неделю — одна страница для всех ролей.

    Что видно, решает `accessible_lessons`: педагог — свои занятия,
    родитель — занятия своих детей, ученик — свои, администратор — все.
    Никакой отдельной фильтрации здесь нет, иначе правила разъедутся.
    """
    organization = request.organization
    try:
        offset = int(request.GET.get("n", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(-52, min(52, offset))

    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)

    lessons = (
        accessible_lessons(request.user, organization)
        .filter(starts_at__date__gte=monday, starts_at__date__lte=sunday)
        .distinct()
        .order_by("starts_at")
    )

    # Группируем по дням в шаблоне неудобно, а по датам — нельзя: пустые дни
    # тоже нужны, иначе неделя выглядит рваной.
    by_day: dict[dt.date, list] = {monday + timedelta(days=i): [] for i in range(7)}
    for lesson in lessons:
        by_day.setdefault(lesson.local_date, []).append(lesson)

    return render(
        request,
        "cabinet/schedule.html",
        {
            "days": [
                {"date": day, "is_today": day == today, "lessons": items}
                for day, items in sorted(by_day.items())
            ],
            "monday": monday,
            "sunday": sunday,
            "offset": offset,
            "has_lessons": any(by_day.values()),
            "external_url": organization.schedule_url,
        },
    )
