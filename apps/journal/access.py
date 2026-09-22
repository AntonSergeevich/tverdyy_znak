"""
Объектные права (ТЗ 3.2).

Педагог не должен получить доступ к чужому предмету подстановкой id в URL,
родитель — к чужому ребёнку. Поэтому вью не фильтруют вручную, а берут
выборку отсюда: одно место — один набор правил.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, QuerySet

from apps.accounts.models import ORG_MANAGER_ROLES, Role
from apps.journal.models import GradeItem, Group, Lesson, Student, Teacher


def is_manager(user, organization) -> bool:
    if user is None or not user.is_authenticated:
        return False
    return user.is_superuser or user.has_role(organization, *ORG_MANAGER_ROLES, Role.PLATFORM_ADMIN)


def teacher_profile(user, organization) -> Teacher | None:
    if user is None or not user.is_authenticated:
        return None
    return Teacher.objects.filter(organization=organization, user=user).first()


def accessible_students(user, organization) -> QuerySet[Student]:
    """Ученики, которых пользователю в принципе можно показывать."""
    base = Student.objects.filter(organization=organization)
    if user is None or not user.is_authenticated:
        return base.none()
    if is_manager(user, organization):
        return base
    if user.has_role(organization, Role.TEACHER):
        return base.filter(
            group_memberships__group__lessons__teacher__user=user
        ).distinct()
    if user.has_role(organization, Role.PARENT):
        return base.filter(parent_links__parent__user=user).distinct()
    if user.has_role(organization, Role.STUDENT):
        return base.filter(user=user)
    return base.none()


def get_student_or_403(user, organization, student_id) -> Student:
    student = accessible_students(user, organization).filter(pk=student_id).first()
    if student is None:
        raise PermissionDenied("Нет доступа к карточке этого ученика.")
    return student


def accessible_lessons(user, organization) -> QuerySet[Lesson]:
    base = Lesson.objects.filter(organization=organization).select_related(
        "subject", "group", "module", "teacher", "teacher__user"
    )
    if user is None or not user.is_authenticated:
        return base.none()
    if is_manager(user, organization):
        return base
    if user.has_role(organization, Role.TEACHER):
        return base.filter(teacher__user=user)
    if user.has_role(organization, Role.PARENT):
        return base.filter(group__memberships__student__parent_links__parent__user=user).distinct()
    if user.has_role(organization, Role.STUDENT):
        return base.filter(group__memberships__student__user=user).distinct()
    return base.none()


def get_lesson_or_403(user, organization, lesson_id) -> Lesson:
    lesson = accessible_lessons(user, organization).filter(pk=lesson_id).first()
    if lesson is None:
        raise PermissionDenied("Нет доступа к этому занятию.")
    return lesson


def assert_can_grade(user, organization, lesson: Lesson) -> None:
    """Выставлять баллы может педагог этого занятия, администратор или владелец."""
    if is_manager(user, organization):
        return
    profile = teacher_profile(user, organization)
    if profile is not None and lesson.teacher_id == profile.id:
        return
    raise PermissionDenied("Баллы по этому занятию выставляет другой педагог.")


def accessible_groups(user, organization) -> QuerySet[Group]:
    base = Group.objects.filter(organization=organization)
    if is_manager(user, organization):
        return base
    profile = teacher_profile(user, organization)
    if profile is not None:
        return base.filter(lessons__teacher=profile).distinct()
    return base.none()


def accessible_grade_items(user, organization) -> QuerySet[GradeItem]:
    """
    Работы модуля, баллы по которым пользователю можно выставлять.

    Проверочная, контрольная и зачёт не привязаны ни к какому занятию —
    у них нет ни педагога, ни даты в расписании. Поэтому право считаем
    по занятиям: работу ведёт тот, у кого в этом модуле есть занятия по
    этому предмету у этой группы.

    Связка проверяется целиком, одним подзапросом. Три отдельных фильтра
    дали бы доступ педагогу, который ведёт этот предмет другой группе,
    а эту группу — по другому предмету: каждое условие выполнено,
    а нужного занятия нет.
    """
    base = GradeItem.objects.filter(organization=organization).select_related(
        "module", "subject", "group", "lesson"
    )
    if user is None or not user.is_authenticated:
        return base.none()
    if is_manager(user, organization):
        return base
    profile = teacher_profile(user, organization)
    if profile is None:
        return base.none()
    mine = Lesson.objects.filter(
        organization=organization, teacher=profile,
        module=OuterRef("module_id"), subject=OuterRef("subject_id"),
        group=OuterRef("group_id"),
    )
    return base.filter(Exists(mine))


def get_grade_item_or_403(user, organization, item_id) -> GradeItem:
    item = accessible_grade_items(user, organization).filter(pk=item_id).first()
    if item is None:
        raise PermissionDenied("Баллы по этой работе выставляет другой педагог.")
    return item
