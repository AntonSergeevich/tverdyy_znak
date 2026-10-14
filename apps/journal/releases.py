"""
Обновления кабинета: версии, что изменилось и где это теперь.

Список ведётся здесь, в коде, а не в базе: заметки к версии выезжают
вместе с самой версией, и не бывает так, что на сайте уже новое, а
рассказ о нём ещё не написан (или наоборот).

Каждое изменение помечено, кому оно интересно. Окно «Что нового» и
страница обновлений показывают человеку только его: родителю незачем
читать про журнал педагога. Руководитель видит всё.

Картинки — снимки демо-кабинета с выдуманными учениками. Настоящих
детей в них нет и быть не может (152-ФЗ): снимки делаются скриптом на
тестовой базе, а не с рабочего сайта.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from apps.accounts.models import ORG_MANAGER_ROLES, Role

MANAGER = "manager"
TEACHER = "teacher"
PARENT = "parent"
STUDENT = "student"

STAFF = (MANAGER, TEACHER)
FAMILY = (PARENT, STUDENT)

AUDIENCE_LABELS = {
    MANAGER: "руководителю",
    TEACHER: "педагогу",
    PARENT: "родителю",
    STUDENT: "ученику",
}

KIND_LABELS = {
    "new": "Новое",
    "moved": "Переехало",
    "better": "Стало удобнее",
    "fixed": "Исправлено",
}


@dataclass(frozen=True)
class Media:
    """Картинка или видео: путь внутри static и подпись для незрячих."""

    src: str
    alt: str

    @property
    def is_video(self) -> bool:
        return self.src.endswith((".mp4", ".webm"))


@dataclass(frozen=True)
class Change:
    title: str
    text: str
    kind: str = "new"
    # Кому показывать. Пусто — всем.
    roles: tuple[str, ...] = ()
    # Где это теперь — одной строкой, словами человека, а не адресом.
    where: str = ""
    media: tuple[Media, ...] = ()

    def is_for(self, audiences: set[str]) -> bool:
        return not self.roles or bool(audiences & set(self.roles))

    @property
    def kind_label(self) -> str:
        return KIND_LABELS[self.kind]

    @property
    def role_labels(self) -> list[str]:
        return [AUDIENCE_LABELS[role] for role in self.roles]


@dataclass(frozen=True)
class Release:
    version: str
    date: dt.date
    title: str
    summary: str
    changes: tuple[Change, ...] = field(default_factory=tuple)
    # Рассказывать ли в окне после обновления. Версии до появления окна —
    # только история на странице: всплывать с ними задним числом незачем.
    announce: bool = True

    @property
    def anchor(self) -> str:
        return "v" + self.version.replace(".", "-")

    def changes_for(self, audiences: set[str]) -> list[Change]:
        if MANAGER in audiences:
            return list(self.changes)
        return [change for change in self.changes if change.is_for(audiences)]


def _shot(name: str, alt: str) -> Media:
    return Media(f"img/updates/{name}", alt)


# Новые версии — сверху.
RELEASES: tuple[Release, ...] = (
    Release(
        version="2.1",
        date=dt.date(2026, 10, 14),
        title="Свайпы и «Отменить»",
        summary=(
            "На телефоне частые действия делаются жестом, мелкие удаления — без "
            "вопроса «Вы уверены?», зато с кнопкой «Отменить», а поиск ученика "
            "ищет прямо по мере набора."
        ),
        changes=(
            Change(
                title="Проверка домашнего — смахиванием",
                text=(
                    "Смахните строку ученика вправо — «Зачтено», влево — «Доделать». "
                    "Из-под строки видно, что сейчас произойдёт; не дотянули — она "
                    "вернётся на место. Кнопки в строке остались."
                ),
                roles=STAFF,
                where="Занятие → вкладка «Домашнее»",
                media=(_shot("2.1/review-swipe.webp", "Строка ученика смахивается вправо, проступает «Зачтено»"),),
            ),
            Change(
                title="«Сделал» — смахиванием",
                text="Сделали задание — смахните карточку вправо. Кнопка «Сделал» тоже на месте.",
                roles=(STUDENT,),
                where="Мой кабинет → Домашние задания",
                media=(_shot("2.1/homework-swipe.webp", "Карточка задания смахивается вправо"),),
            ),
            Change(
                title="Недели и вкладки листаются пальцем",
                text=(
                    "В расписании проведите влево — следующая неделя, вправо — "
                    "предыдущая. Так же листаются вкладки занятия и, если детей "
                    "несколько, кабинеты детей у родителя."
                ),
                kind="better",
                where="Расписание; занятие; Мой ребёнок",
            ),
            Change(
                title="«Отменить» вместо «Вы уверены?»",
                text=(
                    "Убрали ученика из группы, сняли занятие в расписании, удалили "
                    "пустую работу — это делается сразу, а внизу на несколько секунд "
                    "появляется «Отменить». Где вернуть всё нельзя (работа вместе "
                    "с баллами, удаление ученика), подтверждение осталось."
                ),
                kind="better",
                roles=STAFF,
                where="Группы; конструктор расписания; страница работы",
                media=(_shot("2.1/undo.webp", "Внизу экрана плашка «Отменить»"),),
            ),
            Change(
                title="Поиск ученика — по мере набора",
                text="Начните печатать фамилию или имя — список сразу сужается, кнопка «Найти» больше не нужна.",
                kind="better",
                roles=(MANAGER,),
                where="Дети → Ученики",
            ),
        ),
    ),
    Release(
        version="2.0",
        date=dt.date(2026, 10, 14),
        title="Новый вид кабинета",
        summary=(
            "Кабинет стал проще и удобнее с телефона: меню внизу экрана, "
            "занятие разложено по вкладкам, у ученика сверху то, что нужно сегодня."
        ),
        changes=(
            Change(
                title="Меню — внизу экрана",
                text=(
                    "На телефоне разделы теперь в нижней строке, как в привычных "
                    "приложениях: до них достаёт большой палец, и искать значок "
                    "меню в углу больше не нужно. Если разделов много, остальные "
                    "лежат под «Ещё»."
                ),
                kind="moved",
                where="На телефоне — нижняя строка экрана",
                media=(_shot("2.0/phone-menu.webp", "Нижнее меню кабинета на телефоне"),),
            ),
            Change(
                title="Профиль, тема и выход — под кружком с инициалами",
                text=(
                    "Кнопки «Профиль» и «Выйти» и переключатель темы собраны в одно "
                    "меню. Его открывает кружок с вашими инициалами справа вверху."
                ),
                kind="moved",
                where="Справа вверху, кружок с инициалами",
                media=(_shot("2.0/account-menu.webp", "Меню профиля открыто: профиль, обновления, тема, выход"),),
            ),
            Change(
                title="Занятие разложено по вкладкам",
                text=(
                    "На странице занятия три вкладки: «Ученики» — баллы за занятие, "
                    "«Домашнее» — задать новое и проверить прошлое, «Работы» — "
                    "проверочные, контрольная и зачёт. Раньше всё шло одним длинным "
                    "листом, и список детей терялся посередине. Тема занятия — "
                    "одной строкой сверху, она видна на любой вкладке."
                ),
                roles=STAFF,
                where="Расписание → занятие",
                media=(_shot("2.0/lesson-tabs.webp", "Страница занятия: вкладки Ученики, Домашнее, Работы"),),
            ),
            Change(
                title="Таблицы на телефоне стали карточками",
                text=(
                    "Ученики, группы, сотрудники и оплаты на узком экране больше не "
                    "обрезаются справа: каждая строка — отдельная карточка, где "
                    "видно всё."
                ),
                kind="better",
                roles=(MANAGER, PARENT),
                where="Ученики, Группы, Сотрудники, Оплаты",
                media=(_shot("2.0/cards.webp", "Список учеников карточками на телефоне"),),
            ),
            Change(
                title="В кабинете ученика сначала — сегодня",
                text=(
                    "Сверху теперь занятия на сегодня и домашние задания, ниже — "
                    "баллы и цели. «Как день» — одна строка смайликов, а отметить "
                    "вчерашний день можно по ссылке под ней."
                ),
                roles=(STUDENT, MANAGER),
                where="Мой кабинет",
                media=(_shot("2.0/student-home.webp", "Кабинет ученика: сегодня и домашнее сверху"),),
            ),
            Change(
                title="Динамика по модулям — со второго модуля",
                text=(
                    "График из одного столбика ничего не сравнивал и занимал пол-"
                    "экрана. Теперь он появляется, когда закончатся хотя бы два "
                    "модуля, а до тех пор итог виден в таблице."
                ),
                kind="fixed",
                roles=(PARENT,),
                where="Мой ребёнок",
            ),
            Change(
                title="Страница обновлений",
                text=(
                    "Что изменилось в кабинете, где теперь лежит и как этим "
                    "пользоваться — с картинками. После каждого обновления один раз "
                    "появляется короткое окно, а подробности остаются здесь."
                ),
                where="Кружок с инициалами → Обновления",
            ),
        ),
    ),
    Release(
        version="1.7",
        announce=False,
        date=dt.date(2026, 10, 14),
        title="Группы и курсы",
        summary="Руководитель сам заводит группы и курсы, ученик может быть в нескольких.",
        changes=(
            Change(
                title="Группы заводит руководитель",
                text=(
                    "Курсы подготовки («ОГЭ: математика», «6 класс: русский язык») "
                    "заводятся в разделе «Группы». Ученик может быть сразу в "
                    "семейном классе и на курсах."
                ),
                roles=(MANAGER,),
                where="Дети → Группы",
            ),
            Change(
                title="Итоги прошлых модулей не пропадают",
                text=(
                    "Когда начинается новый модуль, баллы за прошлые остаются в "
                    "кабинете — с разбивкой, за что их поставили."
                ),
                kind="fixed",
                roles=(STUDENT, PARENT, MANAGER),
                where="Мой кабинет → Прошлые модули",
            ),
        ),
    ),
    Release(
        version="1.6",
        announce=False,
        date=dt.date(2026, 10, 5),
        title="Лишнее убирается",
        summary="Лишнюю работу можно удалить, оценивание — снять с занятия.",
        changes=(
            Change(
                title="Удалить лишнюю работу",
                text="Со страницы работы — вместе с баллами за неё. Удаление мягкое, баллы не теряются бесследно.",
                roles=STAFF,
                where="Занятие → Работы → работа → внизу «Удалить»",
            ),
            Change(
                title="Снять оценивание с занятия",
                text="Если мешают выставленные баллы, видно поимённо, чьи, и снять можно одной кнопкой.",
                kind="fixed",
                roles=STAFF,
                where="Занятие → «Сделать без оценивания»",
            ),
        ),
    ),
    Release(
        version="1.5",
        announce=False,
        date=dt.date(2026, 9, 24),
        title="Проверочные на странице занятия",
        summary="Проверочная, контрольная и зачёт заводятся и оцениваются там, где их провели.",
        changes=(
            Change(
                title="Свой журнал у каждой работы",
                text="Диктант, проверочная, контрольная и зачёт — своим списком баллов, прямо со страницы занятия.",
                roles=STAFF,
                where="Занятие → Работы",
            ),
        ),
    ),
    Release(
        version="1.4",
        announce=False,
        date=dt.date(2026, 9, 15),
        title="За что балл",
        summary="Баллы за домашнее и разбивка: за какую работу сколько.",
        changes=(
            Change(
                title="Видно, за что каждый балл",
                text="У каждого предмета раскрывается список: работа, дата, баллы и комментарий педагога.",
                roles=(STUDENT, PARENT, MANAGER),
                where="Баллы по предметам → «за что»",
            ),
            Change(
                title="Балл за домашнее",
                text="Домашнее можно не только зачесть, но и оценить баллами.",
                roles=STAFF,
                where="Занятие → проверка домашнего",
            ),
        ),
    ),
    Release(
        version="1.3",
        announce=False,
        date=dt.date(2026, 9, 3),
        title="Домашнее до конца",
        summary="Сделал → проверено → ответ ученику. Меню собрано в группы.",
        changes=(
            Change(
                title="Домашнее с ответом",
                text="Ученик отмечает «сделал», педагог принимает или отправляет на доработку с комментарием.",
                roles=(STUDENT, TEACHER, MANAGER),
                where="Домашние задания",
            ),
            Change(
                title="Регламент оценивания — всем",
                text="Как ставят баллы, видят и семьи.",
                roles=FAMILY,
                where="Как оценивают",
            ),
        ),
    ),
    Release(
        version="1.2",
        announce=False,
        date=dt.date(2026, 9, 2),
        title="Файлы к заданиям",
        summary="К домашнему прикладываются документы, таблицы и картинки.",
        changes=(
            Change(
                title="Файлы к домашнему",
                text="Перетащите файл или вставьте из буфера — Word, PDF, таблицы, презентации, картинки.",
                roles=STAFF,
                where="Занятие → Домашнее",
            ),
        ),
    ),
    Release(
        version="1.1",
        announce=False,
        date=dt.date(2026, 8, 31),
        title="Журнал занятия",
        summary="Занятие открывается из расписания, балл ставится кругом. Цели по шагам.",
        changes=(
            Change(
                title="Балл — кругом",
                text="Нажмите на балл в строке ученика и потяните по кругу.",
                roles=STAFF,
                where="Расписание → занятие",
            ),
            Change(
                title="Цели по шагам и «как день»",
                text="Цель раскладывается на шаги; наставник видит открытые цели и настроение.",
                roles=(STUDENT, MANAGER),
                where="Мой кабинет",
            ),
        ),
    ),
    Release(
        version="1.0",
        announce=False,
        date=dt.date(2026, 8, 26),
        title="Кабинеты открыты",
        summary="Журнал, расписание, баллы по 100-балльной системе и кабинеты для всей семьи.",
    ),
)

CURRENT = RELEASES[0]


def audiences(user, organization) -> set[str]:
    """Кем человек приходит в кабинет — от этого зависит, что ему рассказывать."""
    if user.is_superuser:
        return {MANAGER}
    roles = user.roles_in(organization) if organization else set()
    found = set()
    if roles & {*ORG_MANAGER_ROLES, Role.PLATFORM_ADMIN}:
        found.add(MANAGER)
    if Role.TEACHER in roles:
        found.add(TEACHER)
    if Role.PARENT in roles:
        found.add(PARENT)
    if Role.STUDENT in roles:
        found.add(STUDENT)
    return found


def unseen_releases(user) -> list[Release]:
    """
    Версии, о которых человеку ещё не рассказали, — новые сверху.

    Пропустил две версии — узнает про обе, в одном окне. Версии из истории
    (до появления окна) не рассказываются никогда.

    Тому, кто пришёл в кабинет уже после выхода версии, рассказывать «что
    изменилось» не о чем: для него так было всегда.
    """
    seen = user.release_seen
    joined = getattr(user, "created_at", None)
    found = []
    for release in RELEASES:
        if release.version == seen or not release.announce:
            break
        if joined and joined.date() >= release.date:
            break
        found.append(release)
    return found


def mark_seen(user) -> None:
    if user.release_seen != CURRENT.version:
        user.release_seen = CURRENT.version
        user.save(update_fields=["release_seen"])
