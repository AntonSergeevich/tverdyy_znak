"""
Демонстрационные данные для приёмки: педагог, родители, три ученика,
занятия текущего модуля и структура оценивания.

Только для dev и стенда приёмки. На проде не запускать.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Membership, Role, User
from apps.core.models import Organization
from apps.core.tenancy import organization_context
from apps.journal.models import (
    AcademicYear,
    Group,
    GroupMembership,
    Lesson,
    Module,
    ModuleKind,
    Parent,
    Payment,
    Student,
    StudentParent,
    Subject,
    Teacher,
)
from apps.journal.services.grading import create_default_structure, set_grade

DEMO_PASSWORD = "demo-parol-12345"


class Command(BaseCommand):
    help = "Наполнить организацию демонстрационными данными (только dev)"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default=settings.DEFAULT_ORGANIZATION_SLUG)

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo запускается только при DEBUG=True")

        organization = Organization.objects.filter(slug=options["slug"]).first()
        if organization is None:
            raise CommandError("Сначала выполните bootstrap_organization")

        with organization_context(organization):
            year = AcademicYear.objects.filter(is_current=True).first()
            if year is None:
                raise CommandError("Нет текущего учебного года")

            owner = self._user("owner@example.org", "Иванова", "Мария")
            self._membership(owner, organization, Role.OWNER)

            teacher_user = self._user("teacher@example.org", "Петров", "Сергей")
            self._membership(teacher_user, organization, Role.TEACHER)
            teacher, _ = Teacher.objects.get_or_create(
                organization=organization, user=teacher_user,
                defaults={"hourly_rate": Decimal("1200.00")},
            )

            subject = Subject.objects.filter(academic_year=year, name="Математика").first()
            teacher.subjects.add(subject)

            group, _ = Group.objects.get_or_create(
                organization=organization, academic_year=year, name="Семейный класс 9",
                defaults={"grade_level": 9},
            )

            parent_user = self._user("parent@example.org", "Смирнова", "Ольга")
            self._membership(parent_user, organization, Role.PARENT)
            parent, _ = Parent.objects.get_or_create(
                organization=organization, user=parent_user,
                defaults={"last_name": "Смирнова", "first_name": "Ольга", "phone": "79130000001"},
            )

            students = []
            for index, (last, first) in enumerate(
                [("Смирнов", "Артём"), ("Кузнецова", "Лиза"), ("Волков", "Никита")], start=1
            ):
                student_user = self._user(f"student{index}@example.org", last, first)
                self._membership(student_user, organization, Role.STUDENT)
                student, _ = Student.objects.get_or_create(
                    organization=organization, last_name=last, first_name=first,
                    defaults={
                        "grade_level": 9,
                        "user": student_user,
                        "enrolled_on": dt.date(2026, 9, 1),
                        "birth_date": dt.date(2010, 5, index),
                        "attestation_partner": "Аккредитованная школа-партнёр",
                    },
                )
                GroupMembership.objects.get_or_create(
                    organization=organization, group=group, student=student
                )
                StudentParent.objects.get_or_create(
                    organization=organization, student=student, parent=parent,
                    defaults={"relation": "мать", "is_primary_contact": index == 1},
                )
                Payment.objects.get_or_create(
                    organization=organization, student=student, title="Обучение, сентябрь",
                    period_start=dt.date(2026, 9, 1), period_end=dt.date(2026, 9, 30),
                    defaults={"amount": Decimal(organization.price_full_month)},
                )
                students.append(student)

            module = (
                Module.objects.filter(kind=ModuleKind.MODULE, academic_year=year)
                .order_by("starts_on")
                .first()
            )

            # Занятия модуля: два в неделю, первые восемь — с оцениванием.
            day = module.starts_on
            created_lessons = []
            while day <= module.ends_on and len(created_lessons) < 10:
                if day.weekday() in (0, 3):
                    starts_at = timezone.make_aware(
                        dt.datetime.combine(day, dt.time(10, 0)), organization.tzinfo
                    )
                    lesson, _ = Lesson.objects.get_or_create(
                        organization=organization, module=module, subject=subject, group=group,
                        starts_at=starts_at,
                        defaults={
                            "teacher": teacher,
                            "topic": f"Тема занятия {len(created_lessons) + 1}",
                            "duration_minutes": 45,
                        },
                    )
                    created_lessons.append(lesson)
                day += dt.timedelta(days=1)

            items = list(module.grade_items.filter(subject=subject, group=group))
            if not items:
                items = create_default_structure(module, subject, group, actor=owner)

            # Привязываем элементы типа «занятие» к реальным занятиям.
            lesson_items = [item for item in items if item.kind == "lesson"]
            for lesson, item in zip(created_lessons, lesson_items):
                if item.lesson_id is None:
                    item.lesson = lesson
                    item.due_date = lesson.local_date
                    item.save(update_fields=["lesson", "due_date", "updated_at"])
                    lesson.is_graded = True
                    lesson.save(update_fields=["is_graded", "updated_at"])

            # Три ученика с разными итогами: незачёт, базовый, продвинутый —
            # ровно то, что нужно проверить на приёмке.
            targets = [Decimal("0.5"), Decimal("0.68"), Decimal("0.92")]
            for student, share in zip(students, targets):
                for item in items:
                    set_grade(
                        student=student,
                        grade_item=item,
                        points=(item.max_points * share).quantize(Decimal("0.01")),
                        actor=owner,
                        comment="",
                    )

        self.stdout.write(self.style.SUCCESS(
            "Демо-данные готовы.\n"
            f"  владелец  owner@example.org / {DEMO_PASSWORD}\n"
            f"  педагог   teacher@example.org / {DEMO_PASSWORD}\n"
            f"  родитель  parent@example.org / {DEMO_PASSWORD}\n"
            f"  ученик    student1@example.org / {DEMO_PASSWORD}"
        ))

    def _user(self, email: str, last_name: str, first_name: str) -> User:
        user = User.objects.filter(email=email).first()
        if user is None:
            return User.objects.create_user(
                email=email, password=DEMO_PASSWORD, last_name=last_name, first_name=first_name
            )
        # Пароль переустанавливаем всегда: команда должна оставлять стенд
        # в известном состоянии, а не в том, до которого его довели опыты.
        user.set_password(DEMO_PASSWORD)
        user.save(update_fields=["password", "updated_at"])
        return user

    @staticmethod
    def _membership(user: User, organization: Organization, role: str) -> None:
        Membership.objects.get_or_create(user=user, organization=organization, role=role)
