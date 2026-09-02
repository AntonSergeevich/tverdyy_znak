"""
Нагрузка в академических часах.

Считать её в астрономических было арифметически верно и практически
бесполезно: занятие в сорок минут превращалось в «0,67 часа», и педагог,
проведший полноценный урок, видел на экране две трети непонятно чего.
Ставка у него за академический час, и урок он проводит один, сколько бы
минут в нём ни было.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import Lesson
from apps.journal.services.workload import ACADEMIC_MINUTES, academic_hours, hours_of
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


@pytest.mark.parametrize(
    "minutes, expected",
    [
        # Ради этого всё и затевалось: сорок минут — это проведённый урок.
        (40, 1),
        (45, 1),
        (30, 1),
        (1, 1),
        # Длиннее — столько часов, сколько помещается, неполный считается целым:
        # к полутора часам готовятся как к двум урокам, а не к полутора.
        (60, 2),
        (90, 2),
        (135, 3),
        # Занятия нулевой длины не бывает, но и часов за него нет.
        (0, 0),
        (None, 0),
    ],
)
def test_a_lesson_is_at_least_one_academic_hour(minutes, expected):
    assert academic_hours(minutes) == expected


def test_two_short_lessons_are_two_hours_not_one_and_a_third():
    """
    Считаем по каждому занятию, а не по сумме минут.

    Сложи мы сначала минуты, два урока по сорок дали бы час двадцать —
    и педагог недосчитался бы половины дня.
    """
    class FakeLesson:
        def __init__(self, minutes):
            self.duration_minutes = minutes

    assert hours_of([FakeLesson(40), FakeLesson(40)]) == 2
    assert ACADEMIC_MINUTES == 45


def _lesson(tenant, minutes: int, day_shift: int = 0) -> Lesson:
    return Lesson.objects.create(
        organization=tenant.organization, module=tenant.module, subject=tenant.subject,
        group=tenant.group, teacher=tenant.teacher,
        starts_at=tenant.lesson.starts_at + dt.timedelta(days=day_shift, hours=day_shift),
        duration_minutes=minutes,
    )


def test_the_teacher_sees_hours_not_thirds_of_them(tenant_a):
    """«0,67» на экране педагога и было той самой жалобой."""
    with organization_context(tenant_a.organization):
        tenant_a.lesson.duration_minutes = 40
        tenant_a.lesson.save(update_fields=["duration_minutes"])
        tenant_a.teacher.hourly_rate = Decimal("1000.00")
        tenant_a.teacher.save(update_fields=["hourly_rate"])
        day = tenant_a.lesson.local_date

    client = sign_in(tenant_a, tenant_a.teacher_user)
    body = client.get(
        reverse("cabinet:teacher_hours"),
        {"from": day.isoformat(), "to": day.isoformat()},
    ).content.decode()

    assert "Академических часов" in body
    assert "0,67" not in body
    assert "по 45 минут" in body


def test_the_payroll_counts_the_same_hours_as_the_teacher_sees(tenant_a):
    """
    Расходиться этим цифрам нельзя: правым окажется тот, кто громче,
    а не тот, кто прав.
    """
    from apps.journal.views.manage import _payroll_rows

    with organization_context(tenant_a.organization):
        tenant_a.lesson.duration_minutes = 40
        tenant_a.lesson.save(update_fields=["duration_minutes"])
        _lesson(tenant_a, 40, day_shift=0)
        tenant_a.teacher.hourly_rate = Decimal("1000.00")
        tenant_a.teacher.save(update_fields=["hourly_rate"])
        day = tenant_a.lesson.local_date

        rows = _payroll_rows(day, day + dt.timedelta(days=1))
        mine = next(row for row in rows if row["teacher"] == tenant_a.teacher)

    # Два урока по сорок минут — два академических часа и две тысячи.
    assert mine["hours"] == 2
    assert mine["amount"] == Decimal("2000.00")
    assert mine["lessons"] == 2
