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

        const attr =
            rootEl.getAttribute('data-bs-theme') ||
            bodyEl.getAttribute('data-bs-theme') ||
            '';

        // Явный маппинг на безопасные значения
        if (attr === THEME_DARK) return THEME_DARK;
        if (attr === THEME_LIGHT) return THEME_LIGHT;

        const hasDarkClass = rootEl.classList.contains('dark') || bodyEl.classList.contains('dark');
        return hasDarkClass ? THEME_DARK : THEME_LIGHT;
    }

    function updateThemeIcon(theme) {
        const themeIcon = document.getElementById('theme-icon');
        if (!themeIcon) return;

        if (theme === THEME_DARK) {
            themeIcon.classList.remove('bi-sun');
            themeIcon.classList.add('bi-moon');
        } else {
            themeIcon.classList.remove('bi-moon');
            themeIcon.classList.add('bi-sun');
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
        const themeIcon = document.getElementById('theme-icon');
        if (!themeToggle || !themeIcon) return;

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
        const initialTheme = readThemeFromDom();
        applyTheme(initialTheme);
        initThemeToggle();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
