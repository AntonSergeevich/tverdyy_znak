"""Заявки с публичного сайта и содержимое, которое правит владелец."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import SoftDeleteTenantModel, TenantModel


class Lead(SoftDeleteTenantModel):
    """
    Заявка на бесплатную диагностику — единственное целевое действие сайта.

    Согласие на обработку ПДн фиксируется отдельным полем: временем и версией
    текста. Автосогласие по факту нажатия кнопки не допускается (ТЗ 4, 8.3).
    """

    class Status(models.TextChoices):
        NEW = "new", "новая"
        DIAGNOSTIC_SCHEDULED = "diagnostic_scheduled", "диагностика назначена"
        DIAGNOSTIC_DONE = "diagnostic_done", "диагностика проведена"
        CONTRACT = "contract", "договор"
        ENROLLED = "enrolled", "учится"
        DECLINED = "declined", "отказ"

    class CallWindow(models.TextChoices):
        MORNING = "09-12", "9:00–12:00"
        DAY = "12-15", "12:00–15:00"
        AFTERNOON = "15-18", "15:00–18:00"
        EVENING = "18-21", "18:00–21:00"

    class Segment(models.TextChoices):
        SELF_STUDY = "self_study", "ушёл на самообразование"
        EXAMS = "exams", "готовится к ОГЭ или ЕГЭ"
        CAREER = "career", "не выбрал направление"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("имя", max_length=60)
    phone = models.CharField("телефон", max_length=16)
    grade = models.PositiveSmallIntegerField(
        "класс ребёнка", validators=[MinValueValidator(8), MaxValueValidator(11)]
    )
    call_window = models.CharField("удобное время звонка", max_length=10, choices=CallWindow.choices)
    segment = models.CharField("сегмент", max_length=20, choices=Segment.choices, blank=True)
    comment = models.TextField("комментарий", max_length=2000, blank=True)

    consent_at = models.DateTimeField("согласие на обработку ПДн")
    policy_version = models.CharField("версия политики", max_length=32)

    utm_source = models.CharField(max_length=120, blank=True)
    utm_medium = models.CharField(max_length=120, blank=True)
    utm_campaign = models.CharField(max_length=120, blank=True)
    utm_content = models.CharField(max_length=120, blank=True)
    utm_term = models.CharField(max_length=120, blank=True)
    referrer = models.CharField("реферер", max_length=500, blank=True)
    page_path = models.CharField("страница", max_length=300, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("user-agent", max_length=300, blank=True)

    status = models.CharField(
        "статус", max_length=24, choices=Status.choices, default=Status.NEW, db_index=True
    )
    decline_reason = models.CharField("причина отказа", max_length=250, blank=True)
    status_changed_at = models.DateTimeField("статус изменён", default=timezone.now)
    manager_note = models.TextField("заметка администратора", blank=True)
    notified_at = models.DateTimeField("уведомление отправлено", null=True, blank=True)

    class Meta:
        verbose_name = "заявка"
        verbose_name_plural = "заявки"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status", "-created_at"]),
            models.Index(fields=["organization", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} · {self.phone} · {self.get_status_display()}"

    def clean(self):
        super().clean()
        # Причина отказа обязательна (ТЗ 5.4).
        if self.status == self.Status.DECLINED and not self.decline_reason.strip():
            raise ValidationError({"decline_reason": "Укажите причину отказа."})

    @property
    def phone_display(self) -> str:
        digits = self.phone
        if len(digits) == 11:
            return f"+{digits[0]} ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:]}"
        return digits


class FaqItem(TenantModel):
    """Вопрос-ответ на лендинге. Правится владельцем без разработчика."""

    question = models.CharField("вопрос", max_length=250)
    answer = models.TextField("ответ")
    position = models.PositiveSmallIntegerField("порядок", default=100)
    is_published = models.BooleanField("опубликован", default=True)

    class Meta:
        verbose_name = "вопрос FAQ"
        verbose_name_plural = "вопросы FAQ"
        ordering = ["position", "id"]
        indexes = [models.Index(fields=["organization", "is_published", "position"])]

    def __str__(self) -> str:
        return self.question


class TeacherCard(TenantModel):
    """
    Карточка педагога для публичной страницы.

    Отдельно от journal.Teacher: на сайт попадает только то, что педагог
    разрешил публиковать, а не его учётные данные.
    """

    full_name = models.CharField("имя", max_length=120)
    subject_line = models.CharField("предмет", max_length=120)
    experience = models.CharField("опыт", max_length=200, blank=True)
    bio = models.TextField("о педагоге", blank=True)
    photo = models.ImageField("фото", upload_to="teachers/", blank=True)
    position = models.PositiveSmallIntegerField("порядок", default=100)
    is_published = models.BooleanField("опубликован", default=True)
    is_featured = models.BooleanField(
        "крупная карточка", default=False,
        help_text="Показывается на главной большим блоком с полным текстом. "
                  "Остальные — компактной лентой: педагогов со временем станет "
                  "больше, и одинаковых карточек в ряд будет не разглядеть.",
    )

    class Meta:
        verbose_name = "карточка педагога"
        verbose_name_plural = "карточки педагогов"
        ordering = ["position", "full_name"]

    def __str__(self) -> str:
        return self.full_name


class TeacherReview(TenantModel):
    """
    Отзыв родителя о педагоге.

    Оставить его можно только из кабинета и только про того, кто учит
    твоего ребёнка: анонимный отзыв на сайте центра — это не обратная
    связь, а канал для случайного человека.

    На сайт отзыв попадает после проверки администратором. Дело не
    в цензуре: публичная страница — зона ответственности организации,
    и то, что там появляется, должно быть кем-то прочитано.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "на проверке"
        PUBLISHED = "published", "опубликован"
        REJECTED = "rejected", "отклонён"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher = models.ForeignKey(
        "journal.Teacher", on_delete=models.CASCADE, related_name="reviews",
        verbose_name="педагог",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="teacher_reviews", verbose_name="автор",
    )
    # Подпись хранится снимком: родитель может уйти, а отзыв на сайте
    # останется — и должен остаться подписанным так же, как был.
    author_label = models.CharField("подпись", max_length=120, blank=True)
    rating = models.PositiveSmallIntegerField(
        "оценка", validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    text = models.TextField("отзыв", max_length=2000)
    status = models.CharField(
        "статус", max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="moderated_reviews", verbose_name="кто проверил",
    )
    moderated_at = models.DateTimeField("проверен", null=True, blank=True)

    class Meta:
        verbose_name = "отзыв о педагоге"
        verbose_name_plural = "отзывы о педагогах"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "teacher", "status"]),
        ]
        constraints = [
            # Один родитель — один отзыв на педагога. Иначе страница
            # педагога превращается в переписку.
            models.UniqueConstraint(
                fields=["teacher", "author"], condition=models.Q(author__isnull=False),
                name="teacher_review_one_per_author",
            )
        ]

    def __str__(self) -> str:
        return f"{self.author_label} о {self.teacher}"

    @property
    def stars(self) -> str:
        return "★" * self.rating + "☆" * (5 - self.rating)


class LegalDocument(TenantModel):
    """Правовая страница: политика, согласие, пользовательское соглашение."""

    class Kind(models.TextChoices):
        PRIVACY = "privacy", "политика обработки персональных данных"
        CONSENT = "consent", "согласие на обработку персональных данных"
        TERMS = "terms", "пользовательское соглашение"

    kind = models.CharField("тип", max_length=20, choices=Kind.choices)
    title = models.CharField("заголовок", max_length=200)
    body = models.TextField("текст (Markdown-подобный простой текст)")
    version = models.CharField("версия", max_length=32)
    edited_on = models.DateField("дата редакции", default=timezone.localdate)

    class Meta:
        verbose_name = "правовой документ"
        verbose_name_plural = "правовые документы"
        constraints = [
            models.UniqueConstraint(fields=["organization", "kind"], name="legal_document_unique")
        ]

    def __str__(self) -> str:
        return self.title
