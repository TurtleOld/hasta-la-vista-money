/* global Tabulator, bootstrap */

// Функция получения ID группы (глобальная)
function getGroupId() {
    const groupSelect = document.getElementById('income-group-select');
    return groupSelect ? groupSelect.value : 'my';
}

document.addEventListener('DOMContentLoaded', function () {
    // Получаем текущий user id из data-атрибута таблицы
    const table = document.getElementById('income-table');
    const currentUserId = table ? parseInt(table.dataset.currentUserId) : null;

    if (typeof Tabulator === 'undefined') {
        console.error('Tabulator не загружен');
        return;
    }

    // Добавляем CSS класс для стилизации
    if (table) {
        table.classList.add('income-table');
    }

    // Показываем skeleton loader до загрузки данных
    const skeleton = document.getElementById('income-skeleton');
    const mobileCardsContainer = document.getElementById('income-mobile-cards');
    if (skeleton) {
        skeleton.style.display = '';
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
            mobileCardsContainer.innerHTML = '<div class="text-center text-muted py-4">Нет данных для отображения. Добавьте первый доход!</div>';
            return;
        }

        data.forEach(function (item) {
            const card = document.createElement('div');
            card.className = 'mobile-card';

            const isOwner = item.user_id === currentUserId;
            let actionsHtml = '';

            if (isOwner) {
                const csrfToken = getCookie('csrftoken') || '';
                actionsHtml = `
                    <a href="/income/change/${item.id}/" class="btn btn-sm btn-outline-success me-1" title="Редактировать">
                        <i class="bi bi-pencil"></i>
                    </a>
                    <form method="post" action="/income/${item.id}/copy/" class="d-inline me-1">
                        <input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}">
                        <button type="submit" class="btn btn-sm btn-outline-primary" title="Копировать">
                            <i class="bi bi-files"></i>
                        </button>
                    </form>
                    <form method="post" action="/income/delete/${item.id}/" class="d-inline">
                        <input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}">
                        <button type="submit" class="btn btn-sm btn-outline-danger" title="Удалить" onclick="return confirm('Вы уверены, что хотите удалить этот доход?');">
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

    // Создание Tabulator таблицы
    window.incomeTabulator = new Tabulator("#income-table", {
        theme: 'bootstrap5',
        ajaxURL: '/income/ajax/income_data/',
        ajaxParams: function() {
            return {
                group_id: getGroupId()
            };
        },
        ajaxResponse: function(url, params, response) {
            if (table) table.classList.remove('d-none');
            if (skeleton) skeleton.style.display = 'none';
            const data = response.data || response;
            // Генерируем мобильные карточки
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
            // Генерируем мобильные карточки при первой загрузке
            const data = window.incomeTabulator.getData();
            renderMobileCards(data);
        },
        dataLoaded: function (data) {
            // Обновляем мобильные карточки при загрузке данных
            renderMobileCards(data);
        }
    });

    // Убираем d-none сразу после инициализации (на всякий случай)
    const tableElem = document.getElementById('income-table');
    if (tableElem) {
        tableElem.classList.remove('d-none');
    }

    // Обработчик изменения группы
    const groupSelect = document.getElementById('income-group-select');
    if (groupSelect) {
        groupSelect.addEventListener('change', function() {
            window.incomeTabulator.setData('/income/ajax/income_data/', { group_id: getGroupId() });
        });
    }

    // Обновляем мобильные карточки при изменении данных
    window.incomeTabulator.on('dataChanged', function () {
        const data = window.incomeTabulator.getData();
        renderMobileCards(data);
    });

    // Показать/скрыть фильтр групп
    const toggleBtn = document.getElementById('toggle-group-filter');
    const filterBlock = document.getElementById('income-group-filter-block');
    if (toggleBtn && filterBlock) {
        toggleBtn.addEventListener('click', function() {
            filterBlock.classList.toggle('d-none');
        });
    }

    // Обработчик для кнопки добавления нового дохода
    const addIncomeBtn = document.querySelector('[data-bs-target="#add-income"]');
    if (addIncomeBtn) {
        addIncomeBtn.addEventListener('click', function() {
            // Сбросить форму
            const form = document.getElementById('income-form');
            if (form) {
                form.reset();
                form.action = '/income/create/';
            }
            // Изменить заголовок модального окна
            const modalTitle = document.querySelector('#add-income .modal-title');
            if (modalTitle) {
                modalTitle.textContent = 'Добавить доход';
            }
        });
    }

    // Если произошла ошибка загрузки — скрыть skeleton
    window.incomeTabulator.on("dataLoadError", function(){
        if (skeleton) {
            skeleton.style.display = 'none';
        }
    });
});

// Вспомогательные функции
function getCookie(name) {
    // Разрешаем только буквы, цифры, дефис и подчёркивание
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

