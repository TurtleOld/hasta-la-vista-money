document.addEventListener('DOMContentLoaded', function () {
    const table = document.getElementById('income-table');
    if (!table) return;

    const headers = table.querySelectorAll('th.sortable');
    let sortDirection = {};

    const validSortTypes = ['amount', 'date', 'category', 'account'];

    function isValidSortType(type) {
        return validSortTypes.includes(type);
    }

    function compareRows(a, b, type, dir) {
        let valA = a, valB = b;
        if (type === 'amount') {
            valA = parseFloat(a.replace(/\s/g, '').replace(',', '.'));
            valB = parseFloat(b.replace(/\s/g, '').replace(',', '.'));
        } else if (type === 'date') {
            // Ожидается формат "Месяц Год" или ISO
            valA = Date.parse(a) || a;
            valB = Date.parse(b) || b;
        } else {
            valA = a.toLowerCase();
            valB = b.toLowerCase();
        }
        if (valA < valB) return dir === 'asc' ? -1 : 1;
        if (valA > valB) return dir === 'asc' ? 1 : -1;
        return 0;
    }

    headers.forEach((header, idx) => {
        header.addEventListener('click', function () {
            const type = header.getAttribute('data-sort');

            // Валидация типа сортировки
            if (!isValidSortType(type)) {
                console.warn('Invalid sort type:', type);
                return;
            }

            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr')).filter(row => row.querySelectorAll('td').length);
            const dir = sortDirection[type] === 'asc' ? 'desc' : 'asc';
            sortDirection = {};
            sortDirection[type] = dir;

            // Сбросить индикаторы
            headers.forEach(h => h.querySelector('.sort-indicator').textContent = '');
            header.querySelector('.sort-indicator').textContent = dir === 'asc' ? '▲' : '▼';

            rows.sort((rowA, rowB) => {
                const cellsA = rowA.querySelectorAll('td');
                const cellsB = rowB.querySelectorAll('td');

                // Проверка валидности индекса
                if (idx >= cellsA.length || idx >= cellsB.length) {
                    return 0;
                }

                let cellA = cellsA[idx].textContent.trim();
                let cellB = cellsB[idx].textContent.trim();
                return compareRows(cellA, cellB, type, dir);
            });
            rows.forEach(row => tbody.appendChild(row));
        });
    });

    new DataTable('#income-table', {
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
});
