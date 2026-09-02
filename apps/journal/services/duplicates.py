"""
Один человек — одна запись.

Учётные записи заводятся из нескольких мест: педагога добавляют в разделе
сотрудников, он же попадает в расписание из выгрузки, ему же потом выдают
доступ. Ничто из этого не проверяло, нет ли такого человека уже, — и на
публичной странице центра один и тот же педагог оказывался дважды.

Здесь две вещи: узнать однофамильца заранее и свести двойника с оригиналом,
не потеряв ни занятий, ни отзывов.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.journal.models import Lesson, Teacher


def name_parts(*values) -> frozenset:
    """
    Имя человека как набор слов, без оглядки на то, что где записано.

    В одной записи «Семидалова Маргарита Андреевна», в другой — просто
    «Маргарита Андреевна»: фамилию при первом заведении не знали. Сравнение
    по паре «фамилия + имя» такие записи не сводило вовсе, и предложение
    объединить не появлялось — а человек всё это время был на сайте дважды.

    Поэтому сравниваем множества слов: порядок и то, в какое поле слово
    попало, значения не имеют.
    """
    words = set()
    for value in values:
        for word in (value or "").strip().lower().replace("ё", "е").split():
            word = word.strip(".,")
            if word:
                words.add(word)
    return frozenset(words)


def looks_like_the_same(first: frozenset, second: frozenset) -> bool:
    """
    Один ли это человек.

    Совпало полностью — да. Одно имя целиком входит в другое и общих слов
    не меньше двух — тоже да: «Маргарита Андреевна» и «Семидалова Маргарита
    Андреевна» это один человек, а вот «Иванов» и «Иванов Пётр» по одному
    слову сводить нельзя, однофамильцев слишком много.
    """
    if not first or not second:
        return False
    if first == second:
        return True
    common = first & second
    return len(common) >= 2 and (first <= second or second <= first)


def find_duplicate(*, organization, last_name: str, first_name: str,
                   middle_name: str = "", email: str = "", phone: str = "",
                   exclude_user=None):
    """
    Есть ли уже такой человек в организации.

    Совпадением считаем совпадение по имени (см. `looks_like_the_same`)
    либо тот же email или телефон. Возвращаем найденного — решать, тот ли
    это человек, будет живой человек, а не мы.
    """
    User = get_user_model()
    people = User.objects.filter(memberships__organization=organization).distinct()
    if exclude_user is not None:
        people = people.exclude(pk=exclude_user.pk)

    email = (email or "").strip().lower()
    phone = (phone or "").strip()
    if email:
        found = people.filter(email__iexact=email).first()
        if found is not None:
            return found
    if phone:
        found = people.filter(phone=phone).first()
        if found is not None:
            return found

    mine = name_parts(last_name, first_name, middle_name)
    if not mine:
        return None
    for person in people:
        theirs = name_parts(person.last_name, person.first_name, person.middle_name)
        if looks_like_the_same(mine, theirs):
            return person
    return None


def find_pairs(organization) -> list[tuple]:
    """
    Все подозрительные пары в организации — для отдельного экрана.

    Ходить по карточкам и высматривать двойников вручную бесполезно:
    заметен двойник только на публичной странице, а туда владелец
    заглядывает раз в месяц. Пусть система назовёт их сама.
    """
    User = get_user_model()
    people = list(
        User.objects.filter(memberships__organization=organization)
        .distinct()
        .select_related("teacher_profile")
    )
    named = [
        (person, name_parts(person.last_name, person.first_name, person.middle_name))
        for person in people
    ]

    pairs = []
    for index, (person, mine) in enumerate(named):
        for other, theirs in named[index + 1:]:
            same_contact = bool(
                (person.email and person.email.lower() == (other.email or "").lower())
                or (person.phone and person.phone == other.phone)
            )
            if same_contact or looks_like_the_same(mine, theirs):
                # Первым — тот, у кого имя полнее: его карточку и оставляем.
                if len(theirs) > len(mine):
                    pairs.append((other, person))
                else:
                    pairs.append((person, other))
    return pairs


@transaction.atomic
def merge_teachers(*, keep: Teacher, drop: Teacher) -> dict:
    """
    Свести двойника с оригиналом.

    Переносим всё, что на двойнике висит: занятия, предметы, отзывы. Потом
    убираем и карточку педагога, и учётную запись — оставленная «на всякий
    случай» вторая запись рано или поздно снова всплывёт на сайте.

    Занятия переносим, а не удаляем: за ними стоят баллы детей, и потерять
    их из-за чужой ошибки при заведении — недопустимо.
    """
    if keep.pk == drop.pk:
        raise ValidationError("Это одна и та же карточка.")
    if keep.organization_id != drop.organization_id:
        raise ValidationError("Карточки из разных организаций свести нельзя.")

    moved_lessons = Lesson.objects.filter(teacher=drop).update(teacher=keep)
    moved_reviews = drop.reviews.update(teacher=keep)
    subjects = list(drop.subjects.all())
    keep.subjects.add(*subjects)

    dropped_user = drop.user
    drop.subjects.clear()
    # Убираем совсем, а не пометкой. Мягкое удаление здесь уже подводило:
    # карточка оставалась в базе, связь «пользователь → педагог» продолжала
    # её отдавать, и двойник возвращался на экран при первой же правке.
    # Терять нечего: занятия, отзывы и предметы только что переехали.
    drop.hard_delete()
    if dropped_user is not None:
        # Учётную запись двойника убираем целиком: она никому не
        # принадлежит, а её membership иначе продолжит светиться в списках.
        dropped_user.memberships.all().delete()
        dropped_user.is_active = False
        dropped_user.save(update_fields=["is_active"])

    return {
        "lessons": moved_lessons,
        "reviews": moved_reviews,
        "subjects": len(subjects),
    }
