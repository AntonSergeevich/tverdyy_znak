"""
Загрузка недельной сетки расписания в занятия журнала.

Расписание Алина ведёт в отдельном файле (Яндекс.Документы). Разбирать
чужой формат таблицы вслепую — способ тихо потерять половину строк,
поэтому вход здесь один и явный: CSV с шестью колонками. Файл выгружается
из документа «Сохранить как → CSV», образец лежит в docs/schedule.example.csv.

Команда разворачивает одну неделю на весь модуль: каждая строка сетки
превращается в занятия на все соответствующие дни между началом и концом
модуля. Повторный запуск ничего не дублирует — занятие опознаётся по
организации, группе, предмету и времени начала.
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.models import Organization
from apps.core.tenancy import organization_context
from apps.journal.models import (
    AcademicYear,
    Group,
    Lesson,
    Module,
    ModuleKind,
    Subject,
    Teacher,
)

REQUIRED_COLUMNS = ["day", "time", "subject", "group"]
OPTIONAL_COLUMNS = ["teacher", "room", "duration"]

# Дни принимаем и словом, и цифрой: в выгрузках встречается и то, и другое.
WEEKDAYS = {
    "пн": 0, "понедельник": 0, "mon": 0, "1": 0,
    "вт": 1, "вторник": 1, "tue": 1, "2": 1,
    "ср": 2, "среда": 2, "wed": 2, "3": 2,
    "чт": 3, "четверг": 3, "thu": 3, "4": 3,
    "пт": 4, "пятница": 4, "fri": 4, "5": 4,
    "сб": 5, "суббота": 5, "sat": 5, "6": 5,
    "вс": 6, "воскресенье": 6, "sun": 6, "7": 6,
}


def parse_weekday(raw: str) -> int:
    key = (raw or "").strip().lower().rstrip(".")
    if key in WEEKDAYS:
        return WEEKDAYS[key]
    raise CommandError(f"Не понимаю день недели «{raw}». Пишите пн/вт/ср или 1–7.")


def parse_time(raw: str) -> dt.time:
    value = (raw or "").strip().replace(".", ":")
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return dt.datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise CommandError(f"Не понимаю время «{raw}». Формат — 09:30.")


class Command(BaseCommand):
    help = "Загрузить недельную сетку расписания из CSV в занятия модуля"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="путь к файлу с сеткой")
        parser.add_argument(
            "--organization", default=None,
            help="код организации; по умолчанию — DEFAULT_ORGANIZATION_SLUG",
        )
        parser.add_argument(
            "--module", type=int, default=None,
            help="номер учебного модуля; по умолчанию — тот, что идёт сейчас",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="только показать, что получится, ничего не записывая",
        )

    def handle(self, *args, **options):
        path = Path(options["csv_path"])
        if not path.exists():
            raise CommandError(f"Файл {path} не найден.")

        organization = self._get_organization(options["organization"])
        with organization_context(organization):
            module = self._get_module(organization, options["module"])
            rows = self._read_rows(path)
            self._import(organization, module, rows, dry_run=options["dry_run"])

    # ── подготовка ──────────────────────────────────────────────────────────

    def _get_organization(self, slug: str | None) -> Organization:
        from django.conf import settings

        slug = slug or getattr(settings, "DEFAULT_ORGANIZATION_SLUG", "")
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"Организация «{slug}» не найдена.")
        return organization

    def _get_module(self, organization: Organization, number: int | None) -> Module:
        year = AcademicYear.objects.filter(is_current=True).first()
        if year is None:
            raise CommandError(
                "Нет текущего учебного года. Сначала: manage.py bootstrap_organization"
            )
        modules = Module.objects.filter(academic_year=year, kind=ModuleKind.MODULE)
        if number is not None:
            module = modules.filter(number=number).first()
            if module is None:
                raise CommandError(f"Модуля №{number} в году {year} нет.")
            return module

        today = timezone.localdate()
        module = modules.filter(starts_on__lte=today, ends_on__gte=today).first()
        if module is None:
            module = modules.filter(starts_on__gte=today).order_by("starts_on").first()
        if module is None:
            raise CommandError(
                "Не смог выбрать модуль автоматически. Укажите его явно: --module 2"
            )
        return module

    def _read_rows(self, path: Path) -> list[dict]:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(handle, dialect=dialect)
            missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise CommandError(
                    "В файле нет колонок: " + ", ".join(missing) + ".\n"
                    "Ожидаются: " + ", ".join(REQUIRED_COLUMNS + OPTIONAL_COLUMNS) + ".\n"
                    "Образец: docs/schedule.example.csv"
                )
            return [row for row in reader if any((v or "").strip() for v in row.values())]

    # ── разворачивание сетки ────────────────────────────────────────────────

    def _import(self, organization, module: Module, rows: list[dict], *, dry_run: bool) -> None:
        # Время в сетке — местное время центра, а не сервера: 09:00 в файле
        # должно остаться 09:00 в кабинете. Часовой пояс берём у организации,
        # потому что в команде нет запроса и middleware его не включает.
        tz = organization.tzinfo
        created = skipped = 0
        problems: list[str] = []

        with transaction.atomic():
            for line, row in enumerate(rows, start=2):
                weekday = parse_weekday(row.get("day", ""))
                start_time = parse_time(row.get("time", ""))

                subject = self._lookup(Subject, row.get("subject"), module)
                if subject is None:
                    problems.append(f"строка {line}: предмет «{row.get('subject')}» не найден")
                    continue
                group = self._lookup(Group, row.get("group"), module)
                if group is None:
                    problems.append(f"строка {line}: группа «{row.get('group')}» не найдена")
                    continue
                teacher = self._lookup_teacher(row.get("teacher"))

                duration = (row.get("duration") or "").strip()
                duration_minutes = int(duration) if duration.isdigit() else 45
                room = (row.get("room") or "").strip()[:40]

                for day in self._days(module, weekday):
                    starts_at = timezone.make_aware(
                        dt.datetime.combine(day, start_time), tz
                    )
                    exists = Lesson.objects.filter(
                        module=module, subject=subject, group=group, starts_at=starts_at
                    ).exists()
                    if exists:
                        skipped += 1
                        continue
                    if not dry_run:
                        Lesson.objects.create(
                            organization=organization, module=module, subject=subject,
                            group=group, teacher=teacher, starts_at=starts_at,
                            duration_minutes=duration_minutes, room=room,
                        )
                    created += 1

            if dry_run:
                transaction.set_rollback(True)

        for problem in problems:
            self.stderr.write(self.style.WARNING(problem))

        verb = "появится" if dry_run else "создано"
        self.stdout.write(
            self.style.SUCCESS(
                f"{module}: занятий {verb} — {created}, уже было — {skipped}."
            )
        )
        if problems:
            self.stdout.write(
                "Названия предметов и групп должны совпадать с журналом. "
                "Что заведено сейчас: manage.py shell -c "
                "\"from apps.journal.models import Subject; print(list(Subject.all_objects.values_list('name', flat=True)))\""
            )
        if dry_run:
            self.stdout.write("Это была проверка: в базу ничего не записано.")

    def _days(self, module: Module, weekday: int):
        day = module.starts_on
        while day.weekday() != weekday:
            day += dt.timedelta(days=1)
            if day > module.ends_on:
                return
        while day <= module.ends_on:
            yield day
            day += dt.timedelta(days=7)

    def _lookup(self, model, raw: str | None, module: Module):
        name = (raw or "").strip()
        if not name:
            return None
        qs = model.objects.filter(academic_year=module.academic_year)
        return qs.filter(name__iexact=name).first() or qs.filter(name__istartswith=name).first()

    def _lookup_teacher(self, raw: str | None) -> Teacher | None:
        value = (raw or "").strip()
        if not value:
            return None
        return (
            Teacher.objects.filter(user__email__iexact=value).first()
            or Teacher.objects.filter(user__last_name__iexact=value).first()
        )
