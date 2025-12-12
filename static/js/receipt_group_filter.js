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

    const DANGEROUS_TAGS = ['script', 'iframe', 'object', 'embed', 'link', 'style', 'meta', 'base'];
    const DANGEROUS_ATTR_PATTERN = /^on\w+/i;
    const JAVASCRIPT_PROTOCOL = /^\s*javascript:/i;
    const SAFE_URL_ATTRS = ['href', 'src', 'action', 'formaction', 'xlink:href'];

    function isAttributeSafe(attrName, attrValue) {
        const name = attrName.toLowerCase();

        if (DANGEROUS_ATTR_PATTERN.test(name)) {
            return false;
        }

        if (SAFE_URL_ATTRS.includes(name)) {
            if (JAVASCRIPT_PROTOCOL.test(attrValue)) {
                return false;
            }
        }

        return true;
    }

    function createCleanElement(sourceElement) {
        if (!sourceElement || sourceElement.nodeType !== Node.ELEMENT_NODE) {
            return null;
        }

        const tagName = sourceElement.tagName.toLowerCase();
        if (DANGEROUS_TAGS.includes(tagName)) {
            return null;
        }

        const cleanElement = document.createElement(tagName);

        const attributes = Array.from(sourceElement.attributes);
        for (const attr of attributes) {
            if (isAttributeSafe(attr.name, attr.value)) {
                cleanElement.setAttribute(attr.name, attr.value);
            }
        }

        for (const childNode of sourceElement.childNodes) {
            if (childNode.nodeType === Node.TEXT_NODE) {
                cleanElement.appendChild(document.createTextNode(childNode.textContent || ''));
            } else if (childNode.nodeType === Node.ELEMENT_NODE) {
                const cleanChild = createCleanElement(childNode);
                if (cleanChild) {
                    cleanElement.appendChild(cleanChild);
                }
            }
        }

        return cleanElement;
    }

    function createSafeContentFromHTML(htmlContent) {
        if (!htmlContent || typeof htmlContent !== 'string' || htmlContent.length === 0) {
            return null;
        }

        if (htmlContent.length > 1000000) {
            console.error('HTML content too large');
            return null;
        }

        try {
            const template = document.createElement('template');
            template.innerHTML = htmlContent;

            const sourceElement = template.content.firstElementChild;
            if (!sourceElement) {
                return null;
            }

            return createCleanElement(sourceElement);
        } catch (error) {
            console.error('Error creating safe content:', error);
            return null;
        }
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
                const block = document.querySelector('#receipts-block');
                if (!block) {
                    return;
                }

                const safeContent = createSafeContentFromHTML(html);
                if (!safeContent) {
                    return;
                }

                block.replaceWith(safeContent);
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
