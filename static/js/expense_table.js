/* global Tabulator */
document.addEventListener('DOMContentLoaded', function () {
    function getGroupId() {
        const groupSelect = document.getElementById('expense-group-select');
        return groupSelect ? groupSelect.value : 'my';
    }

    const table = document.getElementById('expense-table');
    const currentUserId = table ? parseInt(table.dataset.currentUserId) : null;
    const skeleton = document.getElementById('expense-skeleton');
    if (skeleton) skeleton.style.display = '';

    if (typeof Tabulator === 'undefined') {
        console.error('Tabulator не загружен');
        return;
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
            return response.data || response;
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
                        buttons += `<button class="btn btn-sm btn-outline-success me-1" onclick="editExpense(${data.id})" title="Редактировать"><i class="bi bi-pencil"></i></button>`;
                        buttons += `<button class="btn btn-sm btn-outline-primary me-1" onclick="copyExpense(${data.id})" title="Копировать"><i class="bi bi-files"></i></button>`;
                        buttons += `<button class="btn btn-sm btn-outline-danger" onclick="deleteExpense(${data.id})" title="Удалить"><i class="bi bi-trash"></i></button>`;
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
            if(row.getPosition(true) % 2 === 0) {
                el.classList.add('bg-success', 'bg-opacity-10');
            } else {
                el.classList.remove('bg-success', 'bg-opacity-10');
            }
        },
        tableBuilt: function() {
            if (table) table.classList.remove('d-none');
            if (skeleton) skeleton.style.display = 'none';
        }
    });

    // Переключение групп
    const groupSelect = document.getElementById('expense-group-select');
    if (groupSelect) {
        groupSelect.addEventListener('change', function() {
            window.expenseTabulator.setData('/expense/ajax/expense_data/', { group_id: getGroupId() });
        });
    }

    // Обработчик для кнопки фильтра групп
    const toggleBtn = document.getElementById('toggle-group-filter');
    const filterBlock = document.getElementById('expense-group-filter-block');
    if (toggleBtn && filterBlock) {
        toggleBtn.addEventListener('click', function() {
            filterBlock.classList.toggle('d-none');
        });
    }
});

// Вспомогательные функции для действий (заглушка)
function editExpense(id) {
    alert('Редактировать расход: ' + id);
}
function copyExpense(id) {
    alert('Копировать расход: ' + id);
}
function deleteExpense(id) {
    if (confirm('Вы уверены, что хотите удалить этот расход?')) {
        alert('Удалить расход: ' + id);
    }
}
