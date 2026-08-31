"""
Предметная область: учебный год, модули, занятия, оценивание.

Терминология: организация — центр семейного обучения, а не школа.
Слово «школа» встречается только в поле аттестации, где речь идёт
об аккредитованной школе-партнёре.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.fields import EncryptedCharField, EncryptedDateField
from apps.core.managers import AllObjectsManager, TenantManager
from apps.core.models import SoftDeleteTenantModel, TenantModel
from apps.core.storage import private_storage

POINTS = {"max_digits": 5, "decimal_places": 2}  # Decimal, никогда float (ТЗ 9.1)


class AcademicYear(TenantModel):
    title = models.CharField("учебный год", max_length=20)  # «2026/27»
    starts_on = models.DateField("начало")
    ends_on = models.DateField("конец")
    is_current = models.BooleanField("текущий", default=False)

    class Meta:
        verbose_name = "учебный год"
        verbose_name_plural = "учебные годы"
        ordering = ["-starts_on"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "title"], name="academic_year_unique")
        ]

    def __str__(self) -> str:
        return self.title


class SubjectKind(models.TextChoices):
    """
    В расписании стоят не только предметы.

    Утренний круг, обед, рефлексия и проектная деятельность занимают место
    в дне и должны быть видны в кабинете, но 100 баллов по ним не
    раскладываются: оценивается учебный предмет, а не режим дня.
    """

    ACADEMIC = "academic", "учебный предмет"
    ACTIVITY = "activity", "блок дня без баллов"


class Subject(TenantModel):
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name="subjects", verbose_name="учебный год"
    )
    name = models.CharField("предмет", max_length=120)
    short_name = models.CharField("сокращение", max_length=20, blank=True)
    kind = models.CharField(
        "тип", max_length=10, choices=SubjectKind.choices, default=SubjectKind.ACADEMIC
    )
    weekly_hours = models.PositiveSmallIntegerField("часов в неделю", default=1)
    position = models.PositiveSmallIntegerField("порядок", default=100)

    class Meta:
        verbose_name = "предмет"
        verbose_name_plural = "предметы"
        ordering = ["position", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "academic_year", "name"], name="subject_unique"
            )
        ]
        indexes = [models.Index(fields=["organization", "academic_year"])]

    def __str__(self) -> str:
        return self.name

    @property
    def is_graded(self) -> bool:
        return self.kind == SubjectKind.ACADEMIC


class ModuleKind(models.TextChoices):
    MODULE = "module", "учебный модуль"
    VACATION = "vacation", "каникулярная неделя"


class Module(TenantModel):
    """
    Учебный модуль (ТЗ 3.5).

    Каникулярные недели тоже хранятся здесь: на них назначаются консультации
    для тех, кто добирает баллы после незачёта.
    """

    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name="modules", verbose_name="учебный год"
    )
    kind = models.CharField("тип", max_length=10, choices=ModuleKind.choices, default=ModuleKind.MODULE)
    number = models.PositiveSmallIntegerField("номер")
    title = models.CharField("тема", max_length=200, blank=True)
    focus = models.CharField("смысловой фокус", max_length=200, blank=True)
    starts_on = models.DateField("начало")
    ends_on = models.DateField("конец")

    class Meta:
        verbose_name = "модуль"
        verbose_name_plural = "модули"
        ordering = ["starts_on"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "academic_year", "kind", "number"], name="module_unique"
            )
        ]
        indexes = [models.Index(fields=["organization", "starts_on", "ends_on"])]

    def __str__(self) -> str:
        if self.kind == ModuleKind.VACATION:
            return f"Каникулы {self.number}"
        return f"Модуль {self.number}"

    @property
    def weeks(self) -> int:
        return max(1, round((self.ends_on - self.starts_on).days / 7))

    @property
    def days_left(self) -> int:
        return max(0, (self.ends_on - timezone.localdate()).days)

    def contains(self, day) -> bool:
        return self.starts_on <= day <= self.ends_on


class GroupKind(models.TextChoices):
    FAMILY_CLASS = "family_class", "семейный класс"
    CLUB = "club", "клуб самоопределения"


class Group(TenantModel):
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name="groups", verbose_name="учебный год"
    )
    name = models.CharField("название", max_length=120)
    kind = models.CharField(
        "тип", max_length=20, choices=GroupKind.choices, default=GroupKind.FAMILY_CLASS
    )
    grade_level = models.PositiveSmallIntegerField(
        "класс", null=True, blank=True,
        validators=[MinValueValidator(8), MaxValueValidator(11)],
    )
    students = models.ManyToManyField(
        "journal.Student", through="journal.GroupMembership", related_name="groups",
        verbose_name="состав",
    )

    class Meta:
        verbose_name = "группа"
        verbose_name_plural = "группы"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "academic_year", "name"], name="group_unique"
            )
        ]

    def __str__(self) -> str:
        return self.name


class StudentStatus(models.TextChoices):
    ENROLLED = "enrolled", "учится"
    ON_HOLD = "on_hold", "приостановлено"
    GRADUATED = "graduated", "выпустился"
    LEFT = "left", "ушёл"


class Student(SoftDeleteTenantModel):
    """
    Ученик. Персональные данные несовершеннолетнего — самая чувствительная
    часть базы: первичный ключ UUID (нельзя перебирать), дата рождения
    и документы шифруются на уровне поля (ТЗ 8.1, 8.2).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_name = models.CharField("фамилия", max_length=80)
    first_name = models.CharField("имя", max_length=80)
    middle_name = models.CharField("отчество", max_length=80, blank=True)
    grade_level = models.PositiveSmallIntegerField(
        "класс", validators=[MinValueValidator(8), MaxValueValidator(11)]
    )
    birth_date = EncryptedDateField("дата рождения", null=True, blank=True)
    document_info = EncryptedCharField("документ", blank=True, default="")
    attestation_partner = models.CharField(
        "аккредитованная школа-партнёр для аттестации", max_length=200, blank=True
    )
    status = models.CharField(
        "статус", max_length=20, choices=StudentStatus.choices, default=StudentStatus.ENROLLED,
        db_index=True,
    )
    enrolled_on = models.DateField("дата зачисления", null=True, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="student_profile", verbose_name="учётная запись",
    )
    note = models.TextField("заметка", blank=True)

    class Meta:
        verbose_name = "ученик"
        verbose_name_plural = "ученики"
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "last_name", "first_name"]),
        ]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p)

    @property
    def short_name(self) -> str:
        initials = "".join(f"{p[0]}." for p in (self.first_name, self.middle_name) if p)
        return f"{self.last_name} {initials}".strip()


