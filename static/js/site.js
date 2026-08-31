/* Публичный сайт: тема, 100-балльная шкала, сегменты, маска телефона,
   защита от двойной отправки, cookie-баннер. Внешних библиотек нет. */
(function () {
  'use strict';

  // ─── Тема ────────────────────────────────────────────────────────────────
  var root = document.documentElement;
  var toggle = document.querySelector('[data-theme-toggle]');
  function applyTheme(theme) {
    root.setAttribute('data-theme', theme);
    if (toggle) {
      var dark = theme === 'dark';
      toggle.textContent = dark ? '☀' : '☾';
      var label = dark ? 'Светлая тема' : 'Тёмная тема';
      toggle.setAttribute('aria-label', label);
      toggle.setAttribute('title', label);
    }
  }
  if (toggle) {
    toggle.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('tz-theme', next); } catch (e) { /* приватный режим */ }
      applyTheme(next);
    });
    applyTheme(root.getAttribute('data-theme') || 'light');
  }

  // ─── Бургер-меню ─────────────────────────────────────────────────────────
  document.querySelectorAll('[data-nav-toggle]').forEach(function (button) {
    var header = button.closest('.site-header');
    if (!header) return;
    var nav = header.querySelector('.site-nav, .cabinet-nav');

    function setOpen(open) {
      header.classList.toggle('is-open', open);
      button.setAttribute('aria-expanded', String(open));
      button.setAttribute('aria-label', open ? 'Закрыть меню' : 'Меню');
    }

    button.addEventListener('click', function () {
      setOpen(!header.classList.contains('is-open'));
    });

    // Переход по пункту закрывает меню: якорная ссылка не перезагружает
    // страницу, и раскрытое меню осталось бы висеть поверх содержимого.
    if (nav) {
      nav.addEventListener('click', function (event) {
        if (event.target.closest('a')) setOpen(false);
      });
    }

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') setOpen(false);
    });
  });

  // ─── 100-балльная шкала ──────────────────────────────────────────────────
  document.querySelectorAll('[data-scale]').forEach(function (panel) {
    var input = panel.querySelector('input[type=range]');
    if (!input) return;
    var levels = JSON.parse(panel.getAttribute('data-scale') || '[]');
    var ticks = panel.querySelectorAll('.scale-ticks span');
    var valueEl = panel.querySelector('[data-scale-value]');
    var nameEl = panel.querySelector('[data-scale-level]');
    var hintEl = panel.querySelector('[data-scale-hint]');
    var rowLevel = panel.querySelector('[data-scale-row-level]');
    var rowFocus = panel.querySelector('[data-scale-row-focus]');
    var rowRetake = panel.querySelector('[data-scale-row-retake]');
    var wink = panel.querySelector('[data-scale-wink]');
    var scoreBox = panel.querySelector('.scale-panel__score');

    function render() {
      var score = parseInt(input.value, 10) || 0;
      var level = levels.find(function (l) { return score <= l.max; }) || levels[levels.length - 1];
      if (valueEl) valueEl.textContent = score;
      // Сотня — единственная точка шкалы, где уместно порадоваться вместе
      // с подростком: число уступает место подмигивающему смайлу.
      if (scoreBox) scoreBox.classList.toggle('is-full', score === 100);
      if (wink && score === 100) {
        wink.classList.remove('is-winking');
        // Перезапуск анимации: без чтения offsetWidth браузер склеит
        // снятие и установку класса в один кадр и ничего не проиграет.
        void wink.offsetWidth;
        wink.classList.add('is-winking');
      }
      if (nameEl) nameEl.textContent = level.name;
      if (hintEl) hintEl.textContent = level.hint;
      if (rowLevel) rowLevel.textContent = level.name;
      if (rowFocus) rowFocus.textContent = level.focus;
      if (rowRetake) rowRetake.textContent = level.retake;
      input.setAttribute('aria-valuetext', score + ' баллов, ' + level.name);
      ticks.forEach(function (tick, index) {
        tick.classList.toggle('is-on', (index + 1) * (100 / ticks.length) <= score);
      });
    }
    input.addEventListener('input', render);
    render();
  });

  // ─── Сегменты «для кого» ─────────────────────────────────────────────────
  var segmentButtons = document.querySelectorAll('[data-segment]');
  var ctaTargets = document.querySelectorAll('[data-segment-cta]');
  var segmentInput = document.querySelector('input[name="segment"][type="hidden"]');
  segmentButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      segmentButtons.forEach(function (other) { other.setAttribute('aria-pressed', String(other === button)); });
      var cta = button.getAttribute('data-segment-label');
      ctaTargets.forEach(function (target) { if (cta) target.textContent = cta; });
      var value = button.getAttribute('data-segment');
      if (segmentInput) segmentInput.value = value;
      document.querySelectorAll('input[name="segment"][type="radio"]').forEach(function (radio) {
        radio.checked = radio.value === value;
      });
    });
  });

  // ─── Маска телефона ──────────────────────────────────────────────────────
  document.querySelectorAll('[data-phone-mask]').forEach(function (input) {
    function format(value) {
      var digits = value.replace(/\D/g, '');
      if (digits[0] === '8') digits = '7' + digits.slice(1);
      if (digits[0] !== '7') digits = '7' + digits;
      digits = digits.slice(0, 11);
      var out = '+7';
      if (digits.length > 1) out += ' (' + digits.slice(1, 4);
      if (digits.length >= 4) out += ') ' + digits.slice(4, 7);
      if (digits.length >= 8) out += '-' + digits.slice(7, 9);
      if (digits.length >= 10) out += '-' + digits.slice(9, 11);
      return out;
    }
    input.addEventListener('focus', function () { if (!input.value) input.value = '+7 ('; });
    input.addEventListener('input', function () { input.value = format(input.value); });
  });

  // ─── Согласие включает кнопку, двойная отправка блокируется ──────────────
  document.querySelectorAll('form[data-lead-form]').forEach(function (form) {
    var consent = form.querySelector('input[name="consent"]');
    var submit = form.querySelector('[type="submit"]');
    function sync() { if (submit && consent) submit.disabled = !consent.checked; }
    if (consent) consent.addEventListener('change', sync);
    sync();
    form.addEventListener('submit', function () {
      if (submit) {
        submit.dataset.idleLabel = submit.dataset.idleLabel || submit.textContent;
        submit.disabled = true;
        submit.textContent = 'Отправляем…';
      }
    });
    document.body.addEventListener('htmx:afterRequest', function () {
      if (submit && submit.dataset.idleLabel) {
        submit.textContent = submit.dataset.idleLabel;
        submit.disabled = consent ? !consent.checked : false;
      }
    });
  });

  // ─── Cookie-баннер ───────────────────────────────────────────────────────
  var bar = document.querySelector('[data-cookie-bar]');
  if (bar) {
    var stored = null;
    try { stored = JSON.parse(localStorage.getItem('tz-cookie-consent') || 'null'); } catch (e) { stored = null; }
    if (!stored) {
      bar.hidden = false;
    } else if (stored.value === 'all') {
      loadAnalytics();
    }
    bar.querySelectorAll('[data-cookie-choice]').forEach(function (button) {
      button.addEventListener('click', function () {
        var value = button.getAttribute('data-cookie-choice');
        try {
          localStorage.setItem('tz-cookie-consent', JSON.stringify({
            value: value, at: new Date().toISOString(), version: bar.getAttribute('data-version') || ''
          }));
        } catch (e) { /* ничего страшного: спросим в следующий раз */ }
        bar.hidden = true;
        if (value === 'all') loadAnalytics();
      });
    });
  }

  // Педагог по клику — в диалоге, без перехода на другую страницу.
  //
  // Мини-карточка остаётся обычной ссылкой на страницу состава: без
  // скрипта человек просто попадёт туда и прочитает то же самое.
  // Перехватываем только обычный левый клик — Ctrl+click и «открыть
  // в новой вкладке» должны работать как у любой ссылки.
  var modal = document.querySelector('[data-teacher-modal]');
  if (modal && typeof modal.showModal === 'function') {
    var body = modal.querySelector('[data-teacher-modal-body]');

    document.addEventListener('click', function (event) {
      var chip = event.target.closest ? event.target.closest('[data-teacher]') : null;
      if (!chip) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;

      var details = document.querySelector(
        '[data-teacher-details="' + chip.getAttribute('data-teacher') + '"]'
      );
      if (!details) return;

      event.preventDefault();
      body.innerHTML = '';
      body.appendChild(details.content.cloneNode(true));
      modal.showModal();
    });

    modal.addEventListener('click', function (event) {
      // Клик по подложке — за пределами самого диалога — закрывает его.
      if (event.target === modal) modal.close();
      if (event.target.closest('[data-teacher-close]')) modal.close();
    });

    modal.addEventListener('close', function () { body.innerHTML = ''; });
  }

  // Кнопка «скопировать»: пароль показывается один раз, и переписывать
  // его руками — гарантированная опечатка. Делегируем на документ,
  // чтобы работало и для фрагментов, пришедших через HTMX.
  document.addEventListener('click', function (event) {
    var button = event.target.closest ? event.target.closest('[data-copy]') : null;
    if (!button) return;

    var text = button.getAttribute('data-copy-text') || '';
    var done = button.parentNode.querySelector('[data-copy-done]');

    function reportCopied() {
      if (!done) return;
      done.hidden = false;
      setTimeout(function () { done.hidden = true; }, 2500);
    }

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(reportCopied);
      return;
    }
    // Резервный путь для http: clipboard API там недоступен, а доступы
    // выдавать надо и на тестовом стенде без сертификата.
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); reportCopied(); } catch (e) { /* покажем как есть */ }
    document.body.removeChild(area);
  });

  // Аналитика подключается только после согласия «принять все».
  // В кабинетах её нет вообще: там персональные данные детей.
  function loadAnalytics() {
    var holder = document.querySelector('[data-metrika-id]');
    if (!holder) return;
    var id = holder.getAttribute('data-metrika-id');
    if (!id || window.__tzMetrikaLoaded) return;
    window.__tzMetrikaLoaded = true;
    (function (m, e, t, r, i, k, a) {
      m[i] = m[i] || function () { (m[i].a = m[i].a || []).push(arguments); };
      m[i].l = 1 * new Date();
      k = e.createElement(t); a = e.getElementsByTagName(t)[0];
      k.async = 1; k.src = r; a.parentNode.insertBefore(k, a);
    })(window, document, 'script', 'https://mc.yandex.ru/metrika/tag.js', 'ym');
    window.ym(id, 'init', { clickmap: true, trackLinks: true, accurateTrackBounce: true });
  }
})();

