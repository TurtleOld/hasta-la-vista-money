/* global Tabulator */
window.BUDGET_SCRIPT_EXECUTED = false;
try {
    (function () {
        'use strict';
        window.BUDGET_SCRIPT_EXECUTED = true;
        function initBudgetTables() {
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
        options.credentials = 'include';
        options.headers['Accept'] = 'application/json';
        options.headers['X-Requested-With'] = 'XMLHttpRequest';
        const jwt = getJWT();
        if (jwt) {
            options.headers['Authorization'] = 'Bearer ' + jwt;
        }
        if (options.method && options.method.toUpperCase() === 'POST') {
            options.headers['Content-Type'] = 'application/json';
        }
        return fetch(hardcodedUrl, options).then(resp => { // eslint-disable-line
            if (resp.status === 401 && retry) {
                return refreshToken().then(newAccess => {
                    options.headers['Authorization'] = 'Bearer ' + newAccess;
                    return fetch(hardcodedUrl, options); // eslint-disable-line
                }).catch(err => {
                    console.error('[BUDGET] Token refresh failed:', err);
                    throw err;
                });
            }
            return resp;
        }).catch(err => {
            console.error('[BUDGET] Fetch error:', err);
            throw err;
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

            function fixBudgetTableStyles(tableElement) {
                if (!tableElement) {
                    return;
                }

                function applyHorizontalStyles(element) {
                    if (!element) return;
                    element.style.setProperty('writing-mode', 'horizontal-tb', 'important');
                    element.style.setProperty('text-orientation', 'mixed', 'important');
                    element.style.setProperty('transform', 'none', 'important');
                    element.style.setProperty('transform-origin', 'center', 'important');
                    element.style.setProperty('direction', 'ltr', 'important');
                }

                const allHeaderElements = tableElement.querySelectorAll(
                    '.tabulator-header .tabulator-col, ' +
                    '.tabulator-col-group, ' +
                    '.tabulator-header .tabulator-col-content, ' +
                    '.tabulator-header .tabulator-col-title-holder, ' +
                    '.tabulator-header .tabulator-col-title, ' +
                    '.tabulator-headers .tabulator-col, ' +
                    '.tabulator-headers .tabulator-col-group, ' +
                    '.tabulator-headers .tabulator-col-content, ' +
                    '.tabulator-headers .tabulator-col-title-holder, ' +
                    '.tabulator-headers .tabulator-col-title'
                );

                allHeaderElements.forEach(function (element) {
                    applyHorizontalStyles(element);
                    if (element.classList.contains('tabulator-col') || element.classList.contains('tabulator-col-group')) {
                        element.style.setProperty('display', 'table-cell', 'important');
                        element.style.setProperty('vertical-align', 'middle', 'important');
                    }
                    element.style.setProperty('white-space', 'normal', 'important');
                });

                const headerCols = tableElement.querySelectorAll('.tabulator-header .tabulator-col, .tabulator-col-group');
                headerCols.forEach(function (col) {
                    applyHorizontalStyles(col);
                    col.style.setProperty('max-width', '100%', 'important');
                    col.style.setProperty('box-sizing', 'border-box', 'important');
                    col.style.setProperty('overflow', 'visible', 'important');
                    col.style.setProperty('display', 'table-cell', 'important');
                    col.style.setProperty('vertical-align', 'middle', 'important');
                    col.style.setProperty('text-align', 'center', 'important');

                    const colContent = col.querySelector('.tabulator-col-content');
                    if (colContent) {
                        applyHorizontalStyles(colContent);
                        colContent.style.setProperty('display', 'flex', 'important');
                        colContent.style.setProperty('flex-direction', 'row', 'important');
                        colContent.style.setProperty('flex-wrap', 'nowrap', 'important');
                        colContent.style.setProperty('align-items', 'center', 'important');
                        colContent.style.setProperty('justify-content', 'center', 'important');
                        colContent.style.setProperty('gap', '0.5rem', 'important');
                        colContent.style.setProperty('overflow', 'visible', 'important');
                        colContent.style.setProperty('width', '100%', 'important');
                    }

                    const titleHolder = col.querySelector('.tabulator-col-title-holder');
                    if (titleHolder) {
                        applyHorizontalStyles(titleHolder);
                        titleHolder.style.setProperty('display', 'flex', 'important');
                        titleHolder.style.setProperty('flex-direction', 'row', 'important');
                        titleHolder.style.setProperty('flex-wrap', 'nowrap', 'important');
                        titleHolder.style.setProperty('align-items', 'center', 'important');
                        titleHolder.style.setProperty('justify-content', 'center', 'important');
                        titleHolder.style.setProperty('gap', '0.5rem', 'important');
                    }

                    const titles = col.querySelectorAll('.tabulator-col-title');
                    titles.forEach(function (title) {
                        applyHorizontalStyles(title);
                        title.style.setProperty('display', 'inline-block', 'important');
                        title.style.setProperty('white-space', 'nowrap', 'important');
                        title.style.setProperty('text-align', 'center', 'important');
                        title.style.setProperty('line-height', 'normal', 'important');
                    });

                    const filterInputs = col.querySelectorAll('.tabulator-header-filter input, .tabulator-header-filter select');
                    filterInputs.forEach(function (input) {
                        input.style.setProperty('width', 'auto', 'important');
                        input.style.setProperty('max-width', '100%', 'important');
                        input.style.setProperty('box-sizing', 'border-box', 'important');
                        input.style.setProperty('flex', '1 1 auto', 'important');
                        input.style.setProperty('margin', '0', 'important');
                    });

                    const filterContainer = col.querySelector('.tabulator-header-filter');
                    if (filterContainer) {
                        filterContainer.style.setProperty('width', 'auto', 'important');
                        filterContainer.style.setProperty('max-width', '100%', 'important');
                        filterContainer.style.setProperty('box-sizing', 'border-box', 'important');
                        filterContainer.style.setProperty('overflow', 'visible', 'important');
                        filterContainer.style.setProperty('flex', '1 1 auto', 'important');
                        filterContainer.style.setProperty('margin-top', '0', 'important');
                    }
                });

                const categoryCol = tableElement.querySelector('.budget-category-col, .tabulator-col[tabulator-field="category"]');
                if (categoryCol) {
                    applyHorizontalStyles(categoryCol);
                    categoryCol.style.setProperty('text-align', 'left', 'important');
                    const categoryContent = categoryCol.querySelector('.tabulator-col-content');
                    if (categoryContent) {
                        categoryContent.style.setProperty('justify-content', 'flex-start', 'important');
                    }
                }

                const colGroups = tableElement.querySelectorAll('.tabulator-col-group');
                colGroups.forEach(function (group) {
                    applyHorizontalStyles(group);
                    group.style.setProperty('display', 'table-cell', 'important');
                    group.style.setProperty('vertical-align', 'middle', 'important');
                    group.style.setProperty('text-align', 'center', 'important');
                    group.style.setProperty('white-space', 'normal', 'important');

                    const allGroupElements = group.querySelectorAll('*');
                    allGroupElements.forEach(function (elem) {
                        applyHorizontalStyles(elem);
                    });

                    const groupContent = group.querySelector('.tabulator-col-content');
                    if (groupContent) {
                        applyHorizontalStyles(groupContent);
                        groupContent.style.setProperty('display', 'flex', 'important');
                        groupContent.style.setProperty('flex-direction', 'row', 'important');
                        groupContent.style.setProperty('align-items', 'center', 'important');
                        groupContent.style.setProperty('justify-content', 'center', 'important');
                        groupContent.style.setProperty('width', '100%', 'important');
                    }

                    const groupTitleHolder = group.querySelector('.tabulator-col-title-holder');
                    if (groupTitleHolder) {
                        applyHorizontalStyles(groupTitleHolder);
                        groupTitleHolder.style.setProperty('display', 'flex', 'important');
                        groupTitleHolder.style.setProperty('flex-direction', 'row', 'important');
                        groupTitleHolder.style.setProperty('align-items', 'center', 'important');
                        groupTitleHolder.style.setProperty('justify-content', 'center', 'important');
                    }

                    const groupTitles = group.querySelectorAll('.tabulator-col-title');
                    groupTitles.forEach(function (groupTitle) {
                        applyHorizontalStyles(groupTitle);
                        groupTitle.style.setProperty('white-space', 'nowrap', 'important');
                        groupTitle.style.setProperty('text-align', 'center', 'important');
                        groupTitle.style.setProperty('display', 'inline-block', 'important');
                        groupTitle.style.setProperty('line-height', 'normal', 'important');
                    });
                });

                const headerRows = tableElement.querySelectorAll('.tabulator-headers');
                headerRows.forEach(function (row) {
                    row.style.setProperty('height', 'auto', 'important');
                    row.style.setProperty('display', 'table-row', 'important');
                    applyHorizontalStyles(row);

                    const rowElements = row.querySelectorAll('*');
                    rowElements.forEach(function (elem) {
                        applyHorizontalStyles(elem);
                    });
                });

                const header = tableElement.querySelector('.tabulator-header');
                if (header) {
                    header.style.setProperty('display', 'table-header-group', 'important');
                    applyHorizontalStyles(header);

                    const headerElements = header.querySelectorAll('*');
                    headerElements.forEach(function (elem) {
                        if (elem.classList && (
                            elem.classList.contains('tabulator-col') ||
                            elem.classList.contains('tabulator-col-group') ||
                            elem.classList.contains('tabulator-col-content') ||
                            elem.classList.contains('tabulator-col-title-holder') ||
                            elem.classList.contains('tabulator-col-title')
                        )) {
                            applyHorizontalStyles(elem);
                        }
                    });
                }

                const cells = tableElement.querySelectorAll('.tabulator-cell');
                cells.forEach(function (cell) {
                    applyHorizontalStyles(cell);
                    cell.style.setProperty('max-width', '100%', 'important');
                    cell.style.setProperty('box-sizing', 'border-box', 'important');
                    cell.style.setProperty('overflow', 'hidden', 'important');
                    cell.style.setProperty('display', 'table-cell', 'important');
                    cell.style.setProperty('vertical-align', 'middle', 'important');
                });

                const rows = tableElement.querySelectorAll('.tabulator-table .tabulator-row');
                rows.forEach(function (row) {
                    row.style.setProperty('display', 'table-row', 'important');
                });

                const table = tableElement.querySelector('.tabulator-table');
                if (table) {
                    table.style.setProperty('display', 'table', 'important');
                    table.style.setProperty('width', '100%', 'important');
                    table.style.setProperty('table-layout', 'auto', 'important');
                }
            }

            function setupBudgetTableStyleObserver(tableElement) {
                if (!tableElement) {
                    return null;
                }

                const observer = new MutationObserver(function (mutations) {
                    let shouldFix = false;
                    mutations.forEach(function (mutation) {
                        if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
                            const target = mutation.target;
                            if (target && target.classList && (
                                target.classList.contains('tabulator-col') ||
                                target.classList.contains('tabulator-col-group') ||
                                target.classList.contains('tabulator-headers') ||
                                target.classList.contains('tabulator-header-filter') ||
                                target.closest('.tabulator-header')
                            )) {
                                shouldFix = true;
                            }
                        }
                        if (mutation.type === 'childList') {
                            const addedNodes = Array.from(mutation.addedNodes);
                            if (addedNodes.some(function (node) {
                                return node.nodeType === 1 && (
                                    node.classList && (
                                        node.classList.contains('tabulator-col') ||
                                        node.classList.contains('tabulator-col-group') ||
                                        node.classList.contains('tabulator-headers')
                                    ) || node.closest('.tabulator-header')
                                );
                            })) {
                                shouldFix = true;
                            }
                        }
                    });

                    if (shouldFix) {
                        setTimeout(function () {
                            fixBudgetTableStyles(tableElement);
                        }, 10);
                    }
                });

                observer.observe(tableElement, {
                    attributes: true,
                    attributeFilter: ['style', 'class'],
                    subtree: true,
                    childList: true
                });

                return observer;
            }
    TABLES.forEach(({ id, type, api }) => {
        const container = document.getElementById(id);
        if (!container) {
            return;
        }
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
            .then(async resp => {
                const contentType = resp.headers.get('Content-Type') || '';

                if (!resp.ok) {
                    const text = await resp.text();
                    console.error('[BUDGET] API error response:', text.substring(0, 500));
                    throw new Error(`API error: ${resp.status} - ${text.substring(0, 200)}`);
                }

                if (!contentType.includes('application/json')) {
                    const text = await resp.text();
                    console.error('[BUDGET] API returned non-JSON. Content-Type:', contentType);
                    console.error('[BUDGET] Response preview:', text.substring(0, 500));
                    throw new Error(`API returned ${contentType} instead of JSON. Status: ${resp.status}. Response starts with: ${text.substring(0, 100)}`);
                }

                return resp.json();
            })
            .then(data => {
                if (!data || typeof data !== 'object') {
                    if (loader && loader.parentNode) {
                        loader.remove();
                    }
                    console.error('[BUDGET] Invalid data format:', data);
                    showNotification('Ошибка загрузки данных: неверный формат', 'error');
                    return;
                }
                if (!Array.isArray(data.data) || !Array.isArray(data.months)) {
                    console.error('[BUDGET] Missing data or months arrays:', {
                        hasData: Array.isArray(data.data),
                        hasMonths: Array.isArray(data.months),
                        dataKeys: Object.keys(data),
                        data: data
                    });
                    showNotification('Ошибка загрузки данных: отсутствуют данные или месяцы', 'error');
                    return;
                }
                const months = data.months;
                const rows = data.data;
                if (rows.length === 0) {
                    if (loader && loader.parentNode) {
                        loader.remove();
                    }
                    showNotification('Нет данных для отображения. Добавьте категории расходов/доходов и месяцы.', 'info');
                    return;
                }
                if (months.length === 0) {
                    if (loader && loader.parentNode) {
                        loader.remove();
                    }
                    showNotification('Нет месяцев для отображения. Нажмите "Добавить ещё месяцы" на странице бюджета.', 'info');
                    return;
                }
                const columns = [
                    {
                        title: 'Категория',
                        field: 'category',
                        headerFilter: 'input',
                        cssClass: 'fw-bold text-start budget-category-col',
                        width: 200,
                        minWidth: 150,
                        headerSort: true,
                        hozAlign: 'left',
                        formatter: 'plaintext',
                        headerHozAlign: 'left'
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
                if (!container || !container.parentNode || !document.body.contains(container)) {
                    showNotification('Ошибка: контейнер таблицы недоступен', 'error');
                    return;
                }
                if (!Array.isArray(tabData)) {
                    if (loader && loader.parentNode) {
                        loader.remove();
                    }
                    showNotification('Ошибка: неверный формат данных', 'error');
                    return;
                }
                let tabulatorInstance;
                try {
                    if (!container || !container.parentNode || !document.body.contains(container)) {
                        if (loader && loader.parentNode) {
                            loader.remove();
                        }
                        showNotification('Ошибка: контейнер таблицы недоступен', 'error');
                        return;
                    }
                    tabulatorInstance = new Tabulator(container, {
                        data: tabData,
                        columns: columns,
                        layout: 'fitColumns',
                        responsiveLayout: false,
                        placeholder: 'Нет данных для отображения',
                        movableColumns: false,
                        resizableRows: false,
                        resizableColumns: true,
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
                        tooltips: false,
                        renderStart: function () {
                            if (loader && loader.parentNode) {
                                loader.remove();
                            }
                        },
                        tableBuilt: function () {
                            if (loader && loader.parentNode) {
                                loader.remove();
                            }
                            setTimeout(function () {
                                fixBudgetTableStyles(container);
                            }, 10);
                            setTimeout(function () {
                                fixBudgetTableStyles(container);
                            }, 50);
                            setTimeout(function () {
                                fixBudgetTableStyles(container);
                            }, 200);
                            setTimeout(function () {
                                fixBudgetTableStyles(container);
                            }, 500);
                        },
                    cellEdited: function (cell) {
                        const field = cell.getField();
                        if (!field.startsWith('plan_')) return;
                        const value = cell.getValue();
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
                                type: type
                            })
                        })
                            .then(resp => resp.json())
                            .then(data => {
                                if (data.success) {
                                    showNotification('План успешно сохранён', 'success');
                                } else {
                                    showNotification('Ошибка сохранения плана', 'error');
                                    cell.setValue(cell.getOldValue(), true);
                                }
                            })
                            .catch((err) => {
                                showNotification('Ошибка соединения с сервером', 'error');
                                cell.setValue(cell.getOldValue(), true);
                            });
                    }
                });
                    tabulatorInstance.on('dataChanged', function () {
                        setTimeout(function () {
                            fixBudgetTableStyles(container);
                        }, 10);
                        setTimeout(function () {
                            fixBudgetTableStyles(container);
                        }, 50);
                        setTimeout(function () {
                            fixBudgetTableStyles(container);
                        }, 200);
                    });
                    tabulatorInstance.on('columnResized', function () {
                        setTimeout(function () {
                            fixBudgetTableStyles(container);
                        }, 10);
                        setTimeout(function () {
                            fixBudgetTableStyles(container);
                        }, 50);
                    });
                    tabulatorInstance.on('tableBuilt', function () {
                        setTimeout(function () {
                            fixBudgetTableStyles(container);
                        }, 10);
                        setTimeout(function () {
                            fixBudgetTableStyles(container);
                        }, 50);
                        setTimeout(function () {
                            fixBudgetTableStyles(container);
                        }, 200);
                    });

                    setupBudgetTableStyleObserver(container);
                } catch (tabError) {
                    console.error('[BUDGET] Error creating Tabulator:', tabError);
                    console.error('[BUDGET] Error stack:', tabError.stack);
                    showNotification('Ошибка создания таблицы: ' + tabError.message, 'error');
                }
            })
            .catch(err => {
                console.error('[BUDGET] Error loading table data:', err);
                console.error('[BUDGET] Error stack:', err.stack);
                loader.remove();
                const errorMessage = err.message || 'Ошибка загрузки данных';
                showNotification(errorMessage, 'error');
                if (err.message === 'Refresh failed' || err.message === 'No refresh token') {
                    safeRedirect('/login/');
                }
            });
    });
        }

        function waitForTabulator(callback, maxAttempts = 50, attempt = 0) {
            const hasTabulator = typeof Tabulator !== 'undefined';
            if (hasTabulator) {
                callback();
            } else if (attempt < maxAttempts) {
                setTimeout(() => waitForTabulator(callback, maxAttempts, attempt + 1), 100);
            } else {
                console.error('[BUDGET] Tabulator not found after', maxAttempts, 'attempts');
            }
        }

        function startInit() {
            const readyState = document.readyState;
            const initCallback = () => {
                if (typeof requestIdleCallback !== 'undefined') {
                    requestIdleCallback(() => {
                        waitForTabulator(initBudgetTables);
                    }, { timeout: 2000 });
                } else {
                    setTimeout(() => {
                        waitForTabulator(initBudgetTables);
                    }, 0);
                }
            };
            if (readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', initCallback);
            } else {
                initCallback();
            }
        }

        startInit();
    })();
} catch (error) {
    console.error('[BUDGET] Fatal error in script:', error);
    console.error('[BUDGET] Error stack:', error.stack);
}
