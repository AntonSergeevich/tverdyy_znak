"""
Люди в кабинете: ученики, родители, педагоги, сотрудники.

Доступы выдаёт администратор — сами люди не регистрируются. Поэтому
каждая форма создания заканчивается одним и тем же: окном с логином,
паролем и ссылкой на вход, которое можно скопировать одной кнопкой
и отправить человеку в мессенджер.

Пароль показывается ровно один раз: в базе он хранится хэшем, и это
правильно. Забыли — администратор выдаёт новый в один клик.
"""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.journal.forms import (
    DeleteConfirmForm,
    PaymentForm,
    StaffForm,
    StudentEditForm,
    StudentForm,
    TeacherEditForm,
    TeacherForm,
)
from apps.journal.models import (
    Goal,
    GoalStatus,
    GoalVisibility,
    GroupMembership,
    Lesson,
    ModuleResult,
    Parent,
    Payment,
    Student,
    StudentParent,
    StudentStatus,
    Teacher,
)
from apps.journal.services import onboarding
from apps.journal.services.grading import get_scale
from apps.journal.views.parent import current_module

MANAGER_ROLES = ("admin", "owner", "platform_admin")
# Заводить сотрудников может только владелец: администратор, который
# может завести себе второго администратора, — это не роль, а дыра.
OWNER_ROLES = ("owner", "platform_admin")


def _login_url(request) -> str:
    return request.build_absolute_uri(reverse("accounts:login"))


def _credentials_response(request, credentials, *, back_url: str, **extra):
    """
    Страница с доступами.

    Фрагмент вынесен отдельно: через HTMX сюда же приходит сброс пароля,
    и дублировать разметку ради одной обёртки не нужно.
    """
    template = (
        "cabinet/manage/partials/credentials.html"
        if request.headers.get("HX-Request")
        else "cabinet/manage/credentials.html"
    )
    return render(
        request,
        template,
        {
            "credentials": credentials,
            "login_url": _login_url(request),
            "back_url": back_url,
            **extra,
        },
    )


# ─── Ученики ────────────────────────────────────────────────────────────────

@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def student_create(request):
    organization = request.organization
    form = StudentForm(request.POST or None, organization=organization)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            user, credentials = onboarding.issue_account(
                organization=organization,
                role=Role.STUDENT,
                last_name=data["last_name"],
                first_name=data["first_name"],
                middle_name=data["middle_name"],
                phone=data["phone"],
                email=data["email"],
            )
            student = Student.objects.create(
                organization=organization,
                user=user,
                last_name=data["last_name"],
                first_name=data["first_name"],
                middle_name=data["middle_name"],
                grade_level=data["grade_level"],
                birth_date=data.get("birth_date"),
                enrolled_on=data.get("enrolled_on"),
                status=data.get("status") or StudentStatus.ENROLLED,
                note=data.get("note", ""),
            )
            if data.get("group"):
                GroupMembership.objects.create(
                    organization=organization, group=data["group"], student=student
                )
            parent_credentials = _maybe_create_parent(request, student, data)

        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=student,
                  change="student_created")
        messages.success(request, f"{student.short_name} добавлен.")
        return _credentials_response(
            request, credentials,
            back_url=reverse("cabinet:students"),
            extra_credentials=parent_credentials,
            student=student,
        )

    return render(request, "cabinet/manage/student_form.html", {"form": form, "mode": "create"})


def _maybe_create_parent(request, student: Student, data: dict):
    """Родитель заводится вместе с ребёнком, если его назвали."""
    if not (data.get("parent_last_name") and data.get("parent_first_name")):
        return None

    organization = request.organization
    user, credentials = onboarding.issue_account(
        organization=organization,
        role=Role.PARENT,
        last_name=data["parent_last_name"],
        first_name=data["parent_first_name"],
        phone=data.get("parent_phone", ""),
        email=data.get("parent_email", ""),
    )
    parent = Parent.objects.create(
        organization=organization, user=user,
        last_name=data["parent_last_name"], first_name=data["parent_first_name"],
        phone=data.get("parent_phone", ""), email=data.get("parent_email", ""),
    )
    StudentParent.objects.create(
        organization=organization, student=student, parent=parent, is_primary_contact=True
    )
    return credentials


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def student_edit(request, student_id):
    student = get_object_or_404(Student.objects.all(), pk=student_id)
    form = StudentEditForm(request.POST or None, instance=student)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            student = form.save()
            _sync_group(request, student, form.cleaned_data.get("group"))
        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=student,
                  change="student_edited")
        messages.success(request, "Карточка сохранена.")
        return redirect("cabinet:student_card", student_id=student.pk)

    return render(
        request,
        "cabinet/manage/student_form.html",
        {"form": form, "mode": "edit", "student": student},
    )


