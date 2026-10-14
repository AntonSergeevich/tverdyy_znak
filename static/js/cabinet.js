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

/**
 * Перетаскивание в кабинете — мышью и пальцем, одним механизмом.
 *
 * Два вида:
 *
 * Перенос между зонами — [data-drag-item] в [data-drop-zone]. Доска заявок:
 * карточку несут в колонку другого этапа. На отпускании карточка сразу
 * встаёт в новую колонку, а на сервер уходит POST на data-drag-url
 * карточки со значениями зоны (data-drop-values, JSON). Ответ — новая
 * разметка карточки. Не приняли — карточка возвращается, причина в плашке.
 *
 * Порядок внутри списка — [data-sortable] с элементами [data-sort-id].
 * Берут за ручку [data-sort-handle] (или за весь элемент, если ручки нет).
 * Пока несут, остальные расступаются; на отпускании на data-sort-url
 * уходит новый порядок (order=id,id,…).
 *
 * Мышью берут с первого движения, пальцем — после короткого удержания,
 * иначе любая прокрутка уносила бы карточку с собой. Кнопки, ссылки и поля
 * внутри карточки работают как обычно: с них перетаскивание не начинается.
 */
(function () {
  'use strict';

  var HOLD_MS = 260;
  var SLIP_PX = 8;
  var EDGE_PX = 70;
  var CONTROLS = 'a, button, input, select, textarea, label, [contenteditable]';

  var press = null;   // между нажатием и взятием
  var drag = null;    // пока в руке

  function csrf() {
    var input = document.querySelector('input[name=csrfmiddlewaretoken]');
    if (input) return input.value;
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
  }

  function toast(text) {
    if (window.tzToast) window.tzToast(text);
  }

  function buzz() {
    if (!navigator.vibrate) return;
    try { navigator.vibrate(12); } catch (e) { /* не всякий браузер умеет */ }
  }

  function grabbable(event) {
    // Ручка переноса — внутри подписи или строки, где всё остальное нажимается.
    var moveHandle = event.target.closest('[data-drag-handle]');
    if (moveHandle && moveHandle.closest('[data-drag-item]')) {
      return { kind: 'move', item: moveHandle.closest('[data-drag-item]') };
    }
    var handle = event.target.closest('[data-sort-handle]');
    if (handle) {
      var sortItem = handle.closest('[data-sort-id]');
      if (sortItem && sortItem.closest('[data-sortable]')) return { kind: 'sort', item: sortItem };
    }
    if (event.target.closest(CONTROLS)) return null;
    var item = event.target.closest('[data-drag-item]');
    if (item) return { kind: 'move', item: item };
    var plain = event.target.closest('[data-sort-id]');
    if (plain && !plain.querySelector('[data-sort-handle]') && plain.closest('[data-sortable]')) {
      return { kind: 'sort', item: plain };
    }
    return null;
  }

  function begin(x, y) {
    var item = press.item;
    var rect = item.getBoundingClientRect();
    var ghost = item.cloneNode(true);
    ghost.removeAttribute('id');
    ghost.classList.add('drag-ghost');
    ghost.style.width = rect.width + 'px';
    // Строка таблицы вне таблицы теряет ширины колонок — переносим их.
    if (item.tagName === 'TR') {
      Array.prototype.forEach.call(item.children, function (cell, index) {
        if (ghost.children[index]) ghost.children[index].style.width = cell.getBoundingClientRect().width + 'px';
      });
    }
    document.body.appendChild(ghost);
    drag = {
      kind: press.kind, item: item, ghost: ghost,
      dx: x - rect.left, dy: y - rect.top,
      home: item.parentNode, next: item.nextSibling,
      scroller: item.closest('[data-drag-scroll]'),
    };
    if (drag.kind === 'sort') {
      var holder = document.createElement(item.tagName === 'TR' ? 'tr' : 'div');
      holder.className = 'drag-placeholder';
      if (item.tagName === 'TR') {
        holder.innerHTML = '<td colspan="99"></td>';
      }
      holder.style.height = rect.height + 'px';
      item.parentNode.insertBefore(holder, item);
      item.classList.add('is-lifted');
      item.style.display = 'none';
      drag.holder = holder;
    } else {
      item.classList.add('is-lifted');
    }
    document.documentElement.classList.add('is-dragging');
    press = null;
    buzz();
    follow(x, y);
  }

  function zoneAt(x, y) {
    var el = document.elementFromPoint(x, y);
    return el ? el.closest('[data-drop-zone]') : null;
  }

  function follow(x, y) {
    drag.ghost.style.transform = 'translate(' + (x - drag.dx) + 'px,' + (y - drag.dy) + 'px)';

    if (drag.kind === 'move') {
      var zone = zoneAt(x, y);
      document.querySelectorAll('.is-drop-target').forEach(function (z) {
        if (z !== zone) z.classList.remove('is-drop-target');
      });
      if (zone) zone.classList.add('is-drop-target');
    } else {
      var list = drag.holder.parentNode;
      var siblings = Array.prototype.filter.call(list.children, function (el) {
        return el !== drag.holder && el !== drag.item && el.hasAttribute('data-sort-id');
      });
      var before = null;
      for (var i = 0; i < siblings.length; i++) {
        var box = siblings[i].getBoundingClientRect();
        if (y < box.top + box.height / 2) { before = siblings[i]; break; }
      }
      if (before) list.insertBefore(drag.holder, before);
      else if (siblings.length) list.insertBefore(drag.holder, siblings[siblings.length - 1].nextSibling);
    }

    // У края — подкручиваем: страницу по вертикали, доску по горизонтали.
    if (y < EDGE_PX) window.scrollBy(0, -16);
    else if (y > window.innerHeight - EDGE_PX) window.scrollBy(0, 16);
    if (drag.scroller) {
      var area = drag.scroller.getBoundingClientRect();
      if (x < area.left + EDGE_PX) drag.scroller.scrollLeft -= 18;
      else if (x > area.right - EDGE_PX) drag.scroller.scrollLeft += 18;
    }
  }

  function cleanup(state) {
    state.ghost.remove();
    state.item.classList.remove('is-lifted');
    state.item.style.display = '';
    document.documentElement.classList.remove('is-dragging');
    document.querySelectorAll('.is-drop-target').forEach(function (z) { z.classList.remove('is-drop-target'); });
  }

  function putBack(state) {
    state.home.insertBefore(state.item, state.next);
  }

  function post(url, values) {
    var body = new FormData();
    Object.keys(values).forEach(function (key) { body.append(key, values[key]); });
    return fetch(url, {
      method: 'POST', body: body, credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), 'HX-Request': 'true' },
    }).then(function (response) {
      return response.text().then(function (text) { return { ok: response.ok, status: response.status, text: text }; });
    });
  }

  function readError(text) {
    try { return JSON.parse(text).error || ''; } catch (e) { /* не JSON */ }
    if (text && text.length < 300 && text.indexOf('<') !== 0) return text;
    return '';
  }

  function drop(x, y) {
    var state = drag;
    drag = null;
    cleanup(state);

    swallowClick();

    if (state.kind === 'move') {
      var zone = zoneAt(x, y);
      if (!zone || zone === state.home.closest('[data-drop-zone]')) return;
      var values = {};
      try {
        values = Object.assign(
          JSON.parse(zone.getAttribute('data-drop-values') || '{}'),
          JSON.parse(state.item.getAttribute('data-drag-values') || '{}')
        );
      } catch (e) { values = {}; }

      // Зона, после которой проще перечитать страницу, чем собирать её
      // по кускам (состав группы): отправляем и обновляем <main>.
      if (zone.hasAttribute('data-drop-refresh')) {
        state.item.classList.add('is-saving');
        post(state.item.getAttribute('data-drag-url'), values).then(function (result) {
          if (!result.ok) {
            state.item.classList.remove('is-saving');
            toast(readError(result.text) || 'Не получилось.');
            return;
          }
          if (window.htmx) {
            window.htmx.ajax('GET', location.pathname + location.search,
              { target: '#main', select: '#main', swap: 'outerHTML' });
          }
        }).catch(function () {
          state.item.classList.remove('is-saving');
          toast('Нет связи с сервером.');
        });
        return;
      }

      var target = zone.querySelector('[data-drop-list]') || zone;
      target.insertBefore(state.item, target.firstChild);
      state.item.classList.add('is-saving');
      post(state.item.getAttribute('data-drag-url'), values).then(function (result) {
        state.item.classList.remove('is-saving');
        if (result.ok || result.status === 422) {
          var holder = document.createElement('div');
          holder.innerHTML = result.text.trim();
          var fresh = holder.firstElementChild;
          if (fresh && fresh.hasAttribute('data-drag-item')) {
            state.item.replaceWith(fresh);
            if (window.htmx) window.htmx.process(fresh);
            if (result.status === 422) {
              putBack({ item: fresh, home: state.home, next: state.next });
              var field = fresh.querySelector('input, select');
              if (field) field.focus();
            }
          }
          document.dispatchEvent(new CustomEvent('tz:dropped', { detail: { zone: zone } }));
          return;
        }
        putBack(state);
        toast(readError(result.text) || 'Не получилось перенести.');
      }).catch(function () {
        state.item.classList.remove('is-saving');
        putBack(state);
        toast('Нет связи с сервером — карточка осталась на месте.');
      });
      return;
    }

    // Порядок.
    var list = state.holder.parentNode;
    list.insertBefore(state.item, state.holder);
    state.holder.remove();
    var sortable = state.item.closest('[data-sortable]');
    var order = Array.prototype.map.call(
      sortable.querySelectorAll('[data-sort-id]'), function (el) { return el.getAttribute('data-sort-id'); }
    );
    if (state.item.nextSibling === state.next && state.item.parentNode === state.home) return;
    post(sortable.getAttribute('data-sort-url'), { order: order.join(',') }).then(function (result) {
      if (result.ok) return;
      putBack(state);
      toast(readError(result.text) || 'Порядок не сохранился.');
    }).catch(function () {
      putBack(state);
      toast('Нет связи с сервером — порядок не сохранился.');
    });
  }

  // Отпустили над подписью или ссылкой — щелчком это не считается.
  var swallowing = false;
  function swallowClick() {
    swallowing = true;
    setTimeout(function () { swallowing = false; }, 350);
  }
  document.addEventListener('click', function (event) {
    if (!swallowing) return;
    swallowing = false;
    event.preventDefault();
    event.stopPropagation();
  }, true);

  function abort() {
    if (!drag) return;
    var state = drag;
    drag = null;
    cleanup(state);
    if (state.holder) state.holder.remove();
    putBack(state);
  }

  document.addEventListener('pointerdown', function (event) {
    if (event.button || drag) return;
    var found = grabbable(event);
    if (!found) return;
    press = { item: found.item, kind: found.kind, x: event.clientX, y: event.clientY, timer: null };
    // За ручку берут сразу, и пальцем тоже: ручка ничем другим не занята,
    // прокручивать за неё страницу никто не станет.
    press.immediate = !!event.target.closest('[data-sort-handle], [data-drag-handle]');
    if (event.pointerType === 'mouse' || press.immediate) return;
    press.timer = setTimeout(function () {
      if (press) begin(press.x, press.y);
    }, HOLD_MS);
  });

  document.addEventListener('pointermove', function (event) {
    if (drag) { follow(event.clientX, event.clientY); return; }
    if (!press) return;
    var slipped = Math.abs(event.clientX - press.x) + Math.abs(event.clientY - press.y);
    if (slipped < SLIP_PX) return;
    if (event.pointerType === 'mouse' || press.immediate) {
      event.preventDefault();
      begin(event.clientX, event.clientY);
    } else {
      // Палец поехал раньше, чем карточка поднялась, — это прокрутка.
      clearTimeout(press.timer);
      press = null;
    }
  });

  document.addEventListener('pointerup', function (event) {
    if (press) { clearTimeout(press.timer); press = null; }
    if (drag) drop(event.clientX, event.clientY);
  });
  document.addEventListener('pointercancel', function () {
    if (press) { clearTimeout(press.timer); press = null; }
    abort();
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') abort();
  });

  // Пока карточка в руке, палец не листает страницу.
  document.addEventListener('touchmove', function (event) {
    if (drag) event.preventDefault();
  }, { passive: false });

  // Долгое нажатие на телефоне открыло бы меню «скопировать» поверх.
  document.addEventListener('contextmenu', function (event) {
    if (drag || (press && event.target.closest('[data-drag-item], [data-sort-id]'))) event.preventDefault();
  });
})();

