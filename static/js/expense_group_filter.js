document.addEventListener('DOMContentLoaded', function () {
    const groupSelect = document.getElementById('expense-group-select');
    if (groupSelect) {
        const params = new URLSearchParams(window.location.search);
        let groupId = params.get('group_id');
        function fetchExpenseTable(currentGroupId) {
            params.set('group_id', currentGroupId);
            window.history.replaceState({}, '', window.location.pathname + '?' + params.toString());
            fetch('/expense/ajax/expense_by_group/?' + params.toString(), {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
                .then(response => response.text())
                .then(html => {
                    if (window.expenseDataTable) {
                        window.expenseDataTable.destroy();
                        window.expenseDataTable = null;
                    }
                    const block = document.getElementById('expense-table-block');
                    if (block) {
                        const parser = new DOMParser();
                        const doc = parser.parseFromString(html, 'text/html');
                        const newContent = doc.body.firstElementChild;
                        if (newContent) {
                            // Добавляем d-none к новой таблице перед вставкой (только для AJAX)
                            const ajaxTable = newContent.querySelector('#expense-table');
                            if (ajaxTable) {
                                ajaxTable.classList.add('d-none');
                            }
                            block.innerHTML = '';
                            block.appendChild(newContent);
                            setTimeout(() => {
                                window.expenseDataTable = new DataTable('#expense-table', {
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
                                        }
                                    },
                                    order: [[0, 'desc']],
                                    autoWidth: false
                                });
                                const table = document.getElementById('expense-table');
                                if (table) {
                                    table.classList.remove('d-none');
                                    setTimeout(() => {
                                        if (window.expenseDataTable) {
                                            window.expenseDataTable.columns.adjust().draw();
                                        }
                                    }, 50);
                                }
                            }, 100);
                        }
                    }
                });
        }
        if (!groupId) {
            groupId = 'my';
            setTimeout(() => {
                if (!window.expenseDataTable && document.getElementById('expense-table')) {
                    if (window.expenseDataTable) {
                        window.expenseDataTable.destroy();
                        window.expenseDataTable = null;
                    }
                    window.expenseDataTable = new DataTable('#expense-table', {
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
                            }
                        },
                        order: [[0, 'desc']],
                        autoWidth: false
                    });
                    const table = document.getElementById('expense-table');
                    if (table) {
                        table.classList.remove('d-none');
                        setTimeout(() => {
                            if (window.expenseDataTable) {
                                window.expenseDataTable.columns.adjust().draw();
                            }
                        }, 50);
                    }
                }
            }, 100);
        } else {
            if (groupSelect.value !== groupId) {
                groupSelect.value = groupId;
            }
            // Если group_id есть и не 'my', подгружаем таблицу через AJAX
            if (groupId !== 'my') {
                fetchExpenseTable(groupId);
            }
        }
        groupSelect.addEventListener('change', function () {
            const groupId = this.value;
            fetchExpenseTable(groupId);
        });
    }
    // Логика для показа/скрытия фильтра
    const toggleBtn = document.getElementById('toggle-group-filter');
    const filterBlock = document.getElementById('expense-group-filter-block');
    if (toggleBtn && filterBlock) {
        toggleBtn.addEventListener('click', function () {
            filterBlock.classList.toggle('d-none');
        });
    }
}); 