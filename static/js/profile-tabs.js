(function() {
    'use strict';

    function initProfileTabs() {
        const tabButtons = document.querySelectorAll('.profile-tab-button');
        const tabContents = document.querySelectorAll('.profile-tab-content');

        if (tabButtons.length === 0 || tabContents.length === 0) {
            return;
        }

        tabButtons.forEach(function(button) {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();

                const targetTabId = this.getAttribute('data-tab-target');
                if (!targetTabId) {
                    return;
                }

                const targetTab = document.getElementById(targetTabId);
                if (!targetTab) {
                    return;
                }

                tabButtons.forEach(function(btn) {
                    btn.classList.remove('active');
                    btn.setAttribute('aria-selected', 'false');
                });

                tabContents.forEach(function(content) {
                    content.classList.remove('active');
                });

                this.classList.add('active');
                this.setAttribute('aria-selected', 'true');
                targetTab.classList.add('active');
            });
        });
    }

    function init() {
        initProfileTabs();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
