document.addEventListener('alpine:init', () => {
  Alpine.store('financesReady', { enabled: true });
});

(function () {
  const storage = {
    get(key, fallback) {
      try {
        return localStorage.getItem(key) || fallback;
      } catch {
        return fallback;
      }
    },
    set(key, value) {
      try {
        localStorage.setItem(key, value);
      } catch {
        return;
      }
    },
  };

  function app() {
    return document.querySelector('[data-finances-app]');
  }

  function form() {
    return document.getElementById('finances-form');
  }

  function submitForm() {
    const currentForm = form();
    if (currentForm) {
      currentForm.requestSubmit();
    }
  }

  function closePops(except) {
    document.querySelectorAll('[data-finances-pop]').forEach((pop) => {
      if (pop.dataset.financesPop !== except) {
        pop.classList.remove('is-open');
      }
    });
  }

  function setGroup(value) {
    const root = app();
    if (!root) return;
    root.dataset.group = value;
    storage.set('hlvm.finances.group', value);
    syncControls();
  }

  function setLayout(value) {
    const root = app();
    if (!root) return;
    root.dataset.layout = value;
    storage.set('hlvm.finances.layout', value);
    syncControls();
  }

  function toggleBalance() {
    const root = app();
    if (!root) return;
    root.classList.toggle('is-balance-hidden');
    storage.set(
      'hlvm.finances.hideBalance',
      root.classList.contains('is-balance-hidden') ? 'true' : 'false',
    );
    syncControls();
  }

  function syncControls() {
    const root = app();
    if (!root) return;
    document.querySelectorAll('[data-finances-group]').forEach((button) => {
      button.classList.toggle(
        'is-active',
        button.dataset.financesGroup === root.dataset.group,
      );
    });
    document.querySelectorAll('[data-finances-layout]').forEach((button) => {
      button.classList.toggle('is-active', root.dataset.layout === 'dashboard');
    });
    document.querySelectorAll('[data-finances-balance]').forEach((button) => {
      button.classList.toggle(
        'is-active',
        root.classList.contains('is-balance-hidden'),
      );
    });
  }

  function hydrateState() {
    const root = app();
    if (!root) return;
    root.dataset.layout = storage.get('hlvm.finances.layout', 'compact');
    root.dataset.group = storage.get('hlvm.finances.group', 'day');
    root.classList.toggle(
      'is-balance-hidden',
      storage.get('hlvm.finances.hideBalance', 'false') === 'true',
    );
    syncControls();
  }

  document.addEventListener('click', (event) => {
    const popButton = event.target.closest('[data-finances-pop-button]');
    if (popButton) {
      const name = popButton.dataset.financesPopButton;
      const pop = document.querySelector(`[data-finances-pop="${name}"]`);
      const willOpen = pop && !pop.classList.contains('is-open');
      closePops(name);
      if (pop) {
        pop.classList.toggle('is-open', Boolean(willOpen));
      }
      return;
    }

    const setter = event.target.closest('[data-finances-set]');
    if (setter) {
      const target = document.getElementById(setter.dataset.financesSet);
      if (target) {
        target.value = setter.dataset.financesValue || '';
      }
      closePops();
      submitForm();
      return;
    }

    const typeButton = event.target.closest('[data-finances-type]');
    if (typeButton) {
      const typeInput = document.getElementById('finances-type');
      if (typeInput) {
        typeInput.value = typeButton.dataset.financesType;
      }
      submitForm();
      return;
    }

    const groupButton = event.target.closest('[data-finances-group]');
    if (groupButton) {
      setGroup(groupButton.dataset.financesGroup);
      return;
    }

    if (event.target.closest('[data-finances-layout]')) {
      const root = app();
      setLayout(root?.dataset.layout === 'compact' ? 'dashboard' : 'compact');
      return;
    }

    if (event.target.closest('[data-finances-balance]')) {
      toggleBalance();
      return;
    }

    if (!event.target.closest('.finances-pop-wrap')) {
      closePops();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closePops();
    }
    if (event.key === '/' && event.target.tagName !== 'INPUT') {
      const search = document.querySelector('[data-finances-search]');
      if (search) {
        event.preventDefault();
        search.focus();
      }
    }
  });

  document.addEventListener('change', (event) => {
    if (event.target.closest('.finances-pop')) {
      submitForm();
    }
  });

  document.addEventListener('htmx:afterSwap', hydrateState);
  document.addEventListener('DOMContentLoaded', hydrateState);
})();
