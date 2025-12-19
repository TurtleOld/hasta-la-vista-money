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
        const cookieName = String(name);
        const cookies = document.cookie.split(';');
        for (const cookieItem of cookies) {
            const cookie = cookieItem.trim();
            if (cookie.startsWith(cookieName + '=')) {
                return decodeURIComponent(cookie.substring(cookieName.length + 1));
            }
        }
        return '';
    }

    function getCsrfToken() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    function showToast(message, type) {
        const alertClass = type === 'success' ? 'alert-success' : (type === 'error' ? 'alert-danger' : 'alert-info');
        const alert = document.createElement('div');
        alert.className = 'alert ' + alertClass + ' alert-dismissible fade show position-fixed budget-toast';

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

        const performFetch = (targetUrl) => {
            if (!isSafeUrl(targetUrl) || !isWhitelistedUrl(targetUrl)) {
                return Promise.reject(new Error('URL не разрешён'));
            }
            return fetch(targetUrl, opts);
        };

        return performFetch(url).then(resp => {
            if (resp.status === 401 && shouldRetry) {
                return refreshToken().then(newAccess => {
                    if (newAccess) {
                        opts.headers['Authorization'] = 'Bearer ' + newAccess;
                    }
                    return performFetch(url);
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
        wrapper.className = 'budget-toolbar-wrapper';

        const left = document.createElement('div');
        left.className = 'budget-toolbar-left';
        left.textContent = 'Период:';

        const select = document.createElement('select');
        select.className = 'budget-toolbar-select';

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
        right.className = 'budget-toolbar-right';

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
        scroll.className = 'budget-table-scroll-container';

        const inner = document.createElement('div');
        inner.className = 'budget-table-inner';
        scroll.appendChild(inner);
        host.appendChild(scroll);
        return inner;
    }

    function buildTable(inner, type, months, rows) {
        const table = document.createElement('table');
        table.className = 'budget-table';

        const thead = document.createElement('thead');
        const tr1 = document.createElement('tr');
        const tr2 = document.createElement('tr');

        const thCat = document.createElement('th');
        thCat.rowSpan = 2;
        thCat.textContent = 'Категория';
        thCat.className = 'budget-table-header-category';
        tr1.appendChild(thCat);

        months.forEach(m => {
            const th = document.createElement('th');
            th.colSpan = 2;
            th.textContent = monthLabel(m);
            th.className = 'budget-table-header-month';
            tr1.appendChild(th);

            const thFact = document.createElement('th');
            thFact.textContent = 'Факт';
            thFact.className = 'budget-table-header-fact';
            tr2.appendChild(thFact);

            const thPlan = document.createElement('th');
            thPlan.textContent = 'План';
            thPlan.className = 'budget-table-header-plan';
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
            tdCat.className = 'budget-table-cell-category';
            tr.appendChild(tdCat);

            months.forEach(m => {
                const fact = row.facts.get(m) || 0;
                const plan = row.plans.get(m) || 0;

                const t = totals.get(m);
                t.fact += fact;
                t.plan += plan;

                const tdFact = document.createElement('td');
                tdFact.textContent = formatNumber(fact);
                tdFact.className = 'budget-table-cell-fact';
                tr.appendChild(tdFact);

                const tdPlan = document.createElement('td');
                tdPlan.className = 'budget-table-cell-plan';

                const input = document.createElement('input');
                input.type = 'number';
                input.inputMode = 'decimal';
                input.value = plan ? String(plan) : '';
                input.className = 'budget-table-input';

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
        tdTotalLabel.className = 'budget-table-total-label';
        trTotal.appendChild(tdTotalLabel);

        months.forEach(m => {
            const t = totals.get(m);

            const tdTFact = document.createElement('td');
            tdTFact.textContent = formatNumber(t.fact);
            tdTFact.className = 'budget-table-total-cell';
            trTotal.appendChild(tdTFact);

            const tdTPlan = document.createElement('td');
            tdTPlan.textContent = formatNumber(t.plan);
            tdTPlan.className = 'budget-table-total-cell';
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
        if (!isSafeUrl(apiUrl) || !isWhitelistedUrl(apiUrl)) {
            container.innerHTML = '<div class="budget-message-error">Неверный URL API</div>';
            return;
        }

        const loader = document.createElement('div');
        loader.className = 'budget-message';
        loader.textContent = 'Загрузка...';
        container.appendChild(loader);

        const safeApiUrl = apiUrl;
        safeFetchJson(safeApiUrl).then(data => {
            container.innerHTML = '';

            const parsed = parseApiData(data);
            if (!parsed.months.length || !parsed.rows.length) {
                const empty = document.createElement('div');
                empty.className = 'budget-message';
                empty.textContent = 'Нет данных для отображения';
                container.appendChild(empty);
                return;
            }

            const tableHost = document.createElement('div');

            buildToolbar(container, parsed.months, count => {
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
            err.className = 'budget-message-error';
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
