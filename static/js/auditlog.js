const WIDE_QUERY = '(min-width: 768px)';

/**
 * @param {HTMLElement} row
 * @returns {HTMLElement | null}
 */
function getAccordion(row) {
  return row.querySelector('[data-audit-accordion]');
}

/**
 * @param {HTMLElement} row
 */
function closeRow(row) {
  const accordion = getAccordion(row);
  row.classList.remove('audit-row--open');
  if (accordion) {
    accordion.hidden = true;
  }
}

/**
 * @param {HTMLElement} row
 * @param {string} url
 */
async function openRow(row, url) {
  const accordion = getAccordion(row);
  if (!accordion) {
    return;
  }
  row.classList.add('audit-row--open');
  accordion.hidden = false;
  if (accordion.dataset.loaded === 'true') {
    return;
  }
  try {
    const response = await fetch(url, {
      headers: { 'HX-Request': 'true' },
    });
    if (!response.ok) {
      throw new Error(`Unexpected status ${response.status}`);
    }
    accordion.innerHTML = await response.text();
    accordion.dataset.loaded = 'true';
  } catch {
    closeRow(row);
  }
}

document.addEventListener('click', (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }
  const link = event.target.closest('[data-audit-toggle]');
  if (!link || !(link instanceof HTMLElement)) {
    return;
  }
  if (!window.matchMedia(WIDE_QUERY).matches) {
    return;
  }
  const row = link.closest('[data-audit-row]');
  if (!row || !(row instanceof HTMLElement)) {
    return;
  }
  event.preventDefault();
  const url = link.dataset.auditUrl;
  if (!url) {
    return;
  }
  if (row.classList.contains('audit-row--open')) {
    closeRow(row);
    return;
  }
  openRow(row, url);
});

window.matchMedia(WIDE_QUERY).addEventListener('change', (event) => {
  if (event.matches) {
    return;
  }
  document
    .querySelectorAll('[data-audit-row].audit-row--open')
    .forEach((row) => {
      if (row instanceof HTMLElement) {
        closeRow(row);
      }
    });
});

const sheetAnchors = new WeakMap();

/**
 * @param {string} name
 * @returns {HTMLDialogElement | null}
 */
function getFilterSheet(name) {
  return document.querySelector(`dialog[data-audit-sheet="${name}"]`);
}

/**
 * @returns {HTMLFormElement | null}
 */
function getFilterForm() {
  return document.querySelector('[data-audit-filter-form]');
}

/**
 * @param {HTMLFormElement} form
 */
function submitFilterForm(form) {
  if (form.requestSubmit) {
    form.requestSubmit();
  } else {
    form.submit();
  }
}

/**
 * @param {HTMLDialogElement} sheet
 * @param {HTMLElement} anchor
 */
function positionFilterPopover(sheet, anchor) {
  const margin = 8;
  const anchorRect = anchor.getBoundingClientRect();
  const sheetWidth = sheet.offsetWidth;
  const left = Math.max(
    margin,
    Math.min(anchorRect.left, window.innerWidth - sheetWidth - margin),
  );
  sheet.style.top = `${anchorRect.bottom + margin}px`;
  sheet.style.left = `${left}px`;
}

/**
 * @param {string} name
 * @param {HTMLElement} anchor
 */
function openFilterSheet(name, anchor) {
  const sheet = getFilterSheet(name);
  if (!sheet) {
    return;
  }
  document
    .querySelectorAll('dialog[data-audit-sheet][open]')
    .forEach((open) => {
      if (open !== sheet && open instanceof HTMLDialogElement) {
        open.close();
      }
    });
  sheet.style.removeProperty('top');
  sheet.style.removeProperty('left');
  sheet.showModal();
  sheetAnchors.set(sheet, anchor);
  anchor.setAttribute('aria-expanded', 'true');
  if (window.matchMedia(WIDE_QUERY).matches) {
    positionFilterPopover(sheet, anchor);
  }
}

/**
 * @param {string} field
 * @param {string} value
 */
function applyFilterValue(field, value) {
  const form = getFilterForm();
  if (!form) {
    return;
  }
  const select = form.querySelector(`#id_${field}`);
  if (select instanceof HTMLSelectElement) {
    select.value = value;
  }
  submitFilterForm(form);
}

/**
 * @param {string} field
 */
function clearFilterField(field) {
  const form = getFilterForm();
  if (!form) {
    return;
  }
  if (field === 'period') {
    const from = form.querySelector('#id_date_from');
    const to = form.querySelector('#id_date_to');
    if (from instanceof HTMLInputElement) from.value = '';
    if (to instanceof HTMLInputElement) to.value = '';
  } else {
    const select = form.querySelector(`#id_${field}`);
    if (select instanceof HTMLSelectElement) select.value = '';
  }
  submitFilterForm(form);
}

