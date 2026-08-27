"""Организация, базовые абстрактные модели, журнал доступа и согласия."""
from __future__ import annotations

import uuid
import zoneinfo

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.managers import AllObjectsManager, TenantManager


def _timezone_choices():
    common = [
        "Europe/Kaliningrad", "Europe/Moscow", "Europe/Samara", "Asia/Yekaterinburg",
        "Asia/Omsk", "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Yakutsk",
        "Asia/Vladivostok", "Asia/Magadan", "Asia/Kamchatka", "UTC",
    ]
    return [(tz, tz) for tz in common if tz in zoneinfo.available_timezones()]


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("создано", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("изменено", auto_now=True)

    class Meta:
        abstract = True


class Organization(TimeStampedModel):
    """
    Арендатор платформы (ТЗ 3.1).

    Организация — не «школа»: у центра нет образовательной лицензии,
    слово «школа» в названиях моделей, полей и текстов не используется.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("название", max_length=200)
    slug = models.SlugField("код", max_length=60, unique=True)
    legal_name = models.CharField("юридическое наименование", max_length=250, blank=True)
    inn = models.CharField("ИНН", max_length=12, blank=True)
    ogrnip = models.CharField("ОГРНИП", max_length=15, blank=True)

    contact_phone = models.CharField("телефон", max_length=32, blank=True)
    contact_email = models.EmailField("email", blank=True)
    address = models.CharField("адрес", max_length=300, blank=True)
    telegram_chat_id = models.CharField("Telegram chat_id для заявок", max_length=64, blank=True)

    # Ссылка на общий файл с расписанием (Яндекс.Документы, Google Sheets).
    # Показывается только в кабинете и нужна как временная опора, пока
    # занятия не заведены в журнале: сетку из файла загружает
    # `manage.py import_schedule`, и после загрузки ссылка остаётся
    # справочной — для тех, кто привык смотреть исходник.
    schedule_url = models.URLField("ссылка на файл с расписанием", max_length=500, blank=True)

    # ── Банковские реквизиты для оплаты ─────────────────────────────────────
    # Показываются только в кабинете родителя. В подвале сайта — лишь
    # наименование, ИНН, ОГРНИП и адрес: номер счёта там ни к чему.
    bank_name = models.CharField("банк", max_length=200, blank=True)
    bank_bik = models.CharField("БИК", max_length=9, blank=True)
    bank_account = models.CharField("расчётный счёт", max_length=20, blank=True)
    bank_corr_account = models.CharField("корреспондентский счёт", max_length=20, blank=True)

    timezone = models.CharField(
        "часовой пояс", max_length=64, default="Asia/Krasnoyarsk", choices=_timezone_choices
    )
    is_active = models.BooleanField("активна", default=True)

    # ── Настройки предметной области (не глобальные, ТЗ 9.4) ────────────────
    module_max_points = models.DecimalField(
        "максимум баллов за модуль", max_digits=5, decimal_places=2, default=100,
        validators=[MinValueValidator(1)],
    )
    lesson_max_points = models.DecimalField(
        "максимум баллов за одно занятие", max_digits=5, decimal_places=2, default=5
    )
    grade_backdate_days = models.PositiveSmallIntegerField(
        "на сколько дней назад можно выставлять баллы", default=14
    )
    data_retention_days = models.PositiveIntegerField(
        "срок хранения персональных данных после отчисления, дней", default=365 * 3
    )
    lead_retention_days = models.PositiveIntegerField(
        "срок хранения необработанных заявок, дней", default=365
    )

    # ── Тексты первого экрана ───────────────────────────────────────────────
    # Правятся в админке: подбор формулировки не должен требовать деплоя.
    hero_kicker = models.CharField(
        "надзаголовок на первом экране", max_length=200,
        default="Семейный класс «Твёрдый знак» · Красноярск · 8–11 класс",
    )
    hero_title = models.CharField(
        "заголовок на первом экране", max_length=120,
        default="Вся учёба — в одном месте",
        help_text="Коротко: шрифт заголовка рендерит строчные капителью, "
                  "и длинный текст в три строки выглядит тяжело.",
    )
    hero_lead = models.TextField(
        "лид на первом экране",
        default="Подросток учится модулями по 5 недель, видит свою дорожную карту "
                "и получает баллы за конкретную работу. Вы видите то же, что и он.",
    )

    # ── Публичные тексты и цены ─────────────────────────────────────────────
    price_full_month = models.PositiveIntegerField("цена полного формата, ₽/мес", default=70000)
    price_program_month = models.PositiveIntegerField(
        "образовательная программа и подготовка к аттестации, ₽/мес", default=40000
    )
    price_mentor_month = models.PositiveIntegerField(
        "наставник, профориентация и подготовка к поступлению, ₽/мес", default=30000
    )
    price_entry_year = models.PositiveIntegerField("вступительный взнос, ₽/год", default=15000)
    price_career = models.PositiveIntegerField("цена профориентации отдельно, ₽", default=0)
    tutors_reference_price = models.PositiveIntegerField(
        "справочный счёт за репетиторов, ₽/мес", default=88000
    )
    tutors_reference_note = models.CharField(
        "расчёт справочного счёта", max_length=200,
        default="2 занятия в неделю × 4 предмета × 1 100 ₽",
    )

    objects = models.Manager()

    class Meta:
        verbose_name = "организация"
        verbose_name_plural = "организации"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def tzinfo(self) -> zoneinfo.ZoneInfo:
        return zoneinfo.ZoneInfo(self.timezone)

    def localtime(self, value=None):
        return timezone.localtime(value or timezone.now(), self.tzinfo)

    @property
    def map_query(self) -> str:
        """
        Что искать на карте.

        Адрес в карточке пишется без страны и иногда без города — для
        подвала так и надо. Виджету же короткая строка вроде «ул. Весны, 10»
        даёт обзор всей России вместо точки, поэтому недостающее
        дописываем здесь.
        """
        address = (self.address or "").strip()
        if not address:
            return ""
        parts = [address]
        if "россия" not in address.lower():
            parts.insert(0, "Россия")
        return ", ".join(parts)

    @property
    def primary_domain(self) -> str | None:
        domain = self.domains.filter(is_primary=True).first() or self.domains.first()
        return domain.host if domain else None


class OrganizationDomain(TimeStampedModel):
    """Хост, по которому определяется организация запроса."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="domains", verbose_name="организация"
    )
    host = models.CharField("хост", max_length=253, unique=True, db_index=True)
    is_primary = models.BooleanField("основной", default=False)

    objects = models.Manager()

    class Meta:
        verbose_name = "домен организации"
        verbose_name_plural = "домены организаций"
        ordering = ["-is_primary", "host"]

    def __str__(self) -> str:
        return self.host

    def save(self, *args, **kwargs):
        self.host = self.host.strip().lower()
        super().save(*args, **kwargs)


