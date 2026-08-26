"""
Данные заказчика: реквизиты ИП, контакты и карточки педагогов.

Отдельно от bootstrap_organization: тот создаёт учебные справочники и
одинаков для любой организации, а здесь лежит конкретика «Твёрдого знака».
Второй клиент получит свой такой же файл и не тронет этот.

    python manage.py setup_client_data

Идемпотентна. Фотографии подхватываются из media/teachers/<слаг>.webp —
их готовит scripts/prepare_teacher_photos.py.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Organization, OrganizationDomain
from apps.core.tenancy import organization_context
from apps.site_public.models import TeacherCard

# Реквизиты. Эти поля команда выставляет всегда: они обязаны совпадать
# с документами ИП, и «поправить в админке» здесь — не фича, а ошибка.
REQUISITES = {
    "name": "Твёрдый знак",
    "legal_name": "Индивидуальный предприниматель Бабаджанова Алина Алимовна",
    "inn": "241502815698",
    "ogrnip": "326246800106544",
    "address": "Красноярск, ул. Весны, 10",
    "contact_phone": "+7 (913) 560-26-00",
    "bank_name": 'ООО "Банк Точка"',
    "bank_bik": "044525104",
    "bank_account": "40802810820001048577",
    "bank_corr_account": "30101810745374525104",
    "timezone": "Asia/Krasnoyarsk",
}

# Стартовые значения. Заполняются, только если поле пустое: тексты и цены
# правятся в админке, и деплой не должен молча возвращать их назад.
# Перезаписать намеренно: setup_client_data --force.
DEFAULTS = {
    # Полный формат = образовательная программа + наставнический блок.
    "price_full_month": 70000,
    "price_program_month": 40000,
    "price_mentor_month": 30000,
    "price_entry_year": 15000,
    # Тексты первого экрана.
    "hero_kicker": "Семейный класс «Твёрдый знак» · Красноярск · 8–11 класс",
    "hero_title": "Вся учёба — в одном месте",
    "hero_lead": (
        "Подросток учится модулями по 5 недель, видит свою дорожную карту "
        "и получает баллы за конкретную работу. Вы видите то же, что и он."
    ),
    # Файл с расписанием, который ведёт Алина. Виден только в кабинете:
    # пока занятия модуля не заведены в журнале, родителю и ученику надо
    # куда-то смотреть. После import_schedule ссылка остаётся справочной.
    "schedule_url": (
        "https://docs.yandex.ru/view/d/"
        "GqC0hOHNfTT2B6PJgMZsWyPegnqahzm72s0qoIz-cKg6b3FiSndzVjk4Zw"
    ),
}

DOMAINS = ["tverdyy-znak.ru", "www.tverdyy-znak.ru"]

# Тексты проходят проверку из tests/test_content_rules.py: центр нигде
# не называет себя школой и не обещает результатов экзамена.
TEACHERS = [
    {
        "slug": "babadzhanova",
        "full_name": "Бабаджанова Алина Алимовна",
        "subject_line": "Основатель и руководитель центра · наставник",
        "experience": "Более 10 лет в образовании",
        "bio": (
            "Путь в образовании — от воспитателя до директора частного "
            "образовательного учреждения федеральной сети.\n"
            "Лауреат конкурса «Учитель, которого ждут».\n"
            "Призёр международного чемпионата «Молодые профессионалы»."
        ),
        "position": 10,
    },
    {
        "slug": "manasyan",
        "full_name": "Манасян Сергей Керопович",
        "subject_line": "Математика, физика, информатика",
        "experience": "Стаж более 30 лет",
        "bio": (
            "Научный руководитель, автор более 300 научных трудов и 10 патентов.\n"
            "Готовит к ОГЭ, ЕГЭ и олимпиадам. Учит думать, а не зубрить: "
            "помогает каждому ученику выстроить свой путь в точных науках."
        ),
        "position": 20,
    },
    {
        "slug": "polskaya",
        "full_name": "Польская Юлия Евгеньевна",
        "subject_line": "Химия и биология",
        "experience": "Более 5 лет практики",
        "bio": (
            "Профильное образование, опыт работы в школе, колледже и репетиторстве.\n"
            "Умеет заинтересовать предметом и готовит к экзамену без стресса."
        ),
        "position": 30,
    },
    {
        "slug": "margarita",
        "full_name": "Маргарита Андреевна",
        "subject_line": "Английский язык",
        "experience": "Уровень C2 по EF SET, сертификат TESOL",
        "bio": (
            "Высшее педагогическое образование, владелец языкового центра.\n"
            "Международный сертификат TESOL по методике преподавания.\n"
            "Преподавала в Гонконге и Израиле, постоянная практика с носителями языка."
        ),
        "position": 40,
    },
    {
        "slug": "anna",
        "full_name": "Анна Константиновна",
        "subject_line": "Профориентолог, наставник",
        "experience": "Индивидуальное сопровождение и групповые тренинги",
        "bio": (
            "Работает с подростками в формате индивидуального сопровождения "
            "и групповых тренингов.\n"
            "Помогает услышать ребёнка и перевести тревогу в план."
        ),
        "position": 50,
    },
]


class Command(BaseCommand):
    help = "Заполнить реквизиты и карточки педагогов «Твёрдого знака»"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default=settings.DEFAULT_ORGANIZATION_SLUG or "tverdyy-znak")
        parser.add_argument(
            "--force", action="store_true",
            help="перезаписать и тексты с ценами, затерев правки из админки",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        organization = Organization.objects.filter(slug=options["slug"]).first()
        if organization is None:
            raise CommandError(
                f"Организация «{options['slug']}» не найдена. "
                f"Сначала: python manage.py bootstrap_organization"
            )

        for field, value in REQUISITES.items():
            setattr(organization, field, value)

        kept = []
        for field, value in DEFAULTS.items():
            if options["force"] or not getattr(organization, field):
                setattr(organization, field, value)
            else:
                kept.append(field)
        organization.save()

        self.stdout.write(self.style.SUCCESS(f"Реквизиты обновлены: {organization.legal_name}"))
        if kept:
            self.stdout.write(
                f"Не тронуто (уже заполнено, правится в админке): {', '.join(kept)}. "
                "Вернуть значения из кода: --force"
            )

        for index, host in enumerate(DOMAINS):
            OrganizationDomain.objects.get_or_create(
                organization=organization, host=host, defaults={"is_primary": index == 0}
            )
        self.stdout.write(f"Домены: {', '.join(DOMAINS)}")

        photos_dir = Path(settings.MEDIA_ROOT) / "teachers"
        with organization_context(organization):
            for entry in TEACHERS:
                data = {key: value for key, value in entry.items() if key != "slug"}
                slug = entry["slug"]
                card, created = TeacherCard.objects.update_or_create(
                    organization=organization,
                    full_name=data["full_name"],
                    defaults={**data, "is_published": True},
                )

                photo = photos_dir / f"{slug}.webp"
                if photo.exists():
                    card.photo.name = f"teachers/{slug}.webp"
                    card.save(update_fields=["photo", "updated_at"])
                    mark = "с фото"
                else:
                    mark = "без фото — положите оригинал в assets/teachers/"
                self.stdout.write(
                    f"  {'создана' if created else 'обновлена'}: {card.full_name} ({mark})"
                )

        missing = [
            label
            for label, value in [
                ("email", organization.contact_email),
                ("Telegram chat_id для заявок", organization.telegram_chat_id),

            ]
            if not value
        ]
        if missing:
            self.stdout.write(
                self.style.WARNING(
                    "\nНе хватает для публикации (задать в админке или в .env):\n  - "
                    + "\n  - ".join(missing)
                )
            )