class GroupMembership(TenantModel):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="memberships")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="group_memberships")
    joined_on = models.DateField("зачислен в группу", default=timezone.localdate)
    left_on = models.DateField("выбыл из группы", null=True, blank=True)

    class Meta:
        verbose_name = "состав группы"
        verbose_name_plural = "составы групп"
        constraints = [
            models.UniqueConstraint(fields=["group", "student"], name="group_membership_unique")
        ]
        indexes = [models.Index(fields=["organization", "group"])]

    def __str__(self) -> str:
        return f"{self.student} → {self.group}"


class Parent(SoftDeleteTenantModel):
    """Родитель или законный представитель. У ребёнка может быть несколько."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="parent_profiles", verbose_name="учётная запись",
    )
    last_name = models.CharField("фамилия", max_length=80)
    first_name = models.CharField("имя", max_length=80)
    middle_name = models.CharField("отчество", max_length=80, blank=True)
    phone = models.CharField("телефон", max_length=16, blank=True)
    email = models.EmailField("email", blank=True)
    extra_contacts = EncryptedCharField("дополнительные контакты", blank=True, default="")
    students = models.ManyToManyField(
        Student, through="journal.StudentParent", related_name="parents", verbose_name="дети"
    )

    class Meta:
        verbose_name = "родитель"
        verbose_name_plural = "родители"
        ordering = ["last_name", "first_name"]
        indexes = [models.Index(fields=["organization", "last_name"])]

    def __str__(self) -> str:
        return " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p)

    @property
    def full_name(self) -> str:
        return str(self)


class StudentParent(TenantModel):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="parent_links")
    parent = models.ForeignKey(Parent, on_delete=models.CASCADE, related_name="student_links")
    relation = models.CharField("кем приходится", max_length=40, blank=True)
    is_primary_contact = models.BooleanField("основной контакт", default=False)

    class Meta:
        verbose_name = "связь ребёнок — родитель"
        verbose_name_plural = "связи ребёнок — родитель"
        constraints = [
            models.UniqueConstraint(fields=["student", "parent"], name="student_parent_unique")
        ]
        indexes = [models.Index(fields=["organization", "student"])]

    def __str__(self) -> str:
        return f"{self.parent} — {self.student}"


class Teacher(SoftDeleteTenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="teacher_profile",
        verbose_name="учётная запись",
    )
    subjects = models.ManyToManyField(
        Subject, blank=True, related_name="teachers", verbose_name="предметы"
    )
    hourly_rate = models.DecimalField(
        "ставка за час, ₽", max_digits=8, decimal_places=2, default=Decimal("0.00")
    )

    # ── Что о педагоге видно на сайте ───────────────────────────────────────
    # Раньше публичная карточка жила отдельной моделью, и её приходилось
    # заводить второй раз, руками, в другом месте. Два источника правды об
    # одном человеке — гарантия, что однажды они разойдутся: на сайте один
    # предмет, в журнале другой. Теперь педагог один, а поля ниже решают,
    # что из него показывать.
    photo = models.ImageField("фотография", upload_to="teachers/", blank=True)
    subject_line = models.CharField(
        "предметы для сайта", max_length=120, blank=True,
        help_text="Если пусто, соберётся из списка предметов.",
    )
    experience = models.CharField("опыт", max_length=200, blank=True)
    bio = models.TextField("о педагоге", blank=True)
    is_published = models.BooleanField(
        "показывать на сайте", default=False,
        help_text="Пока выключено, педагог виден только в кабинете.",
    )
    is_featured = models.BooleanField(
        "крупная карточка", default=False,
        help_text="Один человек на главной показывается большим блоком.",
    )
    public_position = models.PositiveSmallIntegerField("порядок на сайте", default=100)

    class Meta:
        verbose_name = "педагог"
        verbose_name_plural = "педагоги"
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self) -> str:
        return self.user.full_name or str(self.user)

    @property
    def short_name(self) -> str:
        return self.user.short_name

    @property
    def card_photo(self) -> str:
        return self.photo.url if self.photo else ""

    @property
    def public_subjects(self) -> str:
        """Что написать под именем: своя подпись или список предметов."""
        if self.subject_line:
            return self.subject_line
        return ", ".join(subject.name for subject in self.subjects.all())

    @property
    def rating(self) -> float | None:
        """
        Средняя оценка по опубликованным отзывам.

        Считается по тем же отзывам, что видны на сайте: показывать
        среднее, в которое входят непроверенные, значит показывать
        то, чего никто не читал.
        """
        marks = [r.rating for r in self.published_reviews]
        if not marks:
            return None
        return round(sum(marks) / len(marks), 1)

    @property
    def reviews_count(self) -> int:
        return len(self.published_reviews)

    @property
    def published_reviews(self) -> list:
        """
        Отзывы, прошедшие проверку.

        Фильтруем в Python, а не запросом: список уже загружен через
        prefetch_related, и лишний запрос на каждую карточку превратил бы
        главную страницу в десяток обращений к базе.
        """
        return [r for r in self.reviews.all() if r.status == "published"]


class GradingScale(TenantModel):
    """
    Пороги уровней (ТЗ 3.4).

    В исходных материалах порог 60 описан противоречиво — и как незачёт,
    и как начало базового уровня. Поэтому пороги лежат в БД и правятся
    владельцем без разработчика. Здесь принято: 60 включительно — базовый
    уровень, незачёт — строго меньше 60.
    # TODO(вопрос): подтвердить у заказчика фактические пороги.
    """

    name = models.CharField("название", max_length=80, default="Основная шкала")
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name="grading_scales",
        null=True, blank=True, verbose_name="учебный год",
    )
    is_default = models.BooleanField("по умолчанию", default=True)
    module_max_points = models.DecimalField("максимум за модуль", default=Decimal("100.00"), **POINTS)
    pass_from = models.DecimalField("зачёт от", default=Decimal("60.00"), **POINTS)
    base_from = models.DecimalField("базовый уровень от", default=Decimal("60.00"), **POINTS)
    elevated_from = models.DecimalField("повышенный уровень от", default=Decimal("70.00"), **POINTS)
    advanced_from = models.DecimalField("продвинутый уровень от", default=Decimal("80.00"), **POINTS)

    class Meta:
        verbose_name = "шкала оценивания"
        verbose_name_plural = "шкалы оценивания"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "academic_year", "name"], name="grading_scale_unique"
            )
        ]

    def __str__(self) -> str:
        return self.name

    def level_for(self, points: Decimal) -> str:
        points = Decimal(points or 0)
        if points >= self.advanced_from:
            return Level.ADVANCED
        if points >= self.elevated_from:
            return Level.ELEVATED
        if points >= self.base_from:
            return Level.BASE
        return Level.FAILED

    def is_passed(self, points: Decimal) -> bool:
        return Decimal(points or 0) >= self.pass_from


class Level(models.TextChoices):
    FAILED = "failed", "незачёт"
    BASE = "base", "базовый уровень"
    ELEVATED = "elevated", "повышенный уровень"
    ADVANCED = "advanced", "продвинутый уровень"


class Lesson(TenantModel):
    """Занятие. `is_graded` решает педагог при планировании модуля."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="lessons")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="lessons")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="lessons")
    teacher = models.ForeignKey(
        Teacher, on_delete=models.SET_NULL, null=True, blank=True, related_name="lessons"
    )
    starts_at = models.DateTimeField("начало")
    duration_minutes = models.PositiveSmallIntegerField("длительность, мин", default=45)
    topic = models.CharField("тема занятия", max_length=250, blank=True)
    is_graded = models.BooleanField("с оцениванием", default=False)
    room = models.CharField("аудитория", max_length=40, blank=True)

    class Meta:
        verbose_name = "занятие"
        verbose_name_plural = "занятия"
        ordering = ["starts_at"]
        indexes = [
            models.Index(fields=["organization", "starts_at"]),
            models.Index(fields=["organization", "group", "starts_at"]),
            models.Index(fields=["organization", "teacher", "starts_at"]),
            models.Index(fields=["organization", "module", "subject"]),
        ]

    def __str__(self) -> str:
        return f"{self.subject} · {self.group} · {timezone.localtime(self.starts_at):%d.%m %H:%M}"

    @property
    def local_date(self):
        return timezone.localtime(self.starts_at).date()


