"""
Загрузка расписания в занятия журнала.

Читаются два вида файлов, и это не прихоть — они отвечают на разные вопросы.

**Таблица (.xlsx)** — то, как расписание ведёт заказчик: слева время,
сверху дни с датами, в клетках названия занятий. Загружается ровно то, что
в файле: конкретные дни, включая неполные недели и разовые перестановки.

**CSV с недельной сеткой** — «так каждую неделю до конца модуля». Шесть
колонок, образец в docs/schedule.example.csv. Одна строка превращается
в занятия на все соответствующие дни модуля.

Повторный запуск в обоих случаях ничего не дублирует: занятие опознаётся
по организации, группе, предмету и времени начала.
"""
from __future__ import annotations

import csv
import datetime as dt
from dataclasses import replace
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
from apps.journal.services import schedule_import

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
    help = "Загрузить расписание из таблицы (.xlsx) или недельной сетки (.csv)"

    def add_arguments(self, parser):
        parser.add_argument("path", help="файл с расписанием: .xlsx или .csv")
        parser.add_argument(
            "--organization", default=None,
            help="код организации; по умолчанию — DEFAULT_ORGANIZATION_SLUG",
        )
        parser.add_argument(
            "--module", type=int, default=None,
            help="номер учебного модуля; по умолчанию — тот, что идёт сейчас",
        )
        parser.add_argument(
            "--group", default=None,
            help="группа; обязательна для .xlsx, если групп в году больше одной",
        )
        parser.add_argument(
            "--sheet", default=None,
            help="лист книги; по умолчанию тот, в названии которого есть «расписание»",
        )
        parser.add_argument(
            "--repeat-last-week", action="store_true",
            help="повторить последнюю полную неделю таблицы до конца модуля",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="только показать, что получится, ничего не записывая",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"Файл {path} не найден.")

        organization = self._get_organization(options["organization"])
        with organization_context(organization):
            module = self._get_module(organization, options["module"])
            if path.suffix.lower() in (".xlsx", ".xlsm"):
                self._import_table(organization, module, path, options)
            else:
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

    # ── таблица заказчика ───────────────────────────────────────────────────

    def _import_table(self, organization, module: Module, path: Path, options) -> None:
        try:
            sheets = schedule_import.load_workbook_rows(path)
        except ImportError:  # pragma: no cover - зависимость есть в requirements
            raise CommandError("Для чтения .xlsx нужен openpyxl: pip install openpyxl")

        try:
            sheet = schedule_import.pick_sheet(sheets, options.get("sheet"))
        except KeyError:
            raise CommandError(
                f"Листа «{options['sheet']}» в книге нет. Есть: " + ", ".join(sheets)
            )

        group = self._get_group(module, options.get("group"))
        result = schedule_import.parse_grid(
            sheets[sheet], within=(module.academic_year.starts_on, module.academic_year.ends_on)
        )
        if not result.lessons:
            raise CommandError(
                f"На листе «{sheet}» не нашлось ни одной пары «время + день с датой». "
                "Проверьте, что в шапке стоят даты вида «ПН 30.08», "
                "а слева — время вида «9.30-10.10»."
            )

        self.stdout.write(f"Лист «{sheet}», группа «{group.name}».")
        for warning in result.warnings:
            self.stderr.write(self.style.WARNING(warning))

        entries = list(result.lessons)
        if options.get("repeat_last_week"):
            entries += self._repeat_last_week(entries, module)

        self._write(organization, module, group, entries, dry_run=options["dry_run"], sheet=sheet)

    def _repeat_last_week(self, entries: list, module: Module) -> list:
        """
        Продлить последнюю полную неделю до конца модуля.

        Нужно, когда в таблице расписана пара недель, а дальше «так же».
        По умолчанию выключено: додумывать за расписание — плохая идея,
        это должно быть осознанным решением того, кто загружает.
        """
        if not entries:
            return []
        last_day = max(entry.date for entry in entries)
        last_monday = last_day - dt.timedelta(days=last_day.weekday())
        pattern = [e for e in entries if e.date >= last_monday]
        if not pattern:
            return []

        extra = []
        shift = 1
        while True:
            offset = dt.timedelta(weeks=shift)
            if last_monday + offset > module.ends_on:
                break
            for entry in pattern:
                moved = entry.date + offset
                if module.starts_on <= moved <= module.ends_on:
                    extra.append(replace(entry, date=moved))
            shift += 1
        return extra

    def _get_group(self, module: Module, name: str | None) -> Group:
        groups = Group.objects.filter(academic_year=module.academic_year)
        if name:
            group = groups.filter(name__iexact=name).first() or groups.filter(
                name__istartswith=name
            ).first()
            if group is None:
                raise CommandError(
                    f"Группы «{name}» нет. Есть: " + ", ".join(g.name for g in groups)
                )
            return group
        if groups.count() == 1:
            return groups.first()
        raise CommandError(
            "Групп в году больше одной — укажите, чьё это расписание: --group «Семейный класс 9». "
            "Есть: " + ", ".join(g.name for g in groups)
        )

    def _write(self, organization, module, group, entries, *, dry_run: bool, sheet: str) -> None:
        tz = organization.tzinfo
        created = skipped = outside = 0
        unknown: dict[str, int] = {}

        with transaction.atomic():
            for entry in entries:
                if not (module.starts_on <= entry.date <= module.ends_on):
                    outside += 1
                    continue
                subject = None
                for candidate in schedule_import.title_candidates(entry.title):
                    subject = self._lookup(Subject, candidate, module)
                    if subject is not None:
                        break
                if subject is None:
                    unknown[entry.title] = unknown.get(entry.title, 0) + 1
                    continue

                starts_at = timezone.make_aware(
                    dt.datetime.combine(entry.date, entry.start), tz
                )
                if Lesson.objects.filter(
                    module=module, subject=subject, group=group, starts_at=starts_at
                ).exists():
                    skipped += 1
                    continue
                if not dry_run:
                    Lesson.objects.create(
                        organization=organization, module=module, subject=subject,
                        group=group, starts_at=starts_at,
                        duration_minutes=entry.duration_minutes,
                        is_graded=False,
                    )
                created += 1

            if dry_run:
                transaction.set_rollback(True)

        verb = "появится" if dry_run else "создано"
        self.stdout.write(
            self.style.SUCCESS(f"{module}: занятий {verb} — {created}, уже было — {skipped}.")
        )
        if outside:
            self.stdout.write(
                f"Вне дат модуля ({module.starts_on:%d.%m}—{module.ends_on:%d.%m}) "
                f"осталось строк: {outside}. Для них нужен свой модуль: --module N."
            )
        if unknown:
            self.stderr.write(self.style.WARNING("Не нашёл в журнале такие названия:"))
            for title, count in sorted(unknown.items(), key=lambda kv: -kv[1]):
                self.stderr.write(f"  «{title}» — {count} раз")
            self.stdout.write(
                "Либо поправьте название в таблице, либо заведите предмет "
                "в журнале (блоки дня — с типом «блок дня без баллов»)."
            )
        if dry_run:
            self.stdout.write("Это была проверка: в базу ничего не записано.")

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
