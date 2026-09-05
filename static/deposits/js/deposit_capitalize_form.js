/**
 * Deposit interest confirmation form — scenario switch, destination
 * account visibility, and net amount auto-calculation.
 *
 * Two mutually exclusive scenarios share the same set of fields: "confirm
 * an expected forecast payout" (shows `forecast`, hides `reason`) and
 * "record an unscheduled payout" (shows `reason`, hides `forecast`). This
 * is purely a display convenience — the server-side clean() in
 * CapitalizeInterestForm remains the only source of truth for which
 * fields are actually required, so hiding a field here never disables it.
 *
 * `net` is likewise auto-filled from `gross - withholding` as a
 * convenience; the field stays editable by hand for edge-case rounding,
 * and the server-side check that net == gross - withholding remains the
 * only source of truth.
 */
(function () {
  var INTERNAL_ACCOUNT_DESTINATION = 'internal_account';

  function init() {
    var form = document.querySelector('[data-cif-form]');
    if (!form) return;

    var forecastInput = form.querySelector('[name="forecast"]');
    var reasonInput = form.querySelector('[name="reason"]');
    var destinationSelect = form.querySelector('[name="destination"]');
    var destinationAccountInput = form.querySelector(
      '[name="destination_account"]',
    );
    var scenarioRadios = form.querySelectorAll('[data-cif-scenario-radio]');
    var grossInput = form.querySelector('[name="gross"]');
    var withholdingInput = form.querySelector('[name="withholding"]');
    var netInput = form.querySelector('[name="net"]');

    function section(input) {
      return input ? input.closest('.accounts-cmp-section') : null;
    }

    var forecastSection = section(forecastInput);
    var reasonSection = section(reasonInput);
    var destinationAccountSection = section(destinationAccountInput);

    function applyScenario(scenario) {
      if (forecastSection) {
        forecastSection.classList.toggle(
          'is-hidden-icon',
          scenario !== 'forecast',
        );
      }
      if (reasonSection) {
        reasonSection.classList.toggle(
          'is-hidden-icon',
          scenario !== 'reason',
        );
      }
    }

    function applyDestinationVisibility() {
      if (!destinationSelect || !destinationAccountSection) return;
      destinationAccountSection.classList.toggle(
        'is-hidden-icon',
        destinationSelect.value !== INTERNAL_ACCOUNT_DESTINATION,
      );
    }

    var netEditedByUser = false;

    function recalculateNet() {
      if (netEditedByUser || !grossInput || !withholdingInput || !netInput) {
        return;
      }
      var gross = parseFloat(grossInput.value.replace(',', '.'));
      var withholding = parseFloat(
        withholdingInput.value.replace(',', '.'),
      );
      if (isNaN(gross) || isNaN(withholding)) return;
      var net = Math.round((gross - withholding) * 100) / 100;
      netInput.value = net < 0 ? '' : net;
    }

    var initialScenario = form.getAttribute('data-cif-initial-scenario');
    applyScenario(initialScenario);
    applyDestinationVisibility();
    recalculateNet();

    scenarioRadios.forEach(function (radio) {
      radio.addEventListener('change', function () {
        if (radio.checked) applyScenario(radio.value);
      });
    });
    if (destinationSelect) {
      destinationSelect.addEventListener(
        'change',
        applyDestinationVisibility,
      );
    }
    if (grossInput) grossInput.addEventListener('input', recalculateNet);
    if (withholdingInput) {
      withholdingInput.addEventListener('input', recalculateNet);
    }
    if (netInput) {
      netInput.addEventListener('input', function () {
        netEditedByUser = true;
      });
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
