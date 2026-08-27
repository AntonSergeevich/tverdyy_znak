"""
Справочник предметов.

Список не зашит в код: появится робототехника — её заводят в кабинете,
а не ждут выката. Удаление возможно, только пока предмет ни за что не
держит: занятия и баллы, привязанные к нему, важнее удобства уборки.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.journal.forms import DeleteConfirmForm, SubjectForm
from apps.journal.models import AcademicYear, GradeItem, Lesson, Subject, SubjectKind

MANAGER_ROLES = ("admin", "owner", "platform_admin")


@login_required
@role_required(*MANAGER_ROLES)
def subjects(request):
    rows = (
        Subject.objects.filter(academic_year__is_current=True)
        .annotate(lessons_count=Count("lessons", distinct=True))
        .order_by("kind", "position", "name")
    )
    academic = [row for row in rows if row.kind == SubjectKind.ACADEMIC]
    return render(
        request,
        "cabinet/manage/subjects.html",
        {
            "academic": academic,
            "activities": [row for row in rows if row.kind != SubjectKind.ACADEMIC],
            "total_hours": sum(row.weekly_hours for row in academic),
        },
    )


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def subject_create(request):
    year = AcademicYear.objects.filter(is_current=True).first()
    if year is None:
        messages.error(request, "Сначала должен быть заведён текущий учебный год.")
        return redirect("cabinet:subjects")

    form = SubjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        subject = form.save(commit=False)
        subject.organization = request.organization
        subject.academic_year = year
        subject.save()
        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=subject,
                  change="subject_created")
        messages.success(request, f"«{subject.name}» добавлен.")
        return redirect("cabinet:subjects")

    return render(request, "cabinet/manage/subject_form.html", {"form": form, "mode": "create"})


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def subject_edit(request, subject_id):
    subject = get_object_or_404(Subject.objects.all(), pk=subject_id)
    form = SubjectForm(request.POST or None, instance=subject)

    if request.method == "POST" and form.is_valid():
        form.save()
        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=subject,
                  change="subject_edited")
        messages.success(request, "Сохранено.")
        return redirect("cabinet:subjects")

    return render(
        request,
        "cabinet/manage/subject_form.html",
        {"form": form, "mode": "edit", "subject": subject},
    )


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def subject_delete(request, subject_id):
    subject = get_object_or_404(Subject.objects.all(), pk=subject_id)

    # Предмет, за который цепляются занятия или баллы, удалять нельзя:
    # вместе с ним ушла бы часть журнала. Такой предмет убирают из
    # расписания, а запись о прошлом остаётся.
    lessons = Lesson.objects.filter(subject=subject).count()
    items = GradeItem.objects.filter(subject=subject).count()
    blocked = lessons or items

    form = DeleteConfirmForm(request.POST or None, expected=subject.name)
    if request.method == "POST" and not blocked and form.is_valid():
        name = subject.name
        subject.delete()
        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=subject,
                  change="subject_deleted")
        messages.success(request, f"«{name}» удалён.")
        return redirect("cabinet:subjects")

    return render(
        request,
        "cabinet/manage/subject_delete.html",
        {
            "form": form,
            "subject": subject,
            "lessons": lessons,
            "items": items,
            "blocked": blocked,
        },
    )
