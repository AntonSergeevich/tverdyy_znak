"""
Меню кабинета.

Собирается по роли в одном месте: пункты, которых у роли нет, не должны
существовать даже как ссылка — иначе человек упирается в «нет прав»
и не понимает, что сделал не так.

У владельца разделов набралось тринадцать, и в строку они перестали
помещаться: последние заезжали друг за друга и просто не были видны.
Прокрутка это не лечит — пункт остаётся невидимым, только теперь его ещё
и искать надо. Поэтому близкое собрано в группы: «Учёба», «Дети»,
«Центр». Наверху остаётся пять названий вместо тринадцати, и каждое
отвечает на вопрос «где искать», а не «как называется экран».

`also` перечисляет маршруты, на которых пункт остаётся подсвеченным:
карточка ученика — это всё ещё раздел «Ученики».
"""
from __future__ import annotations

from django.urls import reverse

from apps.accounts.models import ORG_MANAGER_ROLES, Role


def _item(name: str, label: str, *also: str, url: str | None = None) -> dict:
    return {
        "name": name,
        "label": label,
        "url": url or reverse(f"cabinet:{name}"),
        "also": also,
    }


def _group(label: str, *items: dict) -> dict:
    """
    Несколько разделов под одним названием.

    Ключ намеренно не «items»: в шаблоне `entry.items` у обычного пункта
    попал бы в метод словаря `dict.items` и любой одиночный пункт стал бы
    выглядеть группой.
    """
    return {"label": label, "children": [item for item in items if item]}


def _mark_current(menu: list[dict], current: str) -> list[dict]:
    """
    Отметить, где мы сейчас.

    Группа подсвечивается, если внутри неё открытый раздел: иначе,
    провалившись в «Журнал», человек видит невыделенным вообще всё меню
    и теряет ощущение, где находится.
    """
    for entry in menu:
        items = entry.get("children")
        if items is None:
            entry["is_current"] = entry["name"] == current or current in entry["also"]
            continue
        for item in items:
            item["is_current"] = item["name"] == current or current in item["also"]
        entry["is_current"] = any(item["is_current"] for item in items)
    return menu


def cabinet_menu(request) -> dict:
    user = getattr(request, "user", None)
    organization = getattr(request, "organization", None)
    if not (user and user.is_authenticated and organization):
        return {}

    match = getattr(request, "resolver_match", None)
    current = getattr(match, "url_name", "") or ""

    is_manager = user.is_superuser or user.has_role(
        organization, *ORG_MANAGER_ROLES, Role.PLATFORM_ADMIN
    )
    if is_manager:
        menu = [
            _item("dashboard", "Панель"),
            _group(
                "Учёба",
                _item("journal", "Журнал", "lesson_journal"),
                _item("schedule_builder", "Расписание"),
                _item("ktp_list", "КТП", "ktp_detail"),
                _item("subjects", "Предметы", "subject_create", "subject_edit",
                      "subject_delete"),
                _item("rules", "Регламент"),
            ),
            _group(
                "Дети",
                _item("students", "Ученики", "student_card", "student_create",
                      "student_edit", "student_delete"),
                _item("progress_list", "Прогресс", "progress_student"),
            ),
            _group(
                "Центр",
                # Один раздел на всех, кто работает в центре: педагоги,
                # администраторы и владельцы. Раньше их было два, и завести
                # педагога владельцем было попросту негде.
                _item("staff", "Сотрудники", "staff_create", "staff_card",
                      "staff_remove", "staff_twins"),
                _item("payroll", "ФОТ"),
                _item("leads", "Заявки"),
                _item("review_queue", "Отзывы"),
            ),
        ]
        # Просмотр чужого кабинета — сопровождению платформы, не центру.
        if user.is_superuser or user.has_role(organization, Role.PLATFORM_ADMIN):
            menu.append(
                _item("impersonate_list", "Просмотр",
                      url=reverse("accounts:impersonate_list"))
            )
        return {"cabinet_menu": _mark_current(menu, current)}

    if user.has_role(organization, Role.TEACHER):
        return {
            "cabinet_menu": _mark_current(
                [
                    _item("teacher_today", "Сегодня", "lesson_journal", "module_plan"),
                    _item("schedule", "Расписание"),
                    _item("ktp_list", "КТП", "ktp_detail"),
                    _item("progress_list", "Прогресс", "progress_student"),
                    _item("teacher_hours", "Мои часы"),
                    _item("rules", "Регламент"),
                ],
                current,
            )
        }
    if user.has_role(organization, Role.PARENT):
        return {
            "cabinet_menu": _mark_current(
                [
                    _item("parent_home", "Мой ребёнок", "parent_child"),
                    _item("schedule", "Расписание"),
                    _item("parent_teachers", "Педагоги"),
                    # Регламент родителю не «до кучи»: сам документ требует,
                    # чтобы с критериями оценивания были заранее ознакомлены
                    # все — педагоги, ученики и родители (п. 1.6).
                    _item("rules", "Как оценивают"),
                ],
                current,
            )
        }
    if user.has_role(organization, Role.STUDENT):
        return {
            "cabinet_menu": _mark_current(
                [
                    _item("student_home", "Мой кабинет"),
                    _item("schedule", "Расписание"),
                    _item("parent_teachers", "Педагоги"),
                    _item("rules", "Как оценивают"),
                ],
                current,
            )
        }
    return {}
