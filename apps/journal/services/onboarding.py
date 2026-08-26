"""
Выдача доступов: учётная запись создаётся вместе с человеком.

Родители и подростки не заводят аккаунты сами — это делает администратор
и отдаёт логин с паролем лично. Поэтому логин должен быть таким, чтобы
его можно было продиктовать по телефону, а пароль — прочитать вслух и
не перепутать «l» с «1».

Здесь только создание доступов. Кто имеет право их выдавать, решают
декораторы во вью: смешивать эти два вопроса в одном месте — надёжный
способ однажды выдать лишнего.
"""
from __future__ import annotations

import secrets
import string
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.accounts.models import Membership, Role, normalize_phone

# Транслитерация по ГОСТ-подобной таблице. Своя, а не библиотека:
# зависимость ради одного словаря не окупается, а результат надо
# контролировать — логин человек будет диктовать голосом.
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

# Слоги для пароля: читаются вслух без ошибок и не складываются в слова,
# которые неловко диктовать.
SYLLABLES = [
    "ba", "ve", "gi", "do", "zu", "ka", "le", "mi", "no", "pu",
    "ra", "se", "ti", "fo", "hu", "cha", "she", "yu", "ya", "za",
]
# Из цифр выброшены 0 и 1: их путают с «o» и «l» при переписывании с листа.
DIGITS = "23456789"


@dataclass(frozen=True)
class Credentials:
    """Что администратор передаёт человеку. Пароль существует только здесь."""

    login: str
    password: str
    full_name: str
    role_label: str


def transliterate(text: str) -> str:
    result = []
    for char in (text or "").lower():
        if char in TRANSLIT:
            result.append(TRANSLIT[char])
        elif char in string.ascii_lowercase or char.isdigit():
            result.append(char)
    return "".join(result)


def generate_password(syllables: int = 3) -> str:
    """Три слога и две цифры: «bamiro-47». Диктуется по телефону без боли."""
    body = "".join(secrets.choice(SYLLABLES) for _ in range(syllables))
    tail = "".join(secrets.choice(DIGITS) for _ in range(2))
    return f"{body}-{tail}"


def build_login(last_name: str, first_name: str, domain: str) -> str:
    """
    Фамилия и первая буква имени: petrova.m@tverdyy-znak.ru.

    Это настоящий email-адрес по форме, поэтому вход работает без
    отдельного поля «логин»: пользователь входит по email или телефону.
    """
    User = get_user_model()
    base = transliterate(last_name) or "user"
    initial = transliterate(first_name)[:1]
    stem = f"{base}.{initial}" if initial else base

    candidate = f"{stem}@{domain}"
    suffix = 2
    while User.objects.filter(email__iexact=candidate).exists():
        candidate = f"{stem}{suffix}@{domain}"
        suffix += 1
    return candidate


def login_domain(organization) -> str:
    """
    Домен для логинов.

    Берём основной домен организации: логин на чужом домене выглядит
    подозрительно и хуже запоминается.
    """
    return organization.primary_domain or f"{organization.slug}.local"


@transaction.atomic
def issue_account(
    *,
    organization,
    role: str,
    last_name: str,
    first_name: str,
    middle_name: str = "",
    phone: str = "",
    email: str = "",
) -> tuple["object", Credentials]:
    """
    Завести учётную запись и выдать доступ.

    Возвращает пользователя и учётные данные. Пароль нигде не сохраняется
    в открытом виде — если его потеряли, выдаётся новый.
    """
    User = get_user_model()
    login = (email or "").strip().lower() or build_login(
        last_name, first_name, login_domain(organization)
    )
    password = generate_password()

    user = User.objects.create_user(
        email=login,
        phone=normalize_phone(phone),
        password=password,
        last_name=last_name.strip(),
        first_name=first_name.strip(),
        middle_name=middle_name.strip(),
    )
    Membership.objects.create(user=user, organization=organization, role=role)

    return user, Credentials(
        login=login,
        password=password,
        full_name=user.full_name,
        role_label=Role(role).label,
    )


@transaction.atomic
def reset_password(user) -> Credentials:
    """
    Выдать новый пароль вместо забытого.

    Старый восстановить нельзя — он хранится только хэшем, и это
    правильно. Администратор просто выдаёт новый.
    """
    password = generate_password()
    user.set_password(password)
    user.save(update_fields=["password", "updated_at"])

    membership = user.memberships.filter(is_active=True).first()
    return Credentials(
        login=user.email or user.phone,
        password=password,
        full_name=user.full_name,
        role_label=Role(membership.role).label if membership else "",
    )
