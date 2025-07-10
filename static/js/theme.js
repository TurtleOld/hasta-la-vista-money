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

    var initialTheme = document.body.getAttribute('data-bs-theme') || 'light';
    updateThemeIcon(initialTheme);

    document.getElementById('theme-toggle').addEventListener('click', function () {
        var currentTheme = document.body.getAttribute('data-bs-theme');
        var newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.body.classList.add('theme-fade');
        document.body.setAttribute('data-bs-theme', newTheme);
        updateThemeIcon(newTheme);
        setTimeout(function() {
            document.body.classList.remove('theme-fade');
        }, 400);
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
    });

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
