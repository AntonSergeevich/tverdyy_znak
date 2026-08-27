"""
Мелочи, которые видно глазом, но не видно тестам.

Здесь то, что уже один раз сломалось: смайл на шкале оставался
одноглазым, а подсказка в конструкторе занимала колонку целиком.
"""
from __future__ import annotations

import pathlib

import pytest
from django.test import override_settings
from django.urls import reverse

from tests.conftest import PASSWORD

CSS = pathlib.Path("static/css/site.css").read_text(encoding="utf-8")
PANEL = pathlib.Path("templates/public/partials/scale_panel.html").read_text(encoding="utf-8")


def test_the_smiley_always_has_two_eyes():
    """
    Раньше правого глаза в разметке не было вовсе.

    Вместо него лежала дуга закрытого глаза, которая появлялась на время
    подмигивания и гасла обратно, — и смайл оставался одноглазым.
    """
    # Считаем сами элементы: в классе правого глаза имя встречается дважды.
    assert PANEL.count('<circle class="scale-wink__eye') == 2
    assert "scale-wink__wink" not in PANEL


def test_the_wink_returns_to_normal():
    """Подмигивание заканчивается открытым глазом, а не любым другим видом."""
    animation = CSS.split("@keyframes tz-wink {")[1].split("\n}")[0]

    assert "scaleY(.14)" in animation
    assert "100% { transform: scaleY(1); }" in animation


def test_the_smiley_is_the_letter_of_the_centre():
    """
    Смайл собран из буквы Ъ, а не из безымянного кружка.

    Кружок с точками — иконка откуда угодно; знак центра — только его.
    """
    assert "<circle cx=\"32\" cy=\"32\"" not in PANEL  # прежняя окружность-лицо
    assert "M10 13 H22 V50" in PANEL                    # стойка с флагом
    assert "Q31.5 40.5 41 33" in PANEL                  # провисающий край чаши — улыбка


def test_the_scale_panel_renders_the_smiley(client, tenant_a):
    """Шкала стоит на главной дважды, и глаз должно быть по два на каждой."""
    client.defaults["HTTP_HOST"] = tenant_a.host
    body = client.get(reverse("public:landing")).content.decode()

    panels = body.count('data-scale-wink')
    assert panels >= 1
    assert body.count('<circle class="scale-wink__eye') == panels * 2


@pytest.fixture
def owner_client(client, tenant_a):
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.defaults["HTTP_HOST"] = tenant_a.host
        client.post(
            reverse("accounts:login"),
            {"username": tenant_a.owner_user.email, "password": PASSWORD},
        )
        yield client


def test_the_builder_hint_lives_above_the_teachers(owner_client):
    """
    Подсказка стоит в верхней панели, а не в колонке педагогов.

    В колонке она занимала экран целиком, и до первой карточки
    приходилось прокручивать.
    """
    body = owner_client.get(reverse("cabinet:schedule_builder")).content.decode()

    bar = body.index('class="builder-bar"')
    aside = body.index('class="builder__side"')
    hint = body.index('class="builder-help"')

    assert bar < hint < aside


def test_the_clear_button_sits_on_the_button_row(owner_client):
    """
    Кнопка «Очистить неделю» — прямой ребёнок панели.

    Вложенная в соседний ряд, она выравнивалась по середине высокой
    подписи и висела выше «Повторить».
    """
    body = owner_client.get(reverse("cabinet:schedule_builder")).content.decode()
    bar = body.split('class="builder-bar"')[1].split("</div>")[0]

    # Между открытием панели и кнопкой нет вложенного btn-row.
    before_button = body.split("data-clear-week")[0]
    label_row = before_button.rindex('<label class="field"')
    assert before_button.count("</label>", label_row) == 1

    assert "data-clear-week" in body
    assert "btn--danger" in body


def test_a_destructive_button_is_not_the_loudest_one():
    """Заливка перетягивала бы внимание с кнопки, которой пользуются каждый день."""
    rule = CSS.split(".btn--quiet.btn--danger {")[1].split("}")[0]

    assert "var(--surface)" in rule
    assert "var(--accent-2)" in rule
