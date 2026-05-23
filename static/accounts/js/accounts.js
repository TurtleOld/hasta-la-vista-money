/**
 * Accounts dashboard — Alpine.js (CSP build) components.
 *
 * Alpine CSP build only allows identifier expressions in templates:
 * no method calls with arguments, no ternaries, no operators.
 * All conditional values are exposed as getters/computed properties.
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
      `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
      `T${pad(date.getHours())}:${pad(date.getMinutes())}`
    );
  }

  document.addEventListener('alpine:init', () => {
    /* ── Store: hide-balance ─────────────────────────────────── */
    window.Alpine.store('accountsUi', {
      hideBalance: safeGet(STORAGE_KEY, 'false') === 'true',

      get balanceVisible() {
        return !this.hideBalance;
      },

      init() {
        this.applyClass();
      },

      toggle() {
        this.hideBalance = !this.hideBalance;
        safeSet(STORAGE_KEY, this.hideBalance ? 'true' : 'false');
        this.applyClass();
      },

      applyClass() {
        const root = document.querySelector('.accounts-app');
        if (!root) return;
        root.classList.toggle('is-hidden', this.hideBalance);
      },
    });

    /* ── Swipe card ──────────────────────────────────────────── */
    window.Alpine.data('swipeCard', () => ({
      x: 0,
      startX: 0,
      swiping: false,
      reveal: 192,
      pointerId: null,

      onDown(event) {
        this.startX = event.clientX - this.x;
        this.swiping = true;
        this.pointerId = event.pointerId;
        try {
          event.currentTarget.setPointerCapture(event.pointerId);
        } catch (_err) {
          /* ignore */
        }
      },

      onMove(event) {
        if (!this.swiping) return;
        const next = event.clientX - this.startX;
        if (next > 0) {
          this.x = 0;
          return;
        }
        if (next < -this.reveal) {
          this.x = -this.reveal;
          return;
        }
        this.x = next;
      },

      onUp(event) {
        if (!this.swiping) return;
        this.swiping = false;
        try {
          event.currentTarget.releasePointerCapture(this.pointerId);
        } catch (_err) {
          /* ignore */
        }
        this.pointerId = null;
        if (this.x < -this.reveal / 2) {
          this.x = -this.reveal;
        } else {
          this.x = 0;
        }
      },

      close() {
        this.x = 0;
      },
    }));

    /* ── Quick Add drawer ────────────────────────────────────── */
    window.Alpine.data('quickAdd', () => ({
      open: false,
      submitting: false,
      type: 'expense',
      amount: '',
      accountId: '',
      categoryId: '',
      incomeCategories: [],
      expenseCategories: [],
      createUrl: '',
      csrfToken: '',

      init() {
        const config = window.HLVM_QUICK_ADD_CONFIG || {};
        this.incomeCategories = config.incomeCategories || [];
        this.expenseCategories = config.expenseCategories || [];
        this.createUrl = config.createUrl || '';
        this.csrfToken = config.csrfToken || '';
        this.accountId = config.defaultAccount || '';
        this.syncCategory();
        console.log('[quickAdd] init done. open=', this.open, 'accountId=', this.accountId, 'categoryId=', this.categoryId);
      },

      toggle() {
        console.log('[quickAdd] toggle BEFORE: open=', this.open);
        this.open = !this.open;
        console.log('[quickAdd] toggle AFTER: open=', this.open);
        if (this.open) {
          this.syncCategory();
        }
      },

      closeDrawer() {
        this.open = false;
      },

      handleOutside() {
        if (this.open) this.open = false;
      },

      setExpense() {
        this.type = 'expense';
        this.syncCategory();
      },

      setIncome() {
        this.type = 'income';
        this.syncCategory();
      },

      onAmountInput(event) {
        const cleaned = (event.target.value || '').replace(/[^\d]/g, '');
        this.amount = cleaned;
        event.target.value = cleaned;
      },

      syncCategory() {
        const list = this.type === 'income'
          ? this.incomeCategories
          : this.expenseCategories;
        if (!list.length) {
          this.categoryId = '';
          return;
        }
        const match = list.find(
          (c) => String(c.id) === String(this.categoryId),
        );
        if (!match) {
          this.categoryId = String(list[0].id);
        }
      },

      async submit(event) {
        event.preventDefault();
        if (this.submitDisabled) return;
        this.submitting = true;

        const formData = new FormData();
        formData.append('operation_type', this.type);
        formData.append('amount', this.amount);
        formData.append('account', this.accountId);
        formData.append('category', this.categoryId);
        formData.append('date', formatLocalDateTime(new Date()));

        try {
          const response = await fetch(this.createUrl, {
            method: 'POST',
            headers: {
              'X-CSRFToken': this.csrfToken,
              'X-Requested-With': 'XMLHttpRequest',
              'HX-Request': 'true',
            },
            body: formData,
            credentials: 'same-origin',
          });

          if (response.ok || response.redirected) {
            const sign = this.type === 'income' ? '+' : '−';
            window.dispatchEvent(
              new CustomEvent('accounts-toast', {
                detail: { message: `${sign}${this.amount} ₽` },
              }),
            );
            this.amount = '';
            this.open = false;
            window.setTimeout(() => window.location.reload(), 600);
          } else {
            window.dispatchEvent(
              new CustomEvent('accounts-toast', {
                detail: { message: 'Ошибка при сохранении', error: true },
              }),
            );
          }
        } catch (_err) {
          window.dispatchEvent(
            new CustomEvent('accounts-toast', {
              detail: { message: 'Сеть недоступна', error: true },
            }),
          );
        } finally {
          this.submitting = false;
        }
      },
    }));

    /* ── Toast ──────────────────────────────────────────────── */
    window.Alpine.data('accountsToast', () => ({
      message: '',
      visible: false,
      error: false,
      timer: null,

      init() {
        window.addEventListener('accounts-toast', (event) => {
          this.show(event.detail || {});
        });
      },

      show(detail) {
        this.message = detail.message || '';
        this.error = Boolean(detail.error);
        this.visible = true;
        if (this.timer) window.clearTimeout(this.timer);
        this.timer = window.setTimeout(() => {
          this.visible = false;
        }, 2400);
      },
    }));

    /* ── Re-init balance-trend chart + hide-balance class after HTMX swap ─ */
    document.addEventListener('htmx:afterSwap', () => {
      if (window.BalanceTrendWidget && typeof window.BalanceTrendWidget.init === 'function') {
        window.BalanceTrendWidget.init();
      }
      const store = window.Alpine && window.Alpine.store('accountsUi');
      if (store && typeof store.applyClass === 'function') {
        store.applyClass();
      }
    });

    /* ── Group chips: toggle is-active on click (HTMX swaps content, not chips) ─ */
    document.addEventListener('click', (event) => {
      const chip = event.target.closest('[data-group-chip]');
      if (!chip) return;
      const container = chip.closest('.accounts-group-chips');
      if (!container) return;
      container.querySelectorAll('[data-group-chip]').forEach((btn) => {
        btn.classList.toggle('is-active', btn === chip);
      });
    });

  });
})();
