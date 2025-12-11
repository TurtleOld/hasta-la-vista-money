document.addEventListener('DOMContentLoaded', function () {
    const groupSelect = document.getElementById('receipt-group-select');
    if (!groupSelect) return;

    function getGroupIdFromQuery() {
        const params = new URLSearchParams(window.location.search);
        return params.get('group_id') || 'my';
    }

    function updateGroupIdInUrl(groupId) {
        const params = new URLSearchParams(window.location.search);
        params.set('group_id', groupId);
        const newUrl = window.location.pathname + '?' + params.toString();
        window.history.pushState({}, '', newUrl);
    }

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
                    return fetch(window.location.pathname, {
                        method: 'GET',
                        credentials: 'include',
                        headers: { 'X-Requested-With': 'XMLHttpRequest' }
                    }).then(sessionResponse => {
                        if (sessionResponse.ok) {
                            return window.tokens.refreshTokensIfNeeded().then(refreshed => {
                                if (refreshed) {
                                    return fetch('/receipts/ajax/receipts_by_group/?' + params.toString(), {
                                        headers: {
                                            'X-Requested-With': 'XMLHttpRequest',
                                        },
                                        credentials: 'include'
                                    });
                                } else {
                                    throw new Error('JWT tokens expired but Django session is valid');
                                }
                            });
                        }

                        if (sessionResponse.status === 302) {
                            window.location.replace('/login/');
                            return null;
                        }

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
                        const newContent = doc.body.firstElementChild;
                        if (newContent) {
                            block.replaceWith(newContent);
                        }
                    }
                }
            })
            .catch(error => {
                if (error.message === 'JWT tokens expired but Django session is valid') {
                    console.log('JWT tokens expired, but Django session is valid');
                } else {
                    console.error('Error loading receipts:', error);
                }
            });
    }

    const currentGroupId = getGroupIdFromQuery();
    if (groupSelect.value !== currentGroupId) {
        groupSelect.value = currentGroupId;
    }

    groupSelect.addEventListener('change', function () {
        const selectedGroup = this.value;
        updateGroupIdInUrl(selectedGroup);
        loadReceiptsBlock(selectedGroup);
    });

});
