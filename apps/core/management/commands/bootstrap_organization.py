"""
Первичная настройка организации: год, модули 2026/27, предметы, шкала,
правовые страницы и вопросы FAQ.

Идемпотентна: повторный запуск ничего не дублирует.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Organization, OrganizationDomain
from apps.core.tenancy import organization_context
from apps.journal.models import AcademicYear, GradingScale, Module, ModuleKind, Subject
from apps.site_public.models import FaqItem, LegalDocument

# Расписание модулей 2026/27 (ТЗ 3.5).
MODULES = [
    (ModuleKind.MODULE, 1, date(2026, 9, 1), date(2026, 10, 2)),
    (ModuleKind.VACATION, 1, date(2026, 10, 5), date(2026, 10, 9)),
    (ModuleKind.MODULE, 2, date(2026, 10, 12), date(2026, 11, 13)),
    (ModuleKind.VACATION, 2, date(2026, 11, 16), date(2026, 11, 20)),
    (ModuleKind.MODULE, 3, date(2026, 11, 23), date(2026, 12, 29)),
    (ModuleKind.VACATION, 3, date(2026, 12, 30), date(2027, 1, 10)),
    (ModuleKind.MODULE, 4, date(2027, 1, 11), date(2027, 2, 19)),
    (ModuleKind.VACATION, 4, date(2027, 2, 22), date(2027, 2, 26)),
    (ModuleKind.MODULE, 5, date(2027, 3, 1), date(2027, 4, 2)),
    (ModuleKind.VACATION, 5, date(2027, 4, 5), date(2027, 4, 9)),
    (ModuleKind.MODULE, 6, date(2027, 4, 12), date(2027, 5, 21)),
]

# Предметы и недельная нагрузка — 34 часа (ТЗ 3.5).
SUBJECTS = [
    ("Русский язык", 3), ("Литература", 3), ("Английский язык", 3), ("Математика", 6),
    ("Информатика", 1), ("История", 2), ("Обществознание", 1), ("География", 2),
    ("Физика", 3), ("Химия", 2), ("Биология", 2), ("Подготовка к ОГЭ", 6),
]

FAQ = [
    ("У центра есть лицензия на образовательную деятельность?",
     "Нет, и для нашего формата она не требуется. Подросток числится на самообразовании, "
     "а промежуточную аттестацию проходит в аккредитованной школе-партнёре — документ выдаёт она."),
    ("Как проходит аттестация?",
     "По графику аккредитованной школы-партнёра. График согласуется на учебный год "
     "и виден в кабинете родителя."),
    ("Что, если формат не подойдёт?",
     "Решение принимается после бесплатной диагностики. Условия расторжения договора "
     "описаны в самом договоре, скрытых удержаний нет."),
    ("Как оплачивать?",
     "Помесячно, по реквизитам. Все начисления и оплаты видны в кабинете родителя."),
    ("Что с пропусками?",
     "Баллы за пропущенные работы добираются на консультациях каникулярной недели. "
     "Штрафов за пропуск нет, но модуль закрывать придётся."),
    ("Готовите ли к ЕГЭ?",
     "Подготовка к ОГЭ и ЕГЭ встроена в учебный план. Результат экзамена зависит "
     "от подростка, поэтому обещаний по баллам мы не даём."),
]

LEGAL_STUB = (
    "Документ подготовлен по шаблону и требует вычитки юристом до публикации.\n\n"
    "1. Общие положения\n"
    "Оператор обработки персональных данных: {legal_name}, ИНН {inn}, ОГРНИП {ogrnip}, "
    "адрес: {address}.\n\n"
    "2. Какие данные обрабатываются\n"
    "Имя и телефон родителя, класс ребёнка, удобное время звонка, комментарий к заявке, "
    "технические данные обращения (IP, user-agent, источник перехода).\n\n"
    "3. Цели обработки\n"
    "Связь по заявке, организация обучения, ведение электронного журнала, исполнение договора.\n\n"
    "4. Данные несовершеннолетних\n"
    "Данные ребёнка обрабатываются на основании отдельного согласия родителя "
    "или законного представителя.\n\n"
    "5. Сроки хранения и удаление\n"
    "Данные хранятся не дольше срока, необходимого для целей обработки. "
    "Согласие можно отозвать, направив обращение на {email}.\n\n"
    "6. Права субъекта\n"
    "Получение сведений об обработке, уточнение, блокирование и удаление данных, отзыв согласия."
)


class Command(BaseCommand):
    help = "Создать организацию и наполнить справочники учебного года 2026/27"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="tverdyy-znak")
        parser.add_argument("--name", default="Твёрдый знак")
        parser.add_argument("--domain", default="tverdyy-znak.ru")
        parser.add_argument("--year", default="2026/27")

    @transaction.atomic
    def handle(self, *args, **options):
        organization, created = Organization.objects.get_or_create(
            slug=options["slug"],
            defaults={"name": options["name"], "timezone": "Asia/Krasnoyarsk"},
        )
        self.stdout.write(
            self.style.SUCCESS(f"Организация {'создана' if created else 'уже была'}: {organization}")
        )
        if options["domain"]:
            OrganizationDomain.objects.get_or_create(
                organization=organization, host=options["domain"], defaults={"is_primary": True}
            )

        with organization_context(organization):
            year, _ = AcademicYear.objects.get_or_create(
                organization=organization,
                title=options["year"],
                defaults={"starts_on": date(2026, 9, 1), "ends_on": date(2027, 5, 21), "is_current": True},
            )

            for kind, number, starts_on, ends_on in MODULES:
                Module.objects.get_or_create(
                    organization=organization, academic_year=year, kind=kind, number=number,
                    defaults={"starts_on": starts_on, "ends_on": ends_on},
                )

            for position, (name, hours) in enumerate(SUBJECTS, start=1):
                Subject.objects.get_or_create(
                    organization=organization, academic_year=year, name=name,
                    defaults={"weekly_hours": hours, "position": position * 10},
                )

            GradingScale.objects.get_or_create(
                organization=organization, academic_year=None, name="Основная шкала",
                defaults={
                    "module_max_points": Decimal("100.00"),
                    "pass_from": Decimal("60.00"),
                    "base_from": Decimal("60.00"),
                    "elevated_from": Decimal("70.00"),
                    "advanced_from": Decimal("80.00"),
                },
            )

            for position, (question, answer) in enumerate(FAQ, start=1):
                FaqItem.objects.get_or_create(
                    organization=organization, question=question,
                    defaults={"answer": answer, "position": position * 10},
                )

            body = LEGAL_STUB.format(
                legal_name=organization.legal_name or "ИП (реквизиты уточняются)",
                inn=organization.inn or "—",
                ogrnip=organization.ogrnip or "—",
                address=organization.address or "адрес уточняется",
                email=organization.contact_email or "email уточняется",
            )
            for kind, title in LegalDocument.Kind.choices:
                LegalDocument.objects.get_or_create(
                    organization=organization, kind=kind,
                    defaults={"title": title.capitalize(), "body": body, "version": "2026-08-01"},
                )

        total_hours = sum(hours for _, hours in SUBJECTS)
        self.stdout.write(self.style.SUCCESS(
            f"Готово: модулей {len(MODULES)}, предметов {len(SUBJECTS)}, часов в неделю {total_hours}"
        ))
