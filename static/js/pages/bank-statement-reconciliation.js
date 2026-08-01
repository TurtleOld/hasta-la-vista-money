(function () {
  'use strict';

  const form = document.getElementById('bulk-form');
  const results = document.getElementById('bulk-results');
  if (!form || !results) return;

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    const submitter = event.submitter;
    const decision = submitter ? submitter.value : '';
    const data = new FormData(form);
    data.set('decision', decision);
    results.replaceChildren();

    const response = await fetch(form.action, {
      method: 'POST',
      body: data,
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    const payload = await response.json();
    if (!response.ok) {
      const item = document.createElement('p');
      item.textContent =
        payload.error === 'confirmation_required'
          ? form
              .querySelector('[name="confirm_risk"]')
              .parentElement.textContent.trim()
          : String(payload.error || response.status);
      results.appendChild(item);
      return;
    }
    for (const result of payload.results) {
      const item = document.createElement('p');
      const key = result.outcome === 'not_found' ? 'notFound' : result.outcome;
      item.textContent = `#${result.row_id}: ${form.dataset[key] || result.outcome}`;
      results.appendChild(item);
    }
    const summary = document.createElement('p');
    summary.textContent = `${form.dataset.summary}: ${form.dataset.imported} ${payload.outcomes.imported}, ${form.dataset.linkedCount} ${payload.outcomes.linked}, ${form.dataset.awaiting} ${payload.outcomes.awaiting_decision}, ${form.dataset.expiredCount} ${payload.outcomes.expired}`;
    results.appendChild(summary);
  });
})();