/**
 * Форма нового сотрудника: блок педагога раскрывается вместе с ролью.
 *
 * Без скрипта форма работает так же — блок просто остаётся свёрнутым,
 * и его открывают рукой. Это подсказка, а не условие.
 */
(function () {
  'use strict';

  function init() {
    var block = document.querySelector('[data-teacher-block]');
    var role = document.querySelector('select[name="role"]');
    if (!block || !role || block.dataset.ready === '1') return;
    block.dataset.ready = '1';

    role.addEventListener('change', function () {
      block.open = role.value === 'teacher';
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.body.addEventListener('htmx:afterSettle', init);
})();

/**
 * Отказ сервера не должен выглядеть как «кнопка не работает».
 *
 * htmx по умолчанию подменяет содержимое только на успешный ответ. На 403
 * и 500 он не делает ничего — вообще ничего, даже в консоли пусто. Для
 * человека это неотличимо от сломанной кнопки, и именно так и читалось:
 * «нажимаю — ничего не происходит». Хуже всего это било в режиме просмотра
 * чужого кабинета, где любое изменение запрещено по замыслу.
 *
 * Теперь любой неудачный запрос говорит, что случилось. Сообщение сервера
 * показываем как есть, если он прислал короткий текст, — оно точнее любого
 * общего «произошла ошибка».
 */
(function () {
  'use strict';

  var BOX_ID = 'request-error';
  var HIDE_AFTER = 7000;
  var timer = null;

  function box() {
    var found = document.getElementById(BOX_ID);
    if (found) return found;
    found = document.createElement('div');
    found.id = BOX_ID;
    found.className = 'request-error';
    found.setAttribute('role', 'alert');
    document.body.appendChild(found);
    return found;
  }

  function show(text) {
    var element = box();
    element.textContent = text;
    element.classList.add('is-visible');
    clearTimeout(timer);
    timer = setTimeout(function () {
      element.classList.remove('is-visible');
    }, HIDE_AFTER);
  }

  function fromResponse(xhr) {
    var text = (xhr && xhr.responseText) || '';
    // Ответ страницей целиком читать человеку незачем — покажем своё.
    if (!text || text.length > 300 || text.indexOf('<') === 0) return '';
    return text.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  }

  document.body.addEventListener('htmx:responseError', function (event) {
    var xhr = event.detail.xhr || {};
    var said = fromResponse(xhr);
    if (said) return show(said);
    if (xhr.status === 403) {
      return show('Нет прав на это действие. Если вы смотрите чужой кабинет, вернитесь к себе.');
    }
    if (xhr.status === 404) return show('Страница или запись не найдена — обновите экран.');
    show('Сервер не принял запрос (' + (xhr.status || '?') + '). Попробуйте ещё раз.');
  });

  document.body.addEventListener('htmx:sendError', function () {
    show('Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.');
  });

  document.body.addEventListener('htmx:timeout', function () {
    show('Сервер не ответил вовремя. Попробуйте ещё раз.');
  });
})();
