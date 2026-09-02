"""
Цель как путь: шаги, спутник и похвала.

Цель вроде «разобраться с тригонометрией» невыполнима: за неё нельзя взяться
сегодня и нельзя отметить сделанной. Подросток бросает её не от лени, а
потому что не видит, сдвинулся ли он вообще. Шаги отвечают ровно на этот
вопрос — и отвечают честно: придумывает их сам ученик, и никто, кроме него,
их не отмечает.
"""
from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import Goal, GoalKind, GoalStep, GoalVisibility, Hero
from apps.journal.services.goals import STEP_LIMIT, path_of, set_steps, toggle_step
from tests.conftest import PASSWORD


def sign_in(tenant, user):
    from django.test import Client

    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


@pytest.fixture
def goal(tenant_a):
    with organization_context(tenant_a.organization):
        return Goal.objects.create(
            organization=tenant_a.organization, student=tenant_a.student,
            kind=GoalKind.PERSONAL, title="Разобраться с тригонометрией",
        )


# ─── Путь ───────────────────────────────────────────────────────────────────

def test_a_goal_without_steps_has_no_path(tenant_a, goal):
    """Ноль шагов — ноль движения, и притворяться прогрессом нечему."""
    with organization_context(tenant_a.organization):
        path = path_of(goal)

    assert path.total == 0
    assert path.percent == 0
    assert path.praise == ""


def test_each_step_moves_the_companion_forward(tenant_a, goal):
    with organization_context(tenant_a.organization):
        steps = set_steps(goal=goal, titles=["Разобрать синусы", "Прорешать 10 задач",
                                             "Спросить непонятное", "Написать проверочную"])
        assert path_of(goal).percent == 0

        toggle_step(steps[0])
        goal.refresh_from_db()
        assert path_of(goal).percent == 25
        assert path_of(goal).praise

        for step in steps[1:]:
            toggle_step(step)
        assert path_of(goal).is_complete
        assert path_of(goal).praise == "Цель достигнута. Целиком, своим ходом."


def test_a_step_can_be_unticked(tenant_a, goal):
    """
    Отметить лишнее — обычное дело. Невозможность исправить учит врать
    журналу, а не себе.
    """
    with organization_context(tenant_a.organization):
        step = set_steps(goal=goal, titles=["Один шаг"])[0]
        toggle_step(step)
        assert step.is_done

        toggle_step(step)
        assert not step.is_done
        assert path_of(goal).done == 0


def test_editing_the_wording_keeps_what_is_already_done(tenant_a, goal):
    """Ученик уточняет формулировку, а не начинает путь заново."""
    with organization_context(tenant_a.organization):
        steps = set_steps(goal=goal, titles=["Разобрать синусы", "Прорешать задачи"])
        toggle_step(steps[0])

        set_steps(goal=goal, titles=["Разобрать синусы", "Прорешать задачи", "Сдать зачёт"])

        again = list(goal.steps.order_by("position"))
        assert [step.title for step in again] == [
            "Разобрать синусы", "Прорешать задачи", "Сдать зачёт"
        ]
        assert again[0].is_done
        assert not again[1].is_done


def test_a_path_cannot_become_a_timetable(tenant_a, goal):
    """Длинный список шагов — это уже не путь, а расписание."""
    with organization_context(tenant_a.organization):
        with pytest.raises(ValidationError):
            set_steps(goal=goal, titles=[f"Шаг {n}" for n in range(STEP_LIMIT + 1)])


def test_blank_lines_are_not_steps(tenant_a, goal):
    with organization_context(tenant_a.organization):
        set_steps(goal=goal, titles=["Первый", "", "   ", "Второй"])
        assert goal.steps.count() == 2


# ─── Кабинет ученика ────────────────────────────────────────────────────────

def test_the_student_lays_out_the_path_and_walks_it(tenant_a, goal):
    client = sign_in(tenant_a, tenant_a.student_user)

    body = client.post(
        reverse("cabinet:goal_steps_save", args=[goal.pk]),
        {"steps": "Разобрать синусы\nПрорешать задачи"},
    ).content.decode()
    assert "Разобрать синусы" in body
    assert "Пройдено 0 из 2" in body

    with organization_context(tenant_a.organization):
        step = goal.steps.order_by("position").first()

    body = client.post(
        reverse("cabinet:goal_step_toggle", args=[step.pk])
    ).content.decode()
    assert "Пройдено 1 из 2" in body
    # Один шаг из двух — это ровно половина пути, и похвала об этом и говорит.
    assert "Половина пути позади" in body


