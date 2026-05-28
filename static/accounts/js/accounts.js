/**
 * Accounts dashboard — vanilla JS interactions.
 *
 * Alpine.js CSP build was unreliable for state binding here (methods on
 * stores receive a non-reactive `this`, so writes never reach the proxy
 * Alpine reads from in templates). To keep things working everywhere we
 * drive the UI through plain DOM classes and a small module-scoped state
 * object. Pages no longer need Alpine for this dashboard at all.
 */
(function () {
  const STORAGE_KEY = 'hlvm.accounts.hideBalance';

  function safeGet(key, fallback) {
    try {
      return window.localStorage.getItem(key) ?? fallback;
    } catch (_err) {
      return fallback;
    }
  }

  function safeSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (_err) {
      /* ignore */
    }
  }

  function pad(n) {
    return String(n).padStart(2, '0');
  }

  function formatLocalDateTime(date) {
    return (
      pad(date.getFullYear()) + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) +
      'T' + pad(date.getHours()) + ':' + pad(date.getMinutes())
    );
  }

  /* ──────────────────────────────────────────────────────────────
   * Hide-balance toggle
   * ────────────────────────────────────────────────────────────── */
  const balanceState = {
    hidden: safeGet(STORAGE_KEY, 'false') === 'true',
  };

  function applyHideBalance() {
    const root = document.querySelector('.accounts-app');
    if (!root) return;
    root.classList.toggle('is-hidden', balanceState.hidden);
    document.querySelectorAll('[data-eye-show-when-visible]').forEach((el) => {
      el.classList.toggle('is-hidden-icon', balanceState.hidden);
    });
    document.querySelectorAll('[data-eye-show-when-hidden]').forEach((el) => {
      el.classList.toggle('is-hidden-icon', !balanceState.hidden);
    });
  }

  function toggleHideBalance() {
    balanceState.hidden = !balanceState.hidden;
    safeSet(STORAGE_KEY, balanceState.hidden ? 'true' : 'false');
    applyHideBalance();
  }

  /* ──────────────────────────────────────────────────────────────
   * Quick-add drawer
   * ────────────────────────────────────────────────────────────── */
  const drawerState = {
    open: false,
    submitting: false,
    type: 'expense',
    accountId: '',
    categoryId: '',
    amount: '',
    incomeCategories: [],
    expenseCategories: [],
    createUrl: '',
    quickCategoryUrl: '',
    csrfToken: '',
    catFormOpen: false,
    catCreating: false,
  };

  function fab() { return document.querySelector('.accounts-fab'); }
  function drawer() { return document.querySelector('.accounts-drawer'); }
  function drawerAmountInput() { return document.querySelector('[data-qa-amount]'); }
  function drawerAccountSelect() { return document.querySelector('[data-qa-account]'); }
  function drawerCategorySelect() { return document.querySelector('[data-qa-category]'); }
  function drawerSubmit() { return document.querySelector('[data-qa-submit]'); }
  function drawerSubmitTxtIdle() { return document.querySelector('[data-qa-submit-idle]'); }
  function drawerSubmitTxtBusy() { return document.querySelector('[data-qa-submit-busy]'); }
  function drawerFabLabel() { return document.querySelector('[data-qa-fab-label]'); }
  function drawerTabExpense() { return document.querySelector('[data-qa-tab="expense"]'); }
  function drawerTabIncome() { return document.querySelector('[data-qa-tab="income"]'); }
  function drawerCatForm() { return document.querySelector('[data-qa-cat-form]'); }
  function drawerCatNameInput() { return document.querySelector('[data-qa-cat-name]'); }
  function drawerCatSaveBtn() { return document.querySelector('[data-qa-cat-save]'); }

  function applyDrawerState() {
    const fabEl = fab();
    const drawerEl = drawer();
    if (fabEl) fabEl.setAttribute('data-open', drawerState.open ? '1' : '0');
    if (drawerEl) drawerEl.setAttribute('data-open', drawerState.open ? '1' : '0');

    const labelEl = drawerFabLabel();
    if (labelEl) labelEl.classList.toggle('is-hidden-icon', drawerState.open);

    const tabE = drawerTabExpense();
    const tabI = drawerTabIncome();
    if (tabE) tabE.classList.toggle('on', drawerState.type === 'expense');
    if (tabI) tabI.classList.toggle('on', drawerState.type === 'income');

    const submitEl = drawerSubmit();
    if (submitEl) {
      submitEl.disabled = (
        drawerState.submitting ||
        !drawerState.amount ||
        !drawerState.accountId ||
        !drawerState.categoryId
      );
    }
    const idleTxt = drawerSubmitTxtIdle();
    const busyTxt = drawerSubmitTxtBusy();
    if (idleTxt) idleTxt.classList.toggle('is-hidden-icon', drawerState.submitting);
    if (busyTxt) busyTxt.classList.toggle('is-hidden-icon', !drawerState.submitting);

    const catForm = drawerCatForm();
    if (catForm) catForm.classList.toggle('is-hidden-icon', !drawerState.catFormOpen);
    const saveBtn = drawerCatSaveBtn();
    if (saveBtn) saveBtn.disabled = drawerState.catCreating;
  }

  function openCatForm() {
    drawerState.catFormOpen = true;
    applyDrawerState();
    const input = drawerCatNameInput();
    if (input) {
      input.value = '';
      input.focus();
    }
  }

  function closeCatForm() {
    drawerState.catFormOpen = false;
    drawerState.catCreating = false;
    applyDrawerState();
  }

  async function quickCreateCategory() {
    if (drawerState.catCreating) return;
    const input = drawerCatNameInput();
    if (!input) return;
    const name = (input.value || '').trim();
    if (!name) {
      showToast({ message: 'Введите название', error: true });
      return;
    }
    drawerState.catCreating = true;
    applyDrawerState();

    const formData = new FormData();
    formData.append('type', drawerState.type);
    formData.append('name', name);

    try {
      const response = await fetch(drawerState.quickCategoryUrl, {
        method: 'POST',
        headers: {
          'X-CSRFToken': drawerState.csrfToken,
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: formData,
        credentials: 'same-origin',
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        showToast({ message: data.error || 'Ошибка', error: true });
        drawerState.catCreating = false;
        applyDrawerState();
        return;
      }
      const entry = { id: data.id, name: data.name };
      const list = drawerState.type === 'income'
        ? drawerState.incomeCategories
        : drawerState.expenseCategories;
      const existing = list.find((c) => String(c.id) === String(entry.id));
      if (!existing) list.unshift(entry);
      drawerState.categoryId = String(entry.id);
      drawerState.catFormOpen = false;
      drawerState.catCreating = false;
      syncDrawerCategorySelect();
      showToast({ message: 'Категория «' + entry.name + '» добавлена' });
    } catch (_err) {
      showToast({ message: 'Сеть недоступна', error: true });
      drawerState.catCreating = false;
      applyDrawerState();
    }
  }

  function syncDrawerCategorySelect() {
    const select = drawerCategorySelect();
    if (!select) return;
    const list = drawerState.type === 'income'
      ? drawerState.incomeCategories
      : drawerState.expenseCategories;
    select.innerHTML = '';
    list.forEach((cat) => {
      const opt = document.createElement('option');
      opt.value = String(cat.id);
      opt.textContent = cat.name;
      select.appendChild(opt);
    });
    if (!list.length) {
      drawerState.categoryId = '';
    } else {
      const match = list.find((c) => String(c.id) === String(drawerState.categoryId));
      drawerState.categoryId = match ? String(match.id) : String(list[0].id);
      select.value = drawerState.categoryId;
    }
    applyDrawerState();
  }

  function openDrawer() {
    drawerState.open = true;
    syncDrawerCategorySelect();
    applyDrawerState();
  }

  function closeDrawer() {
    drawerState.open = false;
    applyDrawerState();
  }

  function setDrawerType(next) {
    drawerState.type = next;
    drawerState.catFormOpen = false;
    drawerState.catCreating = false;
    syncDrawerCategorySelect();
  }

  function setDrawerAmount(value) {
    const cleaned = String(value || '').replace(/[^\d]/g, '');
    drawerState.amount = cleaned;
    const input = drawerAmountInput();
    if (input && input.value !== cleaned) input.value = cleaned;
    applyDrawerState();
  }

  /* ──────────────────────────────────────────────────────────────
   * Toast
   * ────────────────────────────────────────────────────────────── */
  const toastState = { timer: null };

  function toastEl() { return document.querySelector('.accounts-toast'); }

  function showToast(detail) {
    const el = toastEl();
    if (!el) return;
    el.querySelector('[data-toast-message]').textContent = detail.message || '';
    el.classList.toggle('is-error', Boolean(detail.error));
    el.setAttribute('data-on', '1');
    if (toastState.timer) window.clearTimeout(toastState.timer);
    toastState.timer = window.setTimeout(() => {
      el.setAttribute('data-on', '0');
    }, 2400);
  }

  /* ──────────────────────────────────────────────────────────────
   * Submit
   * ────────────────────────────────────────────────────────────── */
  async function submitDrawer(event) {
    event.preventDefault();
    if (
      drawerState.submitting ||
      !drawerState.amount ||
      !drawerState.accountId ||
      !drawerState.categoryId
    ) return;
    drawerState.submitting = true;
    applyDrawerState();

    const formData = new FormData();
    formData.append('operation_type', drawerState.type);
    formData.append('amount', drawerState.amount);
    formData.append('account', drawerState.accountId);
    formData.append('category', drawerState.categoryId);
    formData.append('date', formatLocalDateTime(new Date()));

    try {
      const response = await fetch(drawerState.createUrl, {
        method: 'POST',
        headers: {
          'X-CSRFToken': drawerState.csrfToken,
          'X-Requested-With': 'XMLHttpRequest',
          'HX-Request': 'true',
        },
        body: formData,
        credentials: 'same-origin',
      });

      if (response.ok || response.redirected) {
        const sign = drawerState.type === 'income' ? '+' : '−';
        showToast({ message: sign + drawerState.amount + ' ₽' });
        drawerState.amount = '';
        const input = drawerAmountInput();
        if (input) input.value = '';
        drawerState.open = false;
        window.setTimeout(() => window.location.reload(), 600);
      } else {
        showToast({ message: 'Ошибка при сохранении', error: true });
      }
    } catch (_err) {
      showToast({ message: 'Сеть недоступна', error: true });
    } finally {
      drawerState.submitting = false;
      applyDrawerState();
    }
  }

  /* ──────────────────────────────────────────────────────────────
   * Init
   * ────────────────────────────────────────────────────────────── */
  function init() {
    /* Hide-balance */
    applyHideBalance();

    /* Drawer config */
    const config = window.HLVM_QUICK_ADD_CONFIG || {};
    drawerState.incomeCategories = config.incomeCategories || [];
    drawerState.expenseCategories = config.expenseCategories || [];
    drawerState.createUrl = config.createUrl || '';
    drawerState.quickCategoryUrl = config.quickCategoryUrl || '';
    drawerState.csrfToken = config.csrfToken || '';
    drawerState.accountId = config.defaultAccount || '';

    const accountSelect = drawerAccountSelect();
    if (accountSelect) {
      accountSelect.value = drawerState.accountId;
      accountSelect.addEventListener('change', () => {
        drawerState.accountId = accountSelect.value;
        applyDrawerState();
      });
    }

    syncDrawerCategorySelect();

    const categorySelect = drawerCategorySelect();
    if (categorySelect) {
      categorySelect.addEventListener('change', () => {
        drawerState.categoryId = categorySelect.value;
        applyDrawerState();
      });
    }

    const amountInput = drawerAmountInput();
    if (amountInput) {
      amountInput.addEventListener('input', (event) => setDrawerAmount(event.target.value));
    }

    const form = document.querySelector('[data-qa-form]');
    if (form) form.addEventListener('submit', submitDrawer);

    const catName = drawerCatNameInput();
    if (catName) {
      catName.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          quickCreateCategory();
        } else if (event.key === 'Escape') {
          event.preventDefault();
          closeCatForm();
        }
      });
    }

    applyDrawerState();

    /* Listen for global accounts-toast events (still used elsewhere). */
    window.addEventListener('accounts-toast', (event) => {
      showToast(event.detail || {});
    });

    /* HTMX hooks. */
    document.addEventListener('htmx:beforeSwap', (event) => {
      /* Destroy the chart bound to the soon-to-be-removed canvas before
         HTMX detaches it; otherwise Chart.js keeps a stale reference and
         the next render throws "Canvas is already in use". */
      if (!window.Chart) return;
      const canvas = document.getElementById('balance-trend-chart');
      if (!canvas) return;
      const target = event.detail && event.detail.target;
      if (!target) return;
      const willReplace = (
        target === canvas ||
        target.contains(canvas) ||
        target.id === 'balance-trend-widget'
      );
      if (willReplace) {
        const existing = window.Chart.getChart(canvas);
        if (existing) existing.destroy();
      }
    });

    document.addEventListener('htmx:afterSwap', () => {
      if (window.BalanceTrendWidget && typeof window.BalanceTrendWidget.init === 'function') {
        window.BalanceTrendWidget.init();
      }
      applyHideBalance();
    });

    /* Delegated clicks for FAB, eye, drawer outside, tabs, group chips. */
    document.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;

      const eyeBtn = target.closest('.accounts-eye');
      if (eyeBtn) {
        toggleHideBalance();
        return;
      }

      const fabBtn = target.closest('.accounts-fab');
      if (fabBtn) {
        if (drawerState.open) closeDrawer();
        else openDrawer();
        return;
      }

      const tabBtn = target.closest('[data-qa-tab]');
      if (tabBtn) {
        setDrawerType(tabBtn.getAttribute('data-qa-tab'));
        return;
      }

      if (target.closest('[data-qa-cat-add]')) {
        openCatForm();
        return;
      }
      if (target.closest('[data-qa-cat-cancel]')) {
        closeCatForm();
        return;
      }
      if (target.closest('[data-qa-cat-save]')) {
        quickCreateCategory();
        return;
      }

      const chip = target.closest('[data-group-chip]');
      if (chip) {
        const container = chip.closest('.accounts-group-chips');
        if (container) {
          container.querySelectorAll('[data-group-chip]').forEach((btn) => {
            btn.classList.toggle('is-active', btn === chip);
          });
        }
        return;
      }

      /* Click outside drawer closes it (when open). */
      if (drawerState.open) {
        const drawerEl = drawer();
        if (drawerEl && !drawerEl.contains(target) && !target.closest('.accounts-fab')) {
          closeDrawer();
        }
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
