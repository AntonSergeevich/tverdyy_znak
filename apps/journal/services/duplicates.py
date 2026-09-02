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


def _key(last_name: str, first_name: str, middle_name: str = "") -> tuple:
    """
    Ключ человека: фамилия, имя и отчество в нижнем регистре.

    Отчество учитываем, если оно есть у обоих: два Ивановых Ивана —
    в центре с сорока учениками почти наверняка один и тот же человек,
    а вот Иванов Иван Петрович и Иванов Иван Сергеевич — разные.
    """
    return (
        (last_name or "").strip().lower(),
        (first_name or "").strip().lower(),
        (middle_name or "").strip().lower(),
    )


def find_duplicate(*, organization, last_name: str, first_name: str,
                   middle_name: str = "", email: str = "", phone: str = "",
                   exclude_user=None):
    """
    Есть ли уже такой человек в организации.

    Совпадением считаем полное совпадение ФИО, либо совпадение фамилии с
    именем при пустом отчестве у одного из них, либо тот же email или
    телефон. Возвращаем найденного — решать, тот ли это человек, будет
    живой человек, а не мы.
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

    surname, name, patronymic = _key(last_name, first_name, middle_name)
    if not surname or not name:
        return None
    for person in people.filter(last_name__iexact=surname, first_name__iexact=name):
        theirs = (person.middle_name or "").strip().lower()
        if not patronymic or not theirs or patronymic == theirs:
            return person
    return None


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
    drop.delete()
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
