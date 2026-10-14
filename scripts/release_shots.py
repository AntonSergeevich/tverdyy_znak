"""
Снимки для страницы обновлений — с демо-кабинета, не с рабочего сайта.

На снимках только выдуманные ученики из `seed_demo`: настоящих детей в
заметках к версиям быть не может (152-ФЗ). Поэтому скрипт ходит на
локальный сервер с демо-базой и отказывается работать с любым другим.

Запуск (локальный сервер уже поднят на демо-базе):

    .venv/bin/python manage.py seed_demo
    .venv/bin/python manage.py runserver 127.0.0.1:8123
    .venv/bin/python scripts/release_shots.py 2.0

Картинки — WebP шириной 780 px (телефон 390 px при двойной плотности):
лёгкие и чёткие. Шаги одного действия склеиваются в анимированный WebP —
он играет сам, без кнопок, и открывается в любом современном браузере.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8123"
PASSWORD = "demo-parol-12345"
PHONE = {"width": 390, "height": 844}
ROOT = Path(__file__).resolve().parent.parent
CHROMIUM = "/opt/pw-browsers/chromium"


def _clean(page):
    # Отладочная панель Django в демо-режиме — на снимках ей не место.
    page.evaluate("document.querySelectorAll('#djDebugRoot,#djDebug').forEach(n => n.remove())")


def _login(browser, who):
    context = browser.new_context(
        viewport=PHONE, is_mobile=True, has_touch=True, device_scale_factor=2,
        color_scheme="light",
    )
    page = context.new_page()
    page.goto(f"{BASE}/vhod/")
    _clean(page)
    page.fill("input[name=username]", f"{who}@example.org")
    page.fill("input[name=password]", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    _clean(page)
    if page.locator("dialog[open]").count():
        page.click("[data-whats-new-close]")
    page.wait_for_timeout(300)
    return context, page


def _go(page, path):
    page.goto(BASE + path)
    page.wait_for_load_state("networkidle")
    _clean(page)
    page.wait_for_timeout(300)


def _frame(page, top=0, height=None) -> Image.Image:
    shot = Image.open(io.BytesIO(page.screenshot()))
    scale = shot.width // PHONE["width"]
    bottom = shot.height if height is None else min(shot.height, (top + height) * scale)
    return shot.crop((0, top * scale, shot.width, bottom)).convert("RGB")


def _save(target: Path, frames: list[Image.Image], step_ms: int = 1700):
    target.parent.mkdir(parents=True, exist_ok=True)
    if len(frames) == 1:
        frames[0].save(target, "WEBP", quality=78, method=6)
    else:
        frames[0].save(
            target, "WEBP", quality=72, method=6,
            save_all=True, append_images=frames[1:], duration=step_ms, loop=0,
        )
    print(f"  {target.relative_to(ROOT)} — {target.stat().st_size // 1024} КБ")


def shots_2_0(browser, out: Path):
    # Нижнее меню: панель руководителя, затем открытая группа «Дети».
    context, page = _login(browser, "owner")
    first = _frame(page, top=PHONE["height"] - 480)
    page.click(".cabinet-nav .nav-group__label:has-text('Дети')")
    page.wait_for_timeout(300)
    second = _frame(page, top=PHONE["height"] - 480)
    _save(out / "phone-menu.webp", [first, second])
    page.click(".cabinet-nav .nav-group__label:has-text('Дети')")
    page.wait_for_timeout(200)

    # Меню профиля.
    page.click(".account__button")
    page.wait_for_timeout(300)
    _save(out / "account-menu.webp", [_frame(page, top=0, height=420)])
    context.close()

    context, page = _login(browser, "teacher")

    # Вкладки занятия — по очереди.
    # Ближайшее прошедшее занятие демо-педагога — из расписания пару недель назад.
    lesson = None
    for weeks_back in range(0, 6):
        _go(page, f"/kabinet/raspisanie/?n=-{weeks_back}")
        lesson = page.evaluate(
            "() => { const a = document.querySelector('a[href*=\"/zanyatie/\"]');"
            " return a ? a.getAttribute('href') : null; }"
        )
        if lesson:
            break
    _go(page, lesson)
    frames = []
    for tab in ("ucheniki", "domashnee", "raboty"):
        page.click(f"[data-tab={tab}]")
        page.wait_for_timeout(250)
        page.evaluate("window.scrollTo(0, 0)")
        frames.append(_frame(page, top=0, height=760))
    _save(out / "lesson-tabs.webp", frames)
    context.close()

    # Карточки вместо таблиц: список учеников у руководителя.
    context, page = _login(browser, "owner")
    _go(page, "/kabinet/ucheniki/")
    _save(out / "cards.webp", [_frame(page, top=0, height=700)])
    context.close()

    # Кабинет ученика: сегодня и домашнее сверху.
    context, page = _login(browser, "student1")
    _go(page, "/kabinet/uchenik/")
    _save(out / "student-home.webp", [_frame(page, top=0, height=760)])
    context.close()


VERSIONS = {"2.0": shots_2_0}


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else ""
    if version not in VERSIONS:
        sys.exit(f"Укажите версию: {', '.join(VERSIONS)}")
    if not BASE.startswith("http://127.0.0.1"):
        sys.exit("Снимки — только с локального демо-кабинета.")
    out = ROOT / "static" / "img" / "updates" / version
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROMIUM)
        VERSIONS[version](browser, out)
        browser.close()


if __name__ == "__main__":
    main()
