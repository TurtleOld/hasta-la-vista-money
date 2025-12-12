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
            const tag = tagName.toLowerCase();
            return ALLOWED_TAGS.includes(tag) && !BLOCKED_TAGS.includes(tag);
        }

        function isUrlSafe(value) {
            if (!value || typeof value !== 'string') {
                return true;
            }
            const trimmed = value.trim();
            if (DANGEROUS_URL_PATTERN.test(trimmed)) {
                return false;
            }
            return true;
        }

        function isStyleSafe(value) {
            if (!value || typeof value !== 'string') {
                return true;
            }
            if (EXPRESSION_PATTERN.test(value)) {
                return false;
            }
            if (DANGEROUS_URL_PATTERN.test(value)) {
                return false;
            }
            if (value.includes('behavior:') || value.includes('-moz-binding')) {
                return false;
            }
            return true;
        }

        function isAttributeSafe(attrName, attrValue) {
            const name = attrName.toLowerCase();

            if (EVENT_ATTR_PATTERN.test(name)) {
                return false;
            }

            if (BLOCKED_ATTRS.some(function(blocked) { return name.includes(blocked); })) {
                return false;
            }

            if (URL_ATTRS.includes(name)) {
                if (!isUrlSafe(attrValue)) {
                    return false;
                }
            }

            if (name === 'style') {
                if (!isStyleSafe(attrValue)) {
                    return false;
                }
            }

            return true;
        }

        function sanitizeAttributeValue(attrName, attrValue) {
            if (typeof attrValue !== 'string') {
                return '';
            }

            let sanitized = attrValue
                .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
                .replace(/&#/gi, '&amp;#');

            return sanitized;
        }

        function createSafeElement(sourceElement) {
            if (!sourceElement || sourceElement.nodeType !== Node.ELEMENT_NODE) {
                return null;
            }

            const tagName = sourceElement.tagName.toLowerCase();

            if (!isTagAllowed(tagName)) {
                return null;
            }

            const safeElement = document.createElement(tagName);

            const attributes = sourceElement.attributes;
            for (let i = 0; i < attributes.length; i++) {
                const attr = attributes[i];
                const attrName = attr.name;
                const attrValue = attr.value;

                if (isAttributeSafe(attrName, attrValue)) {
                    const sanitizedValue = sanitizeAttributeValue(attrName, attrValue);
                    try {
                        safeElement.setAttribute(attrName, sanitizedValue);
                    } catch (e) {
                        // Skip invalid attributes
                    }
                }
            }

            const childNodes = sourceElement.childNodes;
            for (let i = 0; i < childNodes.length; i++) {
                const child = childNodes[i];

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

            const trimmed = htmlString.trim();
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
            isUrlSafe: isUrlSafe
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
