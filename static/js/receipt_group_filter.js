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
            credentials: 'include' // Включаем cookies для JWT аутентификации
        })
            .then(response => {
                if (response.status === 401) {
                    // Проверяем Django сессию перед редиректом
                    return fetch(window.location.pathname, {
                        method: 'GET',
                        credentials: 'include',
                        headers: { 'X-Requested-With': 'XMLHttpRequest' }
                    }).then(sessionResponse => {
                        if (sessionResponse.ok) {
                            // Django сессия валидна, но JWT токены истекли
                            // Попробуем обновить токены
                            return window.tokens.refreshTokensIfNeeded().then(refreshed => {
                                if (refreshed) {
                                    // Токены обновлены, повторим запрос
                                    return fetch('/receipts/ajax/receipts_by_group/?' + params.toString(), {
                                        headers: {
                                            'X-Requested-With': 'XMLHttpRequest',
                                        },
                                        credentials: 'include'
                                    });
                                } else {
                                    // Не удалось обновить токены, но Django сессия валидна
                                    throw new Error('JWT tokens expired but Django session is valid');
                                }
                            });
                        }

                        if (sessionResponse.status === 302) {
                            // Django сессия тоже истекла
                            window.location.replace('/login/');
                            return null;
                        }

                        // В случае других ошибок, предполагаем что сессия валидна
                        throw new Error('JWT tokens expired but Django session is valid');
                    });
                }
                return response.text();
            })
            .then(html => {
                if (html) {
                    const block = document.querySelector('#receipts-block');
                    if (block) {
                        const parser = new DOMParser();
                        const doc = parser.parseFromString(html, 'text/html');  // eslint-disable-line
                        // Ожидаем, что receipts_block.html — это один корневой div
                        const newContent = doc.body.firstElementChild;
                        if (newContent) {
                            block.replaceWith(newContent);
                        }
                    }
                }
            })
            .catch(error => {
                if (error.message === 'JWT tokens expired but Django session is valid') {
                    // JWT токены истекли, но Django сессия валидна
                    // Можно попробовать обновить токены или просто игнорировать ошибку
                    console.log('JWT tokens expired, but Django session is valid');
                } else {
                    console.error('Error loading receipts:', error);
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
