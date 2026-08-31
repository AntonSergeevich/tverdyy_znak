/**
 * Полукруглый ползунок баллов.
 *
 * Педагог ставит баллы с телефона, стоя, сразу после занятия. Клавиатура
 * в этот момент закрывает половину списка, а попасть в узкое поле пальцем
 * трудно. Поэтому балл выбирается дугой во весь экран: ведёшь пальцем —
 * цифра растёт, на каждом делении телефон коротко вздрагивает, и шкалу
 * можно отмерить, почти не глядя.
 *
 * Скрипт ничего не отправляет сам. Он вписывает выбранное в обычные
 * скрытые поля строки и дёргает у них change — дальше всё делает тот же
 * htmx, что и раньше: и сохранение, и очередь на случай обрыва сети.
 */
(function () {
  'use strict';

  var STEP_SMALL = 0.5;   // до этого максимума шаг в полбалла
  var SMALL_MAX = 20;

  var root, sheet, gauge, fillPath, knob, valueOut, maxOut, nameOut, subOut, commentField;
  var fillLength = 0;
  var current = null;      // выбранный балл или null («без балла»)
  var max = 10;
  var step = 1;
  var owner = null;        // .journal-row или #bulk-controls, чью отметку правим
  var lastBuzz = null;
  var restoreFocus = null;

  // ── Мелочи ────────────────────────────────────────────────────────────────

  function buzz(ms) {
    if (navigator.vibrate) { try { navigator.vibrate(ms); } catch (e) { /* нельзя — и ладно */ } }
  }

  function human(value) {
    if (value === null || value === undefined || value === '') return '—';
    var rounded = Math.round(value * 100) / 100;
    return String(rounded).replace('.', ',');
  }

  function machine(value) {
    if (value === null) return '';
    return String(Math.round(value * 100) / 100);
  }

  function clamp(value) {
    if (value < 0) return 0;
    if (value > max) return max;
    return value;
  }

  function snap(value) {
    return clamp(Math.round(value / step) * step);
  }

  // ── Отрисовка ─────────────────────────────────────────────────────────────

  function draw() {
    var fraction = max > 0 && current !== null ? clamp(current) / max : 0;

    if (fillLength) {
      fillPath.style.strokeDasharray = fillLength;
      fillPath.style.strokeDashoffset = fillLength * (1 - fraction);
    }
    // Дуга идёт слева направо через верх: угол π при нуле, 0 при максимуме.
    var angle = Math.PI * (1 - fraction);
    knob.setAttribute('cx', 140 + 118 * Math.cos(angle));
    knob.setAttribute('cy', 150 - 118 * Math.sin(angle));
    knob.classList.toggle('dial__knob--empty', current === null);

    valueOut.textContent = human(current);
    gauge.setAttribute('aria-valuenow', current === null ? 0 : current);
    gauge.setAttribute('aria-valuetext', current === null ? 'балл не выставлен' : human(current));
  }

  function setValue(value, options) {
    var silent = options && options.silent;
    // Уже выставленный балл показываем как есть. Округлить его к делению
    // шкалы значило бы тихо переправить 4,6 на 4,5 у того, кто зашёл
    // просто посмотреть.
    var exact = options && options.exact;
    current = value === null ? null : (exact ? clamp(value) : snap(value));
    if (!silent && current !== lastBuzz) buzz(8);
    lastBuzz = current;
    draw();
  }

  // ── Открытие и закрытие ───────────────────────────────────────────────────

  function rows() {
    return Array.prototype.slice.call(document.querySelectorAll('.journal-list .journal-row'));
  }

  function open(holder) {
    owner = holder;
    max = parseFloat(holder.getAttribute('data-max')) || 0;
    step = max <= SMALL_MAX ? STEP_SMALL : 1;

    var points = holder.querySelector('[data-points]');
    var comment = holder.querySelector('[data-comment]');
    var raw = points && points.value !== '' ? parseFloat(points.value) : null;

    nameOut.textContent = holder.getAttribute('data-name') || '';
    var index = rows().indexOf(holder);
    subOut.textContent = index >= 0
      ? 'ученик ' + (index + 1) + ' из ' + rows().length
      : 'балл получат все, у кого его ещё нет';
    maxOut.textContent = human(max);
    commentField.value = comment ? comment.value : '';
    commentField.closest('.dial__comment').hidden = !comment;

    // Соседей листаем только по списку учеников: «всем» — не ученик.
    var single = index >= 0;
    sheet.querySelector('[data-dial-prev]').hidden = !single;
    sheet.querySelector('[data-dial-next]').hidden = !single;
    sheet.querySelector('[data-dial-next-save]').hidden = !single || index === rows().length - 1;

    lastBuzz = null;
    setValue(isNaN(raw) ? null : raw, { silent: true, exact: true });

    restoreFocus = document.activeElement;
    root.hidden = false;
    root.setAttribute('aria-hidden', 'false');
    document.body.classList.add('is-dialed');
    gauge.focus();
  }

  function close() {
    root.hidden = true;
    root.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('is-dialed');
    owner = null;
    if (restoreFocus && restoreFocus.focus) restoreFocus.focus();
    restoreFocus = null;
  }

  // ── Запись обратно в строку ───────────────────────────────────────────────

  function chipText(holder) {
    var chip = holder.querySelector('[data-chip-value]');
    if (!chip) return;
    var points = holder.querySelector('[data-points]');
    var value = points && points.value !== '' ? parseFloat(points.value) : null;
    chip.textContent = human(isNaN(value) ? null : value);
    var button = chip.closest('.grade-chip');
    if (button) button.classList.toggle('grade-chip--set', value !== null && !isNaN(value));
  }

  function commit(holder) {
    var points = holder.querySelector('[data-points]');
    var comment = holder.querySelector('[data-comment]');
    if (!points) return;

    points.value = machine(current);
    if (comment) comment.value = commentField.value.trim();

    var note = holder.querySelector('[data-note]');
    if (note && comment) {
      note.textContent = comment.value;
      note.hidden = !comment.value;
    }
    chipText(holder);

    // Групповое выставление уходит по кнопке «Поставить», а не сразу:
    // случайно поставить балл всему классу должно быть трудно.
    if (holder.hasAttribute('data-dial-bulk') || holder.id === 'bulk-controls') return;
    points.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function save(thenNext) {
    var holder = owner;
    if (!holder) return;
    buzz(14);
    commit(holder);

    if (thenNext) {
      var list = rows();
      var next = list[list.indexOf(holder) + 1];
      if (next) { open(next); return; }
    }
    close();
  }

  function hop(delta) {
    if (!owner) return;
    var list = rows();
    var next = list[list.indexOf(owner) + delta];
    if (next) open(next);
  }

  // ── Перетаскивание по дуге ────────────────────────────────────────────────

  function valueAt(event) {
    var box = gauge.getBoundingClientRect();
    // Геометрия дуги задана в единицах viewBox (280×172) — переводим в них.
    var scale = box.width / 280;
    var x = (event.clientX - box.left) / scale;
    var y = (event.clientY - box.top) / scale;
    var angle = Math.atan2(150 - y, x - 140);
    if (angle < 0) angle = y > 150 ? (x < 140 ? Math.PI : 0) : 0;
    var fraction = 1 - angle / Math.PI;
    return snap(fraction * max);
  }

  function dragStart(event) {
    if (event.button !== undefined && event.button !== 0) return;
    gauge.setPointerCapture(event.pointerId);
    gauge.classList.add('dial__gauge--held');
    setValue(valueAt(event));
    event.preventDefault();
  }

  function dragMove(event) {
    if (!gauge.hasPointerCapture || !gauge.hasPointerCapture(event.pointerId)) return;
    setValue(valueAt(event));
    event.preventDefault();
  }

  function dragEnd(event) {
    gauge.classList.remove('dial__gauge--held');
    if (gauge.hasPointerCapture && gauge.hasPointerCapture(event.pointerId)) {
      gauge.releasePointerCapture(event.pointerId);
    }
  }

  // ── Сборка ────────────────────────────────────────────────────────────────

  function wire() {
    root = document.getElementById('grade-dial');
    if (!root || root.dataset.ready === '1') return !!root;
    root.dataset.ready = '1';

    sheet = root.querySelector('.dial__sheet');
    gauge = root.querySelector('[data-dial-gauge]');
    fillPath = root.querySelector('[data-dial-fill]');
    knob = root.querySelector('[data-dial-knob]');
    valueOut = root.querySelector('[data-dial-value]');
    maxOut = root.querySelector('[data-dial-max]');
    nameOut = root.querySelector('.dial__name');
    subOut = root.querySelector('.dial__sub');
    commentField = root.querySelector('[data-dial-comment]');

    fillLength = fillPath.getTotalLength ? fillPath.getTotalLength() : 0;

    gauge.addEventListener('pointerdown', dragStart);
    gauge.addEventListener('pointermove', dragMove);
    gauge.addEventListener('pointerup', dragEnd);
    gauge.addEventListener('pointercancel', dragEnd);

    gauge.addEventListener('keydown', function (event) {
      var delta = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[event.key];
      if (delta === undefined) return;
      setValue((current === null ? 0 : current) + delta * step);
      event.preventDefault();
    });

    root.addEventListener('click', function (event) {
      var target = event.target;
      if (target.closest('[data-dial-close]')) return close();
      if (target.closest('[data-dial-save]')) return save(false);
      if (target.closest('[data-dial-next-save]')) return save(true);
      if (target.closest('[data-dial-clear]')) { setValue(null); return save(false); }
      if (target.closest('[data-dial-prev]')) return hop(-1);
      if (target.closest('[data-dial-next]')) return hop(1);

      var stepper = target.closest('[data-dial-step]');
      if (stepper) {
        var by = parseFloat(stepper.getAttribute('data-dial-step')) * step;
        return setValue((current === null ? 0 : current) + by);
      }
      var setter = target.closest('[data-dial-set]');
      if (setter) {
        var what = setter.getAttribute('data-dial-set');
        return setValue(what === 'max' ? max : what === 'half' ? max / 2 : 0);
      }
    });

    document.addEventListener('keydown', function (event) {
      if (root.hidden) return;
      if (event.key === 'Escape') close();
      if (event.key === 'Enter' && event.target !== commentField) save(false);
    });

    return true;
  }

  function init() {
    if (!wire()) return;
    // Отметки в строках держим в согласии со скрытыми полями: после
    // восстановления несохранённого из памяти браузера значения в полях
    // уже другие, а цифра на кнопке осталась серверной.
    document.querySelectorAll('.journal-row, #bulk-controls').forEach(chipText);

    document.querySelectorAll('[data-dial-open]').forEach(function (button) {
      if (button.dataset.wired === '1') return;
      button.dataset.wired = '1';
      button.addEventListener('click', function () {
        var holder = button.closest('.journal-row') || button.closest('#bulk-controls');
        if (holder) open(holder);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  // Строка после сохранения приезжает новая — поднимаем её заново.
  document.body.addEventListener('htmx:afterSettle', init);
})();
