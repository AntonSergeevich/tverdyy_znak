"""
Меню кабинета.

Собирается по роли в одном месте: пункты, которых у роли нет, не должны
существовать даже как ссылка — иначе человек упирается в «нет прав»
и не понимает, что сделал не так.

`also` перечисляет маршруты, на которых пункт остаётся подсвеченным:
карточка ученика — это всё ещё раздел «Ученики».
"""
from __future__ import annotations

from django.urls import reverse

from apps.accounts.models import ORG_MANAGER_ROLES, Role


def _item(name: str, label: str, *also: str) -> dict:
    return {"name": name, "label": label, "url": reverse(f"cabinet:{name}"), "also": also}


def cabinet_menu(request) -> dict:
    user = getattr(request, "user", None)
    organization = getattr(request, "organization", None)
    if not (user and user.is_authenticated and organization):
        return {}

    is_manager = user.is_superuser or user.has_role(
        organization, *ORG_MANAGER_ROLES, Role.PLATFORM_ADMIN
    )
    if is_manager:
        menu = [
            _item("dashboard", "Панель"),
            _item("journal", "Журнал", "lesson_journal"),
            _item("leads", "Заявки"),
            _item("students", "Ученики", "student_card", "student_create", "student_edit",
                  "student_delete"),
            _item("teachers", "Педагоги", "teacher_create", "teacher_edit", "teacher_delete"),
            _item("schedule_builder", "Расписание"),
            _item("payroll", "ФОТ"),
            _item("review_queue", "Отзывы"),
        ]
        if user.is_superuser or user.has_role(organization, Role.OWNER, Role.PLATFORM_ADMIN):
            menu.append(_item("staff", "Сотрудники", "staff_create"))
        return {"cabinet_menu": menu}

    if user.has_role(organization, Role.TEACHER):
        return {
            "cabinet_menu": [
                _item("teacher_today", "Сегодня", "lesson_journal", "module_plan"),
                _item("schedule", "Расписание"),
            ]
        }
    if user.has_role(organization, Role.PARENT):
        return {
            "cabinet_menu": [
                _item("parent_home", "Мой ребёнок", "parent_child"),
                _item("schedule", "Расписание"),
                _item("parent_teachers", "Педагоги"),
            ]
        }
    if user.has_role(organization, Role.STUDENT):
        return {
            "cabinet_menu": [
                _item("student_home", "Мой кабинет"),
                _item("schedule", "Расписание"),
            ]
        }
    return {}
