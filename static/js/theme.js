(function () {
    'use strict';

    const THEME_DARK = 'dark';
    const THEME_LIGHT = 'light';

    function getCookie(name) {
        if (!/^[a-zA-Z0-9_-]+$/.test(name)) return null;

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

    function normalizeTheme(value) {
        return value === THEME_DARK ? THEME_DARK : THEME_LIGHT;
    }

    function readThemeFromDom() {
        const rootEl = document.documentElement;
        const bodyEl = document.body;

        if (!rootEl || !bodyEl) return THEME_LIGHT;

        const rootAttr = rootEl.getAttribute('data-bs-theme');
        const bodyAttr = bodyEl.getAttribute('data-bs-theme');
        const attr = rootAttr || bodyAttr || '';

        // Явный маппинг на безопасные значения
        if (attr === THEME_DARK) return THEME_DARK;
        if (attr === THEME_LIGHT) return THEME_LIGHT;

        const hasDarkClass = rootEl.classList.contains('dark') || bodyEl.classList.contains('dark');
        return hasDarkClass ? THEME_DARK : THEME_LIGHT;
    }

    function updateThemeIcon(theme) {
        const themeIconSun = document.getElementById('theme-icon-sun');
        const themeIconMoon = document.getElementById('theme-icon-moon');

        if (!themeIconSun || !themeIconMoon) return;

        if (theme === THEME_DARK) {
            themeIconSun.classList.add('hidden');
            themeIconMoon.classList.remove('hidden');
        } else {
            themeIconSun.classList.remove('hidden');
            themeIconMoon.classList.add('hidden');
        }
    }

    function applyTheme(theme) {
        const rootEl = document.documentElement;
        const bodyEl = document.body;
        if (!rootEl || !bodyEl) return;

        const safeTheme = normalizeTheme(theme);

        bodyEl.classList.add('theme-fade');

        bodyEl.setAttribute('data-bs-theme', safeTheme);
        rootEl.setAttribute('data-bs-theme', safeTheme);
        rootEl.setAttribute('data-theme', safeTheme);

        if (safeTheme === THEME_DARK) {
            rootEl.classList.add('dark');
            bodyEl.classList.add('dark');
        } else {
            rootEl.classList.remove('dark');
            bodyEl.classList.remove('dark');
        }

        updateThemeIcon(safeTheme);

        const forceReflow = () => bodyEl.offsetHeight;

        requestAnimationFrame(() => {
            forceReflow();
            requestAnimationFrame(() => {
                forceReflow();
              setTimeout(() => {
                  bodyEl.classList.remove('theme-fade');
                  if (safeTheme === THEME_DARK && !rootEl.classList.contains('dark')) {
                      rootEl.classList.add('dark');
                  }
              }, 400);
          });
        });
    }

    function initThemeToggle() {
        const themeToggle = document.getElementById('theme-toggle');
        const themeIconSun = document.getElementById('theme-icon-sun');
        const themeIconMoon = document.getElementById('theme-icon-moon');
        if (!themeToggle || !themeIconSun || !themeIconMoon) return;

        const initialTheme = readThemeFromDom();
        updateThemeIcon(initialTheme);

        themeToggle.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();

            const currentTheme = readThemeFromDom();
            const newTheme = currentTheme === THEME_DARK ? THEME_LIGHT : THEME_DARK;

            applyTheme(newTheme);

            if (window.SET_THEME_URL) {
                fetch(window.SET_THEME_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                      'X-CSRFToken': getCookie('csrftoken'),
                  },
                  body: JSON.stringify({ theme: newTheme }),
              }).catch(function (error) {
                  console.error('Error setting theme:', error);
              });
            }
        });
    }

    function init() {
        const rootEl = document.documentElement;
        const bodyEl = document.body;

        if (!rootEl || !bodyEl) {
            initThemeToggle();
            return;
        }

        const rootAttr = rootEl.getAttribute('data-bs-theme');
        const bodyAttr = bodyEl.getAttribute('data-bs-theme');
        const currentAttr = rootAttr || bodyAttr;
        const hasDarkClass = rootEl.classList.contains('dark') || bodyEl.classList.contains('dark');

        let currentTheme = THEME_LIGHT;
        if (currentAttr === THEME_DARK) {
            currentTheme = THEME_DARK;
        } else if (currentAttr === THEME_LIGHT) {
            currentTheme = THEME_LIGHT;
        } else if (hasDarkClass) {
            currentTheme = THEME_DARK;
        }

        updateThemeIcon(currentTheme);
        initThemeToggle();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
