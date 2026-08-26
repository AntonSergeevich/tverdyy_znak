"""
Формы кабинета.

Формы здесь только проверяют ввод. Создание учётных записей живёт
в services/onboarding.py: форма не должна знать, как устроены пароли.
"""
from __future__ import annotations

import datetime as dt

from django import forms

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


class TeacherForm(PersonForm):
    hourly_rate = forms.DecimalField(
        label="Ставка за час, ₽", max_digits=8, decimal_places=2, min_value=0, initial=0,
    )
    public_title = forms.CharField(label="Подпись для сайта", max_length=200, required=False)
    subjects = forms.ModelMultipleChoiceField(
        label="Предметы", queryset=Subject.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.journal.models import SubjectKind

        self.fields["subjects"].queryset = Subject.objects.filter(
            academic_year__is_current=True, kind=SubjectKind.ACADEMIC
        )


class TeacherEditForm(forms.ModelForm):
    class Meta:
        model = Teacher
        fields = ["hourly_rate", "public_title", "subjects"]
        widgets = {"subjects": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.journal.models import SubjectKind

        self.fields["subjects"].queryset = Subject.objects.filter(
            academic_year__is_current=True, kind=SubjectKind.ACADEMIC
        )


class StaffForm(PersonForm):
    """Администратор или владелец. Роль выбирается явно, а не угадывается."""

    role = forms.ChoiceField(
        label="Роль",
        choices=[("admin", "администратор"), ("owner", "владелец")],
        initial="admin",
    )


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


class ParentForm(PersonForm):
    """Родитель отдельно: у ребёнка их может быть несколько."""