class TenantModel(TimeStampedModel):
    """
    База для всех доменных моделей: обязательная привязка к организации.

    `objects` фильтрует по текущей организации автоматически,
    `all_objects` — без фильтра, только для админки и обслуживания.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="%(class)ss", verbose_name="организация"
    )

    objects = TenantManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True


class SoftDeleteTenantModel(TenantModel):
    """
    Доменная модель с мягким удалением (ТЗ 9.5).

    Ученика, оценку или договор нельзя терять физически: восстановление
    посреди учебного года должно быть возможно.
    """

    deleted_at = models.DateTimeField("удалено", null=True, blank=True, db_index=True)

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def delete(self, using=None, keep_parents=False):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"])


class AuditAction(models.TextChoices):
    LOGIN = "login", "вход в систему"
    LOGIN_FAILED = "login_failed", "неудачный вход"
    LOGOUT = "logout", "выход"
    VIEW_STUDENT = "view_student", "просмотр карточки ученика"
    VIEW_LEAD = "view_lead", "просмотр заявки"
    GRADE_CHANGED = "grade_changed", "изменение оценки"
    GRADE_DELETED = "grade_deleted", "удаление оценки"
    EXPORT = "export", "экспорт данных"
    PERMISSION_CHANGED = "permission_changed", "изменение прав"
    CONSENT_GRANTED = "consent_granted", "согласие получено"
    CONSENT_REVOKED = "consent_revoked", "согласие отозвано"
    DATA_PURGED = "data_purged", "удаление по истечении срока хранения"
    TWO_FACTOR_RESET = "two_factor_reset", "сброс второго фактора"
    PASSWORD_CHANGED = "password_changed", "смена пароля"


class AuditLog(models.Model):
    """
    Кто, когда, что посмотрел или изменил (ТЗ 8.4).

    Живёт отдельно от доменных данных и не удаляется вместе с ними,
    поэтому organization и actor — SET_NULL, а не CASCADE.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    actor_label = models.CharField("кто (снимок)", max_length=200, blank=True)
    action = models.CharField("действие", max_length=32, choices=AuditAction.choices, db_index=True)
    object_type = models.CharField("тип объекта", max_length=64, blank=True)
    object_id = models.CharField("id объекта", max_length=64, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("user-agent", max_length=300, blank=True)
    extra = models.JSONField("подробности", default=dict, blank=True)
    created_at = models.DateTimeField("когда", default=timezone.now, db_index=True)

    objects = models.Manager()

    class Meta:
        verbose_name = "запись журнала доступа"
        verbose_name_plural = "журнал доступа к данным"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_label} {self.action}"


class ConsentType(models.TextChoices):
    PDN = "pdn", "обработка персональных данных"
    MINOR_PDN = "minor_pdn", "обработка данных несовершеннолетнего"
    MARKETING = "marketing", "информационные рассылки"
    COOKIE = "cookie", "необязательные cookie"


class Consent(TimeStampedModel):
    """
    Факт согласия: кто, когда, на что и какую версию текста подписал (ТЗ 8.3).

    Отзыв согласия — отдельное поле revoked_at, запись не удаляется.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="consents"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="consents",
    )
    subject_label = models.CharField("на кого распространяется", max_length=200, blank=True)
    consent_type = models.CharField("тип", max_length=20, choices=ConsentType.choices)
    document_version = models.CharField("версия документа", max_length=32)
    granted_at = models.DateTimeField("дано", default=timezone.now)
    revoked_at = models.DateTimeField("отозвано", null=True, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("user-agent", max_length=300, blank=True)

    objects = models.Manager()

    class Meta:
        verbose_name = "согласие"
        verbose_name_plural = "согласия"
        ordering = ["-granted_at"]
        indexes = [models.Index(fields=["organization", "consent_type", "-granted_at"])]

    def __str__(self) -> str:
        return f"{self.get_consent_type_display()} · {self.subject_label or self.user_id}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
