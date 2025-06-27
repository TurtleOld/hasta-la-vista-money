document.addEventListener('DOMContentLoaded', function () {
    const table = document.getElementById('income-table').querySelector('table');
    const headers = table.querySelectorAll('th.sortable');
    let sortDirection = {};

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
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr')).filter(row => row.querySelectorAll('td').length);
            const dir = sortDirection[type] === 'asc' ? 'desc' : 'asc';
            sortDirection = {}; sortDirection[type] = dir;

            // Сбросить индикаторы
            headers.forEach(h => h.querySelector('.sort-indicator').textContent = '');
            header.querySelector('.sort-indicator').textContent = dir === 'asc' ? '▲' : '▼';

            rows.sort((rowA, rowB) => {
                let cellA = rowA.querySelectorAll('td')[idx].textContent.trim();
                let cellB = rowB.querySelectorAll('td')[idx].textContent.trim();
                return compareRows(cellA, cellB, type, dir);
            });
            rows.forEach(row => tbody.appendChild(row));
        });
    });
}); 