/* global DataTable */
document.addEventListener('DOMContentLoaded', function () {
    function getGroupId() {
        const groupSelect = document.getElementById('expense-group-select');
        return groupSelect ? groupSelect.value : 'my';
    }

    const table = document.getElementById('expense-table');
    const currentUserId = table ? parseInt(table.dataset.currentUserId) : null;

    if (typeof DataTable === 'undefined') {
        return;
    }

    window.expenseDataTable = new DataTable('#expense-table', {
        ajax: {
            url: '/expense/ajax/expense_data/',
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
            emptyTable: "Информация о расходах отсутствует!",
            search: "Поиск:",
            lengthMenu: "Показать _MENU_ записей на странице",
            info: "Показано с _START_ по _END_ из _TOTAL_ записей",
            paginate: {
                first: "«",
                last: "»",
                next: "›",
                previous: "‹"
            },
            searchPanes: {
                panes: {
                    title: {
                        2: 'Категория'
                    }
                }
            }
        },
        order: [[0, 'desc']],
        columnDefs: [
            {
                targets: 2,
                searchPanes: { show: true }
            },
            {
                targets: [0, 1, 3, 4, 5],
                searchPanes: { show: false }
            },
            {
                targets: 1,
                render: {
                    filter: function (data) {
                        if (!data) return '';
                        return data.replace(/<[^>]+>/g, '');
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
            const tableElem = document.getElementById('expense-table');
            if (tableElem) {
                tableElem.classList.remove('d-none');
            }
        }
    });

    const groupSelect = document.getElementById('expense-group-select');
    if (groupSelect) {
        groupSelect.addEventListener('change', function () {
            window.expenseDataTable.ajax.reload();
        });
    }

    const toggleBtn = document.getElementById('toggle-group-filter');
    const filterBlock = document.getElementById('expense-group-filter-block');
    if (toggleBtn && filterBlock) {
        toggleBtn.addEventListener('click', function () {
            filterBlock.classList.toggle('d-none');
        });
    }
});
