"""
Шифрование полей с персональными данными повышенной чувствительности (ТЗ 8.1).

Реализовано на cryptography.fernet: ключи берутся из FIELD_ENCRYPTION_KEYS
(первый — активный, остальные нужны только для расшифровки старых записей).
Библиотека django-cryptography не используется — она не поддерживает Django 5.

Ограничение осознанное: по зашифрованным полям нельзя фильтровать и сортировать
на стороне БД. Поэтому шифруются только те поля, по которым не ищут:
дата рождения, документы, адрес, дополнительные контакты.
"""
from __future__ import annotations

import datetime
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

PREFIX = "enc$"


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    keys = [k.strip() for k in (settings.FIELD_ENCRYPTION_KEYS or []) if k.strip()]
    if not keys:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEYS не задан. Сгенерируйте ключ: "
            "python manage.py generate_fernet_key"
        )
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt_str(value: str) -> str:
    return PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_str(value: str) -> str:
    if not value.startswith(PREFIX):
        # Данные, записанные до включения шифрования, читаем как есть.
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:  # pragma: no cover - сигнал о потере ключа
        raise ImproperlyConfigured(
            "Не удалось расшифровать поле: ключ FIELD_ENCRYPTION_KEYS не подходит. "
            "Старый ключ нужно оставить в списке до перешифровки."
        ) from exc


class EncryptedTextField(models.TextField):
    """Текст, зашифрованный на уровне поля."""

    def get_prep_value(self, value):
        if value in (None, ""):
            return value
        return encrypt_str(str(value))

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        return decrypt_str(value)

    def to_python(self, value):
        if value in (None, "") or not isinstance(value, str):
            return value
        if value.startswith(PREFIX):
            return decrypt_str(value)
        return value


class EncryptedCharField(EncryptedTextField):
    """Короткая строка. В БД всё равно text: шифротекст длиннее оригинала."""

    def __init__(self, *args, **kwargs):
        kwargs.pop("max_length", None)
        super().__init__(*args, **kwargs)


class EncryptedDateField(EncryptedTextField):
    """Дата (например, дата рождения ученика). Хранится как зашифрованный ISO-8601."""

    def get_prep_value(self, value):
        if value in (None, ""):
            return value
        if isinstance(value, (datetime.date, datetime.datetime)):
            value = value.isoformat()[:10]
        return encrypt_str(str(value))

    def from_db_value(self, value, expression, connection):
        raw = super().from_db_value(value, expression, connection)
        if not raw:
            return raw
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError:  # pragma: no cover
            return raw

    def to_python(self, value):
        if value in (None, ""):
            return value
        if isinstance(value, datetime.date):
            return value
        raw = super().to_python(value)
        if isinstance(raw, datetime.date):
            return raw
        try:
            return datetime.date.fromisoformat(str(raw)[:10])
        except ValueError:
            return raw

    def formfield(self, **kwargs):
        from django import forms

        return super().formfield(**{"form_class": forms.DateField, **kwargs})
