"""
Меню кабинета.

У владельца разделов стало столько, что в строку они перестали помещаться:
последние заезжали друг за друга и просто не были видны. Пункты собраны в
группы — и главное, что здесь проверяется: собрать группы можно было,
только ничего не потеряв по дороге.

Заодно регламент оценивания: сам документ (п. 1.6) требует знакомить с
критериями педагогов, учеников и родителей, поэтому страница открыта всем,
а не только тем, кто ставит баллы.
"""
from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

from tests.conftest import PASSWORD

# Разделы владельца, которые обязаны остаться доступными из меню.
OWNER_SECTIONS = [
    "dashboard", "journal", "schedule_builder", "ktp_list", "subjects",
    "rules", "students", "progress_list", "staff", "payroll", "leads",
    "review_queue",
]


@pytest.fixture
def logged_in(client, tenant_a):
    def _login(user):
        with override_settings(TWO_FACTOR_ENABLED=False):
            client.defaults["HTTP_HOST"] = tenant_a.host
            client.post(
                reverse("accounts:login"),
                {"username": user.email, "password": PASSWORD},
            )
        return client

    return _login


def test_grouping_did_not_lose_a_single_section(logged_in, tenant_a):
    """Группы — это способ уместить всё, а не повод что-то выбросить."""
    body = logged_in(tenant_a.owner_user).get(reverse("cabinet:dashboard")).content.decode()

    for name in OWNER_SECTIONS:
        assert reverse(f"cabinet:{name}") in body, name


def test_group_is_highlighted_when_you_are_inside_it(logged_in, tenant_a):
    """
    Иначе, провалившись в журнал, человек видит невыделенным всё меню
    и теряет ощущение, где находится: сам «Журнал» спрятан под «Учёбой».
    """
    body = logged_in(tenant_a.owner_user).get(reverse("cabinet:journal")).content.decode()

    assert 'class="nav-group is-current"' in body


def test_teacher_menu_stays_flat(logged_in, tenant_a):
    """Шесть пунктов помещаются в строку — прятать их под группы незачем."""
    body = logged_in(tenant_a.teacher_user).get(
        reverse("cabinet:teacher_today")
    ).content.decode()

    assert "nav-group" not in body
    assert reverse("cabinet:rules") in body


@pytest.mark.parametrize("who,home", [
    ("parent_user", "cabinet:parent_home"),
    ("student_user", "cabinet:student_home"),
])
def test_rules_are_open_to_the_family(logged_in, tenant_a, who, home):
    """Регламент писался в том числе для родителя — закрывать его не от кого."""
    browser = logged_in(getattr(tenant_a, who))

    assert reverse("cabinet:rules") in browser.get(reverse(home)).content.decode()
    assert browser.get(reverse("cabinet:rules")).status_code == 200


def test_family_does_not_see_the_kitchen(logged_in, tenant_a):
    """
    Цифры для всех одни, но пометка «в документе опечатка, руководитель
    поправит» и отсылки к кнопкам журнала родителю ничего не объясняют.
    """
    body = logged_in(tenant_a.parent_user).get(reverse("cabinet:rules")).content.decode()

    assert "25" in body and "Пересдачи" in body
    assert "опечатка" not in body
    assert "Создать структуру по умолчанию" not in body


def test_teacher_sees_the_kitchen(logged_in, tenant_a):
    body = logged_in(tenant_a.teacher_user).get(reverse("cabinet:rules")).content.decode()

    assert "опечатка" in body
    assert "Создать структуру по умолчанию" in body
