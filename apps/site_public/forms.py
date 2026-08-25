"""Форма заявки: валидация, согласие отдельным чекбоксом, антиспам (ТЗ 4)."""
from __future__ import annotations

import time

from django import forms
from django.conf import settings
from django.utils import timezone

from apps.accounts.models import normalize_phone
from apps.site_public.models import Lead

HONEYPOT_FIELD = "company_site"
TIMESTAMP_FIELD = "form_rendered_at"


class LeadForm(forms.ModelForm):
    consent = forms.BooleanField(
        label="Я даю согласие на обработку персональных данных",
        required=True,
        error_messages={"required": "Без согласия на обработку данных заявку отправить нельзя."},
    )
    # Отдельное поле, а не унаследованное от модели: в форму приходит
    # телефон в маске (+7 (913) 000-11-22), он длиннее хранимых 11 цифр.
    phone = forms.CharField(
        label="Телефон",
        max_length=25,
        widget=forms.TextInput(
            attrs={
                "inputmode": "tel",
                "autocomplete": "tel",
                "placeholder": "+7 (___) ___-__-__",
                "data-phone-mask": "true",
            }
        ),
        error_messages={"required": "Без телефона мы не сможем позвонить."},
    )
    # Honeypot: настоящий человек его не видит и не заполняет.
    company_site = forms.CharField(required=False, widget=forms.HiddenInput)
    form_rendered_at = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Lead
        fields = ["name", "phone", "grade", "call_window", "segment", "comment"]
        labels = {
            "name": "Как вас зовут",
            "phone": "Телефон",
            "grade": "Класс ребёнка",
            "call_window": "Когда удобно позвонить",
            "segment": "Что ближе к вашей ситуации",
            "comment": "Что важно рассказать заранее",
        }
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Имя"}),
            "comment": forms.Textarea(attrs={"rows": 3}),
            "segment": forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["grade"] = forms.TypedChoiceField(
            label="Класс ребёнка",
            choices=[("", "Выберите класс")] + [(g, f"{g} класс") for g in (8, 9, 10, 11)],
            coerce=int,
            error_messages={"required": "Выберите класс ребёнка."},
        )
        self.fields["call_window"].choices = [("", "Выберите время")] + list(
            Lead.CallWindow.choices
        )
        self.fields["segment"].required = False
        self.fields["comment"].required = False
        self.fields[TIMESTAMP_FIELD].initial = str(int(time.time()))

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if len(name) < 2:
            raise forms.ValidationError("Имя слишком короткое.")
        if len(name) > 60:
            raise forms.ValidationError("Имя слишком длинное.")
        return name

    def clean_phone(self):
        digits = normalize_phone(self.cleaned_data.get("phone", ""))
        if len(digits) != 11 or not digits.startswith("7"):
            raise forms.ValidationError("Введите телефон полностью: +7 и 10 цифр.")
        return digits

    def clean(self):
        cleaned = super().clean()
        if cleaned.get(HONEYPOT_FIELD):
            # Молча притворяемся, что поле обязательное: боту незачем знать про ловушку.
            raise forms.ValidationError("Не удалось отправить заявку. Попробуйте ещё раз.")

        rendered_at = cleaned.get(TIMESTAMP_FIELD)
        if rendered_at and rendered_at.isdigit():
            elapsed = int(time.time()) - int(rendered_at)
            if 0 <= elapsed < settings.LEAD_MIN_FILL_SECONDS:
                raise forms.ValidationError("Форма заполнена слишком быстро. Проверьте данные и отправьте ещё раз.")
        return cleaned

    def save(self, commit=True, **extra):
        lead: Lead = super().save(commit=False)
        lead.consent_at = timezone.now()
        lead.policy_version = settings.LEGAL_DOC_VERSION
        for field, value in extra.items():
            setattr(lead, field, value)
        if commit:
            lead.save()
        return lead
