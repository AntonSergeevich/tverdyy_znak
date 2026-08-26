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

    function render() {
      var score = parseInt(input.value, 10) || 0;
      var level = levels.find(function (l) { return score <= l.max; }) || levels[levels.length - 1];
      if (valueEl) valueEl.textContent = score;
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
