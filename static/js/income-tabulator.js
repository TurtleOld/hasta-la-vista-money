/* global Tabulator */
document.addEventListener('DOMContentLoaded', function () {
    // Функция получения ID группы
    function getGroupId() {
        const groupSelect = document.getElementById('income-group-select');
        return groupSelect ? groupSelect.value : 'my';
    }

    // Получаем текущий user id из data-атрибута таблицы
    const table = document.getElementById('income-table');
    const currentUserId = table ? parseInt(table.dataset.currentUserId) : null;

    if (typeof Tabulator === 'undefined') {
        console.error('Tabulator не загружен');
        return;
    }

    // Показываем skeleton loader до загрузки данных
    const skeleton = document.getElementById('income-skeleton');
    if (skeleton) {
        skeleton.style.display = '';
    }

    // Создание Tabulator таблицы
    window.incomeTabulator = new Tabulator("#income-table", {
        ajaxURL: '/income/ajax/income_data/',
        ajaxParams: function() {
            return {
                group_id: getGroupId()
            };
        },
        ajaxResponse: function(url, params, response) {
            // Tabulator ожидает массив данных, а не объект
            const tableElem = document.getElementById('income-table');
            if (tableElem) {
                tableElem.classList.remove('d-none');
            }
            // Скрываем skeleton после загрузки данных
            if (skeleton) {
                skeleton.style.display = 'none';
            }
            return response.data || response;
        },
        // Конфигурация столбцов
        columns: [
            {
                title: "Категория",
                field: "category_name",
                headerFilter: "input",
            },
            {
                title: "Счет",
                field: "account_name",
                headerFilter: "input",
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
                hozAlign: "right"
            },
            {
                title: "Дата",
                field: "date",
                headerFilter: "input",
            },
            {
                title: "Пользователь",
                field: "user_name",
                visible: function() {
                    return getGroupId() !== 'my';
                }
            },
            {
                title: "Действия",
                formatter: function(cell) {
                    const row = cell.getRow();
                    const data = row.getData();
                    const isOwner = data.user_id === currentUserId;

                    let buttons = '';

                    if (isOwner) {
                        buttons += `<button class="btn btn-sm btn-outline-primary me-1" onclick="editIncome(${data.id})" title="Редактировать">
                            <i class="bi bi-pencil"></i>
                        </button>`;
                        buttons += `<button class="btn btn-sm btn-outline-warning me-1" onclick="copyIncome(${data.id})" title="Копировать">
                            <i class="bi bi-files"></i>
                        </button>`;
                        buttons += `<button class="btn btn-sm btn-outline-danger" onclick="deleteIncome(${data.id})" title="Удалить">
                            <i class="bi bi-trash"></i>
                        </button>`;
                    } else {
                        buttons += `<span class="text-muted">Только просмотр</span>`;
                    }

                    return buttons;
                },
                headerSort: false,
                hozAlign: "center"
            }
        ],
        // Настройки таблицы
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
        // Стили для строк
        rowFormatter: function(row) {
            const data = row.getData();
            if (data.user_id !== currentUserId) {
                row.getElement().classList.add('table-foreign');
            }
        },
        // Показать таблицу после загрузки
        tableBuilt: function() {
            const tableElem = document.getElementById('income-table');
            if (tableElem) {
                tableElem.classList.remove('d-none');
            }
            // Скрываем skeleton после построения таблицы
            if (skeleton) {
                skeleton.style.display = 'none';
            }
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
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function showNotification(message, type = 'info') {
    // Простая реализация уведомлений
    const alertClass = type === 'success' ? 'alert-success' :
                      type === 'error' ? 'alert-danger' : 'alert-info';

    const alert = document.createElement('div');
    alert.className = `alert ${alertClass} alert-dismissible fade show position-fixed`;
    alert.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
    alert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;

    document.body.appendChild(alert);

    // Автоматически скрыть через 5 секунд
    setTimeout(() => {
        if (alert.parentNode) {
            alert.remove();
        }
    }, 5000);
}

// Функции редактирования
function editIncome(id) {
    // Открыть модальное окно редактирования
    const modal = new bootstrap.Modal(document.getElementById('add-income'));
    // Загрузить данные дохода
    loadIncomeData(id);
    modal.show();
}

function copyIncome(id) {
    fetch(`/income/${id}/copy/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken')
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.incomeTabulator.reloadData();
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

function deleteIncome(id) {
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
                window.incomeTabulator.reloadData();
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
