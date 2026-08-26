"""
Пользователи, роли и второй фактор.

Кастомная модель User заведена в первой миграции приложения (ТЗ 9.1) —
менять её позже нельзя без потери базы.
"""
from __future__ import annotations

import secrets
import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import Organization, TimeStampedModel


def normalize_phone(raw: str) -> str:
    """+7 (391) 123-45-67 → 79911234567. Пустая строка остаётся пустой."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if not digits:
        return ""
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return digits


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, phone, password, **extra):
        username = (extra.pop("username", "") or "").lower().strip()
        if not (email or phone or username):
            raise ValueError("Нужен логин, email или телефон")
        email = self.normalize_email(email) if email else ""
        user = self.model(
            username=username, email=email.lower(), phone=normalize_phone(phone), **extra
        )
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email=None, phone=None, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, phone, password, **extra)

    def create_superuser(self, email=None, phone=None, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if extra["is_staff"] is not True or extra["is_superuser"] is not True:
            raise ValueError("Суперпользователь должен иметь is_staff и is_superuser")
        return self._create(email, phone, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Вход по email или телефону. Пароли — только штатным хэшером (Argon2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Короткий логин, который выдаёт администратор: «sokolova», а не
    # «sokolova.v@tverdyy-znak.ru». Его диктуют по телефону и вводят
    # с листа, поэтому длина здесь — не мелочь.
    username = models.CharField("логин", max_length=60, blank=True, default="")
    email = models.EmailField("email", blank=True, default="")
    phone = models.CharField("телефон", max_length=16, blank=True, default="")
    last_name = models.CharField("фамилия", max_length=80, blank=True)
    first_name = models.CharField("имя", max_length=80, blank=True)
    middle_name = models.CharField("отчество", max_length=80, blank=True)

    is_active = models.BooleanField("активен", default=True)
    is_staff = models.BooleanField("доступ в админку Django", default=False)
    last_activity_at = models.DateTimeField("последняя активность", null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["username"], condition=~models.Q(username=""),
                name="user_username_unique_not_blank",
            ),
            models.UniqueConstraint(
                fields=["email"], condition=~models.Q(email=""), name="user_email_unique_not_blank"
            ),
            models.UniqueConstraint(
                fields=["phone"], condition=~models.Q(phone=""), name="user_phone_unique_not_blank"
            ),
        ]

    def __str__(self) -> str:
        return self.full_name or self.login or str(self.pk)

    @property
    def login(self) -> str:
        """Чем человек входит. Короткий логин, если он есть."""
        return self.username or self.email or self.phone

    def clean(self):
        super().clean()
        if not (self.username or self.email or self.phone):
            raise ValidationError("Укажите логин, email или телефон — ими входят.")
        self.username = (self.username or "").lower().strip()
        self.email = (self.email or "").lower().strip()
        self.phone = normalize_phone(self.phone)

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p).strip()

    @property
    def short_name(self) -> str:
        if self.last_name and self.first_name:
            return f"{self.last_name} {self.first_name[0]}."
        return self.full_name or self.email or self.phone

    def get_full_name(self) -> str:
        return self.full_name

    def get_short_name(self) -> str:
        return self.short_name

    # ── Роли ────────────────────────────────────────────────────────────────
    def memberships_in(self, organization) -> models.QuerySet["Membership"]:
        return self.memberships.filter(organization=organization, is_active=True)

    def roles_in(self, organization) -> set[str]:
        return set(self.memberships_in(organization).values_list("role", flat=True))

    def has_role(self, organization, *roles: str) -> bool:
        if organization is None:
            return False
        return bool(self.roles_in(organization) & set(roles))

    @property
    def requires_two_factor(self) -> bool:
        """
        Второй фактор обязателен для владельца, администратора и админа
        платформы (ТЗ 8.2).

        Глобальный выключатель TWO_FACTOR_ENABLED нужен только на время
        приёмки, пока в базе нет данных учеников.
        """
        from django.conf import settings

        if not settings.TWO_FACTOR_ENABLED:
            return False
        return self.memberships.filter(
            is_active=True, role__in=PRIVILEGED_ROLES
        ).exists() or self.is_superuser


class Role(models.TextChoices):
    PLATFORM_ADMIN = "platform_admin", "администратор платформы"
    OWNER = "owner", "владелец организации"
    ADMIN = "admin", "администратор"
    TEACHER = "teacher", "педагог"
    PARENT = "parent", "родитель"
    STUDENT = "student", "ученик"


# Списки ролей держим вне TextChoices: любой атрибут внутри enum стал бы его членом.
PRIVILEGED_ROLES = (Role.PLATFORM_ADMIN, Role.OWNER, Role.ADMIN)
STAFF_ROLES = PRIVILEGED_ROLES + (Role.TEACHER,)
ORG_MANAGER_ROLES = (Role.OWNER, Role.ADMIN)


class Membership(TimeStampedModel):
    """
    Роль пользователя в организации.

    У пользователя может быть несколько ролей и несколько организаций
    (например, педагог в одной и родитель в другой) — ТЗ 3.2.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField("роль", max_length=20, choices=Role.choices, db_index=True)
    is_active = models.BooleanField("активна", default=True)

    objects = models.Manager()

    class Meta:
        verbose_name = "роль в организации"
        verbose_name_plural = "роли в организациях"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization", "role"], name="membership_unique"
            )
        ]
        indexes = [models.Index(fields=["organization", "role", "is_active"])]

    def __str__(self) -> str:
        return f"{self.user} — {self.get_role_display()} ({self.organization})"


class TwoFactorDevice(TimeStampedModel):
    """TOTP-устройство. Обязательно для привилегированных ролей (ТЗ 8.2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="totp_device")
    secret = models.CharField("секрет (base32)", max_length=64)
    is_confirmed = models.BooleanField("подтверждено", default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_counter = models.BigIntegerField("последний использованный шаг", default=0)
    recovery_codes = models.JSONField("резервные коды (хэши)", default=list, blank=True)

    objects = models.Manager()

    class Meta:
        verbose_name = "второй фактор"
        verbose_name_plural = "вторые факторы"

    def __str__(self) -> str:
        return f"TOTP {self.user}"

    def confirm(self):
        self.is_confirmed = True
        self.confirmed_at = timezone.now()
        self.save(update_fields=["is_confirmed", "confirmed_at", "updated_at"])

    def generate_recovery_codes(self, count: int = 8) -> list[str]:
        from django.contrib.auth.hashers import make_password

        codes = [f"{secrets.randbelow(10**10):010d}" for _ in range(count)]
        self.recovery_codes = [make_password(code) for code in codes]
        self.save(update_fields=["recovery_codes", "updated_at"])
        return codes

    def consume_recovery_code(self, code: str) -> bool:
        from django.contrib.auth.hashers import check_password

        for stored in list(self.recovery_codes):
            if check_password(code.strip(), stored):
                remaining = [c for c in self.recovery_codes if c != stored]
                self.recovery_codes = remaining
                self.save(update_fields=["recovery_codes", "updated_at"])
                return True
        return False
