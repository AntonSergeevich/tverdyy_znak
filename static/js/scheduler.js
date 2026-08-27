/**
 * Конструктор расписания: карточки педагогов и блоков дня — в сетку.
 *
 * Карточка остаётся на месте после перетаскивания — одного педагога
 * ставят на несколько уроков подряд, и «взял и потерял» здесь было бы
 * издевательством.
 *
 * Всё сохраняется сразу: составление расписания — это десятки мелких
 * действий, и забытая кнопка «сохранить» стоила бы часа работы.
 *
 * Перетаскивание сделано на pointer-событиях, а не на встроенном в
 * браузер draggable. Встроенное на телефонах не работает вовсе: Android
 * его не знает, а десктопный браузер, если включить в нём режим
 * телефона, перестаёт его выдавать. Свои указатели ведут себя одинаково
 * и под мышью, и под пальцем.
 */
(function () {
  'use strict';

  var HOLD_MS = 200;   // сколько держать пальцем, чтобы взять карточку
  var SLIP_PX = 10;    // сдвиг, после которого это уже прокрутка, а не взятие
  var EDGE_PX = 90;    // у края экрана страница подкручивается сама

  // Состояние перетаскивания живёт снаружи init: кабинет ходит по
  // ссылкам без перезагрузки, init поднимается заново на каждой странице,
  // и слушатели на документе иначе копились бы с каждым переходом.
  var page = null;     // {say, place} текущего конструктора
  var drag = null;     // {card, ghost} пока карточка в руке
  var armed = null;    // карточка, выбранная нажатием и ждущая клетки
  var press = null;    // {card, x, y, timer} между нажатием и взятием

  function buzz() {
    // Отклик на взятие: без него на телефоне непонятно, поднялась
    // карточка или ты просто держишь палец на экране.
    if (!navigator.vibrate) return;
    try { navigator.vibrate(12); } catch (e) { /* не всякий браузер умеет */ }
  }

  function slotAt(x, y) {
    var el = document.elementFromPoint(x, y);
    return el ? el.closest('[data-slot]') : null;
  }

  function clearHover(except) {
    document.querySelectorAll('.slot--over').forEach(function (el) {
      if (el !== except) el.classList.remove('slot--over');
    });
  }

  function disarm() {
    if (armed) armed.classList.remove('deck-card--armed');
    armed = null;
  }

  function arm(card) {
    // Нажатие без перетаскивания — тоже способ поставить: сначала
    // карточка, потом клетка. На телефоне это часто быстрее, чем нести
    // палец через пол-экрана.
    if (armed === card) {
      disarm();
      if (page) page.say('');
      return;
    }
    disarm();
    armed = card;
    card.classList.add('deck-card--armed');
    if (page) {
      page.say('Выбрано: ' + (card.getAttribute('data-name') || '') +
               '. Теперь нажмите клетку.');
    }
  }

  function cancelPress() {
    if (press && press.timer) clearTimeout(press.timer);
    press = null;
  }

  function beginDrag(card, x, y) {
    cancelPress();
    disarm();
    var ghost = document.createElement('div');
    ghost.className = 'deck-ghost';
    ghost.textContent = card.getAttribute('data-name') || '';
    document.body.appendChild(ghost);
    card.classList.add('deck-card--dragging');
    drag = { card: card, ghost: ghost };
    moveGhost(x, y);
    buzz();
  }

  function moveGhost(x, y) {
    if (!drag) return;
    drag.ghost.style.left = x + 'px';
    drag.ghost.style.top = y + 'px';

    var slot = slotAt(x, y);
    clearHover(slot);
    if (slot) slot.classList.add('slot--over');

    // Сетка ниже колоды, и на телефоне до неё надо доехать. Пока палец
    // у края — страница подкручивается сама, иначе карточку не донести.
    if (y < EDGE_PX) window.scrollBy(0, -14);
    else if (y > window.innerHeight - EDGE_PX) window.scrollBy(0, 14);
  }

  function dropDrag(x, y) {
    if (!drag) return;
    var card = drag.card;
    drag.ghost.remove();
    card.classList.remove('deck-card--dragging');
    drag = null;

    var slot = slotAt(x, y);
    clearHover(null);
    if (slot && page) page.place(slot, card, false);
  }

  function abortDrag() {
    if (!drag) return;
    drag.ghost.remove();
    drag.card.classList.remove('deck-card--dragging');
    drag = null;
    clearHover(null);
  }

  document.addEventListener('pointermove', function (event) {
    if (drag) {
      moveGhost(event.clientX, event.clientY);
      return;
    }
    if (!press) return;
    var slipped = Math.abs(event.clientX - press.x) + Math.abs(event.clientY - press.y);
    if (slipped < SLIP_PX) return;
    if (event.pointerType === 'mouse') {
      beginDrag(press.card, event.clientX, event.clientY);
    } else {
      // Палец поехал раньше, чем карточка поднялась, — это прокрутка.
      cancelPress();
    }
  });

  document.addEventListener('pointerup', function (event) {
    if (drag) dropDrag(event.clientX, event.clientY);
    cancelPress();
  });

  document.addEventListener('pointercancel', function () {
    abortDrag();
    cancelPress();
  });

  // ── Смена недели без рывка ────────────────────────────────────────────────
  //
  // htmx уводит страницу наверх, когда меняет адрес в строке браузера, —
  // он считает это переходом. Здесь переход мнимый: меняется половина
  // экрана, а человек смотрит в ту же клетку. Запоминаем, где он был,
  // и возвращаем туда же.

  var keepScroll = null;

  document.body.addEventListener('htmx:beforeRequest', function (event) {
    var el = event.target;
    if (el && el.closest && el.closest('.builder__weeks')) keepScroll = window.scrollY;
  });

  document.body.addEventListener('htmx:afterSettle', function () {
    if (keepScroll === null) return;
    var y = keepScroll;
    keepScroll = null;
    window.scrollTo(0, y);
    // htmx подкручивает и после разбора ответа — возвращаем ещё раз,
    // когда он точно закончил.
    setTimeout(function () { window.scrollTo(0, y); }, 0);
  });

  function init() {
  var grid = document.querySelector('[data-grid]');
  if (!grid || grid.dataset.ready === '1') return;
  grid.dataset.ready = '1';

  var status = document.querySelector('[data-builder-status]');

  function csrf() {
    var input = document.querySelector('input[name=csrfmiddlewaretoken]');
    if (input) return input.value;
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
  }

  function say(text, kind) {
    if (!status) return;
    status.textContent = text || '';
    status.className = 'builder__status' + (kind ? ' builder__status--' + kind : '');
    if (text && kind !== 'error') {
      setTimeout(function () {
        if (status.textContent === text) status.textContent = '';
      }, 4000);
    }
  }

  // ── Карточки ──────────────────────────────────────────────────────────────

  document.querySelectorAll('[data-teacher], [data-block]').forEach(function (card) {
    // Колода при смене недели не подменяется — подменяется только правая
    // половина. Без этой отметки init вешал бы на те же карточки новый
    // набор слушателей на каждое переключение.
    if (card.dataset.wired === '1') return;
    card.dataset.wired = '1';

    // Встроенное перетаскивание отключаем явно: иначе мышью запускались
    // бы сразу два механизма и картинка дёргалась.
    card.setAttribute('draggable', 'false');

    card.addEventListener('pointerdown', function (event) {
      if (event.button) return;
      press = {
        card: card, x: event.clientX, y: event.clientY, timer: null,
      };
      if (event.pointerType === 'mouse') return;   // мышью берём с первого движения
      // Палец поднимает карточку не сразу, а после короткого удержания:
      // иначе любая попытка прокрутить страницу уносила бы её с собой.
      press.timer = setTimeout(function () {
        if (press && press.card === card) beginDrag(card, press.x, press.y);
      }, HOLD_MS);
    });

    // Пока карточка в руке, палец не должен листать страницу. Слушатель
    // не пассивный — иначе браузер не даст отменить прокрутку.
    card.addEventListener('touchmove', function (event) {
      if (drag) event.preventDefault();
    }, { passive: false });

    card.addEventListener('click', function () { arm(card); });

    card.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      arm(card);
    });
  });

  // ── Постановка в клетку ───────────────────────────────────────────────────

  function place(slot, card, force) {
    var teacherId = card.getAttribute('data-teacher');
    var blockId = card.getAttribute('data-block');
    var body = new FormData();
    body.append('group', grid.getAttribute('data-group'));
    body.append('day', slot.getAttribute('data-day'));
    body.append('time', slot.getAttribute('data-time'));
    body.append('duration', slot.getAttribute('data-duration') || '40');
    if (force) body.append('force', '1');

    if (blockId) {
      // Блок дня — это «что»: педагога у него нет и не должно быть.
      body.append('subject', blockId);
    } else {
      body.append('teacher', teacherId);
      var picker = document.querySelector('[data-subject-for="' + teacherId + '"]');
      if (picker) body.append('subject', picker.value);
    }

    slot.classList.add('slot--busy');
    fetch(grid.getAttribute('data-set-url'), {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf() },
      body: body,
    }).then(function (response) {
      return response.text().then(function (text) {
        return { ok: response.ok, status: response.status, text: text };
      });
    }).then(function (result) {
      slot.classList.remove('slot--busy');
      if (result.ok) {
        replaceSlot(slot, result.text);
        say('Поставлено');
        return;
      }
      // За то, что стояло в клетке, уже ставили баллы. Спрашиваем один
      // раз — молча стирать чужую работу нельзя.
      var payload = readPayload(result.text);
      if (payload.needs_force &&
          window.confirm(payload.error + '\n\nЗаменить вместе с баллами?')) {
        place(slot, card, true);
        return;
      }
      say(payload.error || 'Не получилось.', 'error');
    }).catch(function () {
      slot.classList.remove('slot--busy');
      say('Не удалось сохранить — проверьте связь и попробуйте ещё раз.', 'error');
    });
  }

  page = { say: say, place: place };

  function readPayload(text) {
    try { return JSON.parse(text); } catch (e) { return {}; }
  }

  function replaceSlot(slot, html) {
    var holder = document.createElement('div');
    holder.innerHTML = html.trim();
    var fresh = holder.firstElementChild;
    if (fresh) slot.replaceWith(fresh);
  }

  // ── Клик по клетке ────────────────────────────────────────────────────────

  grid.addEventListener('click', function (event) {
    var button = event.target.closest('[data-clear-url]');
    if (button) {
      clear(button, false);
      return;
    }
    // Клетка принимает карточку, выбранную нажатием.
    if (!armed) return;
    var slot = event.target.closest('[data-slot]');
    if (!slot) return;
    var card = armed;
    disarm();
    place(slot, card, false);
  });

  function clear(button, force) {
    var slot = button.closest('[data-slot]');
    var body = new FormData();
    if (force) body.append('force', '1');

    fetch(button.getAttribute('data-clear-url'), {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf() },
      body: body,
    }).then(function (response) {
      return response.text().then(function (text) {
        return { ok: response.ok, status: response.status, text: text };
      });
    }).then(function (result) {
      if (result.ok) {
        replaceSlot(slot, result.text);
        say('Убрано');
        return;
      }
      // 409 с needs_force: за занятие уже ставили баллы. Спрашиваем один
      // раз — молча стирать чужую работу нельзя.
      var payload = readPayload(result.text);
      if (payload.needs_force &&
          window.confirm(payload.error + '\n\nУдалить вместе с баллами?')) {
        clear(button, true);
        return;
      }
      say(payload.error || 'Не получилось убрать.', 'error');
    });
  }

  // ── Очистка недели ────────────────────────────────────────────────────────

  var clearWeekButton = document.querySelector('[data-clear-week]');
  if (clearWeekButton && clearWeekButton.dataset.wired !== '1') {
    clearWeekButton.dataset.wired = '1';
    clearWeekButton.addEventListener('click', function () {
      if (!window.confirm('Убрать все занятия этой недели у выбранной группы?')) return;
      clearWeek(false);
    });
  }

  function clearWeek(force) {
    var body = new FormData();
    body.append('group', clearWeekButton.getAttribute('data-group'));
    if (force) body.append('force', '1');

    clearWeekButton.disabled = true;
    say('Очищаю…');
    fetch(clearWeekButton.getAttribute('data-url') + '?week=' + clearWeekButton.getAttribute('data-week'), {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf() },
      body: body,
    }).then(function (response) {
      return response.json().then(function (data) {
        return { ok: response.ok, data: data };
      });
    }).then(function (result) {
      clearWeekButton.disabled = false;
      if (result.ok) {
        if (!result.data.removed) {
          say('На этой неделе занятий и не было.');
          return;
        }
        // Перезагружаем страницу: клеток десятки, подменять каждую
        // по отдельности дольше, чем перерисовать сетку целиком.
        window.location.reload();
        return;
      }
      // За часть занятий уже выставлены баллы — спрашиваем второй раз.
      if (result.data.needs_force &&
          window.confirm(result.data.error + '\n\nОчистить вместе с баллами?')) {
        clearWeek(true);
        return;
      }
      say(result.data.error || 'Не получилось очистить.', 'error');
    }).catch(function () {
      clearWeekButton.disabled = false;
      say('Не удалось очистить — проверьте связь и попробуйте ещё раз.', 'error');
    });
  }

  // ── Повтор недели ─────────────────────────────────────────────────────────

  var copyButton = document.querySelector('[data-copy-week]');
  if (copyButton && copyButton.dataset.wired !== '1') {
    copyButton.dataset.wired = '1';
    copyButton.addEventListener('click', function () {
      var weeks = document.getElementById('copy-weeks');
      var body = new FormData();
      body.append('group', copyButton.getAttribute('data-group'));
      body.append('weeks', weeks ? weeks.value : '1');

      copyButton.disabled = true;
      say('Копирую…');
      fetch(copyButton.getAttribute('data-url') + '?week=' + copyButton.getAttribute('data-week'), {
        method: 'POST',
        headers: { 'X-CSRFToken': csrf() },
        body: body,
      }).then(function (response) { return response.json(); })
        .then(function (data) {
          copyButton.disabled = false;
          var text = 'Создано занятий: ' + data.created;
          if (data.skipped) text += ', пропущено (уже занято или вне модуля): ' + data.skipped;
          say(text);
        })
        .catch(function () {
          copyButton.disabled = false;
          say('Не удалось скопировать.', 'error');
        });
    });
  }
}

  // Кабинет ходит по ссылкам без перезагрузки: скрипт лежит вне
  // подменяемой части и после перехода должен подняться заново.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.body.addEventListener('htmx:afterSettle', init);
})();
