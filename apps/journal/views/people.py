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

from dataclasses import asdict

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.accounts.models import Membership, Role, STAFF_ROLES
from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.journal.forms import (
    DeleteConfirmForm,
    ParentInviteForm,
    PaymentForm,
    StaffForm,
    StaffIdentityForm,
    StudentEditForm,
    StudentForm,
    TeacherEditForm,
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
from apps.journal.services import duplicates
from apps.journal.services import onboarding
from apps.journal.services import staff as staff_service
from apps.journal.services.grading import get_scale
from apps.journal.views.parent import current_module

MANAGER_ROLES = ("admin", "owner", "platform_admin")
# Заводить сотрудников может только владелец: администратор, который
# может завести себе второго администратора, — это не роль, а дыра.
OWNER_ROLES = ("owner", "platform_admin")


def _login_url(request) -> str:
    return request.build_absolute_uri(reverse("accounts:login"))


CREDENTIALS_KEY = "_issued_credentials"


def _credentials_response(request, credentials, *, back_url: str,
                          extra_credentials=None, student=None):
    """
    Показать выданные доступы — отдельной страницей, после перехода.

    Раньше страница отдавалась прямо в ответ на POST, и это ломалось
    дважды. Кабинет перехватывает обычные формы и подменяет только
    середину страницы — а в ответ приходил кусок без неё, и экран
    оставался пустым. Обновление же повторяло POST по адресу, который
    GET не принимает, и браузер показывал 405.

    Поэтому пароль кладём в сессию (она на сервере) и уводим человека
    на страницу, которая его показывает и тут же забывает. Обновить её
    можно сколько угодно — второй раз пароль просто не покажется.
    """
    request.session[CREDENTIALS_KEY] = {
        "credentials": asdict(credentials),
        "extra_credentials": asdict(extra_credentials) if extra_credentials else None,
        "back_url": back_url,
        "student_id": str(student.pk) if student is not None else "",
    }
    return redirect("cabinet:credentials")


@login_required
@role_required(*MANAGER_ROLES)
def credentials(request):
    """
    Логин и пароль, выданные только что.

    Показываются один раз: в базе пароль лежит хэшем, восстановить его
    нельзя — можно только выдать новый.
    """
    issued = request.session.pop(CREDENTIALS_KEY, None)
    if not issued:
        messages.info(request, "Пароль показывается один раз. Выдайте новый, если он потерян.")
        return redirect("cabinet:staff")

    return render(
        request,
        "cabinet/manage/credentials.html",
        {
            "credentials": issued["credentials"],
            "extra_credentials": issued["extra_credentials"],
            "login_url": _login_url(request),
            "back_url": issued["back_url"],
            "student_id": issued["student_id"],
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

# ─── Сотрудники ─────────────────────────────────────────────────────────────
#
# Один раздел на всех, кто работает в центре. Раньше педагоги жили в своём
# списке, а администраторы в другом — при том что действие одно: завести
# человека, выдать ему доступ, поправить данные. Разделение заставляло
# помнить, какая дверь для кого, и делало невозможным простое: сделать
# педагога ещё и владельцем.

# Порядок разделов на странице и старшинство ролей: человек с двумя ролями
# показывается один раз, в разделе старшей.
ROLE_ORDER = [
    (Role.OWNER, "Владельцы"),
    (Role.PLATFORM_ADMIN, "Администраторы платформы"),
    (Role.ADMIN, "Администраторы"),
    (Role.TEACHER, "Педагоги"),
]


def _can_edit_roles(request) -> bool:
    return request.user.is_superuser or request.user.has_role(
        request.organization, Role.OWNER, Role.PLATFORM_ADMIN
    )


def _available_roles(request):
    return staff_service.role_choices(
        with_platform_admin=(
            request.user.is_superuser
            or request.user.has_role(request.organization, Role.PLATFORM_ADMIN)
        )
    )


def _assert_may_touch(request, target) -> None:
    """
    Владельца правит только владелец.

    Иначе роль администратора становится способом добраться до владельца:
    сменить ему почту, выдать новый пароль и войти.
    """
    if target.pk == request.user.pk:
        return
    target_is_privileged = target.memberships.filter(
        organization=request.organization, is_active=True,
        role__in=(Role.OWNER, Role.PLATFORM_ADMIN),
    ).exists()
    if target_is_privileged and not _can_edit_roles(request):
        raise PermissionDenied("Карточку владельца открывает только владелец.")


@login_required
@role_required(*MANAGER_ROLES)
def staff(request):
    """Все, кто работает в центре, — по разделам."""
    organization = request.organization
    memberships = (
        Membership.objects.filter(
            organization=organization, is_active=True, role__in=STAFF_ROLES
        )
        .select_related("user")
        .prefetch_related("user__teacher_profile__subjects")
        .order_by("user__last_name", "user__first_name")
    )

    people: dict = {}
    for membership in memberships:
        people.setdefault(membership.user, set()).add(membership.role)

    sections = []
    for role, label in ROLE_ORDER:
        rows = []
        for user, roles in people.items():
            # Человек показывается один раз — в разделе своей старшей роли.
            top = next(r for r, _ in ROLE_ORDER if r in roles)
            if top != role:
                continue
            rows.append(
                {
                    "user": user,
                    "roles": ", ".join(
                        Role(r).label for r, _ in ROLE_ORDER if r in roles
                    ),
                    "teacher": getattr(user, "teacher_profile", None),
                    # «Выдать доступ» превращается в «новый пароль» только
                    # после того, как доступ действительно выдан.
                    "has_access": user.is_active and user.has_usable_password(),
                }
            )
        rows.sort(key=lambda row: (row["user"].last_name, row["user"].first_name))
        if rows:
            sections.append({"label": label, "rows": rows})

    return render(
        request,
        "cabinet/manage/staff.html",
        {
            "sections": sections,
            # Считаем здесь, а не в шаблоне: ссылка на двойников должна
            # появляться, только когда они есть.
            "twins_count": len(duplicates.find_pairs(organization))
            if _can_edit_roles(request)
            else 0,
        },
    )


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def staff_create(request):
    """Новый сотрудник — любой роли, включая педагога."""
    organization = request.organization
    roles = _available_roles(request)
    if not _can_edit_roles(request):
        # Администратор заводит педагогов, но не себе подобных.
        roles = [choice for choice in roles if choice[0] == Role.TEACHER]

    form = StaffForm(request.POST or None, roles=roles)
    teacher_form = TeacherEditForm(
        request.POST or None, request.FILES or None, prefix="teacher"
    )

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        is_teacher = data["role"] == Role.TEACHER
        if is_teacher and not teacher_form.is_valid():
            return _staff_form_page(request, form, teacher_form)

        # Такой человек уже может быть заведён — из расписания, из другого
        # раздела, кем-то ещё. Молча завести второго значит показать его на
        # сайте дважды и разложить занятия по двум карточкам.
        twin = duplicates.find_duplicate(
            organization=organization,
            last_name=data["last_name"], first_name=data["first_name"],
            middle_name=data["middle_name"], email=data["email"], phone=data["phone"],
        )
        if twin is not None and request.POST.get("confirm_twin") != "1":
            return _staff_form_page(request, form, teacher_form, twin=twin)

        with transaction.atomic():
            user, credentials = onboarding.issue_account(
                organization=organization,
                role=data["role"],
                last_name=data["last_name"],
                first_name=data["first_name"],
                middle_name=data["middle_name"],
                phone=data["phone"],
                email=data["email"],
            )
            if is_teacher:
                teacher = teacher_form.save(commit=False)
                teacher.organization = organization
                teacher.user = user
                teacher.save()
                teacher_form.save_m2m()

        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=user,
                  change="staff_created", role=data["role"])
        messages.success(request, f"{user.full_name} добавлен.")
        return _credentials_response(request, credentials, back_url=reverse("cabinet:staff"))

    return _staff_form_page(request, form, teacher_form)


def _staff_form_page(request, form, teacher_form, *, twin=None):
    return render(
        request,
        "cabinet/manage/staff_form.html",
        {
            "form": form,
            "teacher_form": teacher_form,
            "teacher_role": Role.TEACHER,
            "twin": twin,
        },
    )


@login_required
@role_required(Role.OWNER, Role.PLATFORM_ADMIN)
def staff_twins(request):
    """
    Двойники — отдельным экраном.

    Ходить по карточкам и высматривать их вручную бесполезно: заметен
    двойник только на публичной странице центра, а туда владелец
    заглядывает раз в месяц. Пусть система назовёт пары сама, а решение
    примет человек.
    """
    pairs = duplicates.find_pairs(request.organization)
    return render(
        request,
        "cabinet/manage/staff_twins.html",
        {
            "pairs": [
                {
                    "keep": keep,
                    "drop": drop,
                    "keep_teacher": getattr(keep, "teacher_profile", None),
                    "drop_teacher": getattr(drop, "teacher_profile", None),
                }
                for keep, drop in pairs
            ]
        },
    )


@login_required
@role_required(Role.OWNER, Role.PLATFORM_ADMIN)
@require_http_methods(["POST"])
def staff_merge(request, user_id):
    """
    Свести двойника с оригиналом.

    Право только у владельца: действие необратимое и затрагивает занятия,
    за которыми стоят баллы детей. Занятия при этом не теряются — они
    переезжают на оставшуюся карточку.
    """
    organization = request.organization
    User = get_user_model()
    keep_user = get_object_or_404(
        User.objects.filter(memberships__organization=organization).distinct(), pk=user_id
    )
    drop_user = get_object_or_404(
        User.objects.filter(memberships__organization=organization).distinct(),
        pk=request.POST.get("twin"),
    )
    keep = getattr(keep_user, "teacher_profile", None)
    drop = getattr(drop_user, "teacher_profile", None)
    if keep is None or drop is None:
        messages.error(request, "Свести можно только две карточки педагогов.")
        return redirect("cabinet:staff_card", user_id=user_id)

    try:
        moved = duplicates.merge_teachers(keep=keep, drop=drop)
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
        return redirect("cabinet:staff_card", user_id=user_id)

    log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=keep_user,
              change="teachers_merged", merged_from=str(drop_user.pk))
    messages.success(
        request,
        "Записи сведены: занятий перенесено {lessons}, отзывов {reviews}, "
        "предметов добавлено {subjects}. Вторая запись убрана совсем — "
        "ни в списке, ни на сайте её больше нет.".format(**moved),
    )
    if request.POST.get("back") == "twins":
        return redirect("cabinet:staff_twins")
    return redirect("cabinet:staff_card", user_id=user_id)


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def staff_card(request, user_id):
    """
    Карточка сотрудника: имя, контакты, роли и — если он педагог — всё,
    что о нём знает журнал и видит сайт.
    """
    organization = request.organization
    User = get_user_model()
    target = get_object_or_404(
        User.objects.filter(memberships__organization=organization).distinct(), pk=user_id
    )
    _assert_may_touch(request, target)

    can_edit_roles = _can_edit_roles(request)
    roles_now = staff_service.current_roles(target, organization)
    teacher = getattr(target, "teacher_profile", None)

    form = StaffIdentityForm(
        request.POST or None, instance=target,
        roles=_available_roles(request), can_edit_roles=can_edit_roles,
        initial={"roles": sorted(roles_now)},
    )
    teacher_form = TeacherEditForm(
        request.POST or None, request.FILES or None, prefix="teacher", instance=teacher
    )

    if request.method == "POST" and form.is_valid():
        wanted = form.cleaned_data.get("roles", roles_now) if can_edit_roles else roles_now
        # Педагогический блок разбираем, только если он к этому человеку
        # относится. Иначе правка карточки владельца упиралась бы в
        # незаполненную ставку за час — поле, которое ей ни к чему.
        needs_teacher = Role.TEACHER in wanted or teacher is not None
        if needs_teacher and not teacher_form.is_valid():
            return _staff_card_page(
                request, form, teacher_form, target, teacher, roles_now, can_edit_roles
            )
        try:
            staff_service.check_role_change(
                actor=request.user, target=target, organization=organization, roles=wanted
            )
        except ValidationError as error:
            for message in error.messages:
                form.add_error("roles" if can_edit_roles else None, message)
        else:
            with transaction.atomic():
                form.save()
                if can_edit_roles:
                    staff_service.set_roles(
                        target=target, organization=organization, roles=wanted
                    )
                # Карточка педагога заводится, когда роль появилась, и
                # остаётся, когда её сняли: на неё ссылаются занятия и
                # баллы, а их терять нельзя.
                if needs_teacher:
                    profile = teacher_form.save(commit=False)
                    profile.organization = organization
                    profile.user = target
                    profile.save()
                    teacher_form.save_m2m()

            log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=target,
                      change="staff_edited", roles=sorted(wanted))
            messages.success(request, "Сохранено.")
            return redirect("cabinet:staff")

    return _staff_card_page(
        request, form, teacher_form, target, teacher, roles_now, can_edit_roles
    )


