import flatpickr from 'flatpickr';
import 'flatpickr/dist/flatpickr.min.css';
import { Russian } from 'flatpickr/dist/l10n/ru.js';

const FLATPICKR_SELECTOR = '[data-flatpickr]';

function buildFlatpickrOptions(element) {
  const mode = element.dataset.flatpickrMode ?? 'date';

  if (mode === 'datetime') {
    return {
      locale: Russian,
      enableTime: true,
      time_24hr: true,
      dateFormat: 'Y-m-d\\TH:i',
      altInput: true,
      altFormat: 'd.m.Y H:i',
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

document.addEventListener('DOMContentLoaded', () => {
  initializeFlatpickr();
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
