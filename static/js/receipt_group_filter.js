document.addEventListener('DOMContentLoaded', function () {
    const groupSelect = document.getElementById('receipt-group-select');
    if (!groupSelect) return;

    // Функция для получения значения group_id из query-параметров
    function getGroupIdFromQuery() {
        const params = new URLSearchParams(window.location.search);
        return params.get('group_id') || 'my';
    }

    // Функция для обновления query-параметра group_id в URL
    function updateGroupIdInUrl(groupId) {
        const params = new URLSearchParams(window.location.search);
        params.set('group_id', groupId);
        const newUrl = window.location.pathname + '?' + params.toString();
        window.history.pushState({}, '', newUrl);
    }

    // Функция для подгрузки чеков через AJAX
    function loadReceiptsBlock(groupId) {
        const params = new URLSearchParams(window.location.search);
        params.set('group_id', groupId);
        fetch('/receipts/ajax/receipts_by_group/?' + params.toString(), {
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
            },
        })
            .then(response => response.text())
            .then(html => {
                const block = document.querySelector('#receipts-block');
                if (block) {
                    // Безопасная вставка: парсим HTML и заменяем блок
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    // Ожидаем, что receipts_block.html — это один корневой div
                    const newContent = doc.body.firstElementChild;
                    if (newContent) {
                        block.replaceWith(newContent);
                    }
                }
            });
    }

    // При загрузке страницы выставить селектор по query-параметру
    const currentGroupId = getGroupIdFromQuery();
    if (groupSelect.value !== currentGroupId) {
        groupSelect.value = currentGroupId;
    }

    // При смене селектора — обновлять URL и подгружать чеки
    groupSelect.addEventListener('change', function () {
        const selectedGroup = this.value;
        updateGroupIdInUrl(selectedGroup);
        loadReceiptsBlock(selectedGroup);
    });

    // Если нужно, можно подгрузить чеки при первой загрузке (если блок пустой)
    // loadReceiptsBlock(currentGroupId);
});
