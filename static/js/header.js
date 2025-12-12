(function() {
    'use strict';

    function toggleFinanceDropdown() {
        const menu = document.getElementById('financeDropdownMenu');
        const arrow = document.getElementById('financeDropdownArrow');
        const button = document.getElementById('financeDropdownButton');
        
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
        const financeDropdown = document.getElementById('financeDropdown');
        const userDropdown = document.getElementById('userDropdown');
        
        if (financeDropdown && !financeDropdown.contains(event.target)) {
            const menu = document.getElementById('financeDropdownMenu');
            const arrow = document.getElementById('financeDropdownArrow');
            const button = document.getElementById('financeDropdownButton');
            if (menu && !menu.classList.contains('hidden')) {
                menu.classList.add('hidden');
                if (arrow) arrow.style.transform = 'rotate(0deg)';
                if (button) button.setAttribute('aria-expanded', 'false');
            }
        }
        
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
        const financeButton = document.getElementById('financeDropdownButton');
        const userButton = document.getElementById('userDropdownButton');
        
        if (financeButton) {
            financeButton.addEventListener('click', function(e) {
                e.stopPropagation();
                toggleFinanceDropdown();
            });
        }
        
        if (userButton) {
            userButton.addEventListener('click', function(e) {
                e.stopPropagation();
                toggleUserDropdown();
            });
        }
        
        document.addEventListener('click', closeDropdownsOnOutsideClick);
    });

    window.toggleFinanceDropdown = toggleFinanceDropdown;
    window.toggleUserDropdown = toggleUserDropdown;
})();