/**
 * @param {number} year
 * @param {number} month
 * @param {number} day
 * @returns {string}
 */
function isoDate(year, month, day) {
  const date = new Date(year, month, day);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

/**
 * @param {string} preset
 * @returns {[string, string] | null}
 */
function presetDateRange(preset) {
  const today = new Date();
  const y = today.getFullYear();
  const m = today.getMonth();
  const d = today.getDate();
  switch (preset) {
    case 'today':
      return [isoDate(y, m, d), isoDate(y, m, d)];
    case 'last-7': {
      const from = new Date(y, m, d - 6);
      return [
        isoDate(from.getFullYear(), from.getMonth(), from.getDate()),
        isoDate(y, m, d),
      ];
    }
    case 'this-month':
      return [isoDate(y, m, 1), isoDate(y, m, d)];
    case 'last-month':
      return [isoDate(y, m - 1, 1), isoDate(y, m, 0)];
    default:
      return null;
  }
}

function applyPeriodFromSheet() {
  const sheet = getFilterSheet('period');
  const form = getFilterForm();
  if (!sheet || !form) {
    return;
  }
  const fromField = sheet.querySelector('[data-audit-period-from]');
  const toField = sheet.querySelector('[data-audit-period-to]');
  const dateFrom = form.querySelector('#id_date_from');
  const dateTo = form.querySelector('#id_date_to');
  if (
    fromField instanceof HTMLInputElement &&
    toField instanceof HTMLInputElement &&
    dateFrom instanceof HTMLInputElement &&
    dateTo instanceof HTMLInputElement
  ) {
    dateFrom.value = fromField.value;
    dateTo.value = toField.value;
  }
  submitFilterForm(form);
}

document.querySelectorAll('dialog[data-audit-sheet]').forEach((sheet) => {
  sheet.addEventListener('close', () => {
    const anchor = sheetAnchors.get(sheet);
    anchor?.setAttribute('aria-expanded', 'false');
  });
  sheet.addEventListener('click', (event) => {
    if (event.target === sheet) {
      sheet.close();
    }
  });
});

document.addEventListener('click', (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }

  const clearButton = event.target.closest('[data-audit-chip-clear]');
  if (
    clearButton instanceof HTMLElement &&
    clearButton.dataset.auditChipClear
  ) {
    clearFilterField(clearButton.dataset.auditChipClear);
    return;
  }

  const openButton = event.target.closest('[data-audit-chip-open]');
  if (openButton instanceof HTMLElement && openButton.dataset.auditChipOpen) {
    openFilterSheet(openButton.dataset.auditChipOpen, openButton);
    return;
  }

  const closeButton = event.target.closest('[data-audit-sheet-close]');
  if (closeButton) {
    closeButton.closest('dialog')?.close();
    return;
  }

  const pickButton = event.target.closest('[data-audit-pick]');
  if (pickButton instanceof HTMLElement && pickButton.dataset.auditPick) {
    applyFilterValue(
      pickButton.dataset.auditPick,
      pickButton.dataset.value ?? '',
    );
    return;
  }

  const presetButton = event.target.closest('[data-audit-preset]');
  if (presetButton instanceof HTMLElement && presetButton.dataset.auditPreset) {
    const range = presetDateRange(presetButton.dataset.auditPreset);
    const sheet = presetButton.closest('dialog');
    const fromField = sheet?.querySelector('[data-audit-period-from]');
    const toField = sheet?.querySelector('[data-audit-period-to]');
    if (
      range &&
      fromField instanceof HTMLInputElement &&
      toField instanceof HTMLInputElement
    ) {
      [fromField.value, toField.value] = range;
      sheet
        ?.querySelectorAll('[data-audit-preset]')
        .forEach((preset) => preset.classList.remove('audit-preset--on'));
      presetButton.classList.add('audit-preset--on');
    }
    return;
  }

  const applyButton = event.target.closest('[data-audit-period-apply]');
  if (applyButton) {
    applyPeriodFromSheet();
  }
});

document.addEventListener('input', (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }
  const field = event.target.closest(
    '[data-audit-period-from], [data-audit-period-to]',
  );
  if (!field) {
    return;
  }
  field
    .closest('dialog')
    ?.querySelectorAll('[data-audit-preset]')
    .forEach((preset) => preset.classList.remove('audit-preset--on'));
});

window.matchMedia(WIDE_QUERY).addEventListener('change', () => {
  document
    .querySelectorAll('dialog[data-audit-sheet][open]')
    .forEach((sheet) => {
      if (sheet instanceof HTMLDialogElement) {
        sheet.close();
      }
    });
});
