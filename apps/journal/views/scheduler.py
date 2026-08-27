"""
Конструктор расписания.

Расписание составляется мышью: слева карточки педагогов, справа сетка
дней и времени. Карточку перетаскивают в клетку — появляется занятие,
а сама карточка остаётся на месте, чтобы того же педагога можно было
поставить и на следующий урок.

Всё сохраняется сразу, без кнопки «сохранить»: составление расписания
— это десятки мелких действий, и забытая кнопка стоила бы часа работы.
Каждое действие — отдельный запрос, ответ — обновлённая клетка.
"""
from __future__ import annotations

import datetime as dt

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.site_public.templatetags.public_extras import plural
from apps.journal.models import (
    Group,
    Lesson,
    Module,
    ModuleKind,
    Subject,
    SubjectKind,
    Teacher,
)

MANAGER_ROLES = ("admin", "owner", "platform_admin")

# Сетка дня. Совпадает с той, по которой центр уже живёт: 40-минутные
# уроки с переменами и обедом посередине.
SLOTS = [
    ("09:00", 20), ("09:30", 40), ("10:20", 40), ("11:10", 40),
    ("12:00", 40), ("12:50", 40), ("13:30", 30), ("14:10", 40), ("15:00", 40),
]
WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]


def _week_start(request) -> dt.date:
    raw = request.GET.get("week")
    if raw:
        try:
            day = dt.date.fromisoformat(raw)
            return day - dt.timedelta(days=day.weekday())
        except ValueError:
            pass
    today = timezone.localdate()
    return today - dt.timedelta(days=today.weekday())


def _module_for(organization, day: dt.date) -> Module | None:
    return (
        Module.objects.filter(
            academic_year__is_current=True, kind=ModuleKind.MODULE,
            starts_on__lte=day, ends_on__gte=day,
        ).first()
    )


@login_required
@role_required(*MANAGER_ROLES)
def builder(request):
    """Сетка недели и карточки педагогов рядом."""
    organization = request.organization
    monday = _week_start(request)
    days = [monday + dt.timedelta(days=i) for i in range(len(WEEKDAYS))]

    group_id = request.GET.get("group")
    groups = list(Group.objects.filter(academic_year__is_current=True).order_by("name"))
    group = next((g for g in groups if str(g.pk) == group_id), None) or (
        groups[0] if groups else None
    )

    lessons = {}
    if group is not None:
        for lesson in (
            Lesson.objects.filter(
                group=group, starts_at__date__gte=monday,
                starts_at__date__lte=days[-1],
            ).select_related("subject", "teacher__user")
        ):
            local = timezone.localtime(lesson.starts_at)
            lessons[(local.date().isoformat(), local.strftime("%H:%M"))] = lesson

    grid = []
    for time_label, duration in SLOTS:
        row = {"time": time_label, "duration": duration, "cells": []}
        for day in days:
            row["cells"].append(
                {
                    "day": day,
                    "time": time_label,
                    "duration": duration,
                    "key": f"{day.isoformat()}-{time_label.replace(':', '')}",
                    "lesson": lessons.get((day.isoformat(), time_label)),
                }
            )
        grid.append(row)

    return render(
        request,
        "cabinet/manage/schedule_builder.html",
        {
            "monday": monday,
            "sunday": days[-1],
            "days": list(zip(WEEKDAYS, days)),
            "grid": grid,
            "groups": groups,
            "group": group,
            "teachers": list(
                Teacher.objects.select_related("user").prefetch_related("subjects")
                .order_by("user__last_name")
            ),
            "subjects": list(
                Subject.objects.filter(
                    academic_year__is_current=True, kind=SubjectKind.ACADEMIC
                ).order_by("position", "name")
            ),
            "prev_week": monday - dt.timedelta(days=7),
            "next_week": monday + dt.timedelta(days=7),
            "module": _module_for(organization, monday),
            # Если неделя вне модуля, показываем куда идти, а не название
            # команды: этот экран открывает администратор центра.
            "nearest_module": _nearest_module(monday),
        },
    )


def _nearest_module(day: dt.date) -> Module | None:
    """Ближайший модуль, который начинается не раньше этой недели."""
    upcoming = (
        Module.objects.filter(
            academic_year__is_current=True, kind=ModuleKind.MODULE, ends_on__gte=day
        )
        .order_by("starts_on")
        .first()
    )
    return upcoming or Module.objects.filter(
        academic_year__is_current=True, kind=ModuleKind.MODULE
    ).order_by("-starts_on").first()