def _staff_card_page(request, form, teacher_form, target, teacher, roles_now, can_edit_roles):
    return render(
        request,
        "cabinet/manage/staff_card.html",
        {
            "form": form,
            "teacher_form": teacher_form,
            "person": target,
            "teacher": teacher,
            "roles_now": ", ".join(Role(r).label for r, _ in ROLE_ORDER if r in roles_now),
            "can_edit_roles": can_edit_roles,
            "has_access": target.is_active and target.has_usable_password(),
            "is_self": target.pk == request.user.pk,
            # Если такой человек в организации уже есть — предлагаем свести,
            # а не оставлять две карточки жить своей жизнью.
            "twin": duplicates.find_duplicate(
                organization=request.organization,
                last_name=target.last_name, first_name=target.first_name,
                middle_name=target.middle_name, exclude_user=target,
            ) if teacher is not None else None,
            "may_merge": request.user.has_role(
                request.organization, Role.OWNER, Role.PLATFORM_ADMIN
            ) or request.user.is_superuser,
        },
    )


@login_required
@role_required(*OWNER_ROLES)
@require_http_methods(["GET", "POST"])
def staff_remove(request, user_id):
    """
    Убрать сотрудника.

    Учётная запись выключается, роли гаснут, карточка педагога мягко
    удаляется — а занятия и выставленные баллы остаются: это история
    центра, и она не должна исчезать вместе с человеком.
    """
    organization = request.organization
    User = get_user_model()
    target = get_object_or_404(
        User.objects.filter(memberships__organization=organization).distinct(), pk=user_id
    )
    if target.pk == request.user.pk:
        raise PermissionDenied("Убрать самого себя нельзя.")

    form = DeleteConfirmForm(request.POST or None, expected=target.last_name)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            Membership.objects.filter(organization=organization, user=target).update(
                is_active=False
            )
            target.is_active = False
            target.save(update_fields=["is_active", "updated_at"])
            profile = getattr(target, "teacher_profile", None)
            if profile is not None:
                profile.delete()
        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=target,
                  change="staff_removed")
        messages.success(request, "Сотрудник убран. Занятия и баллы сохранены.")
        return redirect("cabinet:staff")

    return render(
        request,
        "cabinet/manage/confirm_delete.html",
        {
            "form": form,
            "object_label": target.full_name,
            "expected": target.last_name,
            "back_url": reverse("cabinet:staff"),
            "what": "сотрудника",
        },
    )


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


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def two_factor_reset(request, user_id):
    """
    Отвязать приложение с одноразовыми кодами.

    Телефон меняют и теряют, а без этого привилегированный аккаунт
    остаётся запертым навсегда — раньше отвязать можно было только
    командой на сервере. Пароль при этом не меняется: следующий вход
    просто снова предложит отсканировать QR.

    Владельцу второй фактор сбрасывает только владелец — иначе роль
    администратора превращается в способ подобраться к владельцу.
    """
    from apps.accounts.models import TwoFactorDevice

    User = get_user_model()
    user = get_object_or_404(
        User.objects.filter(memberships__organization=request.organization).distinct(), pk=user_id
    )
    is_owner = request.user.has_role(request.organization, Role.OWNER) or request.user.is_superuser
    target_is_privileged = user.memberships.filter(
        organization=request.organization, role__in=(Role.OWNER, Role.PLATFORM_ADMIN)
    ).exists()
    if target_is_privileged and not is_owner:
        raise PermissionDenied("Сбросить второй фактор владельцу может только владелец.")

    deleted, _ = TwoFactorDevice.objects.filter(user=user).delete()
    if deleted:
        log_audit(action=AuditAction.TWO_FACTOR_RESET, request=request, obj=user)
        messages.success(
            request,
            f"{user.full_name}: приложение отвязано. При следующем входе "
            "откроется страница с новым QR-кодом.",
        )
    else:
        messages.info(request, f"У {user.full_name} приложение и не было привязано.")
    return redirect(request.META.get("HTTP_REFERER") or reverse("cabinet:staff"))


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


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["GET", "POST"])
def parent_invite(request, student_id):
    """
    Добавить родителя к уже заведённому ребёнку.

    Доступ выдаётся так же, как всем: логин и пароль генерируются, а
    администратор передаёт их лично. Самостоятельная регистрация по
    ссылке означала бы, что данные ребёнка получит тот, кому ссылку
    переслали, — а пересылают их легко.
    """
    student = get_object_or_404(Student.objects.all(), pk=student_id)
    form = ParentInviteForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            user, credentials = onboarding.issue_account(
                organization=request.organization,
                role=Role.PARENT,
                last_name=data["last_name"],
                first_name=data["first_name"],
                middle_name=data["middle_name"],
                phone=data["phone"],
                email=data["email"],
            )
            parent = Parent.objects.create(
                organization=request.organization, user=user,
                last_name=data["last_name"], first_name=data["first_name"],
                middle_name=data["middle_name"],
                phone=data["phone"], email=data["email"],
            )
            StudentParent.objects.create(
                organization=request.organization, student=student, parent=parent,
                relation=data.get("relation", ""),
                is_primary_contact=data.get("is_primary_contact", False),
            )

        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=parent,
                  change="parent_invited", student=str(student.pk))
        messages.success(request, f"{parent.full_name} добавлен к карточке ребёнка.")
        return _credentials_response(
            request, credentials,
            back_url=reverse("cabinet:student_card", args=[student.pk]),
            student=student,
        )

    return render(
        request,
        "cabinet/manage/parent_form.html",
        {"form": form, "student": student},
    )
