"""
Обработка фотографий педагогов для публичной страницы.

Что делает: выравнивает поворот по EXIF, кадрирует под портрет 4:5 с
запасом сверху (лицо обычно в верхней трети), приводит к 800×1000,
слегка поднимает контраст и резкость, сохраняет WebP.

    python scripts/prepare_teacher_photos.py            # все файлы
    python scripts/prepare_teacher_photos.py manasyan   # только один

Исходники — в assets/teachers/, результат — в media/teachers/.
Идемпотентно: повторный запуск просто перезапишет результат.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "assets" / "teachers"
DST_DIR = BASE_DIR / "media" / "teachers"

TARGET_SIZE = (800, 1000)          # 4:5, как в сетке карточек
FACE_BIAS = 0.38                   # доля отступа сверху при кадрировании
WEBP_QUALITY = 86
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}

# Имя файла = слаг педагога. Скрипт обрабатывает и «чужие» имена, но
# на сайт попадут только эти: setup_client_data ищет media/teachers/<слаг>.webp.
KNOWN_SLUGS = {
    "babadzhanova": "Бабаджанова Алина Алимовна — основатель центра",
    "manasyan": "Манасян Сергей Керопович — математика, физика, информатика",
    "polskaya": "Польская Юлия Евгеньевна — химия и биология",
    "margarita": "Маргарита Андреевна — английский язык",
    "anna": "Анна Константиновна — профориентолог",
}


def crop_portrait(image: Image.Image) -> Image.Image:
    """
    Кадрирование под 4:5 со смещением вверх.

    Центральный кроп на портретах срезает макушку и оставляет пустой низ,
    поэтому вертикально режем не по центру, а ближе к верху.
    """
    target_ratio = TARGET_SIZE[0] / TARGET_SIZE[1]
    width, height = image.size
    current_ratio = width / height

    if current_ratio > target_ratio:
        # Слишком широкое — режем по бокам, по центру.
        new_width = round(height * target_ratio)
        left = (width - new_width) // 2
        box = (left, 0, left + new_width, height)
    else:
        # Слишком высокое — режем сверху и снизу со смещением к лицу.
        new_height = round(width / target_ratio)
        top = round((height - new_height) * FACE_BIAS)
        top = max(0, min(top, height - new_height))
        box = (0, top, width, top + new_height)
    return image.crop(box)


def enhance(image: Image.Image) -> Image.Image:
    """Мягкое улучшение: контраст, цвет, резкость. Без «пластика»."""
    image = ImageOps.autocontrast(image, cutoff=(0.5, 0.5))
    image = ImageEnhance.Color(image).enhance(1.04)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.6, percent=110, threshold=3))
    return image


def process(source: Path) -> Path:
    with Image.open(source) as raw:
        image = ImageOps.exif_transpose(raw)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        elif image.mode == "L":
            image = image.convert("RGB")

        original = image.size
        image = crop_portrait(image)
        image = image.resize(TARGET_SIZE, Image.LANCZOS)
        image = enhance(image)

        DST_DIR.mkdir(parents=True, exist_ok=True)
        target = DST_DIR / f"{source.stem}.webp"
        image.save(target, "WEBP", quality=WEBP_QUALITY, method=6)

    size_kb = target.stat().st_size // 1024
    upscaled = " (апскейл — исходник мелковат)" if min(original) < 800 else ""
    print(f"{source.name} {original[0]}×{original[1]} → {target.name} {size_kb} КБ{upscaled}")
    return target


def main(argv: list[str]) -> int:
    if not SRC_DIR.exists():
        print(f"Нет каталога {SRC_DIR}. Положите оригиналы туда — см. README в нём.")
        return 1

    wanted = {name.lower() for name in argv}
    sources = sorted(
        path
        for path in SRC_DIR.iterdir()
        if path.suffix.lower() in SUPPORTED and (not wanted or path.stem.lower() in wanted)
    )
    if not sources:
        print(f"В {SRC_DIR} нет подходящих файлов. Ожидаются: {', '.join(sorted(SUPPORTED))}")
        return 1

    done: list[str] = []
    for source in sources:
        try:
            process(source)
            done.append(source.stem.lower())
        except Exception as error:  # noqa: BLE001 — одна битая картинка не должна ронять пакет
            print(f"{source.name}: не удалось обработать — {error}")

    return _report(done)


def _report(done: list[str]) -> int:
    """Понятный итог: что встанет на сайт, что нет и что делать дальше."""
    ready = [slug for slug in KNOWN_SLUGS if slug in done]
    unknown = [slug for slug in done if slug not in KNOWN_SLUGS]
    missing = [slug for slug in KNOWN_SLUGS if slug not in done]

    print()
    if ready:
        print(f"На сайт встанут ({len(ready)} из {len(KNOWN_SLUGS)}):")
        for slug in ready:
            print(f"  {slug}.webp — {KNOWN_SLUGS[slug]}")

    if unknown:
        print("\nЭти файлы обработаны, но на сайт НЕ попадут — имя не совпадает")
        print("ни с одним педагогом:")
        for slug in unknown:
            print(f"  {slug}.webp")
        print("\nПереименуйте ОРИГИНАЛЫ в assets/teachers/ и запустите скрипт заново.")

    if missing:
        print("\nНе хватает фотографий:")
        for slug in missing:
            print(f"  {slug} — {KNOWN_SLUGS[slug]}")

    if ready:
        print("\nДальше: python manage.py setup_client_data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
