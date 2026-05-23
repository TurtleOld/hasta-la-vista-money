(function() {
    'use strict';

    function toggleUserDropdown() {
        const menu = document.getElementById('userDropdownMenu');
        const arrow = document.getElementById('userDropdownArrow');
        const button = document.getElementById('userDropdownButton');

        if (menu && arrow && button) {
            const isHidden = menu.classList.contains('hidden');
            menu.classList.toggle('hidden');
            button.setAttribute('aria-expanded', !isHidden);

            if (isHidden) {
                arrow.style.transform = 'rotate(180deg)';
            } else {
                arrow.style.transform = 'rotate(0deg)';
            }
        }
    }

    function closeDropdownsOnOutsideClick(event) {
        const userDropdown = document.getElementById('userDropdown');

        if (userDropdown && !userDropdown.contains(event.target)) {
            const menu = document.getElementById('userDropdownMenu');
            const arrow = document.getElementById('userDropdownArrow');
            const button = document.getElementById('userDropdownButton');
            if (menu && !menu.classList.contains('hidden')) {
                menu.classList.add('hidden');
                if (arrow) arrow.style.transform = 'rotate(0deg)';
                if (button) button.setAttribute('aria-expanded', 'false');
            }
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        const userButton = document.getElementById('userDropdownButton');

        if (userButton) {
            userButton.addEventListener('click', function(e) {
                e.stopPropagation();
                toggleUserDropdown();
            });
        }

        document.addEventListener('click', closeDropdownsOnOutsideClick);
    });

    window.toggleUserDropdown = toggleUserDropdown;
})();
