document.addEventListener('DOMContentLoaded', function () {
    function getGroupId() {
        const groupSelect = document.getElementById('income-group-select');
        return groupSelect ? groupSelect.value : 'my';
    }

    // Инициализация DataTable только один раз
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
        columns: [
            { title: "Дата" },
            { title: "Сумма" },
            { title: "Категория" },
            { title: "Счёт" },
            { title: "" }
        ],
        columnDefs: [
            {
                targets: 2, // Категория
                searchPanes: { show: true }
            },
            {
                targets: [0, 1, 3, 4],
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
        ]
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
