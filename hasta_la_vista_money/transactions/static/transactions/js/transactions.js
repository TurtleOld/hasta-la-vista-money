document.addEventListener('alpine:init', () => {
  Alpine.store('financesReady', { enabled: true });
});

(function () {
  let searchSelection = null;

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
        document
          .querySelector(
            `[data-finances-pop-button="${pop.dataset.financesPop}"]`,
          )
          ?.setAttribute('aria-expanded', 'false');
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
        popButton.setAttribute('aria-expanded', String(Boolean(willOpen)));
      }
      return;
    }

    const setter = event.target.closest('[data-finances-set]');
    if (setter) {
      const target = document.getElementById(setter.dataset.financesSet);
      if (target) {
        target.value = setter.dataset.financesValue || '';
      }
      const clearedIds = (setter.dataset.financesClear || '')
        .split(/\s+/)
        .filter(Boolean);
      clearedIds.forEach((id) => {
        const clearTarget = document.getElementById(id);
        if (clearTarget) clearTarget.value = '';
      });
      if (clearedIds.includes('finances-date-from')) {
        const dateNative = document.querySelector('[data-finances-date-native]');
        const label = document.querySelector('[data-finances-date-label]');
        if (dateNative) dateNative.value = '';
        if (label) label.textContent = label.dataset.financesDatePlaceholder;
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

    const scopeButton = event.target.closest('[data-finances-scope]');
    if (scopeButton) {
      const groupInput = document.getElementById('finances-group');
      if (groupInput) {
        groupInput.value = scopeButton.dataset.financesScope;
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

  function formatDayMonthYear(isoDate) {
    const [year, month, day] = isoDate.split('-');
    return `${day}.${month}.${year}`;
  }

  // Capture phase, and stopped here: the toolbar sits inside the form that
  // htmx auto-submits on "change" (hx-trigger="change, ..."), and the form
  // is reached before document in the bubble phase. Left as a normal bubble
  // listener, htmx would fire its request off the stale (not yet copied)
  // finances-date-from/-to hidden fields a tick before this code runs, and
  // the swapped-in response would immediately erase what we just set.
  document.addEventListener(
    'change',
    (event) => {
      const dateNative = event.target.closest('[data-finances-date-native]');
      if (!dateNative) return;
      event.stopPropagation();

      const value = dateNative.value || '';
      const fromInput = document.getElementById('finances-date-from');
      const toInput = document.getElementById('finances-date-to');
      if (fromInput) fromInput.value = value;
      if (toInput) toInput.value = value;
      if (value) {
        const clearId = dateNative.dataset.financesClearId;
        const clearValue = dateNative.dataset.financesClearValue ?? '';
        const clearTarget = clearId && document.getElementById(clearId);
        if (clearTarget) clearTarget.value = clearValue;
      }
      const label = dateNative
        .closest('.finances-date-chip')
        ?.querySelector('[data-finances-date-label]');
      if (label) {
        label.textContent = value
          ? formatDayMonthYear(value)
          : label.dataset.financesDatePlaceholder;
      }
      submitForm();
    },
    true,
  );

  document.addEventListener('change', (event) => {
    if (event.target.closest('.finances-pop')) {
      submitForm();
    }
  });

  document.addEventListener('htmx:beforeSwap', (event) => {
    if (event.detail.target?.id !== 'finances-results') return;
    const search = document.querySelector('[data-finances-search]');
    if (search && document.activeElement === search) {
      searchSelection = {
        start: search.selectionStart,
        end: search.selectionEnd,
        direction: search.selectionDirection,
      };
    } else {
      searchSelection = null;
    }
  });

  document.addEventListener('htmx:afterSwap', (event) => {
    hydrateState();
    if (event.detail.target?.id !== 'finances-results' || !searchSelection) {
      return;
    }
    const search = document.querySelector('[data-finances-search]');
    if (search) {
      search.focus({ preventScroll: true });
      search.setSelectionRange(
        searchSelection.start,
        searchSelection.end,
        searchSelection.direction,
      );
    }
    searchSelection = null;
  });
  document.addEventListener('DOMContentLoaded', hydrateState);
})();
