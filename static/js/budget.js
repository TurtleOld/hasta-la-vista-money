/* global Tabulator */
document.addEventListener('DOMContentLoaded', function () {
    function safeRedirect(url) {
        if (/^\/[a-zA-Z0-9/_\-.]*$/.test(url)) {
            const safeUrl = encodeURI(url);
            window.location.href = safeUrl;  // eslint-disable-line
        } else {
            const loginUrl = encodeURI('/login/');
            window.location.href = loginUrl;  // eslint-disable-line
        }
    }

    const API = {
        expense: '/api/budget/expenses/',
        income: '/api/budget/incomes/'
    };
    const TABLES = [
        { id: 'expense-budget-table', type: 'expense', api: API.expense },
        { id: 'income-budget-table', type: 'income', api: API.income }
    ];
    function getJWT() {
        const m = document.cookie.match(/(?:^|; )access_token=([^;]*)/);
        if (m) return decodeURIComponent(m[1]);
        return '';
    }
    function refreshToken() {
        const m = document.cookie.match(/(?:^|; )refresh_token=([^;]*)/);
        const refresh = m ? decodeURIComponent(m[1]) : null;

        if (!refresh) return Promise.reject('No refresh token');
        const refreshUrl = '/api/token/refresh/';
        return fetch(refreshUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include'
        })
            .then(resp => {
                if (!resp.ok) throw new Error('Refresh failed');
                return resp.json();
            })
            .then(data => {
                if (data.success) {
                    return getJWT();
                }
                throw new Error('No access token in refresh response');
            });
    }
    function isSafeApiUrl(url) {
        return typeof url === 'string' && /^\/[a-zA-Z0-9/_\-.]*$/.test(url);
    }
    const ALLOWED_API_PATHS = [
        '/api/budget/expenses/',
        '/api/budget/incomes/',
        '/budget/save-planning/',
    ];
    function isWhitelistedUrl(url) {
        return ALLOWED_API_PATHS.includes(url);
    }

    function safeFetchExpenses(options, retry = true) {
        return performSafeFetch('/api/budget/expenses/', options, retry);
    }

    function safeFetchIncomes(options, retry = true) {
        return performSafeFetch('/api/budget/incomes/', options, retry);
    }

    function safeFetchSavePlanning(options, retry = true) {
        return performSafeFetch('/budget/save-planning/', options, retry);
    }

    function performSafeFetch(hardcodedUrl, options, retry = true) {
        if (!isSafeApiUrl(hardcodedUrl) || !isWhitelistedUrl(hardcodedUrl)) {
            return Promise.reject(new Error('URL не разрешён'));
        }

        options = options || {};
        options.headers = options.headers || {};
        options.headers['Authorization'] = 'Bearer ' + getJWT();
        options.headers['X-Requested-With'] = 'XMLHttpRequest';
        return fetch(hardcodedUrl, options).then(resp => { // eslint-disable-line
            if (resp.status === 401 && retry) {
                return refreshToken().then(newAccess => {
                    options.headers['Authorization'] = 'Bearer ' + newAccess;
                    return fetch(hardcodedUrl, options); // eslint-disable-line
                });
            }
            return resp;
        });
    }

    function showNotification(message, type = 'info') {
        let alertClass;
        if (type === 'success') {
            alertClass = 'alert-success';
        } else if (type === 'error') {
            alertClass = 'alert-danger';
        } else {
            alertClass = 'alert-info';
        }
        const alert = document.createElement('div');
        alert.className = `alert ${alertClass} alert-dismissible fade show position-fixed`;
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
        setTimeout(() => { if (alert.parentNode) alert.remove(); }, 4000);
    }
    TABLES.forEach(({ id, type, api }) => {
        const container = document.getElementById(id);
        if (!container) return;
        const loader = document.createElement('div');
        loader.className = 'skeleton-loader';
        loader.style.height = '300px';
        container.appendChild(loader);
        if (!isSafeApiUrl(api)) {
            loader.remove();
            showNotification('Ошибка: небезопасный API URL', 'error');
            return;
        }
        (api === '/api/budget/expenses/' ? safeFetchExpenses() : safeFetchIncomes())
            .then(resp => {
                if (!resp.ok) throw new Error('API error');
                return resp.json();
            })
            .then(data => {
                loader.remove();
                if (!Array.isArray(data.data) || !Array.isArray(data.months)) {
                    showNotification('Ошибка загрузки данных', 'error');
                    return;
                }
                const months = data.months;
                const rows = data.data;
                const columns = [
                    {
                        title: 'Категория',
                        field: 'category',
                        headerFilter: 'input',
                        frozen: true,
                        cssClass: 'fw-bold text-start',
                        width: 200,
                        headerSort: true
                    },
                    ...months.map(m => ({
                        title: new Date(m).toLocaleString('ru-RU', { month: 'short', year: 'numeric' }),
                        columns: [
                            {
                                title: 'Факт', field: `fact_${m}`, hozAlign: 'right', cssClass: 'text-muted',
                                formatter: cell => cell.getValue() ? cell.getValue().toLocaleString('ru-RU', { maximumFractionDigits: 2 }) : '—',
                                bottomCalc: 'sum', bottomCalcFormatter: cell => cell.getValue() ? cell.getValue().toLocaleString('ru-RU', { maximumFractionDigits: 2 }) : '—'
                            },
                            {
                                title: 'План', field: `plan_${m}`, hozAlign: 'right', cssClass: 'plan-cell',
                                editor: function (cell, onRendered, success, cancel, editorParams) {
                                    console.log('[EDITOR] cell edit start', cell.getField(), cell.getValue());
                                    var input = document.createElement("input");
                                    input.type = "number";
                                    input.value = cell.getValue();
                                    input.addEventListener("change", function (e) {
                                        const value = Number(e.target.value);
                                        success(value);
                                        const field = cell.getField();
                                        const row = cell.getRow().getData();
                                        const category_id = row.category_id;
                                        const month = field.replace('plan_', '');
                                        safeFetchSavePlanning({
                                            method: 'POST',
                                            headers: {
                                                'Content-Type': 'application/json',
                                                'X-Requested-With': 'XMLHttpRequest',
                                                'X-CSRFToken': (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '',
                                            },
                                            body: JSON.stringify({
                                                category_id,
                                                month,
                                                amount: value,
                                                type: editorParams.type // 'expense' или 'income'
                                            })
                                        })
                                            .then(resp => resp.json())
                                            .then(data => {
                                                console.log('[EDITOR] save response:', data);
                                                if (data.success) {
                                                    showNotification('План успешно сохранён', 'success');
                                                    const fact = row[`fact_${month}`];
                                                    const plan = value;
        const diff = fact - plan;
        const percent = plan ? (fact / plan * 100) : null;
                                                cell.getRow().update({
                                                    [`plan_${month}`]: plan,
                                                    [`diff_${month}`]: diff,
                                                    [`percent_${month}`]: percent
                                                });
                                            } else {
                                                showNotification('Ошибка сохранения плана', 'error');
                                                cell.setValue(cell.getOldValue(), true);
                                            }
                                        })
                                            .catch((err) => {
                                                console.log('[EDITOR] fetch error:', err);
                                                showNotification('Ошибка соединения с сервером', 'error');
                                                cell.setValue(cell.getOldValue(), true);
                                            });
                                    });
                                    input.addEventListener("blur", function () {
                                        cancel();
                                    });
                                    return input;
                                },
                                editorParams: { type: type },
                                editable: true
                            },
                            {
                                title: 'Δ', field: `diff_${m}`, hozAlign: 'right', cssClass: 'fw-bold',
                                formatter: cell => {
                                    const v = cell.getValue();
                                    if (v === null || v === undefined) return '—';
                                    if (v < 0) return `<span class='text-danger'>${v.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}</span>`;
                                    if (v > 0) return `<span class='text-success'>${v.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}</span>`;
                                    return `<span class='text-muted'>0</span>`;
                                },
                                formatterParams: { html: true },
                                bottomCalc: 'sum', bottomCalcFormatter: cell => cell.getValue() ? cell.getValue().toLocaleString('ru-RU', { maximumFractionDigits: 2 }) : '—'
                            },
                            {
                                title: '%', field: `percent_${m}`, hozAlign: 'right', cssClass: 'text-secondary',
                                formatter: cell => cell.getValue() !== null && cell.getValue() !== undefined ? cell.getValue().toFixed(0) + '%' : '—',
                                bottomCalc: function (values, data) {
                                    let sumFact = 0, sumPlan = 0;
                                    for (const d of data) {
                                        const f = d[`fact_${m}`];
                                        const p = d[`plan_${m}`];
                                        if (typeof f === 'number') sumFact += f;
                                        if (typeof p === 'number') sumPlan += p;
                                    }
                                    return sumPlan ? (sumFact / sumPlan * 100).toFixed(0) + '%' : '—';
                                }
                            }
                        ]
                    }))
                ];
                const tabData = rows.map(row => {
                    const obj = { category: row.category, category_id: row.category_id };
                    months.forEach(m => {
                        obj[`fact_${m}`] = row[`fact_${m}`] !== undefined ? row[`fact_${m}`] : 0;
                        obj[`plan_${m}`] = row[`plan_${m}`] !== undefined ? row[`plan_${m}`] : 0;
                        obj[`diff_${m}`] = row[`diff_${m}`] !== undefined ? row[`diff_${m}`] : 0;
                        obj[`percent_${m}`] = row[`percent_${m}`] !== undefined ? row[`percent_${m}`] : null;
                    });
                    return obj;
                });
                new Tabulator(container, {
                    data: tabData,
                    columns: columns,
                    layout: 'fitDataTable',
                    responsiveLayout: false,
                    placeholder: 'Нет данных для отображения',
                    movableColumns: true,
                    resizableRows: false,
                    height: 'auto',
                    locale: 'ru-ru',
                    langs: {
                        'ru-ru': {
                            columns: { category: 'Категория' },
                            data: { loading: 'Загрузка...', error: 'Ошибка загрузки' },
                            pagination: { first: 'Первая', last: 'Последняя', prev: 'Предыдущая', next: 'Следующая' },
                            headerFilters: { default: 'фильтр столбца' }
                        }
                    },
                    groupBy: false,
                    headerSort: true,
                    initialSort: [{ column: 'category', dir: 'asc' }],
                    downloadConfig: {
                        columnGroups: true,
                        rowGroups: false,
                        columnCalcs: true
                    },
                    autoColumns: false,
                    tooltips: true,
                    cellEdited: function (cell) {
                        const field = cell.getField();
                        console.log('[cellEdited] field:', field);
                        if (!field.startsWith('plan_')) return;
                        const value = cell.getValue();
                        const row = cell.getRow().getData();
                        const category_id = row.category_id;
                        const month = field.replace('plan_', '');
                        console.log('[cellEdited] value:', value, 'category_id:', category_id, 'month:', month, 'type:', type);
                        safeFetchSavePlanning({
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-Requested-With': 'XMLHttpRequest',
                                'X-CSRFToken': (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '',
                            },
                            body: JSON.stringify({
                                category_id,
                                month,
                                amount: value,
                                type: type // 'expense' или 'income'
                            })
                        })
                            .then(resp => resp.json())
                            .then(data => {
                                console.log('[cellEdited] response:', data);
                                if (data.success) {
                                    showNotification('План успешно сохранён', 'success');
                                } else {
                                    showNotification('Ошибка сохранения плана', 'error');
                                    cell.setValue(cell.getOldValue(), true);
                                }
                            })
                            .catch((err) => {
                                console.log('[cellEdited] fetch error:', err);
                                showNotification('Ошибка соединения с сервером', 'error');
                                cell.setValue(cell.getOldValue(), true);
                            });
                    }
                });
            })
            .catch(err => {
                loader.remove();
                showNotification('Ошибка загрузки данных', 'error');
                if (err.message === 'Refresh failed' || err.message === 'No refresh token') {
                    safeRedirect('/login/');
                }
            });
    });
    document.addEventListener('tabulator-cellEdited', function(e){
        console.log('[GLOBAL] tabulator-cellEdited', e);
    });
});