def _slot_html(request, lesson, group):
    """Клетка после изменения — ровно то, что теперь лежит в базе."""
    local = timezone.localtime(lesson.starts_at)
    return render(
        request,
        "cabinet/manage/partials/slot.html",
        {
            "cell": {
                "day": local.date(),
                "time": f"{local:%H:%M}",
                "duration": lesson.duration_minutes,
                "key": f"{local.date().isoformat()}-{local:%H%M}",
                "lesson": lesson,
            },
            "group": group,
        },
    )


def _busy_elsewhere(teacher, starts_at, group):
    """Тот же педагог, то же время, другая группа — раздвоиться он не может."""
    return (
        Lesson.objects.filter(teacher=teacher, starts_at=starts_at)
        .exclude(group=group)
        .select_related("group", "subject")
        .first()
    )


def _assign_teacher(request, lesson, teacher, group):
    """
    Поставить педагога к уже назначенному занятию, не трогая предмет.

    Так наставник встаёт на утренний круг и рефлексию: за этими блоками
    не закреплён «свой» предмет, но человек, который их ведёт, есть.
    Так же назначается педагог занятиям, перенесённым из файла с
    расписанием — там колонка педагога пустая.
    """
    conflict = _busy_elsewhere(teacher, lesson.starts_at, group)
    if conflict is not None:
        return JsonResponse(
            {
                "error": (
                    f"{teacher.short_name} в это время уже ведёт "
                    f"{conflict.subject.name} у группы «{conflict.group.name}»."
                )
            },
            status=409,
        )

    lesson.teacher = teacher
    lesson.save(update_fields=["teacher", "updated_at"])
    log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=lesson,
              change="lesson_teacher_assigned")
    return _slot_html(request, lesson, group)


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def slot_set(request):
    """
    Поставить занятие в клетку.

    Пустая клетка — заводится занятие по предмету педагога. Занятая —
    педагог назначается тому, что там уже стоит, а предмет не трогается:
    расписание чаще всего уже набрано, не хватает только людей.
    """
    organization = request.organization
    group = get_object_or_404(Group.objects.all(), pk=request.POST.get("group"))
    teacher = get_object_or_404(Teacher.objects.all(), pk=request.POST.get("teacher"))
    subject_id = request.POST.get("subject")

    try:
        day = dt.date.fromisoformat(request.POST.get("day", ""))
        start = dt.time.fromisoformat(request.POST.get("time", "") + ":00")
    except ValueError:
        return JsonResponse({"error": "Неверные дата или время."}, status=400)

    module = _module_for(organization, day)
    if module is None:
        return JsonResponse(
            {"error": f"{day:%d.%m.%Y} не входит ни в один учебный модуль."}, status=400
        )

    duration = int(request.POST.get("duration") or 40)
    starts_at = timezone.make_aware(dt.datetime.combine(day, start), organization.tzinfo)
    existing = Lesson.objects.filter(group=group, starts_at=starts_at).first()

    # Клетка занята — значит, педагога ставят к уже назначенному занятию,
    # а не заводят новое. Предмет остаётся: так наставник встаёт на
    # утренний круг и рефлексию, за которыми не закреплён «свой» предмет,
    # и так же получают педагога занятия, перенесённые из файла Алины.
    # Сменить предмет в клетке можно, убрав занятие крестиком.
    if existing is not None:
        return _assign_teacher(request, existing, teacher, group)

    # Предмет: явно выбранный или единственный у этого педагога. Угадывать
    # из нескольких нельзя — получится «химия» вместо «биологии».
    subject = None
    if subject_id:
        subject = get_object_or_404(Subject.objects.all(), pk=subject_id)
    else:
        options = list(teacher.subjects.all())
        if len(options) == 1:
            subject = options[0]

    if subject is None:
        if not teacher.subjects.exists():
            return JsonResponse(
                {
                    "error": (
                        f"У {teacher.short_name} не заданы предметы. Откройте карточку "
                        "педагога и укажите, что он ведёт, — либо перетащите его "
                        "на уже стоящее занятие, чтобы назначить педагогом."
                    )
                },
                status=400,
            )
        return JsonResponse(
            {"error": "У педагога несколько предметов — выберите, какой ставим."},
            status=400,
        )

    conflict = _busy_elsewhere(teacher, starts_at, group)
    if conflict is not None:
        return JsonResponse(
            {
                "error": (
                    f"{teacher.short_name} в это время уже ведёт "
                    f"{conflict.subject.name} у группы «{conflict.group.name}»."
                )
            },
            status=409,
        )

    with transaction.atomic():
        lesson = Lesson.objects.create(
            organization=organization, module=module, subject=subject,
            group=group, teacher=teacher, starts_at=starts_at,
            duration_minutes=duration,
        )

    log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=lesson,
              change="lesson_scheduled")
    return _slot_html(request, lesson, group)


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def slot_clear(request, lesson_id):
    """Убрать занятие из клетки. Баллы за него, если были, уйдут вместе с ним."""
    lesson = get_object_or_404(
        Lesson.objects.select_related("group", "subject"), pk=lesson_id
    )
    local = timezone.localtime(lesson.starts_at)
    group = lesson.group
    key = f"{local.date().isoformat()}-{local:%H%M}"

    graded = hasattr(lesson, "grade_item")
    if graded and request.POST.get("force") != "1":
        return JsonResponse(
            {
                "error": (
                    "За это занятие уже выставлялись баллы. "
                    "Удаление уберёт и их — подтвердите ещё раз."
                ),
                "needs_force": True,
            },
            status=409,
        )

    lesson.delete()
    log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=lesson,
              change="lesson_unscheduled")
    return render(
        request,
        "cabinet/manage/partials/slot.html",
        {
            "cell": {
                "day": local.date(),
                "time": f"{local:%H:%M}",
                "duration": lesson.duration_minutes,
                "key": key,
                "lesson": None,
            },
            "group": group,
        },
    )


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def week_copy(request):
    """
    Скопировать неделю на следующую.

    Расписание в семестре повторяется, и перетаскивать сорок занятий
    заново — работа, которую не должен делать человек.
    """
    organization = request.organization
    group = get_object_or_404(Group.objects.all(), pk=request.POST.get("group"))
    monday = _week_start(request)
    try:
        weeks = max(1, min(12, int(request.POST.get("weeks") or 1)))
    except ValueError:
        weeks = 1

    source = list(
        Lesson.objects.filter(
            group=group, starts_at__date__gte=monday,
            starts_at__date__lte=monday + dt.timedelta(days=6),
        ).select_related("subject", "teacher")
    )
    created = skipped = 0
    with transaction.atomic():
        for shift in range(1, weeks + 1):
            offset = dt.timedelta(weeks=shift)
            for lesson in source:
                starts_at = lesson.starts_at + offset
                day = timezone.localtime(starts_at).date()
                module = _module_for(organization, day)
                if module is None:
                    skipped += 1
                    continue
                if Lesson.objects.filter(group=group, starts_at=starts_at).exists():
                    skipped += 1
                    continue
                Lesson.objects.create(
                    organization=organization, module=module, subject=lesson.subject,
                    group=group, teacher=lesson.teacher, starts_at=starts_at,
                    duration_minutes=lesson.duration_minutes, room=lesson.room,
                )
                created += 1

    return JsonResponse({"created": created, "skipped": skipped})


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def week_clear(request):
    """
    Убрать все занятия недели у группы — для полной перестройки.

    Спрашиваем дважды, если за какие-то занятия уже выставлены баллы:
    расписание переставить не жалко, а работу учеников — жалко.
    """
    group = get_object_or_404(Group.objects.all(), pk=request.POST.get("group"))
    monday = _week_start(request)
    lessons = Lesson.objects.filter(
        group=group,
        starts_at__date__gte=monday,
        starts_at__date__lte=monday + dt.timedelta(days=6),
    )

    total = lessons.count()
    if not total:
        return JsonResponse({"removed": 0, "graded": 0})

    graded = lessons.filter(grade_item__isnull=False).count()
    if graded and request.POST.get("force") != "1":
        return JsonResponse(
            {
                "error": (
                    f"На этой неделе {graded} "
                    f"{plural(graded, 'занятие,занятия,занятий')}, "
                    "за которые уже выставлены баллы. "
                    "Очистка уберёт и их — подтвердите ещё раз."
                ),
                "needs_force": True,
            },
            status=409,
        )

    with transaction.atomic():
        lessons.delete()

    log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=group,
              change="week_cleared")
    return JsonResponse({"removed": total, "graded": graded})
