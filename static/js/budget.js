window.BUDGET_SCRIPT_EXECUTED = false;

(function () {
    'use strict';

    window.BUDGET_SCRIPT_EXECUTED = true;

    const API = {
        expense: '/api/budget/expenses/',
        income: '/api/budget/incomes/',
    };

    const TABLES = [
        { id: 'expense-budget-table', type: 'expense', api: API.expense },
        { id: 'income-budget-table', type: 'income', api: API.income },
    ];

    const ALLOWED_API_PATHS = [
        '/api/budget/expenses/',
        '/api/budget/incomes/',
        '/budget/save-planning/',
    ];

    function isSafeUrl(url) {
        return typeof url === 'string' && /^\/[a-zA-Z0-9/_\-.]*$/.test(url);
    }

    function isWhitelistedUrl(url) {
        return ALLOWED_API_PATHS.includes(url);
    }

    function getCookie(name) {
        const escaped = String(name).replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
        const match = document.cookie.match(new RegExp('(?:^|; )' + escaped + '=([^;]*)'));
        return match ? decodeURIComponent(match[1]) : '';
    }

    function getCsrfToken() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    function showToast(message, type) {
        const alertClass = type === 'success' ? 'alert-success' : (type === 'error' ? 'alert-danger' : 'alert-info');
        const alert = document.createElement('div');
        alert.className = 'alert ' + alertClass + ' alert-dismissible fade show position-fixed';
        alert.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';

        const span = document.createElement('span');
        span.textContent = message;
        alert.appendChild(span);

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'btn-close';
        closeBtn.setAttribute('data-bs-dismiss', 'alert');
        alert.appendChild(closeBtn);

        document.body.appendChild(alert);
        setTimeout(() => {
            if (alert.parentNode) {
                alert.remove();
            }
        }, 3500);
    }

    function refreshToken() {
        const refresh = getCookie('refresh_token');
        if (!refresh) {
            return Promise.reject(new Error('No refresh token'));
        }

        return fetch('/api/token/refresh/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
        }).then(resp => {
            if (!resp.ok) {
                throw new Error('Refresh failed');
            }
            return resp.json();
        }).then(data => {
            if (!data || !data.success) {
                throw new Error('Refresh failed');
            }
            return getCookie('access_token');
        });
    }

    function safeFetchJson(url, options, retry) {
        const shouldRetry = retry !== false;

        if (!isSafeUrl(url) || !isWhitelistedUrl(url)) {
            return Promise.reject(new Error('URL не разрешён'));
        }

        const opts = options ? { ...options } : {};
        opts.headers = opts.headers ? { ...opts.headers } : {};
        opts.credentials = 'include';
        opts.headers['Accept'] = 'application/json';
        opts.headers['X-Requested-With'] = 'XMLHttpRequest';

        const jwt = getCookie('access_token');
        if (jwt) {
            opts.headers['Authorization'] = 'Bearer ' + jwt;
        }

        return fetch(url, opts).then(resp => {
            if (resp.status === 401 && shouldRetry) {
                return refreshToken().then(newAccess => {
                    if (newAccess) {
                        opts.headers['Authorization'] = 'Bearer ' + newAccess;
                    }
                    return fetch(url, opts);
                });
            }
            return resp;
        }).then(resp => {
            const contentType = resp.headers.get('Content-Type') || '';
            if (!resp.ok) {
                return resp.text().then(text => {
                    throw new Error('API error: ' + resp.status + ' - ' + text.slice(0, 200));
                });
            }
            if (!contentType.includes('application/json')) {
                return resp.text().then(text => {
                    throw new Error('API returned non-JSON: ' + contentType + ' ' + text.slice(0, 100));
                });
            }
            return resp.json();
        });
    }

    function formatNumber(value) {
        const num = typeof value === 'number' ? value : parseFloat(String(value));
        if (!isFinite(num) || num === 0) {
            return '—';
        }
        return num.toLocaleString('ru-RU', { maximumFractionDigits: 0 });
    }

    function monthLabel(isoDate) {
        const d = new Date(isoDate);
        if (Number.isNaN(d.getTime())) {
            return String(isoDate);
        }
        return d.toLocaleString('ru-RU', { month: 'long', year: 'numeric' });
    }

    function normalizeMonths(months) {
        const parsed = months
            .map(m => String(m))
            .filter(m => m.length > 0);

        parsed.sort((a, b) => {
            const da = new Date(a).getTime();
            const db = new Date(b).getTime();
            return da - db;
        });

        return parsed;
    }

    function buildToolbar(container, months, onChange) {
        const wrapper = document.createElement('div');
        wrapper.className = 'flex flex-wrap items-center justify-between gap-3 mb-4';

        const left = document.createElement('div');
        left.className = 'text-sm text-gray-600 dark:text-gray-300';
        left.textContent = 'Период:';

        const select = document.createElement('select');
        select.className = 'ml-2 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100';

        const total = months.length;
        const options = [total, 6, 12, 24];
        const unique = Array.from(new Set(options.filter(v => v <= total)));
        unique.sort((a, b) => a - b);

        unique.forEach(v => {
            const opt = document.createElement('option');
            opt.value = String(v);
            opt.textContent = v === total ? 'Все (' + total + ')' : String(v);
            select.appendChild(opt);
        });

        select.value = String(total);

        const right = document.createElement('div');
        right.className = 'text-xs text-gray-500 dark:text-gray-400';

        function updateRight(val) {
            right.textContent = 'Показано месяцев: ' + val + ' из ' + total;
        }

        updateRight(parseInt(select.value, 10));

        select.addEventListener('change', () => {
            const val = parseInt(select.value, 10);
            updateRight(val);
            onChange(val);
        });

        left.appendChild(select);
        wrapper.appendChild(left);
        wrapper.appendChild(right);

        container.appendChild(wrapper);

        return { getValue: () => parseInt(select.value, 10) };
    }

    function ensureScrollableTableContainer(host) {
        host.innerHTML = '';
        const scroll = document.createElement('div');
        scroll.className = 'w-full overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700';
        scroll.style.maxHeight = 'calc(100vh - 320px)';

        const inner = document.createElement('div');
        inner.className = 'min-w-max';
        scroll.appendChild(inner);
        host.appendChild(scroll);
        return inner;
    }

    function buildTable(inner, type, months, rows) {
        const table = document.createElement('table');
        table.className = 'w-full text-sm text-gray-900 dark:text-gray-100 border-separate border-spacing-0';

        const thead = document.createElement('thead');
        const tr1 = document.createElement('tr');
        const tr2 = document.createElement('tr');

        const thCat = document.createElement('th');
        thCat.rowSpan = 2;
        thCat.textContent = 'Категория';
        thCat.className = 'sticky left-0 z-20 bg-white dark:bg-gray-800 px-3 py-2 text-left font-semibold border-b border-r border-gray-200 dark:border-gray-700';
        thCat.style.minWidth = '220px';
        tr1.appendChild(thCat);

        months.forEach(m => {
            const th = document.createElement('th');
            th.colSpan = 2;
            th.textContent = monthLabel(m);
            th.className = 'px-3 py-2 text-center font-semibold bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700';
            tr1.appendChild(th);

            const thFact = document.createElement('th');
            thFact.textContent = 'Факт';
            thFact.className = 'px-3 py-2 text-left font-medium bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700';
            thFact.style.minWidth = '110px';
            tr2.appendChild(thFact);

            const thPlan = document.createElement('th');
            thPlan.textContent = 'План';
            thPlan.className = 'px-3 py-2 text-left font-medium bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700';
            thPlan.style.minWidth = '110px';
            tr2.appendChild(thPlan);
        });

        thead.appendChild(tr1);
        thead.appendChild(tr2);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');

        const totals = new Map();
        months.forEach(m => {
            totals.set(m, { fact: 0, plan: 0 });
        });

        rows.forEach(row => {
            const tr = document.createElement('tr');

            const tdCat = document.createElement('td');
            tdCat.textContent = row.category;
            tdCat.className = 'sticky left-0 z-10 bg-white dark:bg-gray-800 px-3 py-2 border-b border-r border-gray-200 dark:border-gray-700 font-medium';
            tr.appendChild(tdCat);

            months.forEach(m => {
                const fact = row.facts.get(m) || 0;
                const plan = row.plans.get(m) || 0;

                const t = totals.get(m);
                t.fact += fact;
                t.plan += plan;

                const tdFact = document.createElement('td');
                tdFact.textContent = formatNumber(fact);
                tdFact.className = 'px-3 py-2 border-b border-gray-200 dark:border-gray-700 text-right text-gray-700 dark:text-gray-200';
                tr.appendChild(tdFact);

                const tdPlan = document.createElement('td');
                tdPlan.className = 'px-3 py-2 border-b border-gray-200 dark:border-gray-700';

                const input = document.createElement('input');
                input.type = 'number';
                input.inputMode = 'decimal';
                input.value = plan ? String(plan) : '';
                input.className = 'w-24 px-2 py-1 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-right';

                input.addEventListener('change', () => {
                    const raw = input.value;
                    const amount = raw === '' ? 0 : parseFloat(raw);
                    if (!isFinite(amount) || amount < 0) {
                        showToast('Некорректное значение плана', 'error');
                        input.value = plan ? String(plan) : '';
                        return;
                    }

                    safeFetchJson('/budget/save-planning/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest',
                            'X-CSRFToken': getCsrfToken(),
                        },
                        body: JSON.stringify({
                            category_id: row.category_id,
                            month: m,
                            amount: amount,
                            type: type,
                        }),
                    }).then(data => {
                        if (!data || !data.success) {
                            throw new Error('Save failed');
                        }

                        const prev = row.plans.get(m) || 0;
                        row.plans.set(m, amount);

                        const t2 = totals.get(m);
                        t2.plan = t2.plan - prev + amount;

                        const footerCell = table.querySelector('[data-total-plan="' + m + '"]');
                        if (footerCell) {
                            footerCell.textContent = formatNumber(t2.plan);
                        }

                        showToast('План сохранён', 'success');
                    }).catch(() => {
                        showToast('Ошибка сохранения плана', 'error');
                        input.value = plan ? String(plan) : '';
                    });
                });

                tdPlan.appendChild(input);
                tr.appendChild(tdPlan);
            });

            tbody.appendChild(tr);
        });

        const trTotal = document.createElement('tr');

        const tdTotalLabel = document.createElement('td');
        tdTotalLabel.textContent = 'Итого';
        tdTotalLabel.className = 'sticky left-0 z-20 bg-white dark:bg-gray-800 px-3 py-2 border-t border-r border-gray-200 dark:border-gray-700 font-semibold';
        trTotal.appendChild(tdTotalLabel);

        months.forEach(m => {
            const t = totals.get(m);

            const tdTFact = document.createElement('td');
            tdTFact.textContent = formatNumber(t.fact);
            tdTFact.className = 'px-3 py-2 border-t border-gray-200 dark:border-gray-700 text-right font-semibold';
            trTotal.appendChild(tdTFact);

            const tdTPlan = document.createElement('td');
            tdTPlan.textContent = formatNumber(t.plan);
            tdTPlan.className = 'px-3 py-2 border-t border-gray-200 dark:border-gray-700 text-right font-semibold';
            tdTPlan.setAttribute('data-total-plan', m);
            trTotal.appendChild(tdTPlan);
        });

        tbody.appendChild(trTotal);
        table.appendChild(tbody);

        inner.appendChild(table);
    }

    function parseApiData(data) {
        const months = normalizeMonths(data.months || []);
        const rows = Array.isArray(data.data) ? data.data : [];

        const parsedRows = rows.map(r => {
            const facts = new Map();
            const plans = new Map();

            months.forEach(m => {
                const f = r['fact_' + m];
                const p = r['plan_' + m];

                const fn = f === undefined || f === null || f === '' ? 0 : (parseFloat(String(f)) || 0);
                const pn = p === undefined || p === null || p === '' ? 0 : (parseFloat(String(p)) || 0);

                facts.set(m, fn);
                plans.set(m, pn);
            });

            return {
                category: String(r.category || ''),
                category_id: r.category_id,
                facts: facts,
                plans: plans,
            };
        });

        return { months, rows: parsedRows };
    }

    function initMatrixTable(container, type, apiUrl) {
        const loader = document.createElement('div');
        loader.className = 'text-sm text-gray-600 dark:text-gray-300';
        loader.textContent = 'Загрузка...';
        container.appendChild(loader);

        safeFetchJson(apiUrl).then(data => {
            container.innerHTML = '';

            const parsed = parseApiData(data);
            if (!parsed.months.length || !parsed.rows.length) {
                const empty = document.createElement('div');
                empty.className = 'text-sm text-gray-600 dark:text-gray-300';
                empty.textContent = 'Нет данных для отображения';
                container.appendChild(empty);
                return;
            }

            const tableHost = document.createElement('div');

            const toolbar = buildToolbar(container, parsed.months, count => {
                const inner = ensureScrollableTableContainer(tableHost);
                const visibleMonths = parsed.months.slice(-count);
                buildTable(inner, type, visibleMonths, parsed.rows);
            });

            container.appendChild(tableHost);

            const inner = ensureScrollableTableContainer(tableHost);
            buildTable(inner, type, parsed.months, parsed.rows);
        }).catch(() => {
            container.innerHTML = '';
            const err = document.createElement('div');
            err.className = 'text-sm text-red-600 dark:text-red-400';
            err.textContent = 'Ошибка загрузки данных бюджета';
            container.appendChild(err);
        });
    }

    function start() {
        TABLES.forEach(t => {
            const container = document.getElementById(t.id);
            if (!container) {
                return;
            }
            initMatrixTable(container, t.type, t.api);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