def _sync_group(request, student: Student, group) -> None:
    """Группа у ученика одна: смена группы — это переход, а не добавление."""
    current = student.group_memberships.select_related("group").first()
    if current and current.group == group:
        return
    student.group_memberships.all().delete()
    if group is not None:
        GroupMembership.objects.create(
            organization=request.organization, group=group, student=student
        )


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def student_delete(request, student_id):
    student = get_object_or_404(Student.objects.all(), pk=student_id)
    form = DeleteConfirmForm(request.POST or None, expected=student.last_name)

    if request.method == "POST" and form.is_valid():
        # Мягкое удаление: ученика можно вернуть посреди года (ТЗ 9.5).
        student.delete()
        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=student,
                  change="student_deleted")
        messages.success(
            request, f"{student.short_name} удалён. Восстановить можно в списке удалённых."
        )
        return redirect("cabinet:students")

    return render(
        request,
        "cabinet/manage/confirm_delete.html",
        {
            "form": form,
            "object_label": student.full_name,
            "expected": student.last_name,
            "back_url": reverse("cabinet:student_card", args=[student.pk]),
            "what": "ученика",
        },
    )


@login_required
@role_required(*MANAGER_ROLES)
def student_card(request, student_id):
    """Карточка ученика: успеваемость, расписание, оплаты, контакты."""
    organization = request.organization
    student = get_object_or_404(
        Student.objects.select_related("user").prefetch_related(
            Prefetch("parent_links", queryset=StudentParent.objects.select_related("parent__user")),
            "group_memberships__group",
        ),
        pk=student_id,
    )
    module = current_module(organization)
    results = (
        ModuleResult.objects.filter(student=student, module=module)
        .select_related("subject")
        .order_by("subject__position", "subject__name")
        if module
        else []
    )
    lessons = (
        Lesson.objects.filter(group__memberships__student=student)
        .select_related("subject", "teacher__user", "group")
        .order_by("starts_at")
        .distinct()
    )
    log_audit(action=AuditAction.VIEW_STUDENT, request=request, obj=student)

    return render(
        request,
        "cabinet/manage/student_card.html",
        {
            "student": student,
            "module": module,
            "results": list(results),
            "scale": get_scale(organization),
            "payments": list(
                Payment.objects.filter(student=student).order_by("-period_start")[:24]
            ),
            "payment_form": PaymentForm(),
            "upcoming": list(lessons.filter(starts_at__gte=timezone.now())[:10]),
            # Скрытые цели ученика администратору не показываем: механика
            # личных целей держится на том, что «скрытая» значит скрытая.
            "goals": list(
                Goal.objects.filter(
                    student=student, status=GoalStatus.ACTIVE, visibility=GoalVisibility.OPEN
                ).select_related("subject")
            ),
        },
    )


# ─── Педагоги ───────────────────────────────────────────────────────────────

