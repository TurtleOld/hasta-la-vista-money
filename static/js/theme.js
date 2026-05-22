(function () {
    'use strict';

    const THEME_DARK = 'dark';
    const THEME_LIGHT = 'light';
    const THEME_AUTO = 'auto';
    const THEME_SEQUENCE = [THEME_AUTO, THEME_LIGHT, THEME_DARK];

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
        if (value === THEME_DARK || value === THEME_LIGHT || value === THEME_AUTO) {
            return value;
        }
        return THEME_AUTO;
    }

    function getPreferredColorScheme() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return THEME_DARK;
        }
        return THEME_LIGHT;
    }

    function resolveTheme(theme) {
        const safeTheme = normalizeTheme(theme);
        return safeTheme === THEME_AUTO ? getPreferredColorScheme() : safeTheme;
    }

    function readThemeFromDom() {
        const rootEl = document.documentElement;
        const bodyEl = document.body;

        if (!rootEl || !bodyEl) return THEME_AUTO;

        const modeAttr = rootEl.getAttribute('data-theme-mode') || bodyEl.getAttribute('data-theme-mode');
        if (modeAttr === THEME_AUTO) return THEME_AUTO;

        const rootAttr = rootEl.getAttribute('data-bs-theme');
        const bodyAttr = bodyEl.getAttribute('data-bs-theme');
        const attr = rootAttr || bodyAttr || '';

        if (attr === THEME_DARK) return THEME_DARK;
        if (attr === THEME_LIGHT) return THEME_LIGHT;

        const hasDarkClass = rootEl.classList.contains('dark') || bodyEl.classList.contains('dark');
        return hasDarkClass ? THEME_DARK : THEME_LIGHT;
    }

    function updateThemeIcon(theme, resolvedTheme) {
        const themeIconSun = document.getElementById('theme-icon-sun');
        const themeIconMoon = document.getElementById('theme-icon-moon');
        const themeIconAuto = document.getElementById('theme-icon-auto');
        const themeLabel = document.getElementById('theme-label');

        if (!themeIconSun || !themeIconMoon) return;

        themeIconSun.classList.add('hidden');
        themeIconMoon.classList.add('hidden');
        if (themeIconAuto) themeIconAuto.classList.add('hidden');

        if (theme === THEME_AUTO && themeIconAuto) {
            themeIconAuto.classList.remove('hidden');
        } else if (resolvedTheme === THEME_DARK) {
            themeIconMoon.classList.remove('hidden');
        } else {
            themeIconSun.classList.remove('hidden');
        }

        if (themeLabel) {
            if (theme === THEME_AUTO) {
                themeLabel.textContent = resolvedTheme === THEME_DARK ? 'Авто (темная)' : 'Авто (светлая)';
            } else {
                themeLabel.textContent = resolvedTheme === THEME_DARK ? 'Темная' : 'Светлая';
            }
        }
    }

    function applyTheme(theme) {
        const rootEl = document.documentElement;
        const bodyEl = document.body;
        if (!rootEl || !bodyEl) return;

        const safeTheme = normalizeTheme(theme);
        const resolvedTheme = resolveTheme(safeTheme);

        bodyEl.classList.add('theme-fade');

        bodyEl.setAttribute('data-bs-theme', resolvedTheme);
        rootEl.setAttribute('data-bs-theme', resolvedTheme);
        rootEl.setAttribute('data-theme', resolvedTheme);
        bodyEl.setAttribute('data-theme-mode', safeTheme);
        rootEl.setAttribute('data-theme-mode', safeTheme);

        if (resolvedTheme === THEME_DARK) {
            rootEl.classList.add('dark');
            bodyEl.classList.add('dark');
        } else {
            rootEl.classList.remove('dark');
            bodyEl.classList.remove('dark');
        }

        updateThemeIcon(safeTheme, resolvedTheme);

        const forceReflow = () => bodyEl.offsetHeight;

        requestAnimationFrame(() => {
            forceReflow();
            requestAnimationFrame(() => {
                forceReflow();
                setTimeout(() => {
                    bodyEl.classList.remove('theme-fade');
                    if (resolvedTheme === THEME_DARK && !rootEl.classList.contains('dark')) {
                        rootEl.classList.add('dark');
                    }
                }, 400);
            });
        });
    }

    function saveTheme(theme) {
        if (!window.SET_THEME_URL) return;

        fetch(window.SET_THEME_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify({ theme: theme }),
        }).catch(function (error) {
            console.error('Error setting theme:', error);
        });
    }

    function initThemeToggle() {
        const themeToggle = document.getElementById('theme-toggle');
        const themeIconSun = document.getElementById('theme-icon-sun');
        const themeIconMoon = document.getElementById('theme-icon-moon');
        if (!themeToggle || !themeIconSun || !themeIconMoon) return;

        const initialTheme = readThemeFromDom();
        updateThemeIcon(initialTheme, resolveTheme(initialTheme));

        themeToggle.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();

            const currentTheme = readThemeFromDom();
            const currentIndex = THEME_SEQUENCE.indexOf(currentTheme);
            const newTheme = THEME_SEQUENCE[(currentIndex + 1) % THEME_SEQUENCE.length];

            applyTheme(newTheme);
            saveTheme(newTheme);
        });
    }

    function initSystemThemeListener() {
        if (!window.matchMedia) return;

        const colorSchemeQuery = window.matchMedia('(prefers-color-scheme: dark)');
        const handleColorSchemeChange = function () {
            if (readThemeFromDom() === THEME_AUTO) {
                applyTheme(THEME_AUTO);
            }
        };

        if (colorSchemeQuery.addEventListener) {
            colorSchemeQuery.addEventListener('change', handleColorSchemeChange);
        } else if (colorSchemeQuery.addListener) {
            colorSchemeQuery.addListener(handleColorSchemeChange);
        }
    }

    function init() {
        const rootEl = document.documentElement;
        const bodyEl = document.body;

        if (!rootEl || !bodyEl) {
            initThemeToggle();
            return;
        }

        const modeAttr = rootEl.getAttribute('data-theme-mode') || bodyEl.getAttribute('data-theme-mode');
        const rootAttr = rootEl.getAttribute('data-bs-theme');
        const bodyAttr = bodyEl.getAttribute('data-bs-theme');
        const currentAttr = rootAttr || bodyAttr;
        const hasDarkClass = rootEl.classList.contains('dark') || bodyEl.classList.contains('dark');

        let currentTheme = normalizeTheme(modeAttr || currentAttr);
        if (modeAttr === THEME_AUTO) {
            currentTheme = THEME_AUTO;
        } else if (currentAttr === THEME_DARK) {
            currentTheme = THEME_DARK;
        } else if (currentAttr === THEME_LIGHT) {
            currentTheme = THEME_LIGHT;
        } else if (hasDarkClass) {
            currentTheme = THEME_DARK;
        }

        applyTheme(currentTheme);
        initThemeToggle();
        initSystemThemeListener();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
