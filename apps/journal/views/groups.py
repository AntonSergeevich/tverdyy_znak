"""
Группы: семейный класс, курсы подготовки к ОГЭ, клубы.

Раздела не было вовсе: группа заводилась один раз при создании
организации, а новые — только через техническую админку. Курсы
(«ОГЭ: математика», «6 класс: русский язык») завести владелец не мог,
хотя ведёт их центр и расписание, баллы и домашнее для них нужны те же.

Здесь всё, что нужно руководителю: завести группу, поправить название,
собрать состав. Ученик может быть сразу в нескольких группах.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.journal import undo
from apps.journal.forms import GroupForm
from apps.journal.models import (
    AcademicYear,
    GradeItem,
    Group,
    GroupKind,
    GroupMembership,
    Lesson,
    Student,
    ThematicPlan,
)

MANAGER_ROLES = ("admin", "owner", "platform_admin")


def _current_year():
    return AcademicYear.objects.filter(is_current=True).first()


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def groups(request):
    year = _current_year()
    form = GroupForm(
        request.POST or None, organization=request.organization, academic_year=year
    )

    if request.method == "POST":
        if year is None:
            messages.error(request, "Сначала заведите учебный год.")
            return redirect("cabinet:groups")
        if form.is_valid():
            group = form.save(commit=False)
            group.organization = request.organization
            group.academic_year = year
            group.save()
            log_audit(
                action=AuditAction.PERMISSION_CHANGED, request=request, obj=group,
                change="group_created",
            )
            messages.success(request, f"Группа «{group.name}» заведена. Добавьте в неё учеников.")
            return redirect("cabinet:group_card", group_id=group.pk)

    rows = (
        Group.objects.filter(academic_year=year)
        .annotate(
            members=Count("memberships", distinct=True),
            lessons_count=Count("lessons", distinct=True),
        )
        # Семейный класс — первым: это основа центра, курсы и клубы — к нему.
        .annotate(
            kind_order=Case(
                When(kind=GroupKind.FAMILY_CLASS, then=Value(0)),
                When(kind=GroupKind.COURSE, then=Value(1)),
                default=Value(2), output_field=IntegerField(),
            )
        )
        .order_by("kind_order", "name")
        if year
        else Group.objects.none()
    )
    return render(
        request, "cabinet/manage/groups.html",
        {"groups": list(rows), "form": form, "year": year},
    )


def _card_context(group, **extra) -> dict:
    members = list(
        Student.objects.filter(group_memberships__group=group)
        .order_by("last_name", "first_name")
        .distinct()
    )
    candidates = list(
        Student.objects.exclude(group_memberships__group=group)
        .order_by("last_name", "first_name")
    )
    return {
        "group": group,
        "members": members,
        "candidates": candidates,
        "lessons_count": Lesson.objects.filter(group=group).count(),
        **extra,
    }


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def group_card(request, group_id):
    group = get_object_or_404(Group.objects.all(), pk=group_id)
    form = GroupForm(
        request.POST or None, instance=group,
        organization=request.organization, academic_year=group.academic_year,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        log_audit(
            action=AuditAction.PERMISSION_CHANGED, request=request, obj=group,
            change="group_edited",
        )
        messages.success(request, "Группа сохранена.")
        return redirect("cabinet:group_card", group_id=group.pk)
    return render(request, "cabinet/manage/group_card.html", _card_context(group, form=form))


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def group_members_add(request, group_id):
    """Добавить в группу сразу нескольких — набирать курс по одному долго."""
    group = get_object_or_404(Group.objects.all(), pk=group_id)
    chosen = Student.objects.filter(pk__in=request.POST.getlist("students")).exclude(
        group_memberships__group=group
    )
    added = 0
    with transaction.atomic():
        for student in chosen:
            GroupMembership.objects.create(
                organization=request.organization, group=group, student=student
            )
            added += 1
    if added:
        log_audit(
            action=AuditAction.PERMISSION_CHANGED, request=request, obj=group,
            change="group_members_added", count=added,
        )
        if request.POST.get("undo") == "1":
            messages.success(request, "Вернули в группу.")
        else:
            messages.success(request, f"Добавлено в группу: {added}.")
    else:
        messages.error(request, "Никто не выбран — отметьте учеников в списке.")
    return redirect("cabinet:group_card", group_id=group.pk)


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def group_member_remove(request, group_id, student_id):
    """
    Убрать ученика из группы.

    Баллы, выставленные ему в этой группе, не трогаем: они записаны за ним,
    а не за членством, и в итогах модуля остаются. Убирается только место
    в списке группы — с новых занятий его больше не видно.
    """
    group = get_object_or_404(Group.objects.all(), pk=group_id)
    student = get_object_or_404(Student.objects.all(), pk=student_id)
    GroupMembership.objects.filter(group=group, student=student).delete()
    log_audit(
        action=AuditAction.PERMISSION_CHANGED, request=request, obj=group,
        change="group_member_removed", student=str(student.pk),
    )
    # Без «Вы уверены?»: убрали сразу, а вернуть можно одной кнопкой —
    # членство восстанавливается заново, баллы и так никуда не уходили.
    undo.offer(
        request,
        f"{student.short_name} больше не в группе «{group.name}».",
        reverse("cabinet:group_members_add", args=[group.pk]),
        {"students": student.pk, "undo": 1},
    )
    return redirect("cabinet:group_card", group_id=group.pk)


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def group_delete(request, group_id):
    """
    Удалить группу — только пустую по расписанию.

    Группа без занятий — это опечатка или передумали: удалить её не жалко,
    состав просто распускается. Группа с занятиями — это уже журнал,
    баллы и домашние задания: удаление унесло бы их каскадом, а оценки по
    ТЗ 9.5 физически терять нельзя. Такую группу не удаляем и говорим почему.
    """
    group = get_object_or_404(Group.objects.all(), pk=group_id)
    # all_objects: удалённые мягко работы и планы каскад тоже снёс бы.
    attached = [
        (Lesson.all_objects.filter(group=group).count(), "занятия в расписании"),
        (GradeItem.all_objects.filter(group=group).count(), "работы модуля с баллами"),
        (ThematicPlan.all_objects.filter(group=group).count(), "КТП"),
    ]
    attached = [f"{label} ({count})" for count, label in attached if count]
    if attached:
        messages.error(
            request,
            f"У группы «{group.name}» есть {', '.join(attached)}. Удаление унесло "
            "бы их вместе с баллами, поэтому такую группу удалить нельзя. Если "
            "курс закончился, просто уберите из неё учеников.",
        )
        return redirect("cabinet:group_card", group_id=group.pk)

    name = group.name
    with transaction.atomic():
        GroupMembership.objects.filter(group=group).delete()
        log_audit(
            action=AuditAction.PERMISSION_CHANGED, request=request, obj=group,
            change="group_deleted", name=name,
        )
        group.delete()
    messages.success(request, f"Группа «{name}» удалена.")
    return redirect("cabinet:groups")
