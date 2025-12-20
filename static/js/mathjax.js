(function() {
    'use strict';

    window.MathJax = {
        tex: {
            inlineMath: [['\\(', '\\)']],
            displayMath: [['\\[', '\\]']],
            processEscapes: true,
            processEnvironments: true
        },
        options: {
            ignoreHtmlClass: 'tex2jax_ignore',
            processHtmlClass: 'tex2jax_process',
            skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
        },
        startup: {
            ready: function() {
                MathJax.startup.defaultReady();
                function initMathJax() {
                    if (typeof window.renderMathJax === 'function') {
                        window.renderMathJax();
                    }
                }
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', initMathJax);
                } else {
                    initMathJax();
                }
            }
        }
    };

    function renderMathJax(element) {
        if (typeof window.MathJax === 'undefined') {
            console.warn('MathJax is not loaded');
            return Promise.resolve();
        }

        if (!window.MathJax.typesetPromise) {
            console.warn('MathJax.typesetPromise is not available');
            return Promise.resolve();
        }

        const target = element || document.body;

        if (!target) {
            return Promise.resolve();
        }

        if (window.MathJax.typesetClear) {
            window.MathJax.typesetClear([target]);
        }

        return window.MathJax.typesetPromise([target]).catch(function(err) {
            console.error('MathJax typeset error:', err);
        });
    }

    function waitForMathJax() {
        if (typeof window.MathJax !== 'undefined' && window.MathJax.typesetPromise) {
            setTimeout(function() {
                renderMathJax();
            }, 300);
        } else {
            setTimeout(waitForMathJax, 100);
        }
    }

    function initMathJax() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', waitForMathJax);
        } else {
            waitForMathJax();
        }
    }

    window.renderMathJax = renderMathJax;
    initMathJax();
})();
