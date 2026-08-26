"""Аутентификация по email или телефону."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from apps.accounts.models import normalize_phone


class EmailOrPhoneBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = (username or kwargs.get("email") or "").strip()
        if not identifier or password is None:
            return None

        # Логин, email или телефон — человек не должен помнить, что именно
        # ему выдали. Пустые поля из поиска исключены: иначе пустой
        # username совпал бы у всех сразу.
        phone = normalize_phone(identifier)
        query = Q(username__iexact=identifier) & ~Q(username="")
        query |= Q(email__iexact=identifier) & ~Q(email="")
        if phone:
            query |= Q(phone=phone)

        # Один запрос вместо двух; при коллизии берём активного.
        user = User.objects.filter(query).order_by("-is_active").first()
        if user is None:
            # Выравниваем время ответа, чтобы нельзя было перебрать логины.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
