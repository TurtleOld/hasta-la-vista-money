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
  document.querySelectorAll('[data-audit-row].audit-row--open').forEach((row) => {
    if (row instanceof HTMLElement) {
      closeRow(row);
    }
  });
});
