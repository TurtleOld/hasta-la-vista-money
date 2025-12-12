/* global Tabulator, bootstrap */

function getGroupId() {
    const groupSelect = document.getElementById('income-group-select');
    return groupSelect ? groupSelect.value : 'my';
}

document.addEventListener('DOMContentLoaded', function () {
    const table = document.getElementById('income-table');
    const currentUserId = table ? parseInt(table.dataset.currentUserId) : null;

    if (typeof Tabulator === 'undefined') {
        console.error('Tabulator не загружен');
        return;
    }

    if (table) {
        table.classList.add('income-table');
    }

    const skeleton = document.getElementById('income-skeleton');
    const mobileCardsContainer = document.getElementById('income-mobile-cards');
    if (skeleton) {
        skeleton.style.display = '';
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
        row.className = 'mobile-card-row d-flex justify-content-between align-items-center mb-2';

        const label = createTextElement('span', labelText, 'label text-muted');
        const value = createTextElement('span', valueText, valueClass ? 'value ' + valueClass : 'value');

        row.appendChild(label);
        row.appendChild(value);
        return row;
    }

    function createActionButtons(item, isOwner) {
        const valueDiv = document.createElement('span');
        valueDiv.className = 'value';

        if (isOwner) {
            const csrfToken = getCookie('csrftoken') || '';

            const editLink = document.createElement('a');
            editLink.href = '/income/change/' + item.id + '/';
            editLink.className = 'btn btn-sm btn-outline-success me-1';
            editLink.title = 'Редактировать';
            const editIcon = document.createElement('i');
            editIcon.className = 'bi bi-pencil';
            editLink.appendChild(editIcon);
            valueDiv.appendChild(editLink);

            const copyForm = document.createElement('form');
            copyForm.method = 'post';
            copyForm.action = '/income/' + item.id + '/copy/';
            copyForm.className = 'd-inline me-1';
            const copyCsrf = document.createElement('input');
            copyCsrf.type = 'hidden';
            copyCsrf.name = 'csrfmiddlewaretoken';
            copyCsrf.value = csrfToken;
            const copyBtn = document.createElement('button');
            copyBtn.type = 'submit';
            copyBtn.className = 'btn btn-sm btn-outline-primary';
            copyBtn.title = 'Копировать';
            const copyIcon = document.createElement('i');
            copyIcon.className = 'bi bi-files';
            copyBtn.appendChild(copyIcon);
            copyForm.appendChild(copyCsrf);
            copyForm.appendChild(copyBtn);
            valueDiv.appendChild(copyForm);

            const deleteForm = document.createElement('form');
            deleteForm.method = 'post';
            deleteForm.action = '/income/delete/' + item.id + '/';
            deleteForm.className = 'd-inline';
            const deleteCsrf = document.createElement('input');
            deleteCsrf.type = 'hidden';
            deleteCsrf.name = 'csrfmiddlewaretoken';
            deleteCsrf.value = csrfToken;
            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'submit';
            deleteBtn.className = 'btn btn-sm btn-outline-danger';
            deleteBtn.title = 'Удалить';
            deleteBtn.onclick = function() {
                return confirm('Вы уверены, что хотите удалить этот доход?');
            };
            const deleteIcon = document.createElement('i');
            deleteIcon.className = 'bi bi-trash';
            deleteBtn.appendChild(deleteIcon);
            deleteForm.appendChild(deleteCsrf);
            deleteForm.appendChild(deleteBtn);
            valueDiv.appendChild(deleteForm);
        } else {
            const viewOnly = createTextElement('span', 'Только просмотр', 'text-muted');
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
            const emptyDiv = createTextElement('div', 'Нет данных для отображения. Добавьте первый доход!', 'text-center text-muted py-4');
            mobileCardsContainer.appendChild(emptyDiv);
            return;
        }

        data.forEach(function (item) {
            const card = document.createElement('div');
            card.className = 'mobile-card';

            const header = createTextElement('div', item.category_name || 'Без категории', 'mobile-card-header fw-bold text-success mb-2');
            card.appendChild(header);

            const body = document.createElement('div');
            body.className = 'mobile-card-body';

            body.appendChild(createCardRow('Сумма:', formatMoney(item.amount) + ' ₽', 'fw-bold text-success'));
            body.appendChild(createCardRow('Счет:', item.account_name || 'Не указан', 'text-primary'));
            body.appendChild(createCardRow('Дата:', item.date || 'Не указана', 'text-secondary'));
            body.appendChild(createCardRow('Пользователь:', item.user_name || 'Не указан', 'text-muted'));

            const actionsRow = document.createElement('div');
            actionsRow.className = 'mobile-card-row d-flex justify-content-between align-items-center';
            const actionsLabel = createTextElement('span', 'Действия:', 'label text-muted');
            const isOwner = item.user_id === currentUserId;
            const actionsValue = createActionButtons(item, isOwner);
            actionsRow.appendChild(actionsLabel);
            actionsRow.appendChild(actionsValue);
            body.appendChild(actionsRow);

            card.appendChild(body);
            mobileCardsContainer.appendChild(card);
        });
    }

    window.incomeTabulator = new Tabulator("#income-table", {
        theme: 'bootstrap5',
        ajaxURL: '/api/income/data/',
        ajaxParams: function() {
            return {
                group_id: getGroupId()
            };
        },
        ajaxResponse: function(url, params, response) {
            if (table) table.classList.remove('d-none');
            if (skeleton) skeleton.style.display = 'none';
            const data = response.results || response.data || response;
            renderMobileCards(data);
            return data;
        },
        placeholder: 'Нет данных для отображения. Добавьте первый доход!',
        columns: [
            {
                title: "Категория",
                field: "category_name",
                headerFilter: "input",
                cssClass: 'text-success'
            },
            {
                title: "Счет",
                field: "account_name",
                headerFilter: "input",
                cssClass: 'text-primary'
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
                hozAlign: "right",
                cssClass: 'fw-bold text-success'
            },
            {
                title: "Дата",
                field: "date",
                headerFilter: "input",
                cssClass: 'text-secondary'
            },
            {
                title: "Пользователь",
                field: "user_name",
                cssClass: 'text-muted'
            },
            {
                title: "Действия",
                formatter: function(cell) {
                    const data = cell.getRow().getData();
                    const isOwner = data.user_id === currentUserId;
                    let buttons = '';
                    if (isOwner) {
                        const csrfToken = getCookie('csrftoken') || '';
                        buttons += `<a href="/income/change/${data.id}/" class="btn btn-sm btn-outline-success me-1" title="Редактировать"><i class="bi bi-pencil"></i></a>`;
                        buttons += `<form method="post" action="/income/${data.id}/copy/" class="d-inline me-1"><input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}"><button type="submit" class="btn btn-sm btn-outline-primary" title="Копировать"><i class="bi bi-files"></i></button></form>`;
                        buttons += `<form method="post" action="/income/delete/${data.id}/" class="d-inline"><input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}"><button type="submit" class="btn btn-sm btn-outline-danger" title="Удалить" onclick="return confirm('Вы уверены, что хотите удалить этот доход?');"><i class="bi bi-trash"></i></button></form>`;
                    } else {
                        buttons += `<span class="text-muted">Только просмотр</span>`;
                    }
                    return buttons;
                },
                headerSort: false,
                hozAlign: "center",
                cssClass: 'text-center'
            }
        ],
        layout: "fitColumns",
        pagination: true,
        paginationSize: 25,
        paginationSizeSelector: [10, 25, 50, 100],
        paginationCounter: "rows",
        locale: "ru-ru",
        langs: {
            "ru-ru": {
                "pagination": {
                    "first": "Первая",
                    "first_title": "Первая страница",
                    "last": "Последняя",
                    "last_title": "Последняя страница",
                    "prev": "Предыдущая",
                    "prev_title": "Предыдущая страница",
                    "next": "Следующая",
                    "next_title": "Следующая страница"
                },
                "headerFilters": {
                    "default": "фильтр столбца",
                    "columns": {
                        "name": "фильтр имени"
                    }
                }
            }
        },
        rowFormatter: function(row) {
            const el = row.getElement();
            if (row.getPosition(true) % 2 === 0) {
                el.classList.add('tabulator-alt-row');
            } else {
                el.classList.remove('tabulator-alt-row');
            }
        },
        tableBuilt: function() {
            if (table) table.classList.remove('d-none');
            if (skeleton) skeleton.style.display = 'none';
            const data = window.incomeTabulator.getData();
            renderMobileCards(data);
        },
        dataLoaded: function (data) {
            renderMobileCards(data);
        }
    });

    const tableElem = document.getElementById('income-table');
    if (tableElem) {
        tableElem.classList.remove('d-none');
    }

    const groupSelect = document.getElementById('income-group-select');
    if (groupSelect) {
        groupSelect.addEventListener('change', function() {
            window.incomeTabulator.setData('/api/income/data/', { group_id: getGroupId() });
        });
    }

    window.incomeTabulator.on('dataChanged', function () {
        const data = window.incomeTabulator.getData();
        renderMobileCards(data);
    });

    const toggleBtn = document.getElementById('toggle-group-filter');
    const filterBlock = document.getElementById('income-group-filter-block');
    if (toggleBtn && filterBlock) {
        toggleBtn.addEventListener('click', function() {
            filterBlock.classList.toggle('d-none');
        });
    }

    const addIncomeBtn = document.querySelector('[data-bs-target="#add-income"]');
    if (addIncomeBtn) {
        addIncomeBtn.addEventListener('click', function() {
            const form = document.getElementById('income-form');
            if (form) {
                form.reset();
                form.action = '/income/create/';
            }
            const modalTitle = document.querySelector('#add-income .modal-title');
            if (modalTitle) {
                modalTitle.textContent = 'Добавить доход';
            }
        });
    }

    window.incomeTabulator.on("dataLoadError", function(){
        if (skeleton) {
            skeleton.style.display = 'none';
        }
    });
});

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
    setTimeout(() => {
        if (alert.parentNode) {
            alert.remove();
        }
    }, 5000);
}

