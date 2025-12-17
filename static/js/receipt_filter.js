(function() {
    'use strict';

    function initFilterCollapse() {
        const filterCollapse = document.getElementById('filterCollapse');
        const toggleButton = document.getElementById('filterToggle');
        const toggleIcon = document.getElementById('filterToggleIcon');
        
        if (!filterCollapse || !toggleButton || !toggleIcon) {
            return;
        }
        
        function updateIcon(isExpanded) {
            toggleIcon.classList.toggle('rotate-180', Boolean(isExpanded));
        }
        
        function toggleCollapse() {
            const isExpanded = !filterCollapse.classList.contains('hidden');
            
            if (isExpanded) {
                filterCollapse.classList.add('hidden');
                toggleButton.setAttribute('aria-expanded', 'false');
                updateIcon(false);
            } else {
                filterCollapse.classList.remove('hidden');
                toggleButton.setAttribute('aria-expanded', 'true');
                updateIcon(true);
            }
        }
        
        if (window.location.search.length > 1) {
            filterCollapse.classList.remove('hidden');
            toggleButton.setAttribute('aria-expanded', 'true');
            updateIcon(true);
        }
        
        toggleButton.addEventListener('click', function(e) {
            e.preventDefault();
            toggleCollapse();
        });
    }
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initFilterCollapse);
    } else {
        initFilterCollapse();
    }
})();

