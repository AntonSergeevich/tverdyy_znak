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
