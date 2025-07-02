document.addEventListener('DOMContentLoaded', function () {
    const groupSelect = document.getElementById('receipt-group-select');
    if (!groupSelect) return;

    // При загрузке страницы — если есть выбранная группа в sessionStorage, выставить её и инициировать HTMX-запрос
    const savedGroup = sessionStorage.getItem('selectedReceiptGroup');
    if (savedGroup && groupSelect.value !== savedGroup) {
        groupSelect.value = savedGroup;
        groupSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // При смене селектора — сохранять в sessionStorage
    groupSelect.addEventListener('change', function () {
        sessionStorage.setItem('selectedReceiptGroup', this.value);
    });
});
