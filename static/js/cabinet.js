/**
 * Вкладки кабинета.
 *
 * Разметка: [data-tabs] с кнопками [data-tab="имя"] и блоками
 * [data-tab-panel="имя"]. Без скрипта панель вкладок спрятана, а все
 * блоки стоят друг под другом — страница работает как раньше.
 *
 * Открытая вкладка — в адресе (#domashnee): обновление страницы и кнопка
 * «назад» возвращают туда же. Сервер, отправляя обратно на занятие,
 * просит вкладку параметром ?vkladka=… — якорь при переадресации теряется.
 */
(function () {
  'use strict';

  function choose(box, name, remember) {
    var tabs = box.querySelectorAll('[data-tab]');
    var known = Array.prototype.some.call(tabs, function (tab) {
      return tab.getAttribute('data-tab') === name;
    });
    if (!known) name = tabs.length ? tabs[0].getAttribute('data-tab') : '';

    tabs.forEach(function (tab) {
      var on = tab.getAttribute('data-tab') === name;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
    });
    box.querySelectorAll('[data-tab-panel]').forEach(function (panel) {
      panel.classList.toggle('is-active', panel.getAttribute('data-tab-panel') === name);
    });
    box.setAttribute('data-current-tab', name);

    if (remember && window.history && history.replaceState) {
      var first = tabs.length && tabs[0].getAttribute('data-tab') === name;
      var url = location.pathname + location.search.replace(/([?&])vkladka=[^&]*&?/, '$1').replace(/[?&]$/, '');
      history.replaceState(history.state, '', first ? url : url + '#' + name);
    }
  }

  function wanted() {
    var fromHash = (location.hash || '').slice(1);
    if (fromHash) return fromHash;
    var match = /[?&]vkladka=([^&]+)/.exec(location.search);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function init() {
    document.querySelectorAll('[data-tabs]').forEach(function (box) {
      if (box.dataset.ready === '1') return;
      box.dataset.ready = '1';
      var bar = box.querySelector('.tabs__bar');
      if (bar) bar.hidden = false;
      box.classList.add('is-ready');
      choose(box, wanted(), false);
    });
  }

  document.addEventListener('click', function (event) {
    var tab = event.target.closest ? event.target.closest('[data-tab]') : null;
    if (!tab) return;
    var box = tab.closest('[data-tabs]');
    if (box) choose(box, tab.getAttribute('data-tab'), true);
  });

  // Стрелки влево-вправо по вкладкам — как у любых вкладок в системе.
  document.addEventListener('keydown', function (event) {
    var tab = event.target.closest ? event.target.closest('[data-tab]') : null;
    if (!tab || (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft')) return;
    var box = tab.closest('[data-tabs]');
    var tabs = Array.prototype.slice.call(box.querySelectorAll('[data-tab]'));
    var next = tabs[(tabs.indexOf(tab) + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    choose(box, next.getAttribute('data-tab'), true);
    next.focus();
  });

  window.tzTabs = { choose: choose };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.body.addEventListener('htmx:afterSettle', init);
})();

/**
 * Таблицы-карточки на телефоне.
 *
 * На узком экране строка таблицы становится карточкой (CSS, .data--cards),
 * и у каждой ячейки нужна подпись — что это за число. Подписи берутся из
 * шапки той же таблицы, чтобы не дублировать их в каждом шаблоне. Строки,
 * которые htmx подменяет по одной, получают подписи после подмены.
 */
(function () {
  'use strict';

  function label(table) {
    var heads = Array.prototype.map.call(
      table.querySelectorAll('thead th'), function (th) { return th.textContent.trim(); }
    );
    if (!heads.length) return;
    table.querySelectorAll('tbody tr, tfoot tr').forEach(function (row) {
      var column = 0;
      Array.prototype.forEach.call(row.children, function (cell) {
        if (!cell.hasAttribute('data-label') && heads[column]) {
          cell.setAttribute('data-label', heads[column]);
        }
        column += cell.colSpan || 1;
      });
    });
  }

  function init() {
    document.querySelectorAll('table.data--cards').forEach(label);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.body.addEventListener('htmx:afterSettle', init);
})();

/**
 * Плашка «Отменить».
 *
 * Серверная (после удаления с переадресацией) приезжает в <main> готовой —
 * её остаётся только спрятать через несколько секунд. Скрипты страницы
 * (расписание) показывают свою через window.tzToast(текст, {label, run}).
 * Пока на плашку навели или в ней фокус, она не гаснет: человек как раз
 * собирается нажать «Отменить».
 */
(function () {
  'use strict';

  var LIFETIME = 8000;

  function arm(toast) {
    if (toast.dataset.armed === '1') return;
    toast.dataset.armed = '1';
    requestAnimationFrame(function () { toast.classList.add('is-visible'); });
    var timer = null;
    function later() {
      clearTimeout(timer);
      timer = setTimeout(function () {
        if (toast.matches(':hover') || toast.contains(document.activeElement)) return later();
        toast.classList.remove('is-visible');
        setTimeout(function () { toast.remove(); }, 250);
      }, LIFETIME);
    }
    later();
    toast.addEventListener('submit', function () { toast.classList.add('is-busy'); });
  }

  window.tzToast = function (text, action) {
    document.querySelectorAll('.toast[data-js-toast]').forEach(function (old) { old.remove(); });
    var toast = document.createElement('div');
    toast.className = 'toast toast--undo';
    toast.setAttribute('role', 'status');
    toast.setAttribute('data-js-toast', '');
    var span = document.createElement('span');
    span.className = 'toast__text';
    span.textContent = text;
    toast.appendChild(span);
    if (action) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'toast__action';
      button.textContent = action.label || 'Отменить';
      button.addEventListener('click', function () {
        toast.remove();
        action.run();
      });
      toast.appendChild(button);
    }
    document.body.appendChild(toast);
    arm(toast);
    return toast;
  };

  function init() {
    document.querySelectorAll('[data-undo-toast]').forEach(arm);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.body.addEventListener('htmx:afterSettle', init);
})();

/**
 * Свайпы — только пальцем, и только как ускорение видимой кнопки.
 *
 * Смахнуть строку ([data-swipe-row]): строка едет за пальцем, из-под неё
 * проступает подсказка, что произойдёт. Дотянул до порога — нажимается
 * та же кнопка, что видна в строке (data-swipe-right / data-swipe-left —
 * её селектор внутри строки). Не дотянул — строка возвращается на место.
 *
 * Пролистнуть экран ([data-swipe-nav]): быстрый горизонтальный жест
 * нажимает ссылку «дальше» или «назад» (data-swipe-next / data-swipe-prev,
 * селекторы по документу; «tab:next» и «tab:prev» — соседние вкладки).
 *
 * Мышью ничего не смахивается: на компьютере есть кнопки, а случайный
 * «свайп» при выделении текста стоил бы зачтённого задания.
 */
(function () {
  'use strict';

  var START_PX = 12;     // дальше — уже жест, а не дрожание пальца
  var EDGE_PX = 24;      // у края экрана — системный «назад», не наш
  var NAV_PX = 70;       // пролистнуть экран
  var IGNORE = 'input, textarea, select, [contenteditable], [data-dial-open], .grade-dial, dialog, .table-wrap, [data-grid]';

  var gesture = null;
  var swallowClick = false;

  function rowButton(row, dir) {
    var selector = row.getAttribute('data-swipe-' + dir);
    return selector ? row.querySelector(selector) : null;
  }

  function rowThreshold(row) {
    return Math.min(130, row.offsetWidth * 0.35);
  }

  function hint(row, dir) {
    var label = row.getAttribute('data-swipe-' + dir + '-label') || '';
    row.setAttribute('data-swipe-dir', dir);
    row.setAttribute('data-swipe-hint', label);
  }

  function resetRow(row, animate) {
    row.classList.toggle('is-settling', !!animate);
    row.style.transform = '';
    row.classList.remove('is-swiping', 'is-armed');
    setTimeout(function () {
      row.classList.remove('is-settling');
      row.removeAttribute('data-swipe-dir');
    }, animate ? 200 : 0);
  }

  function navTarget(spec) {
    if (!spec) return null;
    if (spec.indexOf('tab:') === 0) return spec;
    return document.querySelector(spec);
  }

  function go(area, dir) {
    var spec = area.getAttribute('data-swipe-' + dir);
    var target = navTarget(spec);
    if (!target) return false;
    if (typeof target === 'string') {
      var box = area.closest('[data-tabs]') || area;
      var tabs = Array.prototype.slice.call(box.querySelectorAll('[data-tab]'));
      var current = box.getAttribute('data-current-tab');
      var index = tabs.findIndex(function (t) { return t.getAttribute('data-tab') === current; });
      var next = tabs[index + (target === 'tab:next' ? 1 : -1)];
      if (!next || !window.tzTabs) return false;
      window.tzTabs.choose(box, next.getAttribute('data-tab'), true);
      return true;
    }
    target.click();
    return true;
  }

  document.addEventListener('pointerdown', function (event) {
    if (event.pointerType === 'mouse' || !event.isPrimary) return;
    if (event.clientX < EDGE_PX || event.clientX > window.innerWidth - EDGE_PX) return;
    var row = event.target.closest('[data-swipe-row]');
    var area = row ? null : event.target.closest('[data-swipe-nav]');
    if (!row && !area) return;
    if (event.target.closest(IGNORE)) return;
    gesture = {
      row: row, area: area, x: event.clientX, y: event.clientY,
      at: Date.now(), engaged: false, dx: 0,
    };
  });

  document.addEventListener('pointermove', function (event) {
    if (!gesture) return;
    var dx = event.clientX - gesture.x;
    var dy = event.clientY - gesture.y;
    if (!gesture.engaged) {
      if (Math.abs(dy) > START_PX && Math.abs(dy) > Math.abs(dx)) { gesture = null; return; }
      if (Math.abs(dx) < START_PX || Math.abs(dx) < Math.abs(dy) * 1.5) return;
      gesture.engaged = true;
    }
    gesture.dx = dx;
    if (gesture.row) {
      var dir = dx > 0 ? 'right' : 'left';
      if (!rowButton(gesture.row, dir)) {
        dx = dx / 6;   // в эту сторону делать нечего — строка лишь чуть поддаётся
      }
      hint(gesture.row, dir);
      gesture.row.classList.add('is-swiping');
      gesture.row.classList.toggle('is-armed', Math.abs(dx) >= rowThreshold(gesture.row));
      gesture.row.style.transform = 'translateX(' + dx + 'px)';
    }
  }, { passive: true });

  function finish(event) {
    if (!gesture) return;
    var g = gesture;
    gesture = null;
    if (!g.engaged) return;

    if (g.row) {
      var dir = g.dx > 0 ? 'right' : 'left';
      var button = rowButton(g.row, dir);
      var done = button && event.type === 'pointerup' && Math.abs(g.dx) >= rowThreshold(g.row);
      resetRow(g.row, true);
      if (done) button.click();
    } else if (event.type === 'pointerup' && Math.abs(g.dx) >= NAV_PX && Date.now() - g.at < 800) {
      go(g.area, g.dx < 0 ? 'next' : 'prev');
    }
    // Браузер следом пришлёт щелчок по тому, над чем отпустили палец, —
    // жест нажатием не считается. Своё нажатие выше уже сделано.
    swallowClick = true;
    setTimeout(function () { swallowClick = false; }, 350);
  }
  document.addEventListener('pointerup', finish);
  document.addEventListener('pointercancel', finish);

  // Жест закончился над кнопкой или ссылкой — нажатием это не считается.
  document.addEventListener('click', function (event) {
    if (!swallowClick) return;
    swallowClick = false;
    event.preventDefault();
    event.stopPropagation();
  }, true);
})();
