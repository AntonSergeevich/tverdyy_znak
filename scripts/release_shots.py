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
    if height is None:
        return shot.crop((0, top * scale, shot.width, shot.height)).convert("RGB")
    # Кадры одной анимации обязаны быть одного размера: у нижнего края
    # экрана окно сдвигается вверх, а не обрезается.
    top = max(0, min(top * scale, shot.height - height * scale))
    return shot.crop((0, top, shot.width, top + height * scale)).convert("RGB")


def _press(page, selector):
    """
    Палец на элемент — синтетические pointer-события, как у тач-экрана.

    Касание — в левый верхний угол, где подпись: с полей ввода жест
    намеренно не начинается.
    """
    box = page.locator(selector).first.bounding_box()
    x, y = box["x"] + 40, box["y"] + 22
    page.evaluate(
        """([x, y]) => {
          const target = document.elementFromPoint(x, y);
          target.dispatchEvent(new PointerEvent('pointerdown', {
            bubbles: true, pointerType: 'touch', isPrimary: true, clientX: x, clientY: y }));
          window.__swipe = { target, x, y };
        }""",
        [x, y],
    )


def _drag(page, dx):
    page.evaluate(
        """(dx) => {
          const s = window.__swipe;
          for (let i = 1; i <= 8; i++) {
            document.dispatchEvent(new PointerEvent('pointermove', {
              bubbles: true, pointerType: 'touch', isPrimary: true,
              clientX: s.x + dx * i / 8, clientY: s.y }));
          }
          s.dx = dx;
        }""",
        dx,
    )
    page.wait_for_timeout(120)


def _release(page):
    page.evaluate(
        """() => {
          const s = window.__swipe;
          document.dispatchEvent(new PointerEvent('pointerup', {
            bubbles: true, pointerType: 'touch', isPrimary: true,
            clientX: s.x + s.dx, clientY: s.y }));
        }"""
    )
    page.wait_for_timeout(900)


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
    lesson = _demo_lesson(page)
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


def _demo_lesson(page, latest=False):
    """Прошедшее занятие демо-педагога — из расписания за последние недели."""
    pick = "a[a.length - 1]" if latest else "a[0]"
    for weeks_back in range(0, 6):
        _go(page, f"/kabinet/raspisanie/?n=-{weeks_back}")
        lesson = page.evaluate(
            "() => { const a = [...document.querySelectorAll('a[href*=\"/zanyatie/\"]')];"
            f" return a.length ? {pick}.getAttribute('href') : null; }}"
        )
        if lesson:
            return lesson
    raise SystemExit("В демо-базе нет занятий педагога — запустите seed_demo.")


def shots_2_1(browser, out: Path):
    # Педагог задаёт домашнее на демо-занятии — чтобы было что проверять
    # и что отметить ученику.
    context, page = _login(browser, "teacher")
    # Последнее занятие — в текущем модуле: задание из прошлого модуля
    # ученик уже не видит.
    lesson = _demo_lesson(page, latest=True)
    _go(page, lesson + "?vkladka=domashnee")
    area = page.locator("#lesson-homework textarea").first
    if not area.input_value().strip():
        area.fill("§12, задачи 3–7 письменно")
        page.locator("#lesson-homework button[type=submit]").first.click()
        page.wait_for_timeout(800)
    _go(page, lesson + "?vkladka=domashnee")
    page.evaluate("document.querySelectorAll('details.hw-archive').forEach(d => d.open = true)")
    row = ".review-row[data-swipe-row]"
    page.locator(row).first.scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, -120)")
    page.wait_for_timeout(200)
    top = int(page.locator(row).first.bounding_box()["y"]) - 90
    frames = [_frame(page, top=top, height=330)]
    _press(page, row)
    _drag(page, 70)
    frames.append(_frame(page, top=top, height=330))
    _drag(page, 170)
    frames.append(_frame(page, top=top, height=330))
    _release(page)
    page.evaluate("window.scrollBy(0, -120)")
    top = int(page.locator(row).first.bounding_box()["y"]) - 90
    frames.append(_frame(page, top=top, height=330))
    _save(out / "review-swipe.webp", frames, step_ms=1200)
    context.close()

    # Ученик смахивает карточку задания.
    context, page = _login(browser, "student1")
    _go(page, "/kabinet/uchenik/")
    card = "#homework-board [data-swipe-row]"
    if page.locator(card).count():
        page.locator(card).first.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        top = max(0, int(page.locator(card).first.bounding_box()["y"]) - 70)
        frames = [_frame(page, top=top, height=360)]
        _press(page, card)
        _drag(page, 180)
        frames.append(_frame(page, top=top, height=360))
        _release(page)
        _go(page, "/kabinet/uchenik/")
        page.locator("#homework-board").scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        top = max(0, int(page.locator("#homework-board").bounding_box()["y"]) - 70)
        frames.append(_frame(page, top=top, height=360))
        _save(out / "homework-swipe.webp", frames, step_ms=1300)
        # Демо-ученик возвращается к «не сделано» — снимки можно переснимать.
        page.locator("#homework-board button:has-text('Убрать отметку')").first.click()
        page.wait_for_timeout(500)
    context.close()

    # «Отменить»: руководитель убирает ученика из курса и возвращает.
    context, page = _login(browser, "owner")
    _go(page, "/kabinet/gruppy/")
    for link in page.locator("table a[href*='/gruppy/']").all():
        href = link.get_attribute("href")
        _go(page, href)
        if page.locator("button:has-text('убрать из группы')").count():
            break
        _go(page, "/kabinet/gruppy/")
    page.locator("button:has-text('убрать из группы')").first.click()
    page.wait_for_load_state("networkidle")
    _clean(page)
    page.wait_for_timeout(400)
    _save(out / "undo.webp", [_frame(page, top=PHONE["height"] - 330)])
    page.locator("[data-undo-toast] button").first.click()
    page.wait_for_load_state("networkidle")
    context.close()


VERSIONS = {"2.0": shots_2_0, "2.1": shots_2_1}


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
