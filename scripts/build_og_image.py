"""
Обложка ссылки для мессенджеров и соцсетей (Open Graph).

    python scripts/build_og_image.py

Результат — static/img/og-cover.png, 1200×630. Именно PNG: SVG в превью
не показывает почти никто — ни Telegram, ни ВКонтакте, ни WhatsApp.

Собирается из брендовых шрифтов и фирменных цветов, поэтому пересобрать
её после правки текста — одна команда.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont as FTFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE_DIR = Path(__file__).resolve().parent.parent
BRAND_FONTS = BASE_DIR / "design" / "fonts"
WEB_FONTS = BASE_DIR / "static" / "fonts"
TARGET = BASE_DIR / "static" / "img" / "og-cover.png"

SIZE = (1200, 630)
PAPER = (245, 241, 234)
INK = (35, 32, 29)
INK_2 = (74, 68, 61)
ACCENT = (232, 120, 60)
MARK = (236, 224, 212)

KICKER = "ЦЕНТР СЕМЕЙНОГО ОБУЧЕНИЯ И ПРОФОРИЕНТАЦИИ"
TITLE = ["Семейный класс", "«Твёрдый знак»"]
BULLETS = [
    "Гибкий график",
    "Группа до 10 человек",
    "Подготовка к ОГЭ и ЕГЭ",
    "Профориентация",
]
FOOTER = "8–11 КЛАСС · КРАСНОЯРСК · TVERDYY-ZNAK.RU"


def brand_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = BRAND_FONTS / name
    if not path.exists():
        raise SystemExit(f"Нет шрифта {path}. Каталог design/fonts обязателен для сборки обложки.")
    return ImageFont.truetype(str(path), size)


def manrope_fonts(size: int, weight: float, cache: dict = {}) -> list[tuple]:
    """
    Manrope для основного текста.

    Полного TTF в открытом виде нет — Google отдаёт вариативный шрифт
    сабсетами: кириллица отдельно, латиница с цифрами отдельно.
    Возвращаем оба; текст рисуется посимвольно тем из них, где глиф есть.
    Начертание одно и то же, поэтому стык не виден.
    """
    key = (size, weight)
    if key in cache:
        return cache[key]

    fonts = []
    tmp = Path(tempfile.gettempdir()) / "tz-og-fonts"
    tmp.mkdir(exist_ok=True)
    for subset in ("cyrillic", "latin"):
        source = WEB_FONTS / f"manrope-var-{subset}.woff2"
        ttf = tmp / f"manrope-{subset}.ttf"
        if not ttf.exists():
            web = FTFont(str(source))
            web.flavor = None
            web.save(str(ttf))
        font = ImageFont.truetype(str(ttf), size)
        try:
            font.set_variation_by_axes([weight])
        except OSError:  # pragma: no cover — шрифт оказался не вариативным
            pass
        # Покрытие берём из cmap. По растру определять нельзя: у отсутствующего
        # символа рисуется .notdef — пустой квадрат с непустым bbox, и проверка
        # «есть ли что рисовать» считает его нормальным глифом.
        coverage = set(FTFont(str(ttf)).getBestCmap())
        fonts.append((font, coverage))
    cache[key] = fonts
    return fonts


def draw_mixed(draw: ImageDraw.ImageDraw, xy, text: str, fonts, fill) -> None:
    """Рисует строку, подбирая под каждый символ шрифт, где такой глиф есть."""
    x, y = xy
    missing = []
    for char in text:
        font = next((f for f, coverage in fonts if ord(char) in coverage), None)
        if font is None:
            missing.append(char)
            font = fonts[0][0]
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font)
    if missing:
        print(f"  внимание: нет глифов для {missing} — символы вышли квадратами")


def paper_background() -> Image.Image:
    """Бумага с фактурой: мягкие заломы плюс мелкое зерно."""
    image = Image.new("RGB", SIZE, PAPER)

    creases = Image.effect_noise(SIZE, 40).convert("L").filter(ImageFilter.GaussianBlur(30))
    image = Image.composite(Image.new("RGB", SIZE, (231, 225, 215)), image, creases)

    grain = Image.effect_noise(SIZE, 10).convert("L").point(lambda v: max(0, v - 120))
    image = Image.composite(Image.new("RGB", SIZE, (238, 233, 225)), image, grain)
    return image


def build() -> Path:
    image = paper_background()
    draw = ImageDraw.Draw(image)

    # Декоративный «Ъ» — тот же приём, что на первом экране сайта.
    draw.text((880, 30), "Ъ", font=brand_font("Constantine_Bold.ttf", 640), fill=MARK)

    left, y = 84, 74

    draw.text((left, y), KICKER, font=brand_font("BebasNeueCyrillic.ttf", 30), fill=ACCENT)
    y += 58

    title_font = brand_font("Constantine_Bold.ttf", 76)
    for line in TITLE:
        draw.text((left, y), line, font=title_font, fill=INK)
        y += 86

    y += 22
    bullet_fonts = manrope_fonts(38, weight=500)
    for item in BULLETS:
        draw.rectangle((left + 2, y + 15, left + 18, y + 31), fill=ACCENT)
        draw_mixed(draw, (left + 40, y), item, bullet_fonts, INK_2)
        y += 56

    draw.text(
        (left, SIZE[1] - 62), FOOTER, font=brand_font("BebasNeueCyrillic.ttf", 26), fill=INK_2
    )
    # Оранжевая полоса слева — узнаваемая деталь брендбука.
    draw.rectangle((0, 0, 12, SIZE[1]), fill=ACCENT)

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    image.save(TARGET, "PNG", optimize=True)
    return TARGET


if __name__ == "__main__":
    path = build()
    print(f"{path.relative_to(BASE_DIR)} — {path.stat().st_size // 1024} КБ, {SIZE[0]}×{SIZE[1]}")
