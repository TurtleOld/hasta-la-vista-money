/* global DataTable */
document.addEventListener('DOMContentLoaded', function () {
    function getGroupId() {
        const groupSelect = document.getElementById('income-group-select');
        return groupSelect ? groupSelect.value : 'my';
    }

    // Получаем текущий user id из data-атрибута таблицы
    const table = document.getElementById('income-table');
    const currentUserId = table ? parseInt(table.dataset.currentUserId) : null;

    if (typeof DataTable === 'undefined') {
        return;
    }

    window.incomeDataTable = new DataTable('#income-table', {
        ajax: {
            url: '/income/ajax/income_data/',
            data: function (d) {
                d.group_id = getGroupId();
            }
        },
        layout: {
            top: 'searchPanes'
        },
        searchPanes: {
            initCollapsed: true
        },
        language: {
            emptyTable: "Информация о доходах отсутствует!",
            search: "Поиск:",
            lengthMenu: "Показать _MENU_ записей на странице",
            info: "Показано с _START_ по _END_ из _TOTAL_ записей",
            paginate: {
                first: "«",
                last: "»",
                next: "›",
                previous: "‹"
            }
        },
        order: [[0, 'desc']],
        columnDefs: [
            {
                targets: 2, // Категория
                searchPanes: { show: true }
            },
            {
                targets: [0, 1, 3, 4, 5],
                searchPanes: { show: false }
            },
            {
                targets: 1, // Сумма
                render: {
                    filter: function (data) {
                        if (!data) return '';
                        return data.replace(/ /g, '');
                    }
                }
            }
        ],
        createdRow: function (row, data) {
            const rowUserId = parseInt(data[6]);
            if (currentUserId && rowUserId && rowUserId !== currentUserId) {
                row.classList.add('table-foreign');
            }
        },
        initComplete: function() {
            const tableElem = document.getElementById('income-table');
            if (tableElem) {
                tableElem.classList.remove('d-none');
            }
        }
    });

    // При смене группы просто обновляйте данные
    const groupSelect = document.getElementById('income-group-select');
    if (groupSelect) {
        groupSelect.addEventListener('change', function () {
            window.incomeDataTable.ajax.reload();
        });
    }

    // Логика для показа/скрытия фильтра
    const toggleBtn = document.getElementById('toggle-group-filter');
    const filterBlock = document.getElementById('income-group-filter-block');
    if (toggleBtn && filterBlock) {
        toggleBtn.addEventListener('click', function () {
            filterBlock.classList.toggle('d-none');
        });
    }
});
