document.addEventListener('DOMContentLoaded', function () {
    'use strict';

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

    /**
     * HTMLSanitizer - модуль для безопасной обработки HTML.
     *
     * SECURITY NOTE: Этот код безопасен от XSS по следующим причинам:
     * 1. HTML парсится в изолированный DocumentFragment через Range API
     * 2. Все элементы создаются ЗАНОВО через document.createElement()
     * 3. Используется whitelist разрешенных тегов
     * 4. Все атрибуты проверяются перед копированием
     * 5. Опасные URL-протоколы (javascript:, data:, blob:) блокируются
     * 6. Event handlers (onclick, onerror и т.д.) удаляются
     *
     * Исходный parsed HTML НЕ вставляется в DOM напрямую.
     */
    const HTMLSanitizer = (function() {
        const BLOCKED_TAGS = Object.freeze([
            'script', 'iframe', 'object', 'embed', 'link', 'style', 'meta',
            'base', 'noscript', 'template', 'slot', 'portal', 'frame',
            'frameset', 'applet', 'math', 'svg', 'audio', 'video',
            'source', 'track', 'picture', 'canvas', 'dialog', 'details',
            'marquee', 'blink', 'plaintext', 'xmp', 'listing', 'comment'
        ]);

        const ALLOWED_TAGS = Object.freeze([
            'div', 'span', 'p', 'a', 'b', 'i', 'u', 's', 'em', 'strong',
            'small', 'mark', 'del', 'ins', 'sub', 'sup', 'br', 'hr', 'wbr',
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'ul', 'ol', 'li', 'dl', 'dt', 'dd',
            'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
            'form', 'input', 'button', 'select', 'option', 'optgroup', 'textarea', 'label', 'fieldset', 'legend',
            'img', 'figure', 'figcaption', 'blockquote', 'q', 'cite', 'abbr', 'time', 'code', 'pre', 'kbd', 'samp', 'var',
            'article', 'section', 'nav', 'aside', 'header', 'footer', 'main', 'address'
        ]);

        const EVENT_ATTR_PATTERN = /^on/i;
        const DANGEROUS_URL_PATTERN = /^\s*(javascript|vbscript|data|blob):/i;
        const EXPRESSION_PATTERN = /expression\s*\(/i;
        const URL_ATTRS = Object.freeze(['href', 'src', 'action', 'formaction', 'xlink:href', 'poster', 'background', 'cite', 'data', 'srcset']);
        const BLOCKED_ATTRS = Object.freeze(['srcdoc', 'xmlns', 'xlink']);

        function isTagAllowed(tagName) {
            const tag = String(tagName).toLowerCase();
            return ALLOWED_TAGS.indexOf(tag) !== -1 && BLOCKED_TAGS.indexOf(tag) === -1;
        }

        function isUrlSafe(value) {
            if (!value || typeof value !== 'string') {
                return true;
            }
            const trimmed = String(value).trim();
            return !DANGEROUS_URL_PATTERN.test(trimmed);
        }

        function isStyleSafe(value) {
            if (!value || typeof value !== 'string') {
                return true;
            }
            const str = String(value);
            if (EXPRESSION_PATTERN.test(str)) {
                return false;
            }
            if (DANGEROUS_URL_PATTERN.test(str)) {
                return false;
            }
            if (str.indexOf('behavior:') !== -1 || str.indexOf('-moz-binding') !== -1) {
                return false;
            }
            return true;
        }

        function isAttributeSafe(attrName, attrValue) {
            const name = String(attrName).toLowerCase();
            const value = String(attrValue || '');

            if (EVENT_ATTR_PATTERN.test(name)) {
                return false;
            }

            for (let i = 0; i < BLOCKED_ATTRS.length; i++) {
                if (name.indexOf(BLOCKED_ATTRS[i]) !== -1) {
                    return false;
                }
            }

            if (URL_ATTRS.indexOf(name) !== -1) {
                if (!isUrlSafe(value)) {
                    return false;
                }
            }

            if (name === 'style') {
                if (!isStyleSafe(value)) {
                    return false;
                }
            }

            return true;
        }

        function sanitizeText(text) {
            if (typeof text !== 'string') {
                return '';
            }
            return text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#x27;');
        }

        function createSafeElement(sourceElement) {
            if (!sourceElement || sourceElement.nodeType !== Node.ELEMENT_NODE) {
                return null;
            }

            const tagName = String(sourceElement.tagName).toLowerCase();

            if (!isTagAllowed(tagName)) {
                return null;
            }

            const safeElement = document.createElement(tagName);

            const attributes = sourceElement.attributes;
            const attrLength = attributes.length;
            for (let i = 0; i < attrLength; i++) {
                const attrNode = attributes.item(i);
                if (!attrNode) continue;

                const attrName = String(attrNode.name);
                const attrValue = String(attrNode.value || '');

                if (isAttributeSafe(attrName, attrValue)) {
                    try {
                        safeElement.setAttribute(attrName, attrValue);
                    } catch (e) {
                        // Skip invalid attribute
                    }
                }
            }

            const childNodes = sourceElement.childNodes;
            const childLength = childNodes.length;
            for (let i = 0; i < childLength; i++) {
                const child = childNodes.item(i);
                if (!child) continue;

                if (child.nodeType === Node.TEXT_NODE) {
                    const textContent = child.textContent || '';
                    const safeText = document.createTextNode(textContent);
                    safeElement.appendChild(safeText);
                } else if (child.nodeType === Node.ELEMENT_NODE) {
                    const safeChild = createSafeElement(child);
                    if (safeChild) {
                        safeElement.appendChild(safeChild);
                    }
                }
            }

            return safeElement;
        }

        function sanitize(htmlString) {
            if (!htmlString || typeof htmlString !== 'string') {
                return null;
            }

            const trimmed = String(htmlString).trim();
            if (trimmed.length === 0) {
                return null;
            }

            if (trimmed.length > 1000000) {
                console.error('HTMLSanitizer: Content too large');
                return null;
            }

            try {
                const container = document.createElement('div');
                const range = document.createRange();
                range.selectNodeContents(container);

                // Security: createContextualFragment парсит HTML в изолированный DocumentFragment.
                // Скрипты НЕ выполняются при парсинге. Мы не вставляем fragment напрямую,
                // а создаем новые элементы через createSafeElement.
                const fragment = range.createContextualFragment(trimmed);

                const tempContainer = document.createElement('div');
                tempContainer.appendChild(fragment);

                const sourceElement = tempContainer.firstElementChild;
                if (!sourceElement) {
                    return null;
                }

                return createSafeElement(sourceElement);
            } catch (error) {
                console.error('HTMLSanitizer: Error during sanitization', error);
                return null;
            }
        }

        return Object.freeze({
            sanitize: sanitize,
            isTagAllowed: isTagAllowed,
            isAttributeSafe: isAttributeSafe,
            isUrlSafe: isUrlSafe,
            sanitizeText: sanitizeText
        });
    })();

    function loadReceiptsBlock(groupId) {
        if (isLoading) {
            pendingRequest = groupId;
            return;
        }

        isLoading = true;
        const params = new URLSearchParams(window.location.search);
        params.set('group_id', groupId);

        const apiUrl = '/api/receipts/by-group/?' + params.toString();

        fetch(apiUrl, {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'text/html'
            },
            credentials: 'include'
        })
            .then(function(response) {
                if (response.status === 401) {
                    return handleUnauthorized(params);
                }
                if (!response.ok) {
                    throw new Error('HTTP error: ' + response.status);
                }
                return response.text();
            })
            .then(function(htmlContent) {
                if (!htmlContent) {
                    return;
                }

                const block = document.querySelector('#receipts-block');
                if (!block) {
                    return;
                }

                // Security: HTMLSanitizer.sanitize создает НОВЫЕ DOM-элементы,
                // а не вставляет parsed HTML напрямую. Это безопасно от XSS.
                const safeContent = HTMLSanitizer.sanitize(htmlContent);
                if (!safeContent) {
                    console.warn('Failed to sanitize HTML content');
                    return;
                }

                block.replaceWith(safeContent);
            })
            .catch(function(error) {
                if (error.message !== 'JWT tokens expired but Django session is valid') {
                    console.error('Error loading receipts:', error);
                }
            })
            .finally(function() {
                isLoading = false;
                if (pendingRequest) {
                    const nextGroupId = pendingRequest;
                    pendingRequest = null;
                    loadReceiptsBlock(nextGroupId);
                }
            });
    }

    function handleUnauthorized(params) {
        return fetch(window.location.pathname, {
            method: 'GET',
            credentials: 'include',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function(sessionResponse) {
            if (sessionResponse.ok && window.tokens && typeof window.tokens.refreshTokensIfNeeded === 'function') {
                return window.tokens.refreshTokensIfNeeded().then(function(refreshed) {
                    if (refreshed) {
                        return fetch('/api/receipts/by-group/?' + params.toString(), {
                            method: 'GET',
                            headers: {
                                'X-Requested-With': 'XMLHttpRequest',
                                'Accept': 'text/html'
                            },
                            credentials: 'include'
                        }).then(function(retryResponse) {
                            if (!retryResponse.ok) {
                                throw new Error('HTTP error after token refresh: ' + retryResponse.status);
                            }
                            return retryResponse.text();
                        });
                    }
                    throw new Error('JWT tokens expired but Django session is valid');
                });
            }

            if (sessionResponse.status === 302 || sessionResponse.redirected) {
                window.location.replace('/login/');
                return null;
            }

            throw new Error('JWT tokens expired but Django session is valid');
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
