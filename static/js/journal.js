/* Журнал занятия: автосохранение баллов, устойчивое к обрыву сети.

   Введённое сохраняется в localStorage до подтверждения от сервера
   и повторно отправляется, когда связь вернулась (ТЗ 9.3).

   Скрипт подключён ко всему кабинету, а не к одной странице: при переходе
   без перезагрузки меняется только <main>, и тег со страницы не приедет.
   Поэтому он не делает ничего сразу, а поднимается на каждой странице
   заново — и молчит там, где журнала нет. */
(function () {
  'use strict';

  function setUp(form) {
    if (form.dataset.ready === '1') return;
    form.dataset.ready = '1';

    var storageKey = 'tz-journal-' + form.getAttribute('data-lesson');
    var queue = load();

    function load() {
      try { return JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch (e) { return {}; }
    }
    function persist() {
      try { localStorage.setItem(storageKey, JSON.stringify(queue)); } catch (e) { /* квота */ }
    }
    function setState(row, className, text) {
      var state = row.querySelector('[data-state]');
      if (!state) return;
      state.className = 'journal-row__state ' + className;
      state.textContent = text;
    }
    function fieldOf(row, name) {
      return row.querySelector('[name="' + name + '"]');
    }

    // Восстанавливаем несохранённое после перезагрузки страницы.
    Object.keys(queue).forEach(function (studentId) {
      var row = form.querySelector('[data-student="' + studentId + '"]');
      if (!row) return;
      var pending = queue[studentId];
      var points = fieldOf(row, 'points');
      var comment = fieldOf(row, 'comment');
      if (points && pending.points !== undefined) points.value = pending.points;
      if (comment && pending.comment !== undefined) comment.value = pending.comment;
      setState(row, 'state--offline', 'не сохранено');
    });

    form.addEventListener('htmx:configRequest', function (event) {
      var row = event.detail.elt.closest('[data-student]');
      if (!row) return;
      var studentId = row.getAttribute('data-student');
      queue[studentId] = {
        points: (fieldOf(row, 'points') || {}).value,
        comment: (fieldOf(row, 'comment') || {}).value
      };
      persist();
      setState(row, 'state--pending', 'сохраняем…');
    });

    form.addEventListener('htmx:afterRequest', function (event) {
      var row = event.detail.elt.closest('[data-student]');
      if (!row) return;
      var studentId = row.getAttribute('data-student');
      if (event.detail.successful && event.detail.xhr && event.detail.xhr.status < 400) {
        delete queue[studentId];
        persist();
      } else if (!event.detail.xhr || event.detail.xhr.status === 0) {
        setState(row, 'state--offline', 'нет сети — отправим позже');
      }
    });

    function flush() {
      Object.keys(queue).forEach(function (studentId) {
        var row = form.querySelector('[data-student="' + studentId + '"]');
        if (!row) return;
        var trigger = row.querySelector('[data-resend]') || fieldOf(row, 'points');
        if (trigger && window.htmx) window.htmx.trigger(trigger, 'resend');
      });
    }
    window.addEventListener('online', flush);
    window.addEventListener('beforeunload', persist);
    if (navigator.onLine) setTimeout(flush, 1200);
  }

  function init() {
    var form = document.querySelector('[data-journal]');
    if (form) setUp(form);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.body.addEventListener('htmx:afterSettle', init);
})();
