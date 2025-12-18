(function() {
    'use strict';

    const loadedScripts = new Set();
    const loadingScripts = new Map();

    function debounce(func, delay) {
        let timeoutId;
        return function(...args) {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => func.apply(this, args), delay);
        };
    }

    function createIntersectionObserver(callback, options = {}) {
        if (!('IntersectionObserver' in window)) {
            return null;
        }

        const defaultOptions = {
            root: null,
            rootMargin: '50px',
            threshold: 0.01,
            ...options
        };

        return new IntersectionObserver(callback, defaultOptions);
    }

    function loadScript(src, options = {}) {
        if (loadedScripts.has(src)) {
            return Promise.resolve();
        }

        if (loadingScripts.has(src)) {
            return loadingScripts.get(src);
        }

        const promise = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            const nonceValue = options.nonce && options.nonce.trim() ? options.nonce.trim() : null;

            if (nonceValue) {
                script.setAttribute('nonce', nonceValue);
            }

            script.src = src;
            script.async = options.async !== false;
            script.defer = options.defer !== false;

            if (nonceValue) {
                script.nonce = nonceValue;
            }

            script.onload = () => {
                loadedScripts.add(src);
                loadingScripts.delete(src);
                resolve();
            };

            script.onerror = (error) => {
                loadingScripts.delete(src);
                reject(new Error(`Failed to load script: ${src}`));
            };

            const target = options.target || document.head || document.body;
            if (nonceValue && !script.hasAttribute('nonce')) {
                script.setAttribute('nonce', nonceValue);
            }
            target.appendChild(script);
        });

        loadingScripts.set(src, promise);
        return promise;
    }

    function loadScriptWhenVisible(selector, scriptSrc, options = {}) {
        const elements = document.querySelectorAll(selector);
        if (elements.length === 0) {
            return Promise.resolve();
        }

        const observer = createIntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    observer.unobserve(entry.target);
                    loadScript(scriptSrc, options).catch(error => {
                        console.error('Error loading script:', error);
                    });
                }
            });
        }, options.observerOptions);

        elements.forEach(element => {
            observer.observe(element);
        });

        return Promise.resolve();
    }

    function loadScriptOnPathMatch(pathPattern, scriptSrc, options = {}) {
        const currentPath = window.location.pathname;
        
        if (typeof pathPattern === 'string') {
            if (currentPath.includes(pathPattern)) {
                return loadScript(scriptSrc, options);
            }
        } else if (pathPattern instanceof RegExp) {
            if (pathPattern.test(currentPath)) {
                return loadScript(scriptSrc, options);
            }
        }

        return Promise.resolve();
    }

    function loadScriptOnInteraction(elementSelector, scriptSrc, options = {}) {
        const elements = document.querySelectorAll(elementSelector);
        if (elements.length === 0) {
            return Promise.resolve();
        }

        const loadHandler = debounce(() => {
            loadScript(scriptSrc, options).then(() => {
                elements.forEach(el => {
                    el.removeEventListener('mouseenter', loadHandler);
                    el.removeEventListener('touchstart', loadHandler, { passive: true });
                });
            }).catch(error => {
                console.error('Error loading script:', error);
            });
        }, options.debounceDelay || 200);

        elements.forEach(element => {
            element.addEventListener('mouseenter', loadHandler, { once: true, passive: true });
            element.addEventListener('touchstart', loadHandler, { once: true, passive: true });
        });

        return Promise.resolve();
    }

    const LazyLoader = {
        loadScript,
        loadScriptWhenVisible,
        loadScriptOnPathMatch,
        loadScriptOnInteraction,
        isLoaded: (src) => loadedScripts.has(src),
        isLoading: (src) => loadingScripts.has(src)
    };

    if (typeof window !== 'undefined') {
        window.LazyLoader = LazyLoader;
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = LazyLoader;
    }
})();