def homework_photo_path(instance, filename: str) -> str:
    """Путь внутри закрытого хранилища: организация, занятие, расширение."""
    suffix = Path(filename).suffix.lower()[:8] or ".jpg"
    return f"homework/{instance.organization_id}/{instance.lesson_id}{suffix}"


class Homework(TenantModel):
    """
    Домашнее задание к занятию.

    Удаляется по-настоящему, а не пометкой: «убрать» здесь значит убрать.
    Мягкое удаление оставляло бы строку с тем же занятием, а связь с ним
    единственная — и второе задание к тому же занятию просто не завелось
    бы. Хранить историю опечаток педагога незачем: персональных данных в
    задании нет, а баллы за него живут отдельно, в оценивании.

    Отдельная запись, а не элемент оценивания: задают домашнее почти на
    каждом занятии, а на баллы идёт малая часть. Требовать баллы за
    «прочитать параграф» значило бы либо ломать распределение сотни, либо
    заставлять педагога писать задание где-то на стороне.

    Когда задание всё-таки на оценку, к нему привязывается обычный
    GradeItem — и оно попадает в те же сто баллов модуля, что и всё
    остальное. Двух источников правды не возникает: баллы живут там же,
    где всегда.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.OneToOneField(
        Lesson, on_delete=models.CASCADE, related_name="homework", verbose_name="занятие"
    )
    text = models.TextField("задание")
    # Лист с задачами проще сфотографировать, чем переписать. Файл лежит
    # в закрытом хранилище и отдаётся вью с проверкой прав: на снимке
    # страницы бывает и фамилия, и почерк ребёнка.
    photo = models.ImageField(
        "фото листа с задачами", upload_to=homework_photo_path,
        storage=private_storage, null=True, blank=True,
    )
    due_date = models.DateField("сдать до", null=True, blank=True)
    grade_item = models.OneToOneField(
        "GradeItem", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="homework", verbose_name="оценивание",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="homework_given", verbose_name="кто задал",
    )

    class Meta:
        verbose_name = "домашнее задание"
        verbose_name_plural = "домашние задания"
        ordering = ["-lesson__starts_at"]
        indexes = [models.Index(fields=["organization", "due_date"])]

    def __str__(self) -> str:
        return f"Д/з к занятию {self.lesson_id}"

    @property
    def is_graded(self) -> bool:
        return self.grade_item_id is not None

    @property
    def is_overdue(self) -> bool:
        """Срок прошёл. Показываем, но не прячем — задолженность не исчезает."""
        from django.utils import timezone

        return bool(self.due_date and self.due_date < timezone.localdate())


class HomeworkMark(TenantModel):
    """
    Отметка ученика «сделал».

    Не оценка и не подтверждение: ребёнок отмечает сам, педагог видит
    список отметившихся. Смысл в том, чтобы задание перестало висеть
    в кабинете, а педагог перед занятием знал, сколько человек к нему
    готовились, — а не в том, чтобы поймать на неправде.

    Отметка есть — значит, строка есть; сняли отметку — строку убрали.
    Мягкое удаление здесь только мешало бы: снятую отметку нельзя было бы
    поставить снова, а передумать ребёнок имеет полное право.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    homework = models.ForeignKey(
        Homework, on_delete=models.CASCADE, related_name="marks", verbose_name="задание"
    )
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="homework_marks", verbose_name="ученик"
    )

    class Meta:
        verbose_name = "отметка о выполнении"
        verbose_name_plural = "отметки о выполнении"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["homework", "student"], name="uniq_homework_mark_per_student"
            )
        ]

    def __str__(self) -> str:
        return f"{self.student} сделал {self.homework_id}"