@login_required
@role_required(*MANAGER_ROLES)
def teachers(request):
    rows = (
        Teacher.objects.select_related("user")
        .prefetch_related("subjects")
        .order_by("user__last_name")
    )
    return render(request, "cabinet/manage/teachers.html", {"teachers": list(rows)})


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def teacher_create(request):
    organization = request.organization
    form = TeacherForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            user, credentials = onboarding.issue_account(
                organization=organization,
                role=Role.TEACHER,
                last_name=data["last_name"],
                first_name=data["first_name"],
                middle_name=data["middle_name"],
                phone=data["phone"],
                email=data["email"],
            )
            teacher = Teacher.objects.create(
                organization=organization, user=user,
                hourly_rate=data["hourly_rate"], public_title=data["public_title"],
            )
            teacher.subjects.set(data["subjects"])

        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=teacher,
                  change="teacher_created")
        messages.success(request, f"{teacher.short_name} добавлен.")
        return _credentials_response(request, credentials, back_url=reverse("cabinet:teachers"))

    return render(request, "cabinet/manage/teacher_form.html", {"form": form, "mode": "create"})


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def teacher_edit(request, teacher_id):
    teacher = get_object_or_404(Teacher.objects.select_related("user"), pk=teacher_id)
    form = TeacherEditForm(request.POST or None, instance=teacher)

    if request.method == "POST" and form.is_valid():
        form.save()
        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=teacher,
                  change="teacher_edited")
        messages.success(request, "Сохранено.")
        return redirect("cabinet:teachers")

    return render(
        request,
        "cabinet/manage/teacher_form.html",
        {"form": form, "mode": "edit", "teacher": teacher},
    )


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def teacher_delete(request, teacher_id):
    teacher = get_object_or_404(Teacher.objects.select_related("user"), pk=teacher_id)
    form = DeleteConfirmForm(request.POST or None, expected=teacher.user.last_name)

    if request.method == "POST" and form.is_valid():
        teacher.delete()
        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=teacher,
                  change="teacher_deleted")
        messages.success(request, "Педагог удалён. Занятия и баллы сохранены.")
        return redirect("cabinet:teachers")

    return render(
        request,
        "cabinet/manage/confirm_delete.html",
        {
            "form": form,
            "object_label": teacher.user.full_name,
            "expected": teacher.user.last_name,
            "back_url": reverse("cabinet:teachers"),
            "what": "педагога",
        },
    )


# ─── Сотрудники ─────────────────────────────────────────────────────────────

@login_required
@role_required(*OWNER_ROLES)
@require_http_methods(["GET", "POST"])
def staff_create(request):
    form = StaffForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        user, credentials = onboarding.issue_account(
            organization=request.organization,
            role=data["role"],
            last_name=data["last_name"],
            first_name=data["first_name"],
            middle_name=data["middle_name"],
            phone=data["phone"],
            email=data["email"],
        )
        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=user,
                  change="staff_created", role=data["role"])
        messages.success(request, f"{user.full_name} добавлен.")
        return _credentials_response(request, credentials, back_url=reverse("cabinet:staff"))

    return render(request, "cabinet/manage/staff_form.html", {"form": form})


@login_required
@role_required(*OWNER_ROLES)
def staff(request):
    from apps.accounts.models import Membership, STAFF_ROLES

    rows = (
        Membership.objects.filter(organization=request.organization, role__in=STAFF_ROLES)
        .select_related("user")
        .order_by("user__last_name")
    )
    return render(request, "cabinet/manage/staff.html", {"memberships": list(rows)})


# ─── Общий сброс пароля ─────────────────────────────────────────────────────

@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def password_reset(request, user_id):
    """
    Новый пароль вместо забытого.

    Администратор не может сбросить пароль тому, кто главнее его:
    иначе роль администратора превращается в способ захватить владельца.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = get_object_or_404(
        User.objects.filter(memberships__organization=request.organization).distinct(), pk=user_id
    )
    is_owner = request.user.has_role(request.organization, Role.OWNER) or request.user.is_superuser
    target_is_privileged = user.memberships.filter(
        organization=request.organization, role__in=(Role.OWNER, Role.PLATFORM_ADMIN)
    ).exists()
    if target_is_privileged and not is_owner:
        raise PermissionDenied("Сбросить пароль владельцу может только владелец.")

    credentials = onboarding.reset_password(user)
    log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=user,
              change="password_reset")
    return _credentials_response(
        request, credentials, back_url=request.META.get("HTTP_REFERER") or reverse("cabinet:home")
    )


# ─── Оплаты ─────────────────────────────────────────────────────────────────

@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def payment_create(request, student_id):
    """Начисление родителю. Эквайринга нет — администратор ведёт вручную."""
    student = get_object_or_404(Student.objects.all(), pk=student_id)
    form = PaymentForm(request.POST)
    if form.is_valid():
        payment = form.save(commit=False)
        payment.organization = request.organization
        payment.student = student
        payment.save()
        messages.success(request, f"Начислено {payment.amount} ₽.")
    else:
        # Ошибки формы показываем текстом: отдельная страница ради одной
        # опечатки в сумме — лишний шаг там, где хватает подсказки.
        for field, errors in form.errors.items():
            messages.error(request, f"{field}: {errors[0]}")
    return redirect("cabinet:student_card", student_id=student.pk)