/**
 * Доска заявок: карточка — в колонке своего этапа, счётчики — верные.
 *
 * Этап меняют и переносом, и списком в карточке. После списка карточка
 * приходит с сервера на старое место — переставляем её в колонку этапа,
 * который у неё теперь записан. Убранную заявку можно вернуть из плашки.
 */
(function () {
  'use strict';

  function recount(board) {
    board.querySelectorAll('[data-lead-column]').forEach(function (column) {
      var count = column.querySelector('[data-count]');
      if (count) count.textContent = column.querySelectorAll('[data-drag-item]').length;
    });
  }

  function settle() {
    var board = document.querySelector('.lead-board');
    if (!board) return;
    board.querySelectorAll('[data-lead-status]').forEach(function (card) {
      if (card.classList.contains('lead-card--error')) return;
      var column = card.closest('[data-lead-column]');
      var wanted = card.getAttribute('data-lead-status');
      if (column && column.getAttribute('data-lead-column') !== wanted) {
        var target = board.querySelector('[data-lead-column="' + wanted + '"] [data-drop-list]');
        if (target) target.insertBefore(card, target.firstChild);
      }
    });
    recount(board);
  }

  document.body.addEventListener('htmx:afterSettle', settle);
  document.addEventListener('tz:dropped', settle);

  // Убрать заявку — сразу, с «Отменить».
  document.body.addEventListener('htmx:afterRequest', function (event) {
    var button = event.detail.elt;
    if (!button || !button.hasAttribute || !button.hasAttribute('data-undo-url')) return;
    if (!event.detail.successful) return;
    settle();
    if (!window.tzToast) return;
    window.tzToast(button.getAttribute('data-undo-text') || 'Убрано.', {
      label: 'Отменить',
      run: function () {
        var body = new FormData();
        var token = document.querySelector('input[name=csrfmiddlewaretoken]');
        if (token) body.append('csrfmiddlewaretoken', token.value);
        fetch(button.getAttribute('data-undo-url'), { method: 'POST', body: body, credentials: 'same-origin' })
          .then(function () {
            if (window.htmx) {
              window.htmx.ajax('GET', location.pathname + location.search, { target: '#main', select: '#main', swap: 'outerHTML' });
            }
          });
      },
    });
  });
})();