def test_a_goal_without_steps_offers_help_instead_of_blame(tenant_a, goal):
    """
    Пустая цель — не вина ученика. Сказано, почему она не двигается, и что
    шаги можно разложить не в одиночку.
    """
    client = sign_in(tenant_a, tenant_a.student_user)
    body = client.get(reverse("cabinet:student_home")).content.decode()

    assert "Шагов пока нет" in body
    assert "наставника или" in body


def test_nobody_else_ticks_the_steps(tenant_a, tenant_b, goal):
    """Путь его, и цена отметки в том, что она правдива."""
    with organization_context(tenant_a.organization):
        step = set_steps(goal=goal, titles=["Мой шаг"])[0]

    stranger = sign_in(tenant_b, tenant_b.student_user)
    response = stranger.post(reverse("cabinet:goal_step_toggle", args=[step.pk]))

    assert response.status_code in (403, 404)
    step.refresh_from_db()
    assert not step.is_done


def test_the_companion_is_chosen_by_the_student(tenant_a):
    client = sign_in(tenant_a, tenant_a.student_user)
    client.post(reverse("cabinet:hero_choose"), {"hero": Hero.ROCKET})

    tenant_a.student.refresh_from_db()
    assert tenant_a.student.hero == Hero.ROCKET


def test_a_made_up_companion_is_ignored(tenant_a):
    client = sign_in(tenant_a, tenant_a.student_user)
    client.post(reverse("cabinet:hero_choose"), {"hero": "godzilla"})

    tenant_a.student.refresh_from_db()
    assert tenant_a.student.hero == Hero.TRAVELLER


def test_steps_of_a_hidden_goal_stay_hidden(tenant_a):
    """
    У скрытой цели скрыты и шаги. Отдельного правила для них нет: обещание
    «скрытую цель не видит никто» не должно повторяться дважды.
    """
    with organization_context(tenant_a.organization):
        hidden = Goal.objects.create(
            organization=tenant_a.organization, student=tenant_a.student,
            kind=GoalKind.PERSONAL, title="Личное",
            visibility=GoalVisibility.HIDDEN,
        )
        set_steps(goal=hidden, titles=["Тайный шаг"])

    teacher = sign_in(tenant_a, tenant_a.teacher_user)
    body = teacher.get(
        reverse("cabinet:progress_student", args=[tenant_a.student.pk])
    ).content.decode()

    assert "Тайный шаг" not in body
    assert "Личное" not in body


# ─── Спутник и архив ────────────────────────────────────────────────────────

def test_the_chosen_companion_is_marked_right_away(tenant_a):
    """
    Раньше выбор спутника жил вне обновляемого блока: нажимаешь — а по
    экрану непонятно, выбралось ли. Отметка «текущий» должна приезжать
    вместе с ответом.
    """
    client = sign_in(tenant_a, tenant_a.student_user)
    body = client.post(reverse("cabinet:hero_choose"), {"hero": Hero.COMPASS}).content.decode()

    assert "hero-picker" in body
    assert 'value="compass"' in body
    marked = body[body.index('value="compass"') - 400:body.index('value="compass"') + 200]
    assert "is-current" in marked


def test_an_achieved_goal_goes_to_the_archive_not_to_nowhere(tenant_a, goal):
    """
    Достигнутая цель исчезала с экрана насовсем. Список сделанного — и есть
    ответ на вопрос «двигаюсь ли я вообще», которого одна активная цель
    не даёт.
    """
    client = sign_in(tenant_a, tenant_a.student_user)
    body = client.post(reverse("cabinet:goal_toggle", args=[goal.pk])).content.decode()

    assert "Достигнутые цели" in body
    assert goal.title in body
    assert "Вернуть в работу" in body


def test_a_goal_can_come_back_from_the_archive(tenant_a, goal):
    """«Достиг» иногда оказывается «показалось»."""
    client = sign_in(tenant_a, tenant_a.student_user)
    client.post(reverse("cabinet:goal_toggle", args=[goal.pk]))
    body = client.post(reverse("cabinet:goal_toggle", args=[goal.pk])).content.decode()

    assert "Достигнутые цели" not in body
    assert goal.title in body
