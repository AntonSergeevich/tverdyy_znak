/**
 * Тема занятия и домашнее задание в журнале.
 *
 * Обычными запросами, а не через htmx: в кабинете на <body> висят
 * hx-select и hx-select-oob для переходов по ссылкам, и они наследуются
 * всем, что внутри. Точечная форма получала ответ, из которого вырезали
 * несуществующие в нём куски, — и обновляемый блок не менялся, а исчезал.
 * Здесь всё под контролем: что отправили, то и вставили.
 *
 * Без скриптов обе формы остаются обычными формами и работают с
 * перезагрузкой страницы.
 */
(function () {
  'use strict';

  var TYPING_PAUSE = 600;   // столько молчит клавиатура, прежде чем сохранять

  function csrf(form) {
    var input = form.querySelector('input[name=csrfmiddlewaretoken]');
    if (input) return input.value;
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
  }

  function say(form, text, kind) {
    var state = form.querySelector('[data-state]');
    if (!state) return;
    state.textContent = text || '';
    state.className = 'lesson-field__state' + (kind ? ' lesson-field__state--' + kind : '');
  }

  function send(form) {
    return fetch(form.getAttribute('action'), {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf(form) },
      body: new FormData(form),
    });
  }

  function init() {
    initTopic();
    initHomework();
    initFill();
  }

  // ── «Как в прошлый раз» ───────────────────────────────────────────────────

  /**
   * Кнопка подставляет в поле то, что было в прошлый раз, и оставляет
   * курсор в конце: педагог правит номера задач, а не набирает всё заново.
   * Подставлять молча нельзя — подставленное молча приходится вычитывать.
   */
  function initFill() {
    document.querySelectorAll('[data-fill]').forEach(function (button) {
      if (button.dataset.ready === '1') return;
      button.dataset.ready = '1';
      button.addEventListener('click', function () {
        var form = button.closest('form');
        var field = form && form.querySelector('[name="' + button.getAttribute('data-fill') + '"]');
        if (!field) return;
        field.value = button.getAttribute('data-fill-value') || '';
        field.focus();
        if (field.setSelectionRange) field.setSelectionRange(field.value.length, field.value.length);
        field.dispatchEvent(new Event('input', { bubbles: true }));
      });
    });
  }

  // ── Тема ──────────────────────────────────────────────────────────────────

  function initTopic() {
    var form = document.querySelector('[data-topic-form]');
    if (!form || form.dataset.ready === '1') return;
    form.dataset.ready = '1';

    var field = form.querySelector('input[name=topic]');
    if (!field) return;
    var timer = null;
    var lastSent = field.value;

    function save() {
      if (field.value === lastSent) return;
      lastSent = field.value;
      say(form, 'сохраняю…');
      send(form).then(function (response) {
        if (!response.ok) { say(form, 'не сохранилось', 'error'); return; }
        // Занятию бывает сопоставлена строка КТП: тогда правка ушла и туда,
        // и сказать об этом надо — иначе непонятно, что план тоже изменился.
        return response.json().then(function (data) {
          say(form, data && data.in_plan ? 'сохранено и в КТП' : 'сохранено');
        }).catch(function () {
          say(form, 'сохранено');
        });
      }).catch(function () {
        say(form, 'нет связи — попробуйте ещё раз', 'error');
      });
    }

    field.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(save, TYPING_PAUSE);
    });
    // Ушли из поля — сохраняем сразу, не дожидаясь паузы.
    field.addEventListener('blur', function () {
      clearTimeout(timer);
      save();
    });
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      clearTimeout(timer);
      save();
    });
  }

  // ── Домашнее задание ──────────────────────────────────────────────────────

  function initHomework() {
    var holder = document.querySelector('[data-homework]');
    if (!holder || holder.dataset.ready === '1') return;
    holder.dataset.ready = '1';

    // Слушаем обёртку, а не форму: после сохранения форма приезжает
    // новая, и слушатель на старой уехал бы вместе с ней.
    holder.addEventListener('submit', function (event) {
      var form = event.target.closest('[data-homework-form]');
      if (!form) return;
      event.preventDefault();

      var button = form.querySelector('button[type=submit]');
      if (button) button.disabled = true;
      say(form, 'сохраняю…');

      send(form).then(function (response) {
        return response.text();
      }).then(function (html) {
        holder.innerHTML = html;
        // Вставленное так htmx не видит: разметку он размечает сам, когда
        // сам же её и получил. Кнопки внутри — «убрать вложение» и прочие —
        // без этого остаются мёртвыми: нажимаешь, и ничего не уходит.
        if (window.htmx) window.htmx.process(holder);
        // Форма приехала новая — «как в прошлый раз» в ней ещё не подключена.
        initFill();
      }).catch(function () {
        if (button) button.disabled = false;
        say(form, 'нет связи — попробуйте ещё раз', 'error');
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  // Кабинет ходит по ссылкам без перезагрузки — поднимаемся заново.
  document.body.addEventListener('htmx:afterSettle', init);
})();
