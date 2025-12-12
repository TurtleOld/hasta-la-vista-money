document.addEventListener('DOMContentLoaded', function () {
    const groupSelect = document.getElementById('receipt-group-select');
    if (!groupSelect) return;

    let isLoading = false;
    let pendingRequest = null;

    function debounce(func, delay) {
        let timeoutId;
        return function(...args) {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => func.apply(this, args), delay);
        };
    }

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
        if (isLoading) {
            pendingRequest = groupId;
            return;
        }

        isLoading = true;
        const params = new URLSearchParams(window.location.search);
        params.set('group_id', groupId);
        fetch('/api/receipts/by-group/?' + params.toString(), {
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
                                    return fetch('/api/receipts/by-group/?' + params.toString(), {
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
                if (!html || typeof html !== 'string') {
                    return;
                }

                const block = document.querySelector('#receipts-block');
                if (!block) {
                    return;
                }

                try {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    
                    const parseError = doc.querySelector('parsererror');
                    if (parseError) {
                        console.error('HTML parsing error:', parseError.textContent);
                        return;
                    }

                    const newContent = doc.body.firstElementChild;
                    if (!newContent || newContent.nodeType !== Node.ELEMENT_NODE) {
                        return;
                    }

                    const dangerousTags = ['script', 'iframe', 'object', 'embed', 'link', 'style'];
                    const dangerousAttributes = /^on\w+/i;
                    const javascriptProtocol = /^\s*javascript:/i;

                    function sanitizeElement(element) {
                        if (!element || element.nodeType !== Node.ELEMENT_NODE) {
                            return;
                        }

                        const tagName = element.tagName.toLowerCase();
                        if (dangerousTags.includes(tagName)) {
                            element.remove();
                            return;
                        }

                        const attributes = Array.from(element.attributes);
                        for (const attr of attributes) {
                            const attrName = attr.name.toLowerCase();
                            const attrValue = attr.value;

                            if (dangerousAttributes.test(attrName)) {
                                element.removeAttribute(attrName);
                                continue;
                            }

                            if (attrName === 'href' || attrName === 'src' || attrName === 'action') {
                                if (javascriptProtocol.test(attrValue)) {
                                    element.removeAttribute(attrName);
                                }
                            }
                        }

                        const children = Array.from(element.children);
                        for (const child of children) {
                            sanitizeElement(child);
                        }
                    }

                    sanitizeElement(newContent);
                    block.replaceWith(newContent);
                } catch (error) {
                    console.error('Error parsing HTML:', error);
                }
            })
            .catch(error => {
                if (error.message === 'JWT tokens expired but Django session is valid') {
                    console.log('JWT tokens expired, but Django session is valid');
                } else {
                    console.error('Error loading receipts:', error);
                }
            })
            .finally(() => {
                isLoading = false;
                if (pendingRequest) {
                    const nextGroupId = pendingRequest;
                    pendingRequest = null;
                    loadReceiptsBlock(nextGroupId);
                }
            });
    }

    const debouncedLoadReceipts = debounce(loadReceiptsBlock, 300);

    const currentGroupId = getGroupIdFromQuery();
    if (groupSelect.value !== currentGroupId) {
        groupSelect.value = currentGroupId;
    }

    groupSelect.addEventListener('change', function () {
        const selectedGroup = this.value;
        updateGroupIdInUrl(selectedGroup);
        debouncedLoadReceipts(selectedGroup);
    });

});
