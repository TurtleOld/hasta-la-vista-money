document.addEventListener('DOMContentLoaded', function () {
    var themeIcon = document.getElementById('theme-icon');
    function updateThemeIcon(theme) {
        if (!themeIcon) return;
        if (theme === 'dark') {
            themeIcon.classList.remove('bi-sun');
            themeIcon.classList.add('bi-moon');
        } else {
            themeIcon.classList.remove('bi-moon');
            themeIcon.classList.add('bi-sun');
        }
    }


    function applyTheme(theme) {
        document.body.classList.add('theme-fade');
        document.body.setAttribute('data-bs-theme', theme);
        document.documentElement.setAttribute('data-bs-theme', theme);
        if (theme === 'dark') {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }
        updateThemeIcon(theme);
        setTimeout(function() {
            document.body.classList.remove('theme-fade');
        }, 400);
    }

    var initialTheme = document.body.getAttribute('data-bs-theme') || 'light';
    applyTheme(initialTheme);

    var themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', function () {
            var currentTheme = document.body.getAttribute('data-bs-theme');
            var newTheme = currentTheme === 'dark' ? 'light' : 'dark';
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
                });
            }
        });
    }

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
});
