"""
Формы кабинета.

Формы здесь только проверяют ввод. Создание учётных записей живёт
в services/onboarding.py: форма не должна знать, как устроены пароли.
"""
from __future__ import annotations

import datetime as dt

from django import forms
from django.contrib.auth import get_user_model

from apps.accounts.models import Role
from apps.journal.services.staff import role_choices
from apps.journal.models import (
    Group,
    Parent,
    Payment,
    Student,
    StudentStatus,
    Subject,
    Teacher,
)


class PersonForm(forms.Form):
    """Общая часть: имя человека и способ с ним связаться."""

    last_name = forms.CharField(label="Фамилия", max_length=80)
    first_name = forms.CharField(label="Имя", max_length=80)
    middle_name = forms.CharField(label="Отчество", max_length=80, required=False)
    phone = forms.CharField(label="Телефон", max_length=32, required=False)
    email = forms.EmailField(
        label="Email", required=False,
        help_text="Если оставить пустым, логин сгенерируется из фамилии и имени.",
    )


class StudentForm(PersonForm):
    grade_level = forms.TypedChoiceField(
        label="Класс", coerce=int, choices=[(n, f"{n} класс") for n in range(8, 12)]
    )
    birth_date = forms.DateField(
        label="Дата рождения", required=False, widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Хранится в зашифрованном виде.",
    )
    group = forms.ModelChoiceField(
        label="Группа", queryset=Group.objects.none(), required=False,
        empty_label="Без группы",
    )
    enrolled_on = forms.DateField(
        label="Дата зачисления", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    status = forms.ChoiceField(label="Статус", choices=StudentStatus.choices, required=False)
    note = forms.CharField(label="Заметка", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    # Родитель заводится вместе с ребёнком: без взрослого в системе
    # некому смотреть оплаты, и карточка ребёнка повисает без контакта.
    parent_last_name = forms.CharField(label="Фамилия родителя", max_length=80, required=False)
    parent_first_name = forms.CharField(label="Имя родителя", max_length=80, required=False)
    parent_phone = forms.CharField(label="Телефон родителя", max_length=32, required=False)
    parent_email = forms.EmailField(label="Email родителя", required=False)

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = Group.objects.filter(academic_year__is_current=True)
        self.fields["enrolled_on"].initial = dt.date.today()
        self.fields["status"].initial = StudentStatus.ENROLLED

    def clean(self):
        data = super().clean()
        # Родителя заводим только если названы фамилия и имя: половина
        # данных хуже, чем их отсутствие — потом не понять, кто это.
        has_any = any(
            data.get(field)
            for field in ("parent_last_name", "parent_first_name", "parent_phone", "parent_email")
        )
        if has_any and not (data.get("parent_last_name") and data.get("parent_first_name")):
            raise forms.ValidationError(
                "У родителя нужны фамилия и имя — иначе непонятно, чей это контакт."
            )
        return data


class StudentEditForm(forms.ModelForm):
    """Правка карточки. Учётную запись здесь не трогаем — для неё свои действия."""

    group = forms.ModelChoiceField(
        label="Группа", queryset=Group.objects.none(), required=False, empty_label="Без группы"
    )

    class Meta:
        model = Student
        fields = [
            "last_name", "first_name", "middle_name", "grade_level",
            "birth_date", "status", "enrolled_on", "attestation_partner", "note",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "enrolled_on": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = Group.objects.filter(academic_year__is_current=True)
        if self.instance.pk:
            membership = self.instance.group_memberships.select_related("group").first()
            self.fields["group"].initial = membership.group if membership else None


class DeleteConfirmForm(forms.Form):
    """
    Удаление с подтверждением: имя вводится руками.

    Кнопка «точно удалить?» нажимается не глядя. Ввод фамилии — единственная
    защита, которая заставляет остановиться и посмотреть, кого удаляешь.
    """

    confirm = forms.CharField(label="Введите фамилию для подтверждения", max_length=120)

    def __init__(self, *args, expected: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.expected = expected

    def clean_confirm(self):
        value = (self.cleaned_data["confirm"] or "").strip().casefold()
        if value != self.expected.strip().casefold():
            raise forms.ValidationError(
                f"Не совпадает. Чтобы удалить, введите: {self.expected}"
            )
        return value


def teachable_subjects():
    """
    Что можно закрепить за педагогом.

    Не только учебные предметы: профориентацию, проектную деятельность
    и рефлексию тоже кто-то ведёт. Из списка выпадает только обед —
    единственный блок дня, за которым нет человека.
    """
    from apps.journal.models import Subject

    return Subject.objects.filter(academic_year__is_current=True).exclude(
        name__iexact="Обед"
    ).order_by("kind", "position", "name")


# Поля, которые решают, что о педагоге видно на сайте. Их набор один
# и там, где педагога заводят, и там, где правят: раньше публичная
# карточка жила отдельно, и половину данных приходилось вводить дважды.
PUBLIC_TEACHER_FIELDS = [
    "photo", "subject_line", "experience", "bio",
    "is_published", "is_featured", "public_position",
]


class TeacherEditForm(forms.ModelForm):
    """
    Всё, что о педагоге знает журнал и видит сайт.

    Одна форма и там, где педагога заводят, и там, где правят: пока их
    было две, половину данных приходилось вводить дважды, а потом гадать,
    почему на сайте один предмет, а в расписании другой.
    """

    class Meta:
        model = Teacher
        fields = ["hourly_rate", "subjects", *PUBLIC_TEACHER_FIELDS]
        widgets = {
            "subjects": forms.CheckboxSelectMultiple,
            "bio": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subjects"].queryset = teachable_subjects()


class StaffForm(PersonForm):
    """
    Новый сотрудник — любой: владелец, администратор, педагог.

    Раньше педагогов заводили в одном разделе, а администраторов в другом,
    хотя действие одно и то же: завести человека и выдать ему доступ.
    Разделять их значило заставлять помнить, какая дверь для кого.
    """

    role = forms.ChoiceField(label="Роль", choices=[], initial=Role.TEACHER)

    def __init__(self, *args, roles=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = roles or role_choices()


class StaffIdentityForm(forms.ModelForm):
    """
    Имя и контакты сотрудника плюс его роли.

    Роли — галочками, а не выбором из списка: один человек бывает и
    владельцем, и педагогом сразу. Так устроен центр, и форма не должна
    заставлять выбирать.
    """

    roles = forms.MultipleChoiceField(
        label="Роли", choices=[], widget=forms.CheckboxSelectMultiple, required=False,
    )

    class Meta:
        model = get_user_model()
        fields = ["last_name", "first_name", "middle_name", "phone", "email"]

    def __init__(self, *args, roles=None, can_edit_roles: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        if not can_edit_roles:
            del self.fields["roles"]
            return
        self.fields["roles"].choices = roles or role_choices()

    def clean_roles(self):
        roles = set(self.cleaned_data.get("roles") or [])
        if not roles:
            raise forms.ValidationError(
                "Хотя бы одна роль нужна: без неё человек не попадёт никуда."
            )
        return roles


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["title", "period_start", "period_end", "amount", "due_on", "status"]
        widgets = {
            "period_start": forms.DateInput(attrs={"type": "date"}),
            "period_end": forms.DateInput(attrs={"type": "date"}),
            "due_on": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        data = super().clean()
        start, end = data.get("period_start"), data.get("period_end")
        if start and end and end < start:
            raise forms.ValidationError("Период заканчивается раньше, чем начинается.")
        return data


class ParentInviteForm(PersonForm):
    """
    Родитель к уже заведённому ребёнку.

    Ребёнка чаще всего заводят по договору с одним взрослым, а второй
    появляется позже. Логин и пароль генерируются так же — родитель
    ничего не заполняет сам: регистрация по ссылке означала бы, что
    доступ к данным ребёнка получает тот, кому ссылку переслали.
    """

    relation = forms.CharField(
        label="Кем приходится", max_length=40, required=False,
        help_text="Мама, папа, бабушка — как удобно.",
    )
    is_primary_contact = forms.BooleanField(
        label="Основной контакт", required=False, initial=False
    )


class SubjectForm(forms.ModelForm):
    """
    Предмет учебного года.

    Список не зашит в код: появится робототехника — её заводят здесь,
    а не ждут выката. Нагрузка в часах нужна для таблицы на сайте,
    у блоков дня она нулевая.
    """

    class Meta:
        model = Subject
        fields = ["name", "short_name", "kind", "weekly_hours", "position"]
        labels = {
            "name": "Название",
            "short_name": "Сокращение",
            "kind": "Тип",
            "weekly_hours": "Уроков в неделю",
            "position": "Порядок",
        }
        help_texts = {
            "kind": "Учебный предмет попадает в программу ФГОС и в оценивание. "
                    "Блок дня — только в расписание.",
            "short_name": "Для узких мест: «Инф.» вместо «Информатика».",
        }

    def clean_name(self):
        name = (self.cleaned_data["name"] or "").strip()
        year = self.instance.academic_year_id
        duplicates = Subject.objects.filter(name__iexact=name)
        if year:
            duplicates = duplicates.filter(academic_year_id=year)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("Такой предмет в этом году уже есть.")
        return name
