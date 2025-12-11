/* global Tabulator */
document.addEventListener('DOMContentLoaded', function () {
    function getGroupId() {
        const groupSelect = document.getElementById('expense-group-select');
        return groupSelect ? groupSelect.value : 'my';
    }

    const table = document.getElementById('expense-table');
    const currentUserId = table ? parseInt(table.dataset.currentUserId) : null;
    const skeleton = document.getElementById('expense-skeleton');
    const mobileCardsContainer = document.getElementById('expense-mobile-cards');
    if (skeleton) skeleton.style.display = '';

    if (typeof Tabulator === 'undefined') {
        console.error('Tabulator не загружен');
        return;
    }

    // Функция для форматирования суммы
    function formatMoney(amount) {
        return parseFloat(amount).toLocaleString('ru-RU', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    // Функция для генерации мобильных карточек
    function renderMobileCards(data) {
        if (!mobileCardsContainer) {
            return;
        }

        mobileCardsContainer.innerHTML = '';

        if (!data || data.length === 0) {
            mobileCardsContainer.innerHTML = '<div class="text-center text-muted py-4">Нет данных для отображения. Добавьте первый расход!</div>';
            return;
        }

        data.forEach(function (item) {
            const card = document.createElement('div');
            card.className = 'mobile-card';

            const isOwner = item.user_id === currentUserId;
            let actionsHtml = '';

            if (item.is_receipt) {
                actionsHtml = '<span class="badge bg-info">Чек</span>';
            } else if (isOwner) {
                const csrfToken = getCookie('csrftoken') || '';
                actionsHtml = `
                    <a href="/expense/change/${item.id}/" class="btn btn-sm btn-outline-success me-1" title="Редактировать">
                        <i class="bi bi-pencil"></i>
                    </a>
                    <form method="post" action="/expense/${item.id}/copy/" class="d-inline me-1">
                        <input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}">
                        <button type="submit" class="btn btn-sm btn-outline-primary" title="Копировать">
                            <i class="bi bi-files"></i>
                        </button>
                    </form>
                    <form method="post" action="/expense/delete/${item.id}/" class="d-inline">
                        <input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}">
                        <button type="submit" class="btn btn-sm btn-outline-danger" title="Удалить" onclick="return confirm('Вы уверены, что хотите удалить этот расход?');">
                            <i class="bi bi-trash"></i>
                        </button>
                    </form>
                `;
            } else {
                actionsHtml = '<span class="text-muted">Только просмотр</span>';
            }

            card.innerHTML = `
                <div class="mobile-card-header fw-bold text-success mb-2">${item.category_name || 'Без категории'}</div>
                <div class="mobile-card-body">
                    <div class="mobile-card-row d-flex justify-content-between align-items-center mb-2">
                        <span class="label text-muted">Сумма:</span>
                        <span class="value fw-bold text-success">${formatMoney(item.amount)} ₽</span>
                    </div>
                    <div class="mobile-card-row d-flex justify-content-between align-items-center mb-2">
                        <span class="label text-muted">Счет:</span>
                        <span class="value text-primary">${item.account_name || 'Не указан'}</span>
                    </div>
                    <div class="mobile-card-row d-flex justify-content-between align-items-center mb-2">
                        <span class="label text-muted">Дата:</span>
                        <span class="value text-secondary">${item.date || 'Не указана'}</span>
                    </div>
                    <div class="mobile-card-row d-flex justify-content-between align-items-center mb-2">
                        <span class="label text-muted">Пользователь:</span>
                        <span class="value text-muted">${item.user_name || 'Не указан'}</span>
                    </div>
                    <div class="mobile-card-row d-flex justify-content-between align-items-center">
                        <span class="label text-muted">Действия:</span>
                        <span class="value">${actionsHtml}</span>
                    </div>
                </div>
            `;

            mobileCardsContainer.appendChild(card);
        });
    }

    window.expenseTabulator = new Tabulator('#expense-table', {
        theme: 'bootstrap5',
        ajaxURL: '/expense/ajax/expense_data/',
        ajaxParams: function() {
            return { group_id: getGroupId() };
        },
        ajaxResponse: function(url, params, response) {
            if (table) table.classList.remove('d-none');
            if (skeleton) skeleton.style.display = 'none';
            const data = response.data || response;
            // Генерируем мобильные карточки
            renderMobileCards(data);
            return data;
        },
        placeholder: 'Нет данных для отображения. Добавьте первый расход!',
        columns: [
            { title: 'Категория', field: 'category_name', headerFilter: 'input', cssClass: 'text-success' },
            { title: 'Счет', field: 'account_name', headerFilter: 'input', cssClass: 'text-primary' },
            { title: 'Сумма', field: 'amount', formatter: 'money', formatterParams: { decimal: ",", thousand: " ", precision: 2 }, hozAlign: 'right', headerFilter: 'number', cssClass: 'fw-bold text-success' },
            { title: 'Дата', field: 'date', headerFilter: 'input', cssClass: 'text-secondary' },
            { title: 'Пользователь', field: 'user_name', cssClass: 'text-muted' },
            { title: 'Действия',
                formatter: function(cell) {
                    const data = cell.getRow().getData();
                    const isOwner = data.user_id === currentUserId;
                    if (data.is_receipt) {
                        return `<span class="badge bg-info">Чек</span>`;
                    }
                    let buttons = '';
                    if (isOwner) {
                        const csrfToken = getCookie('csrftoken') || '';
                        buttons += `<a href="/expense/change/${data.id}/" class="btn btn-sm btn-outline-success me-1" title="Редактировать"><i class="bi bi-pencil"></i></a>`;
                        buttons += `<form method="post" action="/expense/${data.id}/copy/" class="d-inline me-1"><input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}"><button type="submit" class="btn btn-sm btn-outline-primary" title="Копировать"><i class="bi bi-files"></i></button></form>`;
                        buttons += `<form method="post" action="/expense/delete/${data.id}/" class="d-inline"><input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}"><button type="submit" class="btn btn-sm btn-outline-danger" title="Удалить" onclick="return confirm('Вы уверены, что хотите удалить этот расход?');"><i class="bi bi-trash"></i></button></form>`;
                    } else {
                        buttons += `<span class="text-muted">Только просмотр</span>`;
                    }
                    return buttons;
                },
                headerSort: false, hozAlign: 'center', cssClass: 'text-center'
            }
        ],
        layout: 'fitColumns',
        pagination: true,
        paginationSize: 25,
        locale: 'ru-ru',
        langs: {
            'ru-ru': {
                pagination: {
                    first: 'Первая', last: 'Последняя', prev: 'Предыдущая', next: 'Следующая'
                },
                headerFilters: { default: 'фильтр столбца' }
            }
        },
        rowFormatter: function(row) {
            const el = row.getElement();
            // Мягкие полосы только для чётных строк
            if (row.getPosition(true) % 2 === 0) {
                el.classList.add('tabulator-alt-row');
            } else {
                el.classList.remove('tabulator-alt-row');
            }
        },
        tableBuilt: function() {
            if (table) table.classList.remove('d-none');
            if (skeleton) skeleton.style.display = 'none';
            // Генерируем мобильные карточки при первой загрузке
            const data = window.expenseTabulator.getData();
            renderMobileCards(data);
        },
        dataLoaded: function (data) {
            // Обновляем мобильные карточки при загрузке данных
            renderMobileCards(data);
        }
    });

    // Переключение групп
    const groupSelect = document.getElementById('expense-group-select');
    if (groupSelect) {
        groupSelect.addEventListener('change', function() {
            window.expenseTabulator.setData('/expense/ajax/expense_data/', { group_id: getGroupId() });
        });
    }

    // Обновляем мобильные карточки при изменении данных
    window.expenseTabulator.on('dataChanged', function () {
        const data = window.expenseTabulator.getData();
        renderMobileCards(data);
    });

    // Обработчик для кнопки фильтра групп
    const toggleBtn = document.getElementById('toggle-group-filter');
    const filterBlock = document.getElementById('expense-group-filter-block');
    if (toggleBtn && filterBlock) {
        toggleBtn.addEventListener('click', function() {
            filterBlock.classList.toggle('d-none');
        });
    }
});

// Функция для получения CSRF-токена из cookie
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
