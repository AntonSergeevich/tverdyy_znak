/**
 * Конструктор расписания: карточки педагогов перетаскиваются в сетку.
 *
 * Карточка остаётся на месте после перетаскивания — одного педагога
 * ставят на несколько уроков подряд, и «взял и потерял» здесь было бы
 * издевательством.
 *
 * Всё сохраняется сразу: составление расписания — это десятки мелких
 * действий, и забытая кнопка «сохранить» стоила бы часа работы.
 */
(function () {
  'use strict';

  function init() {
  var grid = document.querySelector('[data-grid]');
  if (!grid || grid.dataset.ready === '1') return;
  grid.dataset.ready = '1';

  var status = document.querySelector('[data-builder-status]');
  var dragged = null;

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

  // ── Перетаскивание ────────────────────────────────────────────────────────

  // Карточки двух видов: педагог отвечает на вопрос «кто», блок дня —
  // «что». Перетаскиваются одинаково, а вот в клетку уходят по-разному.
  document.querySelectorAll('[data-teacher], [data-block]').forEach(function (card) {
    card.addEventListener('dragstart', function (event) {
      dragged = card;
      card.classList.add('deck-card--dragging');
      // Данные кладём и в dataTransfer: без этого Firefox не начинает
      // перетаскивание вообще.
      event.dataTransfer.setData('text/plain', cardId(card));
      event.dataTransfer.effectAllowed = 'copy';
    });
    card.addEventListener('dragend', function () {
      card.classList.remove('deck-card--dragging');
      dragged = null;
    });
  });

  grid.addEventListener('dragover', function (event) {
    var slot = event.target.closest('[data-slot]');
    if (!slot) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    slot.classList.add('slot--over');
  });

  grid.addEventListener('dragleave', function (event) {
    var slot = event.target.closest('[data-slot]');
    if (slot) slot.classList.remove('slot--over');
  });

  grid.addEventListener('drop', function (event) {
    var slot = event.target.closest('[data-slot]');
    if (!slot) return;
    event.preventDefault();
    slot.classList.remove('slot--over');

    // dragged надёжнее, чем dataTransfer: по нему видно, карточка это
    // педагога или блока. Через текст приходит только номер.
    if (!dragged) return;
    place(slot, dragged, false);
  });

  function cardId(card) {
    return card.getAttribute('data-teacher') || card.getAttribute('data-block');
  }

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
      var payload = {};
      try { payload = JSON.parse(result.text); } catch (e) { /* ниже */ }
      if (payload.needs_force && window.confirm(payload.error + '\n\nЗаменить вместе с баллами?')) {
        place(slot, card, true);
        return;
      }
      say(payload.error || 'Не получилось.', 'error');
    }).catch(function () {
      slot.classList.remove('slot--busy');
      say('Не удалось сохранить — проверьте связь и попробуйте ещё раз.', 'error');
    });
  }

  function readError(text) {
    try {
      return JSON.parse(text).error || 'Не получилось.';
    } catch (e) {
      return 'Не получилось.';
    }
  }

  function replaceSlot(slot, html) {
    var holder = document.createElement('div');
    holder.innerHTML = html.trim();
    var fresh = holder.firstElementChild;
    if (fresh) slot.replaceWith(fresh);
  }

  // ── Очистка клетки ────────────────────────────────────────────────────────

  grid.addEventListener('click', function (event) {
    var button = event.target.closest('[data-clear-url]');
    if (!button) return;
    clear(button, false);
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
      var payload = {};
      try { payload = JSON.parse(result.text); } catch (e) { /* ниже */ }
      if (payload.needs_force && window.confirm(payload.error + '\n\nУдалить вместе с баллами?')) {
        clear(button, true);
        return;
      }
      say(payload.error || 'Не получилось убрать.', 'error');
    });
  }

  // ── Очистка недели ────────────────────────────────────────────────────────

  var clearWeekButton = document.querySelector('[data-clear-week]');
  if (clearWeekButton) {
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
      if (result.data.needs_force && window.confirm(result.data.error + '\n\nОчистить вместе с баллами?')) {
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
  if (copyButton) {
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
