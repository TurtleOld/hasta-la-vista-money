document.addEventListener('DOMContentLoaded', function () {
    const groupSelect = document.getElementById('income-group-select');
    if (!groupSelect) return;

    groupSelect.addEventListener('change', function () {
        const groupId = this.value;
        const params = new URLSearchParams(window.location.search);
        params.set('group_id', groupId);

        // Обновить адресную строку
        window.history.replaceState({}, '', window.location.pathname + '?' + params.toString());

        fetch('/income/ajax/income_by_group/?' + params.toString(), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
            .then(response => response.text())
            .then(html => {
                // Destroy previous DataTable instance if exists
                if (window.incomeDataTable) {
                    window.incomeDataTable.destroy();
                }
                const block = document.getElementById('income-table-block');
                if (block) {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    const newContent = doc.body.firstElementChild;
                    if (newContent) {
                        block.replaceWith(newContent);
                        // Re-init DataTables and save instance
                        window.incomeDataTable = new DataTable('#income-table', {
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
                            order: [[0, 'desc']]
                        });
                    }
                }
            });
    });

    // Логика для показа/скрытия фильтра
    const toggleBtn = document.getElementById('toggle-group-filter');
    const filterBlock = document.getElementById('income-group-filter-block');
    if (toggleBtn && filterBlock) {
        toggleBtn.addEventListener('click', function () {
            filterBlock.classList.toggle('d-none');
        });
    }
}); 