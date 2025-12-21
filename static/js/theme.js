(function() {
    'use strict';

    function getCookie(name) {
        if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
            return null;
        }
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (const cookieRaw of cookies) {
                const cookie = cookieRaw.trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function updateThemeIcon(theme) {
        const themeIcon = document.getElementById('theme-icon');
        if (!themeIcon) {
            return;
        }
        if (theme === 'dark') {
            themeIcon.classList.remove('bi-sun');
            themeIcon.classList.add('bi-moon');
        } else {
            themeIcon.classList.remove('bi-moon');
            themeIcon.classList.add('bi-sun');
        }
    }

    function applyTheme(theme) {
        const html = document.querySelector('html');
        const body = document.body;

        if (!html) {
            return;
        }

        body.classList.add('theme-fade');

        body.setAttribute('data-bs-theme', theme);
        html.setAttribute('data-bs-theme', theme);

        if (theme === 'dark') {
            html.classList.add('dark');
            if (!body.classList.contains('dark')) {
                body.classList.add('dark');
            }
        } else {
            html.classList.remove('dark');
            body.classList.remove('dark');
        }

        updateThemeIcon(theme);

        const forceReflow = function() {
            return body.offsetHeight;
        };

        requestAnimationFrame(function() {
            forceReflow();
            requestAnimationFrame(function() {
                forceReflow();
                setTimeout(function() {
                    body.classList.remove('theme-fade');
                    if (theme === 'dark' && !html.classList.contains('dark')) {
                        html.classList.add('dark');
                    }
                }, 400);
            });
        });
    }

    function initThemeToggle() {
        const themeToggle = document.getElementById('theme-toggle');
        const themeIcon = document.getElementById('theme-icon');

        if (!themeToggle || !themeIcon) {
            return;
        }

        const htmlElement = document.querySelector('html');
        const initialTheme = htmlElement?.getAttribute('data-bs-theme') ||
                             document.body.getAttribute('data-bs-theme') ||
                             'light';
        updateThemeIcon(initialTheme);

        themeToggle.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();

            const htmlElement = document.querySelector('html');
            const currentTheme = htmlElement?.getAttribute('data-bs-theme') ||
                                 document.body.getAttribute('data-bs-theme') ||
                                 'light';
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            applyTheme(newTheme);

            if (window.SET_THEME_URL) {
                fetch(window.SET_THEME_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({
                        theme: newTheme
                    }),
                }).catch(function(error) {
                    console.error('Error setting theme:', error);
                });
            }
        });
    }

    function init() {
        const html = document.querySelector('html');
        const body = document.body;

        if (!html) {
            return;
        }

        const initialTheme = html.getAttribute('data-bs-theme') ||
                             body.getAttribute('data-bs-theme') ||
                             (html.classList.contains('dark') ? 'dark' : 'light');

        if (initialTheme === 'dark' && !html.classList.contains('dark')) {
            html.classList.add('dark');
            body.classList.add('dark');
        } else if (initialTheme === 'light' && html.classList.contains('dark')) {
            html.classList.remove('dark');
            body.classList.remove('dark');
        }

        applyTheme(initialTheme);
        initThemeToggle();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
