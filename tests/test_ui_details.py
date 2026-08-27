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


# ─── Колода конструктора ────────────────────────────────────────────────────
#
# Всё, что здесь проверяется, уже один раз мешало работать: карточки
# уезжали за нижний край экрана, переключение недель пряталось наверху
# страницы, а пальцем карточка не бралась вовсе.

BUILDER = pathlib.Path(
    "templates/cabinet/manage/schedule_builder.html"
).read_text(encoding="utf-8")
SCHEDULER_JS = pathlib.Path("static/js/scheduler.js").read_text(encoding="utf-8")


def test_week_switch_sits_next_to_the_grid(owner_client):
    """
    Чтобы перелистнуть неделю, приходилось прокручивать наверх.

    И на телефоне, и на большом экране: переключатель жил в заголовке
    страницы, а работают с сеткой.
    """
    body = owner_client.get(reverse("cabinet:schedule_builder")).content.decode()

    weeks = body.index('class="builder__weeks"')
    grid = body.index("data-grid")
    title = body.index('class="page-title"')

    assert title < weeks < grid


def test_the_deck_shows_only_the_name_and_the_subject():
    """
    Из колоды таскают, её не рассматривают.

    Фотография и стаж делали карточку вдвое выше — восемь блоков дня
    уезжали за нижний край экрана.
    """
    deck = BUILDER.split('class="teacher-deck"')[1].split("</ul>")[0]

    assert "deck-card__name" in deck
    assert "deck-card__subjects" in deck
    assert "card_photo" not in deck
    assert "deck-card__photo" not in deck


def test_the_deck_is_two_columns_everywhere():
    """Один ряд на всю ширину колонки — это лишняя прокрутка на ровном месте."""
    rule = CSS.split(".teacher-deck {")[1].split("}")[0]

    assert "repeat(2, minmax(0, 1fr))" in rule


def test_day_blocks_live_under_the_grid():
    """
    Блоков восемь и больше, и в узкой колонке они уходили под экран.

    Под сеткой они лежат строкой ровно там, куда их и роняют.
    """
    grid = BUILDER.index("data-grid")
    blocks = BUILDER.index('class="builder__blocks"')
    side = BUILDER.index('class="builder__side"')

    assert side < grid < blocks


def test_dragging_does_not_rely_on_the_browsers_own_mechanism():
    """
    Встроенное перетаскивание на телефонах не работает.

    Android его не знает, а десктопный браузер в режиме телефона
    перестаёт его выдавать — карточка просто не бралась.
    """
    assert 'draggable="true"' not in BUILDER
    assert "dragstart" not in SCHEDULER_JS
    assert "pointerdown" in SCHEDULER_JS
    assert "pointermove" in SCHEDULER_JS


def test_taking_a_card_buzzes_the_phone():
    """Без отклика непонятно, взялась карточка или ты просто держишь палец."""
    assert "navigator.vibrate" in SCHEDULER_JS


def test_a_held_card_stops_the_page_from_scrolling():
    """
    Пока карточка в руке, палец не должен листать страницу.

    Слушатель обязан быть непассивным — иначе браузер не даст отменить
    прокрутку, и карточка не доедет до сетки.
    """
    handler = SCHEDULER_JS.split("card.addEventListener('touchmove'")[1].split("});")[0]

    assert "preventDefault" in handler
    assert "passive: false" in SCHEDULER_JS.split(
        "card.addEventListener('touchmove'"
    )[1][:400]


def test_document_listeners_are_registered_once():
    """
    Кабинет ходит по ссылкам без перезагрузки.

    Слушатели на документе внутри init копились бы с каждым переходом и
    ссылались на давно заменённую сетку.
    """
    init_at = SCHEDULER_JS.index("function init()")
    tail = SCHEDULER_JS[init_at:]

    assert "document.addEventListener('pointermove'" not in tail
    assert "document.addEventListener('pointerup'" not in tail