def thematic_plan_path(instance, filename: str) -> str:
    """Исходник КТП внутри закрытого хранилища."""
    suffix = Path(filename).suffix.lower()[:8] or ".xlsx"
    return f"ktp/{instance.organization_id}/{instance.pk}{suffix}"


class ThematicPlan(TenantModel):
    """
    Календарно-тематическое планирование (КТП) по предмету.

    Приходит файлом — таблицей, которую педагог составлял не здесь. Мы её
    не переписываем и не подменяем: исходник хранится как есть, а разобранные
    строки живут рядом. Если разбор оказался неверным, файл всегда можно
    прочитать заново с другой разметкой колонок, ничего не потеряв.

    Колонки в присланных таблицах называются как угодно — «Тема урока»,
    «Содержание», «Раздел/тема». Поэтому соответствие колонок хранится
    здесь же, у плана: угаданное можно поправить руками, и разбор
    повторится по исправленному.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name="thematic_plans",
        verbose_name="учебный год",
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="thematic_plans", verbose_name="предмет"
    )
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="thematic_plans",
        null=True, blank=True, verbose_name="группа",
        help_text="Пусто — план общий для всех групп, где идёт предмет.",
    )
    title = models.CharField("название", max_length=200, blank=True)
    source = models.FileField(
        "исходный файл", upload_to=thematic_plan_path, storage=private_storage,
        null=True, blank=True,
    )
    source_name = models.CharField("имя файла", max_length=250, blank=True)
    # Как разобрали файл: с какой строки заголовок и какая колонка что значит.
    header_row = models.PositiveSmallIntegerField("строка заголовка", default=0)
    column_map = models.JSONField("разметка колонок", default=dict, blank=True)
    note = models.TextField("примечание", blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="thematic_plans", verbose_name="кто загрузил",
    )

    class Meta:
        verbose_name = "тематическое планирование"
        verbose_name_plural = "тематические планирования"
        ordering = ["subject__name", "-created_at"]
        indexes = [models.Index(fields=["organization", "academic_year", "subject"])]

    def __str__(self) -> str:
        return self.title or f"КТП · {self.subject}"


class ThematicPlanEntry(TenantModel):
    """
    Строка КТП: одно занятие по плану.

    Привязка к занятию расписания необязательна и появляется отдельным
    действием: план составляют до того, как расписание собрано, и строка
    без занятия — это не ошибка, а «ещё не поставили».
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(
        ThematicPlan, on_delete=models.CASCADE, related_name="entries", verbose_name="план"
    )
    position = models.PositiveIntegerField("порядок", default=0)
    number = models.CharField("№ по плану", max_length=20, blank=True)
    planned_date = models.DateField("дата по плану", null=True, blank=True)
    topic = models.CharField("тема", max_length=250)
    hours = models.DecimalField(
        "часов", max_digits=4, decimal_places=2, default=Decimal("1.00")
    )
    kind = models.CharField("тип занятия", max_length=80, blank=True)
    homework = models.TextField("домашнее задание", blank=True)
    notes = models.TextField("примечание", blank=True)
    lesson = models.ForeignKey(
        Lesson, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="plan_entries", verbose_name="занятие",
    )
    # «Причастие 21ч +2К + 2Р.р» — заголовок раздела, а не занятие. В плане
    # он нужен: без него список тем читается как сплошная лента. Но
    # раскладывать его по расписанию нечего.
    is_section = models.BooleanField("заголовок раздела", default=False)

    class Meta:
        verbose_name = "строка планирования"
        verbose_name_plural = "строки планирования"
        ordering = ["plan", "position"]
        indexes = [models.Index(fields=["organization", "plan", "position"])]

    def __str__(self) -> str:
        return f"{self.number or self.position}. {self.topic}"


