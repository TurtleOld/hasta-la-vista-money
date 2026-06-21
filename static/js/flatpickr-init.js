import flatpickr from 'flatpickr';
import 'flatpickr/dist/flatpickr.min.css';
import { Russian } from 'flatpickr/dist/l10n/ru.js';

const FLATPICKR_SELECTOR = '[data-flatpickr]';

function buildFlatpickrOptions(element) {
  const mode = element.dataset.flatpickrMode ?? 'date';

  if (mode === 'datetime') {
    const now = new Date();
    return {
      locale: Russian,
      enableTime: true,
      time_24hr: true,
      dateFormat: 'Y-m-d\\TH:i',
      altInput: true,
      altFormat: 'd.m.Y H:i',
      defaultHour: now.getHours(),
      defaultMinute: now.getMinutes(),
    };
  }

  if (mode === 'range') {
    const fromId = element.dataset.flatpickrFrom;
    const toId   = element.dataset.flatpickrTo;
    const formEl = element.closest('form');

    const fromInput = fromId ? document.getElementById(fromId) : null;
    const toInput   = toId   ? document.getElementById(toId)   : null;

    const fmt = (d) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

    const bothSet = fromInput?.value && toInput?.value;

    return {
      locale: Russian,
      mode: 'range',
      dateFormat: 'Y-m-d',
      altInput: true,
      altFormat: 'd.m.Y',
      defaultDate: bothSet ? [fromInput.value, toInput.value] : undefined,
      onChange(selectedDates) {
        if (selectedDates.length === 2) {
          if (fromInput) fromInput.value = fmt(selectedDates[0]);
          if (toInput)   toInput.value   = fmt(selectedDates[1]);
          formEl?.submit();
        }
      },
      onClose(selectedDates) {
        if (selectedDates.length === 0) {
          if (fromInput) fromInput.value = '';
          if (toInput)   toInput.value   = '';
        }
      },
    };
  }

  return {
    locale: Russian,
    dateFormat: 'Y-m-d',
    altInput: true,
    altFormat: 'd.m.Y',
  };
}

export function initializeFlatpickr(rootElement = document) {
  const root =
    rootElement instanceof Element || rootElement instanceof Document
      ? rootElement
      : document;

  root.querySelectorAll(FLATPICKR_SELECTOR).forEach((element) => {
    if (!(element instanceof HTMLInputElement)) {
      return;
    }

    if (element._flatpickr) {
      return;
    }

    flatpickr(element, buildFlatpickrOptions(element));
  });
}

function initializeAutosubmit(rootElement = document) {
  const root =
    rootElement instanceof Element || rootElement instanceof Document
      ? rootElement
      : document;

  root.querySelectorAll('select[data-autosubmit]').forEach((select) => {
    if (select._autosubmit) return;
    select._autosubmit = true;
    select.addEventListener('change', () => select.closest('form')?.submit());
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initializeFlatpickr();
  initializeAutosubmit();
});

const bodyElement = document.body;
if (bodyElement) {
  bodyElement.addEventListener('htmx:afterSwap', (event) => {
    const { target } = event;
    if (target instanceof Element) {
      initializeFlatpickr(target);
    }
  });
}
