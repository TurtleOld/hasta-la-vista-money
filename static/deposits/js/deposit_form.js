/**
 * Deposit creation form — inline "add personal bank" control.
 *
 * Lets the user create a personal bank without leaving the page, so the
 * contract terms already typed into the rest of the form are preserved.
 */
(function () {
  function init() {
    var root = document.querySelector('[data-qb-root]');
    if (!root) return;

    var config = window.HLVM_DEPOSIT_FORM_CONFIG || {};
    var section = root.closest('section');
    var select = section ? section.querySelector('select') : null;
    var toggleBtn = root.querySelector('[data-qb-toggle]');
    var form = root.querySelector('[data-qb-form]');
    var input = root.querySelector('[data-qb-name]');
    var saveBtn = root.querySelector('[data-qb-save]');
    var cancelBtn = root.querySelector('[data-qb-cancel]');
    var errorEl = root.querySelector('[data-qb-error]');
    var creating = false;

    if (!select || !form || !input || !saveBtn || !cancelBtn) return;

    function showError(message) {
      if (!errorEl) return;
      errorEl.textContent = message || '';
      errorEl.classList.toggle('is-hidden-icon', !message);
    }

    function showForm() {
      form.classList.remove('is-hidden-icon');
      input.value = '';
      showError('');
      input.focus();
    }

    function hideForm() {
      form.classList.add('is-hidden-icon');
      showError('');
    }

    function setBusy(busy) {
      creating = busy;
      saveBtn.disabled = busy;
    }

    async function save() {
      if (creating) return;
      var name = (input.value || '').trim();
      if (!name) {
        input.focus();
        return;
      }
      setBusy(true);
      showError('');

      var formData = new FormData();
      formData.append('name', name);

      try {
        var response = await fetch(config.quickBankUrl, {
          method: 'POST',
          headers: {
            'X-CSRFToken': config.csrfToken,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: formData,
          credentials: 'same-origin',
        });
        var data = await response.json();
        if (!response.ok || !data.ok) {
          showError(data.error || '');
          setBusy(false);
          return;
        }
        var exists = false;
        for (var i = 0; i < select.options.length; i += 1) {
          if (String(select.options[i].value) === String(data.id)) {
            exists = true;
            break;
          }
        }
        if (!exists) {
          var option = document.createElement('option');
          option.value = String(data.id);
          option.textContent = data.name;
          select.appendChild(option);
        }
        select.value = String(data.id);
        setBusy(false);
        hideForm();
      } catch (_err) {
        showError('');
        setBusy(false);
      }
    }

    toggleBtn.addEventListener('click', showForm);
    cancelBtn.addEventListener('click', hideForm);
    saveBtn.addEventListener('click', save);
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') {
        event.preventDefault();
        save();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();