class GradeItemKind(models.TextChoices):
    LESSON = "lesson", "занятие"
    HOMEWORK = "homework", "домашняя работа"
    QUIZ = "quiz", "проверочная работа"
    TEST = "test", "контрольная работа"
    CREDIT = "credit", "зачёт"


# Структура распределения 100 баллов по умолчанию (ТЗ 3.4).
DEFAULT_STRUCTURE = {
    GradeItemKind.CREDIT: {"count": 1, "max_points": Decimal("25.00")},
    GradeItemKind.QUIZ: {"count": 2, "max_points": Decimal("10.00")},
    GradeItemKind.TEST: {"count": 1, "max_points": Decimal("15.00")},
    GradeItemKind.LESSON: {"count": 8, "max_points": Decimal("5.00")},
}


class GradeItem(TenantModel):
    """
    Оцениваемый элемент модуля по конкретному предмету и группе.

    Сумма max_points всех элементов одной связки (модуль, предмет, группа)
    не может превышать module_max_points — проверяется в сервисе и
    в GradeItem.clean().
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="grade_items")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="grade_items")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="grade_items")
    lesson = models.OneToOneField(
        Lesson, on_delete=models.CASCADE, null=True, blank=True, related_name="grade_item"
    )
    kind = models.CharField("тип работы", max_length=20, choices=GradeItemKind.choices)
    title = models.CharField("название", max_length=200, blank=True)
    max_points = models.DecimalField("максимум баллов", **POINTS)
    due_date = models.DateField("дата", null=True, blank=True)
    position = models.PositiveSmallIntegerField("порядок", default=100)

    class Meta:
        verbose_name = "элемент оценивания"
        verbose_name_plural = "элементы оценивания"
        ordering = ["position", "due_date", "created_at"]
        indexes = [
            models.Index(fields=["organization", "module", "subject", "group"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_points__gt=0), name="grade_item_positive_max"
            )
        ]

    def __str__(self) -> str:
        return self.title or self.get_kind_display()

    def clean(self):
        from apps.journal.services.grading import validate_grade_item

        super().clean()
        validate_grade_item(self)


class Grade(SoftDeleteTenantModel):
    """Балл ученика за элемент оценивания."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="grades")
    grade_item = models.ForeignKey(GradeItem, on_delete=models.CASCADE, related_name="grades")
    points = models.DecimalField("баллы", validators=[MinValueValidator(Decimal("0"))], **POINTS)
    comment = models.TextField("комментарий педагога", blank=True)
    given_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="given_grades", verbose_name="кто выставил",
    )
    graded_at = models.DateTimeField("когда выставлено", default=timezone.now)

    class Meta:
        verbose_name = "балл"
        verbose_name_plural = "баллы"
        ordering = ["-graded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "grade_item"],
                condition=models.Q(deleted_at__isnull=True),
                name="grade_unique_per_item",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "student"]),
            models.Index(fields=["organization", "grade_item"]),
            models.Index(fields=["organization", "-graded_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.student} · {self.grade_item} · {self.points}"


class ModuleResult(TenantModel):
    """
    Итог модуля по предмету. Рассчитывается сервисом, руками не вводится.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="module_results")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="module_results")
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="module_results")
    total_points = models.DecimalField("сумма баллов", default=Decimal("0.00"), **POINTS)
    planned_points = models.DecimalField("распределено баллов", default=Decimal("0.00"), **POINTS)
    level = models.CharField("уровень", max_length=20, choices=Level.choices, default=Level.FAILED)
    is_passed = models.BooleanField("зачёт", default=False)
    # Считается при пересчёте, чтобы кабинет ученика не делал лишних запросов.
    gap_to_next_level = models.DecimalField(
        "не хватает до следующего уровня", null=True, blank=True, **POINTS
    )
    computed_at = models.DateTimeField("пересчитано", default=timezone.now)

    class Meta:
        verbose_name = "итог модуля"
        verbose_name_plural = "итоги модулей"
        ordering = ["module__starts_on", "subject__position"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "subject", "module"], name="module_result_unique"
            )
        ]
        indexes = [
            models.Index(fields=["organization", "student", "module"]),
            models.Index(fields=["organization", "module", "subject"]),
        ]

    def __str__(self) -> str:
        return f"{self.student} · {self.subject} · {self.module}: {self.total_points}"

    @property
    def progress_percent(self) -> int:
        """Прогресс к 100 баллам для полосы в кабинете."""
        if not self.planned_points:
            return 0
        return min(100, int(self.total_points / Decimal("100") * 100))


# ─── Профиль ученика: цели и состояние (этап 4, ТЗ 6) ───────────────────────


class GoalKind(models.TextChoices):
    ACADEMIC = "academic", "академическая цель"
    PERSONAL = "personal", "личная цель"
    OUTCOME = "outcome", "цель-результат"


class GoalVisibility(models.TextChoices):
    OPEN = "open", "открытая"
    HIDDEN = "hidden", "скрытая"


class GoalStatus(models.TextChoices):
    ACTIVE = "active", "в работе"
    DONE = "done", "достигнута"
    DROPPED = "dropped", "снята"


class GoalManager(TenantManager):
    def visible_to_others(self):
        """
        Скрытые личные цели видит только сам ученик.

        Этой выборкой пользуются все выгрузки, отчёты и чужие кабинеты —
        именно она закрывает требование ТЗ 5.2.
        """
        return self.get_queryset().filter(visibility=GoalVisibility.OPEN)


class Goal(SoftDeleteTenantModel):
    """
    Цель ученика.

    Скрытые цели не попадают ни в какие выгрузки и чужие экраны —
    на это есть отдельный тест (ТЗ 9.5).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="goals")
    subject = models.ForeignKey(
        Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name="goals"
    )
    module = models.ForeignKey(
        Module, on_delete=models.SET_NULL, null=True, blank=True, related_name="goals"
    )
    kind = models.CharField("тип", max_length=20, choices=GoalKind.choices)
    visibility = models.CharField(
        "видимость", max_length=10, choices=GoalVisibility.choices, default=GoalVisibility.OPEN
    )
    title = models.CharField("цель", max_length=250)
    description = models.TextField("описание", blank=True)
    status = models.CharField(
        "статус", max_length=10, choices=GoalStatus.choices, default=GoalStatus.ACTIVE
    )
    target_date = models.DateField("срок", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_goals",
    )

    objects = GoalManager()
    all_objects = AllObjectsManager()

    class Meta:
        verbose_name = "цель"
        verbose_name_plural = "цели"
        ordering = ["target_date", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "student", "visibility"]),
            models.Index(fields=["organization", "student", "kind"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_hidden(self) -> bool:
        return self.visibility == GoalVisibility.HIDDEN


class MoodEntry(TenantModel):
    """
    Индикатор состояния (ТЗ 6).

    Штрафов за пропуск нет, отметить можно задним числом за вчера.
    Агрегированное состояние группы никуда публично не выводится.
    """

    class Scale(models.IntegerChoices):
        VERY_LOW = 1, "тяжело"
        LOW = 2, "трудновато"
        NEUTRAL = 3, "ровно"
        GOOD = 4, "хорошо"
        GREAT = 5, "отлично"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="mood_entries")
    day = models.DateField("день", default=timezone.localdate)
    value = models.PositiveSmallIntegerField("состояние", choices=Scale.choices)
    note = models.TextField("комментарий ученика", blank=True)
    mentor_feedback = models.TextField("обратная связь наставника", blank=True)

    class Meta:
        verbose_name = "отметка состояния"
        verbose_name_plural = "индикатор состояния"
        ordering = ["-day"]
        constraints = [
            models.UniqueConstraint(fields=["student", "day"], name="mood_entry_unique_per_day")
        ]
        indexes = [models.Index(fields=["organization", "student", "-day"])]

    def __str__(self) -> str:
        return f"{self.student} · {self.day}: {self.get_value_display()}"


# ─── Оплаты (ТЗ 7: на старте — по реквизитам, отметка администратором) ──────


class Payment(SoftDeleteTenantModel):
    """
    Начисление и его оплата.

    Эквайринга на старте нет: администратор отмечает оплату вручную.
    Интерфейс PaymentProvider (apps/journal/services/payments.py) заложен,
    чтобы подключение эквайринга не переписывало эту модель.
    """

    class Status(models.TextChoices):
        PLANNED = "planned", "предстоит"
        PAID = "paid", "оплачено"
        CANCELLED = "cancelled", "отменено"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="payments")
    title = models.CharField("назначение", max_length=200)
    period_start = models.DateField("период с")
    period_end = models.DateField("период по")
    amount = models.DecimalField("сумма, ₽", max_digits=10, decimal_places=2)
    status = models.CharField(
        "статус", max_length=12, choices=Status.choices, default=Status.PLANNED, db_index=True
    )
    due_on = models.DateField("оплатить до", null=True, blank=True)
    paid_on = models.DateField("оплачено", null=True, blank=True)
    provider = models.CharField("способ", max_length=40, default="manual")
    external_id = models.CharField("id платежа у провайдера", max_length=120, blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="marked_payments", verbose_name="кто отметил",
    )
    comment = models.TextField("комментарий", blank=True)

    class Meta:
        verbose_name = "оплата"
        verbose_name_plural = "оплаты"
        ordering = ["-period_start"]
        indexes = [
            models.Index(fields=["organization", "student", "-period_start"]),
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.student} · {self.title} · {self.amount} ₽"
