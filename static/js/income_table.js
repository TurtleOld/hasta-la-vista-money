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
    if (skeleton) {
        skeleton.style.display = '';
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
            return response.data || response;
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
                        buttons += `<button class="btn btn-sm btn-outline-success me-1 edit-income-btn" data-id="${data.id}" title="Редактировать"><i class="bi bi-pencil"></i></button>`;
                        buttons += `<button class="btn btn-sm btn-outline-primary me-1 copy-income-btn" data-id="${data.id}" title="Копировать"><i class="bi bi-files"></i></button>`;
                        buttons += `<button class="btn btn-sm btn-outline-danger delete-income-btn" data-id="${data.id}" title="Удалить"><i class="bi bi-trash"></i></button>`;
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
    const alertClass = type === 'success' ? 'alert-success' :
                      type === 'error' ? 'alert-danger' : 'alert-info';
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

// Функции редактирования
function editIncome(id) { // eslint-disable-line
    const modal = new bootstrap.Modal(document.getElementById('add-income'));
    loadIncomeData(id);
    modal.show();
}

function copyIncome(id) { // eslint-disable-line
    fetch(`/income/${id}/copy/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken')
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.incomeTabulator.setData('/income/ajax/income_data/', { group_id: getGroupId() });
            showNotification('Доход скопирован', 'success');
        } else {
            showNotification('Ошибка копирования', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Ошибка копирования', 'error');
    });
}

function deleteIncome(id) { // eslint-disable-line
    if (confirm('Вы уверены, что хотите удалить этот доход?')) {
        fetch(`/income/delete/${id}/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.incomeTabulator.setData('/income/ajax/income_data/', { group_id: getGroupId() });
                showNotification('Доход удален', 'success');
            } else {
                showNotification('Ошибка удаления', 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Ошибка удаления', 'error');
        });
    }
}

function loadIncomeData(id) {
    fetch(`/income/get/${id}/`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const income = data.income;
                const form = document.getElementById('income-form');

                // Заполнить форму данными
                form.querySelector('[name="category"]').value = income.category_id;
                form.querySelector('[name="account"]').value = income.account_id;
                form.querySelector('[name="amount"]').value = income.amount;
                form.querySelector('[name="date"]').value = income.date;

                // Изменить action формы на редактирование
                form.action = `/income/change/${id}/`;

                // Изменить заголовок модального окна
                const modalTitle = document.querySelector('#add-income .modal-title');
                if (modalTitle) {
                    modalTitle.textContent = 'Редактировать доход';
                }
            } else {
                showNotification('Ошибка загрузки данных', 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Ошибка загрузки данных', 'error');
        });
}

// Делегирование событий для кнопок действий (CSP-safe)
document.addEventListener('click', function(e) {
    const editBtn = e.target.closest('.edit-income-btn');
    if (editBtn) {
        const id = editBtn.dataset.id;
        editIncome(id);
        return;
    }
    const copyBtn = e.target.closest('.copy-income-btn');
    if (copyBtn) {
        const id = copyBtn.dataset.id;
        copyIncome(id);
        return;
    }
    const deleteBtn = e.target.closest('.delete-income-btn');
    if (deleteBtn) {
        const id = deleteBtn.dataset.id;
        deleteIncome(id);
        return;
    }
});
