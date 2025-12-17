/* global Tabulator */

function escapeHtml(text) {
    if (text == null) {
        return '';
    }
    const textStr = String(text);
    let result = '';
    for (let i = 0; i < textStr.length; i++) {
        const char = textStr.charAt(i);
        if (char === '&') {
            result += '&amp;';
        } else if (char === '<') {
            result += '&lt;';
        } else if (char === '>') {
            result += '&gt;';
        } else if (char === '"') {
            result += '&quot;';
        } else if (char === "'") {
            result += '&#039;';
        } else {
            result += char;
        }
    }
    return result;
}

function sanitizeId(id) {
    if (id == null) {
        return '';
    }
    const idStr = String(id);
    if (!/^\d+$/.test(idStr)) {
        console.warn('Invalid ID format:', idStr);
        return '';
    }
    return idStr;
}

function getGroupId() {
    const groupSelect = document.getElementById('income-group-select');
    return groupSelect ? groupSelect.value : 'my';
}

function initIncomePage() {
    const table = document.getElementById('income-table');
    if (!table) {
        console.error('Элемент #income-table не найден в DOM');
        return;
    }

    const currentUserId = parseInt(table.dataset.currentUserId) || null;

    table.classList.add('income-table');

    const skeleton = document.getElementById('income-skeleton');
    const mobileCardsContainer = document.getElementById('income-mobile-cards');
    if (skeleton) {
        skeleton.style.display = '';
        skeleton.classList.remove('hidden');
    }

    function createIconSvg(type) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'h-4 w-4');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('viewBox', '0 0 24 24');

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');

        if (type === 'edit') {
            path.setAttribute('stroke-linecap', 'round');
            path.setAttribute('stroke-linejoin', 'round');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('d', 'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z');
        } else if (type === 'copy') {
            path.setAttribute('stroke-linecap', 'round');
            path.setAttribute('stroke-linejoin', 'round');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('d', 'M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z');
        } else if (type === 'delete') {
            path.setAttribute('stroke-linecap', 'round');
            path.setAttribute('stroke-linejoin', 'round');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('d', 'M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3m-4 0h14');
        } else {
            return null;
        }

        svg.appendChild(path);
        return svg;
    }

    function getIconSvgHtml(type) {
        if (type === 'edit') {
            return '<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>';
        }
        if (type === 'copy') {
            return '<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>';
        }
        if (type === 'delete') {
            return '<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3m-4 0h14"></path></svg>';
        }
        return '';
    }

    function getActionBaseClass() {
        return [
            'inline-flex items-center justify-center gap-1',
            'rounded-md border px-2 py-1',
            'text-xs font-medium',
            'transition-colors',
            'focus:outline-none focus:ring-2 focus:ring-green-500/30',
            'focus:ring-offset-1 focus:ring-offset-white dark:focus:ring-offset-gray-900'
        ].join(' ');
    }

    function getActionVariantClass(type) {
        if (type === 'edit') {
            return 'border-emerald-600 text-emerald-700 hover:bg-emerald-50 dark:border-emerald-400 dark:text-emerald-300 dark:hover:bg-emerald-900/20';
        }
        if (type === 'copy') {
            return 'border-sky-600 text-sky-700 hover:bg-sky-50 dark:border-sky-400 dark:text-sky-300 dark:hover:bg-sky-900/20';
        }
        if (type === 'delete') {
            return 'border-red-600 text-red-700 hover:bg-red-50 dark:border-red-400 dark:text-red-300 dark:hover:bg-red-900/20';
        }
        return 'border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700/30';
    }

    function createEmptyPlaceholder() {
        const wrapper = document.createElement('div');
        wrapper.className = 'hlvm-empty flex flex-col items-center justify-center gap-3 py-10 text-center';

        const iconDiv = document.createElement('div');
        iconDiv.className = 'flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300';
        const iconSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        iconSvg.setAttribute('class', 'h-6 w-6');
        iconSvg.setAttribute('fill', 'none');
        iconSvg.setAttribute('stroke', 'currentColor');
        iconSvg.setAttribute('viewBox', '0 0 24 24');
        const iconPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        iconPath.setAttribute('stroke-linecap', 'round');
        iconPath.setAttribute('stroke-linejoin', 'round');
        iconPath.setAttribute('stroke-width', '2');
        iconPath.setAttribute('d', 'M3 3v18h18M7 14l3-3 3 3 5-6');
        iconSvg.appendChild(iconPath);
        iconDiv.appendChild(iconSvg);

        const textDiv = document.createElement('div');
        textDiv.className = 'space-y-1';
        const titleDiv = document.createElement('div');
        titleDiv.className = 'text-sm font-semibold text-gray-900 dark:text-gray-100';
        titleDiv.textContent = 'Нет данных';
        const descDiv = document.createElement('div');
        descDiv.className = 'text-sm text-gray-500 dark:text-gray-400';
        descDiv.textContent = 'Добавьте первый доход, чтобы увидеть таблицу';
        textDiv.appendChild(titleDiv);
        textDiv.appendChild(descDiv);

        const link = document.createElement('a');
        link.href = '/income/create/';
        link.className = 'inline-flex items-center justify-center rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-gray-900';
        link.textContent = 'Добавить доход';

        wrapper.appendChild(iconDiv);
        wrapper.appendChild(textDiv);
        wrapper.appendChild(link);

        return wrapper;
    }

    function localizeTabulatorFooter() {
        const pageSize = table.querySelector('.tabulator-page-size');
        if (pageSize) {
            const label = pageSize.querySelector('label');
            if (label && label.textContent && label.textContent.toLowerCase().includes('page size')) {
                label.textContent = 'Размер:';
            }
        }

        const counter = table.querySelector('.tabulator-page-counter');
        if (counter && counter.textContent) {
            const text = counter.textContent;

            const rangeMatch = text.match(/Showing\s+(\d+)\s+to\s+(\d+)\s+of\s+(\d+)\s+rows/i);
            if (rangeMatch) {
                const from = rangeMatch[1];
                const to = rangeMatch[2];
                const total = rangeMatch[3];
                counter.textContent = `Показано: ${from}–${to} из ${total}`;
                return;
            }

            const rowsMatch = text.match(/Showing\s+(\d+)\s+rows/i);
            if (rowsMatch) {
                const totalOnly = rowsMatch[1];
                counter.textContent = `Показано: ${totalOnly}`;
            }
        }
    }

    function fixTabulatorInlineStyles() {
        if (!table) {
            return;
        }

        const headerCols = table.querySelectorAll('.tabulator-header .tabulator-col');
        headerCols.forEach(function (col) {
            col.style.setProperty('max-width', '100%', 'important');
            col.style.setProperty('box-sizing', 'border-box', 'important');
            col.style.setProperty('overflow', 'visible', 'important');
            col.style.removeProperty('display');
            col.style.removeProperty('flex-direction');
            col.style.removeProperty('flex-wrap');
            col.style.removeProperty('align-items');
            col.style.removeProperty('gap');

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

            const colContent = col.querySelector('.tabulator-col-content');
            if (colContent) {
                colContent.style.setProperty('display', 'flex', 'important');
                colContent.style.setProperty('flex-direction', 'row', 'important');
                colContent.style.setProperty('flex-wrap', 'nowrap', 'important');
                colContent.style.setProperty('align-items', 'center', 'important');
                colContent.style.setProperty('gap', '0.5rem', 'important');
                colContent.style.setProperty('flex', '1 1 auto', 'important');
                colContent.style.setProperty('overflow', 'visible', 'important');
                colContent.style.setProperty('width', '100%', 'important');
            }

            const titleHolder = col.querySelector('.tabulator-col-title-holder');
            if (titleHolder) {
                titleHolder.style.setProperty('display', 'flex', 'important');
                titleHolder.style.setProperty('flex-direction', 'row', 'important');
                titleHolder.style.setProperty('flex-wrap', 'nowrap', 'important');
                titleHolder.style.setProperty('align-items', 'center', 'important');
                titleHolder.style.setProperty('gap', '0.5rem', 'important');
            }
        });

        const headerRows = table.querySelectorAll('.tabulator-headers');
        headerRows.forEach(function (row) {
            row.style.setProperty('height', 'auto', 'important');
        });

        const cells = table.querySelectorAll('.tabulator-cell');
        cells.forEach(function (cell) {
            cell.style.setProperty('max-width', '100%', 'important');
            cell.style.setProperty('box-sizing', 'border-box', 'important');
            cell.style.setProperty('overflow', 'hidden', 'important');
        });

        const rows = table.querySelectorAll('.tabulator-table .tabulator-row');
        rows.forEach(function (row) {
            row.style.setProperty('display', 'flex', 'important');
            row.style.setProperty('flex-direction', 'row', 'important');
            row.style.setProperty('flex-wrap', 'nowrap', 'important');
            row.style.setProperty('align-items', 'stretch', 'important');
        });
    }

    function setupTabulatorStyleObserver() {
        if (!table) {
            return;
        }

        const observer = new MutationObserver(function (mutations) {
            let shouldFix = false;
            mutations.forEach(function (mutation) {
                if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
                    const target = mutation.target;
                    if (target.classList && (
                        target.classList.contains('tabulator-col') ||
                        target.classList.contains('tabulator-headers') ||
                        target.classList.contains('tabulator-header-filter') ||
                        target.closest('.tabulator-header')
                    )) {
                        shouldFix = true;
                    }
                }
            });

            if (shouldFix) {
                setTimeout(function () {
                    fixTabulatorInlineStyles();
                }, 10);
            }
        });

        observer.observe(table, {
            attributes: true,
            attributeFilter: ['style'],
            subtree: true,
            childList: true
        });

        return observer;
    }

    function ensureTabulatorLoaded(onReady) {
        if (typeof window.Tabulator !== 'undefined') {
            onReady();
            return;
        }

        const sources = [
            'https://unpkg.com/tabulator-tables@6.3.1/dist/js/tabulator.min.js',
            'https://cdn.jsdelivr.net/npm/tabulator-tables@6.3.1/dist/js/tabulator.min.js',
        ];

        function tryLoad(srcIndex) {
            if (srcIndex >= sources.length) {
                console.error('Tabulator не загружен (все источники недоступны)');
                if (skeleton) {
                    skeleton.style.display = 'none';
                    skeleton.classList.add('hidden');
                }
                table.classList.remove('invisible', 'hidden', 'd-none');
                table.classList.add('visible');
                return;
            }

            const src = sources[srcIndex];
            if (typeof src !== 'string' || !/^https?:\/\//.test(src)) {
                tryLoad(srcIndex + 1);
                return;
            }
            const script = document.createElement('script');
            script.setAttribute('src', src);
            script.setAttribute('async', 'true');
            script.onload = function () {
                if (typeof window.Tabulator !== 'undefined') {
                    onReady();
                } else {
                    tryLoad(srcIndex + 1);
                }
            };
            script.onerror = function () {
                tryLoad(srcIndex + 1);
            };
            document.head.appendChild(script);
        }

        tryLoad(0);
    }

    function formatMoney(amount) {
        return parseFloat(amount).toLocaleString('ru-RU', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    function createTextElement(tag, text, className) {
        const element = document.createElement(tag);
        if (className) {
            element.className = className;
        }
        element.textContent = text;
        return element;
    }

    function createCardRow(labelText, valueText, valueClass) {
        const row = document.createElement('div');
        row.className = 'mobile-card-row flex justify-between items-center mb-2';

        const label = createTextElement('span', labelText, 'label text-gray-500 dark:text-gray-400');
        const value = createTextElement('span', valueText, valueClass ? 'value ' + valueClass : 'value');

        row.appendChild(label);
        row.appendChild(value);
        return row;
    }

    function createActionButtons(item, isOwner) {
        const valueDiv = document.createElement('span');
        valueDiv.className = 'value inline-flex items-center gap-1.5';

        if (isOwner) {
            const sanitizedId = sanitizeId(item.id);
            if (!sanitizedId) {
                return valueDiv;
            }

            const csrfToken = getCookie('csrftoken') || '';

            const editLink = document.createElement('a');
            editLink.href = '/income/change/' + sanitizedId + '/';
            editLink.className = getActionBaseClass() + ' ' + getActionVariantClass('edit');
            editLink.title = 'Редактировать';
            editLink.setAttribute('aria-label', 'Редактировать');
            const editIcon = createIconSvg('edit');
            if (editIcon) {
                editLink.appendChild(editIcon);
            }
            valueDiv.appendChild(editLink);

            const copyForm = document.createElement('form');
            copyForm.method = 'post';
            copyForm.action = '/income/' + sanitizedId + '/copy/';
            copyForm.className = 'inline-flex';
            const copyCsrf = document.createElement('input');
            copyCsrf.type = 'hidden';
            copyCsrf.name = 'csrfmiddlewaretoken';
            copyCsrf.value = escapeHtml(csrfToken);
            const copyBtn = document.createElement('button');
            copyBtn.type = 'submit';
            copyBtn.className = getActionBaseClass() + ' ' + getActionVariantClass('copy');
            copyBtn.title = 'Копировать';
            copyBtn.setAttribute('aria-label', 'Копировать');
            const copyIcon = createIconSvg('copy');
            if (copyIcon) {
                copyBtn.appendChild(copyIcon);
            }
            copyForm.appendChild(copyCsrf);
            copyForm.appendChild(copyBtn);
            valueDiv.appendChild(copyForm);

            const deleteForm = document.createElement('form');
            deleteForm.method = 'post';
            deleteForm.action = '/income/delete/' + sanitizedId + '/';
            deleteForm.className = 'inline-flex';
            const deleteCsrf = document.createElement('input');
            deleteCsrf.type = 'hidden';
            deleteCsrf.name = 'csrfmiddlewaretoken';
            deleteCsrf.value = escapeHtml(csrfToken);
            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'submit';
            deleteBtn.className = getActionBaseClass() + ' ' + getActionVariantClass('delete');
            deleteBtn.title = 'Удалить';
            deleteBtn.setAttribute('aria-label', 'Удалить');
            deleteBtn.onclick = function () {
                return confirm('Вы уверены, что хотите удалить этот доход?');
            };
            const deleteIcon = createIconSvg('delete');
            if (deleteIcon) {
                deleteBtn.appendChild(deleteIcon);
            }
            deleteForm.appendChild(deleteCsrf);
            deleteForm.appendChild(deleteBtn);
            valueDiv.appendChild(deleteForm);
        } else {
            const viewOnly = createTextElement('span', 'Только просмотр', 'text-gray-500 dark:text-gray-400');
            valueDiv.appendChild(viewOnly);
        }

        return valueDiv;
    }

    function renderMobileCards(data) {
        if (!mobileCardsContainer) {
            return;
        }

        while (mobileCardsContainer.firstChild) {
            mobileCardsContainer.removeChild(mobileCardsContainer.firstChild);
        }

        if (!data || data.length === 0) {
            const emptyDiv = createTextElement('div', 'Нет данных для отображения. Добавьте первый доход!', 'text-center text-gray-500 dark:text-gray-400 py-4');
            mobileCardsContainer.appendChild(emptyDiv);
            return;
        }

        data.forEach(function (item) {
            const card = document.createElement('div');
            card.className = 'mobile-card';

            const header = createTextElement('div', item.category_name || 'Без категории', 'mobile-card-header font-bold text-green-600 dark:text-green-400 mb-2');
            card.appendChild(header);

            const body = document.createElement('div');
            body.className = 'mobile-card-body';

            body.appendChild(createCardRow('Сумма:', formatMoney(item.amount) + ' ₽', 'font-bold text-green-600 dark:text-green-400'));
            body.appendChild(createCardRow('Счет:', item.account_name || 'Не указан', 'text-blue-600 dark:text-blue-400'));
            body.appendChild(createCardRow('Дата:', item.date || 'Не указана', 'text-gray-600 dark:text-gray-300'));
            body.appendChild(createCardRow('Пользователь:', item.user_name || 'Не указан', 'text-gray-500 dark:text-gray-400'));

            const actionsRow = document.createElement('div');
            actionsRow.className = 'mobile-card-row flex justify-between items-center';
            const actionsLabel = createTextElement('span', 'Действия:', 'label text-gray-500 dark:text-gray-400');
            const isOwner = item.user_id === currentUserId;
            const actionsValue = createActionButtons(item, isOwner);
            actionsRow.appendChild(actionsLabel);
            actionsRow.appendChild(actionsValue);
            body.appendChild(actionsRow);

            card.appendChild(body);
            mobileCardsContainer.appendChild(card);
        });
    }

    function initIncomeTable() {
        try {
            console.log('Инициализация Tabulator для income, элемент найден:', !!table);
            window.incomeTabulator = new Tabulator('#income-table', {
                ajaxURL: '/api/income/data/',
                ajaxParams: function () {
                    return {
                        group_id: getGroupId()
                    };
                },
                ajaxResponse: function (url, params, response) {
                    console.log('AJAX ответ получен для income:', { url, params, response });
                    table.classList.remove('invisible', 'hidden', 'd-none');
                    table.classList.add('visible');
                    if (skeleton) {
                        skeleton.style.display = 'none';
                        skeleton.classList.add('hidden');
                    }
                    const data = response.results || response.data || response;
                    console.log('Данные для отображения income:', data);
                    renderMobileCards(data);
                    return data;
                },
                ajaxError: function (error) {
                    console.error('Ошибка загрузки данных income:', error);
                    if (skeleton) {
                        skeleton.style.display = 'none';
                        skeleton.classList.add('hidden');
                    }
                    table.classList.remove('invisible', 'hidden', 'd-none');
                    table.classList.add('visible');
                },
                placeholder: createEmptyPlaceholder(),
                columns: [
            {
                title: "Категория",
                field: "category_name",
                headerFilter: "input",
                        headerFilterParams: { elementAttributes: { name: 'category_name', id: 'income-filter-category_name' } },
                        cssClass: 'text-green-600 dark:text-green-400'
            },
            {
                title: "Счет",
                field: "account_name",
                headerFilter: "input",
                headerFilterParams: { elementAttributes: { name: 'account_name', id: 'income-filter-account_name' } },
                cssClass: 'text-blue-600 dark:text-blue-400'
            },
            {
                title: "Сумма",
                field: "amount",
                formatter: "money",
                formatterParams: {
                    decimal: ",",
                    thousand: " ",
                    precision: 2
                },
                headerFilter: "number",
                headerFilterParams: { elementAttributes: { name: 'amount', id: 'income-filter-amount' } },
                hozAlign: "right",
                cssClass: 'font-bold text-green-600 dark:text-green-400'
            },
            {
                title: "Дата",
                field: "date",
                headerFilter: "input",
                headerFilterParams: { elementAttributes: { name: 'date', id: 'income-filter-date' } },
                cssClass: 'text-gray-600 dark:text-gray-300'
            },
            {
                title: "Пользователь",
                field: "user_name",
                cssClass: 'text-gray-500 dark:text-gray-400'
            },
            {
                title: "Действия",
                formatter: function (cell) {
                    const data = cell.getRow().getData();
                    const isOwner = data.user_id === currentUserId;
                    let buttons = '';
                    if (isOwner) {
                        const sanitizedId = sanitizeId(data.id);
                        if (!sanitizedId) {
                            return '<span class="text-gray-500 dark:text-gray-400">Ошибка ID</span>';
                        }
                        const csrfToken = getCookie('csrftoken') || '';
                        const escapedToken = escapeHtml(csrfToken);
                        const escapedConfirm = escapeHtml('Вы уверены, что хотите удалить этот доход?').replace(/"/g, '&quot;');
                        const base = getActionBaseClass();
                        const editClass = getActionVariantClass('edit');
                        const copyClass = getActionVariantClass('copy');
                        const deleteClass = getActionVariantClass('delete');
                        const editIcon = getIconSvgHtml('edit');
                        const copyIcon = getIconSvgHtml('copy');
                        const deleteIcon = getIconSvgHtml('delete');
                        buttons += `<span class="inline-flex items-center gap-1.5">`;
                        buttons += `<a href="/income/change/${sanitizedId}/" class="${base} ${editClass}" title="Редактировать" aria-label="Редактировать">${editIcon}</a>`;
                        buttons += `<form method="post" action="/income/${sanitizedId}/copy/" class="inline-flex"><input type="hidden" name="csrfmiddlewaretoken" value="${escapedToken}"><button type="submit" class="${base} ${copyClass}" title="Копировать" aria-label="Копировать">${copyIcon}</button></form>`;
                        buttons += `<form method="post" action="/income/${sanitizedId}/delete/" class="inline-flex"><input type="hidden" name="csrfmiddlewaretoken" value="${escapedToken}"><button type="submit" class="${base} ${deleteClass}" title="Удалить" aria-label="Удалить" onclick="return confirm(&quot;${escapedConfirm}&quot;);">${deleteIcon}</button></form>`;
                        buttons += `</span>`;
                    } else {
                        buttons += `<span class="text-gray-500 dark:text-gray-400">Только просмотр</span>`;
                    }
                    return buttons;
                },
                headerSort: false,
                hozAlign: "center",
                cssClass: 'text-center'
            }
                ],
                layout: 'fitColumns',
                pagination: true,
                paginationSize: 25,
                paginationSizeSelector: [10, 25, 50, 100],
                paginationCounter: 'rows',
                locale: 'ru-ru',
                langs: {
                    'ru-ru': {
                        'pagination': {
                            'first': '«',
                            'first_title': 'Первая страница',
                            'last': '»',
                            'last_title': 'Последняя страница',
                            'prev': '‹',
                            'prev_title': 'Предыдущая страница',
                            'next': '›',
                            'next_title': 'Следующая страница'
                        },
                        'headerFilters': {
                            'default': 'фильтр столбца',
                            'columns': {
                                'name': 'фильтр имени'
                            }
                        }
                    }
                },
                rowFormatter: function (row) {
                    const el = row.getElement();
                    if (row.getPosition(true) % 2 === 0) {
                        el.classList.add('tabulator-alt-row');
                    } else {
                        el.classList.remove('tabulator-alt-row');
                    }
                },
                tableBuilt: function () {
                    console.log('Таблица income построена');
                    table.classList.remove('invisible', 'hidden', 'd-none');
                    table.classList.add('visible');
                    if (skeleton) {
                        skeleton.style.display = 'none';
                        skeleton.classList.add('hidden');
                    }
                    setTimeout(function () {
                        fixTabulatorInlineStyles();
                        setupTabulatorStyleObserver();
                    }, 100);
                    setTimeout(function () {
                        fixTabulatorInlineStyles();
                    }, 300);
                    setTimeout(function () {
                        fixTabulatorInlineStyles();
                    }, 500);
                    localizeTabulatorFooter();
                    const data = window.incomeTabulator.getData();
                    renderMobileCards(data);
                },
                dataLoaded: function (data) {
                    setTimeout(function () {
                        fixTabulatorInlineStyles();
                    }, 50);
                    setTimeout(function () {
                        fixTabulatorInlineStyles();
                    }, 200);
                    renderMobileCards(data);
                    localizeTabulatorFooter();
                }
            });
        } catch (error) {
            console.error('Ошибка инициализации Tabulator для income:', error);
            if (skeleton) {
                skeleton.style.display = 'none';
                skeleton.classList.add('hidden');
            }
            table.classList.remove('invisible', 'hidden', 'd-none');
            table.classList.add('visible');
            return;
        }

        const groupSelect = document.getElementById('income-group-select');
        if (groupSelect) {
            groupSelect.addEventListener('change', function () {
                window.incomeTabulator.setData('/api/income/data/', { group_id: getGroupId() });
            });
        }

        window.incomeTabulator.on('dataChanged', function () {
            setTimeout(function () {
                fixTabulatorInlineStyles();
            }, 50);
            setTimeout(function () {
                fixTabulatorInlineStyles();
            }, 200);
            const data = window.incomeTabulator.getData();
            renderMobileCards(data);
        });

        window.incomeTabulator.on('columnResized', function () {
            setTimeout(function () {
                fixTabulatorInlineStyles();
            }, 50);
            setTimeout(function () {
                fixTabulatorInlineStyles();
            }, 200);
        });

        const toggleBtn = document.getElementById('toggle-group-filter');
        const filterBlock = document.getElementById('income-group-filter-block');
        if (toggleBtn && filterBlock) {
            toggleBtn.addEventListener('click', function () {
                filterBlock.classList.toggle('hidden');
            });
        }

        window.incomeTabulator.on('dataLoadError', function (error) {
            console.error('Ошибка загрузки данных income:', error);
            if (skeleton) {
                skeleton.style.display = 'none';
                skeleton.classList.add('hidden');
            }
            table.classList.remove('invisible', 'hidden', 'd-none');
            table.classList.add('visible');
        });
    }

    ensureTabulatorLoaded(initIncomeTable);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initIncomePage);
} else {
    initIncomePage();
}

function getCookie(name) {
    if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
        return null;
    }
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (const cookieRaw of cookies) {
            const cookie = cookieRaw.trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}
