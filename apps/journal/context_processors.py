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

from functools import cached_property

from django.urls import reverse

from apps.accounts.models import ORG_MANAGER_ROLES, Role
from apps.journal import releases


# Значок раздела в нижнем меню телефона. Спрайт — cabinet/partials/icons.html.
ICONS = {
    "dashboard": "grid",
    "teacher_today": "sun",
    "schedule": "calendar",
    "ktp_list": "list",
    "progress_list": "chart",
    "teacher_hours": "clock",
    "rules": "doc",
    "parent_home": "heart",
    "student_home": "home",
    "parent_teachers": "users",
    "impersonate_list": "eye",
    "Учёба": "book",
    "Дети": "users",
    "Центр": "building",
}

# Сколько разделов помещается в нижнюю строку телефона. Больше пяти — и
# подписи перестают читаться, а в значки не попасть пальцем.
PHONE_TABS = 5


def _item(name: str, label: str, *also: str, url: str | None = None) -> dict:
    return {
        "name": name,
        "label": label,
        "url": url or reverse(f"cabinet:{name}"),
        "also": also,
        "icon": ICONS.get(name, "doc"),
    }


def _phone_more(menu: list[dict]) -> dict | None:
    """
    Что не влезло в нижнюю строку телефона — под «Ещё».

    На компьютере разделы стоят в строку как были; на телефоне первые
    четыре остаются на виду, остальные уходят в пятую кнопку. Помеченные
    `phone_hidden` прячет CSS только на узком экране.
    """
    if len(menu) <= PHONE_TABS:
        return None
    rest = menu[PHONE_TABS - 1:]
    children = []
    for entry in rest:
        entry["phone_hidden"] = True
        children.extend(entry.get("children") or [entry])
    return {
        "label": "Ещё",
        "icon": "more",
        "children": children,
        "is_current": any(item["is_current"] for item in children),
    }


def _menu(menu: list[dict], current: str) -> dict:
    menu = _mark_current(menu, current)
    return {"cabinet_menu": menu, "cabinet_more": _phone_more(menu)}


def _group(label: str, *items: dict) -> dict:
    """
    Несколько разделов под одним названием.

    Ключ намеренно не «items»: в шаблоне `entry.items` у обычного пункта
    попал бы в метод словаря `dict.items` и любой одиночный пункт стал бы
    выглядеть группой.
    """
    return {
        "label": label,
        "children": [item for item in items if item],
        "icon": ICONS.get(label, "doc"),
    }


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
                _item("groups", "Группы", "group_card"),
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
        return _menu(menu, current)

    if user.has_role(organization, Role.TEACHER):
        return _menu(
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
    if user.has_role(organization, Role.PARENT):
        return _menu(
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
    if user.has_role(organization, Role.STUDENT):
        return _menu(
            [
                _item("student_home", "Мой кабинет"),
                _item("schedule", "Расписание"),
                _item("parent_teachers", "Педагоги"),
                _item("rules", "Как оценивают"),
            ],
            current,
        )
    return {}


class _ReleaseNotice:
    """
    Что рассказать человеку об обновлениях — считается, только если шаблон
    спросил: на публичных страницах этот блок не нужен, и лишний запрос
    к ролям там ни к чему.
    """

    def __init__(self, request):
        self._request = request

    @cached_property
    def _audiences(self) -> set[str]:
        return releases.audiences(self._request.user, getattr(self._request, "organization", None))

    @cached_property
    def pending(self) -> list:
        request = self._request
        # Глядя чужими глазами, окно не показываем и «прочитано» не ставим:
        # человек сам ещё ничего не видел.
        if getattr(request, "impersonator", None):
            return []
        return releases.unseen_releases(request.user)

    @cached_property
    def changes(self) -> list:
        """Не больше пяти пунктов: окно — чтобы заметить, читать — на странице."""
        found = []
        for release in self.pending:
            # Строго своё, даже руководителю: на странице он видит всё,
            # а в окне — то, что поменялось у него самого.
            found.extend(c for c in release.changes if c.is_for(self._audiences))
        return found[:5]

    @cached_property
    def picture(self):
        for change in self.changes:
            if change.media and not change.media[0].is_video:
                return change.media[0]
        return None

    @property
    def show(self) -> bool:
        return bool(self.changes)

    @property
    def is_unread(self) -> bool:
        return bool(self.pending)

    @property
    def version(self) -> str:
        return releases.CURRENT.version

    @property
    def title(self) -> str:
        if len(self.pending) > 1:
            return "Что нового в кабинете"
        return f"Что нового: {self.pending[0].title.lower()}" if self.pending else ""

    @property
    def versions_label(self) -> str:
        """«Обновление 2.1» или «Обновления 2.0–2.1», если пропущено несколько."""
        if len(self.pending) > 1:
            return f"Обновления {self.pending[-1].version}–{self.pending[0].version}"
        return f"Обновление {self.version}"


def release_notice(request) -> dict:
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {}
    return {"release_notice": _ReleaseNotice(request)}
