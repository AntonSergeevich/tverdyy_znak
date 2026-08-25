"""
Пересборка брендовых шрифтов в woff2 с сабсетом под кириллицу.

Готовые файлы уже лежат в static/fonts/ — скрипт нужен, только если
заказчик пришлёт новые начертания.

    python scripts/build_fonts.py
"""
from __future__ import annotations

import pathlib

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

SRC = pathlib.Path("design/fonts")
DST = pathlib.Path("static/fonts")

# Кириллица, латиница, пунктуация, знак рубля, стрелки и символы тем.
UNICODES = (
    set(range(0x20, 0x7F))
    | set(range(0x0400, 0x0460))
    | {
        0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026, 0x00A0, 0x00B7,
        0x20BD, 0x2116, 0x2192, 0x2600, 0x263E, 0x2264, 0x2265, 0x00D7,
    }
)

FILES = {
    "Constantine.ttf": "constantine-regular",
    "Constantine_Bold.ttf": "constantine-bold",
    "BebasNeueCyrillic.ttf": "bebas-cyr",
}


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    for source_name, target_name in FILES.items():
        source = SRC / source_name
        if not source.exists():
            print(f"пропуск: нет файла {source}")
            continue

        font = TTFont(str(source))
        options = Options()
        options.layout_features = ["*"]
        options.desubroutinize = True
        options.name_IDs = ["*"]
        options.notdef_outline = True

        subsetter = Subsetter(options=options)
        subsetter.populate(unicodes=UNICODES)
        subsetter.subset(font)

        font.flavor = "woff2"
        target = DST / f"{target_name}.woff2"
        font.save(str(target))
        print(f"{target} — {target.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
